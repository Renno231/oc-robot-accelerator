-- Lazy compiled recipe database. Processing recipes keep their separate file.
local cbor = require "cbor"
local filesystem = require "filesystem"
local lzss = require "lzss"
local builder = require "recipes.build"
local recipePath = builder.directory
local recipedb, processRecipes, userRecipes = {}, {}, {}
local loaded = false
local recipelib = {
    __recipes = recipedb, __processRecipes = processRecipes, __userRecipes = userRecipes,
    _cacheSize = 10, _recipeCache = {}
}
local array_mt = {__name = "array"}
local options = {[array_mt] = cbor.type_encoders.map}

local function deepcopy(orig)
    local orig_type = type(orig)
    local copy
    if orig_type == 'table' then
        copy = {}
        for orig_key, orig_value in next, orig, nil do
            copy[deepcopy(orig_key)] = deepcopy(orig_value)
        end
        setmetatable(copy, deepcopy(getmetatable(orig)))
    else -- number, string, boolean, etc
        copy = orig
    end
    return copy
end

-- Install the actual built table: no copy, file read, encoding, or compression.
function recipelib.install(db)
    local valid, err = builder.validate(db)
    if not valid then error(err, 2) end
    recipedb = db
    recipelib.__recipes = db
    recipelib._recipeCache = {}
    loaded = true
    return recipelib
end

local function readOrBuild()
    if filesystem.exists(builder.compiledPath) then
        local db, err = builder.load()
        if not db then error(err .. "; run build_db to rebuild it.", 0) end
        return db
    end
    local db = builder.build()
    local saved, err = builder.save(db)
    -- A missing cache on read-only/full storage should not stop otherwise valid
    -- source recipes from being used. Keep the built table for this runtime.
    if not saved then print("Warning: compiled recipes were not saved: " .. tostring(err)) end
    return db
end

local function ensureLoaded()
    if not loaded then recipelib.install(readOrBuild()) end
end

function recipelib.reload()
    return recipelib.install(readOrBuild())
end

-- Process recipes remain independently persisted and retain eager initialization
-- for callers using __processRecipes directly. No crafting DB is read here.
if filesystem.exists(filesystem.concat(recipePath, "process.cb")) then
    local path = filesystem.concat(recipePath, "process.cb")
    local file, err = io.open(path, "rb")
    if not file then error("cannot open "..path..": "..tostring(err)) end
    local ok, decoded = pcall(function()
        local data, readErr = file:read(math.huge)
        if not data then error(readErr or "read failed") end
        local result = cbor.decode(data)
        if type(result) ~= "table" then error("expected processing recipe table") end
        return result
    end)
    local closeOK, closed, closeErr = pcall(file.close, file)
    if not ok then error("cannot decode "..path..": "..tostring(decoded), 0) end
    if not closeOK or closed == false or closeErr then error("cannot close "..path..": "..tostring(closeErr or closed)) end
    processRecipes = decoded
    recipelib.__processRecipes = processRecipes
end

-- The temporary file is on the same filesystem as the destination. Never
-- truncate/remove the durable file: a failed write/close/rename leaves it intact.
local saveSequence = 0
local function atomicSave(path, data)
    local encodedOK, encoded = pcall(cbor.encode, data)
    if not encodedOK then return false, tostring(encoded) end
    saveSequence = saveSequence + 1
    local temporary = path..".tmp."..saveSequence
    local function cleanup()
        if filesystem.remove then pcall(filesystem.remove, temporary) end
    end
    local openOK, file, err = pcall(io.open, temporary, "wb")
    if not openOK or not file then
        cleanup()
        return false, tostring(err or file or "cannot open temporary recipe file")
    end
    local writtenOK, written, writeErr = pcall(file.write, file, encoded)
    local flushOK, flushed, flushErr = true, true, nil
    -- OpenOS close discards flush's result; a buffered write's success alone is
    -- not sufficient evidence that the temporary file reached the filesystem.
    if writtenOK and written and file.flush then
        flushOK, flushed, flushErr = pcall(file.flush, file)
    end
    local closeOK, closed, closeErr = pcall(file.close, file)
    if not writtenOK or not written then
        cleanup()
        return false, tostring(writeErr or written or "recipe write failed")
    end
    if not flushOK or not flushed or flushErr then
        cleanup()
        return false, tostring(flushErr or flushed or "recipe flush failed")
    end
    -- OpenOS buffered handles may return nil without an error on successful close.
    if not closeOK or closed == false or closeErr then
        cleanup()
        return false, tostring(closeErr or closed or "recipe close failed")
    end
    if not filesystem.rename then cleanup();return false, "filesystem.rename required for atomic recipe saves" end
    local renameOK, renamed, renameErr = pcall(filesystem.rename, temporary, path)
    if not renameOK or not renamed then
        cleanup()
        return false, tostring(renameErr or renamed or "recipe rename failed")
    end
    return true
end

local function saveProcessingRecipes()
    return atomicSave(filesystem.concat(recipePath, "process.cb"), processRecipes)
end

-- Small editable crafting overlay, independent of the compressed database.
local userPath = filesystem.concat(recipePath, "user.cb")
if filesystem.exists(userPath) then
    local file, err = io.open(userPath, "rb")
    if not file then error("cannot open "..userPath..": "..tostring(err)) end
    local ok, decoded = pcall(function() return cbor.decode(assert(file:read(math.huge))) end)
    local closeOK, closed, closeErr = pcall(file.close, file)
    if not ok or type(decoded) ~= "table" then error("cannot decode "..userPath..": "..tostring(decoded)) end
    if not closeOK or closed == false or closeErr then error("cannot close "..userPath) end
    userRecipes = decoded
    recipelib.__userRecipes = decoded
end

function recipelib.saveUserRecipes()
    return atomicSave(userPath, userRecipes)
end

-- so the idea is that the machines are registered separately
-- they have "type" that can be referenced to get a list of machines of that kind that would be compatible with this recipe
-- example: register("minecraft:coal:1", "furnaceBulk", {recipe = {"minecraft:log:*,64"}, qty = 64})
-- that example registers attaches a recipe for 64 charcoal from 64 logs to a machine type of furnaceBulk
local function registerProcessingRecipe(rawItemName, machineType, recipeData)
    checkArg(1, rawItemName, "string")
    checkArg(2, machineType, "string")
    checkArg(3, recipeData, "table")

    local byproducts
    if recipeData.byproducts ~= nil then
        if type(recipeData.byproducts) ~= "table" then return false, "invalid byproducts" end
        byproducts = {}
        local n = 0
        for k, output in pairs(recipeData.byproducts) do
            if type(k) ~= "number" or k < 1 or k % 1 ~= 0 or k > #recipeData.byproducts or
                type(output) ~= "table" or type(output.item) ~= "string" or
                not (output.item:match("^[%w_.%-]+:[%w_./%-]+$") or
                    output.item:match("^[%w_.%-]+:[%w_./%-]+:%d+$")) or
                type(output.qty) ~= "number" or output.qty <= 0 or output.qty >= math.huge or
                output.qty % 1 ~= 0 then return false, "invalid byproducts" end
            local item = require("item_identity").canonical(output.item)
            if item == "minecraft:air" then return false, "invalid byproducts" end
            byproducts[k] = {item=item, qty=output.qty}
            n = n + 1
        end
        if n ~= #recipeData.byproducts then return false, "invalid byproducts" end
    end

    local modname = rawItemName:match("[^:]+")
    if not modname then return false, "modname not found in "..tostring(rawItemName) end
    local itemName = rawItemName:sub(modname:len()+2)
    if itemName == nil or itemName == "" then return false, "invalid modname from "..tostring(rawItemName) end
    local modifier = itemName:match(".*:(.+)")
    if modifier then
        itemName = itemName:sub(1,itemName:len()-modifier:len()-1)
    end
    local procRecipe = {qty = recipeData.qty, machineType=machineType, isProcessing=true,
        byproducts=byproducts}
    for i,v in pairs (recipeData.recipe) do
        if type(i) == "number" then
            procRecipe[i] = v
        end
    end
    
    local previous = processRecipes[rawItemName]
    local staged = {}
    for i, recipe in ipairs(previous or {}) do staged[i] = recipe end
    staged[#staged+1] = procRecipe
    processRecipes[rawItemName] = staged
    local ok, err = recipelib.saveProcessingRecipes()
    if not ok then processRecipes[rawItemName] = previous end
    return ok, err
end

local function retrieveDB(rawItemName)
    checkArg(1, rawItemName, "string")
    ensureLoaded()
    for _, cached in ipairs(recipelib._recipeCache) do
        if cached[1] == rawItemName then return cached[2] end
    end
    local modname = rawItemName:match("[^:]+")
    if not modname then return false, "modname not found in " .. rawItemName end
    local itemName = rawItemName:sub(#modname + 2)
    if itemName == "" then return false, "invalid item name in " .. rawItemName end
    local modifier = itemName:match(".*:(.+)")
    if modifier then itemName = itemName:sub(1, #itemName - #modifier - 1) end
    local modCache = recipedb[modname]
    if not modCache then return false, "mod not in recipe dictionary cache" end
    local dictionary = modCache[itemName]
    if not dictionary then return false, "recipe dictionary for item not found" end
    local decodedOk, recipeList = pcall(function()
        local categories = cbor.decode(lzss.decompress(dictionary), options)
        if type(categories) ~= "table" then error("expected recipe category table") end
        for category, list in pairs(categories) do
            if type(category) ~= "string" or type(list) ~= "table" then
                error("invalid recipe category/list")
            end
        end
        local list = categories[modifier or "base"]
        if not list then return nil end -- Missing metadata is a normal lookup miss.
        local count = 0
        for i, encoded in pairs(list) do
            if type(i) ~= "number" or i < 1 or i % 1 ~= 0 or i > #list or type(encoded) ~= "string" then
                error("invalid encoded recipe list")
            end
            local recipe = cbor.decode(encoded, options)
            if type(recipe) ~= "table" then error("expected decoded recipe table") end
            list[i] = recipe
            count = count + 1
        end
        if count ~= #list then error("sparse encoded recipe list") end
        return list
    end)
    if not decodedOk then
        error("cannot decode " .. builder.compiledPath .. " recipe " .. rawItemName .. ": " ..
            tostring(recipeList) .. "; run build_db to rebuild it.", 0)
    end
    if #recipelib._recipeCache >= recipelib._cacheSize then table.remove(recipelib._recipeCache, 1) end
    table.insert(recipelib._recipeCache, {rawItemName, recipeList})
    return recipeList
end

recipelib.getDatabase = retrieveDB
function recipelib.getAll(rawItemName)
    checkArg(1, rawItemName, "string")
    -- Preserve processing overrides; user crafting entries precede DB entries.
    local canonical = require("item_identity").canonical(rawItemName)
    local processing = processRecipes[rawItemName] or processRecipes[canonical]
    if processing then return deepcopy(processing) end
    local users = userRecipes[rawItemName] or userRecipes[canonical]
    if not users then return retrieveDB(rawItemName) end
    local result = deepcopy(users)
    for _, recipe in ipairs(retrieveDB(rawItemName) or {}) do result[#result+1] = deepcopy(recipe) end
    return result
end

-- Iterate IDs without expanding the whole compressed database. Only the current
-- item's metadata dictionary is decoded, never its individual recipes.
function recipelib.databaseIds()
    ensureLoaded()
    return coroutine.wrap(function()
        for namespace, items in pairs(recipedb) do
            for item, dictionary in pairs(items) do
                local categories = cbor.decode(lzss.decompress(dictionary), options)
                for modifier in pairs(categories) do
                    coroutine.yield(namespace..":"..item..(modifier == "base" and "" or ":"..modifier))
                end
            end
        end
    end)
end
recipelib.saveProcessingRecipes = saveProcessingRecipes
recipelib.registerProcessingRecipe = registerProcessingRecipe
-- Management does not load hardware dependencies or the crafting DB until used.
for _, name in ipairs({"readSlots", "transposerInventories", "slotsFromListing",
    "recipeFromSlots", "save", "list", "remove", "oreFamilies", "search"}) do
    recipelib[name] = function(...) return require("recipes.management")[name](...) end
end
return recipelib
