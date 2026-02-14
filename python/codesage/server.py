"""CodeSage JSON-RPC server over Unix domain socket."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import struct
from pathlib import Path

from rich.logging import RichHandler

from codesage.config import CodeSageConfig, load_config
from codesage.handlers import RequestHandler
from codesage.models import JsonRpcRequest, JsonRpcResponse, JsonRpcError

logger = logging.getLogger("codesage")

HEADER_SIZE = 4  # 4-byte big-endian length prefix


class CodeSageServer:
    """Async JSON-RPC server over Unix domain socket."""

    def __init__(self, config: CodeSageConfig) -> None:
        self._config = config
        self._socket_path = config.server.get_socket_path()
        self._handler = RequestHandler(config)
        self._server: asyncio.AbstractServer | None = None
        self._shutdown_event = asyncio.Event()
        self._cancel_events: dict[int, asyncio.Event] = {}

    @property
    def socket_path(self) -> str:
        return self._socket_path

    async def start(self) -> None:
        """Start the server and listen for connections."""
        # Clean up stale socket
        socket_path = Path(self._socket_path)
        if socket_path.exists():
            socket_path.unlink()

        self._server = await asyncio.start_unix_server(
            self._handle_connection,
            path=self._socket_path,
        )

        # Set socket permissions to owner-only
        os.chmod(self._socket_path, 0o600)

        # Print socket path for the NeoVim plugin to capture
        startup_msg = json.dumps({"socket": self._socket_path})
        print(startup_msg, flush=True)
        logger.info("Server listening on %s", self._socket_path)

        # Start background index build
        asyncio.create_task(self._build_index())

        await self._shutdown_event.wait()

    async def _build_index(self) -> None:
        """Build the project index in the background."""
        try:
            # Determine project root (cwd)
            root = Path.cwd()
            logger.info("Building project index for: %s", root)
            await self._handler._index.build(root, self._config)
            self._handler.set_project_root(root)
            logger.info("Project index ready")
        except Exception as e:
            logger.error("Failed to build project index: %s", e)

    async def stop(self) -> None:
        """Stop the server and clean up."""
        logger.info("Shutting down server...")
        if self._server:
            self._server.close()
            await self._server.wait_closed()

        socket_path = Path(self._socket_path)
        if socket_path.exists():
            socket_path.unlink()

        self._shutdown_event.set()

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single client connection."""
        logger.debug("Client connected")
        try:
            while True:
                # Read length prefix
                header = await reader.readexactly(HEADER_SIZE)
                length = struct.unpack("!I", header)[0]

                # Read payload
                data = await reader.readexactly(length)
                message = data.decode("utf-8")
                logger.debug("Received: %s", message[:200])

                try:
                    raw = json.loads(message)
                    request = JsonRpcRequest.model_validate(raw)
                except Exception as e:
                    response = JsonRpcResponse(
                        error=JsonRpcError(code=-32700, message=f"Parse error: {e}"),
                    )
                    await self._send_response(writer, response)
                    continue

                # Handle stream/cancel notification (no id, but method starts with stream/)
                if request.id is None and request.method == "stream/cancel":
                    cancel_id = request.params.get("id")
                    if cancel_id is not None:
                        event = self._cancel_events.get(cancel_id)
                        if event is not None:
                            event.set()
                            logger.debug("Cancelled request %s", cancel_id)
                    continue

                # Notifications (no id) — fire and forget
                if request.id is None and request.method.startswith("notify/"):
                    await self._handler.handle_notification(
                        request.method, request.params
                    )
                    continue

                # Check if this is a streaming request
                if request.method.startswith("stream/"):
                    cancel_event = asyncio.Event()
                    self._cancel_events[request.id] = cancel_event
                    try:
                        async for chunk in self._handler.dispatch_stream(
                            request, cancel_event=cancel_event
                        ):
                            chunk_response = JsonRpcResponse(
                                result=chunk.model_dump(),
                                id=request.id,
                            )
                            await self._send_response(writer, chunk_response)
                    finally:
                        self._cancel_events.pop(request.id, None)
                else:
                    response = await self._handler.dispatch(request)
                    await self._send_response(writer, response)

                    # Handle shutdown
                    if request.method == "shutdown":
                        await self.stop()
                        return

        except asyncio.IncompleteReadError:
            logger.debug("Client disconnected")
        except Exception as e:
            logger.error("Connection error: %s", e)
        finally:
            writer.close()
            await writer.wait_closed()

    async def _send_response(
        self,
        writer: asyncio.StreamWriter,
        response: JsonRpcResponse,
    ) -> None:
        """Send a length-prefixed JSON response."""
        payload = response.model_dump_json().encode("utf-8")
        header = struct.pack("!I", len(payload))
        writer.write(header + payload)
        await writer.drain()


def main() -> None:
    """Entry point for the CodeSage backend server."""
    config = load_config()

    # Set up logging with rich
    logging.basicConfig(
        level=getattr(logging, config.server.log_level),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
    )

    server = CodeSageServer(config)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Signal handlers for clean shutdown
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: loop.create_task(server.stop()))

    try:
        loop.run_until_complete(server.start())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
