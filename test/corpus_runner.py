#!/usr/bin/env python3
"""Corpus test runner for leta.

A general-purpose command line testing tool.

Test suites are directories containing *.txt test files. Tests within a suite
run sequentially, but suites run in parallel.

Special files:
  - _setup.txt: Runs first in a suite (for workspace setup, etc.)
  - fixture/: If present, copied to temp dir; $FIXTURE_DIR env var set

Usage:
    python -m test.corpus_runner                    # Run all tests
    python -m test.corpus_runner languages/python   # Run Python tests only
    python -m test.corpus_runner languages/python/grep  # Run specific test
    python -m test.corpus_runner --update           # Update expected outputs
    python -m test.corpus_runner --list             # List all tests
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
from threading import Thread

CORPUS_DIR = Path(__file__).parent / "corpus"


@dataclass
class CorpusTest:
    name: str
    command: str
    expected_output: str
    file_path: Path
    start_line: int
    end_line: int


@dataclass
class TestResult:
    test: CorpusTest
    passed: bool
    actual_output: str | None = None
    error: str | None = None
    elapsed: float = 0.0
    suite: str = ""


@dataclass
class FileResult:
    file_path: Path
    results: list[TestResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)


@dataclass
class SuiteResult:
    suite: str
    file_results: list[FileResult] = field(default_factory=list)
    setup_error: str | None = None
    elapsed: float = 0.0

    @property
    def passed(self) -> bool:
        return self.setup_error is None and all(f.passed for f in self.file_results)

    @property
    def total_tests(self) -> int:
        return sum(len(f.results) for f in self.file_results)

    @property
    def passed_tests(self) -> int:
        return sum(1 for f in self.file_results for r in f.results if r.passed)


class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    @classmethod
    def disable(cls) -> None:
        cls.GREEN = ""
        cls.RED = ""
        cls.YELLOW = ""
        cls.CYAN = ""
        cls.BOLD = ""
        cls.DIM = ""
        cls.RESET = ""


progress_queue: Queue | None = None


def parse_corpus_file(path: Path) -> list[CorpusTest]:
    """Parse a corpus test file into individual tests."""
    content = path.read_text()
    tests = []

    pattern = re.compile(
        r"^(={3,})\n"
        r"(.+?)\n"
        r"\1\n"
        r"(.+?)\n"
        r"(-{3,})\n"
        r"(.*?)"
        r"(?=\n={3,}\n|\Z)",
        re.MULTILINE | re.DOTALL,
    )

    for match in pattern.finditer(content):
        name = match.group(2).strip()
        command = match.group(3).strip()
        expected = match.group(5).rstrip("\n")

        start_line = content[: match.start()].count("\n") + 1
        end_line = content[: match.end()].count("\n") + 1

        tests.append(
            CorpusTest(
                name=name,
                command=command,
                expected_output=expected,
                file_path=path,
                start_line=start_line,
                end_line=end_line,
            )
        )

    return tests


def discover_suites(base_dir: Path) -> list[Path]:
    """Discover all test suites (directories with *.txt files)."""
    suites = []
    for path in sorted(base_dir.rglob("*.txt")):
        if path.name.startswith("_"):
            continue
        suite_dir = path.parent
        if suite_dir not in suites:
            suites.append(suite_dir)
    return suites


def run_command(command: str, work_dir: Path, env: dict[str, str] | None = None) -> tuple[str, int]:
    """Run a shell command and return (output, return_code)."""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    
    result = subprocess.run(
        command,
        shell=True,
        cwd=work_dir,
        capture_output=True,
        text=True,
        timeout=60,
        env=full_env,
    )
    output = result.stdout + result.stderr
    return output.rstrip("\n"), result.returncode


def run_test(test: CorpusTest, work_dir: Path, suite: str, env: dict[str, str] | None = None, check_exit_only: bool = False) -> TestResult:
    """Run a single test and return the result."""
    start = time.time()
    try:
        actual_output, exit_code = run_command(test.command, work_dir, env)
        elapsed = time.time() - start

        if check_exit_only:
            passed = exit_code == 0
        else:
            passed = actual_output == test.expected_output
        
        if passed:
            result = TestResult(test=test, passed=True, actual_output=actual_output, elapsed=elapsed, suite=suite)
        else:
            result = TestResult(test=test, passed=False, actual_output=actual_output, elapsed=elapsed, suite=suite)
    except subprocess.TimeoutExpired:
        result = TestResult(test=test, passed=False, error="Command timed out", elapsed=time.time() - start, suite=suite)
    except Exception as e:
        result = TestResult(test=test, passed=False, error=str(e), elapsed=time.time() - start, suite=suite)
    
    if progress_queue:
        progress_queue.put(("test", result))
    
    return result


def run_corpus_file(file_path: Path, work_dir: Path, suite: str, env: dict[str, str] | None = None, check_exit_only: bool = False) -> FileResult:
    """Run all tests in a corpus file."""
    file_result = FileResult(file_path=file_path)
    tests = parse_corpus_file(file_path)

    for test in tests:
        result = run_test(test, work_dir, suite, env, check_exit_only)
        file_result.results.append(result)

    return file_result


def run_suite(suite_dir: Path, filter_pattern: str | None = None) -> SuiteResult:
    """Run all corpus tests in a suite directory."""
    start_time = time.time()
    suite_name = str(suite_dir.relative_to(CORPUS_DIR))
    result = SuiteResult(suite=suite_name)
    
    fixture_dir = suite_dir / "fixture"
    temp_dir = None
    env: dict[str, str] = {}
    
    try:
        # Set up temp directory and copy fixture if present
        if fixture_dir.exists():
            temp_dir = Path(tempfile.mkdtemp(prefix=f"leta_corpus_{suite_name.replace('/', '_')}_")).resolve()
            shutil.copytree(fixture_dir, temp_dir, dirs_exist_ok=True)
            work_dir = temp_dir
            env["FIXTURE_DIR"] = str(temp_dir)
        else:
            work_dir = suite_dir
        
        # Run _setup.txt first if it exists (only check exit code, not output)
        setup_file = suite_dir / "_setup.txt"
        if setup_file.exists():
            file_result = run_corpus_file(setup_file, work_dir, suite_name, env, check_exit_only=True)
            result.file_results.append(file_result)
            if not file_result.passed:
                result.setup_error = "Setup failed"
                result.elapsed = time.time() - start_time
                return result
        
        # Run all other test files
        corpus_files = sorted(f for f in suite_dir.glob("*.txt") if not f.name.startswith("_"))
        
        for corpus_file in corpus_files:
            if filter_pattern and filter_pattern not in corpus_file.stem:
                continue
            file_result = run_corpus_file(corpus_file, work_dir, suite_name, env)
            result.file_results.append(file_result)
        
        result.elapsed = time.time() - start_time
        return result
    
    finally:
        if temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def progress_printer_thread(queue: Queue, verbose: bool, stop_event: threading.Event) -> None:
    """Thread that prints progress updates from the queue."""
    dot_count = 0
    
    while not stop_event.is_set() or not queue.empty():
        try:
            msg = queue.get(timeout=0.1)
        except Empty:
            continue
        
        if msg[0] == "test":
            result = msg[1]
            if verbose:
                status = f"{Colors.GREEN}✓{Colors.RESET}" if result.passed else f"{Colors.RED}✗{Colors.RESET}"
                time_str = f"{Colors.DIM}{result.elapsed:.2f}s{Colors.RESET}"
                print(f"{status} {result.suite}/{result.test.file_path.stem}: {result.test.name} {time_str}")
                sys.stdout.flush()
            else:
                if result.passed:
                    print(f"{Colors.GREEN}.{Colors.RESET}", end="", flush=True)
                else:
                    print(f"{Colors.RED}F{Colors.RESET}", end="", flush=True)
                dot_count += 1
                if dot_count >= 80:
                    print()
                    dot_count = 0
        elif msg[0] == "skip":
            suite, reason = msg[1], msg[2]
            if verbose:
                print(f"{Colors.YELLOW}S{Colors.RESET} {suite}: {reason}")
            else:
                print(f"{Colors.YELLOW}S{Colors.RESET}", end="", flush=True)
                dot_count += 1
    
    if not verbose and dot_count > 0:
        print()


def update_corpus_file(file_path: Path, results: list[TestResult]) -> None:
    """Update expected outputs in a corpus file."""
    content = file_path.read_text()
    lines = content.split("\n")

    for result in results:
        if result.passed or result.actual_output is None:
            continue

        test = result.test
        in_expected = False
        expected_start = -1
        expected_end = -1

        for i, line in enumerate(lines):
            if i + 1 == test.start_line:
                pass
            if i >= test.start_line and re.match(r"^-{3,}$", line):
                expected_start = i + 1
                in_expected = True
            elif in_expected:
                if re.match(r"^={3,}$", line) or i >= len(lines) - 1:
                    expected_end = i if re.match(r"^={3,}$", line) else i + 1
                    break

        if expected_start > 0:
            new_lines = (
                lines[:expected_start]
                + result.actual_output.split("\n")
                + ([""] if expected_end < len(lines) and lines[expected_end - 1] != "" else [])
                + lines[expected_end:]
            )
            lines = new_lines

    file_path.write_text("\n".join(lines))


def print_diff(expected: str, actual: str) -> None:
    """Print a colored diff between expected and actual output."""
    import difflib

    diff = list(
        difflib.unified_diff(
            expected.splitlines(keepends=True),
            actual.splitlines(keepends=True),
            fromfile="expected",
            tofile="actual",
        )
    )

    for line in diff:
        if line.startswith("+") and not line.startswith("+++"):
            print(f"{Colors.GREEN}{line.rstrip()}{Colors.RESET}")
        elif line.startswith("-") and not line.startswith("---"):
            print(f"{Colors.RED}{line.rstrip()}{Colors.RESET}")
        elif line.startswith("@@"):
            print(f"{Colors.CYAN}{line.rstrip()}{Colors.RESET}")
        else:
            print(line.rstrip())


def print_results(results: list[SuiteResult], elapsed: float) -> None:
    """Print test results."""
    total_passed = 0
    total_failed = 0
    total_skipped = 0
    failed_tests: list[TestResult] = []

    for suite_result in sorted(results, key=lambda r: r.suite):
        if suite_result.setup_error:
            print(f"{Colors.YELLOW}⊘ {suite_result.suite}{Colors.RESET}: {suite_result.setup_error}")
            total_skipped += 1
            continue

        suite_passed = suite_result.passed_tests
        suite_total = suite_result.total_tests
        suite_time = f" in {suite_result.elapsed:.2f}s"

        total_passed += suite_passed
        total_failed += suite_total - suite_passed

        if suite_result.passed:
            print(f"{Colors.GREEN}✓ {suite_result.suite}{Colors.RESET}: {suite_passed}/{suite_total} tests passed{suite_time}")
        else:
            print(f"{Colors.RED}✗ {suite_result.suite}{Colors.RESET}: {suite_passed}/{suite_total} tests passed{suite_time}")
            for file_result in suite_result.file_results:
                for result in file_result.results:
                    if not result.passed:
                        failed_tests.append(result)

    if failed_tests:
        print(f"\n{Colors.RED}{Colors.BOLD}Failures:{Colors.RESET}")
        for result in failed_tests:
            file_name = result.test.file_path.stem
            print(f"\n{Colors.RED}✗{Colors.RESET} {result.suite}/{file_name}: {result.test.name}")
            if result.error:
                print(f"  Error: {result.error}")
            elif result.actual_output is not None:
                print(f"  {result.test.file_path}:{result.test.start_line}")
                print(f"  Command: {result.test.command}")
                print()
                print_diff(result.test.expected_output, result.actual_output)

    print()
    elapsed_str = f" in {elapsed:.2f}s"
    if total_failed == 0 and total_skipped == 0:
        print(f"{Colors.GREEN}{Colors.BOLD}All {total_passed} tests passed{Colors.RESET}{elapsed_str}")
    else:
        print(f"{Colors.BOLD}Summary:{Colors.RESET} {total_passed} passed, {total_failed} failed, {total_skipped} skipped{elapsed_str}")


def list_tests() -> None:
    """List all available tests."""
    suites = discover_suites(CORPUS_DIR)
    
    for suite_dir in suites:
        suite_name = str(suite_dir.relative_to(CORPUS_DIR))
        has_fixture = (suite_dir / "fixture").exists()
        has_setup = (suite_dir / "_setup.txt").exists()
        
        markers = []
        if has_fixture:
            markers.append("fixture")
        if has_setup:
            markers.append("setup")
        marker_str = f" [{', '.join(markers)}]" if markers else ""
        
        print(f"\n{Colors.BOLD}{suite_name}{Colors.RESET}{marker_str}")

        corpus_files = sorted(f for f in suite_dir.glob("*.txt") if not f.name.startswith("_"))
        for corpus_file in corpus_files:
            tests = parse_corpus_file(corpus_file)
            print(f"  {corpus_file.stem}: {len(tests)} test(s)")
            for test in tests:
                print(f"    - {test.name}")


def main() -> int:
    global progress_queue

    parser = argparse.ArgumentParser(description="Run leta corpus tests")
    parser.add_argument("filter", nargs="?", help="Filter by suite or suite/file")
    parser.add_argument("--update", "-u", action="store_true", help="Update expected outputs")
    parser.add_argument("--list", "-l", action="store_true", help="List all tests")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--no-color", action="store_true", help="Disable colored output")
    parser.add_argument("--sequential", "-s", action="store_true", help="Run suites sequentially")

    args = parser.parse_args()

    if args.no_color or not sys.stdout.isatty():
        Colors.disable()

    if args.list:
        list_tests()
        return 0

    suite_filter = None
    file_filter = None

    if args.filter:
        if "/" in args.filter:
            parts = args.filter.rsplit("/", 1)
            # Check if last part is a file filter or part of suite path
            potential_suite = CORPUS_DIR / args.filter
            if potential_suite.is_dir():
                suite_filter = args.filter
            else:
                suite_filter = parts[0]
                file_filter = parts[1]
        else:
            suite_filter = args.filter

    # Discover all suites
    all_suites = discover_suites(CORPUS_DIR)
    
    # Filter suites
    suites = []
    for suite_dir in all_suites:
        suite_name = str(suite_dir.relative_to(CORPUS_DIR))
        if suite_filter:
            if not suite_name.startswith(suite_filter):
                continue
        suites.append(suite_dir)

    if not suites:
        print(f"{Colors.RED}No test suites found{Colors.RESET}")
        return 1

    start_time = time.time()

    progress_queue = Queue()
    stop_event = threading.Event()
    printer_thread = Thread(target=progress_printer_thread, args=(progress_queue, args.verbose, stop_event))
    printer_thread.start()

    try:
        if args.sequential or len(suites) == 1:
            results = [run_suite(suite, file_filter) for suite in suites]
        else:
            results = []
            with ThreadPoolExecutor(max_workers=len(suites)) as executor:
                futures = {executor.submit(run_suite, suite, file_filter): suite for suite in suites}
                for future in as_completed(futures):
                    results.append(future.result())

        stop_event.set()
        printer_thread.join()

        print()

        if args.update:
            for suite_result in results:
                for file_result in suite_result.file_results:
                    failed_results = [r for r in file_result.results if not r.passed and r.actual_output is not None]
                    if failed_results:
                        update_corpus_file(file_result.file_path, failed_results)
                        print(f"{Colors.YELLOW}Updated{Colors.RESET}: {file_result.file_path}")

        elapsed = time.time() - start_time
        print_results(results, elapsed=elapsed)

        all_passed = all(r.passed or r.setup_error for r in results)
        return 0 if all_passed else 1

    finally:
        stop_event.set()
        printer_thread.join(timeout=1)


if __name__ == "__main__":
    sys.exit(main())
