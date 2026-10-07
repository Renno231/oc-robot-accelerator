-- Inventory identity: an explicit zero metadata modifier is the base item.
-- Recipe lookup may still need the original raw ID to find its DB category.
local identity = {}
function identity.canonical(name)
    if type(name) ~= "string" then return name end
    return (name:gsub("^([^:]+:[^:]+):0$", "%1"))
end
function identity.stackName(stack)
    if stack == "air" then return "air" end
    if type(stack) ~= "table" or not stack.name then return nil end
    return stack.name .. ((stack.damage or 0) ~= 0 and ":" .. tostring(stack.damage) or "")
end
return identity
