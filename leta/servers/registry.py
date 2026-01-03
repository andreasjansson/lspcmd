import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ..utils.text import get_language_id


def _get_extended_path() -> str:
    home = os.path.expanduser("~")
    extra_paths = [
        f"{home}/.gem/bin",
        f"{home}/go/bin",
        f"{home}/.cargo/bin",
        f"{home}/.local/bin",
        "/usr/local/bin",
        "/opt/homebrew/bin",
    ]
    current_path = os.environ.get("PATH", "")
    return ":".join(extra_paths) + ":" + current_path


@dataclass
class ServerConfig:
    name: str
    command: list[str]
    languages: list[str]
    file_patterns: list[str] = field(default_factory=list)
    install_cmd: str | None = None
    root_markers: list[str] = field(default_factory=list)


SERVERS: dict[str, list[ServerConfig]] = {
    "python": [
        ServerConfig(
            name="basedpyright",
            command=["basedpyright-langserver", "--stdio"],
            languages=["python"],
            file_patterns=["*.py", "*.pyi"],
            install_cmd="npm install -g @anthropic/basedpyright",
            root_markers=["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "pyrightconfig.json"],
        ),
        ServerConfig(
            name="pylsp",
            command=["pylsp"],
            languages=["python"],
            file_patterns=["*.py", "*.pyi"],
            install_cmd="pip install python-lsp-server",
            root_markers=["pyproject.toml", "setup.py", "setup.cfg"],
        ),
        ServerConfig(
            name="ruff-lsp",
            command=["ruff-lsp"],
            languages=["python"],
            file_patterns=["*.py", "*.pyi"],
            install_cmd="pip install ruff-lsp",
            root_markers=["pyproject.toml", "ruff.toml"],
        ),
    ],
    "rust": [
        ServerConfig(
            name="rust-analyzer",
            command=["rust-analyzer"],
            languages=["rust"],
            file_patterns=["*.rs"],
            install_cmd="rustup component add rust-analyzer",
            root_markers=["Cargo.toml"],
        ),
    ],
    "typescript": [
        ServerConfig(
            name="typescript-language-server",
            command=["typescript-language-server", "--stdio"],
            languages=["typescript", "typescriptreact", "javascript", "javascriptreact"],
            file_patterns=["*.ts", "*.tsx", "*.js", "*.jsx"],
            install_cmd="npm install -g typescript-language-server typescript",
            root_markers=["package.json", "tsconfig.json", "jsconfig.json"],
        ),
    ],
    "go": [
        ServerConfig(
            name="gopls",
            command=["gopls"],
            languages=["go"],
            file_patterns=["*.go"],
            install_cmd="go install golang.org/x/tools/gopls@latest",
            root_markers=["go.mod", "go.sum"],
        ),
    ],
    "c": [
        ServerConfig(
            name="clangd",
            command=["clangd"],
            languages=["c", "cpp"],
            file_patterns=["*.c", "*.h", "*.cpp", "*.hpp", "*.cc", "*.cxx"],
            install_cmd="brew install llvm (macOS) or apt install clangd (Ubuntu)",
            root_markers=["compile_commands.json", "CMakeLists.txt", "Makefile"],
        ),
    ],
    "java": [
        ServerConfig(
            name="jdtls",
            command=["jdtls"],
            languages=["java"],
            file_patterns=["*.java"],
            root_markers=["pom.xml", "build.gradle", ".project"],
        ),
    ],
    "ruby": [
        ServerConfig(
            name="solargraph",
            command=["solargraph", "stdio"],
            languages=["ruby"],
            file_patterns=["*.rb", "*.rake", "Gemfile", "Rakefile"],
            install_cmd="gem install solargraph",
            root_markers=["Gemfile", ".ruby-version", "Rakefile"],
        ),
    ],
    "php": [
        ServerConfig(
            name="intelephense",
            command=["intelephense", "--stdio"],
            languages=["php"],
            file_patterns=["*.php", "*.phtml"],
            install_cmd="npm install -g intelephense",
            root_markers=["composer.json", "composer.lock", "index.php"],
        ),
    ],
    "elixir": [
        ServerConfig(
            name="elixir-ls",
            command=["elixir-ls"],
            languages=["elixir"],
            file_patterns=["*.ex", "*.exs"],
            root_markers=["mix.exs"],
        ),
    ],
    "haskell": [
        ServerConfig(
            name="haskell-language-server",
            command=["haskell-language-server-wrapper", "--lsp"],
            languages=["haskell"],
            file_patterns=["*.hs"],
            install_cmd="ghcup install hls",
            root_markers=["*.cabal", "stack.yaml", "cabal.project"],
        ),
    ],
    "ocaml": [
        ServerConfig(
            name="ocamllsp",
            command=["ocamllsp"],
            languages=["ocaml"],
            file_patterns=["*.ml", "*.mli"],
            install_cmd="opam install ocaml-lsp-server",
            root_markers=["dune-project", "*.opam"],
        ),
    ],
    "lua": [
        ServerConfig(
            name="lua-language-server",
            command=["lua-language-server"],
            languages=["lua"],
            file_patterns=["*.lua"],
            install_cmd="brew install lua-language-server",
            root_markers=[".luarc.json", ".luarc.jsonc"],
        ),
    ],
    "zig": [
        ServerConfig(
            name="zls",
            command=["zls"],
            languages=["zig"],
            file_patterns=["*.zig"],
            install_cmd="brew install zls",
            root_markers=["build.zig"],
        ),
    ],
    "yaml": [
        ServerConfig(
            name="yaml-language-server",
            command=["yaml-language-server", "--stdio"],
            languages=["yaml"],
            file_patterns=["*.yaml", "*.yml"],
            install_cmd="npm install -g yaml-language-server",
        ),
    ],
    "json": [
        ServerConfig(
            name="vscode-json-languageserver",
            command=["vscode-json-languageserver", "--stdio"],
            languages=["json"],
            file_patterns=["*.json"],
            install_cmd="npm install -g vscode-langservers-extracted",
        ),
    ],
    "html": [
        ServerConfig(
            name="vscode-html-languageserver",
            command=["vscode-html-language-server", "--stdio"],
            languages=["html"],
            file_patterns=["*.html", "*.htm"],
            install_cmd="npm install -g vscode-langservers-extracted",
        ),
    ],
    "css": [
        ServerConfig(
            name="vscode-css-languageserver",
            command=["vscode-css-language-server", "--stdio"],
            languages=["css", "scss", "less"],
            file_patterns=["*.css", "*.scss", "*.less"],
            install_cmd="npm install -g vscode-langservers-extracted",
        ),
    ],
}


from typing import Any, Mapping


def get_server_for_file(path: str | Path, config: Mapping[str, Any] | None = None) -> ServerConfig | None:
    language_id = get_language_id(path)
    return get_server_for_language(language_id, config)


def get_server_for_language(language_id: str, config: Mapping[str, Any] | None = None) -> ServerConfig | None:
    language_to_key = {
        "python": "python",
        "rust": "rust",
        "typescript": "typescript",
        "typescriptreact": "typescript",
        "javascript": "typescript",
        "javascriptreact": "typescript",
        "go": "go",
        "c": "c",
        "cpp": "c",
        "java": "java",
        "ruby": "ruby",
        "php": "php",
        "elixir": "elixir",
        "haskell": "haskell",
        "ocaml": "ocaml",
        "lua": "lua",
        "zig": "zig",
        "yaml": "yaml",
        "json": "json",
        "html": "html",
        "css": "css",
        "scss": "css",
        "less": "css",
    }

    key = language_to_key.get(language_id)
    if not key:
        return None

    servers = SERVERS.get(key, [])
    if not servers:
        return None

    preferred = None
    if config:
        server_config = config.get("servers", {}).get(key, {})
        preferred = server_config.get("preferred")

    if preferred:
        for server in servers:
            if server.name == preferred and is_server_installed(server):
                return server

    for server in servers:
        if is_server_installed(server):
            return server

    return servers[0] if servers else None


def is_server_installed(server: ServerConfig) -> bool:
    return shutil.which(server.command[0], path=_get_extended_path()) is not None


def get_all_servers() -> list[ServerConfig]:
    result = []
    for servers in SERVERS.values():
        result.extend(servers)
    return result
