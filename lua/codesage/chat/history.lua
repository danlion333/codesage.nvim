--- Chat history buffer: message rendering, extmarks, auto-scroll, code block detection
local M = {}

local ns = vim.api.nvim_create_namespace("codesage_chat_history")

--- State per history instance
---@class ChatHistory
---@field bufnr integer
---@field winid integer|nil
---@field message_marks integer[] extmark IDs for message headers
---@field auto_scroll boolean whether to auto-scroll on new content
---@field _streaming boolean whether currently streaming a response
local ChatHistory = {}
ChatHistory.__index = ChatHistory

--- Create a new ChatHistory manager
---@param bufnr integer
---@return ChatHistory
function M.new(bufnr)
  local self = setmetatable({}, ChatHistory)
  self.bufnr = bufnr
  self.winid = nil
  self.message_marks = {}
  self.auto_scroll = true
  self._streaming = false
  return self
end

--- Set the window ID (call after layout mount)
---@param winid integer
function ChatHistory:set_winid(winid)
  self.winid = winid
end

--- Check if the window is scrolled to the bottom
---@return boolean
function ChatHistory:is_at_bottom()
  if not self.winid or not vim.api.nvim_win_is_valid(self.winid) then
    return true
  end
  local win_height = vim.api.nvim_win_get_height(self.winid)
  local total_lines = vim.api.nvim_buf_line_count(self.bufnr)
  local top_line = vim.fn.getwininfo(self.winid)[1].topline
  return (top_line + win_height - 1) >= total_lines
end

--- Update auto-scroll state based on current scroll position
--- Called from WinScrolled autocmd
function ChatHistory:on_scroll()
  if self._streaming then
    self.auto_scroll = self:is_at_bottom()
  end
end

--- Re-enable auto-scroll (called when user presses G)
function ChatHistory:enable_auto_scroll()
  self.auto_scroll = true
end

--- Scroll to the bottom of the buffer
function ChatHistory:scroll_to_bottom()
  if not self.winid or not vim.api.nvim_win_is_valid(self.winid) then
    return
  end
  local line_count = vim.api.nvim_buf_line_count(self.bufnr)
  vim.api.nvim_win_set_cursor(self.winid, { line_count, 0 })
end

--- Add a message header extmark at the given line
---@param line integer 0-indexed line number
local function add_message_mark(self, line)
  local mark_id = vim.api.nvim_buf_set_extmark(self.bufnr, ns, line, 0, {})
  table.insert(self.message_marks, mark_id)
end

--- Append lines to the history buffer
---@param lines string[]
function ChatHistory:append_lines(lines)
  vim.api.nvim_buf_set_option(self.bufnr, "modifiable", true)
  local line_count = vim.api.nvim_buf_line_count(self.bufnr)
  local last_line = vim.api.nvim_buf_get_lines(self.bufnr, line_count - 1, line_count, false)

  -- If buffer is empty (single empty line), replace it
  if line_count == 1 and last_line[1] == "" then
    vim.api.nvim_buf_set_lines(self.bufnr, 0, 1, false, lines)
  else
    vim.api.nvim_buf_set_lines(self.bufnr, line_count, line_count, false, lines)
  end

  vim.api.nvim_buf_set_option(self.bufnr, "modifiable", false)

  if self.auto_scroll then
    self:scroll_to_bottom()
  end
end

--- Append a user message with markdown header format
---@param text string The message text
---@param header string The header name (e.g. "You")
---@param show_separator boolean Whether to add --- separator after
function ChatHistory:append_user_message(text, header, show_separator)
  local lines = {}

  -- Add separator before if buffer is not empty
  local line_count = vim.api.nvim_buf_line_count(self.bufnr)
  local last_line = vim.api.nvim_buf_get_lines(self.bufnr, line_count - 1, line_count, false)
  local is_empty = (line_count == 1 and last_line[1] == "")

  if not is_empty then
    table.insert(lines, "")
  end

  table.insert(lines, "## " .. header)
  table.insert(lines, "")

  -- Split message into lines
  local msg_lines = vim.split(text, "\n", { plain = true })
  for _, l in ipairs(msg_lines) do
    table.insert(lines, l)
  end

  if show_separator then
    table.insert(lines, "")
    table.insert(lines, "---")
  end

  -- Calculate where the header will be placed
  local header_line
  if is_empty then
    header_line = (not is_empty) and 1 or 0
  else
    header_line = line_count + 1 -- after the blank line
  end
  -- Adjust: if buffer was empty, first line is at 0
  if is_empty then
    header_line = 0
  end

  self:append_lines(lines)
  add_message_mark(self, header_line)
end

--- Append a complete assistant message (for restoring history, not streaming)
---@param text string The message text
---@param header string The header name (e.g. "CodeSage")
---@param show_separator boolean Whether to add --- separator after
function ChatHistory:append_assistant_message(text, header, show_separator)
  local lines = {}

  -- Add separator before if buffer is not empty
  local line_count = vim.api.nvim_buf_line_count(self.bufnr)
  local last_line = vim.api.nvim_buf_get_lines(self.bufnr, line_count - 1, line_count, false)
  local is_empty = (line_count == 1 and last_line[1] == "")

  if not is_empty then
    table.insert(lines, "")
  end

  table.insert(lines, "## " .. header)
  table.insert(lines, "")

  -- Split message into lines
  local msg_lines = vim.split(text, "\n", { plain = true })
  for _, l in ipairs(msg_lines) do
    table.insert(lines, l)
  end

  if show_separator then
    table.insert(lines, "")
    table.insert(lines, "---")
  end

  -- Calculate where the header will be placed
  local header_line
  if is_empty then
    header_line = 0
  else
    header_line = line_count + 1 -- after the blank line
  end

  self:append_lines(lines)
  add_message_mark(self, header_line)
end

--- Start an assistant response (adds header, sets streaming state)
---@param header string The assistant header name (e.g. "CodeSage")
---@param show_separator boolean Whether the preceding user message had a separator
function ChatHistory:start_assistant_response(header, show_separator)
  self._streaming = true
  self.auto_scroll = true

  local lines = {}

  local line_count = vim.api.nvim_buf_line_count(self.bufnr)

  table.insert(lines, "")
  table.insert(lines, "## " .. header .. " (streaming...)")
  table.insert(lines, "")

  local header_line = line_count + 1 -- the "## header" line (0-indexed, after blank)

  self:append_lines(lines)
  add_message_mark(self, header_line)
end

--- Finish streaming: update the header to remove "(streaming...)" and add separator
---@param header string The assistant header name
---@param show_separator boolean Whether to add --- separator
function ChatHistory:finish_assistant_response(header, show_separator)
  self._streaming = false

  -- Find the last "## header (streaming...)" line and replace it
  vim.api.nvim_buf_set_option(self.bufnr, "modifiable", true)
  local total = vim.api.nvim_buf_line_count(self.bufnr)
  local target = "## " .. header .. " (streaming...)"
  -- Search backwards for the streaming header
  for i = total, 1, -1 do
    local line = vim.api.nvim_buf_get_lines(self.bufnr, i - 1, i, false)[1]
    if line == target then
      vim.api.nvim_buf_set_lines(self.bufnr, i - 1, i, false, { "## " .. header })
      break
    end
  end

  -- Add separator at end
  if show_separator then
    total = vim.api.nvim_buf_line_count(self.bufnr)
    vim.api.nvim_buf_set_lines(self.bufnr, total, total, false, { "", "---" })
  end

  vim.api.nvim_buf_set_option(self.bufnr, "modifiable", false)

  if self.auto_scroll then
    self:scroll_to_bottom()
  end
end

--- Append streaming content to the history buffer
---@param text string The text chunk to append
function ChatHistory:append_streaming_content(text)
  if not self.bufnr or not vim.api.nvim_buf_is_valid(self.bufnr) then
    return
  end

  vim.api.nvim_buf_set_option(self.bufnr, "modifiable", true)

  local new_lines = vim.split(text, "\n", { plain = true })
  local line_count = vim.api.nvim_buf_line_count(self.bufnr)
  local last_line = vim.api.nvim_buf_get_lines(self.bufnr, line_count - 1, line_count, false)
  local current_last = last_line[1] or ""

  new_lines[1] = current_last .. new_lines[1]
  vim.api.nvim_buf_set_lines(self.bufnr, line_count - 1, line_count, false, new_lines)

  vim.api.nvim_buf_set_option(self.bufnr, "modifiable", false)

  if self.auto_scroll then
    self:scroll_to_bottom()
  end
end

--- Append an error message
---@param msg string
function ChatHistory:append_error(msg)
  vim.api.nvim_buf_set_option(self.bufnr, "modifiable", true)
  local line_count = vim.api.nvim_buf_line_count(self.bufnr)
  vim.api.nvim_buf_set_lines(self.bufnr, line_count, line_count, false, { "", "**Error:** " .. msg })
  vim.api.nvim_buf_set_option(self.bufnr, "modifiable", false)

  if self.auto_scroll then
    self:scroll_to_bottom()
  end
end

--- Jump to the next message header from the current cursor position
function ChatHistory:jump_next_message()
  if not self.winid or not vim.api.nvim_win_is_valid(self.winid) then
    return
  end
  local cursor = vim.api.nvim_win_get_cursor(self.winid)
  local current_line = cursor[1] - 1 -- 0-indexed

  -- Find next extmark after current line
  local marks = vim.api.nvim_buf_get_extmarks(self.bufnr, ns, { current_line + 1, 0 }, -1, { limit = 1 })
  if #marks > 0 then
    vim.api.nvim_win_set_cursor(self.winid, { marks[1][2] + 1, 0 })
  end
end

--- Jump to the previous message header from the current cursor position
function ChatHistory:jump_prev_message()
  if not self.winid or not vim.api.nvim_win_is_valid(self.winid) then
    return
  end
  local cursor = vim.api.nvim_win_get_cursor(self.winid)
  local current_line = cursor[1] - 1 -- 0-indexed

  -- Find previous extmark before current line
  local marks = vim.api.nvim_buf_get_extmarks(self.bufnr, ns, { current_line - 1, 0 }, 0, { limit = 1 })
  if #marks > 0 then
    vim.api.nvim_win_set_cursor(self.winid, { marks[1][2] + 1, 0 })
  end
end

--- Detect the code block under the cursor and return its contents
--- Looks for ``` fences around the cursor line
---@return string|nil content The code block content, or nil if not in a code block
function ChatHistory:get_code_block_at_cursor()
  if not self.winid or not vim.api.nvim_win_is_valid(self.winid) then
    return nil
  end

  local cursor = vim.api.nvim_win_get_cursor(self.winid)
  local cursor_line = cursor[1] -- 1-indexed
  local total = vim.api.nvim_buf_line_count(self.bufnr)
  local all_lines = vim.api.nvim_buf_get_lines(self.bufnr, 0, -1, false)

  -- Find the opening ``` fence above or at cursor
  local fence_start = nil
  for i = cursor_line, 1, -1 do
    if all_lines[i]:match("^```") then
      -- Check if this is an opening fence (not a closing one)
      -- Count fences from start to this line
      local fence_count = 0
      for j = 1, i do
        if all_lines[j]:match("^```") then
          fence_count = fence_count + 1
        end
      end
      -- Odd count means this is an opening fence
      if fence_count % 2 == 1 then
        fence_start = i
      end
      break
    end
  end

  if not fence_start then
    return nil
  end

  -- Find the closing ``` fence below cursor
  local fence_end = nil
  for i = fence_start + 1, total do
    if all_lines[i]:match("^```%s*$") then
      fence_end = i
      break
    end
  end

  if not fence_end then
    return nil
  end

  -- Check cursor is between the fences
  if cursor_line <= fence_start or cursor_line >= fence_end then
    return nil
  end

  -- Extract code between fences
  local code_lines = {}
  for i = fence_start + 1, fence_end - 1 do
    table.insert(code_lines, all_lines[i])
  end

  return table.concat(code_lines, "\n")
end

--- Clear all content and extmarks
function ChatHistory:clear()
  vim.api.nvim_buf_set_option(self.bufnr, "modifiable", true)
  vim.api.nvim_buf_set_lines(self.bufnr, 0, -1, false, { "" })
  vim.api.nvim_buf_set_option(self.bufnr, "modifiable", false)
  vim.api.nvim_buf_clear_namespace(self.bufnr, ns, 0, -1)
  self.message_marks = {}
  self.auto_scroll = true
  self._streaming = false
end

return M
