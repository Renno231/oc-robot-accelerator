-- Captured choices, pure accounting and structural kit composition. No hardware,
-- filesystem, recipe database, ore dictionary or interactive dependencies.
local identity = require "item_identity"
local rules = require "craft_tool_rules"
local budget = require "craft_tool_budget"
local lib = {}
local function integer(n) return type(n)=="number" and n>0 and n<math.huge and n%1==0 end
local function item(s)
    return type(s)=="string" and s:find(":",1,true) and not s:find("*",1,true) and
        not s:find(" | ",1,true) and s:sub(1,4)~="ore:" and s~="minecraft:air"
end
local function keys(t) local r={}; for k in pairs(t) do r[#r+1]=k end; table.sort(r); return r end
local function map(t) local r={}; for k,v in pairs(t or {}) do r[k]=v end; return r end
local function order(b)
    local seen, visiting, sorted = {}, {}, {}
    for _,root in ipairs(b.roots) do
        local stack={{id=root.node}}
        while #stack>0 do
            local frame=table.remove(stack); local id=frame.id
            if frame.exit then visiting[id]=nil; seen[id]=true; sorted[#sorted+1]=id
            elseif not seen[id] then
                if visiting[id] then error("Crafting dependency cycle detected at "..b.nodes[id].item) end
                visiting[id]=true; stack[#stack+1]={id=id,exit=true}
                local deps=b.nodes[id].deps or {}; local slots=keys(deps)
                for i=#slots,1,-1 do stack[#stack+1]={id=deps[slots[i]]} end
            end
        end
    end
    return sorted
end
function lib.validate(b)
    local ok,err=pcall(function()
        assert(type(b)=="table" and type(b.roots)=="table" and #b.roots>0 and
            type(b.nodes)=="table" and type(b.tools or {})=="table","Invalid blueprint.")
        local rootCount=0
        for i,r in pairs(b.roots) do
            rootCount=rootCount+1
            assert(integer(i) and i<=#b.roots and type(r)=="table" and
                type(r.node)=="string" and b.nodes[r.node] and integer(r.quantity),"Invalid blueprint root.")
        end
        assert(rootCount==#b.roots,"Sparse blueprint roots.")
        for family,profile in pairs(b.tools or {}) do
            assert(item(family) and rules.family(family)==family,"Invalid tool family.")
            assert(rules.validate(profile))
        end
        for id,n in pairs(b.nodes) do
            assert(type(id)=="string" and #id>0 and type(n)=="table" and item(n.item) and
                type(n.useStock)=="boolean","Invalid blueprint node.")
            if n.recipe then
                assert(type(n.recipe)=="table" and integer(n.recipeOutput) and
                    type(n.deps)=="table","Invalid captured recipe.")
                local inputs=0
                for slot,name in pairs(n.recipe) do
                    assert(integer(slot) and (n.isProcessing or slot<=9) and item(name) and
                        type(n.deps[slot])=="string" and b.nodes[n.deps[slot]],"Invalid captured ingredient.")
                    local dep=b.nodes[n.deps[slot]]
                    assert(identity.canonical(name)==identity.canonical(dep.item),"Ingredient/reference mismatch.")
                    local q=n.input_quantities and n.input_quantities[slot] or 1
                    assert(type(q)=="number" and q>0 and q<math.huge and
                        (n.isProcessing or q==1),"Invalid captured ingredient quantity.")
                    inputs=inputs+1
                end
                assert(inputs>0,"Recipe has no ingredients.")
                for slot in pairs(n.deps) do assert(n.recipe[slot],"Unexpected dependency slot.") end
                for slot,source in pairs(n.ingredient_sources or {}) do
                    assert(n.recipe[slot] and type(source)=="string","Invalid ingredient source.")
                end
                for slot,family in pairs(n.tool_slots or {}) do
                    assert(not n.isProcessing and n.recipe[slot]==family and (b.tools or {})[family],
                        "Invalid captured tool slot.")
                end
            else
                assert(n.recipeOutput==nil and n.deps==nil and n.tool_slots==nil and
                    n.input_quantities==nil and n.ingredient_sources==nil,"Invalid terminal node.")
            end
            assert(n.isProcessing==nil or type(n.isProcessing)=="boolean","Invalid processing flag.")
            assert(n.machineType==nil or type(n.machineType)=="string","Invalid machine type.")
        end
        local all={nodes=b.nodes,roots={}}
        for _,id in ipairs(keys(b.nodes)) do all.roots[#all.roots+1]={node=id} end
        order(all)
    end)
    return ok,not ok and tostring(err) or nil
end
function lib.copy(b)
    local valid,err=lib.validate(b); if not valid then return nil,err end
    local out={roots={},nodes={},tools={}}
    for i,r in ipairs(b.roots) do out.roots[i]={node=r.node,quantity=r.quantity} end
    for family,p in pairs(b.tools or {}) do out.tools[family]={durability=p.durability,durabilityPerUse=p.durabilityPerUse} end
    for id,n in pairs(b.nodes) do
        local node={item=identity.canonical(n.item),useStock=n.useStock,
            isProcessing=n.isProcessing,machineType=n.machineType}
        if n.recipe then
            node.recipeOutput=n.recipeOutput; node.recipe=map(n.recipe); node.deps=map(n.deps)
            node.tool_slots=map(n.tool_slots); node.input_quantities=map(n.input_quantities)
            if n.ingredient_sources then node.ingredient_sources=map(n.ingredient_sources) end
        end
        out.nodes[id]=node
    end
    return out
end
function lib.calculate(b,inventory)
    local valid,err=lib.validate(b); if not valid then return nil,err end
    local ok,result=pcall(function()
        assert(inventory and type(inventory.countItemByName)=="function","Missing accounting inventory.")
        b=assert(lib.copy(b)); local sorted=order(b)
        local function add(t,k,n)
            local value=(t[k] or 0)+n
            assert(value>=0 and value<math.huge,"Crafting demand overflow."); t[k]=value
        end
        local guess={}
        -- Demand flows toward leaves, but wear must be charged in the actual
        -- execution order. Replacement manufacture can itself need other tools.
        -- Iterate those DAG-local demands to a bounded fixed point.
        for pass=1,#sorted+2 do
            local demand,forced,reservations={},{},{}
            local inventoryNeeded,external,tasks,stockNodes,outputs,requestNodes={},{},{},{},{},{}
            for _,root in ipairs(b.roots) do
                add(demand,root.node,root.quantity); add(forced,root.node,root.quantity)
                add(requestNodes,root.node,root.quantity); add(outputs,b.nodes[root.node].item,root.quantity)
            end
            for id,n in pairs(guess) do add(demand,id,n); add(forced,id,n) end
            for i=#sorted,1,-1 do
                local id=sorted[i]; local node=b.nodes[id]; local needed=demand[id] or 0
                if needed>0 then
                    local take=0
                    if node.useStock then
                        local available=math.max(0,inventory:countItemByName(node.item)-(reservations[node.item] or 0))
                        take=math.min(math.max(0,needed-(forced[id] or 0)),available)
                    end
                    if take>0 then
                        add(reservations,node.item,take); add(inventoryNeeded,node.item,take); stockNodes[id]=take
                    end
                    local produce=needed-take
                    if produce>0 then
                        if not node.recipe then add(external,node.item,produce)
                        else
                            local ops=math.ceil(produce/node.recipeOutput)
                            tasks[id]={node=id,item=node.item,qty_produced=ops*node.recipeOutput,
                                repetitions=ops,recipeOutput=node.recipeOutput,recipe=map(node.recipe),
                                input_nodes=map(node.deps),tool_slots=map(node.tool_slots),
                                isProcessing=node.isProcessing,machineType=node.machineType}
                            for _,slot in ipairs(keys(node.recipe)) do
                                if not (node.tool_slots or {})[slot] then
                                    add(demand,node.deps[slot],ops*((node.input_quantities or {})[slot] or 1))
                                end
                            end
                        end
                    end
                end
            end
            local pools=budget.new(inventory,b.tools,false,reservations)
            local nextGuess,taskList={},{}
            for _,id in ipairs(sorted) do
                local task=tasks[id]
                if task then
                    taskList[#taskList+1]=task
                    local deps={}
                    for slot,family in pairs(task.tool_slots) do
                        local dep=task.input_nodes[slot]
                        deps[dep]=deps[dep] or {family=family,count=0}
                        deps[dep].count=deps[dep].count+1
                    end
                    for _,dep in ipairs(keys(deps)) do
                        add(nextGuess,dep,pools.charge(deps[dep].family,deps[dep].count,
                            task.repetitions,dep,b.nodes[dep].useStock))
                    end
                end
            end
            local same=true
            for _,id in ipairs(sorted) do if (guess[id] or 0)~=(nextGuess[id] or 0) then same=false end end
            if same then
                local profiles,stock,toolNodes=pools.snapshot(); local first=b.roots[1]
                -- The full graph remains in the saved blueprint, not the modem
                -- packet. Retain only branch identities used by this execution.
                local nodeItems={}
                local function include(id) nodeItems[id]=b.nodes[id].item end
                for id in pairs(requestNodes) do include(id) end
                for id in pairs(stockNodes) do include(id) end
                for _,task in ipairs(taskList) do
                    include(task.node);for _,dep in pairs(task.input_nodes) do include(dep) end
                end
                return {success=true,craftable=next(external)==nil,external_needed=external,
                    inventory_needed=inventoryNeeded,tasks=taskList,tools=profiles,tool_stock=stock,
                    tool_stock_nodes=toolNodes,stock_nodes=stockNodes,request_nodes=requestNodes,node_items=nodeItems,
                    requestItem=b.nodes[first.node].item,requestQuantity=outputs[b.nodes[first.node].item],
                    requestOutputs=outputs,blueprint=b}
            end
            guess=nextGuess
        end
        error("Tool accounting did not converge within the captured dependency graph.")
    end)
    if not ok then return nil,tostring(result) end
    return result
end
function lib.merge(blueprints)
    local ok,result=pcall(function()
        assert(type(blueprints)=="table" and #blueprints>0,"No blueprints to merge.")
        local out={nodes={},roots={},tools={}}; local intern,sequence={},0
        for _,b in ipairs(blueprints) do
            b=assert(lib.copy(b))
            for family,p in pairs(b.tools) do
                local old=out.tools[family]
                assert(not old or (old.durability==p.durability and old.durabilityPerUse==p.durabilityPerUse),
                    "Conflicting captured tool profiles for "..family.."; use separate mode or explicitly edit the profiles.")
                out.tools[family]=p
            end
            local translated={}
            for _,id in ipairs(order(b)) do
                local n=b.nodes[id]
                local function atom(value) return type(value)..":"..tostring(value) end
                local parts={n.item,atom(n.useStock),atom(n.recipeOutput),atom(n.isProcessing),atom(n.machineType)}
                for _,slot in ipairs(keys(n.recipe or {})) do
                    local fields={tostring(slot),n.recipe[slot],translated[n.deps[slot]],
                        tostring((n.input_quantities or {})[slot] or 1),(n.tool_slots or {})[slot] or ""}
                    fields[#fields+1]=(n.ingredient_sources or {})[slot] or ""
                    for _,s in ipairs(fields) do parts[#parts+1]=s end
                end
                local encoded={};for _,s in ipairs(parts) do encoded[#encoded+1]=#s..":"..s end
                local key=table.concat(encoded); local target=intern[key]
                if not target then
                    sequence=sequence+1; target="n"..sequence; intern[key]=target
                    local node={item=n.item,useStock=n.useStock,recipeOutput=n.recipeOutput,
                        isProcessing=n.isProcessing,machineType=n.machineType}
                    if n.recipe then
                        node.recipe=map(n.recipe); node.deps={}; node.tool_slots=map(n.tool_slots)
                        node.input_quantities=map(n.input_quantities)
                        if n.ingredient_sources then node.ingredient_sources=map(n.ingredient_sources) end
                        for slot,dep in pairs(n.deps) do node.deps[slot]=translated[dep] end
                    end
                    out.nodes[target]=node
                end
                translated[id]=target
            end
            for _,r in ipairs(b.roots) do out.roots[#out.roots+1]={node=translated[r.node],quantity=r.quantity} end
        end
        assert(lib.validate(out)); return out
    end)
    if not ok then return nil,tostring(result) end
    return result
end
return lib
