"""Tests for CodeSage data models."""

from codesage.models import (
    CommandType,
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    StreamChunk,
    TokenUsage,
)


class TestCommandType:
    def test_enum_values(self):
        assert CommandType.explain == "explain"
        assert CommandType.improve == "improve"
        assert CommandType.chat == "chat"

    def test_from_string(self):
        assert CommandType("explain") == CommandType.explain


class TestJsonRpc:
    def test_request_minimal(self):
        req = JsonRpcRequest(method="ping")
        assert req.jsonrpc == "2.0"
        assert req.method == "ping"
        assert req.params == {}
        assert req.id is None

    def test_request_full(self):
        req = JsonRpcRequest(
            method="explain",
            params={"code": "x = 1", "language": "python"},
            id=42,
        )
        assert req.method == "explain"
        assert req.params["code"] == "x = 1"
        assert req.id == 42

    def test_response_success(self):
        resp = JsonRpcResponse(result={"status": "ok"}, id=1)
        assert resp.result == {"status": "ok"}
        assert resp.error is None

    def test_response_error(self):
        resp = JsonRpcResponse(
            error=JsonRpcError(code=-32600, message="Invalid Request"),
            id=1,
        )
        assert resp.result is None
        assert resp.error.code == -32600

    def test_roundtrip_serialization(self):
        req = JsonRpcRequest(method="ping", id=1)
        data = req.model_dump_json()
        parsed = JsonRpcRequest.model_validate_json(data)
        assert parsed.method == req.method


class TestLLMModels:
    def test_token_usage_defaults(self):
        usage = TokenUsage()
        assert usage.prompt_tokens == 0
        assert usage.total_tokens == 0

    def test_llm_message(self):
        msg = LLMMessage(role="user", content="hello")
        assert msg.role == "user"

    def test_llm_request_minimal(self):
        req = LLMRequest(command=CommandType.explain, code="x = 1")
        assert req.language == ""
        assert req.model is None

    def test_llm_request_full(self):
        req = LLMRequest(
            command=CommandType.improve,
            code="def foo(): pass",
            language="python",
            filename="test.py",
            context="module context",
            model="gpt-4o",
        )
        assert req.command == CommandType.improve
        assert req.model == "gpt-4o"

    def test_llm_response(self):
        resp = LLMResponse(
            content="explanation",
            model="gpt-4o-mini",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )
        assert resp.usage.total_tokens == 15

    def test_stream_chunk(self):
        chunk = StreamChunk(content="hello")
        assert not chunk.done
        assert chunk.error is None

    def test_stream_chunk_done(self):
        chunk = StreamChunk(done=True)
        assert chunk.content == ""
        assert chunk.done

    def test_stream_chunk_error(self):
        chunk = StreamChunk(error="API error", done=True)
        assert chunk.error == "API error"
