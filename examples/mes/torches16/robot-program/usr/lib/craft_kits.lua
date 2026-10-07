-- Labelled plan collections with explicit bindings, execution and accounting.
-- No hardware/UI/network/recipe database is loaded by requiring this library.
local plans=require "craft_plans"
local validator=require "craft_plan"
local store=require "craft_store"
local identity=require "item_identity"
local kits={directory="/usr/craftkits/"}
local function storage() return store.new(kits.directory,".kit") end
local function copy(t)
    if type(t)~="table" then return t end
    local out={};for k,v in pairs(t) do out[k]=copy(v) end;return out
end
local function modes(mode,accounting)
    assert(mode=="separate" or mode=="merged","Execution mode must be separate or merged.")
    assert(accounting=="saved" or accounting=="refresh","Accounting must be saved or refresh.")
end
local function capture(kit)
    assert(type(kit)=="table" and type(kit.entries)=="table" and #kit.entries>0,"Kit must contain plans.")
    local mode,accounting=kit.executionMode or "separate",kit.accounting or "saved"
    modes(mode,accounting)
    local out={executionMode=mode,accounting=accounting,entries={}}
    local count=0
    for i,entry in pairs(kit.entries) do
        count=count+1
        assert(type(i)=="number" and i%1==0 and i>=1 and i<=#kit.entries and type(entry)=="table","Invalid kit entries.")
        local row={binding=entry.binding}
        if entry.binding=="live" then
            assert(store.validName(entry.planName),"Invalid live plan name.");row.planName=entry.planName
        elseif entry.binding=="pinned" then
            if entry.sourceName~=nil then assert(store.validName(entry.sourceName),"Invalid pinned source name.");row.sourceName=entry.sourceName end
            row.plan=assert(plans.prepare(entry.plan))
        else error("Entry binding must be pinned or live.") end
        out.entries[i]=row
    end
    assert(count==#kit.entries,"Sparse kit entries.")
    return out
end
function kits.save(name,kit)
    local ok,data=pcall(capture,kit);if not ok then return nil,tostring(data) end
    return storage().save(name,data)
end
function kits.load(name)
    local data,err=storage().load(name);if not data then return nil,err end
    local ok,value=pcall(capture,data);if not ok then return nil,tostring(value) end
    return value
end
function kits.list() return storage().list() end
function kits.remove(name) return storage().remove(name) end
function kits.pin(name)
    local p,err=plans.load(name);if not p then return nil,err end
    return {binding="pinned",sourceName=name,plan=p}
end

local function mergeSaved(entries)
    local combined={success=true,craftable=true,inventory_needed={},external_needed={},tasks={},
        requestOutputs={},tools={},tool_stock={},node_items={},stock_nodes={},request_nodes={},tool_stock_nodes={}}
    local function add(t,k,n) t[k]=(t[k] or 0)+n;assert(t[k]>0 and t[k]<math.huge,"Merged quantity overflow.") end
    for index,entry in ipairs(entries) do
        local p=entry.plan;local prefix="p"..index..":"
        local function id(node,item) return prefix..(node or "item:"..identity.canonical(item)) end
        for item,qty in pairs(assert(validator.outputs(p))) do add(combined.requestOutputs,item,qty) end
        for item,qty in pairs(p.inventory_needed) do add(combined.inventory_needed,identity.canonical(item),qty) end
        if p.node_items then
            for node,item in pairs(p.node_items) do combined.node_items[id(node)]=item end
            for node,qty in pairs(p.stock_nodes) do combined.stock_nodes[id(node)]=qty end
            for node,qty in pairs(p.request_nodes) do combined.request_nodes[id(node)]=qty end
        else
            for item,qty in pairs(p.inventory_needed) do
                local node=id(nil,item);combined.node_items[node]=identity.canonical(item);add(combined.stock_nodes,node,qty)
            end
            for item,qty in pairs(assert(validator.outputs(p))) do
                local node=id(nil,item);combined.node_items[node]=item;add(combined.request_nodes,node,qty)
            end
        end
        for family,profile in pairs(p.tools or {}) do
            local old=combined.tools[family]
            assert(not old or (old.durability==profile.durability and old.durabilityPerUse==profile.durabilityPerUse),
                "Conflicting captured tool profiles for "..family)
            combined.tools[family]=copy(profile)
        end
        for family,units in pairs(p.tool_stock or {}) do
            combined.tool_stock[family]=combined.tool_stock[family] or {};combined.tool_stock_nodes[family]=combined.tool_stock_nodes[family] or {}
            for i,uses in ipairs(units) do
                local node=p.node_items and id(p.tool_stock_nodes[family][i]) or id(nil,family)
                combined.node_items[node]=family
                local j=#combined.tool_stock[family]+1
                combined.tool_stock[family][j]=uses;combined.tool_stock_nodes[family][j]=node
            end
        end
        for _,task in ipairs(p.tasks) do
            local t=copy(task);t.node=id(task.node,task.item);t.input_nodes={}
            combined.node_items[t.node]=identity.canonical(task.item)
            for slot,item in pairs(task.recipe) do
                if item~="minecraft:air" then
                    local dep=id(task.input_nodes and task.input_nodes[slot],item)
                    t.input_nodes[slot]=dep;combined.node_items[dep]=identity.canonical(item)
                end
            end
            combined.tasks[#combined.tasks+1]=t
        end
    end
    local outputs={};for item in pairs(combined.requestOutputs) do outputs[#outputs+1]=item end;table.sort(outputs)
    combined.requestItem=outputs[1];combined.requestQuantity=combined.requestOutputs[outputs[1]]
    local bs={}
    for i,entry in ipairs(entries) do
        if not entry.plan.blueprint then bs=nil;break end
        bs[i]=entry.plan.blueprint
    end
    if bs then combined.blueprint=assert(require("craft_blueprint").merge(bs)) end
    assert(validator.validateFlow(combined))
    return assert(plans.prepare(combined))
end
function kits.prepare(nameOrKit,options)
    local ok,result=pcall(function()
        options=options or {};assert(type(options)=="table","Kit options must be a table.")
        local kit=type(nameOrKit)=="string" and assert(kits.load(nameOrKit)) or capture(nameOrKit)
        local mode,accounting=options.executionMode or kit.executionMode,options.accounting or kit.accounting
        modes(mode,accounting)
        local entries,liveCache={},{}
        for i,entry in ipairs(kit.entries) do
            local p
            if entry.binding=="live" then
                if not liveCache[entry.planName] then liveCache[entry.planName]=assert(plans.load(entry.planName)) end
                p=assert(plans.prepare(liveCache[entry.planName]))
            else p=assert(plans.prepare(entry.plan)) end
            if accounting=="refresh" then assert(p.blueprint,"Plan has no blueprint; explicitly capture choices before refreshing.") end
            entries[i]={binding=entry.binding,name=entry.planName or entry.sourceName or "Entry "..i,plan=p}
        end
        local prepared={executionMode=mode,accounting=accounting,entries=entries}
        if mode=="merged" then
            if accounting=="saved" then prepared.plan=mergeSaved(entries)
            else
                local bs={};for i,entry in ipairs(entries) do bs[i]=entry.plan.blueprint end
                local bp=require "craft_blueprint"
                local merged=assert(bp.merge(bs))
                local p=assert(bp.calculate(merged,plans.inventory(options)))
                assert(p.craftable,"Missing allowed inputs: "..require("serialization").serialize(p.external_needed))
                prepared.plan=assert(plans.prepare(p))
            end
        end
        return prepared
    end)
    if not ok then return nil,tostring(result) end
    return result
end
function kits.run(nameOrKit,options)
    options=options or {}
    local result={status="failed",success=false,entries={},completedEntries=0,mayHaveExecuted=false}
    if type(nameOrKit)=="string" then result.name=nameOrKit end
    local ok,err=pcall(function()
        assert(type(options)=="table","Kit options must be a table.")
        for _,name in ipairs({"onSuccess","onFailure","onSkip","onMessage","shouldContinue"}) do
            assert(options[name]==nil or type(options[name])=="function",name.." must be a function.")
        end
        assert(options.stockAtLeast==nil,"Kit stock checks must check all components in the caller; stockAtLeast is single-plan only.")
        local reserved=assert(validator.reservations(options.externalReserved))
        local prepared=assert(kits.prepare(nameOrKit,options))
        result.executionMode=prepared.executionMode;result.accounting=prepared.accounting
        result.outputs={}
        for _,entry in ipairs(prepared.entries) do
            for item,qty in pairs(assert(validator.outputs(entry.plan))) do
                result.outputs[item]=(result.outputs[item] or 0)+qty
                assert(result.outputs[item]<math.huge,"Kit output quantity overflow.")
            end
        end
        local childOptions={};for k,v in pairs(options) do childOptions[k]=v end
        childOptions.onSuccess=nil;childOptions.onFailure=nil;childOptions.onSkip=nil
        if prepared.executionMode=="merged" then
            childOptions.accounting="saved" -- Combined refresh was performed once above.
            local r=plans.run(prepared.plan,childOptions)
            result.status=r.status;result.success=r.success;result.message=r.message
            result.mayHaveExecuted=r.mayHaveExecuted;result.cleanupError=r.cleanupError
            result.entries[1]=r
            if r.success then result.completedEntries=#prepared.entries end
        else
            childOptions.accounting=prepared.accounting
            for i,entry in ipairs(prepared.entries) do
                childOptions.externalReserved=next(reserved) and copy(reserved) or nil
                local r=plans.run(entry.plan,childOptions);r.name=entry.name;r.binding=entry.binding
                result.entries[i]=r;result.mayHaveExecuted=result.mayHaveExecuted or r.mayHaveExecuted or false
                if r.cleanupError then result.cleanupError=(result.cleanupError and result.cleanupError.."; " or "")..r.cleanupError end
                if not r.success and r.status~="skipped" then
                    result.status=r.status;result.message=r.message;return
                end
                if r.success then
                    result.completedEntries=result.completedEntries+1
                    for item,qty in pairs(r.outputs) do reserved[item]=(reserved[item] or 0)+qty end
                end
            end
            result.status="complete";result.success=true;result.message="All kit component plans completed."
        end
    end)
    if not ok then result.message=tostring(err) end
    result.partial=result.completedEntries>0 and not result.success
    local hook=result.status=="complete" and "onSuccess" or result.status=="skipped" and "onSkip" or "onFailure"
    if type(options)=="table" and type(options[hook])=="function" then
        local called,problem=pcall(options[hook],copy(result));if not called then result.hookError=tostring(problem) end
    end
    return result
end
return kits
