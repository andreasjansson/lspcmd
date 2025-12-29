import subprocess
import sys
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from lspcmd.cli import cli, parse_position
from lspcmd.daemon.pidfile import is_daemon_running
from lspcmd.utils.config import get_pid_path, get_socket_path

from .conftest import requires_pyright


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


class TestCliCommands:
    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "LSP command-line interface" in result.output

    def test_config_command(self, isolated_config):
        runner = CliRunner()
        result = runner.invoke(cli, ["config"])
        assert result.exit_code == 0
        assert "Config file:" in result.output

    def test_find_definition_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["find-definition", "--help"])
        assert result.exit_code == 0
        assert "LINE,COLUMN" in result.output


@requires_pyright
class TestCliWithDaemon:
    @pytest.fixture(autouse=True)
    def setup_teardown(self, isolated_config):
        yield
        pid_path = get_pid_path()
        socket_path = get_socket_path()

        if is_daemon_running(pid_path):
            runner = CliRunner()
            runner.invoke(cli, ["shutdown"])
            time.sleep(0.5)

    def test_describe_session(self, isolated_config):
        runner = CliRunner()
        result = runner.invoke(cli, ["describe-session"])
        assert result.exit_code == 0

    def test_find_definition(self, python_project, isolated_config):
        main_py = python_project / "main.py"

        runner = CliRunner()
        result = runner.invoke(cli, ["find-definition", str(main_py), "36,11"], input="y\n")

        assert result.exit_code == 0

    def test_describe_thing_at_point(self, python_project, isolated_config):
        main_py = python_project / "main.py"

        runner = CliRunner()
        result = runner.invoke(cli, ["describe-thing-at-point", str(main_py), "6,6"], input="y\n")

        assert result.exit_code == 0

    def test_list_symbols(self, python_project, isolated_config):
        main_py = python_project / "main.py"

        runner = CliRunner()
        result = runner.invoke(cli, ["list-symbols", str(main_py)], input="y\n")

        assert result.exit_code == 0
        assert "User" in result.output or "Class" in result.output

    def test_shutdown(self, isolated_config):
        runner = CliRunner()
        runner.invoke(cli, ["describe-session"])

        result = runner.invoke(cli, ["shutdown"])
        assert result.exit_code == 0

        time.sleep(0.5)
        assert not is_daemon_running(get_pid_path())

    def test_json_output(self, isolated_config):
        runner = CliRunner()
        result = runner.invoke(cli, ["--json", "describe-session"])
        assert result.exit_code == 0
        assert "{" in result.output
