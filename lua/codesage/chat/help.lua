--- Help popup showing keybinding reference
local M = {}

local ns = vim.api.nvim_create_namespace("codesage_chat_help")

local help_lines = {
  "CodeSage Chat Keybindings",
  "",
  "Input Pane:",
  "  <CR>      Newline (insert mode)",
  "  <C-s>     Send message (insert mode)",
  "  <CR>      Send message (normal mode)",
  "  <Tab>     Focus history pane",
  "  q         Close chat",
  "  ?         Show this help",
  "",
  "History Pane:",
  "  j/k       Scroll line by line",
  "  <C-d/u>   Scroll half page",
  "  gg/G      Go to top/bottom",
  "  ]]        Jump to next message",
  "  [[        Jump to previous message",
  "  gy        Copy code block under cursor",
  "  <C-c>     Stop generation",
  "  <Tab>     Focus input pane",
  "  q         Close chat",
  "  ?         Show this help",
}

--- Compute highlight ranges for the help buffer
---@return table[] List of { line, col_start, col_end, hl_group }
local function get_highlights()
  local hls = {}
  -- Title line
  table.insert(hls, { 0, 0, #help_lines[1], "Title" })

  -- Section headers
  for i, line in ipairs(help_lines) do
    if line:match("^%w.+:$") then
      table.insert(hls, { i - 1, 0, #line, "Title" })
    end
    -- Key bindings: text before first whitespace gap
    local key_start, key_end = line:match("^  ()(%S+)")
    if key_start and key_end then
      table.insert(hls, { i - 1, key_start - 1, key_start - 1 + #key_end, "CodeSageHelpKey" })
      -- Description after the key
      local desc_start = line:find("%S", key_start + #key_end + 1)
      if desc_start then
        table.insert(hls, { i - 1, desc_start - 1, #line, "CodeSageHelpDesc" })
      end
    end
  end

  return hls
end

--- Show the help popup
---@return integer|nil winid The help window ID
function M.show()
  local buf = vim.api.nvim_create_buf(false, true)
  vim.api.nvim_buf_set_lines(buf, 0, -1, false, help_lines)
  vim.api.nvim_buf_set_option(buf, "modifiable", false)
  vim.api.nvim_buf_set_option(buf, "bufhidden", "wipe")

  local width = 46
  local height = #help_lines

  local winid = vim.api.nvim_open_win(buf, true, {
    relative = "editor",
    row = math.floor((vim.o.lines - height) / 2),
    col = math.floor((vim.o.columns - width) / 2),
    width = width,
    height = height,
    style = "minimal",
    border = "rounded",
    title = " Help ",
    title_pos = "center",
    zindex = 100,
  })

  -- Apply highlights
  for _, hl in ipairs(get_highlights()) do
    vim.api.nvim_buf_set_extmark(buf, ns, hl[1], hl[2], {
      end_col = hl[3],
      hl_group = hl[4],
    })
  end

  -- Close on any key
  local function close()
    if vim.api.nvim_win_is_valid(winid) then
      vim.api.nvim_win_close(winid, true)
    end
  end

  vim.keymap.set("n", "q", close, { buffer = buf, nowait = true })
  vim.keymap.set("n", "<Esc>", close, { buffer = buf, nowait = true })
  vim.keymap.set("n", "?", close, { buffer = buf, nowait = true })

  return winid
end

return M
