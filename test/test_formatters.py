import pytest

from lspcmd.output.formatters import (
    format_output,
    format_locations,
    format_symbols,
    format_code_actions,
    format_session,
    format_tree,
    format_call_tree,
    format_call_path,
    _is_stdlib_path,
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

    def test_stdlib_paths_hidden(self):
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
                    "calls": [
                        {
                            "name": "len",
                            "kind": "Function",
                            "detail": None,
                            "path": "/usr/lib/basedpyright/typeshed-fallback/stdlib/builtins.pyi",
                            "line": 100,
                            "column": 0,
                            "calls": [],
                        },
                    ],
                },
                {
                    "name": "Sprintf",
                    "kind": "Function",
                    "detail": "fmt",
                    "path": "/opt/homebrew/Cellar/go/1.25/libexec/src/fmt/print.go",
                    "line": 237,
                    "column": 0,
                    "calls": [],
                },
            ],
        }
        result = format_output(data, "plain")
        assert result == """\
main.py:10 [Function] main

Outgoing calls:
  ├── utils.py:5 [Function] helper
  │   └── [Function] len
  └── [Function] Sprintf (fmt)"""


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


class TestIsStdlibPath:
    def test_python_typeshed_stdlib(self):
        assert _is_stdlib_path("/Users/foo/.local/share/uv/tools/basedpyright/lib/python3.14/site-packages/basedpyright/dist/typeshed-fallback/stdlib/builtins.pyi")
        assert _is_stdlib_path("/path/to/typeshed/stdlib/collections/__init__.pyi")

    def test_python_site_packages_not_stdlib(self):
        assert not _is_stdlib_path(".venv/lib/python3.14/site-packages/click/core.py")
        assert not _is_stdlib_path("/Users/foo/.local/lib/python3.14/site-packages/requests/api.py")

    def test_go_stdlib(self):
        assert _is_stdlib_path("/opt/homebrew/Cellar/go/1.25.5/libexec/src/fmt/print.go")
        assert _is_stdlib_path("/usr/local/go/libexec/src/io/io.go")

    def test_go_third_party_not_stdlib(self):
        assert not _is_stdlib_path("/Users/foo/go/pkg/mod/github.com/gin-gonic/gin@v1.9.0/gin.go")
        assert not _is_stdlib_path("/home/user/project/vendor/github.com/pkg/errors/errors.go")

    def test_typescript_lib_dts(self):
        assert _is_stdlib_path("/Users/foo/.nvm/versions/node/v25.2.1/lib/node_modules/typescript/lib/lib.dom.d.ts")
        assert _is_stdlib_path("/usr/lib/node_modules/typescript/lib/lib.es5.d.ts")
        assert _is_stdlib_path("/path/to/lib.es2020.d.ts")

    def test_typescript_node_modules_not_stdlib(self):
        assert not _is_stdlib_path("node_modules/lodash/index.d.ts")
        assert not _is_stdlib_path("/Users/foo/project/node_modules/@types/node/index.d.ts")

    def test_rust_stdlib(self):
        assert _is_stdlib_path("/Users/foo/.rustup/toolchains/stable-aarch64-apple-darwin/lib/rustlib/src/rust/library/alloc/src/string.rs")
        assert _is_stdlib_path("/home/user/.rustup/toolchains/nightly-x86_64-unknown-linux-gnu/lib/rustlib/src/rust/library/core/src/iter/mod.rs")

    def test_rust_cargo_not_stdlib(self):
        assert not _is_stdlib_path("/Users/foo/.cargo/registry/src/github.com-1ecc6299db9ec823/serde-1.0.0/src/lib.rs")

    def test_project_files_not_stdlib(self):
        assert not _is_stdlib_path("src/main.py")
        assert not _is_stdlib_path("main.go")
        assert not _is_stdlib_path("/home/user/project/src/lib.rs")
        assert not _is_stdlib_path("src/main.ts")
