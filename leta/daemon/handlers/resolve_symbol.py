"""Handler for resolve-symbol command."""

import fnmatch
import re
from pathlib import Path

from ..rpc import ResolveSymbolParams, ResolveSymbolResult, SymbolInfo
from .base import HandlerContext, SymbolDict


async def handle_resolve_symbol(
    ctx: HandlerContext, params: ResolveSymbolParams
) -> ResolveSymbolResult:
    workspace_root = Path(params.workspace_root).resolve()
    symbol_path = params.symbol_path

    path_filter: str | None = None
    line_filter: int | None = None

    colon_count = symbol_path.count(":")
    if colon_count == 2:
        path_filter, line_str, symbol_path = symbol_path.split(":", 2)
        try:
            line_filter = int(line_str)
        except ValueError:
            return ResolveSymbolResult(error=f"Invalid line number: '{line_str}'")
    elif colon_count == 1:
        path_filter, symbol_path = symbol_path.split(":", 1)

    parts = symbol_path.split(".")

    all_symbols = await ctx.collect_all_workspace_symbols(workspace_root)

    if path_filter:

        def matches_path(rel_path: str) -> bool:
            if fnmatch.fnmatch(rel_path, path_filter):
                return True
            if fnmatch.fnmatch(rel_path, f"**/{path_filter}"):
                return True
            if fnmatch.fnmatch(rel_path, f"{path_filter}/**"):
                return True
            if "/" not in path_filter:
                if fnmatch.fnmatch(Path(rel_path).name, path_filter):
                    return True
                if path_filter in Path(rel_path).parts:
                    return True
            return False

        all_symbols = [s for s in all_symbols if matches_path(s.get("path", ""))]

    if line_filter is not None:
        all_symbols = [s for s in all_symbols if s.get("line") == line_filter]

    target_name = parts[-1]

    if len(parts) == 1:
        matches = []
        for s in all_symbols:
            sym_name = s.get("name", "")
            if _name_matches(sym_name, target_name):
                matches.append(s)
            elif sym_name.endswith(f").{target_name}"):
                matches.append(s)
    else:
        container_parts = parts[:-1]
        matches = []
        container_str = ".".join(container_parts)

        for sym in all_symbols:
            sym_name = sym.get("name", "")

            go_style_name = f"(*{container_str}).{target_name}"
            go_style_name_val = f"({container_str}).{target_name}"
            if sym_name == go_style_name or sym_name == go_style_name_val:
                matches.append(sym)
                continue

            if not _name_matches(sym_name, target_name):
                continue

            sym_container = sym.get("container", "") or ""
            sym_container_normalized = _normalize_container(sym_container)
            sym_path = sym.get("path", "")
            module_name = _get_module_name(sym_path)

            full_container = (
                f"{module_name}.{sym_container_normalized}"
                if sym_container_normalized
                else module_name
            )

            if sym_container_normalized == container_str:
                matches.append(sym)
            elif sym_container == container_str:
                matches.append(sym)
            elif full_container == container_str:
                matches.append(sym)
            elif full_container.endswith(f".{container_str}"):
                matches.append(sym)
            elif len(container_parts) == 1 and container_parts[0] == module_name:
                matches.append(sym)

    if not matches:
        error_parts = []
        if path_filter:
            error_parts.append(f"in files matching '{path_filter}'")
        if line_filter is not None:
            error_parts.append(f"on line {line_filter}")
        suffix = " " + " ".join(error_parts) if error_parts else ""
        return ResolveSymbolResult(error=f"Symbol '{symbol_path}' not found{suffix}")

    preferred_kinds = {
        "Class",
        "Struct",
        "Interface",
        "Enum",
        "Module",
        "Namespace",
        "Package",
    }
    type_matches = [m for m in matches if m.get("kind") in preferred_kinds]
    if len(type_matches) == 1 and len(matches) > 1:
        matches = type_matches

    if len(matches) == 1:
        sym = matches[0]
        return ResolveSymbolResult(
            path=str(workspace_root / sym["path"]),
            line=sym["line"],
            column=sym.get("column", 0),
            name=sym.get("name"),
            kind=sym.get("kind"),
            container=sym.get("container"),
            range_start_line=sym.get("range_start_line"),
            range_end_line=sym.get("range_end_line"),
        )

    matches_info: list[SymbolInfo] = []
    for sym in matches[:10]:
        ref = _generate_unambiguous_ref(sym, matches, target_name)
        matches_info.append(
            SymbolInfo(
                name=sym.get("name", ""),
                kind=sym.get("kind", ""),
                path=sym.get("path", ""),
                line=sym.get("line", 0),
                column=sym.get("column", 0),
                container=sym.get("container"),
                ref=ref,
            )
        )

    return ResolveSymbolResult(
        error=f"Symbol '{symbol_path}' is ambiguous ({len(matches)} matches)",
        matches=matches_info,
        total_matches=len(matches),
    )


def _name_matches(sym_name: str, target: str) -> bool:
    if sym_name == target:
        return True
    if _normalize_symbol_name(sym_name) == target:
        return True
    return False


def _normalize_symbol_name(name: str) -> str:
    match = re.match(r"^(\w+)\([^)]*\)$", name)
    if match:
        return match.group(1)
    match = re.match(r"^\(\*?\w+\)\.(\w+)$", name)
    if match:
        return match.group(1)
    # Handle Lua colon method syntax: "User:isAdult" -> "isAdult"
    if ":" in name:
        return name.split(":")[-1]
    # Handle dot-qualified names: "User.new" -> "new"
    if "." in name:
        return name.split(".")[-1]
    return name


def _get_effective_container(sym: SymbolDict) -> str:
    container = sym.get("container", "") or ""
    if container:
        return _normalize_container(container)

    sym_name = sym.get("name", "")
    match = re.match(r"^\(\*?(\w+)\)\.", sym_name)
    if match:
        return match.group(1)

    return ""


def _generate_unambiguous_ref(
    sym: SymbolDict, all_matches: list[SymbolDict], target_name: str
) -> str:
    sym_path = sym.get("path", "")
    sym_line = sym.get("line", 0)
    sym_container = _get_effective_container(sym)
    filename = Path(sym_path).name
    normalized_name = _normalize_symbol_name(target_name)

    if sym_container:
        ref = f"{sym_container}.{normalized_name}"
        if _ref_resolves_uniquely(ref, sym, all_matches):
            return ref

    ref = f"{filename}:{normalized_name}"
    if _ref_resolves_uniquely(ref, sym, all_matches):
        return ref

    if sym_container:
        ref = f"{filename}:{sym_container}.{normalized_name}"
        if _ref_resolves_uniquely(ref, sym, all_matches):
            return ref

    return f"{filename}:{sym_line}:{normalized_name}"


def _ref_resolves_uniquely(
    ref: str, target_sym: SymbolDict, all_matches: list[SymbolDict]
) -> bool:
    path_filter: str | None = None
    symbol_path = ref

    colon_count = ref.count(":")
    if colon_count >= 1:
        parts = ref.split(":")
        if colon_count == 1:
            path_filter, symbol_path = parts[0], parts[1]
        elif colon_count == 2:
            path_filter = parts[0]
            try:
                line_filter = int(parts[1])
                matching = [
                    s
                    for s in all_matches
                    if Path(s.get("path", "")).name == path_filter
                    and s.get("line") == line_filter
                ]
                return len(matching) == 1 and matching[0] is target_sym
            except ValueError:
                symbol_path = f"{parts[1]}:{parts[2]}" if len(parts) > 2 else parts[1]

    if path_filter:
        candidates = [
            s for s in all_matches if Path(s.get("path", "")).name == path_filter
        ]
    else:
        candidates = all_matches

    sym_parts = symbol_path.split(".")
    if len(sym_parts) == 1:
        matching = [
            s
            for s in candidates
            if _normalize_symbol_name(s.get("name", "")) == sym_parts[0]
        ]
    else:
        container_str = ".".join(sym_parts[:-1])
        target_name = sym_parts[-1]
        matching = []

        for s in candidates:
            if _normalize_symbol_name(s.get("name", "")) != target_name:
                continue

            s_container = s.get("container", "") or ""
            s_container_normalized = _normalize_container(s_container)
            s_path = s.get("path", "")
            s_module = _get_module_name(s_path)
            full_container = (
                f"{s_module}.{s_container_normalized}"
                if s_container_normalized
                else s_module
            )

            s_effective_container = _get_effective_container(s)

            if s_container_normalized == container_str:
                matching.append(s)
            elif s_container == container_str:
                matching.append(s)
            elif s_effective_container == container_str:
                matching.append(s)
            elif full_container == container_str:
                matching.append(s)
            elif full_container.endswith(f".{container_str}"):
                matching.append(s)
            elif len(sym_parts) == 2 and sym_parts[0] == s_module:
                matching.append(s)

    return len(matching) == 1 and matching[0] is target_sym


def _get_module_name(rel_path: str) -> str:
    path = Path(rel_path)
    return path.stem


def _normalize_container(container: str) -> str:
    match = re.match(r"^\(\*?(\w+)\)$", container)
    if match:
        return match.group(1)
    match = re.match(r"^impl\s+\w+(?:<[^>]+>)?\s+for\s+(\w+)", container)
    if match:
        return match.group(1)
    match = re.match(r"^impl\s+(\w+)", container)
    if match:
        return match.group(1)
    return container
