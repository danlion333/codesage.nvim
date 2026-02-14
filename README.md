# CodeSage

AI-powered code intelligence plugin for Neovim. Select code, get explanations and improvement suggestions streamed directly into a floating window.

**Status:** v0.1.0 (Tier 1 - Foundations)

## Features

- **Explain** (`<leader>ce`) — Select code and get a detailed explanation with project-aware context
- **Improve** (`<leader>ci`) — Get improvement suggestions with a quality rating
- **Chat** (`<leader>cc`) — Multi-turn conversations with persistent history and code-aware context
- **Project Indexing** — Automatic tree-sitter symbol extraction, import resolution, and project structure awareness
- **Agentic Tool Use** — The LLM can read files, search symbols, grep code, and explore your project to give deeper analysis
- **Streaming** — Responses stream in real-time to a floating window
- **Multi-model** — Supports 100+ LLM providers via LiteLLM (OpenAI, Anthropic, Google, etc.)

## Requirements

- Neovim 0.9+
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- [nui.nvim](https://github.com/MunifTanjim/nui.nvim)

## Installation

### lazy.nvim

```lua
{
  "your-username/codesage",
  dependencies = { "MunifTanjim/nui.nvim" },
  build = "uv sync",
  config = function()
    require("codesage").setup()
  end,
}
```

### Manual

```bash
git clone https://github.com/your-username/codesage ~/.local/share/nvim/site/pack/plugins/start/codesage
cd ~/.local/share/nvim/site/pack/plugins/start/codesage
uv sync
```

## Setup

1. Set your API key:

```bash
export ANTHROPIC_API_KEY="sk-..."
# or
export OPENAI_API_KEY="sk-..."
```

2. Add to your Neovim config:

```lua
require("codesage").setup({
  keymaps = {
    explain = "<leader>ce",  -- default
    improve = "<leader>ci",  -- default
    chat = "<leader>cc",     -- default
  },
  ui = {
    width = 0.7,
    height = 0.6,
    streaming = true,
  },
  backend = {
    auto_start = true,
  },
})
```

## Configuration

Create a `.codesage.toml` in your project root to override defaults:

```toml
[models]
default_model = "anthropic/claude-sonnet-4-20250514"  # any LiteLLM-supported model
api_key_env = "ANTHROPIC_API_KEY"       # env var holding the API key
max_tokens = 4096
temperature = 0.3

[context]
max_context_tokens = 8000
include_imports = true
include_symbols = true
include_project_summary = true
include_related_symbols = true
max_file_tokens = 2000

[agentic]
enabled = true                          # enable agentic tool use
max_iterations = 20                     # max tool-use rounds per request
show_tool_calls = true                  # show tool call status in responses
allow_shell_commands = false            # allow the LLM to run shell commands

[ui]
float_width = 0.7
float_height = 0.6
streaming = true

[chat]
send_key = "<CR>"                       # key to send message
input_min_height = 1                    # minimum input height
auto_scroll = true                      # auto-scroll to bottom

[privacy]
telemetry = false
send_filenames = true
send_file_contents = true
exclude_patterns = [".env", "*.pem", "*.key", "credentials*", "secrets*"]
```

Configuration is loaded in this order (highest priority first):

1. Environment variables (`CODESAGE_` prefix, `__` for nesting)
2. Project `.codesage.toml`
3. `~/.config/codesage/config.toml`
4. Built-in defaults

## Commands

| Command | Mode | Keymap | Description |
|---------|------|--------|-------------|
| `:CodeSageExplain` | Visual | `<leader>ce` | Explain selected code |
| `:CodeSageImprove` | Visual | `<leader>ci` | Suggest improvements |
| `:CodeSageChat` | Normal/Visual | `<leader>cc` | Open chat (visual mode attaches selection) |
| `:CodeSageChatClear` | Normal | — | Clear current chat session history |
| `:CodeSageChatNew` | Normal | — | Start a new chat session |
| `:CodeSageStatus` | Normal | — | Show backend status |

### Floating window controls

- `q` / `<Esc>` — Close window
- `y` — Copy response to clipboard

### Chat window controls

- `<CR>` (normal) / `<C-CR>` (insert) — Send message
- `q` — Close chat (session persists)
- `<Tab>` — Switch focus between history and input

## Architecture

```
Neovim (Lua)                    Backend (Python)
┌──────────────┐   Unix socket   ┌──────────────┐
│  commands.lua │ ──── JSON-RPC ──→│  server.py   │
│  rpc.lua      │ ←── streaming ───│  handlers.py │
│  chat.lua     │                  │  indexer/    │
│  ui.lua       │                  │  llm/        │
└──────────────┘                  │  tools/      │
                                   │  chat/       │
                                   │  analysis/   │
                                   └──────────────┘
```

The backend starts automatically as a subprocess, communicates its socket path (`/tmp/codesage-{PID}.sock`) via stdout, and exchanges length-prefixed JSON-RPC 2.0 messages over the Unix socket.

On startup, the backend builds a project index using tree-sitter to extract symbols (functions, classes, imports) from all project files. This index powers context assembly, import resolution, and the agentic tool-use loop, giving the LLM rich project awareness beyond the selected code snippet.

## Development

```bash
# Install dependencies
uv sync

# Run tests
pytest tests/ -v

# Lint
ruff check python/codesage

# Type check
mypy python/codesage

# Run backend manually (for debugging)
uv run codesage
```

## Project Structure

```
├── plugin/codesage.lua        # Plugin loader
├── lua/codesage/
│   ├── init.lua               # Setup, keymaps, autocmds
│   ├── commands.lua           # User-facing commands
│   ├── rpc.lua                # JSON-RPC client (vim.uv)
│   ├── ui.lua                 # Floating window UI
│   └── chat/
│       ├── init.lua           # Chat module entry point
│       ├── session.lua        # Session management
│       ├── input.lua          # Input component
│       ├── history.lua        # Message history display
│       └── renderer.lua       # Message rendering
├── python/codesage/
│   ├── server.py              # Async JSON-RPC server
│   ├── config.py              # Configuration (TOML + env)
│   ├── handlers.py            # Request dispatch
│   ├── models.py              # Pydantic data models
│   ├── indexer/
│   │   ├── project.py         # Project scanner (git ls-files)
│   │   ├── symbols.py         # Tree-sitter symbol extraction
│   │   ├── index.py           # In-memory symbol index
│   │   └── context.py         # Token-budgeted context assembly
│   ├── llm/
│   │   ├── provider.py        # LiteLLM integration + agentic loop
│   │   ├── prompts.py         # Jinja2 prompt templates
│   │   └── streaming.py       # Stream utilities
│   ├── tools/
│   │   ├── definitions.py     # Tool schemas (OpenAI format)
│   │   └── executor.py        # Sandboxed tool execution
│   ├── chat/
│   │   └── session.py         # Session management + persistence
│   └── analysis/
│       ├── architecture.py    # Architecture analysis
│       ├── performance.py     # Performance analysis
│       ├── quality.py         # Code quality analysis
│       └── security.py        # Security analysis
├── templates/                  # Prompt templates (explain, improve, chat, agentic)
├── tests/                      # pytest suite
├── pyproject.toml
└── .codesage.toml              # Project-local config
```

## License

MIT
