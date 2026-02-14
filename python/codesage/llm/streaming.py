"""Streaming utilities for CodeSage LLM integration."""

from __future__ import annotations

from typing import AsyncIterator

from codesage.models import LLMResponse, StreamChunk


async def collect_stream(chunks: AsyncIterator[StreamChunk]) -> LLMResponse:
    """Collect a stream of chunks into a single LLMResponse.

    Useful for testing and cases where the full response is needed.

    Args:
        chunks: An async iterator of StreamChunk objects.

    Returns:
        A complete LLMResponse with concatenated content.

    Raises:
        RuntimeError: If the stream contains an error chunk.
    """
    parts: list[str] = []

    async for chunk in chunks:
        if chunk.error:
            raise RuntimeError(f"Stream error: {chunk.error}")
        if chunk.content:
            parts.append(chunk.content)
        if chunk.done:
            break

    return LLMResponse(
        content="".join(parts),
        model="stream",
    )
