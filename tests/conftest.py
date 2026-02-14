"""Shared test fixtures for CodeSage."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from codesage.config import CodeSageConfig
from codesage.models import LLMResponse, StreamChunk, TokenUsage


@pytest.fixture
def tmp_socket_path(tmp_path: Path) -> Path:
    """Provide a temporary socket path for testing."""
    return tmp_path / "test-codesage.sock"


@pytest.fixture
def mock_config(tmp_path: Path) -> CodeSageConfig:
    """Provide a test configuration."""
    return CodeSageConfig(
        models={"default_model": "gpt-4o-mini"},
        server={"socket_path": str(tmp_path / "test.sock")},
    )


@pytest.fixture
def mock_llm_response() -> LLMResponse:
    """Provide a mock LLM response."""
    return LLMResponse(
        content="This is a test explanation of the code.",
        model="gpt-4o-mini",
        usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
    )


@pytest.fixture
def mock_stream_chunks() -> list[StreamChunk]:
    """Provide mock streaming chunks."""
    return [
        StreamChunk(content="This is ", done=False),
        StreamChunk(content="a test ", done=False),
        StreamChunk(content="explanation.", done=False),
        StreamChunk(content="", done=True),
    ]


@pytest.fixture
def mock_litellm() -> MagicMock:
    """Provide a mock litellm module."""
    mock = MagicMock()
    mock.acompletion = AsyncMock()
    return mock
