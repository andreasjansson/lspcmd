import subprocess
import sys
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from lspcmd.cli import cli, parse_position
from lspcmd.daemon.pidfile import is_daemon_running
from lspcmd.utils.config import get_pid_path, get_socket_path, add_workspace_root, load_config

from .conftest import requires_pyright, requires_gopls


class TestParsePosition:
    def test_valid_position(self):
        line, col = parse_position("10,5")
        assert line == 10
        assert col == 5

    def test_invalid_format(self):
        with pytest.raises(Exception):
            parse_position("10")

    def test_first_line(self):
        line, col = parse_position("1,0")
        assert line == 1
        assert col == 0

    def test_regex_requires_file_path(self):
        with pytest.raises(Exception) as exc_info:
            parse_position("def foo")
        assert "without a file path" in str(exc_info.value)

    def test_line_regex_format(self, python_project):
        main_py = python_project / "main.py"
        # Line 25 has "class User:"
        line, col = parse_position("25:User", main_py)
        assert line == 25
        assert col == 6

    def test_regex_only_format(self, python_project):
        main_py = python_project / "main.py"
        # "class User:" is on line 25
        line, col = parse_position("class User:", main_py)
        assert line == 25
        assert col == 0

    def test_regex_multiple_matches_error(self, python_project):
        main_py = python_project / "main.py"
        with pytest.raises(Exception) as exc_info:
            parse_position("self", main_py)
        assert "matches" in str(exc_info.value)

    def test_regex_not_found_error(self, python_project):
        main_py = python_project / "main.py"
        with pytest.raises(Exception) as exc_info:
            parse_position("xyz_nonexistent", main_py)
        assert "not found" in str(exc_info.value)

    def test_line_regex_not_found_on_line(self, python_project):
        main_py = python_project / "main.py"
        with pytest.raises(Exception) as exc_info:
            parse_position("1:User", main_py)
        assert "not found on line 1" in str(exc_info.value)

    def test_regex_with_special_chars(self, python_project):
        main_py = python_project / "main.py"
        line, col = parse_position(r"def __init__\(self\)", main_py)
        assert line == 13
        assert col == 4

    def test_regex_finds_correct_column(self, python_project):
        main_py = python_project / "main.py"
        # Line 7 is "    name: str"
        line, col = parse_position("7:name", main_py)
        assert line == 7
        assert col == 4

    def test_line_column_still_works_with_file(self, python_project):
        main_py = python_project / "main.py"
        line, col = parse_position("10,5", main_py)
        assert line == 10
        assert col == 5

    def test_ambiguous_match_shows_locations(self, python_project):
        main_py = python_project / "main.py"
        with pytest.raises(Exception) as exc_info:
            parse_position("def", main_py)
        error_msg = str(exc_info.value)
        assert "matches" in error_msg
        assert "line" in error_msg


class TestCliCommands:
    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Commands:" in result.output
        assert "definition" in result.output
        assert "workspace" in result.output
        assert "daemon" in result.output

    def test_config_command(self, isolated_config):
        runner = CliRunner()
        result = runner.invoke(cli, ["config"])
        assert result.exit_code == 0
        assert "Config file:" in result.output

    def test_definition_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["definition", "--help"])
        assert result.exit_code == 0
        assert "LINE,COLUMN" in result.output
        assert "--body" in result.output

    def test_workspace_init(self, python_project, isolated_config):
        runner = CliRunner()
        result = runner.invoke(cli, ["workspace", "init", "--root", str(python_project)])
        assert result.exit_code == 0
        assert "Initialized workspace:" in result.output

    def test_workspace_init_already_initialized(self, python_project, isolated_config):
        runner = CliRunner()
        runner.invoke(cli, ["workspace", "init", "--root", str(python_project)])
        result = runner.invoke(cli, ["workspace", "init", "--root", str(python_project)])
        assert result.exit_code == 0
        assert "already initialized" in result.output

    def test_grep_no_workspace(self, isolated_config):
        runner = CliRunner()
        result = runner.invoke(cli, ["grep", ".*"])
        assert result.exit_code == 1
        assert "No workspace initialized" in result.output
        assert "workspace init" in result.output


class TestCliWithDaemon:
    @pytest.fixture(autouse=True)
    def setup_teardown(self, isolated_config):
        requires_pyright()
        yield
        pid_path = get_pid_path()

        if is_daemon_running(pid_path):
            runner = CliRunner()
            runner.invoke(cli, ["daemon", "shutdown"])
            time.sleep(0.5)

    def test_daemon_info(self, isolated_config):
        runner = CliRunner()
        result = runner.invoke(cli, ["daemon", "info"])
        assert result.exit_code == 0

    def test_definition(self, python_project, isolated_config):
        main_py = python_project / "main.py"
        config = load_config()
        add_workspace_root(python_project, config)

        runner = CliRunner()
        result = runner.invoke(cli, ["definition", str(main_py), "36,11"])
        assert result.exit_code == 0

    def test_describe(self, python_project, isolated_config):
        main_py = python_project / "main.py"
        config = load_config()
        add_workspace_root(python_project, config)

        runner = CliRunner()
        result = runner.invoke(cli, ["describe", str(main_py), "6,6"])
        assert result.exit_code == 0

    def test_grep_with_file(self, python_project, isolated_config):
        main_py = python_project / "main.py"
        config = load_config()
        add_workspace_root(python_project, config)

        runner = CliRunner()
        result = runner.invoke(cli, ["grep", ".*", str(main_py)])
        assert result.exit_code == 0
        assert "User" in result.output or "Class" in result.output

    def test_daemon_shutdown(self, isolated_config):
        runner = CliRunner()
        runner.invoke(cli, ["daemon", "info"])

        result = runner.invoke(cli, ["daemon", "shutdown"])
        assert result.exit_code == 0

        time.sleep(0.5)
        assert not is_daemon_running(get_pid_path())

    def test_json_output(self, isolated_config):
        runner = CliRunner()
        result = runner.invoke(cli, ["--json", "daemon", "info"])
        assert result.exit_code == 0
        assert "{" in result.output

    def test_workspace_restart(self, python_project, isolated_config):
        main_py = python_project / "main.py"
        config = load_config()
        add_workspace_root(python_project, config)

        runner = CliRunner()
        # First, do something to initialize the workspace
        runner.invoke(cli, ["grep", ".*", str(main_py)])

        # Now restart it
        result = runner.invoke(cli, ["workspace", "restart", str(python_project)])
        assert result.exit_code == 0
        assert "restarted" in result.output.lower() or "True" in result.output

    def test_workspace_restart_not_found(self, temp_dir, isolated_config):
        runner = CliRunner()
        # Try to restart a workspace that doesn't exist
        result = runner.invoke(cli, ["workspace", "restart", str(temp_dir)])
        # Should fail because workspace isn't initialized
        assert result.exit_code != 0 or "error" in result.output.lower() or "not" in result.output.lower()

    def test_implementations_not_supported(self, python_project, isolated_config):
        """Test that implementations returns a helpful error for Python."""
        main_py = python_project / "main.py"
        config = load_config()
        add_workspace_root(python_project, config)

        runner = CliRunner()
        result = runner.invoke(cli, ["implementations", str(main_py), "6,6"])
        # Should fail with a "not supported" error
        assert result.exit_code == 1
        assert "not supported" in result.output.lower() or "method not found" in result.output.lower()

    def test_subtypes_not_supported(self, python_project, isolated_config):
        """Test that subtypes returns a helpful error for Python."""
        main_py = python_project / "main.py"
        config = load_config()
        add_workspace_root(python_project, config)

        runner = CliRunner()
        result = runner.invoke(cli, ["subtypes", str(main_py), "6,6"])
        # Should fail with a "not supported" error
        assert result.exit_code == 1
        assert "not supported" in result.output.lower() or "method not found" in result.output.lower()

    def test_diagnostics_single_file(self, python_project, isolated_config):
        """Test diagnostics for a single file."""
        config = load_config()
        add_workspace_root(python_project, config)

        # Create a file with errors
        bad_file = python_project / "bad.py"
        bad_file.write_text('x: str = 123\n')

        runner = CliRunner()
        result = runner.invoke(cli, ["diagnostics", str(bad_file)])
        assert result.exit_code == 0, f"Failed with: {result.output}"
        assert "error" in result.output.lower()

    def test_diagnostics_workspace(self, python_project, isolated_config):
        """Test diagnostics for entire workspace."""
        config = load_config()
        add_workspace_root(python_project, config)

        # Create a file with errors
        bad_file = python_project / "bad.py"
        bad_file.write_text('x: str = 123\n')

        runner = CliRunner()
        # Run from the python_project directory
        with runner.isolated_filesystem():
            import os
            os.chdir(python_project)
            result = runner.invoke(cli, ["diagnostics"])
        assert result.exit_code == 0, f"Failed with: {result.output}"
        # Should find the error in bad.py
        assert "bad.py" in result.output or "error" in result.output.lower()

    def test_diagnostics_severity_filter(self, python_project, isolated_config):
        """Test diagnostics with severity filter."""
        config = load_config()
        add_workspace_root(python_project, config)

        # Create a file with errors
        bad_file = python_project / "bad.py"
        bad_file.write_text('x: str = 123\nundefined_var\n')

        runner = CliRunner()
        result = runner.invoke(cli, ["diagnostics", str(bad_file), "-s", "error"])
        assert result.exit_code == 0, f"Failed with: {result.output}"
        # Should have errors but filter out warnings
        assert "error" in result.output.lower()


class TestCliWithGopls:
    @pytest.fixture(autouse=True)
    def setup_teardown(self, isolated_config):
        requires_gopls()
        yield
        pid_path = get_pid_path()

        if is_daemon_running(pid_path):
            runner = CliRunner()
            runner.invoke(cli, ["daemon", "shutdown"])
            time.sleep(0.5)

    def test_implementations(self, go_project, isolated_config):
        """Test that implementations works for Go interfaces."""
        main_go = go_project / "main.go"
        config = load_config()
        add_workspace_root(go_project, config)

        runner = CliRunner()
        # Find implementations of Storage interface (line 16)
        result = runner.invoke(cli, ["implementations", str(main_go), "16:Storage"])
        assert result.exit_code == 0, f"Failed with: {result.output}"
        # Should find MemoryStorage (line 22) and FileStorage (line 36)
        assert "main.go:22" in result.output
        assert "main.go:36" in result.output

    def test_subtypes(self, go_project, isolated_config):
        """Test that subtypes works for Go interfaces."""
        main_go = go_project / "main.go"
        config = load_config()
        add_workspace_root(go_project, config)

        runner = CliRunner()
        # Find subtypes of Storage interface (line 16)
        result = runner.invoke(cli, ["subtypes", str(main_go), "16:Storage"])
        assert result.exit_code == 0, f"Failed with: {result.output}"
        # Should find MemoryStorage and FileStorage as direct subtypes
        assert "MemoryStorage" in result.output
        assert "FileStorage" in result.output

    def test_supertypes(self, go_project, isolated_config):
        """Test that supertypes works for Go structs."""
        main_go = go_project / "main.go"
        config = load_config()
        add_workspace_root(go_project, config)

        runner = CliRunner()
        # Find supertypes of MemoryStorage (line 22)
        result = runner.invoke(cli, ["supertypes", str(main_go), "22:MemoryStorage"])
        assert result.exit_code == 0, f"Failed with: {result.output}"
        # Should find Storage interface as a supertype
        assert "Storage" in result.output
