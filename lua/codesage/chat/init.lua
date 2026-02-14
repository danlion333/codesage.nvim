--- CodeSage Chat — main orchestrator
--- Layout, lifecycle, session management, send/receive, keymaps, dynamic input sizing
local M = {}

local Popup = require("nui.popup")
local Layout = require("nui.layout")
local history_mod = require("codesage.chat.history")
local scrollbar_mod = require("codesage.chat.scrollbar")
local help = require("codesage.chat.help")

local SESSION_FILE = vim.fn.stdpath("data") .. "/codesage/session_id"

--- Load persisted session ID from disk
---@return string|nil
local function load_session_id()
  local session_file = io.open(SESSION_FILE, "r")
  if not session_file then
    return nil
  end
  local session_id = session_file:read("*a"):match("^%s*(.-)%s*$")
  session_file:close()
  if session_id == "" then
    return nil
  end
  return session_id
end

--- Persist session ID to disk
---@param session_id string|nil
local function save_session_id(session_id)
  -- Ensure directory exists
  vim.fn.mkdir(vim.fn.fnamemodify(SESSION_FILE, ":p:h"), "p")
  if session_id then
    local f = io.open(SESSION_FILE, "w")
    if f then
      f:write(session_id)
      f:close()
    end
  else
    vim.fn.delete(SESSION_FILE)
  end
end
--- State
local current_session_id = nil
local layout = nil
local history_popup = nil
local input_popup = nil
local history = nil ---@type ChatHistory|nil
local scrollbar = nil ---@type Scrollbar|nil
local active_request_id = nil
local augroup = vim.api.nvim_create_augroup("CodeSageChat", { clear = true })

--- Get chat config with defaults
---@return table
local function chat_config()
  local codesage = require("codesage")
  local defaults = {
    send_key = "<C-s>",
    input_min_height = 3,
    input_max_ratio = 0.5,
    auto_scroll = true,
    scrollbar = true,
    show_separator = true,
    user_header = "You",
    assistant_header = "CodeSage",
  }
  return vim.tbl_deep_extend("force", defaults, codesage.config.chat or {})
end

--- Compute the desired input height based on content and wrapping
---@return integer
local function compute_input_height()
  if not input_popup or not input_popup.bufnr or not vim.api.nvim_buf_is_valid(input_popup.bufnr) then
    return chat_config().input_min_height
  end

  local cfg = chat_config()
  local lines = vim.api.nvim_buf_get_lines(input_popup.bufnr, 0, -1, false)
  local total_config = require("codesage").config.ui
  local layout_height = math.floor(vim.o.lines * total_config.height)
  local max_input = math.floor(layout_height * cfg.input_max_ratio)

  -- Count wrapped lines
  local visual_lines = 0
  local input_width = input_popup.winid and vim.api.nvim_win_is_valid(input_popup.winid)
      and vim.api.nvim_win_get_width(input_popup.winid)
    or 60

  for _, line in ipairs(lines) do
    -- Each line takes at least 1 visual line, plus wraps
    local len = vim.fn.strdisplaywidth(line)
    visual_lines = visual_lines + math.max(1, math.ceil((len + 1) / math.max(1, input_width)))
  end

  return math.max(cfg.input_min_height, math.min(visual_lines + 2, max_input))
end

--- Update the layout split sizes based on current input content
local function update_layout_size()
  if not layout or not input_popup then
    return
  end

  local desired = compute_input_height()
  local total_config = require("codesage").config.ui
  local layout_height = math.floor(vim.o.lines * total_config.height)

  -- nui Layout.Box sizes are percentages or fixed
  -- We use percentage approach: input% = desired / layout_height
  local input_pct = math.floor((desired / layout_height) * 100)
  input_pct = math.max(10, math.min(input_pct, 50))
  local history_pct = 100 - input_pct

  layout:update(Layout.Box({
    Layout.Box(history_popup, { size = history_pct .. "%" }),
    Layout.Box(input_popup, { size = input_pct .. "%" }),
  }, { dir = "col" }))

  -- Re-attach scrollbar to possibly resized history window
  if scrollbar then
    vim.schedule(function()
      scrollbar:update()
    end)
  end
end

--- Send the current input as a chat message
local function send_message()
  if not current_session_id then
    vim.notify("[CodeSage] No active chat session", vim.log.levels.WARN)
    return
  end

  local rpc = require("codesage.rpc")

  if not rpc.is_connected() then
    vim.notify("[CodeSage] Not connected to backend", vim.log.levels.WARN)
    return
  end

  -- Get input text
  local lines = vim.api.nvim_buf_get_lines(input_popup.bufnr, 0, -1, false)
  local message = table.concat(lines, "\n")

  if message:match("^%s*$") then
    return
  end

  -- Clear input and reset size
  vim.api.nvim_buf_set_option(input_popup.bufnr, "modifiable", true)
  vim.api.nvim_buf_set_lines(input_popup.bufnr, 0, -1, false, { "" })

  -- Reset input height
  vim.schedule(function()
    update_layout_size()
  end)

  local cfg = chat_config()

  -- Handle slash commands
  local trimmed = vim.trim(message)
  if trimmed == "/clear" then
    rpc.request("chat/clear_session", { session_id = current_session_id }, function()
      vim.schedule(function()
        if history then
          history:clear()
        end
        if scrollbar then
          scrollbar:update()
        end
        vim.notify("[CodeSage] Chat session cleared", vim.log.levels.INFO)
      end)
    end)
    return
  end

  if trimmed == "/compact" then
    vim.notify("[CodeSage] Compacting conversation...", vim.log.levels.INFO)
    rpc.request("chat/compact_session", { session_id = current_session_id }, function(response)
      vim.schedule(function()
        if history then
          history:clear()
        end
        if scrollbar then
          scrollbar:update()
        end
        if response.error and response.error ~= vim.NIL then
          local msg = type(response.error) == "table" and response.error.message or tostring(response.error)
          vim.notify("[CodeSage] Compact failed: " .. (msg or "Unknown error"), vim.log.levels.ERROR)
        else
          vim.notify("[CodeSage] Context compacted", vim.log.levels.INFO)
        end
      end)
    end)
    return
  end

  -- Append user message to history
  history:append_user_message(message, cfg.user_header, cfg.show_separator)

  -- Start assistant response
  history:start_assistant_response(cfg.assistant_header, cfg.show_separator)

  -- Send via RPC
  active_request_id = rpc.request("stream/chat/send_message", {
    session_id = current_session_id,
    message = message,
  }, function(response)
    -- Final callback
    vim.schedule(function()
      active_request_id = nil

      if not history then
        return
      end

      if response.error and response.error ~= vim.NIL then
        local msg = type(response.error) == "table" and response.error.message or tostring(response.error)
        history:append_error(msg or "Unknown error")
      end

      history:finish_assistant_response(cfg.assistant_header, cfg.show_separator)

      if scrollbar then
        scrollbar:update()
      end
    end)
  end, function(chunk)
    -- Stream callback
    vim.schedule(function()
      if not history then
        return
      end

      if chunk.error and chunk.error ~= vim.NIL then
        history:append_error(tostring(chunk.error))
        return
      end

      if chunk.content and chunk.content ~= "" then
        history:append_streaming_content(chunk.content)
      end

      if scrollbar then
        scrollbar:update()
      end
    end)
  end)
end

--- Stop the current generation
local function stop_generation()
  if active_request_id then
    local rpc = require("codesage.rpc")
    rpc.cancel_request(active_request_id)
    active_request_id = nil

    if history then
      local cfg = chat_config()
      history:finish_assistant_response(cfg.assistant_header, cfg.show_separator)
    end

    if scrollbar then
      scrollbar:update()
    end
  end
end

--- Close the chat UI (session persists)
local function close_chat()
  -- Clear autocmds
  vim.api.nvim_clear_autocmds({ group = augroup })

  -- Destroy scrollbar
  if scrollbar then
    scrollbar:destroy()
    scrollbar = nil
  end

  if layout then
    layout:unmount()
    layout = nil
    history_popup = nil
    input_popup = nil
    history = nil
  end
end

--- Set up keymaps for both panes
local function setup_keymaps()
  local cfg = chat_config()

  -- == Input pane ==

  -- <C-s> (or configured key) in insert mode: send message
  input_popup:map("i", cfg.send_key, function()
    vim.cmd("stopinsert")
    send_message()
    vim.cmd("startinsert")
  end, { noremap = true, desc = "Send message" })

  -- <CR> in normal mode: send message
  input_popup:map("n", "<CR>", function()
    send_message()
  end, { noremap = true, desc = "Send message" })

  -- q in normal mode: close chat
  input_popup:map("n", "q", close_chat, { noremap = true, desc = "Close chat" })

  -- ? in normal mode: show help
  input_popup:map("n", "?", function()
    help.show()
  end, { noremap = true, desc = "Show help" })

  -- <Tab>: switch focus to history
  input_popup:map("n", "<Tab>", function()
    if history_popup.winid and vim.api.nvim_win_is_valid(history_popup.winid) then
      vim.api.nvim_set_current_win(history_popup.winid)
    end
  end, { noremap = true, desc = "Focus history" })

  -- == History pane ==

  -- ]] and [[ for message navigation
  history_popup:map("n", "]]", function()
    if history then
      history:jump_next_message()
    end
  end, { noremap = true, desc = "Next message" })

  history_popup:map("n", "[[", function()
    if history then
      history:jump_prev_message()
    end
  end, { noremap = true, desc = "Previous message" })

  -- gy: copy code block under cursor
  history_popup:map("n", "gy", function()
    if history then
      local code = history:get_code_block_at_cursor()
      if code then
        vim.fn.setreg("+", code)
        vim.notify("[CodeSage] Code block copied to clipboard", vim.log.levels.INFO)
      else
        vim.notify("[CodeSage] No code block under cursor", vim.log.levels.INFO)
      end
    end
  end, { noremap = true, desc = "Copy code block" })

  -- <C-c>: stop generation
  history_popup:map("n", "<C-c>", function()
    stop_generation()
  end, { noremap = true, desc = "Stop generation" })

  -- <Tab>: switch focus to input
  history_popup:map("n", "<Tab>", function()
    if input_popup.winid and vim.api.nvim_win_is_valid(input_popup.winid) then
      vim.api.nvim_set_current_win(input_popup.winid)
      vim.cmd("startinsert")
    end
  end, { noremap = true, desc = "Focus input" })

  -- q: close chat
  history_popup:map("n", "q", close_chat, { noremap = true, desc = "Close chat" })

  -- ?: show help
  history_popup:map("n", "?", function()
    help.show()
  end, { noremap = true, desc = "Show help" })

  -- G: re-enable auto-scroll
  history_popup:map("n", "G", function()
    -- Execute default G first
    vim.cmd("normal! G")
    if history then
      history:enable_auto_scroll()
    end
  end, { noremap = true, desc = "Go to bottom + enable auto-scroll" })
end

--- Set up autocmds for dynamic resizing and scroll tracking
local function setup_autocmds()
  -- Dynamic input resizing
  vim.api.nvim_create_autocmd({ "TextChanged", "TextChangedI" }, {
    group = augroup,
    buffer = input_popup.bufnr,
    callback = function()
      update_layout_size()
    end,
  })

  -- Scroll tracking for auto-scroll
  vim.api.nvim_create_autocmd("WinScrolled", {
    group = augroup,
    callback = function(args)
      -- Check if the scrolled window is our history window
      if history and history_popup and history_popup.winid then
        local scrolled_win = tonumber(args.match)
        if scrolled_win == history_popup.winid then
          history:on_scroll()
          if scrollbar then
            scrollbar:update()
          end
        end
      end
    end,
  })
end

--- Create and open the chat UI
---@param selection? table Optional code selection { code, language, filename }
function M.open(selection)
  local codesage = require("codesage")
  local rpc = require("codesage.rpc")
  local ui_config = codesage.config.ui
  local cfg = chat_config()

  -- If chat is already open, just focus it
  if layout and history_popup and history_popup.winid and vim.api.nvim_win_is_valid(history_popup.winid) then
    if input_popup.winid and vim.api.nvim_win_is_valid(input_popup.winid) then
      vim.api.nvim_set_current_win(input_popup.winid)
      vim.cmd("startinsert")
    end
    return
  end

  -- Create history popup (top)
  history_popup = Popup({
    enter = false,
    focusable = true,
    border = {
      style = "rounded",
      text = {
        top = " CodeSage Chat ",
        top_align = "center",
      },
    },
    buf_options = {
      modifiable = false,
      filetype = "markdown",
    },
    win_options = {
      winblend = 5,
      wrap = true,
      conceallevel = 2,
      concealcursor = "nc",
    },
  })

  -- Create input popup (bottom)
  input_popup = Popup({
    enter = true,
    focusable = true,
    border = {
      style = "rounded",
      text = {
        top = " Message (" .. cfg.send_key .. " to send) ",
        top_align = "left",
      },
    },
    buf_options = {
      modifiable = true,
      filetype = "markdown",
    },
    win_options = {
      winblend = 5,
      wrap = true,
    },
  })

  -- Create split layout
  local layout_width = math.floor(vim.o.columns * ui_config.width)
  local layout_height = math.floor(vim.o.lines * ui_config.height)

  -- Calculate initial input percentage
  local input_pct = math.max(10, math.floor((cfg.input_min_height / layout_height) * 100))
  local history_pct = 100 - input_pct

  layout = Layout(
    {
      position = "50%",
      size = {
        width = layout_width,
        height = layout_height,
      },
    },
    Layout.Box({
      Layout.Box(history_popup, { size = history_pct .. "%" }),
      Layout.Box(input_popup, { size = input_pct .. "%" }),
    }, { dir = "col" })
  )

  layout:mount()

  -- Create history manager
  history = history_mod.new(history_popup.bufnr)
  history:set_winid(history_popup.winid)
  history.auto_scroll = cfg.auto_scroll

  -- Create scrollbar
  if cfg.scrollbar and history_popup.winid then
    scrollbar = scrollbar_mod.new(history_popup.winid)
    scrollbar:update()
  end

  -- Set up keymaps and autocmds
  setup_keymaps()
  setup_autocmds()

  -- Start in insert mode
  vim.cmd("startinsert")

  current_session_id = load_session_id()
  -- Create or reuse session
  codesage.ensure_backend(function()
    if not current_session_id then
      local params = {}
      if selection then
        params.code = selection.code or ""
        params.language = selection.language or ""
        params.filename = selection.filename or ""
      end

      rpc.request("chat/create_session", params, function(response)
  		vim.schedule(function()
    	  if response.result then
      		current_session_id = response.result.session_id
      		  save_session_id(current_session_id)  -- Add this line
    		end
  		  end)
	  end)
    else
      -- Restore previous messages into the UI
      rpc.request("chat/get_session_messages", { session_id = current_session_id }, function(response)
        vim.schedule(function()
          if not history or not response.result then
            return
          end
          local messages = response.result.messages
          if not messages or #messages == 0 then
            return
          end
          for _, msg in ipairs(messages) do
            if msg.role == "user" then
              history:append_user_message(msg.content or "", cfg.user_header, cfg.show_separator)
            elseif msg.role == "assistant" then
              history:append_assistant_message(msg.content or "", cfg.assistant_header, cfg.show_separator)
            end
          end
          if scrollbar then
            scrollbar:update()
          end
        end)
      end)
    end
  end)
end

--- Clear the current chat session
function M.clear()
  if not current_session_id then
    vim.notify("[CodeSage] No active chat session", vim.log.levels.INFO)
    return
  end

  local rpc = require("codesage.rpc")

  rpc.request("chat/clear_session", { session_id = current_session_id }, function(response)
    vim.schedule(function()
      if history then
        history:clear()
      end
      if scrollbar then
        scrollbar:update()
      end
      vim.notify("[CodeSage] Chat session cleared", vim.log.levels.INFO)
    end)
  end)
end

--- Start a new chat session
function M.new_session()
  close_chat()
  current_session_id = nil
  save_session_id(nil)  -- Add this line
end

--- Stop the current generation (for use as a command)
function M.stop()
  stop_generation()
end

return M
