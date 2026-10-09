local serial = require "serialization"
local lz16 = require "liblz16"
local lzss = require"lzss"
local cbor = require"cbor"
local fs = require"filesystem"

local oredict = {
    cache = {},         -- Forward cache: oreDictName -> compressed list of items
    reverseCache = {},  -- Reverse cache: baseItemName -> oreDictName (stores first found)
    _cachesize = 150,   -- Note: This seems unused in the provided code
    _path = "/usr/lib/oredict/" -- Path to oredict database
}

-- Helper function (from crafting script, needed here now)
local function getBaseItemName(item)
    if type(item) ~= "string" then return "" end
    -- Remove prefix (minecraft:, ore:, modid:)
    local name = item:match("^[a-zA-Z0-9_]+:(.*)") or item
    -- Remove metadata (:*, :meta, {data}) at the end
    name = name:match("^([^:{*]+)") or name
    return name:lower()
end


-- CBOR options (unchanged)
local array_mt = { __name = "array" }
local options = { [array_mt] = cbor.type_encoders.map }

-- Load data and build BOTH caches
local db = fs.concat(oredict._path, "oredict.dblz")
local file, err = lz16.open(db)

if err then
    error("Failed to open oredict database: " .. tostring(err)) -- Use error to halt if DB fails
end

-- print("Loading Ore Dictionary and building caches...")
local lineCount = 0
local reverseEntryCount = 0

for line in file:lines() do
    lineCount = lineCount + 1
    local oreName = line:match("^%S+")
    local listString = line:match("^%S+\t(.+)$")

    if oreName and listString then
        local list, errUnserialize = serial.unserialize(listString)
        if list and #list > 0 then
            -- Store forward cache entry (compressed)
            oredict.cache[oreName] = lzss.compress(cbor.encode(list, options))

            -- Build reverse cache entries
            for _, item in ipairs(list) do
                local baseItem = getBaseItemName(item) -- Normalize name (lowercase, no metadata)
                if baseItem ~= "" then
                    -- Only store the *first* oreDict name found for this base item
                    -- This simplifies lookup later, assuming the first is good enough
                    if not oredict.reverseCache[baseItem] then
                        oredict.reverseCache[baseItem] = oreName
                        reverseEntryCount = reverseEntryCount + 1
                    end
                end
            end
        elseif errUnserialize then
            --  print("Oredict unserialize error on line", lineCount, ":", errUnserialize)
        end
    else
        -- Skip or log lines that don't match the expected format
        -- if line:match("%S") then -- Avoid printing blank lines
        --      print("Oredict format error on line", lineCount, ": ", line)
        -- end
    end
end
file:close()
-- print("Oredict loading complete. Forward entries:", #oredict.cache, "Reverse entries:", reverseEntryCount)


--- Gets the list of specific item names for a given Ore Dictionary name.
-- @param name (string) The Ore Dictionary name (e.g., "ingotIron").
-- @return (table) List of item names, or nil if not found.
function oredict.get(name)
    local compressedData = oredict.cache[name]
    if not compressedData then return nil end -- Changed return, no error message needed here

    -- Use pcall for safety during decode/decompress
    local success, decodedList = pcall(function()
        return cbor.decode(lzss.decompress(compressedData), options)
    end)

    if success then
        return decodedList
    -- else
    --     print("Error decoding/decompressing oredict entry for:", name, decodedList) -- Log error
    --     return nil
    end
end

--- Gets the Ore Dictionary name associated with a specific item name.
-- Uses the pre-computed reverse cache. Ignores metadata/damage values.
-- @param itemName (string) The specific item name (e.g., "minecraft:iron_ingot").
-- @return (string) The Ore Dictionary name (e.g., "ingotIron"), or nil if not found.
function oredict.getByItemName(itemName)
    local baseItem = getBaseItemName(itemName) -- Normalize input
    if baseItem == "" then return nil end -- Invalid input
    -- Direct lookup in the reverse cache
    return oredict.reverseCache[baseItem]
end

return oredict