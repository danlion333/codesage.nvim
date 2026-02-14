"""Tests for the agentic loop in LLMProvider."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from codesage.config import CodeSageConfig
from codesage.llm.provider import LLMProvider
from codesage.llm.streaming import collect_stream
from codesage.models import LLMMessage


@pytest.fixture
def config() -> CodeSageConfig:
    return CodeSageConfig(models={"default_model": "gpt-4o-mini"})


@pytest.fixture
def provider(config: CodeSageConfig) -> LLMProvider:
    return LLMProvider(config)


def _make_tool_call(tool_id: str, name: str, arguments: dict) -> MagicMock:
    """Create a mock tool call."""
    tc = MagicMock()
    tc.id = tool_id
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments)
    return tc


def _make_response(content: str = "", tool_calls: list | None = None) -> MagicMock:
    """Create a mock litellm response."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    response.choices[0].message.tool_calls = tool_calls
    response.choices[0].finish_reason = "stop" if not tool_calls else "tool_calls"
    return response


class TestAgenticStream:
    @pytest.mark.asyncio
    async def test_no_tool_calls(self, provider: LLMProvider):
        """LLM responds without using tools."""
        mock_response = _make_response(content="Here is my analysis.")

        with patch("codesage.llm.provider.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)

            messages = [LLMMessage(role="user", content="Explain this")]
            chunks = []
            async for chunk in provider.agentic_stream(
                messages=messages, tools=[], tool_executor=None
            ):
                chunks.append(chunk)

        assert len(chunks) == 2  # content + done
        assert chunks[0].content == "Here is my analysis."
        assert chunks[1].done is True

    @pytest.mark.asyncio
    async def test_single_tool_call(self, provider: LLMProvider):
        """LLM makes one tool call then responds."""
        tool_call = _make_tool_call("tc1", "read_file", {"path": "main.py"})
        tool_response = _make_response(tool_calls=[tool_call])
        final_response = _make_response(content="After reading the file, here's my analysis.")

        mock_executor = AsyncMock()
        mock_executor.execute = AsyncMock(return_value="def main(): pass")

        with patch("codesage.llm.provider.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[tool_response, final_response]
            )

            messages = [LLMMessage(role="user", content="Explain main.py")]
            chunks = []
            async for chunk in provider.agentic_stream(
                messages=messages, tools=[{"type": "function"}], tool_executor=mock_executor
            ):
                chunks.append(chunk)

        # Should have: status chunk, content chunk, done chunk
        status_chunks = [c for c in chunks if c.chunk_type == "status"]
        content_chunks = [c for c in chunks if c.chunk_type == "content" and c.content]
        assert len(status_chunks) >= 1
        assert "read_file" in status_chunks[0].content
        assert len(content_chunks) >= 1
        assert chunks[-1].done is True

        # Executor should have been called
        mock_executor.execute.assert_called_once_with("read_file", {"path": "main.py"})

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_in_sequence(self, provider: LLMProvider):
        """LLM makes multiple rounds of tool calls."""
        tc1 = _make_tool_call("tc1", "search_symbols", {"query": "main"})
        tc2 = _make_tool_call("tc2", "read_file", {"path": "main.py"})

        response1 = _make_response(tool_calls=[tc1])
        response2 = _make_response(tool_calls=[tc2])
        response3 = _make_response(content="Final analysis.")

        mock_executor = AsyncMock()
        mock_executor.execute = AsyncMock(side_effect=["[function] main", "def main(): pass"])

        with patch("codesage.llm.provider.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[response1, response2, response3]
            )

            messages = [LLMMessage(role="user", content="Analyze")]
            chunks = []
            async for chunk in provider.agentic_stream(
                messages=messages, tools=[{}], tool_executor=mock_executor
            ):
                chunks.append(chunk)

        status_chunks = [c for c in chunks if c.chunk_type == "status"]
        assert len(status_chunks) == 2
        assert mock_executor.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_max_iterations(self, provider: LLMProvider):
        """Stops after max_iterations even if LLM keeps calling tools."""
        tool_call = _make_tool_call("tc1", "read_file", {"path": "x.py"})
        tool_response = _make_response(tool_calls=[tool_call])

        mock_executor = AsyncMock()
        mock_executor.execute = AsyncMock(return_value="file contents")

        with patch("codesage.llm.provider.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=tool_response)

            messages = [LLMMessage(role="user", content="Analyze")]
            chunks = []
            async for chunk in provider.agentic_stream(
                messages=messages,
                tools=[{}],
                tool_executor=mock_executor,
                max_iterations=3,
            ):
                chunks.append(chunk)

        # Should have hit max iterations
        assert chunks[-1].done is True
        assert any("maximum" in c.content.lower() for c in chunks if c.content)
        assert mock_executor.execute.call_count == 3

    @pytest.mark.asyncio
    async def test_tool_execution_error(self, provider: LLMProvider):
        """Tool execution error is passed back to LLM."""
        tool_call = _make_tool_call("tc1", "read_file", {"path": "nope.py"})
        tool_response = _make_response(tool_calls=[tool_call])
        final_response = _make_response(content="File not found, here's what I know.")

        mock_executor = AsyncMock()
        mock_executor.execute = AsyncMock(return_value="Error: File not found")

        with patch("codesage.llm.provider.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[tool_response, final_response]
            )

            messages = [LLMMessage(role="user", content="Read nope.py")]
            chunks = []
            async for chunk in provider.agentic_stream(
                messages=messages, tools=[{}], tool_executor=mock_executor
            ):
                chunks.append(chunk)

        assert chunks[-1].done is True

    @pytest.mark.asyncio
    async def test_llm_api_error(self, provider: LLMProvider):
        """LLM API error is yielded as error chunk."""
        with patch("codesage.llm.provider.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(side_effect=Exception("API down"))

            messages = [LLMMessage(role="user", content="Analyze")]
            chunks = []
            async for chunk in provider.agentic_stream(
                messages=messages, tools=[], tool_executor=None
            ):
                chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0].error == "API down"
        assert chunks[0].done is True

    @pytest.mark.asyncio
    async def test_parallel_tool_calls_in_single_response(self, provider: LLMProvider):
        """LLM returns 2 tool_calls at once; both execute and both status chunks appear."""
        tc1 = _make_tool_call("tc1", "read_file", {"path": "main.py"})
        tc2 = _make_tool_call("tc2", "list_files", {"pattern": "*.py"})

        tool_response = _make_response(tool_calls=[tc1, tc2])
        final_response = _make_response(content="Done analyzing.")

        mock_executor = AsyncMock()
        mock_executor.execute = AsyncMock(
            side_effect=["def main(): pass", "main.py\nutils.py"]
        )

        with patch("codesage.llm.provider.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=[tool_response, final_response]
            )

            messages = [LLMMessage(role="user", content="Analyze")]
            chunks = []
            async for chunk in provider.agentic_stream(
                messages=messages, tools=[{}], tool_executor=mock_executor
            ):
                chunks.append(chunk)

        status_chunks = [c for c in chunks if c.chunk_type == "status"]
        assert len(status_chunks) == 2
        assert "read_file" in status_chunks[0].content
        assert "list_files" in status_chunks[1].content
        assert mock_executor.execute.call_count == 2
        assert chunks[-1].done is True
