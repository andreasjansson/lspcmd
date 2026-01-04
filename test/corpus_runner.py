#!/usr/bin/env python3
"""Corpus test runner for leta.

Runs integration tests defined in corpus files against real language servers.

Usage:
    python -m test.corpus_runner                    # Run all tests
    python -m test.corpus_runner python             # Run Python tests only
    python -m test.corpus_runner python/grep_all    # Run specific test file
    python -m test.corpus_runner --update           # Update expected outputs
    python -m test.corpus_runner --list             # List all tests
"""

import argparse
import multiprocessing
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
from threading import Thread

CORPUS_DIR = Path(__file__).parent / "corpus"

LANGUAGE_SERVER_COMMANDS = {
    "python": "basedpyright-langserver",
    "go": "gopls",
    "typescript": "typescript-language-server",
    "rust": "rust-analyzer",
    "java": "jdtls",
    "cpp": "clangd",
    "ruby": "ruby-lsp",
    "php": "intelephense",
    "lua": "lua-language-server",
    "zig": "zls",
    "multi_language": ["basedpyright-langserver", "gopls"],
}


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
    language: str = ""


@dataclass
class FileResult:
    file_path: Path
    results: list[TestResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)


@dataclass
class LanguageResult:
    language: str
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
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    @classmethod
    def disable(cls) -> None:
        cls.GREEN = ""
        cls.RED = ""
        cls.YELLOW = ""
        cls.BLUE = ""
        cls.CYAN = ""
        cls.BOLD = ""
        cls.DIM = ""
        cls.RESET = ""


# Global queue for progress updates
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


def check_language_server(language: str) -> bool:
    """Check if the language server for a language is installed."""
    cmd = LANGUAGE_SERVER_COMMANDS.get(language)
    if not cmd:
        return False
    if isinstance(cmd, list):
        return all(shutil.which(c) is not None for c in cmd)
    return shutil.which(cmd) is not None


def get_language_server_name(language: str) -> str:
    """Get display name for language server(s)."""
    cmd = LANGUAGE_SERVER_COMMANDS.get(language, "unknown")
    if isinstance(cmd, list):
        return ", ".join(cmd)
    return cmd


def setup_workspace(language: str, work_dir: Path) -> str | None:
    """Set up a workspace for testing. Returns error message or None."""
    fixture_dir = CORPUS_DIR / language / "fixture"
    if not fixture_dir.exists():
        return f"No fixture directory found: {fixture_dir}"

    shutil.copytree(fixture_dir, work_dir, dirs_exist_ok=True)

    result = subprocess.run(
        ["leta", "workspace", "add", "--root", str(work_dir)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return f"Failed to add workspace: {result.stderr}"

    result = subprocess.run(
        ["leta", "grep", "."],
        cwd=work_dir,
        capture_output=True,
        text=True,
        timeout=60,
    )

    time.sleep(1.0)
    return None


def run_command(command: str, work_dir: Path) -> tuple[str, int]:
    """Run a shell command and return (output, return_code)."""
    result = subprocess.run(
        command,
        shell=True,
        cwd=work_dir,
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = result.stdout + result.stderr
    return output.rstrip("\n"), result.returncode


def run_test(test: CorpusTest, work_dir: Path, language: str) -> TestResult:
    """Run a single test and return the result."""
    start = time.time()
    try:
        actual_output, _ = run_command(test.command, work_dir)
        elapsed = time.time() - start

        if actual_output == test.expected_output:
            result = TestResult(test=test, passed=True, actual_output=actual_output, elapsed=elapsed, language=language)
        else:
            result = TestResult(test=test, passed=False, actual_output=actual_output, elapsed=elapsed, language=language)
    except subprocess.TimeoutExpired:
        result = TestResult(test=test, passed=False, error="Command timed out", elapsed=time.time() - start, language=language)
    except Exception as e:
        result = TestResult(test=test, passed=False, error=str(e), elapsed=time.time() - start, language=language)
    
    if progress_queue:
        progress_queue.put(("test", result))
    
    return result


def run_corpus_file(file_path: Path, work_dir: Path, language: str) -> FileResult:
    """Run all tests in a corpus file."""
    file_result = FileResult(file_path=file_path)
    tests = parse_corpus_file(file_path)

    for test in tests:
        result = run_test(test, work_dir, language)
        file_result.results.append(result)

    return file_result


def run_language(language: str, temp_base: Path, filter_pattern: str | None = None) -> LanguageResult:
    """Run all corpus tests for a language."""
    start_time = time.time()
    result = LanguageResult(language=language)

    if not check_language_server(language):
        result.setup_error = f"Language server not installed: {get_language_server_name(language)}"
        result.elapsed = time.time() - start_time
        if progress_queue:
            progress_queue.put(("skip", language, result.setup_error))
        return result

    work_dir = temp_base / language
    work_dir.mkdir(parents=True, exist_ok=True)

    setup_error = setup_workspace(language, work_dir)
    if setup_error:
        result.setup_error = setup_error
        result.elapsed = time.time() - start_time
        if progress_queue:
            progress_queue.put(("skip", language, setup_error))
        return result

    corpus_files = sorted((CORPUS_DIR / language).glob("*.txt"))

    for corpus_file in corpus_files:
        if filter_pattern and filter_pattern not in corpus_file.stem:
            continue
        file_result = run_corpus_file(corpus_file, work_dir, language)
        result.file_results.append(file_result)

    result.elapsed = time.time() - start_time
    return result


def progress_printer_thread(queue: Queue, verbose: bool, stop_event) -> None:
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
                print(f"{status} {result.language}/{result.test.file_path.stem}: {result.test.name} {time_str}")
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
            language, reason = msg[1], msg[2]
            if verbose:
                print(f"{Colors.YELLOW}S{Colors.RESET} {language}: {reason}")
            else:
                print(f"{Colors.YELLOW}S{Colors.RESET}", end="", flush=True)
                dot_count += 1
    
    # Final newline after dots
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


def print_results(results: list[LanguageResult], elapsed: float) -> None:
    """Print test results."""
    total_passed = 0
    total_failed = 0
    total_skipped = 0
    failed_tests: list[TestResult] = []

    # Print per-language results (no blank lines between)
    for lang_result in sorted(results, key=lambda r: r.language):
        if lang_result.setup_error:
            print(f"{Colors.YELLOW}⊘ {lang_result.language}{Colors.RESET}: {lang_result.setup_error}")
            total_skipped += 1
            continue

        lang_passed = lang_result.passed_tests
        lang_total = lang_result.total_tests
        lang_time = f" in {lang_result.elapsed:.2f}s"

        total_passed += lang_passed
        total_failed += lang_total - lang_passed

        if lang_result.passed:
            print(f"{Colors.GREEN}✓ {lang_result.language}{Colors.RESET}: {lang_passed}/{lang_total} tests passed{lang_time}")
        else:
            print(f"{Colors.RED}✗ {lang_result.language}{Colors.RESET}: {lang_passed}/{lang_total} tests passed{lang_time}")
            for file_result in lang_result.file_results:
                for result in file_result.results:
                    if not result.passed:
                        failed_tests.append(result)

    # Print failures
    if failed_tests:
        print(f"\n{Colors.RED}{Colors.BOLD}Failures:{Colors.RESET}")
        for result in failed_tests:
            file_name = result.test.file_path.stem
            print(f"\n{Colors.RED}✗{Colors.RESET} {result.language}/{file_name}: {result.test.name}")
            if result.error:
                print(f"  Error: {result.error}")
            elif result.actual_output is not None:
                print(f"  {result.test.file_path}:{result.test.start_line}")
                print(f"  Command: {result.test.command}")
                print()
                print_diff(result.test.expected_output, result.actual_output)

    # Print final summary
    print()
    elapsed_str = f" in {elapsed:.2f}s"
    if total_failed == 0 and total_skipped == 0:
        print(f"{Colors.GREEN}{Colors.BOLD}All {total_passed} tests passed{Colors.RESET}{elapsed_str}")
    else:
        print(f"{Colors.BOLD}Summary:{Colors.RESET} {total_passed} passed, {total_failed} failed, {total_skipped} skipped{elapsed_str}")


def list_tests() -> None:
    """List all available tests."""
    for lang_dir in sorted(CORPUS_DIR.iterdir()):
        if not lang_dir.is_dir() or not (lang_dir / "fixture").exists():
            continue

        language = lang_dir.name
        server_cmd = get_language_server_name(language)
        installed = "✓" if check_language_server(language) else "✗"

        print(f"\n{Colors.BOLD}{language}{Colors.RESET} ({server_cmd}) [{installed}]")

        for corpus_file in sorted(lang_dir.glob("*.txt")):
            tests = parse_corpus_file(corpus_file)
            print(f"  {corpus_file.stem}: {len(tests)} test(s)")
            for test in tests:
                print(f"    - {test.name}")


def main() -> int:
    global progress_queue

    parser = argparse.ArgumentParser(description="Run leta corpus tests")
    parser.add_argument("filter", nargs="?", help="Filter by language or language/file")
    parser.add_argument("--update", "-u", action="store_true", help="Update expected outputs")
    parser.add_argument("--list", "-l", action="store_true", help="List all tests")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--no-color", action="store_true", help="Disable colored output")
    parser.add_argument("--sequential", "-s", action="store_true", help="Run languages sequentially")

    args = parser.parse_args()

    if args.no_color or not sys.stdout.isatty():
        Colors.disable()

    if args.list:
        list_tests()
        return 0

    language_filter = None
    file_filter = None

    if args.filter:
        if "/" in args.filter:
            language_filter, file_filter = args.filter.split("/", 1)
        else:
            language_filter = args.filter

    languages = []
    for lang_dir in sorted(CORPUS_DIR.iterdir()):
        if not lang_dir.is_dir() or not (lang_dir / "fixture").exists():
            continue
        language = lang_dir.name
        if language_filter and language != language_filter:
            continue
        languages.append(language)

    if not languages:
        print(f"{Colors.RED}No languages found{Colors.RESET}")
        return 1

    temp_base = Path(tempfile.mkdtemp(prefix="leta_corpus_")).resolve()
    start_time = time.time()

    # Set up progress queue and printer thread
    import threading
    progress_queue = Queue()
    stop_event = threading.Event()
    printer_thread = Thread(target=progress_printer_thread, args=(progress_queue, args.verbose, stop_event))
    printer_thread.start()

    try:
        if args.sequential or len(languages) == 1:
            results = [run_language(lang, temp_base, file_filter) for lang in languages]
        else:
            # Use ThreadPoolExecutor for parallel execution with progress updates
            results = []
            with ThreadPoolExecutor(max_workers=len(languages)) as executor:
                futures = {executor.submit(run_language, lang, temp_base, file_filter): lang for lang in languages}
                for future in as_completed(futures):
                    results.append(future.result())

        # Stop the printer thread
        stop_event.set()
        printer_thread.join()

        # Add separator in verbose mode
        if args.verbose:
            print()

        if args.update:
            for lang_result in results:
                for file_result in lang_result.file_results:
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
        shutil.rmtree(temp_base, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
