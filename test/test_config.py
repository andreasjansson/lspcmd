from pathlib import Path

import pytest

from lspcmd.utils.config import (
    detect_workspace_root,
    get_known_workspace_root,
    add_workspace_root,
    load_config,
    save_config,
)


class TestDetectWorkspaceRoot:
    def test_detect_git(self, temp_dir):
        project = (temp_dir / "project").resolve()
        project.mkdir()
        (project / ".git").mkdir()
        (project / "src").mkdir()
        (project / "src" / "main.py").touch()

        root = detect_workspace_root(project / "src" / "main.py")
        assert root == project

    def test_detect_pyproject(self, temp_dir):
        project = (temp_dir / "project").resolve()
        project.mkdir()
        (project / "pyproject.toml").touch()
        (project / "main.py").touch()

        root = detect_workspace_root(project / "main.py")
        assert root == project

    def test_detect_cargo(self, temp_dir):
        project = (temp_dir / "project").resolve()
        (project / "src").mkdir(parents=True)
        (project / "Cargo.toml").touch()
        (project / "src" / "main.rs").touch()

        root = detect_workspace_root(project / "src" / "main.rs")
        assert root == project

    def test_detect_package_json(self, temp_dir):
        project = (temp_dir / "project").resolve()
        (project / "src").mkdir(parents=True)
        (project / "package.json").touch()
        (project / "src" / "main.ts").touch()

        root = detect_workspace_root(project / "src" / "main.ts")
        assert root == project

    def test_no_markers(self, temp_dir):
        project = (temp_dir / "project").resolve()
        project.mkdir()
        (project / "main.py").touch()

        root = detect_workspace_root(project / "main.py")
        assert root is None


class TestKnownWorkspaceRoot:
    def test_known_root(self, temp_dir):
        project = (temp_dir / "project").resolve()
        config = {"workspaces": {"roots": [str(project)]}}
        file_path = project / "src" / "main.py"

        root = get_known_workspace_root(file_path, config)
        assert root == project

    def test_unknown_root(self, temp_dir):
        config = {"workspaces": {"roots": []}}
        file_path = temp_dir / "project" / "main.py"

        root = get_known_workspace_root(file_path, config)
        assert root is None

    def test_prefers_most_specific_root(self, temp_dir):
        outer_project = (temp_dir / "project").resolve()
        inner_project = (outer_project / "fixtures" / "rust_project").resolve()
        inner_project.mkdir(parents=True)
        
        config = {"workspaces": {"roots": [
            str(outer_project),
            str(inner_project),
        ]}}
        
        file_in_inner = inner_project / "src" / "main.rs"
        root = get_known_workspace_root(file_in_inner, config)
        assert root == inner_project
        
        file_in_outer = outer_project / "src" / "main.py"
        root = get_known_workspace_root(file_in_outer, config)
        assert root == outer_project

    def test_prefers_most_specific_root_regardless_of_order(self, temp_dir):
        outer_project = (temp_dir / "project").resolve()
        inner_project = (outer_project / "fixtures" / "go_project").resolve()
        inner_project.mkdir(parents=True)
        
        # Reverse order - inner first, outer second
        config = {"workspaces": {"roots": [
            str(inner_project),
            str(outer_project),
        ]}}
        
        file_in_inner = inner_project / "main.go"
        root = get_known_workspace_root(file_in_inner, config)
        assert root == inner_project


class TestAddWorkspaceRoot:
    def test_add_new_root(self, temp_dir, isolated_config):
        config = load_config()
        project = (temp_dir / "project").resolve()
        project.mkdir()

        add_workspace_root(project, config)

        loaded = load_config()
        assert str(project) in loaded["workspaces"]["roots"]

    def test_add_duplicate_root(self, temp_dir, isolated_config):
        config = load_config()
        project = (temp_dir / "project").resolve()
        project.mkdir()

        add_workspace_root(project, config)
        add_workspace_root(project, config)

        loaded = load_config()
        roots = loaded["workspaces"]["roots"]
        assert roots.count(str(project)) == 1
