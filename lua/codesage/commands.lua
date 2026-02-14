--- CodeSage commands - User-facing commands and their implementations
local M = {}

--- Get the selected code from a range, including filepath and file content
---@param line1 integer Start line (1-indexed)
---@param line2 integer End line (1-indexed)
---@return table selection { code, language, filename, filepath, file_content }
function M.get_selection(line1, line2)
  local lines = vim.api.nvim_buf_get_lines(0, line1 - 1, line2, false)
  local all_lines = vim.api.nvim_buf_get_lines(0, 0, -1, false)
  return {
    code = table.concat(lines, "\n"),
    language = vim.bo.filetype,
    filename = vim.fn.expand("%:t"),
    filepath = vim.fn.expand("%:p"),
    file_content = table.concat(all_lines, "\n"),
  }
end

--- Execute a streaming command (explain/improve)
---@param method string The stream method (e.g., "stream/explain")
---@param title string Window title
---@param line1 integer Start line
---@param line2 integer End line
local function execute_stream_command(method, title, line1, line2)
  local codesage = require("codesage")
  local rpc = require("codesage.rpc")
  local ui = require("codesage.ui")

  local selection = M.get_selection(line1, line2)

  if selection.code == "" then
    vim.notify("[CodeSage] No code selected", vim.log.levels.WARN)
    return
  end

  local popup = ui.create_result_window(title)
  ui.show_loading(popup)

  local first_chunk = true

  codesage.ensure_backend(function()
    rpc.request(method, {
      code = selection.code,
      language = selection.language,
      filename = selection.filename,
      filepath = selection.filepath,
      file_content = selection.file_content,
    }, function(response)
      -- Final callback (on done or error)
      if response.error and response.error ~= vim.NIL then
        vim.schedule(function()
          local msg = type(response.error) == "table" and response.error.message or tostring(response.error)
          ui.set_content(popup, { "Error: " .. (msg or "Unknown error") })
        end)
      end
    end, function(chunk)
      -- Stream callback
      vim.schedule(function()
        if not popup.bufnr or not vim.api.nvim_buf_is_valid(popup.bufnr) then
          return
        end

        if chunk.error and chunk.error ~= vim.NIL then
          ui.set_content(popup, { "Error: " .. tostring(chunk.error) })
          return
        end

        if first_chunk then
          -- Clear the "Thinking..." placeholder
          ui.set_content(popup, { "" })
          first_chunk = false
        end

        if chunk.content and chunk.content ~= "" then
          ui.append_content(popup, chunk.content)
        end
      end)
    end)
  end)
end

--- Register all user commands
function M.register()
  vim.api.nvim_create_user_command("CodeSageExplain", function(opts)
    execute_stream_command("stream/explain", "CodeSage: Explain", opts.line1, opts.line2)
  end, {
    range = true,
    desc = "Explain the selected code",
  })

  vim.api.nvim_create_user_command("CodeSageImprove", function(opts)
    execute_stream_command("stream/improve", "CodeSage: Improve", opts.line1, opts.line2)
  end, {
    range = true,
    desc = "Suggest improvements for the selected code",
  })

  vim.api.nvim_create_user_command("CodeSageChat", function(opts)
    local chat = require("codesage.chat")
    if opts.range == 2 then
      -- Visual mode: open chat with selection
      local selection = M.get_selection(opts.line1, opts.line2)
      chat.open(selection)
    else
      -- Normal mode: open chat without selection
      chat.open()
    end
  end, {
    range = true,
    desc = "Open CodeSage chat",
  })

  vim.api.nvim_create_user_command("CodeSageChatClear", function()
    local chat = require("codesage.chat")
    chat.clear()
  end, {
    desc = "Clear current CodeSage chat session",
  })

  vim.api.nvim_create_user_command("CodeSageChatNew", function()
    local chat = require("codesage.chat")
    chat.new_session()
  end, {
    desc = "Start a new CodeSage chat session",
  })

  vim.api.nvim_create_user_command("CodeSageChatStop", function()
    local chat = require("codesage.chat")
    chat.stop()
  end, {
    desc = "Stop current CodeSage chat generation",
  })

  vim.api.nvim_create_user_command("CodeSageStatus", function()
    local rpc = require("codesage.rpc")

    if not rpc.is_connected() then
      vim.notify("[CodeSage] Not connected to backend", vim.log.levels.WARN)
      return
    end

    rpc.request("ping", {}, function(response)
      vim.schedule(function()
        if response.error and response.error ~= vim.NIL then
          local msg = type(response.error) == "table" and response.error.message or tostring(response.error)
          vim.notify("[CodeSage] Backend error: " .. (msg or "Unknown error"), vim.log.levels.ERROR)
        else
          local result = response.result
          vim.notify(
            string.format("[CodeSage] Connected - v%s", result.version),
            vim.log.levels.INFO
          )
        end
      end)
    end)
  end, {
    desc = "Show CodeSage backend status",
  })
end

return M
