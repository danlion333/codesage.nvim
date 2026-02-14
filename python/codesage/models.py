"""Core data models for CodeSage."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class CommandType(str, Enum):
    """Supported command types."""

    explain = "explain"
    improve = "improve"
    chat = "chat"


# --- JSON-RPC 2.0 ---


class JsonRpcRequest(BaseModel):
    """JSON-RPC 2.0 request object."""

    jsonrpc: str = "2.0"
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
    id: int | str | None = None


class JsonRpcError(BaseModel):
    """JSON-RPC 2.0 error object."""

    code: int
    message: str
    data: Any | None = None


class JsonRpcResponse(BaseModel):
    """JSON-RPC 2.0 response object."""

    jsonrpc: str = "2.0"
    result: Any | None = None
    error: JsonRpcError | None = None
    id: int | str | None = None


# --- LLM Types ---


class TokenUsage(BaseModel):
    """Token usage statistics from an LLM call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMMessage(BaseModel):
    """A single message in an LLM conversation."""

    role: str
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


class LLMRequest(BaseModel):
    """Request to the LLM provider."""

    command: CommandType
    code: str
    language: str = ""
    filename: str = ""
    context: str = ""
    model: str | None = None


class LLMResponse(BaseModel):
    """Response from the LLM provider."""

    content: str
    model: str
    usage: TokenUsage = Field(default_factory=TokenUsage)


class StreamChunk(BaseModel):
    """A single chunk from a streaming LLM response."""

    content: str = ""
    done: bool = False
    error: str | None = None
    chunk_type: str = "content"  # "content" | "status" | "tool_call"
