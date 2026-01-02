"""Handler for grep command."""

import re
from pathlib import Path

from ..rpc import GrepParams, GrepResult, SymbolInfo
from .base import HandlerContext, is_excluded


async def handle_grep(ctx: HandlerContext, params: GrepParams) -> GrepResult:
    workspace_root = Path(params.workspace_root).resolve()
    pattern = params.pattern
    kinds = params.kinds
    case_sensitive = params.case_sensitive
    include_docs = params.include_docs
    paths = params.paths
    exclude_patterns = params.exclude_patterns

    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        raise ValueError(f"Invalid regex pattern '{pattern}': {e}")

    kinds_set = set(k.lower() for k in kinds) if kinds else None

    if paths:
        symbols = await ctx.collect_symbols_for_paths(
            [Path(p) for p in paths], workspace_root
        )
    else:
        symbols = await ctx.collect_all_workspace_symbols(workspace_root, "")

    if exclude_patterns:
        symbols = [s for s in symbols if not is_excluded(s.get("path", ""), exclude_patterns)]

    symbols = [s for s in symbols if regex.search(s.get("name", ""))]

    if kinds_set:
        symbols = [s for s in symbols if s.get("kind", "").lower() in kinds_set]

    if include_docs and symbols:
        for sym in symbols:
            sym["documentation"] = await ctx.get_symbol_documentation(
                workspace_root, sym["path"], sym["line"], sym.get("column", 0)
            )

    warning = None
    if not symbols and r"\|" in pattern:
        warning = "No results. Note: use '|' for alternation, not '\\|' (e.g., 'foo|bar' not 'foo\\|bar')"

    return GrepResult(
        symbols=[SymbolInfo(**s) for s in symbols],
        warning=warning,
    )
