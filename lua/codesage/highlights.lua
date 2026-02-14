--- CodeSage highlight group definitions
--- All use `default = true` so users can override.
local M = {}

function M.setup()
  -- Scrollbar
  vim.api.nvim_set_hl(0, "CodeSageScrollbarThumb", { default = true, bg = "#585858" })
  vim.api.nvim_set_hl(0, "CodeSageScrollbarTrack", { default = true, bg = "NONE" })

  -- Status indicators
  vim.api.nvim_set_hl(0, "CodeSageStreaming", { default = true, link = "DiagnosticWarn" })
  vim.api.nvim_set_hl(0, "CodeSageError", { default = true, link = "DiagnosticError" })

  -- Help popup
  vim.api.nvim_set_hl(0, "CodeSageHelpKey", { default = true, link = "Special" })
  vim.api.nvim_set_hl(0, "CodeSageHelpDesc", { default = true, link = "Comment" })

  -- Border
  vim.api.nvim_set_hl(0, "CodeSageBorder", { default = true, link = "FloatBorder" })
end

return M
