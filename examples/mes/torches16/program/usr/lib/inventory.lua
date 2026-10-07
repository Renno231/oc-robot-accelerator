-- inventory.lua
-- Inventory Cache Library for OpenComputers Transposer (Optimized)
-- Version: 1.3.0 - countItemByName now returns slot list.

local identity = require "item_identity"
local InventoryCache = {}
InventoryCache.__index = InventoryCache

-- Helper: Simple shallow copy for stack tables
local function shallowCopy(original)
  if type(original) ~= "table" then return original end
  local copy = {}; for k, v in pairs(original) do copy[k] = v end; return copy
end

-- Helper: Standard representation for an empty slot
local function createEmptySlotRepresentation(slot)
    return {name = "minecraft:air", damage = 0, size = 0, maxSize = 64, label = "Air", hasTag = false, maxDamage = 0, slot = slot}
end

-- Helper: Get base name (remove :damage or :*)
local function getBaseName(itemName)
    if type(itemName) ~= "string" then return "" end
    local name = itemName:match("^(.*):[%*%d]+") -- Match name:damage or name:*
    if name then return name end
    -- Remove trailing wildcard only if not preceded by ':' (less common case)
    name = itemName:match("^(.*)%*$")
    if name and not name:find(":$", -1) then return name end
    return itemName -- Return original if no separator/wildcard found
end


-- Helper: Check if a name uses a wildcard we handle (ends with :*)
local function hasWildcard(name)
    -- Ensure it's a string and ends with ':*' optionally followed by spaces
    return type(name) == "string" and name:match(":%*%s*$") ~= nil
end

function InventoryCache:nextSlotContaining(itemName)
    itemName = identity.canonical(itemName)
    local lookup = self._nameLookup[itemName]
    if lookup then
        return lookup[1]
    end
end

function InventoryCache:slotsContaining(itemName)
    itemName = identity.canonical(itemName)
    local lookup = self._nameLookup[itemName]
    return lookup and shallowCopy(lookup) or {}
end
--- Creates a new InventoryCache object and performs the initial synchronization.
function InventoryCache.new(transposer, side)
  assert(transposer and transposer.getAllStacks, "Valid transposer proxy required.")
  assert(type(side) == "number", "Side must be a number.")
  local self = setmetatable({_transposer = transposer, _side = side, _inventory = {}, _nameLookup = {}, _emptySlots = {}, _inventorySize = 0}, InventoryCache)
  if self:sync() then return self else return nil end
end

--- Performs synchronization. Builds cache using name:damage as key.
function InventoryCache:sync()
  local iteratorSuccess, iterator = pcall(self._transposer.getAllStacks, self._side)
  if not iteratorSuccess or not iterator then self._inventorySize = 0; self._inventory = {}; self._nameLookup = {}; self._emptySlots = {}; return false end

  -- Use pcall for iterator.getAll as it might fail on empty/invalid inventories
  local allStacksSuccess, allStacksResult = pcall(iterator.getAll)

  -- Reset caches before filling
  self._inventory = {}; self._nameLookup = {}; self._emptySlots = {}

  -- Handle potential errors or empty results from getAll
  if not allStacksSuccess or type(allStacksResult) ~= "table" then
     -- Attempt to get size directly if getAll failed but iterator exists (fallback)
     local sizeSuccess, sizeResult = pcall(self._transposer.getInventorySize, self._side)
     if sizeSuccess and type(sizeResult) == "number" then
          self._inventorySize = sizeResult
          -- Populate empty slots based on size
          for i=1, self._inventorySize do table.insert(self._emptySlots, i) end
     else
          self._inventorySize = 0 -- Unable to determine size
     end
     -- Still return false as we couldn't get stack details
     return false
  end

  local allStacks = allStacksResult -- Use the successful result
  self._inventorySize = #allStacks; local airName = "minecraft:air"

  for slot = 1, self._inventorySize do
    local stack = allStacks[slot]
    -- Check for empty/invalid slots more robustly
    if not stack or type(stack) ~= "table" or stack.size == nil or stack.size <= 0 or (stack.name == airName and stack.size <= 0) then
      self._inventory[slot] = nil; table.insert(self._emptySlots, slot)
      -- Add to name lookup for air (optional, usually not needed for crafting logic)
      -- if not self._nameLookup[airName] then self._nameLookup[airName] = {} end
      -- table.insert(self._nameLookup[airName], slot)
    else
      local stackCopy = shallowCopy(stack); stackCopy.slot = slot; self._inventory[slot] = stackCopy
      -- Key includes damage value if not 0
      local nameKey = identity.stackName(stackCopy)
      if not self._nameLookup[nameKey] then self._nameLookup[nameKey] = {} end
      table.insert(self._nameLookup[nameKey], slot)
    end
  end
  -- Clean up potentially empty air entry if it was added
  -- if self._nameLookup[airName] and #self._nameLookup[airName] == 0 then self._nameLookup[airName] = nil end
  return true
end

--- Returns the total number of slots in the cached inventory.
function InventoryCache:getInventorySize()
  return self._inventorySize
end

--- Retrieves the cached item stack information for a specific slot.
function InventoryCache:getItemInSlot(slot)
  if slot and slot >= 1 and slot <= self._inventorySize then
    local cachedData = self._inventory[slot]
    -- Return a copy to prevent external modification of the cache
    if cachedData then return shallowCopy(cachedData) else return createEmptySlotRepresentation(slot) end
  end
  return nil -- Return nil for invalid slots
end

--- Finds all slots containing items matching the specified name (supports name:* wildcard).
-- @param name (string) The item name (e.g., "minecraft:stone", "minecraft:planks:*").
-- @return (table) A list of slot numbers, or an empty table if none found.
function InventoryCache:findItemByName(name)
    name = identity.canonical(name)
    local results = {}
    if type(name) ~= "string" or name == "minecraft:air" then return results end -- Return empty table on invalid/air input

    if hasWildcard(name) then
        -- Wildcard search: Iterate through nameLookup
        local baseName = getBaseName(name) -- Get the part before ':*'
        if baseName and baseName ~= "" then
            local patternPrefix = baseName .. ":" -- For matching name:damage
            local patternLen = #baseName

            for lookupName, slots in pairs(self._nameLookup) do
                 -- Check if lookupName matches the base name exactly OR starts with baseName:
                 -- Ensure lookupName is a string before comparing
                 if type(lookupName) == "string" then
                    if lookupName == baseName or lookupName:sub(1, patternLen + 1) == patternPrefix then
                        -- Add all slots found for this matching lookupName
                        for _, slot in ipairs(slots) do
                            -- Ensure slot is valid before adding
                            if self._inventory[slot] then table.insert(results, slot) end
                        end
                    end
                 end
            end
        end
        -- If baseName is empty (e.g., input was just ":*"), results remains empty
    else
        -- Exact name search (original logic)
        local slots = self._nameLookup[name]
        if slots then
            for _, slot in ipairs(slots) do
                 -- Ensure slot is valid before adding
                 if self._inventory[slot] then table.insert(results, slot) end
            end
        end
    end
    return results -- Always return a table (possibly empty)
end

--- [[ REVISED v1.3.0: Returns count AND list of slots ]]
--- Counts the total number of items matching the specified name (supports name:* wildcard).
-- @param name (string) The item name.
-- @return (number) The total count of the item, or 0 if none found.
-- @return (table) A list of slot numbers where the item was found.
function InventoryCache:countItemByName(name)
    if type(name) ~= "string" or name == "minecraft:air" then return 0, {} end -- Safety check and ignore air
    local slots = self:findItemByName(name) -- Reuse the (now wildcard-aware) find function
    if #slots == 0 then return 0, {} end -- findItemByName now always returns a table
    local total = 0
    for _, slot in ipairs(slots) do
        local stack = self._inventory[slot] -- Access cache directly (faster)
        if stack then -- Should always be true if findItemByName returned it
            total = total + (stack.size or 0)
        end
    end
    return total, slots -- Return total count AND the list of slots
end

--- Returns a list of all empty slots based on the cache.
function InventoryCache:getEmptySlots()
  local slotsCopy = {}; for _, slot in ipairs(self._emptySlots) do table.insert(slotsCopy, slot) end; return slotsCopy
end

--- Returns the slot number of the first empty slot found in the cache.
function InventoryCache:getFirstEmptySlot()
  -- Check if emptySlots has entries before accessing index 1
  return (#self._emptySlots > 0) and self._emptySlots[1] or nil
end


--- Returns a representation of the entire cached inventory. Creates copies.
function InventoryCache:getAllCachedItems()
  local inventoryCopy = {}
  for i = 1, self._inventorySize do
    local cachedData = self._inventory[i]
    if cachedData then inventoryCopy[i] = shallowCopy(cachedData) else inventoryCopy[i] = createEmptySlotRepresentation(i) end
  end
  return inventoryCopy
end

--- Provides an iterator function over the cached inventory slots. Creates copies.
function InventoryCache:iter()
    local i = 0; local n = self._inventorySize
    return function()
        i = i + 1;
        if i <= n then
            local d = self._inventory[i];
            if d then return i, shallowCopy(d) else return i, createEmptySlotRepresentation(i) end
        else
            return nil -- Explicitly return nil when done
        end
    end
end


--- [Helper] Transfers items using the transposer and forces a cache resync.
-- Consider removing if not used by external crafting executor.
function InventoryCache:transferItemAndSync(sourceSide, sinkSide, count, sourceSlot, sinkSlot)
    -- Ensure sourceSide matches the side this cache represents
    if sourceSide ~= self._side then
        print("Error: Transfer source side ("..sourceSide..") does not match cached side ("..self._side..")")
        self:sync() -- Resync just in case external state changed
        return 0
    end

    local moved = 0
    -- Validate sourceSlot before attempting transfer
    if not sourceSlot or sourceSlot < 1 or sourceSlot > self._inventorySize or not self._inventory[sourceSlot] then
        print("Warning: Attempted transfer from invalid or empty source slot: " .. tostring(sourceSlot))
        self:sync(); -- Resync as the intended source state might be wrong
        return 0
    end

    local success, result = pcall(self._transposer.transferItem, sourceSide, sinkSide, count, sourceSlot, sinkSlot)

    -- Resync *regardless* of success, as the inventory state might have changed externally or partially.
    self:sync();

    if success then
        -- Ensure result is a number, default to 0 if nil or other type
        moved = (type(result) == "number" and result or 0)
    else
       -- Log the error if the transfer failed
       print("Error during transposer.transferItem: " .. tostring(result))
       -- moved remains 0
    end

    return moved
end


return InventoryCache