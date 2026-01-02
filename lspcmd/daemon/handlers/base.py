"""Base handler context and shared utilities."""

from __future__ import annotations

import fnmatch
import hashlib
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from ...cache import LMDBCache
from ...lsp.types import (
    SymbolKind,
    Location,
    LocationLink,
    TypeHierarchyItem,
    DocumentSymbol,
    SymbolInformation,
    DefinitionResponse,
    DocumentSymbolParams,
    TextDocumentPositionParams,
    TextDocumentIdentifier,
    Position,
    MarkupContent,
)
from ...utils.text import get_language_id, read_file_content, get_lines_around
from ...utils.uri import uri_to_path

if TYPE_CHECKING:
    from ..session import Session, Workspace, OpenDocument

logger = logging.getLogger(__name__)


class SymbolDict(TypedDict, total=False):
    name: str
    kind: str
    path: str
    line: int
    column: int
    container: str | None
    detail: str | None
    documentation: str | None
    range_start_line: int | None
    range_end_line: int | None


class LocationDict(TypedDict, total=False):
    path: str
    line: int
    column: int
    context_lines: list[str]
    context_start: int
    name: str
    kind: str | None
    detail: str | None

DEFAULT_EXCLUDE_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    "target", "build", "dist", ".tox", ".mypy_cache", ".pytest_cache",
    ".eggs", ".cache", ".coverage", ".hypothesis", ".nox", ".ruff_cache",
    "__pypackages__", ".pants.d", ".pyre", ".pytype",
    "vendor", "third_party", ".bundle",
    ".next", ".nuxt", ".svelte-kit", ".turbo", ".parcel-cache",
    "coverage", ".nyc_output",
    ".zig-cache",
}

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tiff", ".tif",
    ".svg", ".pdf", ".eps", ".ps",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".a", ".o", ".lib",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp3", ".mp4", ".wav", ".ogg", ".flac", ".avi", ".mov", ".mkv", ".webm",
    ".pyc", ".pyo", ".class", ".jar", ".war", ".ear",
    ".db", ".sqlite", ".sqlite3",
    ".bin", ".dat", ".pak", ".bundle",
    ".lock",
}


class HandlerContext:
    """Context object providing access to session, caches, and utilities."""
    
    def __init__(
        self,
        session: Session,
        hover_cache: LMDBCache,
        symbol_cache: LMDBCache,
    ):
        self.session = session
        self.hover_cache = hover_cache
        self.symbol_cache = symbol_cache

    def relative_path(self, path: Path, workspace_root: Path) -> str:
        try:
            return str(path.resolve().relative_to(workspace_root.resolve()))
        except ValueError:
            return str(path)

    async def get_workspace_and_document(
        self, params: dict[str, str]
    ) -> tuple[Workspace, OpenDocument, Path]:
        path = Path(params["path"]).resolve()
        workspace_root = Path(params["workspace_root"]).resolve()
        workspace = await self.session.get_or_create_workspace(path, workspace_root)
        doc = await workspace.ensure_document_open(path)
        return workspace, doc, path

    def parse_position(self, params: dict[str, int]) -> tuple[int, int]:
        line = params["line"] - 1
        column = params["column"]
        return line, column

    def get_file_sha(self, file_path: Path) -> str:
        try:
            content = file_path.read_bytes()
            return hashlib.sha256(content).hexdigest()[:16]
        except Exception:
            return ""

    async def get_file_symbols_cached(
        self, workspace: Workspace, workspace_root: Path, file_path: Path
    ) -> list[SymbolDict]:
        assert workspace.client
        file_sha = self.get_file_sha(file_path)
        cache_key = (str(file_path), str(workspace_root), file_sha)

        cached = self.symbol_cache.get(cache_key)
        if cached is not None:
            return cached

        symbols: list[SymbolDict] = []
        try:
            doc = await workspace.ensure_document_open(file_path)
            result = await workspace.client.send_request(
                "textDocument/documentSymbol",
                DocumentSymbolParams(textDocument=TextDocumentIdentifier(uri=doc.uri)),
            )
            if result:
                rel_path = self.relative_path(file_path, workspace_root)
                flatten_symbols(result, rel_path, symbols)

            self.symbol_cache[cache_key] = symbols
        except Exception as e:
            logger.warning(f"Failed to get symbols for {file_path}: {e}")
            self.symbol_cache[cache_key] = []

        return symbols

    async def collect_symbols_from_files(
        self,
        workspace: Workspace,
        workspace_root: Path,
        files: list[Path],
        close_after: bool = True,
    ) -> list[SymbolDict]:
        symbols = []
        opened_files = []

        for file_path in files:
            file_symbols = await self.get_file_symbols_cached(
                workspace, workspace_root, file_path
            )
            symbols.extend(file_symbols)
            if str(file_path) in workspace.open_documents:
                opened_files.append(file_path)

        if close_after:
            for file_path in opened_files:
                await workspace.close_document(file_path)

        return symbols

    async def collect_symbols_for_paths(
        self, paths: list[Path], workspace_root: Path
    ) -> list[SymbolDict]:
        files_by_language: dict[str, list[Path]] = {}
        for file_path in paths:
            if not file_path.exists():
                continue
            lang = get_language_id(file_path)
            if lang and lang != "plaintext":
                files_by_language.setdefault(lang, []).append(file_path)

        all_symbols = []
        for lang, files in files_by_language.items():
            try:
                workspace = await self.session.get_or_create_workspace(
                    files[0], workspace_root
                )
            except ValueError:
                continue

            if not workspace or not workspace.client:
                continue

            symbols = await self.collect_symbols_from_files(
                workspace, workspace_root, files
            )
            all_symbols.extend(symbols)

        return all_symbols

    async def collect_all_workspace_symbols(
        self, workspace_root: Path, query: str
    ) -> list[SymbolDict]:
        from ...servers.registry import get_server_for_language

        skip_dirs = {
            "node_modules", "__pycache__", ".git", "venv", ".venv",
            "build", "dist", ".tox", ".eggs",
        }
        excluded_languages = set(
            self.session.config.get("workspaces", {}).get("excluded_languages", [])
        )

        languages_found: dict[str, list[Path]] = {}
        for file_path in workspace_root.rglob("*"):
            if not file_path.is_file():
                continue
            if any(
                part.startswith(".") or part in skip_dirs or part.endswith(".egg-info")
                for part in file_path.parts
            ):
                continue

            lang_id = get_language_id(file_path)
            if lang_id == "plaintext" or lang_id in excluded_languages:
                continue

            server_config = get_server_for_language(lang_id, self.session.config)
            if server_config is None:
                continue

            if lang_id not in languages_found:
                languages_found[lang_id] = []
            languages_found[lang_id].append(file_path)

        all_symbols = []

        for lang_id, files in languages_found.items():
            workspace = await self.session.get_or_create_workspace_for_language(
                lang_id, workspace_root
            )

            if not workspace or not workspace.client:
                continue

            symbols = await self.collect_symbols_from_files(
                workspace, workspace_root, files
            )
            all_symbols.extend(symbols)

        return all_symbols

    async def get_symbol_documentation(
        self, workspace_root: Path, rel_path: str, line: int, column: int
    ) -> str | None:
        file_path = workspace_root / rel_path

        workspace = self.session.get_workspace_for_file(file_path)
        if not workspace or not workspace.client:
            return None

        try:
            file_sha = self.get_file_sha(file_path)
            cache_key = (str(file_path), line, column, file_sha)

            if cache_key in self.hover_cache:
                return self.hover_cache[cache_key] or None

            doc = await workspace.ensure_document_open(file_path)
            result = await workspace.client.send_request(
                "textDocument/hover",
                TextDocumentPositionParams(
                    textDocument=TextDocumentIdentifier(uri=doc.uri),
                    position=Position(line=line - 1, character=column),
                ),
            )

            if not result:
                self.hover_cache[cache_key] = ""
                return None

            contents = result.contents
            if isinstance(contents, MarkupContent):
                doc_str = contents.value
            elif isinstance(contents, list):
                doc_str = "\n".join(str(c) for c in contents)
            else:
                doc_str = str(contents) if contents else None

            self.hover_cache[cache_key] = doc_str or ""
            return doc_str
        except Exception as e:
            logger.debug(f"Failed to get hover for {rel_path}:{line}: {e}")
            return None

    def format_locations(
        self, result: DefinitionResponse,
        workspace_root: Path,
        context: int = 0,
    ) -> list[LocationDict]:
        if not result:
            return []

        items: list[Location | LocationLink]
        if isinstance(result, Location):
            items = [result]
        elif isinstance(result, list):
            items = result
        else:
            items = [result]

        locations: list[LocationDict] = []
        for item in items:
            if isinstance(item, LocationLink):
                uri = item.target_uri
                range_ = item.target_selection_range
            else:
                uri = item.uri
                range_ = item.range

            file_path = uri_to_path(uri)
            start_line = range_.start.line

            location: LocationDict = {
                "path": self.relative_path(file_path, workspace_root),
                "line": start_line + 1,
                "column": range_.start.character,
            }

            if context > 0 and file_path.exists():
                content = read_file_content(file_path)
                lines, start, end = get_lines_around(content, start_line, context)
                location["context_lines"] = lines
                location["context_start"] = start + 1

            locations.append(location)

        return locations

    def format_type_hierarchy_items(
        self,
        result: list[TypeHierarchyItem] | None,
        workspace_root: Path,
        context: int = 0,
    ) -> list[LocationDict]:
        if not result:
            return []

        locations: list[LocationDict] = []
        for item in result:
            uri = item.uri
            range_ = item.selection_range

            file_path = uri_to_path(uri)
            start_line = range_.start.line

            location: LocationDict = {
                "path": self.relative_path(file_path, workspace_root),
                "line": start_line + 1,
                "column": range_.start.character,
                "name": item.name,
                "kind": SymbolKind(item.kind).name,
                "detail": item.detail,
            }

            if context > 0 and file_path.exists():
                content = read_file_content(file_path)
                lines, start, end = get_lines_around(content, start_line, context)
                location["context_lines"] = lines
                location["context_start"] = start + 1

            locations.append(location)

        return locations

    def find_all_files_for_tree(
        self, workspace_root: Path, exclude_dirs: set[str]
    ) -> list[Path]:
        files = []
        for root, dirs, filenames in os.walk(workspace_root):
            dirs[:] = [
                d for d in dirs
                if d not in exclude_dirs and not d.endswith(".egg-info")
            ]

            for filename in filenames:
                if not filename.startswith("."):
                    files.append(Path(root) / filename)

        return files

    def group_files_by_language(
        self, files: list[Path]
    ) -> dict[str | None, list[Path]]:
        from ...servers.registry import get_server_for_language

        excluded_languages = set(
            self.session.config.get("workspaces", {}).get("excluded_languages", [])
        )

        result: dict[str | None, list[Path]] = {}
        for file_path in files:
            lang_id = get_language_id(file_path)
            if lang_id == "plaintext" or lang_id in excluded_languages:
                result.setdefault(None, []).append(file_path)
                continue

            server_config = get_server_for_language(lang_id, self.session.config)
            if server_config is None:
                result.setdefault(None, []).append(file_path)
            else:
                result.setdefault(lang_id, []).append(file_path)

        return result

    def find_all_source_files(self, workspace_root: Path) -> list[Path]:
        source_extensions = {
            ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs",
            ".java", ".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".rb",
            ".ex", ".exs", ".hs", ".ml", ".mli", ".lua", ".zig", ".php",
        }
        exclude_dirs = {
            ".git", "__pycache__", "node_modules", ".venv", "venv",
            "target", "build", "dist", ".tox", ".mypy_cache", ".pytest_cache",
            ".eggs", "*.egg-info",
        }

        files = []
        for root, dirs, filenames in os.walk(workspace_root):
            dirs[:] = [
                d for d in dirs
                if d not in exclude_dirs and not d.endswith(".egg-info")
            ]

            for filename in filenames:
                if Path(filename).suffix in source_extensions:
                    files.append(Path(root) / filename)

        return files

    def discover_languages(self, workspace_root: Path) -> list[str]:
        from ...servers.registry import get_server_for_language

        skip_dirs = {
            "node_modules", "__pycache__", ".git", "venv", ".venv",
            "build", "dist", ".tox", ".eggs",
        }
        excluded_languages = set(
            self.session.config.get("workspaces", {}).get("excluded_languages", [])
        )
        languages = set()

        for file_path in workspace_root.rglob("*"):
            if not file_path.is_file():
                continue
            if any(
                part.startswith(".") or part in skip_dirs or part.endswith(".egg-info")
                for part in file_path.parts
            ):
                continue

            lang_id = get_language_id(file_path)
            if lang_id == "plaintext" or lang_id in excluded_languages:
                continue

            server_config = get_server_for_language(lang_id, self.session.config)
            if server_config:
                languages.add(lang_id)

        return list(languages)


def flatten_symbols(
    items: list[DocumentSymbol] | list[SymbolInformation],
    file_path: str,
    output: list[SymbolDict],
    container: str | None = None,
) -> None:
    for item in items:
        if isinstance(item, SymbolInformation):
            loc_range = item.location.range
            output.append(
                {
                    "name": item.name,
                    "kind": SymbolKind(item.kind).name,
                    "path": file_path,
                    "line": loc_range.start.line + 1,
                    "column": loc_range.start.character,
                    "container": item.container_name,
                    "range_start_line": loc_range.start.line + 1,
                    "range_end_line": loc_range.end.line + 1,
                }
            )
        else:
            sel_range = item.selection_range
            full_range = item.range
            output.append(
                {
                    "name": item.name,
                    "kind": SymbolKind(item.kind).name,
                    "path": file_path,
                    "line": sel_range.start.line + 1,
                    "column": sel_range.start.character,
                    "container": container,
                    "detail": item.detail,
                    "range_start_line": full_range.start.line + 1,
                    "range_end_line": full_range.end.line + 1,
                }
            )
            if item.children:
                flatten_symbols(item.children, file_path, output, item.name)


class FoundSymbol(TypedDict):
    range_start: int
    range_end: int
    children: list[DocumentSymbol] | None


def find_symbol_at_line(
    symbols: list[DocumentSymbol] | list[SymbolInformation], line: int
) -> FoundSymbol | None:
    for sym in symbols:
        if isinstance(sym, DocumentSymbol):
            start = sym.range.start.line
            end = sym.range.end.line
            if start <= line <= end:
                if sym.children:
                    child = find_symbol_at_line(sym.children, line)
                    if child:
                        return child
                return {"range_start": start, "range_end": end, "children": sym.children}
        else:
            sym_line = sym.location.range.start.line
            if sym_line == line:
                return {
                    "range_start": sym_line,
                    "range_end": sym.location.range.end.line,
                    "children": None,
                }
    return None


def expand_variable_range(lines: list[str], start_line: int) -> int:
    """Expand a single-line variable range to include full multi-line definitions."""
    if start_line >= len(lines):
        return start_line
    
    first_line = lines[start_line]
    
    open_parens = first_line.count('(') - first_line.count(')')
    open_brackets = first_line.count('[') - first_line.count(']')
    open_braces = first_line.count('{') - first_line.count('}')
    
    in_multiline_string = first_line.count('"""') % 2 == 1 or first_line.count("'''") % 2 == 1
    
    if open_parens == 0 and open_brackets == 0 and open_braces == 0 and not in_multiline_string:
        return start_line
    
    for i in range(start_line + 1, len(lines)):
        line = lines[i]
        
        if in_multiline_string:
            if '"""' in line or "'''" in line:
                in_multiline_string = False
                if open_parens == 0 and open_brackets == 0 and open_braces == 0:
                    return i
            continue
        
        open_parens += line.count('(') - line.count(')')
        open_brackets += line.count('[') - line.count(']')
        open_braces += line.count('{') - line.count('}')
        
        if '"""' in line or "'''" in line:
            if line.count('"""') % 2 == 1 or line.count("'''") % 2 == 1:
                in_multiline_string = True
                continue
        
        if open_parens <= 0 and open_brackets <= 0 and open_braces <= 0:
            return i
    
    return start_line


def is_excluded(rel_path: str, exclude_patterns: list[str]) -> bool:
    path_parts = Path(rel_path).parts
    for pat in exclude_patterns:
        if fnmatch.fnmatch(rel_path, pat):
            return True
        if "/" not in pat and "*" not in pat and "?" not in pat:
            if pat in path_parts:
                return True
        if fnmatch.fnmatch(Path(rel_path).name, pat):
            return True
    return False
