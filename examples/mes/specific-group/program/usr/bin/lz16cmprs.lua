--compresses file A into lzss compressed file B

local lz16 = require "liblz16"
local tA = {...}
local fileIn = io.open(tA[1], "rb")
local fileOut = lz16.open(tA[2] or tA[1].."lz", "wb")
while true do
    local rb = fileIn:read(4096)
    if not rb or rb == "" then break end
    fileOut:write(rb)
end
fileIn:close()
fileOut:close()
