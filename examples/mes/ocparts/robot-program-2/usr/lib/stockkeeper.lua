-- Fixed-batch stock rules driven directly by OpenOS event.timer.
-- Requiring/listing this library does not start timers or load hardware/UI.
local store=require "craft_store"
local identity=require "item_identity"
local keeper={directory="/usr/stockkeeper/"}
local states,holds={},{}
local checking=false
local function storage() return store.new(keeper.directory,".rule") end
local function copy(value)
    if type(value)~="table" then return value end
    local out={};for k,v in pairs(value) do out[k]=copy(v) end;return out
end
local function shallow(value)
    local out={};for k,v in pairs(value or {}) do out[k]=v end;return out
end
local function integer(n) return type(n)=="number" and n>=0 and n<math.huge and n%1==0 end
local function capture(rule)
    assert(type(rule)=="table","Rule must be a table.")
    assert(type(rule.item)=="string" and (rule.item:match("^[^:%s]+:[^:%s]+$") or
        rule.item:match("^[^:%s]+:[^:%s]+:%d+$")) and not rule.item:find("%c") and
        not rule.item:find("*",1,true) and rule.item:sub(1,4)~="ore:" and rule.item~="minecraft:air",
        "Watch one exact item ID, not an ore dictionary or wildcard.")
    assert(integer(rule.quantity),"Quantity must be a finite nonnegative integer.")
    assert(type(rule.interval)=="number" and rule.interval>0 and rule.interval<math.huge,"Interval must be positive.")
    assert(rule.trigger=="level" or rule.trigger=="replacement","Trigger must be level or replacement.")
    local source=rule.source
    assert(type(source)=="table" and (source.kind=="plan" or source.kind=="kit") and
        store.validName(source.name),"Source must name a saved plan or kit.")
    assert(rule.enabled==nil or type(rule.enabled)=="boolean","Enabled must be a boolean.")
    assert(rule.paused==nil or type(rule.paused)=="boolean","Paused must be a boolean.")
    assert(rule.useExisting==nil or type(rule.useExisting)=="boolean","useExisting must be a boolean.")
    assert(identity.canonical(rule.item)~="minecraft:air","Cannot keep stock of air.")
    local out={item=identity.canonical(rule.item),quantity=rule.quantity,interval=rule.interval,
        trigger=rule.trigger,source={kind=source.kind,name=source.name},enabled=rule.enabled==true}
    if rule.useExisting then out.useExisting=true end
    if rule.paused then out.paused=true end
    for _,key in ipairs({"storageSide","port","connectTimeout","idleTimeout","discoveryTimeout","jobTimeout"}) do
        local n=rule[key]
        if n~=nil then
            assert(type(n)=="number" and n>=0 and n<math.huge,"Invalid "..key)
            if key=="storageSide" then assert(integer(n) and n<=5,"Invalid storage side.")
            elseif key=="port" then assert(integer(n) and n>=1 and n<=65535,"Invalid modem port.")
            elseif key~="jobTimeout" then assert(n>0,"Timeout must be positive: "..key) end
            out[key]=n
        end
    end
    return out
end
local function options(value)
    assert(value==nil or type(value)=="table","Options must be a table.")
    local out=shallow(value)
    for _,key in ipairs({"onSuccess","onFailure","onSkip","onMessage","shouldContinue","countStock"}) do
        assert(out[key]==nil or type(out[key])=="function",key.." must be a function.")
    end
    -- The trigger belongs to the rule; these plan/kit overrides must not bypass it.
    out.stockAtLeast=nil;out.accounting=nil;out.executionMode=nil;out.externalReserved=nil
    -- Each tick is a new attempt. GUI result tickets and previous job IDs belong
    -- to their initiating caller, not to a persistent rule's future timers.
    out.resultId=nil;out.jobId=nil
    return out
end
function keeper.list() return storage().list() end
function keeper.load(name)
    local value,err=storage().load(name);if not value then return nil,err end
    local ok,rule=pcall(capture,value);if not ok then return nil,tostring(rule) end
    return rule
end

local function live(state,name)
    return states[name]==state and state.active and state.rule.enabled and not state.rule.paused and not holds[name]
end
local function register(name,state)
    -- No timer IDs to track. Disabled/deleted/replaced callbacks retire themselves.
    assert(require("event").timer(state.rule.interval,function()
        if not live(state,name) then return false end
        keeper.check(name)
        if not live(state,name) then return false end
        -- In particular, a confirmed crafting failure must NOT return false.
    end,math.huge),"Timer registration failed.")
end
local function put(name,rule,opts,acknowledged)
    assert(store.validName(name),"Invalid rule label.")
    rule=capture(rule)
    local old=states[name]
    local previous=old and old.rule
    if not previous and not acknowledged then
        local fs=require "filesystem"
        if fs.exists(fs.concat(keeper.directory,name..".rule")) then previous=assert(keeper.load(name)) end
    end
    if not acknowledged and (holds[name] or (previous and previous.paused)) then rule.paused=true end
    local state={rule=rule,options=options(opts or (old and old.options)),lastResult=old and old.lastResult,
        busy=old and old.busy}
    -- Publish only after successful persistence. Old callbacks keep their old
    -- state reference and return false when they next run.
    assert(storage().save(name,rule))
    if acknowledged then holds[name]=nil end
    states[name]=state
    if rule.enabled and not rule.paused and not holds[name] then
        state.active=true
        local ok,err=pcall(register,name,state)
        if not ok then
            state.active=false;state.rule.enabled=false
            local saved,why=storage().save(name,state.rule)
            return nil,"Cannot register timer: "..tostring(err)..(not saved and "; "..tostring(why) or "")
        end
    end
    return true
end
function keeper.save(name,rule,opts)
    local ok,value,err=pcall(put,name,rule,opts)
    if not ok then return nil,tostring(value) end
    return value,err
end
function keeper.enable(name,opts)
    local rule,err=keeper.load(name);if not rule then return nil,err end
    if rule.paused or holds[name] then return nil,"Outcome unknown; inspect storage, then explicitly resume the rule." end
    local state=states[name]
    if state and live(state,name) and opts==nil then return true end
    rule.enabled=true;return keeper.save(name,rule,opts)
end
function keeper.disable(name)
    local state=states[name]
    local rule,err
    if state then rule=copy(state.rule) else rule,err=keeper.load(name) end
    if not rule then return nil,err end
    rule.enabled=false
    -- Turning checks off takes effect even if their file becomes unwritable.
    if state then state.active=false;state.rule.enabled=false end
    local ok,why=keeper.save(name,rule)
    if not ok and state then
        state.persistenceError="Checks disabled in memory; cannot persist disable: "..tostring(why)
        return nil,state.persistenceError
    end
    return ok,why
end
function keeper.resume(name,opts)
    if checking then return nil,"Wait for the active check before resuming." end
    local rule,err=keeper.load(name);if not rule then return nil,err end
    rule.paused=nil;rule.enabled=true
    local ok,value,why=pcall(put,name,rule,opts,true)
    if not ok then return nil,tostring(value) end
    return value,why
end
function keeper.remove(name)
    local ok,err=storage().remove(name);if not ok then return nil,err end
    states[name]=nil
    return true
end
function keeper.status(name)
    local state=states[name]
    local rule,err
    if state then rule=state.rule else rule,err=keeper.load(name) end
    if not rule then return nil,err end
    return {name=name,enabled=state~=nil and live(state,name) or false,configuredEnabled=rule.enabled,
        paused=rule.paused==true or holds[name]~=nil,busy=state and state.busy or false,
        rule=copy(rule),lastResult=copy(holds[name] or (state and state.lastResult)),
        persistenceError=state and state.persistenceError}
end
-- Explicit boot/rc entry point. Merely requiring the library never restores rules.
function keeper.start(opts)
    local valid,runOptions=pcall(options,opts);if not valid then return nil,tostring(runOptions) end
    local names,err=keeper.list();if not names then return nil,err end
    local result={started=0,alreadyRunning=0,errors={}}
    for _,name in ipairs(names) do
        local rule,why=keeper.load(name)
        if not rule then result.errors[name]=why
        elseif rule.enabled and not rule.paused and not holds[name] and
            not (states[name] and states[name].rule.paused) then
            local old=states[name]
            if old and old.persistenceError then result.errors[name]=old.persistenceError
            elseif old and live(old,name) then result.alreadyRunning=result.alreadyRunning+1
            else
                local state={rule=rule,options=opts==nil and old and old.options or runOptions,active=true,
                    lastResult=old and old.lastResult}
                states[name]=state
                local ok,problem=pcall(register,name,state)
                if ok then result.started=result.started+1
                else state.active=false;result.errors[name]=tostring(problem) end
            end
        end
    end
    return result
end
function keeper.stop()
    local errors={}
    for name in pairs(states) do
        local ok,err=keeper.disable(name);if not ok then errors[name]=err end
    end
    return not next(errors),errors
end

local function increment(batches,item)
    local total,declared=0,false
    local validator=require "craft_plan"
    for _,batch in ipairs(batches) do
        if assert(validator.outputs(batch))[item] then declared=true end
        for _,task in ipairs(batch.tasks) do
            if identity.canonical(task.item)==item then total=total+task.qty_produced end
            local operations=task.qty_produced/task.recipeOutput
            for slot,input in pairs(task.recipe) do
                local family=(task.tool_slots or {})[slot]
                if family then
                    if item:match("^[^:]+:[^:]+") == family and batch.tools[family].durabilityPerUse>0 then
                        error("Watched output is also a wearing tool; use a dedicated producer source.")
                    end
                elseif identity.canonical(input)==item then total=total-operations end
            end
        end
    end
    assert(declared,"Watched item is not a declared source output.")
    assert(integer(total) and total>0,"Source must have a positive net replenishment increment for the watched item.")
    return total
end
local function source(rule,opts)
    local plans=require "craft_plans"
    local function refresh(p)
        assert(p.blueprint,"Source has no blueprint; explicitly capture choices before using existing stock.")
        -- Keep an uncraftable forecast too: a small deficit should simply wait,
        -- even when materials for the next full batch are currently missing.
        return assert(require("craft_blueprint").calculate(p.blueprint,plans.inventory(opts)))
    end
    if rule.source.kind=="plan" then
        local p=assert(plans.load(rule.source.name))
        if rule.useExisting then p=refresh(p) end
        return {plan=p,batches={p}}
    end
    local kits=require "craft_kits"
    local prepared=assert(kits.prepare(rule.source.name,{accounting="saved"}))
    local frozen={executionMode=prepared.executionMode,accounting="saved",entries={}}
    local batches={}
    for i,entry in ipairs(prepared.entries) do
        frozen.entries[i]={binding="pinned",sourceName=entry.name,plan=entry.plan};batches[i]=entry.plan
    end
    if prepared.plan then
        local p=rule.useExisting and refresh(prepared.plan) or prepared.plan
        return {plan=p,batches={p},executionMode="merged",entryCount=#prepared.entries}
    end
    if rule.useExisting then
        for i,entry in ipairs(prepared.entries) do
            local bp=entry.plan.blueprint
            assert(bp,"Source has no blueprint; explicitly capture choices before using existing stock.")
            if #prepared.entries>1 then
                -- Later separate jobs see different inventory. For a watched
                -- output also used as an input, their net increment can change.
                -- One merged accounting pass is the supported exact forecast.
                local family=rule.item:match("^[^:]+:[^:]+")
                for _,node in pairs(bp.nodes) do
                    for slot,input in pairs(node.recipe or {}) do
                        assert(identity.canonical(input)~=rule.item and (node.tool_slots or {})[slot]~=family,
                            "Separate stock-reuse kits cannot also consume/use the watched output; use merged mode or a dedicated producer.")
                    end
                end
            end
            batches[i]=refresh(entry.plan)
        end
    end
    return {kit=frozen,batches=batches}
end
local function pause(name,result)
    holds[name]=copy(result)
    local state=states[name]
    if state then
        state.rule.paused=true;state.active=false
        local ok,saved,err=pcall(storage().save,name,state.rule)
        if not ok or not saved then result.persistenceError="Unknown hold could not be saved: "..tostring(err or saved) end
    end
    holds[name]=copy(result)
end
function keeper.check(name,overrides)
    if checking then return {status="skipped",success=false,name=name,message="Another stock check/craft is active."} end
    local state=states[name]
    if not state then
        local rule,err=keeper.load(name)
        if not rule then return {status="failed",success=false,name=name,message=err} end
        state={rule=rule,options={}};states[name]=state
    end
    if state.rule.paused or holds[name] then
        return copy(holds[name] or {status="unknown",success=false,name=name,message="Inspect storage, then explicitly resume the rule."})
    end
    checking=true;state.busy=true
    local rule=copy(state.rule)
    local result={status="failed",success=false,name=name,item=rule.item,source=copy(rule.source),mayHaveExecuted=false}
    local opts
    local ok,err=pcall(function()
        opts=options(state.options)
        for k,v in pairs(options(overrides)) do opts[k]=v end
        for _,key in ipairs({"storageSide","port","connectTimeout","idleTimeout","discoveryTimeout","jobTimeout"}) do
            if opts[key]==nil then opts[key]=rule[key] end
        end
        local plans=require "craft_plans"
        local snapshot
        if opts.countStock then result.stockCount=opts.countStock(rule.item)
        else snapshot=plans.inventory(opts);result.stockCount=snapshot:countItemByName(rule.item) end
        assert(integer(result.stockCount),"Stock count must be a finite nonnegative integer.")
        if (rule.trigger=="level" and result.stockCount>rule.quantity) or
            (rule.trigger=="replacement" and result.stockCount>=rule.quantity) then
            result.status="skipped";result.message="Stock trigger not reached.";return
        end
        local previewOptions=shallow(opts)
        if snapshot then previewOptions.inventory=snapshot end
        local captured=source(rule,previewOptions)
        result.increment=increment(captured.batches,rule.item)
        if rule.trigger=="replacement" and rule.quantity-result.stockCount<result.increment then
            result.status="skipped";result.message="Waiting for a full batch deficit.";return
        end
        local runOptions=shallow(opts)
        runOptions.onSuccess=nil;runOptions.onFailure=nil;runOptions.onSkip=nil
        -- Single/merged forecasts are already accounted once; replay that exact
        -- checked result. Separate reuse kits refresh each child at its live turn.
        runOptions.accounting=captured.kit and rule.useExisting and "refresh" or "saved"
        if states[name]~=state then
            result.status="skipped";result.message="Rule changed during the check.";return
        end
        if captured.plan and captured.plan.craftable==false then
            error("Missing allowed inputs: "..require("serialization").serialize(captured.plan.external_needed))
        end
        -- Snapshot the source now; live labels cannot change this checked action.
        local execution=captured.plan and plans.run(captured.plan,runOptions) or
            require("craft_kits").run(captured.kit,runOptions)
        for k,v in pairs(execution) do result[k]=v end
        result.accounting=rule.useExisting and "refresh" or "saved"
        if captured.executionMode then
            result.executionMode=captured.executionMode;result.entries={execution}
            result.completedEntries=execution.success and captured.entryCount or 0;result.partial=false
        end
        result.name=name;result.item=rule.item;result.source=copy(rule.source)
    end)
    if not ok then result.message=tostring(err) end
    if result.status=="unknown" then pause(name,result) end
    state.lastResult=copy(result)
    -- Report once for the whole source; hook errors don't change the job outcome.
    local hook=result.status=="complete" and "onSuccess" or result.status=="skipped" and "onSkip" or "onFailure"
    if opts and type(opts[hook])=="function" then
        local called,problem=pcall(opts[hook],copy(result));if not called then result.hookError=tostring(problem) end
    end
    state.lastResult=copy(result)
    if result.status=="unknown" then holds[name]=copy(result) end
    if states[name] and states[name]~=state then
        states[name].lastResult=copy(result);states[name].busy=false
    end
    state.busy=false;checking=false
    return result
end
return keeper
