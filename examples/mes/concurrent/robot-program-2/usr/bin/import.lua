--import
local component = require"component"
local transposer = component.transposer
local sides = require"sides"

local amountTransferred, totalItems = 0,0
repeat
    amountTransferred = transposer.transferItem(sides.south, sides.down, 64)
    totalItems = totalItems + amountTransferred
until amountTransferred == 0
print("imported",totalItems,"items")