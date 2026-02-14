"""Tests for chat-related RPC handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from codesage.config import CodeSageConfig
from codesage.handlers import RequestHandler
from codesage.models import JsonRpcRequest, StreamChunk


@pytest.fixture
def config() -> CodeSageConfig:
    return CodeSageConfig(
        models={"default_model": "gpt-4o-mini"},
        agentic={"enabled": False},  # disable agentic for simpler testing
    )


@pytest.fixture
def handler(config: CodeSageConfig) -> RequestHandler:
    return RequestHandler(config)


class TestChatSessionHandlers:
    @pytest.mark.asyncio
    async def test_create_session(self, handler: RequestHandler):
        request = JsonRpcRequest(
            method="chat/create_session",
            params={"code": "x = 1", "language": "python"},
            id=1,
        )
        response = await handler.dispatch(request)
        assert response.error is None
        assert "session_id" in response.result

    @pytest.mark.asyncio
    async def test_list_sessions(self, handler: RequestHandler):
        # Create a session first
        create_req = JsonRpcRequest(
            method="chat/create_session",
            params={},
            id=1,
        )
        await handler.dispatch(create_req)

        # List sessions
        list_req = JsonRpcRequest(method="chat/list_sessions", params={}, id=2)
        response = await handler.dispatch(list_req)

        assert response.error is None
        assert len(response.result["sessions"]) >= 1

    @pytest.mark.asyncio
    async def test_clear_session(self, handler: RequestHandler):
        # Create session
        create_req = JsonRpcRequest(
            method="chat/create_session", params={}, id=1
        )
        create_resp = await handler.dispatch(create_req)
        session_id = create_resp.result["session_id"]

        # Clear it
        clear_req = JsonRpcRequest(
            method="chat/clear_session",
            params={"session_id": session_id},
            id=2,
        )
        response = await handler.dispatch(clear_req)
        assert response.result["success"] is True

    @pytest.mark.asyncio
    async def test_delete_session(self, handler: RequestHandler):
        # Create session
        create_req = JsonRpcRequest(
            method="chat/create_session", params={}, id=1
        )
        create_resp = await handler.dispatch(create_req)
        session_id = create_resp.result["session_id"]

        # Delete it
        delete_req = JsonRpcRequest(
            method="chat/delete_session",
            params={"session_id": session_id},
            id=2,
        )
        response = await handler.dispatch(delete_req)
        assert response.result["success"] is True

        # Verify it's gone
        list_req = JsonRpcRequest(method="chat/list_sessions", params={}, id=3)
        list_resp = await handler.dispatch(list_req)
        ids = {s["id"] for s in list_resp.result["sessions"]}
        assert session_id not in ids


class TestChatSendMessage:
    @pytest.mark.asyncio
    async def test_send_message(self, handler: RequestHandler):
        # Create session
        create_req = JsonRpcRequest(
            method="chat/create_session",
            params={"code": "def foo(): pass", "language": "python"},
            id=1,
        )
        create_resp = await handler.dispatch(create_req)
        session_id = create_resp.result["session_id"]

        # Mock the LLM stream
        async def mock_stream(*args, **kwargs):
            yield StreamChunk(content="Hello! ")
            yield StreamChunk(content="I see your code.")
            yield StreamChunk(content="", done=True)

        with patch.object(handler._llm, "stream", side_effect=mock_stream):
            request = JsonRpcRequest(
                method="stream/chat/send_message",
                params={
                    "session_id": session_id,
                    "message": "What does this do?",
                },
                id=2,
            )
            chunks = []
            async for chunk in handler.dispatch_stream(request):
                chunks.append(chunk)

        # Should have streamed content
        content_chunks = [c for c in chunks if c.content]
        assert len(content_chunks) >= 1
        assert chunks[-1].done is True

        # Verify history was saved
        session = handler._session_manager.get_session(session_id)
        assert len(session.messages) >= 2  # user + assistant
        assert session.messages[0].role == "user"
        assert session.messages[0].content == "What does this do?"

    @pytest.mark.asyncio
    async def test_send_message_nonexistent_session(self, handler: RequestHandler):
        request = JsonRpcRequest(
            method="stream/chat/send_message",
            params={
                "session_id": "nonexistent",
                "message": "Hello",
            },
            id=1,
        )
        chunks = []
        async for chunk in handler.dispatch_stream(request):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0].error is not None
        assert "not found" in chunks[0].error.lower()

    @pytest.mark.asyncio
    async def test_conversation_accumulates_history(self, handler: RequestHandler):
        # Create session
        create_req = JsonRpcRequest(
            method="chat/create_session", params={}, id=1
        )
        create_resp = await handler.dispatch(create_req)
        session_id = create_resp.result["session_id"]

        # Send two messages
        async def mock_stream1(*args, **kwargs):
            yield StreamChunk(content="First reply")
            yield StreamChunk(content="", done=True)

        async def mock_stream2(*args, **kwargs):
            yield StreamChunk(content="Second reply")
            yield StreamChunk(content="", done=True)

        with patch.object(handler._llm, "stream", side_effect=mock_stream1):
            req1 = JsonRpcRequest(
                method="stream/chat/send_message",
                params={"session_id": session_id, "message": "First question"},
                id=2,
            )
            async for _ in handler.dispatch_stream(req1):
                pass

        with patch.object(handler._llm, "stream", side_effect=mock_stream2):
            req2 = JsonRpcRequest(
                method="stream/chat/send_message",
                params={"session_id": session_id, "message": "Second question"},
                id=3,
            )
            async for _ in handler.dispatch_stream(req2):
                pass

        session = handler._session_manager.get_session(session_id)
        assert len(session.messages) == 4  # 2 user + 2 assistant
