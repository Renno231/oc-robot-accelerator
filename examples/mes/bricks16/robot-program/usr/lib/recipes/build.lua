-- Shared runtime database compiler and its single persistent CBOR file.
-- Requiring this module performs no database reads, builds, or writes.
local cbor = require "cbor"
local filesystem = require "filesystem"
local builder = {
    directory = "/usr/lib/recipes",
    compiledPath = "/usr/lib/recipes/compiled.cb"
}

-- Check only the outer runtime representation. Individual compressed recipe
-- dictionaries remain compressed until the runtime actually queries an item.
function builder.validate(db)
    if type(db) ~= "table" then return false, "expected compiled recipe table" end
    for namespace, items in pairs(db) do
        if type(namespace) ~= "string" or type(items) ~= "table" then
            return false, "invalid compiled recipe namespace"
        end
        for item, dictionary in pairs(items) do
            if type(item) ~= "string" or type(dictionary) ~= "string" then
                return false, "invalid compressed recipe dictionary"
            end
        end
    end
    return true
end

function builder.load()
    local path = builder.compiledPath
    local file, err = io.open(path, "rb")
    if not file then return false, "cannot open " .. path .. ": " .. tostring(err) end
    local ok, db = pcall(function()
        local data, readError = file:read(math.huge)
        if not data then error(readError or "compiled database is empty") end
        local decoded = cbor.decode(data)
        local valid, validationError = builder.validate(decoded)
        if not valid then error(validationError) end
        return decoded
    end)
    local closeOk, closed, closeError = pcall(file.close, file)
    if not ok then return false, "cannot load " .. path .. ": " .. tostring(db) end
    if not closeOk or closed == false or closeError then
        return false, "cannot close " .. path .. ": " .. tostring(closeError or closed)
    end
    return db
end

function builder.save(db)
    local valid, validationError = builder.validate(db)
    if not valid then return false, validationError end
    local encodedOk, encoded = pcall(cbor.encode, db)
    if not encodedOk then return false, tostring(encoded) end
    local path = builder.compiledPath
    local file, openError = io.open(path, "wb")
    if not file then return false, "cannot open " .. path .. ": " .. tostring(openError) end
    local ok, writeError = pcall(function()
        local written, err = file:write(encoded)
        if not written then error(err or "compiled database write failed") end
    end)
    local closeOk, closed, closeError = pcall(file.close, file)
    if not ok then return false, "cannot save " .. path .. ": " .. tostring(writeError) end
    if not closeOk or closed == false or closeError then
        return false, "cannot close " .. path .. ": " .. tostring(closeError or closed)
    end
    return true
end

function builder.build(directory)
    local recipePath = directory or builder.directory
    local recipedb = {}
    local lz16 = require "liblz16"
    local lzss = require "lzss"
    local serialization = require "serialization"
    local useCbor, useLZSS = true, true
    local array_mt = {__name = "array"}
    local options = {[array_mt] = cbor.type_encoders.map}

    local function readDBLZ(transformer)
        for file in filesystem.list(recipePath) do
            if file:sub(-4) == "dblz" then
                transformer(file)
                for i = 1, 5 do os.sleep() end
            end
        end
    end

    local function makeStatic(modname)
        if not recipedb[modname] then return end
        local i = 0
        print('statifying', modname)
        for item, recipes in pairs(recipedb[modname]) do
            if i % 2500 == 0 then os.sleep(0.05) end
            if type(recipes) == "table" then
                recipedb[modname][item] = lzss.compress(cbor.encode(recipes, options))
            end
            i = i + 1
        end
    end

    local function import(filename, directPath)
        local modname = filename:match("([^/]+)%.dblz$")
        local path = directPath and filename or filesystem.concat(recipePath, filename)
        local file, err = lz16.open(path)
        if not file then error("cannot open recipe database " .. path .. ": " .. tostring(err or "no error returned")) end
        local linesProcessed, totalLines = 0, 0
        local isMisc = modname == "misc"
        local touched = {}
        local lastMiscMod
        local ok, failure = pcall(function()
            for line in file:lines() do
                totalLines = totalLines + 1
                local itemName = line:match("^[^\t]+")
                local recipe = line:match("^[^\t]+\t(.+)$")
                if isMisc then
                    modname, itemName, recipe = string.match(line, "^([^:]+):([^\t]+)\t(.+)$")
                end
                if not modname or itemName == nil or itemName == "" or not recipe then
                    error(string.format("line: %s on %s, itemName: %s, recipe: %s", line or "(nil?)", totalLines, itemName or "(nil?)", recipe or "(nil?)"))
                end
                if isMisc and useCbor and useLZSS then
                    if lastMiscMod and lastMiscMod ~= modname then
                        makeStatic(lastMiscMod)
                        os.sleep()
                    end
                    lastMiscMod = modname
                end
                if itemName and recipe and recipe ~= "{}" then
                    if not isMisc then
                        local prefix = modname .. ":"
                        if itemName:sub(1, #prefix) ~= prefix then
                            error("invalid recipe namespace at " .. path .. ":" .. totalLines)
                        end
                        itemName = itemName:sub(#prefix + 1)
                    end
                    local modifier = itemName:match(".*:(.+)")
                    if modifier then itemName = itemName:sub(1, itemName:len() - modifier:len() - 1) end
                    if itemName == "" then error("empty recipe item at " .. path .. ":" .. totalLines) end
                    local modcache = recipedb[modname] or {}
                    local itemcache = modcache[itemName] or {}
                    if type(itemcache) == "string" then
                        itemcache = cbor.decode(lzss.decompress(itemcache), options)
                    end
                    touched[modname] = true
                    local key = modifier or "base"
                    itemcache[key] = itemcache[key] or {}
                    local deserialized, decodeErr = serialization.unserialize(recipe)
                    if type(deserialized) ~= "table" then
                        error("invalid recipe at " .. path .. ":" .. totalLines .. ": " .. tostring(decodeErr or "expected table"))
                    end
                    local toInsert = useCbor and cbor.encode(deserialized, options) or deserialized
                    table.insert(itemcache[key], toInsert)
                    linesProcessed = linesProcessed + 1
                    modcache[itemName] = itemcache
                    recipedb[modname] = modcache
                end
            end
        end)
        local closeOK, closed, closeErr = pcall(file.close, file)
        if not ok then error("cannot import " .. path .. ": " .. tostring(failure), 0) end
        if not closeOK or closed == false or closeErr then
            error("cannot close " .. path .. ": " .. tostring(closeErr or closed), 0)
        end
        if useCbor and useLZSS then
            for namespace in pairs(touched) do
                makeStatic(namespace)
                os.sleep()
            end
        end
    end
    readDBLZ(import)
    return recipedb
end

return builder
