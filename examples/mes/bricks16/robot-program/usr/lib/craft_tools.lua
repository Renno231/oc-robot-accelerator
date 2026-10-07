-- User-declared reusable tools. Profiles are loaded lazily; callers receive
-- copies so an edit cannot silently mutate profiles captured by another job.
local cbor = require "cbor"
local filesystem = require "filesystem"
local rules = require "craft_tool_rules"
local tools = {path = "/usr/lib/craft_tools.cb"}
local profiles
tools.family, tools.validate, tools.usesLeft = rules.family, rules.validate, rules.usesLeft

local function copy(profile)
    return {durability = profile.durability, durabilityPerUse = profile.durabilityPerUse}
end

-- Charged per recipe operation, not per output item. Zero wear means reusable
-- without a durability limit. Damage is wear, not a separate recipe variant,
-- only for item families explicitly registered by the user.

local function read()
    if not filesystem.exists(tools.path) then return {} end
    local file, err = io.open(tools.path, "rb")
    if not file then error("Cannot open tool profiles: " .. tostring(err), 0) end
    local ok, db = pcall(function()
        local data, readError = file:read(math.huge)
        if not data then error(readError or "Empty tool profile file.") end
        local decoded = cbor.decode(data)
        if type(decoded) ~= "table" then error("Invalid tool profile table.") end
        local result = {}
        for item, profile in pairs(decoded) do
            if type(item) ~= "string" or not item:match("^[^:]+:[^:]+$") then error("Invalid tool item name.") end
            local valid, problem = tools.validate(profile)
            if not valid then error(problem) end
            result[item] = copy(profile)
        end
        return result
    end)
    local closeOk, closed, closeError = pcall(file.close, file)
    if not ok then error("Cannot load tool profiles: " .. tostring(db), 0) end
    if not closeOk or closed == false or closeError then error("Cannot close tool profiles: " .. tostring(closeError or closed), 0) end
    return db
end

local function ensureLoaded()
    if not profiles then profiles = read() end
end

function tools.reload()
    profiles = read()
    return tools
end

function tools.get(item)
    ensureLoaded()
    local profile = profiles[tools.family(item)]
    return profile and copy(profile) or nil
end

function tools.list()
    ensureLoaded()
    local result = {}
    for item, profile in pairs(profiles) do result[item] = copy(profile) end
    return result
end

local function persist(nextProfiles)
    local ok, encoded = pcall(cbor.encode, nextProfiles)
    if not ok then return nil, tostring(encoded) end
    local file, err = io.open(tools.path, "wb")
    if not file then return nil, "Cannot save tool profiles: " .. tostring(err) end
    local writtenOk, problem = pcall(function()
        local written, writeError = file:write(encoded)
        if not written then error(writeError or "Tool profile write failed.") end
    end)
    local closeOk, closed, closeError = pcall(file.close, file)
    if not writtenOk then return nil, tostring(problem) end
    if not closeOk or closed == false or closeError then return nil, "Cannot close tool profiles: " .. tostring(closeError or closed) end
    profiles = nextProfiles -- A failed edit leaves the active profiles unchanged.
    return true
end

function tools.set(item, durability, durabilityPerUse)
    item = tools.family(item)
    if type(item) ~= "string" or not item:match("^[^:]+:[^:]+$") then return nil, "Expected an item name such as mod:hammer." end
    local profile = {durability = durability, durabilityPerUse = durabilityPerUse}
    local valid, err = tools.validate(profile)
    if not valid then return nil, err end
    ensureLoaded()
    local nextProfiles = tools.list()
    nextProfiles[item] = profile
    return persist(nextProfiles)
end

function tools.remove(item)
    item = tools.family(item)
    if type(item) ~= "string" or not item:match("^[^:]+:[^:]+$") then return nil, "Expected an item name such as mod:hammer." end
    ensureLoaded()
    local nextProfiles = tools.list()
    nextProfiles[item] = nil
    return persist(nextProfiles)
end

return tools
