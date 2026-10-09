--mod synonym or shorthands

local shortHand = {}

shortHand.__modNameShorthand = {
    ['ie'] = 'immersiveengineering',
    ['mc'] = 'minecraft',
    ['oc'] = 'opencomputers',
    ['nc'] = 'nuclearcraft',
    ['sd'] = 'storagedrawers',
    ['edec'] = 'engineersdecor',
    ['eio'] = 'enderio',
    ['zetta'] = 'zettaindustries',
    ['osec'] = 'opensecurity',
    ['ctron'] = 'computronics',
    ['iwire'] = 'industrialwires',
    ['ipetro'] = 'immersivepetroleum',
    ['itech'] = 'immersivetech',
    ['tcon'] = 'tconstruct',
}

shortHand.convertItemName = function(itemName)
    local colonPos = string.find(itemName, ":", 1, true)
    if colonPos and colonPos > 1 then
        local shorthandPart = string.sub(itemName, 1, colonPos - 1)
        local fullName = shortHand.__modNameShorthand[shorthandPart]

        -- If a full name was found in the table...
        if fullName then
            -- Extract the part after the colon
            local itemPart = string.sub(itemName, colonPos + 1)
            -- Construct and return the new string
            return (fullName .. ":" .. itemPart)
        end
    end
    return itemName
end


return shortHand