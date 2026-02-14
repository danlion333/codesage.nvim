"""End-to-end tests for CodeSage server."""

from __future__ import annotations

import asyncio
import json
import struct
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from codesage.config import CodeSageConfig
from codesage.models import LLMResponse, StreamChunk, TokenUsage
from codesage.server import CodeSageServer


def encode_message(data: dict) -> bytes:
    payload = json.dumps(data).encode("utf-8")
    return struct.pack("!I", len(payload)) + payload


async def read_response(reader: asyncio.StreamReader) -> dict:
    header = await reader.readexactly(4)
    length = struct.unpack("!I", header)[0]
    data = await reader.readexactly(length)
    return json.loads(data.decode("utf-8"))


@pytest.fixture
def server_config(tmp_path: Path) -> CodeSageConfig:
    return CodeSageConfig(
        server={"socket_path": str(tmp_path / "e2e.sock")},
        agentic={"enabled": False},
    )


class TestE2E:
    @pytest.mark.asyncio
    async def test_full_explain_flow(self, server_config: CodeSageConfig):
        """Test complete explain flow: connect -> explain -> verify response."""
        server = CodeSageServer(server_config)

        mock_response = LLMResponse(
            content="## Summary\nThis code assigns 1 to x.",
            model="gpt-4o-mini",
            usage=TokenUsage(prompt_tokens=50, completion_tokens=20, total_tokens=70),
        )

        server_task = asyncio.create_task(server.start())
        await asyncio.sleep(0.1)

        try:
            with patch.object(
                server._handler._llm, "complete", new_callable=AsyncMock
            ) as mock_llm:
                mock_llm.return_value = mock_response

                reader, writer = await asyncio.open_unix_connection(
                    server.socket_path,
                )

                # Ping first
                writer.write(encode_message({
                    "jsonrpc": "2.0", "method": "ping", "id": 1,
                }))
                await writer.drain()
                resp = await asyncio.wait_for(read_response(reader), timeout=2.0)
                assert resp["result"]["status"] == "ok"

                # Explain request
                writer.write(encode_message({
                    "jsonrpc": "2.0",
                    "method": "explain",
                    "params": {
                        "code": "x = 1",
                        "language": "python",
                        "filename": "test.py",
                    },
                    "id": 2,
                }))
                await writer.drain()
                resp = await asyncio.wait_for(read_response(reader), timeout=2.0)
                assert resp["error"] is None
                assert "assigns 1 to x" in resp["result"]["content"]
                assert resp["result"]["usage"]["total_tokens"] == 70

                writer.close()
                await writer.wait_closed()
        finally:
            await server.stop()
            await asyncio.wait_for(server_task, timeout=2.0)

    @pytest.mark.asyncio
    async def test_multiple_sequential_requests(self, server_config: CodeSageConfig):
        """Test sending multiple requests on the same connection."""
        server = CodeSageServer(server_config)
        server_task = asyncio.create_task(server.start())
        await asyncio.sleep(0.1)

        try:
            reader, writer = await asyncio.open_unix_connection(
                server.socket_path,
            )

            # Send multiple pings
            for i in range(5):
                writer.write(encode_message({
                    "jsonrpc": "2.0", "method": "ping", "id": i,
                }))
                await writer.drain()
                resp = await asyncio.wait_for(read_response(reader), timeout=2.0)
                assert resp["id"] == i
                assert resp["result"]["status"] == "ok"

            writer.close()
            await writer.wait_closed()
        finally:
            await server.stop()
            await asyncio.wait_for(server_task, timeout=2.0)

    @pytest.mark.asyncio
    async def test_streaming_explain_e2e(self, server_config: CodeSageConfig):
        """Test streaming explain flow end-to-end."""
        server = CodeSageServer(server_config)

        async def mock_stream(request):
            yield StreamChunk(content="## Summary\n")
            yield StreamChunk(content="This code ")
            yield StreamChunk(content="does things.")
            yield StreamChunk(content="", done=True)

        server_task = asyncio.create_task(server.start())
        await asyncio.sleep(0.1)

        try:
            with patch.object(server._handler._llm, "stream", side_effect=mock_stream):
                reader, writer = await asyncio.open_unix_connection(
                    server.socket_path,
                )

                writer.write(encode_message({
                    "jsonrpc": "2.0",
                    "method": "stream/explain",
                    "params": {"code": "x = 1", "language": "python"},
                    "id": 10,
                }))
                await writer.drain()

                collected = []
                while True:
                    resp = await asyncio.wait_for(read_response(reader), timeout=2.0)
                    chunk = resp["result"]
                    collected.append(chunk["content"])
                    if chunk.get("done"):
                        break

                full_text = "".join(collected)
                assert "Summary" in full_text
                assert "does things" in full_text

                writer.close()
                await writer.wait_closed()
        finally:
            await server.stop()
            await asyncio.wait_for(server_task, timeout=2.0)
