from pathlib import Path

LANGUAGE_IDS = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascriptreact",
    ".ts": "typescript",
    ".tsx": "typescriptreact",
    ".rs": "rust",
    ".go": "go",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".fs": "fsharp",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".lua": "lua",
    ".sh": "shellscript",
    ".bash": "shellscript",
    ".zsh": "shellscript",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".less": "less",
    ".md": "markdown",
    ".markdown": "markdown",
    ".sql": "sql",
    ".r": "r",
    ".R": "r",
    ".el": "emacs-lisp",
    ".clj": "clojure",
    ".cljs": "clojurescript",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".hrl": "erlang",
    ".hs": "haskell",
    ".ml": "ocaml",
    ".mli": "ocaml",
    ".vim": "vim",
    ".zig": "zig",
    ".nim": "nim",
    ".d": "d",
    ".dart": "dart",
    ".v": "v",
    ".vue": "vue",
    ".svelte": "svelte",
}


def get_language_id(path: str | Path) -> str:
    path = Path(path)
    return LANGUAGE_IDS.get(path.suffix, "plaintext")


def read_file_content(path: str | Path) -> str:
    return Path(path).read_text()


def get_line_at(content: str, line: int) -> str:
    lines = content.splitlines()
    if 0 <= line < len(lines):
        return lines[line]
    return ""


def get_lines_around(content: str, line: int, context: int) -> tuple[list[str], int, int]:
    lines = content.splitlines()
    start = max(0, line - context)
    end = min(len(lines), line + context + 1)
    return lines[start:end], start, end


def position_to_offset(content: str, line: int, character: int) -> int:
    lines = content.splitlines(keepends=True)
    offset = 0
    for i, ln in enumerate(lines):
        if i == line:
            return offset + character
        offset += len(ln)
    return offset


def offset_to_position(content: str, offset: int) -> tuple[int, int]:
    lines = content.splitlines(keepends=True)
    current = 0
    for i, ln in enumerate(lines):
        if current + len(ln) > offset:
            return i, offset - current
        current += len(ln)
    return len(lines), 0


def resolve_regex_position(content: str, pattern: str, line: int | None = None) -> tuple[int, int]:
    """Resolve a regex pattern to a (line, column) position.
    
    Args:
        content: The file content
        pattern: Regex pattern to search for
        line: If provided (1-based), search only on this line
        
    Returns:
        Tuple of (line, column) where line is 1-based, column is 0-based
        
    Raises:
        ValueError with descriptive message if pattern not found or ambiguous
    """
    import re
    
    lines = content.splitlines()
    
    if line is not None:
        line_idx = line - 1
        if line_idx < 0 or line_idx >= len(lines):
            raise ValueError(f"Line {line} is out of range (file has {len(lines)} lines)")
        
        line_content = lines[line_idx]
        matches = list(re.finditer(pattern, line_content))
        
        if not matches:
            raise ValueError(f"Pattern '{pattern}' not found on line {line}")
        if len(matches) > 1:
            match_positions = [f"column {m.start()}" for m in matches]
            raise ValueError(
                f"Pattern '{pattern}' matches {len(matches)} times on line {line}: "
                f"{', '.join(match_positions)}. Use LINE,COLUMN syntax to specify which one."
            )
        
        return (line, matches[0].start())
    else:
        all_matches = []
        for line_idx, line_content in enumerate(lines):
            for m in re.finditer(pattern, line_content):
                all_matches.append((line_idx + 1, m.start(), line_content))
        
        if not all_matches:
            raise ValueError(f"Pattern '{pattern}' not found in file")
        if len(all_matches) > 1:
            if len(all_matches) <= 5:
                locations = [f"  line {l}: {content_line.strip()}" for l, _, content_line in all_matches]
            else:
                locations = [f"  line {l}: {content_line.strip()}" for l, _, content_line in all_matches[:5]]
                locations.append(f"  ... and {len(all_matches) - 5} more matches")
            raise ValueError(
                f"Pattern '{pattern}' matches {len(all_matches)} times in file:\n"
                + "\n".join(locations)
                + "\nUse LINE,REGEX or LINE,COLUMN syntax to specify which one."
            )
        
        return (all_matches[0][0], all_matches[0][1])
