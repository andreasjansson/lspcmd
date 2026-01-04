import pytest

from leta.servers.registry import (
    get_server_for_file,
    get_server_for_language,
    SERVERS,
)


class TestGetServerForFile:
    def test_python_file(self):
        server = get_server_for_file("main.py")
        assert server is not None
        assert "python" in server.languages

    def test_rust_file(self):
        server = get_server_for_file("main.rs")
        assert server is not None
        assert "rust" in server.languages

    def test_typescript_file(self):
        server = get_server_for_file("app.ts")
        assert server is not None
        assert "typescript" in server.languages

    def test_javascript_file(self):
        server = get_server_for_file("app.js")
        assert server is not None
        assert "javascript" in server.languages

    def test_go_file(self):
        server = get_server_for_file("main.go")
        assert server is not None
        assert "go" in server.languages

    def test_unknown_file(self):
        server = get_server_for_file("file.xyz")
        assert server is None


class TestGetServerForLanguage:
    def test_python(self):
        server = get_server_for_language("python")
        assert server is not None
        assert server.name in ["basedpyright", "pyright", "pylsp", "ruff-lsp"]

    def test_rust(self):
        server = get_server_for_language("rust")
        assert server is not None
        assert server.name == "rust-analyzer"

    def test_typescript(self):
        server = get_server_for_language("typescript")
        assert server is not None
        assert server.name == "typescript-language-server"

    def test_preferred_server(self):
        config = {"servers": {"python": {"preferred": "pylsp"}}}
        server = get_server_for_language("python", config)
        assert server is not None


class TestServerConfigs:
    def test_all_servers_have_command(self):
        for lang, servers in SERVERS.items():
            for server in servers:
                assert len(server.command) > 0
                assert isinstance(server.command[0], str)

    def test_all_servers_have_languages(self):
        for lang, servers in SERVERS.items():
            for server in servers:
                assert len(server.languages) > 0
