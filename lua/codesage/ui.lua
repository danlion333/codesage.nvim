--- CodeSage UI - Floating windows using nui.nvim
local M = {}

local Popup = require("nui.popup")
local scrollbar_mod = require("codesage.chat.scrollbar")

--- Active scrollbars for result windows (keyed by bufnr)
local scrollbars = {}

--- Detect code block under cursor and return its contents
---@param bufnr integer
---@param winid integer
---@return string|nil
local function get_code_block_at_cursor(bufnr, winid)
  if not winid or not vim.api.nvim_win_is_valid(winid) then
    return nil
  end

  local cursor = vim.api.nvim_win_get_cursor(winid)
  local cursor_line = cursor[1] -- 1-indexed
  local total = vim.api.nvim_buf_line_count(bufnr)
  local all_lines = vim.api.nvim_buf_get_lines(bufnr, 0, -1, false)

  -- Find the opening ``` fence above or at cursor
  local fence_start = nil
  for i = cursor_line, 1, -1 do
    if all_lines[i]:match("^```") then
      local fence_count = 0
      for j = 1, i do
        if all_lines[j]:match("^```") then
          fence_count = fence_count + 1
        end
      end
      if fence_count % 2 == 1 then
        fence_start = i
      end
      break
    end
  end

  if not fence_start then
    return nil
  end

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

  if cursor_line <= fence_start or cursor_line >= fence_end then
    return nil
  end

  local code_lines = {}
  for i = fence_start + 1, fence_end - 1 do
    table.insert(code_lines, all_lines[i])
  end

  return table.concat(code_lines, "\n")
end

--- Create a floating result window
---@param title string Window title
---@return table popup The nui Popup instance
function M.create_result_window(title)
  local config = require("codesage").config.ui

  local popup = Popup({
    enter = true,
    focusable = true,
    border = {
      style = "rounded",
      text = {
        top = " " .. title .. " ",
        top_align = "center",
      },
    },
    position = "50%",
    size = {
      width = math.floor(vim.o.columns * config.width),
      height = math.floor(vim.o.lines * config.height),
    },
    buf_options = {
      modifiable = true,
      filetype = "markdown",
    },
    win_options = {
      winblend = 5,
      wrap = true,
      conceallevel = 2,
      concealcursor = "nc",
    },
  })

  popup:mount()

  -- Create scrollbar for this window
  if popup.winid then
    local sb = scrollbar_mod.new(popup.winid)
    scrollbars[popup.bufnr] = sb

    -- Track scrolling for scrollbar
    local aug = vim.api.nvim_create_augroup("CodeSageResultScrollbar" .. popup.bufnr, { clear = true })
    vim.api.nvim_create_autocmd("WinScrolled", {
      group = aug,
      callback = function(args)
        local scrolled_win = tonumber(args.match)
        if scrolled_win == popup.winid and sb then
          sb:update()
        end
      end,
    })

    -- Clean up on buffer wipe
    vim.api.nvim_create_autocmd("BufWipeout", {
      group = aug,
      buffer = popup.bufnr,
      callback = function()
        if sb then
          sb:destroy()
          scrollbars[popup.bufnr] = nil
        end
        vim.api.nvim_del_augroup_by_id(aug)
      end,
    })
  end

  -- Keymaps: q/Esc to close
  local function close()
    local sb = scrollbars[popup.bufnr]
    if sb then
      sb:destroy()
      scrollbars[popup.bufnr] = nil
    end
    popup:unmount()
  end

  popup:map("n", "q", close, { noremap = true })
  popup:map("n", "<Esc>", close, { noremap = true })

  -- y to yank content to system clipboard
  popup:map("n", "y", function()
    local lines = vim.api.nvim_buf_get_lines(popup.bufnr, 0, -1, false)
    local content = table.concat(lines, "\n")
    vim.fn.setreg("+", content)
    vim.notify("[CodeSage] Content copied to clipboard", vim.log.levels.INFO)
  end, { noremap = true })

  -- gy to copy code block under cursor
  popup:map("n", "gy", function()
    local code = get_code_block_at_cursor(popup.bufnr, popup.winid)
    if code then
      vim.fn.setreg("+", code)
      vim.notify("[CodeSage] Code block copied to clipboard", vim.log.levels.INFO)
    else
      vim.notify("[CodeSage] No code block under cursor", vim.log.levels.INFO)
    end
  end, { noremap = true })

  return popup
end

--- Set the full content of a popup
---@param popup table The nui Popup instance
---@param lines string[] Lines to set
function M.set_content(popup, lines)
  vim.api.nvim_buf_set_option(popup.bufnr, "modifiable", true)
  vim.api.nvim_buf_set_lines(popup.bufnr, 0, -1, false, lines)
  vim.api.nvim_buf_set_option(popup.bufnr, "modifiable", false)
end

--- Append text to a popup (for streaming)
---@param popup table The nui Popup instance
---@param text string Text to append
---@param auto_scroll? boolean Whether to auto-scroll (default true)
function M.append_content(popup, text, auto_scroll)
  if not popup.bufnr or not vim.api.nvim_buf_is_valid(popup.bufnr) then
    return
  end

  if auto_scroll == nil then
    auto_scroll = true
  end

  vim.api.nvim_buf_set_option(popup.bufnr, "modifiable", true)

  -- Split incoming text into lines
  local new_lines = vim.split(text, "\n", { plain = true })

  -- Get current last line to append to
  local line_count = vim.api.nvim_buf_line_count(popup.bufnr)
  local last_line = vim.api.nvim_buf_get_lines(popup.bufnr, line_count - 1, line_count, false)
  local current_last = last_line[1] or ""

  -- Combine with last line
  new_lines[1] = current_last .. new_lines[1]

  -- Replace last line and add any new lines
  vim.api.nvim_buf_set_lines(popup.bufnr, line_count - 1, line_count, false, new_lines)

  vim.api.nvim_buf_set_option(popup.bufnr, "modifiable", false)

  -- Auto-scroll to bottom
  if auto_scroll and popup.winid and vim.api.nvim_win_is_valid(popup.winid) then
    local new_count = vim.api.nvim_buf_line_count(popup.bufnr)
    vim.api.nvim_win_set_cursor(popup.winid, { new_count, 0 })
  end

  -- Update scrollbar
  local sb = scrollbars[popup.bufnr]
  if sb then
    sb:update()
  end
end

--- Show a loading indicator
---@param popup table The nui Popup instance
function M.show_loading(popup)
  M.set_content(popup, { "Thinking..." })
end

return M
