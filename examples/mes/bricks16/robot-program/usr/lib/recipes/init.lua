-- Lazy compiled recipe database. Processing recipes keep their separate file.
local cbor = require "cbor"
local filesystem = require "filesystem"
local lzss = require "lzss"
local builder = require "recipes.build"
local recipePath = builder.directory
local recipedb, processRecipes = {}, {}
local loaded = false
local recipelib = {
    __recipes = recipedb, __processRecipes = processRecipes,
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

local function saveProcessingRecipes()
    local file, err = io.open(filesystem.concat(recipePath, "process.cb"), "w")
    if file == nil then return false, err~=nil and err or "no error returned?" end
    local ok, failure = pcall(function()
        local written, writeErr = file:write(cbor.encode(recipelib.__processRecipes))
        if not written then error(writeErr or "write failed") end
    end)
    local closeOK, closed, closeErr = pcall(file.close, file)
    if not ok then return false, tostring(failure) end
    if not closeOK or closed == false or closeErr then return false, tostring(closeErr or closed) end
    return true
end

-- so the idea is that the machines are registered separately
-- they have "type" that can be referenced to get a list of machines of that kind that would be compatible with this recipe
-- example: register("minecraft:coal:1", "furnaceBulk", {recipe = {"minecraft:log:*,64"}, qty = 64})
-- that example registers attaches a recipe for 64 charcoal from 64 logs to a machine type of furnaceBulk
local function registerProcessingRecipe(rawItemName, machineType, recipeData)
    checkArg(1, rawItemName, "string")
    checkArg(2, machineType, "string")
    checkArg(3, recipeData, "table")

    local modname = rawItemName:match("[^:]+")
    if not modname then return false, "modname not found in "..tostring(rawItemName) end
    local itemName = rawItemName:sub(modname:len()+2)
    if itemName == nil or itemName == "" then return false, "invalid modname from "..tostring(rawItemName) end
    local modifier = itemName:match(".*:(.+)")
    if modifier then
        itemName = itemName:sub(1,itemName:len()-modifier:len()-1)
    end
    local procRecipe = {qty = recipeData.qty, machineType=machineType, isProcessing=true}
    for i,v in pairs (recipeData.recipe) do
        if type(i) == "number" then
            procRecipe[i] = v
        end
    end
    
    processRecipes[rawItemName] = processRecipes[rawItemName] or {}
    table.insert(processRecipes[rawItemName], procRecipe)
    
    return saveProcessingRecipes()
end

local function retrieve(rawItemName)
    checkArg(1, rawItemName, "string")
    -- Processing overrides must not be hidden by a cached crafting recipe.
    if processRecipes[rawItemName] then return deepcopy(processRecipes[rawItemName]) end
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

recipelib.getAll = retrieve
recipelib.saveProcessingRecipes = saveProcessingRecipes
recipelib.registerProcessingRecipe = registerProcessingRecipe
return recipelib
