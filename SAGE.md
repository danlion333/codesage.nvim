# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CodeSage is an AI-powered code intelligence plugin for Neovim. It uses a client-server architecture: a Lua frontend inside Neovim communicates with an async Python backend over Unix domain sockets using length-prefixed JSON-RPC 2.0 messages.

## Commands

```bash
# Install dependencies
uv sync

# Run all tests
pytest tests/ -v

# Run a single test file
pytest tests/test_handlers.py -v

# Run a single test
pytest tests/test_handlers.py::test_function_name -v

# Lint
ruff check python/codesage

# Type check
mypy python/codesage

# Run backend manually (for debugging)
uv run codesage
```

## Architecture

```
Neovim (Lua)  ←→  Unix Socket (JSON-RPC 2.0)  ←→  Python Backend (asyncio)
```

**Frontend** (`lua/codesage/`): Neovim plugin using `vim.uv` for async I/O. Entry point is `init.lua` (setup, keymaps, lifecycle). `rpc.lua` spawns the backend via `uv run codesage` and manages socket communication. `commands.lua` defines user commands. `ui.lua` renders floating windows via nui.nvim. `chat/` handles the multi-pane chat UI.

**Backend** (`python/codesage/`): Async JSON-RPC server. `server.py` handles socket connections with 4-byte big-endian length-prefixed messages. `handlers.py` dispatches RPC methods and assembles context. Key subsystems:
- `indexer/` — Tree-sitter symbol extraction (`symbols.py`), git-based project scanning (`project.py`), in-memory index (`index.py`), token-budgeted context assembly (`context.py`)
- `llm/` — LiteLLM provider wrapper (`provider.py`) supporting 100+ models, Jinja2 prompt rendering (`prompts.py`)
- `tools/` — Sandboxed tool execution for agentic mode (`executor.py`) with path traversal prevention and output truncation
- `chat/` — Session persistence to `~/.local/share/codesage/sessions/` with token-budgeted history

**Templates** (`templates/`): Jinja2 prompt templates for explain, improve, chat, and agentic system prompts.

## Code Conventions

- Python: Ruff for linting, mypy strict mode, line length 99
- Python 3.11+ required, uses Pydantic v2 for models and config
- Tests use pytest with `asyncio_mode="auto"` — async test functions run automatically
- Config hierarchy: env vars (`CODESAGE_` prefix) → project `.codesage.toml` → global `~/.config/codesage/config.toml` → defaults
