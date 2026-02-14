--- CodeSage RPC client - Unix socket communication
--- Uses vim.uv (libuv bindings) for async socket I/O

local M = {}

--- State
local pipe = nil
local job_id = nil
local connected = false
local request_id = 0
local pending = {} -- id -> { callback, stream_callback }
local read_buffer = ""

--- Check if connected to backend
---@return boolean
function M.is_connected()
  return connected and pipe ~= nil
end

--- Start the backend process and connect
---@param plugin_root string Path to plugin root directory
---@param on_ready function Called when connected and ready
function M.start_backend(plugin_root, on_ready)
  local cmd = { "uv", "run", "--project", plugin_root, "codesage" }

  local socket_path = nil

  job_id = vim.fn.jobstart(cmd, {
    cwd = plugin_root,
    on_stdout = function(_, data, _)
      for _, line in ipairs(data) do
        if line ~= "" and not socket_path then
          local ok, parsed = pcall(vim.json.decode, line)
          if ok and parsed and parsed.socket then
            socket_path = parsed.socket
            M.connect(socket_path, on_ready)
          end
        end
      end
    end,
    on_stderr = function(_, data, _)
      for _, line in ipairs(data) do
        if line ~= "" then
          -- Log stderr but don't display to user
          vim.schedule(function()
            -- Only show errors, not info logging
            if line:match("ERROR") then
              vim.notify("[CodeSage] " .. line, vim.log.levels.ERROR)
            end
          end)
        end
      end
    end,
    on_exit = function(_, exit_code, _)
      vim.schedule(function()
        connected = false
        pipe = nil
        job_id = nil
        if exit_code ~= 0 then
          vim.notify(
            "[CodeSage] Backend exited with code " .. exit_code,
            vim.log.levels.WARN
          )
        end
      end)
    end,
  })

  if job_id <= 0 then
    vim.notify("[CodeSage] Failed to start backend", vim.log.levels.ERROR)
  end
end

--- Connect to the backend Unix socket
---@param socket_path string Path to the Unix socket
---@param on_connected function Called when connected
function M.connect(socket_path, on_connected)
  pipe = vim.uv.new_pipe(false)

  pipe:connect(socket_path, function(err)
    if err then
      vim.schedule(function()
        vim.notify("[CodeSage] Connection failed: " .. err, vim.log.levels.ERROR)
      end)
      return
    end

    connected = true
    read_buffer = ""

    -- Start reading responses
    pipe:read_start(function(read_err, data)
      if read_err then
        vim.schedule(function()
          vim.notify("[CodeSage] Read error: " .. read_err, vim.log.levels.ERROR)
          M.shutdown()
        end)
        return
      end

      if data then
        M._on_data(data)
      else
        -- EOF - connection closed
        vim.schedule(function()
          connected = false
        end)
      end
    end)

    vim.schedule(function()
      if on_connected then
        on_connected()
      end
    end)
  end)
end

--- Handle incoming data from the socket
--- Accumulates buffer and parses complete length-prefixed messages
---@param data string Raw bytes received
function M._on_data(data)
  read_buffer = read_buffer .. data

  while true do
    -- Need at least 4 bytes for the length header
    if #read_buffer < 4 then
      return
    end

    -- Parse 4-byte big-endian length prefix
    local b1, b2, b3, b4 = read_buffer:byte(1, 4)
    local length = b1 * 16777216 + b2 * 65536 + b3 * 256 + b4

    -- Check if we have the complete message
    if #read_buffer < 4 + length then
      return
    end

    -- Extract the message
    local message = read_buffer:sub(5, 4 + length)
    read_buffer = read_buffer:sub(4 + length + 1)

    -- Parse and dispatch
    local ok, response = pcall(vim.json.decode, message)
    if ok and response then
      vim.schedule(function()
        M._dispatch_response(response)
      end)
    end
  end
end

--- Route a response to the appropriate pending callback
---@param response table Parsed JSON-RPC response
function M._dispatch_response(response)
  local id = response.id
  if id == nil then
    return
  end

  local entry = pending[id]
  if not entry then
    return
  end

  -- Silently discard responses for cancelled requests
  if entry.cancelled then
    local result = response.result
    if result and result.done then
      pending[id] = nil
    end
    return
  end

  -- Check if this is a streaming chunk
  local result = response.result
  if result and (result.done ~= nil) then
    -- Streaming response
    if entry.stream_callback then
      entry.stream_callback(result)
    end
    if result.done then
      -- Final chunk - clean up
      if entry.callback then
        entry.callback(response)
      end
      pending[id] = nil
    end
  else
    -- Non-streaming response
    if entry.callback then
      entry.callback(response)
    end
    pending[id] = nil
  end
end

--- Cancel an active streaming request
---@param id integer The request ID to cancel
function M.cancel_request(id)
  if not id then
    return
  end

  local entry = pending[id]
  if entry then
    entry.cancelled = true
  end

  -- Send cancel notification to backend
  M.notify("stream/cancel", { id = id })
end

--- Send a JSON-RPC request
---@param method string The RPC method name
---@param params? table Method parameters
---@param callback? function Called with the final response
---@param stream_callback? function Called with each streaming chunk
---@return integer|nil request_id The request ID, or nil on failure
function M.request(method, params, callback, stream_callback)
  if not M.is_connected() then
    vim.schedule(function()
      vim.notify("[CodeSage] Not connected to backend", vim.log.levels.ERROR)
    end)
    return nil
  end

  request_id = request_id + 1
  local id = request_id

  -- Ensure empty params encodes as JSON object {}, not array []
  local p = params or {}
  if not next(p) then
    p = vim.empty_dict()
  end

  local message = vim.json.encode({
    jsonrpc = "2.0",
    method = method,
    params = p,
    id = id,
  })

  -- Length-prefix the message
  local len = #message
  local header = string.char(
    math.floor(len / 16777216) % 256,
    math.floor(len / 65536) % 256,
    math.floor(len / 256) % 256,
    len % 256
  )

  pending[id] = {
    callback = callback,
    stream_callback = stream_callback,
  }

  pipe:write(header .. message, function(err)
    if err then
      vim.schedule(function()
        vim.notify("[CodeSage] Write error: " .. err, vim.log.levels.ERROR)
        pending[id] = nil
      end)
    end
  end)

  return id
end

--- Send a JSON-RPC notification (no id, no response expected)
---@param method string The notification method name
---@param params? table Method parameters
function M.notify(method, params)
  if not M.is_connected() then
    return
  end

  -- Ensure empty params encodes as JSON object {}, not array []
  local p = params or {}
  if not next(p) then
    p = vim.empty_dict()
  end

  local message = vim.json.encode({
    jsonrpc = "2.0",
    method = method,
    params = p,
  })

  -- Length-prefix the message
  local len = #message
  local header = string.char(
    math.floor(len / 16777216) % 256,
    math.floor(len / 65536) % 256,
    math.floor(len / 256) % 256,
    len % 256
  )

  pipe:write(header .. message, function(err)
    if err then
      vim.schedule(function()
        vim.notify("[CodeSage] Notify write error: " .. err, vim.log.levels.ERROR)
      end)
    end
  end)
end

--- Shutdown the backend and clean up
function M.shutdown()
  -- Send shutdown request (fire and forget)
  if M.is_connected() then
    pcall(function()
      M.request("shutdown", {})
    end)
  end

  -- Close pipe
  if pipe then
    pcall(function()
      pipe:read_stop()
      if not pipe:is_closing() then
        pipe:close()
      end
    end)
    pipe = nil
  end

  -- Stop job
  if job_id then
    pcall(vim.fn.jobstop, job_id)
    job_id = nil
  end

  connected = false
  pending = {}
  read_buffer = ""
end

return M
