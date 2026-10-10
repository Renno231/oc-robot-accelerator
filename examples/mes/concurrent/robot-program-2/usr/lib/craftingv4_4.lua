-- Interactive choice capture followed by pure, constrained demand accounting.
local recipesdb = require "recipes"
local oredict = require "oredict"
local InventoryCache = require "inventory"
local identity = require "item_identity"
local rules = require "craft_tool_rules"
local blueprint = require "craft_blueprint"
local craftLib = {}

local function resolvedItems(name)
    local out={wildcards={}}
    if name:find(" | ",1,true) then
        for part in name:gmatch("[^|]+") do
            local trimmed=part:match("^%s*(.-)%s*$")
            if #trimmed>0 then out[#out+1]=trimmed end
        end
    elseif name:sub(1,4)=="ore:" then
        local oreName=name:sub(5)
        for _,candidate in ipairs(oredict.get(oreName) or {}) do
            if candidate:match(":%*%s*$") then out.wildcards[#out.wildcards+1]=candidate
            else out[#out+1]=candidate end
        end
        local vanilla={plankWood="minecraft:planks",logWood="minecraft:log",
            stone="minecraft:stone",cobblestone="minecraft:cobblestone"}
        if vanilla[oreName] then
            local found=false
            for _,candidate in ipairs(out) do if identity.canonical(candidate)==vanilla[oreName] then found=true end end
            if not found then out[#out+1]=vanilla[oreName] end
        end
    elseif name:match(":%*%s*$") then out.wildcards[1]=name
    else out[1]=name end
    return out
end

local function defaultIngredient(candidates,inventory,original)
    local possible,seen={},{}
    local function add(name) if not seen[name] then seen[name]=true; possible[#possible+1]=name end end
    for _,name in ipairs(candidates) do add(name) end
    for _,wildcard in ipairs(candidates.wildcards) do
        local _,slots=inventory:countItemByName(wildcard)
        for _,slot in ipairs(slots) do add(identity.stackName(inventory:getItemInSlot(slot))) end
        if #slots==0 then add(wildcard:gsub(":%*%s*$","")) end
    end
    table.sort(possible,function(a,b)
        local ca,cb=inventory:countItemByName(a),inventory:countItemByName(b)
        return ca==cb and a<b or ca>cb
    end)
    return possible[1] or original
end

local function capture(item,quantity,inventory,profiles,ignoreInventory,override)
    local target=identity.canonical(item)
    local b={roots={{node=target,quantity=quantity}},nodes={},tools={}}
    local stack,rawNames={{item=target,raw=item}},{[target]=item}
    while #stack>0 do
        local frame=table.remove(stack); local name=frame.item
        if not b.nodes[name] then
            local all,problem
            if name==target and override~=nil then all={override}
            else all,problem=recipesdb.getAll(rawNames[name] or name) end
            if not all then
                local alternate=(rawNames[name] or name)~=name and name or name..":0"
                all,problem=recipesdb.getAll(alternate)
            end
            local chosen
            local explicit=name==target and override~=nil
            if explicit then chosen=override
            elseif all and #all>0 and not problem then
                chosen=coroutine.yield("select_recipe",name,all,inventory)
                if chosen==nil then chosen=all[1] end
                if chosen~=false and type(chosen)~="table" then error("Invalid recipe selected for "..name) end
            end
            local node={item=name,useStock=not ignoreInventory}
            b.nodes[name]=node -- Mark before descent; validation catches cycles.
            if chosen then
                local force
                if not explicit then force=coroutine.yield("skip_inventory_check",name,chosen) end
                node.useStock=not ignoreInventory and not force
                local qty=chosen.qty or 1
                assert(type(qty)=="number" and qty>0 and qty<math.huge and qty%1==0,
                    "Invalid recipe output quantity for "..name)
                node.recipeOutput=qty; node.recipe={}; node.deps={};node.tool_slots={};node.input_quantities={};node.ingredient_sources={}
                node.isProcessing=chosen.isProcessing; node.machineType=chosen.machineType
                local slots={}
                for slot,value in pairs(chosen) do
                    if type(slot)=="number" then
                        assert(slot>=1 and slot%1==0 and (chosen.isProcessing or slot<=9) and
                            type(value)=="string","Invalid recipe ingredient for "..name)
                        slots[#slots+1]=slot
                    end
                end
                table.sort(slots)
                for _,slot in ipairs(slots) do
                    local original=chosen[slot];local inputQty=1
                    if chosen.isProcessing then
                        local parsed,amount=original:match("^(.-),([%d%.]+)$")
                        if parsed then original=parsed;inputQty=tonumber(amount) end
                    end
                    assert(inputQty and inputQty>0 and inputQty<math.huge,
                        "Invalid processing ingredient quantity for "..name)
                    if original~="minecraft:air" then
                        local candidates=resolvedItems(original)
                        local specific=coroutine.yield("select_oredict",original,candidates,chosen,slot,inventory)
                        if specific==nil then specific=defaultIngredient(candidates,inventory,original) end
                        assert(type(specific)=="string","Invalid ingredient choice for "..name)
                        local canonical=identity.canonical(specific)
                        local family=rules.family(canonical)
                        if profiles[family] and not chosen.isProcessing then
                            assert(rules.validate(profiles[family]))
                            canonical=family
                            b.tools[family]={durability=profiles[family].durability,
                                durabilityPerUse=profiles[family].durabilityPerUse}
                            node.tool_slots[slot]=family
                            specific=family -- Wear variants use the fresh manufacturing route.
                        end
                        node.recipe[slot]=canonical;node.deps[slot]=canonical
                        node.ingredient_sources[slot]=original
                        node.input_quantities[slot]=inputQty
                        rawNames[canonical]=rawNames[canonical] or specific
                        stack[#stack+1]={item=canonical}
                    end
                end
                assert(next(node.recipe),"Recipe has no ingredients for "..name)
            end
        end
    end
    return assert(blueprint.calculate(b,inventory))
end

-- Explicit route-edit capture. Returns choices even when current stock cannot
-- satisfy the temporary one-unit demand; final accounting belongs to the caller.
function craftLib.captureChoices(item,inventory,profiles,selectChoice,recipe)
    local co=coroutine.create(function() return capture(item,1,inventory,profiles or {},false,recipe) end)
    local input
    while true do
        local values={coroutine.resume(co,input)}
        if not table.remove(values,1) then return nil,tostring(values[1]) end
        if coroutine.status(co)=="dead" then return values[1].blueprint end
        input=nil
        if selectChoice then
            local ok,value=pcall(selectChoice,values)
            if not ok then return nil,tostring(value) end
            input=value
        end
    end
end
function craftLib.materialAllowed(source,item)
    local wanted=identity.canonical(item)
    local candidates=resolvedItems(source)
    for _,name in ipairs(candidates) do if identity.canonical(name)==wanted then return true end end
    for _,pattern in ipairs(candidates.wildcards) do
        local base=pattern:gsub(":%*%s*$","")
        if wanted==identity.canonical(base) or wanted:match("^(.*):%d+$")==base then return true end
    end
    return false
end

local function fail(plan,message)
    plan.success=false;plan.craftable=false;plan.error=message
    plan.coroutine=nil;plan.yield_data=nil
    return {success=false,error=message,planResult=plan}
end
local function resume(plan,input)
    local values={coroutine.resume(plan.coroutine,input)}
    if not table.remove(values,1) then return fail(plan,"Error during calculation: "..tostring(values[1])) end
    if coroutine.status(plan.coroutine)=="dead" then
        local result=values[1]
        for k,v in pairs(result) do plan[k]=v end
        plan.coroutine=nil;plan.yield_data=nil;plan.error=nil
    else plan.yield_data=values end
    return {success=true,planResult=plan}
end

function craftLib.calculateCraftingPlan(item,quantity,transposer,side,shouldCraftNewItem,options)
    local plan={success=true,craftable=false,requestItem=item}
    local ok,problem=pcall(function()
        assert(transposer and transposer.getAllStacks,"Invalid or missing transposer component proxy.")
        assert(type(side)=="number" and side>=0 and side<=5 and side%1==0,"Invalid inventory side provided.")
        assert(type(item)=="string" and item:find(":",1,true),"Invalid item name provided.")
        quantity=tonumber(quantity) or 1
        assert(quantity>0 and quantity<math.huge,"Quantity must be finite and positive.")
        quantity=math.ceil(quantity);plan.requestQuantity=quantity
        options=options or {};assert(type(options)=="table","Invalid planner options.")
        local inventory=assert(InventoryCache.new(transposer,side),"Unable to read crafting inventory.")
        local profiles=options.toolProfiles
        if profiles==nil then profiles=require("craft_tools").list() end
        assert(type(profiles)=="table","Invalid tool profile table.")
        plan.coroutine=coroutine.create(function()
            return capture(item,quantity,inventory,profiles,shouldCraftNewItem==false)
        end)
        resume(plan)
    end)
    if not ok then fail(plan,tostring(problem)) end
    return plan
end
function craftLib.resumeCalculation(plan,input)
    if type(plan)~="table" then return {success=false,error="Invalid plan."} end
    if type(plan.coroutine)~="thread" or coroutine.status(plan.coroutine)~="suspended" then
        return fail(plan,plan.error or "Invalid or non-suspended coroutine provided.")
    end
    return resume(plan,input)
end
function craftLib.cancelCalculation(plan)
    if type(plan)~="table" then return {success=false,error="Invalid plan."} end
    plan.cancelled=true;return fail(plan,"Crafting calculation cancelled.")
end
return craftLib
