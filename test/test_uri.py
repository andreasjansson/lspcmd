from pathlib import Path
import tempfile

import pytest

from lspcmd.utils.uri import path_to_uri, uri_to_path


class TestPathToUri:
    def test_simple_path(self, temp_dir):
        test_file = temp_dir / "file.py"
        test_file.touch()
        uri = path_to_uri(test_file)
        assert uri.startswith("file://")
        assert uri.endswith("file.py")

    def test_path_object(self, temp_dir):
        test_file = temp_dir / "file.py"
        test_file.touch()
        uri = path_to_uri(test_file)
        assert uri.startswith("file://")

    def test_path_with_spaces(self, temp_dir):
        test_file = temp_dir / "my file.py"
        test_file.touch()
        uri = path_to_uri(test_file)
        assert "%20" in uri or "my file" in uri


class TestUriToPath:
    def test_simple_uri(self):
        path = uri_to_path("file:///home/user/file.py")
        assert path == Path("/home/user/file.py")

    def test_uri_with_encoded_spaces(self):
        path = uri_to_path("file:///home/user/my%20file.py")
        assert path == Path("/home/user/my file.py")

    def test_non_file_uri_raises(self):
        with pytest.raises(ValueError):
            uri_to_path("https://example.com/file.py")


class TestRoundTrip:
    def test_roundtrip(self, temp_dir):
        original = temp_dir / "main.py"
        original.touch()
        original = original.resolve()
        uri = path_to_uri(original)
        result = uri_to_path(uri)
        assert result == original

    def test_roundtrip_with_spaces(self, temp_dir):
        original = temp_dir / "my project"
        original.mkdir()
        original = original / "main file.py"
        original.touch()
        original = original.resolve()
        uri = path_to_uri(original)
        result = uri_to_path(uri)
        assert result == original
