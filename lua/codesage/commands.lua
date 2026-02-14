--- CodeSage commands - User-facing commands and their implementations
local M = {}

--- Get the selected code from a range, including filepath and file content
---@param line1 integer Start line (1-indexed)
---@param line2 integer End line (1-indexed)
---@return table selection { code, language, filename, filepath, file_content }
function M.get_selection(line1, line2, include_file_content)
  local lines = vim.api.nvim_buf_get_lines(0, line1 - 1, line2, false)
  local file_content = nil
  if include_file_content then
    local all_lines = vim.api.nvim_buf_get_lines(0, 0, -1, false)
    file_content = table.concat(all_lines, "\n")
  end
  return {
    code = table.concat(lines, "\n"),
    language = vim.bo.filetype,
    filename = vim.fn.expand("%:t"),
    filepath = vim.fn.expand("%:p"),
    file_content = file_content,
  }
end
--- Execute a streaming command (explain/improve)
---@param method string The stream method (e.g., "stream/explain")
---@param title string Window title
---@param line1 integer Start line
---@param line2 integer End line
local function execute_stream_command(method, title, line1, line2, include_file_content)
  local codesage = require("codesage")
  local rpc = require("codesage.rpc")
  local ui = require("codesage.ui")

  
  local selection = M.get_selection(line1, line2, include_file_content)

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
  local include_file_content = (opts.range ~= 2)
  execute_stream_command("stream/explain", "CodeSage: Explain", opts.line1, opts.line2, include_file_content)
end, { 
  range = true,
  desc = "Explain the selected code",
  })

  vim.api.nvim_create_user_command("CodeSageImprove", function(opts)
  local include_file_content = (opts.range ~= 2)
  execute_stream_command("stream/improve", "CodeSage: Improve", opts.line1, opts.line2, include_file_content)
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
          local model = result.model or "unknown"
          local tokens = 0
          if result.usage then
            tokens = result.usage.total_tokens or 0
          end
          vim.notify(
            string.format("[CodeSage] Connected - v%s | Model: %s | Tokens: %d", result.version, model, tokens),
            vim.log.levels.INFO
          )
        end
      end)
    end)
  end, {
    desc = "Show CodeSage backend status",
  })

  vim.api.nvim_create_user_command("CodeSageSwitchModel", function()
    local codesage = require("codesage")
    local rpc = require("codesage.rpc")

    codesage.ensure_backend(function()
      rpc.request("config/get_model", {}, function(response)
        vim.schedule(function()
          if response.error and response.error ~= vim.NIL then
            vim.notify("[CodeSage] Failed to get current model", vim.log.levels.ERROR)
            return
          end

          local current_model = response.result.model
          local models = codesage.config.models or {}

          -- Build display list marking current model
          local items = {}
          for _, m in ipairs(models) do
            if m == current_model then
              table.insert(items, m .. " (current)")
            else
              table.insert(items, m)
            end
          end

          vim.ui.select(items, { prompt = "Switch Model:" }, function(choice)
            if not choice then
              return
            end
            -- Strip " (current)" suffix if present
            local model = choice:gsub(" %(current%)$", "")
            rpc.request("config/set_model", { model = model }, function(set_response)
              vim.schedule(function()
                if set_response.error and set_response.error ~= vim.NIL then
                  vim.notify("[CodeSage] Failed to switch model", vim.log.levels.ERROR)
                else
                  vim.notify("[CodeSage] Model switched to: " .. model, vim.log.levels.INFO)
                end
              end)
            end)
          end)
        end)
      end)
    end)
  end, {
    desc = "Switch CodeSage LLM model",
  })

  vim.api.nvim_create_user_command("CodeSagePalette", function(opts)
    local palette = require("codesage.palette")
    if opts.range == 2 then
      palette.open({ opts.line1, opts.line2 })
    else
      palette.open()
    end
  end, {
    range = true,
    desc = "Open CodeSage command palette",
  })
end

return M
