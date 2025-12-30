import pytest

from lspcmd.output.formatters import (
    format_output,
    format_locations,
    format_symbols,
    format_code_actions,
    format_session,
)


class TestFormatLocations:
    def test_simple_location(self):
        locations = [{"path": "/home/user/main.py", "line": 10, "column": 5}]
        result = format_locations(locations)
        assert "/home/user/main.py:10" in result

    def test_multiple_locations(self):
        locations = [
            {"path": "/home/user/main.py", "line": 10, "column": 5},
            {"path": "/home/user/utils.py", "line": 20, "column": 0},
        ]
        result = format_locations(locations)
        assert "/home/user/main.py:10" in result
        assert "/home/user/utils.py:20" in result

    def test_location_with_context(self):
        locations = [{
            "path": "/home/user/main.py",
            "line": 2,
            "column": 0,
            "context_lines": ["line1", "line2", "line3"],
            "context_start": 1,
        }]
        result = format_locations(locations)
        assert "/home/user/main.py:1-3" in result
        assert "line1" in result
        assert "line2" in result
        assert "line3" in result


class TestFormatSymbols:
    def test_simple_symbol(self):
        symbols = [{
            "name": "main",
            "kind": "Function",
            "path": "/home/user/main.py",
            "line": 10,
        }]
        result = format_symbols(symbols)
        assert "main" in result
        assert "Function" in result
        assert "/home/user/main.py:10" in result

    def test_symbol_with_detail(self):
        symbols = [{
            "name": "User",
            "kind": "Class",
            "path": "/home/user/main.py",
            "line": 5,
            "detail": "class User(BaseModel)",
        }]
        result = format_symbols(symbols)
        assert "User" in result
        assert "class User(BaseModel)" in result

    def test_symbol_with_container(self):
        symbols = [{
            "name": "get_name",
            "kind": "Method",
            "path": "/home/user/main.py",
            "line": 15,
            "container": "User",
        }]
        result = format_symbols(symbols)
        assert "get_name" in result
        assert "in User" in result


class TestFormatCodeActions:
    def test_simple_action(self):
        actions = [{"title": "Add import", "kind": "quickfix"}]
        result = format_code_actions(actions)
        assert "Add import" in result
        assert "quickfix" in result

    def test_preferred_action(self):
        actions = [{"title": "Fix typo", "kind": "quickfix", "is_preferred": True}]
        result = format_code_actions(actions)
        assert "[preferred]" in result


class TestFormatSession:
    def test_empty_session(self):
        result = format_session({"workspaces": []})
        assert "No active workspaces" in result

    def test_session_with_workspace(self):
        data = {
            "workspaces": [{
                "root": "/home/user/project",
                "server": "pyright",
                "running": True,
                "open_documents": ["file:///home/user/project/main.py"],
            }]
        }
        result = format_session(data)
        assert "/home/user/project" in result
        assert "pyright" in result
        assert "running" in result


class TestFormatOutput:
    def test_json_output(self):
        data = {"key": "value"}
        result = format_output(data, "json")
        assert '"key": "value"' in result

    def test_plain_output(self):
        data = {"contents": "Hello world"}
        result = format_output(data, "plain")
        assert "Hello world" in result
