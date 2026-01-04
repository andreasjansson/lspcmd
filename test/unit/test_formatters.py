import pytest

from leta.daemon.rpc import (
    CallNode,
    CallsResult,
    CacheInfo,
    DescribeSessionResult,
    FileInfo,
    FilesResult,
    GrepResult,
    LocationInfo,
    ReferencesResult,
    SymbolInfo,
    WorkspaceInfo,
)
from leta.output.formatters import (
    format_result,
    format_model,
    _is_stdlib_path,
)


class TestFormatLocations:
    def test_simple_location(self):
        result = ReferencesResult(
            locations=[LocationInfo(path="/home/user/main.py", line=10, column=5)]
        )
        output = format_result(result)
        assert "/home/user/main.py:10" in output

    def test_multiple_locations(self):
        result = ReferencesResult(
            locations=[
                LocationInfo(path="/home/user/main.py", line=10, column=5),
                LocationInfo(path="/home/user/utils.py", line=20, column=0),
            ]
        )
        output = format_result(result)
        assert "/home/user/main.py:10" in output
        assert "/home/user/utils.py:20" in output

    def test_location_with_context(self):
        result = ReferencesResult(
            locations=[
                LocationInfo(
                    path="/home/user/main.py",
                    line=2,
                    column=0,
                    context_lines=["line1", "line2", "line3"],
                    context_start=1,
                )
            ]
        )
        output = format_result(result)
        assert "/home/user/main.py:1-3" in output
        assert "line1" in output
        assert "line2" in output
        assert "line3" in output


class TestFormatSymbols:
    def test_simple_symbol(self):
        result = GrepResult(
            symbols=[
                SymbolInfo(
                    name="main",
                    kind="Function",
                    path="/home/user/main.py",
                    line=10,
                )
            ]
        )
        output = format_result(result)
        assert "main" in output
        assert "Function" in output
        assert "/home/user/main.py:10" in output

    def test_symbol_with_detail(self):
        result = GrepResult(
            symbols=[
                SymbolInfo(
                    name="User",
                    kind="Class",
                    path="/home/user/main.py",
                    line=5,
                    detail="class User(BaseModel)",
                )
            ]
        )
        output = format_result(result)
        assert "User" in output
        assert "class User(BaseModel)" in output

    def test_symbol_with_container(self):
        result = GrepResult(
            symbols=[
                SymbolInfo(
                    name="get_name",
                    kind="Method",
                    path="/home/user/main.py",
                    line=15,
                    container="User",
                )
            ]
        )
        output = format_result(result)
        assert "get_name" in output
        assert "in User" in output

    def test_grep_with_warning(self):
        result = GrepResult(symbols=[], warning="No symbols found")
        output = format_result(result)
        assert output == "Warning: No symbols found"


class TestFormatSession:
    def test_empty_session(self):
        result = DescribeSessionResult(
            daemon_pid=12345,
            caches={},
            workspaces=[],
        )
        output = format_result(result)
        assert "No active workspaces" in output
        assert "Daemon PID: 12345" in output

    def test_session_with_workspace(self):
        result = DescribeSessionResult(
            daemon_pid=12345,
            caches={},
            workspaces=[
                WorkspaceInfo(
                    root="/home/user/project",
                    language="python",
                    server_pid=67890,
                    open_documents=["file:///home/user/project/main.py"],
                )
            ],
        )
        output = format_result(result)
        assert "Daemon PID: 12345" in output
        assert "/home/user/project" in output
        assert "python" in output
        assert "running" in output
        assert "PID 67890" in output

    def test_session_with_caches(self):
        result = DescribeSessionResult(
            daemon_pid=12345,
            caches={
                "hover_cache": CacheInfo(current_bytes=1024, max_bytes=10240, entries=5),
                "symbol_cache": CacheInfo(current_bytes=2048, max_bytes=20480, entries=10),
            },
            workspaces=[],
        )
        output = format_result(result)
        assert "Caches:" in output
        assert "Hover:" in output
        assert "Symbol:" in output


class TestFormatTree:
    def test_simple_tree(self):
        result = FilesResult(
            files={
                "main.py": FileInfo(path="main.py", bytes=1024, lines=50),
                "utils.py": FileInfo(path="utils.py", bytes=512, lines=25),
            },
            total_files=2,
            total_bytes=1536,
            total_lines=75,
        )
        output = format_result(result)
        assert (
            output
            == """main.py (1.0KB, 50 lines)
utils.py (512B, 25 lines)

2 files, 1.5KB, 75 lines"""
        )

    def test_tree_with_symbols(self):
        result = FilesResult(
            files={
                "main.py": FileInfo(
                    path="main.py",
                    bytes=1024,
                    lines=50,
                    symbols={"class": 2, "function": 3, "method": 5},
                ),
            },
            total_files=1,
            total_bytes=1024,
            total_lines=50,
        )
        output = format_result(result)
        assert (
            output
            == """main.py (1.0KB, 50 lines, 2 classes, 3 functions, 5 methods)

1 files, 1.0KB, 50 lines"""
        )

    def test_tree_with_nested_directories(self):
        result = FilesResult(
            files={
                "main.py": FileInfo(path="main.py", bytes=100, lines=10),
                "src/utils.py": FileInfo(path="src/utils.py", bytes=200, lines=20),
                "src/lib/helper.py": FileInfo(path="src/lib/helper.py", bytes=300, lines=30),
            },
            total_files=3,
            total_bytes=600,
            total_lines=60,
        )
        output = format_result(result)
        assert (
            output
            == """main.py (100B, 10 lines)
src
├── utils.py (200B, 20 lines)
└── lib
    └── helper.py (300B, 30 lines)

3 files, 600B, 60 lines"""
        )

    def test_tree_empty(self):
        result = FilesResult(
            files={},
            total_files=0,
            total_bytes=0,
            total_lines=0,
        )
        output = format_result(result)
        assert output == "0 files, 0B"

    def test_tree_single_symbol_singular(self):
        result = FilesResult(
            files={
                "main.py": FileInfo(
                    path="main.py",
                    bytes=512,
                    lines=25,
                    symbols={"class": 1, "function": 1, "method": 1},
                ),
            },
            total_files=1,
            total_bytes=512,
            total_lines=25,
        )
        output = format_result(result)
        assert (
            output
            == """main.py (512B, 25 lines, 1 class, 1 function, 1 method)

1 files, 512B, 25 lines"""
        )


class TestFormatCallTree:
    def test_outgoing_calls(self):
        result = CallsResult(
            root=CallNode(
                name="main",
                kind="Function",
                path="main.py",
                line=10,
                column=0,
                calls=[
                    CallNode(
                        name="helper",
                        kind="Function",
                        path="utils.py",
                        line=5,
                        column=0,
                        calls=[],
                    ),
                ],
            )
        )
        output = format_result(result)
        assert (
            output
            == """\
main.py:10 [Function] main

Outgoing calls:
  └── utils.py:5 [Function] helper"""
        )

    def test_incoming_calls(self):
        result = CallsResult(
            root=CallNode(
                name="helper",
                kind="Function",
                path="utils.py",
                line=5,
                column=0,
                called_by=[
                    CallNode(
                        name="main",
                        kind="Function",
                        path="main.py",
                        line=10,
                        column=0,
                        called_by=[],
                    ),
                ],
            )
        )
        output = format_result(result)
        assert (
            output
            == """\
utils.py:5 [Function] helper

Incoming calls:
  └── main.py:10 [Function] main"""
        )

    def test_nested_outgoing_calls(self):
        result = CallsResult(
            root=CallNode(
                name="main",
                kind="Function",
                path="main.py",
                line=10,
                column=0,
                calls=[
                    CallNode(
                        name="foo",
                        kind="Function",
                        path="utils.py",
                        line=5,
                        column=0,
                        calls=[
                            CallNode(
                                name="bar",
                                kind="Function",
                                path="utils.py",
                                line=15,
                                column=0,
                                calls=[],
                            ),
                        ],
                    ),
                    CallNode(
                        name="baz",
                        kind="Function",
                        path="utils.py",
                        line=25,
                        column=0,
                        calls=[],
                    ),
                ],
            )
        )
        output = format_result(result)
        assert (
            output
            == """\
main.py:10 [Function] main

Outgoing calls:
  ├── utils.py:5 [Function] foo
  │   └── utils.py:15 [Function] bar
  └── utils.py:25 [Function] baz"""
        )

    def test_stdlib_paths_hidden(self):
        result = CallsResult(
            root=CallNode(
                name="main",
                kind="Function",
                path="main.py",
                line=10,
                column=0,
                calls=[
                    CallNode(
                        name="helper",
                        kind="Function",
                        path="utils.py",
                        line=5,
                        column=0,
                        calls=[
                            CallNode(
                                name="len",
                                kind="Function",
                                path="/usr/lib/basedpyright/typeshed-fallback/stdlib/builtins.pyi",
                                line=100,
                                column=0,
                                calls=[],
                            ),
                        ],
                    ),
                    CallNode(
                        name="Sprintf",
                        kind="Function",
                        detail="fmt",
                        path="/opt/homebrew/Cellar/go/1.25/libexec/src/fmt/print.go",
                        line=237,
                        column=0,
                        calls=[],
                    ),
                ],
            )
        )
        output = format_result(result)
        assert (
            output
            == """\
main.py:10 [Function] main

Outgoing calls:
  ├── utils.py:5 [Function] helper
  │   └── [Function] len
  └── [Function] Sprintf (fmt)"""
        )

    def test_calls_with_error(self):
        result = CallsResult(error="Call hierarchy not supported")
        output = format_result(result)
        assert output == "Error: Call hierarchy not supported"

    def test_calls_with_message(self):
        result = CallsResult(message="No call path found from 'foo' to 'bar' within depth 3")
        output = format_result(result)
        assert output == "No call path found from 'foo' to 'bar' within depth 3"


class TestFormatCallPath:
    def test_path_found(self):
        result = CallsResult(
            path=[
                CallNode(
                    name="main",
                    kind="Function",
                    path="main.py",
                    line=10,
                    column=0,
                ),
                CallNode(
                    name="helper",
                    kind="Function",
                    path="utils.py",
                    line=5,
                    column=0,
                ),
            ]
        )
        output = format_result(result)
        assert (
            output
            == """\
Call path:
main.py:10 [Function] main
  → utils.py:5 [Function] helper"""
        )

    def test_path_not_found(self):
        result = CallsResult(
            message="No call path found from 'foo' to 'bar' within depth 3"
        )
        output = format_result(result)
        assert output == "No call path found from 'foo' to 'bar' within depth 3"


class TestFormatResult:
    def test_json_output(self):
        result = GrepResult(symbols=[SymbolInfo(name="foo", kind="Function", path="a.py", line=1)])
        output = format_result(result, "json")
        assert '"name": "foo"' in output
        assert '"kind": "Function"' in output

    def test_plain_output(self):
        result = GrepResult(symbols=[SymbolInfo(name="foo", kind="Function", path="a.py", line=1)])
        output = format_result(result, "plain")
        assert "foo" in output
        assert "Function" in output


class TestIsStdlibPath:
    def test_python_typeshed_stdlib(self):
        assert _is_stdlib_path(
            "/Users/foo/.local/share/uv/tools/basedpyright/lib/python3.14/site-packages/basedpyright/dist/typeshed-fallback/stdlib/builtins.pyi"
        )
        assert _is_stdlib_path("/path/to/typeshed/stdlib/collections/__init__.pyi")

    def test_python_site_packages_not_stdlib(self):
        assert not _is_stdlib_path(".venv/lib/python3.14/site-packages/click/core.py")
        assert not _is_stdlib_path(
            "/Users/foo/.local/lib/python3.14/site-packages/requests/api.py"
        )

    def test_go_stdlib(self):
        assert _is_stdlib_path(
            "/opt/homebrew/Cellar/go/1.25.5/libexec/src/fmt/print.go"
        )
        assert _is_stdlib_path("/usr/local/go/libexec/src/io/io.go")

    def test_go_third_party_not_stdlib(self):
        assert not _is_stdlib_path(
            "/Users/foo/go/pkg/mod/github.com/gin-gonic/gin@v1.9.0/gin.go"
        )
        assert not _is_stdlib_path(
            "/home/user/project/vendor/github.com/pkg/errors/errors.go"
        )

    def test_typescript_lib_dts(self):
        assert _is_stdlib_path(
            "/Users/foo/.nvm/versions/node/v25.2.1/lib/node_modules/typescript/lib/lib.dom.d.ts"
        )
        assert _is_stdlib_path("/usr/lib/node_modules/typescript/lib/lib.es5.d.ts")
        assert _is_stdlib_path("/path/to/lib.es2020.d.ts")

    def test_typescript_node_modules_not_stdlib(self):
        assert not _is_stdlib_path("node_modules/lodash/index.d.ts")
        assert not _is_stdlib_path(
            "/Users/foo/project/node_modules/@types/node/index.d.ts"
        )

    def test_rust_stdlib(self):
        assert _is_stdlib_path(
            "/Users/foo/.rustup/toolchains/stable-aarch64-apple-darwin/lib/rustlib/src/rust/library/alloc/src/string.rs"
        )
        assert _is_stdlib_path(
            "/home/user/.rustup/toolchains/nightly-x86_64-unknown-linux-gnu/lib/rustlib/src/rust/library/core/src/iter/mod.rs"
        )

    def test_rust_cargo_not_stdlib(self):
        assert not _is_stdlib_path(
            "/Users/foo/.cargo/registry/src/github.com-1ecc6299db9ec823/serde-1.0.0/src/lib.rs"
        )

    def test_project_files_not_stdlib(self):
        assert not _is_stdlib_path("src/main.py")
        assert not _is_stdlib_path("main.go")
        assert not _is_stdlib_path("/home/user/project/src/lib.rs")
        assert not _is_stdlib_path("src/main.ts")
