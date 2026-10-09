-- Pure tool rules shared by the planner and robot. No registry/file I/O.
local rules = {}
function rules.family(item)
    if type(item) == "table" then item = item.name end
    if type(item) ~= "string" then return nil end
    return item:match("^([^:]+:[^:]+):[%d%*]+$") or item
end
local function integer(value, minimum)
    return type(value) == "number" and value >= minimum and value < math.huge and value % 1 == 0
end
function rules.validate(profile)
    if type(profile) ~= "table" or not integer(profile.durability, 1) or
        not integer(profile.durabilityPerUse, 0) or profile.durabilityPerUse > profile.durability then
        return false, "Tool durability must be a positive integer; wear per use must be an integer from zero to durability."
    end
    return true
end
function rules.usesLeft(stack, profile)
    local valid, err = rules.validate(profile)
    if not valid then error(err, 2) end
    if type(stack) ~= "table" or not integer(stack.damage or 0, 0) then error("Invalid tool damage.", 2) end
    if profile.durabilityPerUse == 0 then return math.huge end
    return math.floor(math.max(0, profile.durability - (stack.damage or 0)) / profile.durabilityPerUse)
end
return rules
