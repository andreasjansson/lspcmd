import os
import shutil
import time

import pytest

from leta.utils.config import add_workspace_root, load_config

from .conftest import (
    FIXTURES_DIR,
    format_output,
    requires_basedpyright,
    requires_gopls,
    run_request,
)


class TestMultiLanguageIntegration:
    """Integration tests for multi-language projects."""

    @pytest.fixture(scope="class")
    def project(self, class_temp_dir):
        src = FIXTURES_DIR / "multi_language_project"
        dst = class_temp_dir / "multi_language_project"
        shutil.copytree(src, dst)
        return dst

    @pytest.fixture(scope="class")
    def workspace(self, project, class_daemon, class_isolated_config):
        config = load_config()
        add_workspace_root(project, config)
        return project

    def test_python_grep(self, workspace):
        requires_basedpyright()
        os.chdir(workspace)

        run_request(
            "grep",
            {
                "paths": [str(workspace / "app.py")],
                "workspace_root": str(workspace),
                "pattern": ".*",
            },
        )
        time.sleep(0.5)

        result = run_request(
            "grep",
            {
                "paths": [str(workspace / "app.py")],
                "workspace_root": str(workspace),
                "pattern": ".*",
                "kinds": ["class"],
            },
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
app.py:10 [Class] ServiceProtocol
app.py:19 [Class] PythonUser
app.py:25 [Class] PythonService"""
        )

    def test_go_grep(self, workspace):
        requires_gopls()
        os.chdir(workspace)

        run_request(
            "grep",
            {
                "paths": [str(workspace / "main.go")],
                "workspace_root": str(workspace),
                "pattern": ".*",
            },
        )
        time.sleep(0.5)

        result = run_request(
            "grep",
            {
                "paths": [str(workspace / "main.go")],
                "workspace_root": str(workspace),
                "pattern": ".*",
                "kinds": ["struct"],
            },
        )
        output = format_output(result, "plain")
        assert (
            output
            == """\
main.go:6 [Struct] GoUser (struct{...})
main.go:12 [Struct] GoService (struct{...})"""
        )

    def test_both_languages_workspace_wide(self, workspace):
        requires_basedpyright()
        requires_gopls()
        os.chdir(workspace)

        # Warm up both servers
        run_request(
            "grep",
            {
                "paths": [str(workspace / "app.py")],
                "workspace_root": str(workspace),
                "pattern": ".*",
            },
        )
        run_request(
            "grep",
            {
                "paths": [str(workspace / "main.go")],
                "workspace_root": str(workspace),
                "pattern": ".*",
            },
        )
        time.sleep(0.5)

        # Now do workspace-wide search
        result = run_request(
            "grep",
            {
                "workspace_root": str(workspace),
                "pattern": "Service",
                "kinds": ["struct", "class"],
            },
        )
        output = format_output(result, "plain")
        # Order may vary, check both are present
        assert "app.py:10 [Class] ServiceProtocol" in output
        assert "app.py:25 [Class] PythonService" in output
        assert "main.go:12 [Struct] GoService" in output
