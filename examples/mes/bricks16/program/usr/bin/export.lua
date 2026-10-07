local args, options = require"shell".parse(...)
local itemToExport, amountToExport = args[1], math.max(tonumber(args[2]) or 1, 1)
local component = require"component"
local transposer = component.transposer
local sides = require"sides"
local inventory = require"inventory"
local shortHand = require"msyn"

local snapshot = inventory.new(transposer, sides.down)

if not itemToExport  or type(itemToExport) ~= "string" or not string.find(itemToExport, ":", 1, true) then
    return "first argument must be an item ID"
end

itemToExport = shortHand.convertItemName(itemToExport)

repeat
    local slotToExtractFrom = snapshot:nextSlotContaining(itemToExport)
    if not slotToExtractFrom then print("Unable to extract item", itemToExport) break end
    local moved = transposer.transferItem(sides.down, sides.south, amountToExport, slotToExtractFrom)
    if moved == 0 then print("Failed to move",itemToExport,"to output") break end
    print(string.format("Transferred %s of %s to output", moved, itemToExport))
    amountToExport = amountToExport - moved
    snapshot:sync()
until amountToExport == 0

if amountToExport > 0 then
    return itemToExport, amountToExport
end