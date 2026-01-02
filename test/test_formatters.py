import pytest

from lspcmd.output.formatters import (
    format_output,
    format_locations,
    format_symbols,
    format_code_actions,
    format_session,
    format_tree,
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
        result = format_session({"workspaces": [], "daemon_pid": 12345})
        assert "No active workspaces" in result
        assert "Daemon PID: 12345" in result

    def test_session_with_workspace(self):
        data = {
            "daemon_pid": 12345,
            "workspaces": [{
                "root": "/home/user/project",
                "server": "pyright",
                "server_pid": 67890,
                "running": True,
                "open_documents": ["file:///home/user/project/main.py"],
            }]
        }
        result = format_session(data)
        assert "Daemon PID: 12345" in result
        assert "/home/user/project" in result
        assert "pyright" in result
        assert "running" in result
        assert "PID 67890" in result


class TestFormatTree:
    def test_simple_tree(self):
        data = {
            "root": "/home/user/project",
            "files": {
                "main.py": {"size": 1024, "lines": 50},
                "utils.py": {"size": 512, "lines": 25},
            },
            "total_files": 2,
            "total_bytes": 1536,
            "total_lines": 75,
        }
        result = format_tree(data)
        assert result == """main.py (1.0KB, 50 lines)
utils.py (512B, 25 lines)

2 files, 1.5KB, 75 lines"""

    def test_tree_with_symbols(self):
        data = {
            "root": "/home/user/project",
            "files": {
                "main.py": {
                    "size": 1024,
                    "lines": 50,
                    "symbols": {"class": 2, "function": 3, "method": 5},
                },
            },
            "total_files": 1,
            "total_bytes": 1024,
            "total_lines": 50,
        }
        result = format_tree(data)
        assert result == """main.py (1.0KB, 50 lines, 2 classes, 3 functions, 5 methods)

1 files, 1.0KB, 50 lines"""

    def test_tree_with_nested_directories(self):
        data = {
            "root": "/home/user/project",
            "files": {
                "main.py": {"size": 100, "lines": 10},
                "src/utils.py": {"size": 200, "lines": 20},
                "src/lib/helper.py": {"size": 300, "lines": 30},
            },
            "total_files": 3,
            "total_bytes": 600,
            "total_lines": 60,
        }
        result = format_tree(data)
        assert result == """main.py (100B, 10 lines)
src
├── utils.py (200B, 20 lines)
└── lib
    └── helper.py (300B, 30 lines)

3 files, 600B, 60 lines"""

    def test_tree_binary_file_no_lines(self):
        data = {
            "root": "/home/user/project",
            "files": {
                "main.py": {"size": 1024, "lines": 50},
                "logo.png": {"size": 2048},
            },
            "total_files": 2,
            "total_bytes": 3072,
            "total_lines": 50,
        }
        result = format_tree(data)
        assert result == """logo.png (2.0KB)
main.py (1.0KB, 50 lines)

2 files, 3.0KB, 50 lines"""

    def test_tree_empty(self):
        data = {
            "root": "/home/user/project",
            "files": {},
            "total_files": 0,
            "total_bytes": 0,
            "total_lines": 0,
        }
        result = format_tree(data)
        assert result == "0 files, 0B"

    def test_tree_single_symbol_singular(self):
        data = {
            "root": "/home/user/project",
            "files": {
                "main.py": {
                    "size": 512,
                    "lines": 25,
                    "symbols": {"class": 1, "function": 1, "method": 1},
                },
            },
            "total_files": 1,
            "total_bytes": 512,
            "total_lines": 25,
        }
        result = format_tree(data)
        assert result == """main.py (512B, 25 lines, 1 class, 1 function, 1 method)

1 files, 512B, 25 lines"""


class TestFormatCallTree:
    def test_outgoing_calls(self):
        data = {
            "name": "main",
            "kind": "Function",
            "detail": None,
            "path": "main.py",
            "line": 10,
            "column": 0,
            "calls": [
                {
                    "name": "helper",
                    "kind": "Function",
                    "detail": None,
                    "path": "utils.py",
                    "line": 5,
                    "column": 0,
                    "from_ranges": [{"line": 12, "column": 4}],
                    "calls": [],
                },
            ],
        }
        result = format_output(data, "plain")
        assert result == """\
main.py:10 [Function] main

Outgoing calls:
  └── utils.py:5 [Function] helper"""

    def test_incoming_calls(self):
        data = {
            "name": "helper",
            "kind": "Function",
            "detail": None,
            "path": "utils.py",
            "line": 5,
            "column": 0,
            "called_by": [
                {
                    "name": "main",
                    "kind": "Function",
                    "detail": None,
                    "path": "main.py",
                    "line": 10,
                    "column": 0,
                    "call_sites": [{"line": 12, "column": 4}],
                    "called_by": [],
                },
            ],
        }
        result = format_output(data, "plain")
        assert result == """\
utils.py:5 [Function] helper

Incoming calls:
  └── main.py:10 [Function] main"""

    def test_nested_outgoing_calls(self):
        data = {
            "name": "main",
            "kind": "Function",
            "detail": None,
            "path": "main.py",
            "line": 10,
            "column": 0,
            "calls": [
                {
                    "name": "foo",
                    "kind": "Function",
                    "detail": None,
                    "path": "utils.py",
                    "line": 5,
                    "column": 0,
                    "from_ranges": [],
                    "calls": [
                        {
                            "name": "bar",
                            "kind": "Function",
                            "detail": None,
                            "path": "utils.py",
                            "line": 15,
                            "column": 0,
                            "from_ranges": [],
                            "calls": [],
                        },
                    ],
                },
                {
                    "name": "baz",
                    "kind": "Function",
                    "detail": None,
                    "path": "utils.py",
                    "line": 25,
                    "column": 0,
                    "from_ranges": [],
                    "calls": [],
                },
            ],
        }
        result = format_output(data, "plain")
        assert result == """\
main.py:10 [Function] main

Outgoing calls:
  ├── utils.py:5 [Function] foo
  │   └── utils.py:15 [Function] bar
  └── utils.py:25 [Function] baz"""


class TestFormatCallPath:
    def test_path_found(self):
        data = {
            "found": True,
            "path": [
                {
                    "name": "main",
                    "kind": "Function",
                    "detail": None,
                    "path": "main.py",
                    "line": 10,
                    "column": 0,
                },
                {
                    "name": "helper",
                    "kind": "Function",
                    "detail": None,
                    "path": "utils.py",
                    "line": 5,
                    "column": 0,
                },
            ],
        }
        result = format_output(data, "plain")
        assert result == """\
Call path:
main.py:10 [Function] main
  → utils.py:5 [Function] helper"""

    def test_path_not_found(self):
        data = {
            "found": False,
            "from": {"name": "foo", "kind": "Function", "path": "a.py", "line": 1},
            "to": {"name": "bar", "kind": "Function", "path": "b.py", "line": 1},
            "message": "No call path found from 'foo' to 'bar' within depth 3",
        }
        result = format_output(data, "plain")
        assert result == "No call path found from 'foo' to 'bar' within depth 3"


class TestFormatOutput:
    def test_json_output(self):
        data = {"key": "value"}
        result = format_output(data, "json")
        assert '"key": "value"' in result

    def test_plain_output(self):
        data = {"contents": "Hello world"}
        result = format_output(data, "plain")
        assert "Hello world" in result
