local lz = require "lzss"
local buffer = require "buffer"
local lz16 = {}

-- Configuration for yielding
local YIELD_INTERVAL = 4096  -- Bytes to process before yielding
local MAX_BLOCK_SIZE = 16384  -- Maximum block size for compression

-- Helper function to yield periodically
local function periodicYield(counter)
    if counter % YIELD_INTERVAL == 0 then
        if os.sleep then
            os.sleep(0)
        else
            coroutine.yield()
        end
    end
end

local function readBuffer(fi)
    local stream = {}
    if fi:read(4) ~= "lz16" then return false, "not an lz16 archive" end
    
    function stream.read()
        local header, headerError = fi:read(2)
        if headerError then error(headerError) end
        if not header or header == "" then return nil end
        if #header ~= 2 then error("Truncated lz16 block length.") end
        local len = string.unpack(">I2", header)
        if len < 1 then return nil end
        
        -- Read compressed data in chunks to avoid large allocations
        local compressedData = ""
        local remaining = len
        local counter = 0
        
        while remaining > 0 do
            local chunkSize = math.min(remaining, 4096)
            local chunk, readError = fi:read(chunkSize)
            if readError then error(readError) end
            if not chunk or #chunk == 0 then error("Truncated lz16 block data.") end
            compressedData = compressedData .. chunk
            remaining = remaining - #chunk
            
            -- Yield periodically while reading
            counter = counter + chunkSize
            periodicYield(counter)
        end
        
        -- Decompress in chunks if the data is large
        local decompressed = ""
        if #compressedData > 0 then
            decompressed = lz.decompress(compressedData)
            -- Yield after decompression since it can be CPU intensive
            periodicYield(#compressedData)
        end
        
        return decompressed
    end
    
    function stream.close() return fi:close() end
    return buffer.new("rb", stream)
end

local function writeBuffer(fo)
    local stream = {}
    local written, headerError = fo:write("lz16")
    if not written then error(headerError or "Unable to write lz16 header.") end
    
    function stream:write(data)
        local totalWritten = 0
        local pos = 1
        local dataLen = #data
        
        -- Process data in chunks to avoid large memory usage and timeouts
        while pos <= dataLen do
            local chunkSize = math.min(MAX_BLOCK_SIZE, dataLen - pos + 1)
            local chunk = data:sub(pos, pos + chunkSize - 1)
            pos = pos + chunkSize
            
            -- Compress the chunk
            local cblock = lz.compress(chunk)
            local written, writeError = fo:write(string.pack(">I2", cblock:len()) .. cblock)
            if not written then error(writeError or "Unable to write lz16 block.") end
            totalWritten = totalWritten + cblock:len() + 2
            
            -- Yield after each chunk
            periodicYield(chunkSize)
        end
        
        return totalWritten
    end
    
    function stream.close() return fo:close() end
    return buffer.new("wb", stream)
end

function lz16.buffer(stream) -- table -- table -- Wrap a stream to read or write LZ16.
    if stream.mode.w then return writeBuffer(stream) end
    return readBuffer(stream)
end

function lz16.open(fname, mode) -- string string -- table -- Open file *fname* to read or write LZ16-compressed data depending on *mode*
    local f, openError = io.open(fname, mode)
    if not f then return false, openError end
    local ok, result, bufferError = pcall(function()
        f.mode.b = true
        return lz16.buffer(f)
    end)
    if not ok or not result then
        pcall(f.close, f)
        return false, ok and bufferError or result
    end
    return result
end

return lz16