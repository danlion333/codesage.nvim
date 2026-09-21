# CodeSage

AI-powered code intelligence plugin for Neovim. Select code, get explanations and improvement suggestions streamed directly into a floating window.

**Status:** early — v0.1.0 (Tier 1, Foundations). It works and I use it daily,
but it is young: the API and defaults can still change between versions, some
modules are stubs (Telescope integration in particular), and rough edges are
expected. Issues and patches welcome.

## Features

- **Explain** (`<leader>ce`) — Select code and get a detailed explanation with project-aware context
- **Improve** (`<leader>ci`) — Get improvement suggestions with a quality rating
- **Chat** (`<leader>cc`) — Multi-turn conversations with persistent history and code-aware context
- **Project Indexing** — Automatic tree-sitter symbol extraction, import resolution, and project structure awareness
- **Agentic Tool Use** — The LLM can read files, search symbols, grep code, and explore your project to give deeper analysis
- **Streaming** — Responses stream in real-time to a floating window
- **Multi-model** — Supports 100+ LLM providers via LiteLLM (OpenAI, Anthropic, Google, etc.), switchable mid-session with `<leader>cm`
- **Command palette** (`<leader>cs`) — All actions from one menu
- **Git-diff context** — Uncommitted changes are folded into the context sent to the model
- **Token tracking** — Per-session token usage, visible in `:CodeSageStatus`

## Requirements

- Neovim 0.9+
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- [nui.nvim](https://github.com/MunifTanjim/nui.nvim) — floating windows and chat layout
- An API key for at least one LLM provider (Anthropic, OpenAI, Google, ...)

Tree-sitter is used for symbol extraction, but it runs on the Python side via
`tree-sitter-languages` — you do **not** need `nvim-treesitter` installed, and
grammars are pulled in by `uv sync`.

## Installation

Both plugin managers need to run `uv sync` after install so the Python backend
has its dependencies.

### lazy.nvim

```lua
{
  "danlion333/codesage.nvim",
  dependencies = { "MunifTanjim/nui.nvim" },
  build = "uv sync",
  config = function()
    require("codesage").setup()
  end,
}
```

### packer.nvim

```lua
use({
  "danlion333/codesage.nvim",
  requires = { "MunifTanjim/nui.nvim" },
  run = "uv sync",
  config = function()
    require("codesage").setup()
  end,
})
```

### Manual

```bash
git clone https://github.com/danlion333/codesage.nvim \
  ~/.local/share/nvim/site/pack/plugins/start/codesage.nvim
cd ~/.local/share/nvim/site/pack/plugins/start/codesage.nvim
uv sync
```

## Setup

### 1. API key

The key is read from an environment variable at runtime — it is never read from
a config file, and you should never commit it. Export it from your shell rc:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
# or, depending on the model you use
export OPENAI_API_KEY="sk-..."
export GEMINI_API_KEY="..."
```

Which variable gets read is controlled by `models.api_key_env` (default
`ANTHROPIC_API_KEY`). In agentic tool use the provider is detected from the
model string, so `openai/gpt-4o` looks up `OPENAI_API_KEY`.

### 2. Python backend

`uv sync` (run by `build`/`run` above, or by hand in the plugin directory)
installs the backend into a `.venv` inside the plugin. The backend is started
automatically as a subprocess when Neovim starts; there is no daemon to manage.
To check it came up:

```vim
:CodeSageStatus
```

### 3. Neovim config

`setup()` works with no arguments. The defaults are:

```lua
require("codesage").setup({
  keymaps = {
    explain = "<leader>ce",
    improve = "<leader>ci",
    chat = "<leader>cc",
    switch_model = "<leader>cm",
    palette = "<leader>cs",
  },
  models = {
    "anthropic/claude-sonnet-4-20250514",
    "anthropic/claude-haiku-4-20250514",
    "openai/gpt-4o",
    "openai/gpt-4o-mini",
    "google/gemini-2.0-flash",
  },
  ui = {
    width = 0.7,
    height = 0.6,
    streaming = true,
  },
  backend = {
    auto_start = true,
  },
  chat = {
    send_key = "<C-s>",
    input_min_height = 3,
    auto_scroll = true,
    scrollbar = true,
  },
})
```

## Usage

Visually select a block of code and press `<leader>ce`. A floating window opens
and the explanation streams in; `y` copies it, `q` closes it. `<leader>ci` does
the same but asks for improvements and a quality rating.

`<leader>cc` opens the chat pane — in visual mode it attaches the selection as
context. Type your message in the input box, send with `<C-s>`, `<Tab>` moves
focus between the transcript and the input. The session persists across Neovim
restarts (stored in `~/.local/share/codesage/sessions`), so you can pick a
conversation back up the next day; `:CodeSageChatNew` starts a fresh one.

`<leader>cs` opens the command palette if you would rather not remember the
individual maps, and `<leader>cm` switches the active model mid-session.

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
send_key = "<C-s>"                      # key to send message
input_min_height = 3                    # minimum input height
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
| `:CodeSageChatStop` | Normal | — | Stop the in-flight response |
| `:CodeSageSwitchModel` | Normal | `<leader>cm` | Switch the active model |
| `:CodeSagePalette` | Normal/Visual | `<leader>cs` | Open the command palette |
| `:CodeSageStatus` | Normal | — | Backend status, active model, token usage |

### Floating window controls

- `q` / `<Esc>` — Close window
- `y` — Copy response to clipboard

### Chat window controls

- `<C-s>` — Send message (configurable via `chat.send_key`)
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
│   ├── palette.lua            # Command palette
│   ├── highlights.lua         # Highlight groups
│   ├── telescope.lua          # Telescope integration (stub)
│   └── chat/
│       ├── init.lua           # Chat pane (nui layout)
│       ├── history.lua        # Message history display
│       ├── scrollbar.lua      # Transcript scrollbar
│       └── help.lua           # In-chat key help
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
└── .codesage.toml              # Project-local config (git-ignored)
```

## License

MIT — see [LICENSE](LICENSE).
