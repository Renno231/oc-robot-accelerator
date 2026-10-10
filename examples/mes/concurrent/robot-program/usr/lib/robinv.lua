local component = require("component")
local identity = require "item_identity"
local robot = component.robot
local sides = require("sides")

local crafting = component.crafting
local invController = component.inventory_controller

local robotInventory = {}

if not invController then error("Inventory Controller Upgrade not found!", 0) end
if not crafting then error("Crafting Upgrade not found!", 0) end

local internalInventory = {}
local nameLookup = {}

local selection = robot.select()
local internalBufferStart = 13 -- Assuming slots 1-12 might be grid/output/special
local internalBufferEnd = robot.inventorySize()
local internalGridMap = {
    [1] = 1, [2] = 2, [3] = 3,
    [4] = 5, [5] = 6, [6] = 7,
    [7] = 9, [8] = 10, [9] = 11
}

local getItemNameString = identity.stackName

local function shallowCopy(original)
    if type(original) ~= "table" then return original end
    local copy = {}; for k, v in pairs(original) do copy[k] = v end; return copy
end  

local function tblFind(tbl, val)
    if val == nil then return nil end
    for i,v in ipairs (tbl) do
        if v == val then
            return i
        end
    end
end

robotInventory.toCraftingSlot = function(index)
    return internalGridMap[index]
end

local function populateLookup(itemName, val)
    if not nameLookup[itemName] then nameLookup[itemName] = {} end
    table.insert(nameLookup[itemName], val)
end

local function populateStack(stack, internalSlot)
    local oldName = getItemNameString(internalInventory[internalSlot])
    local oldLookup = oldName and nameLookup[oldName]
    local position = oldLookup and tblFind(oldLookup, internalSlot)
    if position then
        table.remove(oldLookup, position)
        if #oldLookup == 0 and oldName ~= "air" then nameLookup[oldName] = nil end
    end
    internalInventory[internalSlot] = type(stack) == "table" and shallowCopy(stack) or "air"
    local itemName = getItemNameString(internalInventory[internalSlot])
    populateLookup(itemName, internalSlot)
    table.sort(nameLookup[itemName])
end

-- Sync the entire internal inventory state and nameLookup table
robotInventory.sync = function()
    -- print("Syncing internal inventory state...")
    internalInventory = {}
    nameLookup = {}
    nameLookup.air = {} -- Initialize empty list
    -- nameLookup["minecraft:air"] = nameLookup.air
    for i = 1, internalBufferEnd do
        local stackSize = robot.count(i)
        if stackSize > 0 then
            local stack = invController.getStackInInternalSlot(i)
            populateStack(stack, i)
        else
            internalInventory[i] = "air"
            populateLookup("air", i)
        end
    end
end


robotInventory.nextSlotContaining = function(itemName, excludeCraftingGridSlots)
    itemName = identity.canonical(itemName)
    local lookup = nameLookup[itemName]
    if lookup then
        if excludeCraftingGridSlots then
            for i,index in ipairs (lookup) do
                if index >= internalBufferStart then
                    return index
                end
            end
        else
            return lookup[1]
        end
    end
end

local nextEmptyBufferSlot = function()
    for i,index in ipairs (nameLookup.air) do
        if index >= internalBufferStart then
            return index
        end
    end
end

--next slot containing item(itemName, amount) --if none found, return nextEmptyBufferSlot()
robotInventory.nextSlotContainingItemWithRoom = function(itemName, amount, excludeCraftingGridSlots)
    itemName = identity.canonical(itemName)
    local lookupList = nameLookup[itemName]
    if lookupList then
        for i, slot in ipairs (lookupList) do --may need to be tweaked
            if internalInventory[slot].maxSize - internalInventory[slot].size >= amount and (excludeCraftingGridSlots == true and slot >= internalBufferStart or excludeCraftingGridSlots~=true) then
                return slot 
            end
        end
    end
    return nextEmptyBufferSlot()
end

local selectSlot = function(index) --to save on component calls if we already have the correct slot
    if index and index~=selection then
        selection = robot.select(math.min(math.max(index, 1), internalBufferEnd))
    end
    return selection
end

robotInventory.findItemSlots = function(itemName)
    return shallowCopy(nameLookup[identity.canonical(itemName)] or {})
end

robotInventory.isBufferEmpty = function()
    for i = internalBufferStart, internalBufferEnd do
        if robot.count(i) > 0 then
            return false
        end
    end
    return true
end

robotInventory.countSlotsWithItem = function(itemName)
    itemName = identity.canonical(itemName)
    return nameLookup[itemName] and #nameLookup[itemName] or 0
end

robotInventory.getStack = function(slot)
    if not slot then return end
    return shallowCopy(internalInventory[slot])
end

robotInventory.getItemNameInSlot = function(slot)
    if not slot then return end
    return getItemNameString(internalInventory[slot])
end

-- robot.count is tick-free: use it for quantities and avoid detail calls for
-- empty slots. Read actual stack identity after transfers/crafts (including swaps,
-- retained tools, and container items) rather than predicting the result.
robotInventory.forceSyncStack = function(slot)
    if type(slot) ~= "number" or slot < 1 or slot > internalBufferEnd then
        return false, "invalid internal slot"
    end
    if robot.count(slot) == 0 then
        populateStack(nil, slot)
    else
        local stack = invController.getStackInInternalSlot(slot)
        if not stack then error("Unable to read occupied robot slot " .. slot) end
        populateStack(stack, slot)
    end
    return true
end

robotInventory.transferInternal = function(sourceSlot, targetSlot, amount)
    if type(sourceSlot) ~= "number" or type(targetSlot) ~= "number" or
        sourceSlot < 1 or sourceSlot > internalBufferEnd or
        targetSlot < 1 or targetSlot > internalBufferEnd then
        return false, "invalid internal slot"
    end
    if robot.count(sourceSlot) == 0 then return false, "source stack empty" end
    selectSlot(sourceSlot)
    local success, reason = robot.transferTo(targetSlot, amount or 64)
    robotInventory.forceSyncStack(sourceSlot)
    robotInventory.forceSyncStack(targetSlot)
    return success, reason
end

robotInventory.countItemByName = function(itemName)
    itemName = identity.canonical(itemName)
    local count = 0
    for _, slot in ipairs(nameLookup[itemName] or {}) do
        count = count + robot.count(slot)
    end
    return count
end

robotInventory.resyncCraftingGrid = function()
    for i = 1, 9 do robotInventory.forceSyncStack(internalGridMap[i]) end
end

robotInventory.transferToInternal = function(side, fromSlot, toSlot, count)
    side = side or sides.front
    toSlot = toSlot or nextEmptyBufferSlot()
    if not toSlot then return false, "no empty buffer slot" end
    count = math.max(math.min(count or 64, 64), 1)
    selectSlot(toSlot)
    local before = robot.count(toSlot)
    local success = invController.suckFromSlot(side, fromSlot, count)
    robotInventory.forceSyncStack(toSlot)
    local moved = robot.count(toSlot) - before
    return success and moved > 0, moved
end

robotInventory.transferToExternal = function(side, internalSlot, count, externalSlot)
    side = side or sides.front
    internalSlot = internalSlot or selection
    local before = robot.count(internalSlot)
    if before == 0 then return false, "nothing to transfer, selection is empty" end
    count = math.max(math.min(count or 64, 64), 1)
    selectSlot(internalSlot)
    local success
    if type(externalSlot) == "number" then
        success = invController.dropIntoSlot(side, externalSlot, count)
    else
        success = robot.drop(side, count)
    end
    robotInventory.forceSyncStack(internalSlot)
    local moved = before - robot.count(internalSlot)
    return success and moved > 0, moved
end


robotInventory.getInventorySize = function() return internalBufferEnd end

robotInventory.getItemNameString = getItemNameString
robotInventory.nextEmptyBufferSlot = nextEmptyBufferSlot
robotInventory.select = selectSlot
robotInventory.sync()

robotInventory.expose = function()
    return internalInventory, nameLookup
end

return robotInventory