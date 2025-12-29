from pathlib import Path

import pytest

from lspcmd.utils.uri import path_to_uri, uri_to_path


class TestPathToUri:
    def test_simple_path(self):
        uri = path_to_uri("/home/user/file.py")
        assert uri == "file:///home/user/file.py"

    def test_path_object(self):
        uri = path_to_uri(Path("/home/user/file.py"))
        assert uri == "file:///home/user/file.py"

    def test_path_with_spaces(self):
        uri = path_to_uri("/home/user/my file.py")
        assert uri == "file:///home/user/my%20file.py"


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
    def test_roundtrip(self):
        original = Path("/home/user/project/main.py")
        uri = path_to_uri(original)
        result = uri_to_path(uri)
        assert result == original

    def test_roundtrip_with_spaces(self):
        original = Path("/home/user/my project/main file.py")
        uri = path_to_uri(original)
        result = uri_to_path(uri)
        assert result == original
