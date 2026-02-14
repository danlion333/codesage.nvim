--- CodeSage command palette
local M = {}

--- Open the command palette
---@param range? table {line1, line2} if called from visual mode
function M.open(range)
  local has_selection = range ~= nil

  local actions = {
    {
      label = "Explain",
      requires_selection = false,  -- CHANGED: was true
      action = function(r)
        if r then
          vim.cmd(string.format("%d,%dCodeSageExplain", r[1], r[2]))
        else
          -- No selection: operate on current line
          vim.cmd(".,.CodeSageExplain")
        end
      end,
    },
    {
      label = "Improve",
      requires_selection = false,  -- CHANGED: was true
      action = function(r)
        if r then
          vim.cmd(string.format("%d,%dCodeSageImprove", r[1], r[2]))
        else
          -- No selection: operate on current line
          vim.cmd(".,.CodeSageImprove")
        end
      end,
    },
    {
      label = "Chat",
      requires_selection = false,
      action = function()
        vim.cmd("CodeSageChat")
      end,
    },
    {
      label = "Chat with selection",
      requires_selection = true,
      action = function(r)
        vim.cmd(string.format("%d,%dCodeSageChat", r[1], r[2]))
      end,
    },
    {
      label = "Switch Model",
      requires_selection = false,
      action = function()
        vim.cmd("CodeSageSwitchModel")
      end,
    },
    {
      label = "Status",
      requires_selection = false,
      action = function()
        vim.cmd("CodeSageStatus")
      end,
    },
  }

  -- Filter out selection-required actions when no visual range
  local available = {}
  for _, a in ipairs(actions) do
    if not a.requires_selection or has_selection then
      table.insert(available, a)
    end
  end

  local labels = {}
  for _, a in ipairs(available) do
    table.insert(labels, a.label)
  end

  vim.ui.select(labels, { prompt = "CodeSage Actions:" }, function(choice, idx)
    if not choice or not idx then
      return
    end
    local selected = available[idx]
    if selected.requires_selection and range then
      selected.action(range)
    else
      selected.action()
    end
  end)
end

return M
