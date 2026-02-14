"""LLM provider integration via LiteLLM."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

import litellm

from codesage.config import CodeSageConfig
from codesage.llm.prompts import PromptManager
from codesage.models import LLMMessage, LLMRequest, LLMResponse, StreamChunk, TokenUsage

logger = logging.getLogger(__name__)


class LLMProvider:
    """Provides LLM completions via LiteLLM."""

    def __init__(self, config: CodeSageConfig, prompt_manager: PromptManager | None = None) -> None:
        self._config = config
        self._prompts = prompt_manager or PromptManager()

        # Suppress litellm's verbose logging
        litellm.suppress_debug_info = True

    def _get_model(self, request: LLMRequest) -> str:
        """Get the model to use, with request override taking precedence."""
        return request.model or self._config.models.default_model

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Send a non-streaming completion request.

        Args:
            request: The LLM request.

        Returns:
            The complete LLM response.

        Raises:
            Exception: On LLM API errors.
        """
        messages = self._prompts.render(request)
        model = self._get_model(request)

        response = await litellm.acompletion(
            model=model,
            messages=[m.model_dump() for m in messages],
            max_tokens=self._config.models.max_tokens,
            temperature=self._config.models.temperature,
        )

        content = response.choices[0].message.content or ""
        usage = TokenUsage()
        if response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens or 0,
                completion_tokens=response.usage.completion_tokens or 0,
                total_tokens=response.usage.total_tokens or 0,
            )

        return LLMResponse(content=content, model=model, usage=usage)

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamChunk]:
        """Send a streaming completion request.

        Yields StreamChunk objects. The final chunk has done=True.
        Errors are yielded as chunks with the error field set, not raised.

        Args:
            request: The LLM request.

        Yields:
            StreamChunk objects with content or error/done markers.
        """
        messages = self._prompts.render(request)
        model = self._get_model(request)

        try:
            response = await litellm.acompletion(
                model=model,
                messages=[m.model_dump() for m in messages],
                max_tokens=self._config.models.max_tokens,
                temperature=self._config.models.temperature,
                stream=True,
                stream_options={"include_usage": True},
            )

            usage: TokenUsage | None = None
            async for chunk in response:
                delta = chunk.choices[0].delta if chunk.choices else None
                content = delta.content if delta and delta.content else ""
                finish_reason = chunk.choices[0].finish_reason if chunk.choices else None

                # Capture usage from the final chunk
                if hasattr(chunk, "usage") and chunk.usage:
                    usage = TokenUsage(
                        prompt_tokens=chunk.usage.prompt_tokens or 0,
                        completion_tokens=chunk.usage.completion_tokens or 0,
                        total_tokens=chunk.usage.total_tokens or 0,
                    )

                if content:
                    yield StreamChunk(content=content)

                if finish_reason is not None:
                    yield StreamChunk(content="", done=True, usage=usage)
                    return

            # If we exhaust the iterator without a finish_reason
            yield StreamChunk(content="", done=True, usage=usage)

        except Exception as e:
            logger.error("LLM streaming error: %s", e)
            yield StreamChunk(error=str(e), done=True)

    async def complete_messages(
        self, messages: list[LLMMessage], model: str | None = None
    ) -> str:
        """Non-streaming completion from pre-built messages.

        Args:
            messages: Pre-built conversation messages.
            model: Optional model override.

        Returns:
            The complete response content string.
        """
        model = model or self._config.models.default_model

        response = await litellm.acompletion(
            model=model,
            messages=[m.model_dump(exclude_none=True) for m in messages],
            max_tokens=self._config.models.max_tokens,
            temperature=self._config.models.temperature,
        )

        content: str = response.choices[0].message.content or ""
        return content

    async def stream_messages(
        self, messages: list[LLMMessage], model: str | None = None
    ) -> AsyncIterator[StreamChunk]:
        """Stream a completion from pre-built messages (with conversation history).

        Args:
            messages: Pre-built conversation messages.
            model: Optional model override.

        Yields:
            StreamChunk objects with content or error/done markers.
        """
        model = model or self._config.models.default_model

        try:
            response = await litellm.acompletion(
                model=model,
                messages=[m.model_dump(exclude_none=True) for m in messages],
                max_tokens=self._config.models.max_tokens,
                temperature=self._config.models.temperature,
                stream=True,
                stream_options={"include_usage": True},
            )

            usage: TokenUsage | None = None
            async for chunk in response:
                delta = chunk.choices[0].delta if chunk.choices else None
                content = delta.content if delta and delta.content else ""
                finish_reason = chunk.choices[0].finish_reason if chunk.choices else None

                # Capture usage from the final chunk
                if hasattr(chunk, "usage") and chunk.usage:
                    usage = TokenUsage(
                        prompt_tokens=chunk.usage.prompt_tokens or 0,
                        completion_tokens=chunk.usage.completion_tokens or 0,
                        total_tokens=chunk.usage.total_tokens or 0,
                    )

                if content:
                    yield StreamChunk(content=content)

                if finish_reason is not None:
                    yield StreamChunk(content="", done=True, usage=usage)
                    return

            # If we exhaust the iterator without a finish_reason
            yield StreamChunk(content="", done=True, usage=usage)

        except Exception as e:
            logger.error("LLM streaming error: %s", e)
            yield StreamChunk(error=str(e), done=True)

    async def agentic_stream(
        self,
        messages: list[LLMMessage],
        tools: list[dict],
        tool_executor: Any,
        max_iterations: int = 10,
        model: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Run an agentic loop with tool calls, yielding stream chunks.

        Loops up to max_iterations:
        1. Call LLM with tools
        2. If tool_calls: yield status, execute tools, append results, continue
        3. If stop: yield final content as chunks

        Args:
            messages: Conversation messages (including system prompt).
            tools: Tool schemas for the LLM.
            tool_executor: ToolExecutor instance.
            max_iterations: Max agentic loop iterations.
            model: Model override.

        Yields:
            StreamChunk objects.
        """
        model = model or self._config.models.default_model
        msg_dicts = [m.model_dump(exclude_none=True) for m in messages]

        try:
            for iteration in range(max_iterations):
                response = await litellm.acompletion(
                    model=model,
                    messages=msg_dicts,
                    max_tokens=self._config.models.max_tokens,
                    temperature=self._config.models.temperature,
                    tools=tools,
                    tool_choice="auto",
                )

                choice = response.choices[0]
                assistant_msg = choice.message

                # Check for tool calls
                if assistant_msg.tool_calls:
                    # Add assistant message with tool calls to history
                    tc_dicts = []
                    parsed_calls: list[tuple[Any, str, dict]] = []
                    for tc in assistant_msg.tool_calls:
                        tc_dicts.append({
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        })
                        tool_name = tc.function.name
                        try:
                            tool_args = json.loads(tc.function.arguments)
                        except json.JSONDecodeError:
                            tool_args = {}
                        parsed_calls.append((tc, tool_name, tool_args))

                    msg_dicts.append({
                        "role": "assistant",
                        "content": assistant_msg.content,
                        "tool_calls": tc_dicts,
                    })

                    # Yield all status chunks upfront
                    for tc, tool_name, tool_args in parsed_calls:
                        args_str = ", ".join(f"{k}={v!r}" for k, v in tool_args.items())
                        yield StreamChunk(
                            content=f"> Using tool: {tool_name}({args_str})\n",
                            chunk_type="status",
                        )

                    # Execute all tool calls in parallel
                    async def _safe_execute(name: str, args: dict) -> str:
                        try:
                            return await tool_executor.execute(name, args)
                        except Exception as e:
                            return f"Error executing {name}: {e}"

                    results = await asyncio.gather(
                        *[_safe_execute(name, args) for _, name, args in parsed_calls]
                    )

                    # Append results in original order
                    for (tc, _, _), result in zip(parsed_calls, results):
                        msg_dicts.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        })

                    continue  # Next iteration

                # No tool calls — yield final content
                content = assistant_msg.content or ""
                if content:
                    yield StreamChunk(content=content)
                yield StreamChunk(content="", done=True)
                return

            # Exhausted iterations
            yield StreamChunk(
                content="\n\n(Reached maximum tool use iterations)",
                chunk_type="status",
            )
            yield StreamChunk(content="", done=True)

        except Exception as e:
            logger.error("Agentic loop error: %s", e)
            yield StreamChunk(error=str(e), done=True)
