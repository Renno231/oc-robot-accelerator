-- Shared, hardware-free validation of a fixed robot crafting batch.
local identity = require "item_identity"
local rules = require "craft_tool_rules"
local plan = {}

local function positiveInteger(value)
    return type(value) == "number" and value == value and value < math.huge and
        value > 0 and value % 1 == 0
end

local function itemID(value)
    return type(value) == "string" and value:find(":", 1, true) and
        not value:find("*", 1, true) and not value:find(" | ", 1, true) and
        value:sub(1, 4) ~= "ore:"
end

function plan.outputs(batch)
    local out={}
    if batch.requestOutputs~=nil then
        if type(batch.requestOutputs)~="table" then return nil,"Invalid requested outputs." end
        for item,qty in pairs(batch.requestOutputs) do
            if not itemID(item) or item=="minecraft:air" or not positiveInteger(qty) then
                return nil,"Invalid requested output."
            end
            item=identity.canonical(item);out[item]=(out[item] or 0)+qty
            if not positiveInteger(out[item]) then return nil,"Requested output overflow." end
        end
        if not next(out) then return nil,"Empty requested outputs." end
        if batch.requestItem~=nil or batch.requestQuantity~=nil then
            if not itemID(batch.requestItem) or not positiveInteger(batch.requestQuantity) or
                out[identity.canonical(batch.requestItem)]~=batch.requestQuantity then
                return nil,"Requested outputs disagree with the legacy target."
            end
        end
    elseif itemID(batch.requestItem) and positiveInteger(batch.requestQuantity) then
        out[identity.canonical(batch.requestItem)]=batch.requestQuantity
    else return nil,"Invalid crafting target." end
    return out
end

function plan.reservations(map)
    if map==nil then return {} end
    if type(map)~="table" then return nil,"Invalid external reservations." end
    local out={}
    for item,qty in pairs(map) do
        if not itemID(item) or item=="minecraft:air" or not positiveInteger(qty) then
            return nil,"Invalid external reservation."
        end
        item=identity.canonical(item);out[item]=(out[item] or 0)+qty
        if not positiveInteger(out[item]) then return nil,"External reservation overflow." end
    end
    return out
end

local function validateExtras(batch)
    local outputs,problem=plan.outputs(batch);if not outputs then return false,problem end
    local reserved,why=plan.reservations(batch.external_reserved);if not reserved then return false,why end
    local ok,err=pcall(function()
        local profiles=batch.tools or {}
        assert(type(profiles)=="table","Invalid captured tools.")
        for family,profile in pairs(profiles) do
            assert(type(family)=="string" and family:match("^[^:]+:[^:]+$"),"Invalid tool family.")
            assert(rules.validate(profile))
        end
        local function dense(t)
            assert(type(t)=="table","Invalid tool units.")
            local count=0
            for i,v in pairs(t) do
                assert(positiveInteger(i) and i<=#t and positiveInteger(v),"Invalid tool capacity.")
                count=count+1
            end
            assert(count==#t and count>0,"Empty or sparse tool units.")
        end
        local stock=batch.tool_stock or {};assert(type(stock)=="table","Invalid tool stock.")
        for family,units in pairs(stock) do
            assert(profiles[family],"Missing captured tool profile.");dense(units)
            for _,uses in ipairs(units) do
                assert(uses<=rules.usesLeft({damage=0},profiles[family]),"Impossible tool wear requirement.")
            end
        end
        local nodes=batch.node_items
        if nodes then
            assert(type(nodes)=="table" and type(batch.stock_nodes)=="table" and
                type(batch.request_nodes)=="table","Incomplete branch accounting.")
            for id,item in pairs(nodes) do
                assert(type(id)=="string" and #id>0 and itemID(item),"Invalid branch item.")
            end
            for id,qty in pairs(batch.request_nodes) do
                assert(nodes[id] and positiveInteger(qty),"Invalid protected branch output.")
            end
            local roots={}
            for id,qty in pairs(batch.request_nodes) do
                local item=identity.canonical(nodes[id]);roots[item]=(roots[item] or 0)+qty
            end
            for item,qty in pairs(outputs) do assert(roots[item]==qty,"Protected outputs mismatch.") end
            for item,qty in pairs(roots) do assert(outputs[item]==qty,"Unexpected protected output.") end
            local withdrawn={}
            for id,qty in pairs(batch.stock_nodes) do
                assert(nodes[id] and positiveInteger(qty),"Invalid branch stock.")
                local item=identity.canonical(nodes[id]);withdrawn[item]=(withdrawn[item] or 0)+qty
            end
            local expected={}
            for item,qty in pairs(batch.inventory_needed) do
                item=identity.canonical(item);expected[item]=(expected[item] or 0)+qty
            end
            for item,qty in pairs(expected) do assert(withdrawn[item]==qty,"Branch withdrawal mismatch.") end
            for item,qty in pairs(withdrawn) do assert(expected[item]==qty,"Unexpected branch withdrawal.") end
            for family,units in pairs(stock) do
                local ids=(batch.tool_stock_nodes or {})[family]
                assert(type(ids)=="table" and #ids==#units,"Missing tool branch bindings.")
                local count=0
                for i,id in pairs(ids) do
                    assert(positiveInteger(i) and i<=#ids and nodes[id]==family,"Invalid tool branch binding.")
                    count=count+1
                end
                assert(count==#units,"Sparse tool branch bindings.")
            end
        else
            assert(batch.stock_nodes==nil and batch.request_nodes==nil and batch.tool_stock_nodes==nil,
                "Missing branch item metadata.")
        end
        for _,task in ipairs(batch.tasks) do
            assert(type(task.tool_slots or {})=="table","Invalid tool slots.")
            for slot,family in pairs(task.tool_slots or {}) do
                assert(positiveInteger(slot) and slot<=9 and task.recipe[slot]==family and profiles[family],
                    "Invalid task tool slot.")
            end
            if nodes then
                assert(nodes[task.node] and identity.canonical(nodes[task.node])==identity.canonical(task.item) and
                    type(task.input_nodes)=="table","Invalid task branch.")
                for slot,item in pairs(task.recipe) do
                    if item~="minecraft:air" then
                        assert(nodes[task.input_nodes[slot]] and
                            identity.canonical(nodes[task.input_nodes[slot]])==identity.canonical(item),
                            "Invalid ingredient branch.")
                    end
                end
                for slot in pairs(task.input_nodes) do assert(task.recipe[slot],"Unexpected ingredient branch.") end
            else assert(task.node==nil and task.input_nodes==nil,"Missing task branch metadata.") end
        end
    end)
    return ok,not ok and tostring(err) or nil
end

local outputMap=plan.outputs
function plan.validate(plan)
    if type(plan) ~= "table" or type(plan.inventory_needed) ~= "table" or
        type(plan.tasks) ~= "table" then return false, "Invalid crafting plan." end
    for item, quantity in pairs(plan.inventory_needed) do
        if not itemID(item) or not positiveInteger(quantity) then
            return false, "Invalid inventory requirement."
        end
    end
    local taskCount,produced = 0,{}
    for index, task in pairs(plan.tasks) do
        taskCount = taskCount + 1
        if not positiveInteger(index) or index > #plan.tasks or type(task) ~= "table" then
            return false, "Invalid task list."
        end
        if task.isProcessing or task.machineType then
            return false, "Machine processing is not supported by this robot executor."
        end
        if not itemID(task.item) or not positiveInteger(task.recipeOutput) or
            not positiveInteger(task.qty_produced) or task.qty_produced % task.recipeOutput ~= 0 or
            type(task.recipe) ~= "table" then return false, "Invalid crafting task." end
        local inputs = 0
        for slot, item in pairs(task.recipe) do
            if not positiveInteger(slot) or slot > 9 or not itemID(item) or identity.canonical(item) == identity.canonical(task.item) then
                return false, "Invalid or self-dependent recipe ingredient."
            end
            if item ~= "minecraft:air" then inputs = inputs + 1 end
        end
        if inputs == 0 then return false, "Crafting recipe has no ingredients." end
        local item=identity.canonical(task.item)
        produced[item]=(produced[item] or 0)+task.qty_produced
        if not positiveInteger(produced[item]) then return false,"Crafted output overflow." end
    end
    if taskCount ~= #plan.tasks or taskCount == 0 then return false, "Empty or sparse task list." end
    local outputs,problem=outputMap(plan)
    if not outputs then return false,problem end
    for item,qty in pairs(outputs) do
        if (produced[item] or 0)<qty then return false,"Tasks do not produce the requested quantity: "..item end
    end
    return validateExtras(plan)
end

-- Conservation check for merged snapshots and captured plans. Legacy snapshots
-- keep their existing execution-time checks; callers explicitly invoke this
-- before combining them into a multi-output job.
function plan.validateFlow(batch)
    local valid,err=plan.validate(batch);if not valid then return false,err end
    local balance,branches,protected={},{},{}
    local profiles=batch.tools or {}
    local pools=require("craft_tool_budget").new(nil,profiles,true)
    local function scope(node,item) return node or identity.canonical(item) end
    for node,qty in pairs(batch.stock_nodes or {}) do branches[node]=qty end
    for item,qty in pairs(batch.inventory_needed) do
        item=identity.canonical(item);balance[item]=(balance[item] or 0)+qty
    end
    for family,units in pairs(batch.tool_stock or {}) do
        balance[family]=(balance[family] or 0)+#units
        for index,uses in ipairs(units) do
            local node=batch.node_items and batch.tool_stock_nodes[family][index] or nil
            local id=scope(node,family)
            pools.supply(family,1,uses,id,true)
            if node then branches[node]=(branches[node] or 0)+1 end
        end
    end
    for _,task in ipairs(batch.tasks) do
        local ops=task.qty_produced/task.recipeOutput
        local tools={}
        for slot,item in pairs(task.recipe) do
            item=identity.canonical(item)
            if item~="minecraft:air" then
                local dep=task.input_nodes and task.input_nodes[slot]
                if (task.tool_slots or {})[slot] then
                    local id=scope(dep,item)
                    tools[id]=tools[id] or {item=item,node=dep,count=0}
                    tools[id].count=tools[id].count+1
                else
                    balance[item]=(balance[item] or 0)-ops
                    if balance[item]<0 then return false,"Insufficient fixed prerequisite: "..item end
                    if dep then
                        branches[dep]=(branches[dep] or 0)-ops
                        if branches[dep]<(protected[dep] or 0) then return false,"Insufficient fixed prerequisite in an ingredient branch, or a protected output would be consumed." end
                    end
                end
            end
        end
        for id,entry in pairs(tools) do
            if (balance[entry.item] or 0)<entry.count then return false,"Insufficient distinct fixed tools: "..entry.item end
            if pools.charge(entry.item,entry.count,ops,id,false)>0 then
                return false,"Insufficient fixed tool wear budget: "..entry.item
            end
        end
        local item=identity.canonical(task.item);balance[item]=(balance[item] or 0)+task.qty_produced
        local id=scope(task.node,item)
        local rootQty=batch.node_items and (batch.request_nodes[task.node] or 0) or (assert(plan.outputs(batch))[item] or 0)
        local already=protected[id] or 0
        local hold=math.min(math.max(0,rootQty-already),task.qty_produced)
        protected[id]=already+hold
        if task.node then branches[task.node]=(branches[task.node] or 0)+task.qty_produced end
        local family=rules.family(item)
        local free=task.qty_produced-hold
        if profiles[family] and free>0 then
            local damage=tonumber(item:match(":(%d+)$")) or 0
            local capacity=rules.usesLeft({damage=damage},profiles[family])
            if capacity>0 then pools.supply(family,free,capacity,id,false) end
        end
    end
    for node,qty in pairs(batch.request_nodes or {}) do
        if (branches[node] or 0)<qty then return false,"Fixed tasks cannot preserve a requested output branch." end
    end
    for item,qty in pairs(assert(plan.outputs(batch))) do
        if (balance[item] or 0)<qty then return false,"Fixed tasks cannot preserve output: "..item end
    end
    return true
end

return plan
