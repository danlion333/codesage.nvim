"""Tests for the JSON-RPC server."""

from __future__ import annotations

import asyncio
import json
import struct
from pathlib import Path

import pytest

from codesage.config import CodeSageConfig
from codesage.server import CodeSageServer, HEADER_SIZE


def encode_message(data: dict) -> bytes:
    """Encode a dict as a length-prefixed JSON message."""
    payload = json.dumps(data).encode("utf-8")
    return struct.pack("!I", len(payload)) + payload


async def read_response(reader: asyncio.StreamReader) -> dict:
    """Read a length-prefixed JSON response."""
    header = await reader.readexactly(HEADER_SIZE)
    length = struct.unpack("!I", header)[0]
    data = await reader.readexactly(length)
    return json.loads(data.decode("utf-8"))


@pytest.fixture
def server_config(tmp_path: Path) -> CodeSageConfig:
    socket_path = str(tmp_path / "test.sock")
    return CodeSageConfig(server={"socket_path": socket_path})


class TestCodeSageServer:
    @pytest.mark.asyncio
    async def test_ping_roundtrip(self, server_config: CodeSageConfig):
        server = CodeSageServer(server_config)

        # Start server in background
        server_task = asyncio.create_task(server.start())

        # Wait for server to be ready
        await asyncio.sleep(0.1)

        try:
            reader, writer = await asyncio.open_unix_connection(
                server.socket_path,
            )

            # Send ping
            msg = encode_message({
                "jsonrpc": "2.0",
                "method": "ping",
                "id": 1,
            })
            writer.write(msg)
            await writer.drain()

            # Read response
            response = await asyncio.wait_for(read_response(reader), timeout=2.0)
            assert response["result"]["status"] == "ok"
            assert response["id"] == 1

            writer.close()
            await writer.wait_closed()
        finally:
            await server.stop()
            await asyncio.wait_for(server_task, timeout=2.0)

    @pytest.mark.asyncio
    async def test_invalid_json(self, server_config: CodeSageConfig):
        server = CodeSageServer(server_config)
        server_task = asyncio.create_task(server.start())
        await asyncio.sleep(0.1)

        try:
            reader, writer = await asyncio.open_unix_connection(
                server.socket_path,
            )

            # Send invalid JSON
            payload = b"not valid json"
            header = struct.pack("!I", len(payload))
            writer.write(header + payload)
            await writer.drain()

            response = await asyncio.wait_for(read_response(reader), timeout=2.0)
            assert response["error"]["code"] == -32700

            writer.close()
            await writer.wait_closed()
        finally:
            await server.stop()
            await asyncio.wait_for(server_task, timeout=2.0)

    @pytest.mark.asyncio
    async def test_shutdown_command(self, server_config: CodeSageConfig):
        server = CodeSageServer(server_config)
        server_task = asyncio.create_task(server.start())
        await asyncio.sleep(0.1)

        reader, writer = await asyncio.open_unix_connection(
            server.socket_path,
        )

        # Send shutdown
        msg = encode_message({
            "jsonrpc": "2.0",
            "method": "shutdown",
            "id": 99,
        })
        writer.write(msg)
        await writer.drain()

        response = await asyncio.wait_for(read_response(reader), timeout=2.0)
        assert response["result"]["status"] == "shutting_down"

        # Server should stop
        await asyncio.wait_for(server_task, timeout=2.0)

    @pytest.mark.asyncio
    async def test_socket_permissions(self, server_config: CodeSageConfig):
        import stat

        server = CodeSageServer(server_config)
        server_task = asyncio.create_task(server.start())
        await asyncio.sleep(0.1)

        try:
            mode = Path(server.socket_path).stat().st_mode
            assert stat.S_IMODE(mode) == 0o600
        finally:
            await server.stop()
            await asyncio.wait_for(server_task, timeout=2.0)

    @pytest.mark.asyncio
    async def test_stream_response(self, server_config: CodeSageConfig):
        """Test that streaming requests return multiple responses."""
        from unittest.mock import AsyncMock, patch

        from codesage.models import StreamChunk

        server = CodeSageServer(server_config)

        async def mock_stream(*args, **kwargs):
            yield StreamChunk(content="chunk1")
            yield StreamChunk(content="chunk2")
            yield StreamChunk(content="", done=True)

        server_task = asyncio.create_task(server.start())
        await asyncio.sleep(0.1)

        try:
            with patch.object(
                server._handler, "dispatch_stream", side_effect=mock_stream
            ):
                reader, writer = await asyncio.open_unix_connection(
                    server.socket_path,
                )

                msg = encode_message({
                    "jsonrpc": "2.0",
                    "method": "stream/explain",
                    "params": {"code": "x = 1"},
                    "id": 10,
                })
                writer.write(msg)
                await writer.drain()

                # Read all streamed responses
                responses = []
                for _ in range(3):
                    resp = await asyncio.wait_for(read_response(reader), timeout=2.0)
                    responses.append(resp)

                assert responses[0]["result"]["content"] == "chunk1"
                assert responses[1]["result"]["content"] == "chunk2"
                assert responses[2]["result"]["done"] is True

                writer.close()
                await writer.wait_closed()
        finally:
            await server.stop()
            await asyncio.wait_for(server_task, timeout=2.0)
