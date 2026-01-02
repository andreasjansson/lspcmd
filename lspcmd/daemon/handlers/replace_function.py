"""Handler for replace-function command."""

import asyncio
import re
from pathlib import Path

from ..rpc import ReplaceFunctionParams, ReplaceFunctionResult
from ...utils.text import read_file_content
from ...utils.uri import path_to_uri
from .base import HandlerContext, find_symbol_at_line


async def handle_replace_function(
    ctx: HandlerContext, params: ReplaceFunctionParams
) -> ReplaceFunctionResult:
    from .resolve_symbol import handle_resolve_symbol
    from ..rpc import ResolveSymbolParams

    workspace_root = Path(params.workspace_root).resolve()
    symbol = params.symbol
    new_contents = params.new_contents
    check_signature = params.check_signature

    resolved = await handle_resolve_symbol(
        ctx,
        ResolveSymbolParams(workspace_root=str(workspace_root), symbol_path=symbol),
    )
    if resolved.error:
        return ReplaceFunctionResult(error=resolved.error)

    kind = resolved.kind
    if kind not in ("Function", "Method"):
        return ReplaceFunctionResult(
            error=f"Symbol '{symbol}' is a {kind}, not a Function or Method"
        )

    file_path = Path(resolved.path).resolve()
    line = resolved.line
    column = resolved.column or 0
    range_start = resolved.range_start_line
    range_end = resolved.range_end_line

    if range_start is None or range_end is None:
        return ReplaceFunctionResult(
            error="Language server does not provide symbol ranges"
        )

    workspace = await ctx.session.get_or_create_workspace(file_path, workspace_root)
    await workspace.ensure_document_open(file_path)

    old_signature = await _extract_function_signature(
        workspace, file_path, line, column
    )

    original_content = read_file_content(file_path)
    backup_path = file_path.with_suffix(file_path.suffix + ".lspcmd.bkup")

    try:
        backup_path.write_text(original_content)

        new_content, new_line_count = _apply_function_replacement(
            original_content, new_contents, range_start, range_end
        )

        file_path.write_text(new_content)

        doc = workspace.open_documents.get(path_to_uri(file_path))
        if doc:
            doc.version += 1
            doc.content = new_content
            await workspace.client.send_notification(
                "textDocument/didChange",
                {
                    "textDocument": {"uri": doc.uri, "version": doc.version},
                    "contentChanges": [{"text": new_content}],
                },
            )

        if check_signature:
            await asyncio.sleep(0.2)

            new_signature = await _extract_function_signature(
                workspace, file_path, range_start, column
            )

            if new_signature is None:
                _revert_file(file_path, original_content, backup_path, doc, workspace)
                return ReplaceFunctionResult(
                    error="Could not extract signature from new content - the content may be invalid",
                    hint="Use --no-check-signature to replace anyway",
                )

            if old_signature and not _signatures_match(old_signature, new_signature):
                _revert_file(file_path, original_content, backup_path, doc, workspace)
                return ReplaceFunctionResult(
                    error="Signature mismatch",
                    old_signature=old_signature,
                    new_signature=new_signature,
                    hint="Use --no-check-signature to replace anyway",
                )

        backup_path.unlink(missing_ok=True)

        rel_path = ctx.relative_path(file_path, workspace_root)
        return ReplaceFunctionResult(
            replaced=True,
            path=rel_path,
            old_range=f"{range_start}-{range_end}",
            new_range=f"{range_start}-{range_start + new_line_count - 1}",
        )

    except Exception:
        if backup_path.exists():
            file_path.write_text(backup_path.read_text())
            backup_path.unlink()
        raise


async def _revert_file(file_path, original_content, backup_path, doc, workspace):
    file_path.write_text(original_content)
    backup_path.unlink(missing_ok=True)
    if doc:
        doc.version += 1
        doc.content = original_content
        await workspace.client.send_notification(
            "textDocument/didChange",
            {
                "textDocument": {"uri": doc.uri, "version": doc.version},
                "contentChanges": [{"text": original_content}],
            },
        )


def _apply_function_replacement(
    original_content: str, new_contents: str, range_start: int, range_end: int
) -> tuple[str, int]:
    lines = original_content.splitlines(keepends=True)
    start_line_idx = range_start - 1
    end_line_idx = range_end - 1

    if start_line_idx >= 0 and start_line_idx < len(lines):
        original_line = lines[start_line_idx]
        leading_ws = len(original_line) - len(original_line.lstrip())
        indentation = original_line[:leading_ws]
    else:
        indentation = ""

    new_lines = new_contents.splitlines(keepends=True)
    if new_lines and not new_lines[-1].endswith("\n"):
        new_lines[-1] += "\n"

    if new_lines:
        first_line = new_lines[0]
        first_line_ws = len(first_line) - len(first_line.lstrip())

        reindented = []
        for line in new_lines:
            if line.strip() == "":
                reindented.append(line)
            elif len(line) >= first_line_ws and line[:first_line_ws].strip() == "":
                reindented.append(indentation + line[first_line_ws:])
            else:
                reindented.append(indentation + line.lstrip())
        new_lines = reindented

    result_lines = lines[:start_line_idx] + new_lines + lines[end_line_idx + 1:]
    return "".join(result_lines), len(new_lines)


async def _extract_function_signature(
    workspace, file_path: Path, line: int, column: int
) -> str | None:
    doc = await workspace.ensure_document_open(file_path)

    symbols_result = await workspace.client.send_request(
        "textDocument/documentSymbol",
        {"textDocument": {"uri": doc.uri}},
    )
    if symbols_result:
        symbol = find_symbol_at_line(symbols_result, line - 1)
        if symbol and symbol.get("detail"):
            return _format_signature_from_detail(symbol)

    hover_result = await workspace.client.send_request(
        "textDocument/hover",
        {
            "textDocument": {"uri": doc.uri},
            "position": {"line": line - 1, "character": column},
        },
    )
    if not hover_result:
        return None
    return _parse_signature_from_hover(hover_result)


def _format_signature_from_detail(symbol: dict) -> str:
    name = symbol.get("name", "")
    detail = symbol.get("detail", "")
    if detail.startswith("func"):
        return f"func {name}{detail[4:]}"
    elif detail.startswith("fn"):
        return f"fn {name}{detail[2:]}"
    return f"{name} {detail}"


def _parse_signature_from_hover(hover_result: dict) -> str | None:
    contents = hover_result.get("contents")
    if not contents:
        return None

    if isinstance(contents, dict):
        value = contents.get("value", "")
    elif isinstance(contents, list):
        value = "\n".join(
            c.get("value", str(c)) if isinstance(c, dict) else str(c)
            for c in contents
        )
    else:
        value = str(contents)

    code_match = re.search(r"```\w*\n(.+?)```", value, re.DOTALL)
    if code_match:
        code_block = code_match.group(1).strip()
        return _extract_full_signature(code_block)

    return _extract_full_signature(value.strip())


def _extract_full_signature(code_block: str) -> str | None:
    lines = code_block.split("\n")
    if not lines:
        return None

    signature_parts: list[str] = []
    paren_depth = 0
    bracket_depth = 0
    found_start = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if not found_start:
            if any(kw in stripped for kw in ["def ", "func ", "fn ", "function ", "(function)", "(method)"]):
                found_start = True
            elif stripped.startswith("class ") or stripped.startswith("type "):
                return stripped
            else:
                continue

        for char in stripped:
            if char == '(':
                paren_depth += 1
            elif char == ')':
                paren_depth -= 1
            elif char == '[':
                bracket_depth += 1
            elif char == ']':
                bracket_depth -= 1

        signature_parts.append(stripped)

        if paren_depth == 0 and bracket_depth == 0:
            full_sig = " ".join(signature_parts)
            colon_idx = full_sig.rfind(":")
            brace_idx = full_sig.rfind("{")
            if brace_idx > 0 and (colon_idx < 0 or brace_idx < colon_idx):
                full_sig = full_sig[:brace_idx].strip()
            return full_sig

    return " ".join(signature_parts) if signature_parts else lines[0].strip()


def _signatures_match(old_sig: str, new_sig: str) -> bool:
    old_normalized = _normalize_signature(old_sig)
    new_normalized = _normalize_signature(new_sig)

    if old_normalized == new_normalized:
        return True

    old_params = _extract_params_only(old_normalized)
    new_params = _extract_params_only(new_normalized)
    return old_params == new_params


def _extract_params_only(sig: str) -> str:
    match = re.match(r"^((?:def|func|fn|function)\s+\w+\s*\([^)]*\))", sig)
    if match:
        return match.group(1)
    return sig


def _normalize_signature(sig: str) -> str:
    sig = re.sub(r"^\(function\)\s*", "", sig)
    sig = re.sub(r"^\(method\)\s*", "", sig)
    sig = re.sub(r"^function\s+", "", sig)
    sig = re.sub(r"^func\s+", "func ", sig)
    sig = re.sub(r"^def\s+", "def ", sig)
    sig = re.sub(r"^fn\s+", "fn ", sig)

    sig = re.sub(r"\bself:\s*Self@\w+", "self", sig)
    sig = re.sub(r"\bself:\s*Unknown", "self", sig)
    sig = re.sub(r"\bcls:\s*type\[Self@\w+\]", "cls", sig)
    sig = re.sub(r"\bcls:\s*Unknown", "cls", sig)

    sig = re.sub(r"\s*\(\+\d+\s*overload[s]?\)", "", sig)

    sig = re.sub(r"\s*,\s*", ", ", sig)
    sig = re.sub(r"\(\s+", "(", sig)
    sig = re.sub(r"\s+\)", ")", sig)
    sig = re.sub(r"\[\s+", "[", sig)
    sig = re.sub(r"\s+\]", "]", sig)
    sig = re.sub(r"\s*:\s*", ": ", sig)
    sig = re.sub(r"\s*->\s*", " -> ", sig)
    sig = re.sub(r"\s+", " ", sig)
    sig = sig.strip()
    return sig
