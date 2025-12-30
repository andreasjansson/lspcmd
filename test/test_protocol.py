import asyncio
import pytest

from lspcmd.lsp.protocol import encode_message, read_message, LSPProtocolError


class TestEncodeMessage:
    def test_basic_message(self):
        msg = {"jsonrpc": "2.0", "method": "test"}
        encoded = encode_message(msg)

        assert encoded.startswith(b"Content-Length: ")
        assert b"\r\n\r\n" in encoded
        assert b'"jsonrpc": "2.0"' in encoded
        assert b'"method": "test"' in encoded

    def test_content_length_correct(self):
        msg = {"id": 1, "method": "initialize"}
        encoded = encode_message(msg)

        header, body = encoded.split(b"\r\n\r\n", 1)
        length_str = header.decode("ascii").split(": ")[1]
        assert int(length_str) == len(body)


class TestReadMessage:
    @pytest.mark.asyncio
    async def test_read_simple_message(self):
        msg = {"jsonrpc": "2.0", "id": 1, "result": "ok"}
        encoded = encode_message(msg)

        reader = asyncio.StreamReader()
        reader.feed_data(encoded)
        reader.feed_eof()

        result = await read_message(reader)
        assert result == msg

    @pytest.mark.asyncio
    async def test_missing_content_length(self):
        reader = asyncio.StreamReader()
        reader.feed_data(b"\r\n\r\n{}")
        reader.feed_eof()

        with pytest.raises(LSPProtocolError):
            await read_message(reader)

    @pytest.mark.asyncio
    async def test_connection_closed(self):
        reader = asyncio.StreamReader()
        reader.feed_eof()

        with pytest.raises(LSPProtocolError):
            await read_message(reader)
