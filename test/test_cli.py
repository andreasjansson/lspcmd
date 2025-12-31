import subprocess
import sys
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from lspcmd.cli import cli
from lspcmd.daemon.pidfile import is_daemon_running
from lspcmd.utils.config import get_pid_path, get_socket_path, add_workspace_root, load_config

from .conftest import requires_basedpyright, requires_gopls


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
        assert "SYMBOL" in result.output
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

    def test_grep_no_workspace(self, isolated_config, temp_dir):
        runner = CliRunner()
        import os
        # Run from an empty temp dir with no workspace markers
        empty_dir = temp_dir / "empty"
        empty_dir.mkdir()
        with runner.isolated_filesystem():
            os.chdir(empty_dir)
            result = runner.invoke(cli, ["grep", ".*"])
        assert result.exit_code == 1
        assert "No workspace initialized" in result.output
        assert "workspace init" in result.output


class TestCliWithDaemon:
    @pytest.fixture(autouse=True)
    def setup_teardown(self, isolated_config):
        requires_basedpyright()
        # Shutdown any existing daemon before test (might be from different config)
        pid_path = get_pid_path()
        if is_daemon_running(pid_path):
            runner = CliRunner()
            runner.invoke(cli, ["daemon", "shutdown"])
            time.sleep(0.5)
        yield
        # Shutdown daemon after test
        pid_path = get_pid_path()
        if is_daemon_running(pid_path):
            runner = CliRunner()
            runner.invoke(cli, ["daemon", "shutdown"])
            time.sleep(0.5)

    def test_daemon_info(self, isolated_config):
        runner = CliRunner()
        result = runner.invoke(cli, ["daemon", "info"])
        assert result.exit_code == 0

    def test_definition_by_symbol(self, python_project, isolated_config):
        config = load_config()
        add_workspace_root(python_project, config)

        runner = CliRunner()
        import os
        with runner.isolated_filesystem():
            os.chdir(python_project)
            result = runner.invoke(cli, ["definition", "User"])
        assert result.exit_code == 0
        assert "main.py" in result.output

    def test_definition_with_container(self, python_project, isolated_config):
        config = load_config()
        add_workspace_root(python_project, config)

        runner = CliRunner()
        import os
        with runner.isolated_filesystem():
            os.chdir(python_project)
            result = runner.invoke(cli, ["definition", "MemoryStorage.save"])
        assert result.exit_code == 0
        assert "main.py" in result.output

    def test_definition_with_path_filter(self, python_project, isolated_config):
        config = load_config()
        add_workspace_root(python_project, config)

        runner = CliRunner()
        import os
        with runner.isolated_filesystem():
            os.chdir(python_project)
            result = runner.invoke(cli, ["definition", "main.py:User"])
        assert result.exit_code == 0
        assert "main.py" in result.output

    def test_definition_body(self, python_project, isolated_config):
        config = load_config()
        add_workspace_root(python_project, config)

        runner = CliRunner()
        import os
        with runner.isolated_filesystem():
            os.chdir(python_project)
            result = runner.invoke(cli, ["definition", "User", "--body"])
        assert result.exit_code == 0
        assert "class User" in result.output

    def test_describe(self, python_project, isolated_config):
        config = load_config()
        add_workspace_root(python_project, config)

        runner = CliRunner()
        import os
        with runner.isolated_filesystem():
            os.chdir(python_project)
            result = runner.invoke(cli, ["describe", "User"])
        assert result.exit_code == 0

    def test_references(self, python_project, isolated_config):
        config = load_config()
        add_workspace_root(python_project, config)

        runner = CliRunner()
        import os
        with runner.isolated_filesystem():
            os.chdir(python_project)
            result = runner.invoke(cli, ["references", "User"])
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

    def test_implementations_for_protocol(self, python_project, isolated_config):
        """Test that implementations works for Python Protocols.
        
        basedpyright now supports implementations for Protocol classes.
        """
        config = load_config()
        add_workspace_root(python_project, config)

        runner = CliRunner()
        import os
        with runner.isolated_filesystem():
            os.chdir(python_project)
            result = runner.invoke(cli, ["implementations", "StorageProtocol"])
        assert result.exit_code == 0
        # Should find MemoryStorage and FileStorage as implementations
        assert "main.py" in result.output

    def test_subtypes_not_supported(self, python_project, isolated_config):
        """Test that subtypes returns a helpful error for Python."""
        config = load_config()
        add_workspace_root(python_project, config)

        runner = CliRunner()
        import os
        with runner.isolated_filesystem():
            os.chdir(python_project)
            result = runner.invoke(cli, ["subtypes", "User"])
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
        import os
        with runner.isolated_filesystem():
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

    def test_rename(self, python_project, isolated_config):
        """Test rename symbol."""
        config = load_config()
        add_workspace_root(python_project, config)

        runner = CliRunner()
        import os
        with runner.isolated_filesystem():
            os.chdir(python_project)
            # Rename a function
            result = runner.invoke(cli, ["rename", "create_sample_user", "make_sample_user"])
        assert result.exit_code == 0


class TestCliWithGopls:
    @pytest.fixture(autouse=True)
    def setup_teardown(self, isolated_config):
        requires_gopls()
        # Shutdown any existing daemon before test (might be from different config)
        pid_path = get_pid_path()
        if is_daemon_running(pid_path):
            runner = CliRunner()
            runner.invoke(cli, ["daemon", "shutdown"])
            time.sleep(0.5)
        yield
        # Shutdown daemon after test
        pid_path = get_pid_path()
        if is_daemon_running(pid_path):
            runner = CliRunner()
            runner.invoke(cli, ["daemon", "shutdown"])
            time.sleep(0.5)

    def test_implementations(self, go_project, isolated_config):
        """Test that implementations works for Go interfaces."""
        config = load_config()
        add_workspace_root(go_project, config)

        runner = CliRunner()
        import os
        with runner.isolated_filesystem():
            os.chdir(go_project)
            result = runner.invoke(cli, ["implementations", "Storage"])
        assert result.exit_code == 0, f"Failed with: {result.output}"
        # Should find MemoryStorage and FileStorage as implementations
        assert "main.go:39" in result.output
        assert "main.go:85" in result.output

    def test_subtypes(self, go_project, isolated_config):
        """Test that subtypes works for Go interfaces."""
        config = load_config()
        add_workspace_root(go_project, config)

        runner = CliRunner()
        import os
        with runner.isolated_filesystem():
            os.chdir(go_project)
            result = runner.invoke(cli, ["subtypes", "Storage"])
        assert result.exit_code == 0, f"Failed with: {result.output}"
        # Order may vary, so sort
        assert sorted(result.output.strip().split("\n")) == sorted("""\
main.go:85 [Class] FileStorage (sample_project)
main.go:39 [Class] MemoryStorage (sample_project)
""".strip().split("\n"))

    def test_supertypes(self, go_project, isolated_config):
        """Test that supertypes works for Go structs."""
        config = load_config()
        add_workspace_root(go_project, config)

        runner = CliRunner()
        import os
        with runner.isolated_filesystem():
            os.chdir(go_project)
            result = runner.invoke(cli, ["supertypes", "MemoryStorage"])
        assert result.exit_code == 0, f"Failed with: {result.output}"
        assert result.output == """\
main.go:31 [Interface] Storage (sample_project)
"""

    def test_definition_by_symbol(self, go_project, isolated_config):
        """Test definition works with symbol syntax in Go."""
        config = load_config()
        add_workspace_root(go_project, config)

        runner = CliRunner()
        import os
        with runner.isolated_filesystem():
            os.chdir(go_project)
            result = runner.invoke(cli, ["definition", "User"])
        assert result.exit_code == 0
        assert "main.go" in result.output

    def test_definition_with_container(self, go_project, isolated_config):
        """Test definition with qualified name in Go."""
        config = load_config()
        add_workspace_root(go_project, config)

        runner = CliRunner()
        import os
        with runner.isolated_filesystem():
            os.chdir(go_project)
            result = runner.invoke(cli, ["definition", "MemoryStorage.Save"])
        assert result.exit_code == 0, f"Failed with: {result.output}"
        assert "main.go" in result.output
