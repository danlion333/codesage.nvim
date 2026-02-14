"""Request handlers for CodeSage JSON-RPC server."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import AsyncIterator

from codesage import __version__
from codesage.chat.session import SessionManager
from codesage.config import CodeSageConfig
from codesage.indexer.context import ContextAssembler
from codesage.indexer.index import SymbolIndex
from codesage.llm.prompts import PromptManager
from codesage.llm.provider import LLMProvider
from codesage.models import (
    CommandType,
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
    LLMMessage,
    LLMRequest,
    StreamChunk,
)
from codesage.tools.definitions import TOOL_SCHEMAS
from codesage.tools.executor import ToolExecutor

logger = logging.getLogger(__name__)


class RequestHandler:
    """Dispatches JSON-RPC requests to the appropriate handler."""

    def __init__(self, config: CodeSageConfig) -> None:
        self._config = config
        self._prompt_manager = PromptManager()
        self._llm = LLMProvider(config, self._prompt_manager)
        self._index = SymbolIndex()
        self._context_assembler: ContextAssembler | None = None
        self._tool_executor: ToolExecutor | None = None
        self._session_manager = SessionManager()
        self._project_root: Path | None = None

        # Load persisted sessions
        self._session_manager.load_sessions()

        self._methods = {
            "ping": self._handle_ping,
            "shutdown": self._handle_shutdown,
            "explain": self._handle_explain,
            "improve": self._handle_improve,
            "chat": self._handle_chat,
            "chat/create_session": self._handle_create_session,
            "chat/list_sessions": self._handle_list_sessions,
            "chat/clear_session": self._handle_clear_session,
            "chat/delete_session": self._handle_delete_session,
            "chat/get_session_messages": self._handle_get_session_messages,
            "chat/compact_session": self._handle_compact_session,
        }

        self._stream_methods = {
            "stream/explain": CommandType.explain,
            "stream/improve": CommandType.improve,
            "stream/chat": CommandType.chat,
        }

    def set_project_root(self, root: Path) -> None:
        """Set the project root after index build. Initializes ToolExecutor and ContextAssembler."""
        self._project_root = root
        self._tool_executor = ToolExecutor(root, self._index, self._config)
        self._context_assembler = ContextAssembler(
            self._index,
            self._config.context,
            self._config.models.default_model,
        )

    def _load_sage_md(self) -> str:
        """Load SAGE.md from project root if it exists.
    
        Returns:
        Content of SAGE.md if found, empty string otherwise.
        """
        if self._project_root is None:
            return ""
    
        sage_path = self._project_root / "SAGE.md"
        if sage_path.exists():
            try:
                return sage_path.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning("Failed to read SAGE.md: %s", e)
        return ""
  

    async def dispatch(self, request: JsonRpcRequest) -> JsonRpcResponse:
        """Dispatch a non-streaming JSON-RPC request."""
        handler = self._methods.get(request.method)
        if handler is None:
            return JsonRpcResponse(
                error=JsonRpcError(
                    code=-32601,
                    message=f"Method not found: {request.method}",
                ),
                id=request.id,
            )

        try:
            result = await handler(request)
            return JsonRpcResponse(result=result, id=request.id)
        except Exception as e:
            logger.error("Handler error for %s: %s", request.method, e)
            return JsonRpcResponse(
                error=JsonRpcError(code=-32000, message=str(e)),
                id=request.id,
            )

    async def dispatch_stream(
        self,
        request: JsonRpcRequest,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Dispatch a streaming JSON-RPC request."""
        # Handle chat/send_message streaming
        if request.method == "stream/chat/send_message":
            async for chunk in self._handle_chat_send_message(
                request, cancel_event=cancel_event
            ):
                yield chunk
            return

        command = self._stream_methods.get(request.method)
        if command is None:
            yield StreamChunk(
                error=f"Method not found: {request.method}",
                done=True,
            )
            return

        try:
            llm_request = self._build_llm_request(command, request.params)

            # Use agentic mode if enabled and index is built
            if (
                self._config.agentic.enabled
                and self._index.is_built
                and self._tool_executor is not None
            ):
                # Build context-enriched messages
                messages = self._prompt_manager.render_with_system(
                    llm_request,
                    "system_agentic.j2",
                    {"context": llm_request.context},
                )
                async for chunk in self._llm.agentic_stream(
                    messages=messages,
                    tools=TOOL_SCHEMAS,
                    tool_executor=self._tool_executor,
                    max_iterations=self._config.agentic.max_iterations,
                    model=llm_request.model,
                ):
                    if cancel_event and cancel_event.is_set():
                        yield StreamChunk(content="", done=True)
                        return
                    yield chunk
            else:
                async for chunk in self._llm.stream(llm_request):
                    if cancel_event and cancel_event.is_set():
                        yield StreamChunk(content="", done=True)
                        return
                    yield chunk
        except Exception as e:
            logger.error("Stream handler error for %s: %s", request.method, e)
            yield StreamChunk(error=str(e), done=True)

    def _build_llm_request(self, command: CommandType, params: dict) -> LLMRequest:
        """Build an LLMRequest from JSON-RPC params, enriching with context if available."""
        context = params.get("context", "")

        # Assemble context from index if available
        if self._context_assembler and self._index.is_built:
            assembled = self._context_assembler.assemble(
                code=params.get("code", ""),
                filepath=params.get("filepath", ""),
                file_content=params.get("file_content", ""),
                language=params.get("language", ""),
            )
            rendered = assembled.render()
            if rendered:
                context = rendered

        return LLMRequest(
            command=command,
            code=params.get("code", ""),
            language=params.get("language", ""),
            filename=params.get("filename", ""),
            context=context,
            model=params.get("model"),
        )

    async def handle_notification(self, method: str, params: dict) -> None:
        """Handle a JSON-RPC notification (no response expected)."""
        if method == "notify/file_changed":
            filepath = params.get("filepath", "")
            language = params.get("language", "")
            if filepath and self._index.is_built:
                self._index.rebuild_file(Path(filepath), language)
                logger.debug("Re-indexed: %s", filepath)

    async def _handle_ping(self, request: JsonRpcRequest) -> dict:
        return {"status": "ok", "version": __version__}

    async def _handle_shutdown(self, request: JsonRpcRequest) -> dict:
        return {"status": "shutting_down"}

    async def _handle_explain(self, request: JsonRpcRequest) -> dict:
        llm_request = self._build_llm_request(CommandType.explain, request.params)
        response = await self._llm.complete(llm_request)
        return response.model_dump()

    async def _handle_improve(self, request: JsonRpcRequest) -> dict:
        llm_request = self._build_llm_request(CommandType.improve, request.params)
        response = await self._llm.complete(llm_request)
        return response.model_dump()

    async def _handle_chat(self, request: JsonRpcRequest) -> dict:
        llm_request = self._build_llm_request(CommandType.chat, request.params)
        response = await self._llm.complete(llm_request)
        return response.model_dump()

    # --- Chat session methods ---

    async def _handle_create_session(self, request: JsonRpcRequest) -> dict:
        session = self._session_manager.create_session(
            code=request.params.get("code", ""),
            language=request.params.get("language", ""),
            filename=request.params.get("filename", ""),
        )
        return {"session_id": session.id}

    async def _handle_list_sessions(self, request: JsonRpcRequest) -> dict:
        return {"sessions": self._session_manager.list_sessions()}

    async def _handle_clear_session(self, request: JsonRpcRequest) -> dict:
        session_id = request.params.get("session_id", "")
        success = self._session_manager.clear_session(session_id)
        return {"success": success}

    async def _handle_delete_session(self, request: JsonRpcRequest) -> dict:
        session_id = request.params.get("session_id", "")
        success = self._session_manager.delete_session(session_id)
        return {"success": success}

    async def _handle_get_session_messages(self, request: JsonRpcRequest) -> dict:
        session_id = request.params.get("session_id", "")
        session = self._session_manager.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        # Return only user/assistant messages (not system)
        return {
            "messages": [
                {"role": m.role, "content": m.content}
                for m in session.messages
                if m.role in ("user", "assistant")
            ]
        }

    async def _handle_compact_session(self, request: JsonRpcRequest) -> dict:
        session_id = request.params.get("session_id", "")
        session = self._session_manager.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        conv_messages = [m for m in session.messages if m.role in ("user", "assistant")]
        if not conv_messages:
            return {"success": True}

        # Build compaction prompt
        compact_template = self._prompt_manager._env.get_template("compact.j2")
        compact_system = compact_template.render()

        messages: list[LLMMessage] = [
            LLMMessage(role="system", content=compact_system),
            *conv_messages,
            LLMMessage(role="user", content="Please summarize the conversation above."),
        ]

        summary = await self._llm.complete_messages(messages)

        # Replace session messages with just the summary
        session.messages.clear()
        session.add_assistant_message(summary)
        self._session_manager.save_session(session_id)

        return {"success": True, "summary": summary}

    async def _handle_chat_send_message(
        self,
        request: JsonRpcRequest,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Handle streaming chat message with session history."""
        params = request.params
        session_id = params.get("session_id", "")
        message = params.get("message", "")

        session = self._session_manager.get_session(session_id)
        if not session:
            yield StreamChunk(error=f"Session not found: {session_id}", done=True)
            return

        # Add user message to session
        session.add_user_message(message)

        # Build messages for LLM
        # Start with system prompt
        sys_vars = {
            "code": session.attached_code,
            "language": session.attached_language,
            "filename": session.attached_filename,
            "context": "",
        }

        # Add project context if available
        sage_content = self._load_sage_md()

        # Add project context if available
        project_context = ""
        if self._context_assembler and self._index.is_built and session.attached_code:
            assembled = self._context_assembler.assemble(
                code=session.attached_code,
                filepath=session.attached_filename,
                language=session.attached_language,
            )
            project_context = assembled.render()

        # Combine SAGE.md with project context
        if sage_content:
            sys_vars["context"] = f"## SAGE.md\n\n{sage_content}\n\n{project_context}"
        elif project_context:
            sys_vars["context"] = project_context

        sys_template = self._prompt_manager._env.get_template("system_chat.j2")
        system_content = sys_template.render(**sys_vars)
        system_msg = LLMMessage(role="system", content=system_content)

        # Get conversation history within token budget
        history = session.get_messages_for_llm(
            max_tokens=self._config.context.max_context_tokens,
            model=self._config.models.default_model,
        )
        messages = [system_msg] + history

        # Stream response
        full_response = ""
        cancelled = False
        try:
            if (
                self._config.agentic.enabled
                and self._index.is_built
                and self._tool_executor is not None
            ):
                async for chunk in self._llm.agentic_stream(
                    messages=messages,
                    tools=TOOL_SCHEMAS,
                    tool_executor=self._tool_executor,
                    max_iterations=self._config.agentic.max_iterations,
                ):
                    if cancel_event and cancel_event.is_set():
                        cancelled = True
                        yield StreamChunk(content="", done=True)
                        break
                    if chunk.content and chunk.chunk_type == "content":
                        full_response += chunk.content
                    yield chunk
            else:
                async for chunk in self._llm.stream_messages(messages):
                    if cancel_event and cancel_event.is_set():
                        cancelled = True
                        yield StreamChunk(content="", done=True)
                        break
                    if chunk.content:
                        full_response += chunk.content
                    yield chunk
        except Exception as e:
            logger.error("Chat stream error: %s", e)
            yield StreamChunk(error=str(e), done=True)
            return

        # Save assistant response to session (even partial if cancelled)
        if full_response:
            session.add_assistant_message(full_response)

        # Persist session
        self._session_manager.save_session(session_id)

        if cancelled:
            logger.debug("Chat stream cancelled for session %s", session_id)
