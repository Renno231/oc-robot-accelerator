local args = {...}
local filesystem = require"filesystem"
local computer = require"computer"
local lz16 = require "liblz16"

local dbPath, compressedPath = args[1], args[2]

if not dbPath then print("directory of .db files not provided") return false end
if not compressedPath then compressedPath = dbPath end

if not filesystem.exists(dbPath) then print("directory of .db files not found") return false end
if not filesystem.exists(compressedPath) then print("directory for .dblz files not found") return false end

if not filesystem.isDirectory(dbPath) then print("provided db file directory is not a directory") return false end
if not filesystem.isDirectory(compressedPath) then print("provided .dblz file directory is not a directory") return false end

local function transformer(fileName)
    local inputPath = filesystem.concat(dbPath, fileName)
    local outputPath = filesystem.concat(compressedPath, fileName.."lz")
    print(string.format("converting %s to %s", inputPath, outputPath))
    local startTime = computer.uptime()
    local fileIn, err = io.open(inputPath, "rb")
    if not fileIn then print("cannot open "..inputPath..": "..tostring(err)) return false end
    local fileOut
    local ok, failure = pcall(function()
        local openErr
        fileOut, openErr = lz16.open(outputPath, "wb")
        if not fileOut then error("cannot open "..outputPath..": "..tostring(openErr or "no error returned")) end
        while true do
            local rb, readErr = fileIn:read(4096)
            if readErr then error("cannot read "..inputPath..": "..tostring(readErr)) end
            if not rb or rb == "" then break end
            local written, writeErr = fileOut:write(rb)
            if not written then error("cannot write "..outputPath..": "..tostring(writeErr or "write failed")) end
        end
    end)
    for _, file in ipairs({fileIn, fileOut or nil}) do
        local closeOK, closed, closeErr = pcall(file.close, file)
        if not closeOK or closed == false or closeErr then
            ok, failure = false, failure or closeErr or closed
        end
    end
    if not ok then print(tostring(failure)) return false end
    print(string.format("processed in %s seconds", computer.uptime() - startTime))
    return true
end

for fileName in filesystem.list(dbPath) do
    if fileName:sub(-3) == ".db" then
        if not transformer(fileName) then return false end
    end
end