local serial = require "serialization"
local csv = require "csv"
local tA = {...}
local f = csv.open(tA[1])
local recipes = {}
local nss = {}
local function xyts(x, y) return ((y - 1) * 3) + x end
local skip = true
local line = 0
for fields in f:lines() do
    if skip then
        skip = false
    else
        local recipe = {}
        local ingredients = {}
        for k, v in fields[3]:gmatch("(%a): ([^\n]+)") do
            ingredients[k] = v
        end
        local output = fields[4]:match("^(%S+)")
        local ns = output:match("^(.-):")
        local qty = tonumber(fields[4]:match("^%S+ x(%d+)"))
        local irow = 1
        for row in fields[2]:gmatch("[^\n]+") do
            local ic = 1
            for c in row:gmatch(".") do
                recipe[xyts(ic, irow)] = ingredients[c]
                ic = ic + 1
            end
            irow = irow + 1
        end
        if fields[4]:match("\n") then
            print(output, qty, serial.serialize(recipe))
        end
        if qty ~= nil and qty > 1 then recipe.qty = qty end
        recipes[output] = recipe
        nss[ns] = nss[ns] or {}
        nss[ns][#nss[ns] + 1] = string.format("%s\t%s\n", output, serial.serialize(recipe))
        line = line + 1
        if line % 20 == 0 then os.sleep() end
    end
end
f:close()

local f, err = csv.open(tA[2])
if err then return print(err) end
skip = true
local line = 0
for fields in f:lines() do
    local output = fields[3]:match("^(%S+)")
    if not skip and output then
        local ns = output:match("^(.-):")
        local qty = tonumber(fields[3]:match("^%S+ x(%d+)"))
        local recipe = {}
        for item in fields[2]:gmatch("[^\n]+") do
            recipe[#recipe + 1] = item
        end
        if qty ~= nil and qty > 1 then recipe.qty = qty end
        recipes[output] = recipe
        nss[ns] = nss[ns] or {}
        nss[ns][#nss[ns] + 1] = string.format("%s\t%s\n", output,
                                              serial.serialize(recipe))
        line = line + 1
        if line % 20 == 0 then os.sleep() end
    else
        skip = false
    end
end
f:close()

local sets = {}
for k, v in pairs(nss) do sets[#sets + 1] = k end
table.sort(sets, function(a, b) return #nss[a] < #nss[b] end)
nss.misc = {}
sets[#sets + 1] = "misc"
for k, v in ipairs(sets) do
    print(v, #nss[v])
    if k ~= "misc" and #nss[v] <= 48 then
        for l, m in ipairs(nss[v]) do nss.misc[#nss.misc + 1] = m end
    else
        local f, err = io.open("/usr/lib/recipes/" .. v .. ".db", "wb")
        if err then return print(err) end
        for l, m in ipairs(nss[v]) do f:write(m) end
        f:close()
    end
end

local computer = require "computer"
local oredict = {}
local f = csv.open(tA[3])
local ctime = computer.uptime()
local lines = 0
for fields in f:lines() do
    --  if not skip then
    local list = {}
    for item in fields[2]:gmatch("[^\n]+") do list[#list + 1] = item end
    oredict[fields[1]] = list
    --  end
    lines = lines + 1
end
print("Took", computer.uptime() - ctime, "to do ", lines, "lines")

local f, err = io.open("/usr/lib/oredict/oredict.db", "wb")
if err then return print(err) end
for k, v in pairs(oredict) do
    f:write(string.format("%s\t%s\n", k, serial.serialize(v)))
end
f:close()
