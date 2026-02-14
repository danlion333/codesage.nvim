--- CodeSage.nvim plugin loader
--- Guards against double-loading

if vim.g.loaded_codesage then
  return
end
vim.g.loaded_codesage = true

-- Plugin will be activated by require("codesage").setup({})
-- This file just ensures the plugin directory is recognized by NeoVim
