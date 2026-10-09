local args, options = require"shell".parse(...)
-- local itemToCount = args[1]
local component = require"component"
local transposer = component.transposer
local sides = require"sides"
local inventory = require"inventory"
local shortHand = require"msyn"

local snapshot = inventory.new(transposer, sides.down)

for i, itemToCount in ipairs (args) do
    -- local itemToCount = args[i]

    if not itemToCount  or type(itemToCount) ~= "string" or not string.find(itemToCount, ":", 1, true) then
        print("first argument must be an item ID, got", itemToCount)
    else
        itemToCount = shortHand.convertItemName(itemToCount)
        local count, foundSlots = snapshot:countItemByName(itemToCount)
        print(string.format("%s%s: found %s in %s slots ",itemToCount,foundSlots[1] and string.format(" [%s]", snapshot:getItemInSlot(foundSlots[1]).label) or " ", count, #foundSlots))
    end
end