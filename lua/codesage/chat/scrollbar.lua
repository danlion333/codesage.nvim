--- Scrollbar: 1-column floating window with proportional thumb
local M = {}

local ns = vim.api.nvim_create_namespace("codesage_scrollbar")

---@class Scrollbar
---@field parent_winid integer
---@field bufnr integer|nil
---@field winid integer|nil
---@field _visible boolean
local Scrollbar = {}
Scrollbar.__index = Scrollbar

--- Create a new Scrollbar
---@param parent_winid integer The window the scrollbar is attached to
---@return Scrollbar
function M.new(parent_winid)
  local self = setmetatable({}, Scrollbar)
  self.parent_winid = parent_winid
  self.bufnr = nil
  self.winid = nil
  self._visible = false
  return self
end

--- Create or show the scrollbar float
function Scrollbar:_ensure_window()
  if self.bufnr and vim.api.nvim_buf_is_valid(self.bufnr) and self.winid and vim.api.nvim_win_is_valid(self.winid) then
    return
  end

  if not vim.api.nvim_win_is_valid(self.parent_winid) then
    return
  end

  -- Create buffer
  self.bufnr = vim.api.nvim_create_buf(false, true)
  vim.api.nvim_buf_set_option(self.bufnr, "bufhidden", "wipe")

  local parent_height = vim.api.nvim_win_get_height(self.parent_winid)
  local parent_width = vim.api.nvim_win_get_width(self.parent_winid)

  -- Fill buffer with spaces (one per line)
  local filler = {}
  for _ = 1, parent_height do
    table.insert(filler, " ")
  end
  vim.api.nvim_buf_set_lines(self.bufnr, 0, -1, false, filler)

  -- Create 1-column float at right edge of parent window
  self.winid = vim.api.nvim_open_win(self.bufnr, false, {
    relative = "win",
    win = self.parent_winid,
    row = 0,
    col = parent_width - 1,
    width = 1,
    height = parent_height,
    style = "minimal",
    focusable = false,
    zindex = 60,
  })

  vim.api.nvim_win_set_option(self.winid, "winhighlight", "Normal:CodeSageScrollbarTrack")
  self._visible = true
end

--- Update the scrollbar thumb position
function Scrollbar:update()
  if not vim.api.nvim_win_is_valid(self.parent_winid) then
    self:destroy()
    return
  end

  local parent_buf = vim.api.nvim_win_get_buf(self.parent_winid)
  local total_lines = vim.api.nvim_buf_line_count(parent_buf)
  local win_height = vim.api.nvim_win_get_height(self.parent_winid)

  -- Hide scrollbar if content fits in window
  if total_lines <= win_height then
    self:hide()
    return
  end

  self:_ensure_window()

  if not self.winid or not vim.api.nvim_win_is_valid(self.winid) then
    return
  end

  -- Resize the float to match parent
  local parent_width = vim.api.nvim_win_get_width(self.parent_winid)
  vim.api.nvim_win_set_config(self.winid, {
    relative = "win",
    win = self.parent_winid,
    row = 0,
    col = parent_width - 1,
    width = 1,
    height = win_height,
  })

  -- Ensure buffer has enough lines
  local buf_lines = vim.api.nvim_buf_line_count(self.bufnr)
  if buf_lines < win_height then
    local extra = {}
    for _ = 1, win_height - buf_lines do
      table.insert(extra, " ")
    end
    vim.api.nvim_buf_set_lines(self.bufnr, buf_lines, buf_lines, false, extra)
  elseif buf_lines > win_height then
    vim.api.nvim_buf_set_lines(self.bufnr, win_height, buf_lines, false, {})
  end

  -- Calculate thumb size and position
  local thumb_height = math.max(1, math.floor(win_height * win_height / total_lines + 0.5))
  local top_line = vim.fn.getwininfo(self.parent_winid)[1].topline
  local scroll_fraction = (top_line - 1) / math.max(1, total_lines - win_height)
  local thumb_top = math.floor(scroll_fraction * (win_height - thumb_height) + 0.5)

  -- Clear existing highlights and apply thumb
  vim.api.nvim_buf_clear_namespace(self.bufnr, ns, 0, -1)
  for i = thumb_top, math.min(thumb_top + thumb_height - 1, win_height - 1) do
    vim.api.nvim_buf_set_extmark(self.bufnr, ns, i, 0, {
      end_col = 1,
      hl_group = "CodeSageScrollbarThumb",
    })
  end
end

--- Hide the scrollbar without destroying it
function Scrollbar:hide()
  if self.winid and vim.api.nvim_win_is_valid(self.winid) then
    vim.api.nvim_win_hide(self.winid)
    self.winid = nil
  end
  self._visible = false
end

--- Destroy the scrollbar completely
function Scrollbar:destroy()
  if self.winid and vim.api.nvim_win_is_valid(self.winid) then
    vim.api.nvim_win_close(self.winid, true)
    self.winid = nil
  end
  if self.bufnr and vim.api.nvim_buf_is_valid(self.bufnr) then
    vim.api.nvim_buf_delete(self.bufnr, { force = true })
    self.bufnr = nil
  end
  self._visible = false
end

--- Whether the scrollbar is currently visible
---@return boolean
function Scrollbar:is_visible()
  return self._visible and self.winid ~= nil and vim.api.nvim_win_is_valid(self.winid)
end

return M
