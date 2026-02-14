"""Tests for LLM provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from codesage.config import CodeSageConfig
from codesage.llm.provider import LLMProvider
from codesage.llm.streaming import collect_stream
from codesage.models import CommandType, LLMRequest


@pytest.fixture
def config() -> CodeSageConfig:
    return CodeSageConfig(models={"default_model": "gpt-4o-mini"})


@pytest.fixture
def provider(config: CodeSageConfig) -> LLMProvider:
    return LLMProvider(config)


@pytest.fixture
def explain_request() -> LLMRequest:
    return LLMRequest(
        command=CommandType.explain,
        code="def hello(): return 'world'",
        language="python",
        filename="test.py",
    )


def _make_completion_response(content: str = "Test response") -> MagicMock:
    """Create a mock litellm completion response."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    response.usage = MagicMock()
    response.usage.prompt_tokens = 100
    response.usage.completion_tokens = 50
    response.usage.total_tokens = 150
    return response


def _make_stream_chunks(texts: list[str]) -> list[MagicMock]:
    """Create mock streaming chunks."""
    chunks = []
    for i, text in enumerate(texts):
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta = MagicMock()
        chunk.choices[0].delta.content = text
        chunk.choices[0].finish_reason = None
        chunks.append(chunk)

    # Final chunk with finish_reason
    final = MagicMock()
    final.choices = [MagicMock()]
    final.choices[0].delta = MagicMock()
    final.choices[0].delta.content = None
    final.choices[0].finish_reason = "stop"
    chunks.append(final)
    return chunks


class TestLLMProviderComplete:
    @pytest.mark.asyncio
    async def test_complete_basic(self, provider: LLMProvider, explain_request: LLMRequest):
        mock_response = _make_completion_response("This is an explanation.")

        with patch("codesage.llm.provider.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await provider.complete(explain_request)

        assert result.content == "This is an explanation."
        assert result.model == "gpt-4o-mini"
        assert result.usage.total_tokens == 150

    @pytest.mark.asyncio
    async def test_complete_with_model_override(self, provider: LLMProvider):
        request = LLMRequest(
            command=CommandType.explain,
            code="x = 1",
            model="gpt-4o",
        )
        mock_response = _make_completion_response()

        with patch("codesage.llm.provider.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)
            result = await provider.complete(request)

        assert result.model == "gpt-4o"
        call_kwargs = mock_litellm.acompletion.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o"


class TestLLMProviderStream:
    @pytest.mark.asyncio
    async def test_stream_basic(self, provider: LLMProvider, explain_request: LLMRequest):
        chunks = _make_stream_chunks(["Hello", " world", "!"])

        async def mock_async_iter():
            for c in chunks:
                yield c

        with patch("codesage.llm.provider.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_async_iter())
            result = await collect_stream(provider.stream(explain_request))

        assert result.content == "Hello world!"

    @pytest.mark.asyncio
    async def test_stream_error(self, provider: LLMProvider, explain_request: LLMRequest):
        with patch("codesage.llm.provider.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(side_effect=Exception("API Error"))

            chunks = []
            async for chunk in provider.stream(explain_request):
                chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0].error == "API Error"
        assert chunks[0].done is True
