from pathlib import Path

import pytest

from lspcmd.utils.text import (
    get_language_id,
    get_line_at,
    get_lines_around,
    position_to_offset,
    offset_to_position,
)


class TestGetLanguageId:
    def test_python(self):
        assert get_language_id("main.py") == "python"
        assert get_language_id("types.pyi") == "python"

    def test_javascript(self):
        assert get_language_id("app.js") == "javascript"
        assert get_language_id("App.jsx") == "javascriptreact"

    def test_typescript(self):
        assert get_language_id("app.ts") == "typescript"
        assert get_language_id("App.tsx") == "typescriptreact"

    def test_rust(self):
        assert get_language_id("main.rs") == "rust"

    def test_go(self):
        assert get_language_id("main.go") == "go"

    def test_unknown(self):
        assert get_language_id("file.xyz") == "plaintext"

    def test_path_object(self):
        assert get_language_id(Path("/project/main.py")) == "python"


class TestGetLineAt:
    def test_first_line(self):
        content = "line1\nline2\nline3"
        assert get_line_at(content, 0) == "line1"

    def test_middle_line(self):
        content = "line1\nline2\nline3"
        assert get_line_at(content, 1) == "line2"

    def test_out_of_range(self):
        content = "line1\nline2"
        assert get_line_at(content, 5) == ""


class TestGetLinesAround:
    def test_with_context(self):
        content = "line1\nline2\nline3\nline4\nline5"
        lines, start, end = get_lines_around(content, 2, 1)
        assert lines == ["line2", "line3", "line4"]
        assert start == 1
        assert end == 4

    def test_at_start(self):
        content = "line1\nline2\nline3"
        lines, start, end = get_lines_around(content, 0, 2)
        assert lines == ["line1", "line2", "line3"]
        assert start == 0

    def test_at_end(self):
        content = "line1\nline2\nline3"
        lines, start, end = get_lines_around(content, 2, 2)
        assert lines == ["line1", "line2", "line3"]
        assert end == 3


class TestPositionConversion:
    def test_position_to_offset(self):
        content = "abc\ndefgh\nij"
        assert position_to_offset(content, 0, 0) == 0
        assert position_to_offset(content, 0, 2) == 2
        assert position_to_offset(content, 1, 0) == 4
        assert position_to_offset(content, 1, 3) == 7
        assert position_to_offset(content, 2, 1) == 11

    def test_offset_to_position(self):
        content = "abc\ndefgh\nij"
        assert offset_to_position(content, 0) == (0, 0)
        assert offset_to_position(content, 2) == (0, 2)
        assert offset_to_position(content, 4) == (1, 0)
        assert offset_to_position(content, 7) == (1, 3)
        assert offset_to_position(content, 11) == (2, 1)
