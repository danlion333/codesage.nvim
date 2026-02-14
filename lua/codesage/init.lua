--- CodeSage.nvim - AI-powered code intelligence
--- Plugin entry point

local M = {}

--- Default configuration
M.config = {
  keymaps = {
    explain = "<leader>ce",
    improve = "<leader>ci",
    chat = "<leader>cc",
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
    input_max_ratio = 0.5,
    auto_scroll = true,
    scrollbar = true,
    show_separator = true,
    user_header = "You",
    assistant_header = "CodeSage",
  },
}

--- Whether the plugin has been set up
M._setup_done = false

--- Setup CodeSage with user options
---@param opts? table User configuration overrides
function M.setup(opts)
  if M._setup_done then
    return
  end

  M.config = vim.tbl_deep_extend("force", M.config, opts or {})

  -- Detect plugin root (directory containing lua/ and python/)
  local source = debug.getinfo(1, "S").source:sub(2)
  M.plugin_root = vim.fn.fnamemodify(source, ":h:h:h")

  -- Set up highlight groups
  require("codesage.highlights").setup()

  -- Register commands
  local commands = require("codesage.commands")
  commands.register()

  -- Register keymaps
  M._setup_keymaps()

  -- Auto-start backend
  if M.config.backend.auto_start then
    vim.api.nvim_create_autocmd("VimEnter", {
      group = vim.api.nvim_create_augroup("CodeSageStart", { clear = true }),
      callback = function()
        vim.defer_fn(function()
          M.ensure_backend()
        end, 100)
      end,
    })
  end

  -- Auto-stop backend on exit
  vim.api.nvim_create_autocmd("VimLeavePre", {
    group = vim.api.nvim_create_augroup("CodeSageStop", { clear = true }),
    callback = function()
      local rpc = require("codesage.rpc")
      rpc.shutdown()
    end,
  })

  -- Notify backend on file save for incremental re-indexing
  vim.api.nvim_create_autocmd("BufWritePost", {
    group = vim.api.nvim_create_augroup("CodeSageIndex", { clear = true }),
    callback = function()
      local rpc = require("codesage.rpc")
      if rpc.is_connected() then
        rpc.notify("notify/file_changed", {
          filepath = vim.fn.expand("%:p"),
          language = vim.bo.filetype,
        })
      end
    end,
  })

  M._setup_done = true
end

--- Set up keybindings
function M._setup_keymaps()
  local km = M.config.keymaps

  -- Visual mode keymaps
  vim.keymap.set("v", km.explain, ":'<,'>CodeSageExplain<CR>", {
    desc = "CodeSage: Explain selection",
    silent = true,
  })
  vim.keymap.set("v", km.improve, ":'<,'>CodeSageImprove<CR>", {
    desc = "CodeSage: Improve selection",
    silent = true,
  })

  -- Normal mode keymaps
  vim.keymap.set("n", km.chat, ":CodeSageChat<CR>", {
    desc = "CodeSage: Chat",
    silent = true,
  })

  -- Visual mode chat keymap (sends selection)
  vim.keymap.set("v", km.chat, ":'<,'>CodeSageChat<CR>", {
    desc = "CodeSage: Chat with selection",
    silent = true,
  })
end

--- Backend startup state
M._backend_starting = false
M._backend_callbacks = {}

--- Ensure the backend is started and connected
---@param callback? function Called when backend is ready
function M.ensure_backend(callback)
  local rpc = require("codesage.rpc")

  if rpc.is_connected() then
    if callback then
      callback()
    end
    return
  end

  -- Queue callback if provided
  if callback then
    table.insert(M._backend_callbacks, callback)
  end

  -- Don't start a second backend if one is already starting
  if M._backend_starting then
    return
  end

  M._backend_starting = true
  rpc.start_backend(M.plugin_root, function()
    M._backend_starting = false
    local callbacks = M._backend_callbacks
    M._backend_callbacks = {}
    for _, cb in ipairs(callbacks) do
      cb()
    end
  end)
end

return M
