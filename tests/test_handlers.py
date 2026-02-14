"""Tests for request handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from codesage.config import CodeSageConfig
from codesage.handlers import RequestHandler
from codesage.models import (
    JsonRpcRequest,
    LLMResponse,
    StreamChunk,
    TokenUsage,
)


@pytest.fixture
def config() -> CodeSageConfig:
    return CodeSageConfig(models={"default_model": "gpt-4o-mini"})


@pytest.fixture
def handler(config: CodeSageConfig) -> RequestHandler:
    return RequestHandler(config)


class TestDispatch:
    @pytest.mark.asyncio
    async def test_ping(self, handler: RequestHandler):
        request = JsonRpcRequest(method="ping", id=1)
        response = await handler.dispatch(request)
        assert response.error is None
        assert response.result["status"] == "ok"
        assert response.result["version"] == "0.1.0"
        assert response.id == 1

    @pytest.mark.asyncio
    async def test_shutdown(self, handler: RequestHandler):
        request = JsonRpcRequest(method="shutdown", id=2)
        response = await handler.dispatch(request)
        assert response.result["status"] == "shutting_down"

    @pytest.mark.asyncio
    async def test_method_not_found(self, handler: RequestHandler):
        request = JsonRpcRequest(method="nonexistent", id=3)
        response = await handler.dispatch(request)
        assert response.error is not None
        assert response.error.code == -32601
        assert "nonexistent" in response.error.message

    @pytest.mark.asyncio
    async def test_explain(self, handler: RequestHandler):
        mock_response = LLMResponse(
            content="Explanation here",
            model="gpt-4o-mini",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        )

        with patch.object(handler._llm, "complete", new_callable=AsyncMock) as mock:
            mock.return_value = mock_response
            request = JsonRpcRequest(
                method="explain",
                params={"code": "x = 1", "language": "python"},
                id=4,
            )
            response = await handler.dispatch(request)

        assert response.error is None
        assert response.result["content"] == "Explanation here"

    @pytest.mark.asyncio
    async def test_improve(self, handler: RequestHandler):
        mock_response = LLMResponse(
            content="Improvements here",
            model="gpt-4o-mini",
        )

        with patch.object(handler._llm, "complete", new_callable=AsyncMock) as mock:
            mock.return_value = mock_response
            request = JsonRpcRequest(
                method="improve",
                params={"code": "x = 1", "language": "python"},
                id=5,
            )
            response = await handler.dispatch(request)

        assert response.result["content"] == "Improvements here"

    @pytest.mark.asyncio
    async def test_handler_error(self, handler: RequestHandler):
        with patch.object(handler._llm, "complete", new_callable=AsyncMock) as mock:
            mock.side_effect = Exception("LLM failed")
            request = JsonRpcRequest(
                method="explain",
                params={"code": "x = 1"},
                id=6,
            )
            response = await handler.dispatch(request)

        assert response.error is not None
        assert response.error.code == -32000
        assert "LLM failed" in response.error.message


class TestDispatchStream:
    @pytest.mark.asyncio
    async def test_stream_explain(self, handler: RequestHandler):
        async def mock_stream(*args, **kwargs):
            yield StreamChunk(content="Hello ")
            yield StreamChunk(content="world")
            yield StreamChunk(content="", done=True)

        with patch.object(handler._llm, "stream", side_effect=mock_stream):
            request = JsonRpcRequest(
                method="stream/explain",
                params={"code": "x = 1", "language": "python"},
                id=7,
            )
            chunks = []
            async for chunk in handler.dispatch_stream(request):
                chunks.append(chunk)

        assert len(chunks) == 3
        assert chunks[0].content == "Hello "
        assert chunks[2].done is True

    @pytest.mark.asyncio
    async def test_stream_method_not_found(self, handler: RequestHandler):
        request = JsonRpcRequest(method="stream/nonexistent", id=8)
        chunks = []
        async for chunk in handler.dispatch_stream(request):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0].error is not None
        assert chunks[0].done is True
