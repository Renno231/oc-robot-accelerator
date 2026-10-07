-- Purpose-binary adapters. Noninteractive paths never load GPU or qmenu.
local shell=require "shell"
local commands={}
local function number(options,name,min,integer)
    if options[name]==nil then return nil end
    local n=tonumber(options[name])
    assert(n and n>=min and n<math.huge and (not integer or n%1==0),"Invalid --"..name)
    return n
end
function commands.options(flags)
    local o={accounting=flags.accounting,executionMode=flags.mode or flags["execution-mode"],
        storageSide=number(flags,"storage-side",0,true),stockAtLeast=number(flags,"stock-at-least",0,true),
        connectTimeout=number(flags,"connect-timeout",0),idleTimeout=number(flags,"idle-timeout",0),
        jobTimeout=number(flags,"job-timeout",0),discoveryTimeout=number(flags,"discovery-timeout",0),
        port=number(flags,"port",1,true),resultId=flags["result-id"],onMessage=print}
    assert(not o.storageSide or o.storageSide<=5,"Invalid storage side.")
    assert(not o.port or o.port<=65535,"Invalid modem port.")
    for _,key in ipairs({"connectTimeout","idleTimeout","discoveryTimeout"}) do
        assert(not o[key] or o[key]>0,"Timeout must be positive: "..key)
    end
    assert(not o.accounting or o.accounting=="saved" or o.accounting=="refresh","Accounting must be saved or refresh.")
    assert(not o.executionMode or o.executionMode=="separate" or o.executionMode=="merged","Mode must be separate or merged.")
    return o
end
local function setOf(text)
    local out={};for item in tostring(text or ""):gmatch("[^,]+") do out[item]=true end;return out
end
function commands.calculatePlan(item,quantity,options,selectChoice)
    local plans=require "craft_plans"
    quantity=tonumber(quantity or 1)
    if not quantity or quantity<=0 or quantity>=math.huge or quantity%1~=0 then return nil,"Quantity must be a positive integer." end
    options=options or {}
    local ok,result,problem=pcall(function()
        local side=options.storageSide or 0
        local proxy=options.transposer or require("component").transposer
        local planner=require "craftingv4_4"
        local p=planner.calculateCraftingPlan(item,quantity,proxy,side,true,{toolProfiles=options.toolProfiles})
        local leaves,make=setOf(options.leaf),setOf(options.make)
        while p.yield_data do
            if options.shouldContinue and not options.shouldContinue() then
                planner.cancelCalculation(p);return nil,"Crafting calculation cancelled."
            end
            local yielded=p.yield_data;local input
            if yielded[1]=="select_recipe" and leaves[yielded[2]] then input=false
            elseif yielded[1]=="skip_inventory_check" and make[yielded[2]] then input=true
            elseif selectChoice then
                local selected,value=pcall(selectChoice,yielded)
                if not selected then planner.cancelCalculation(p);return nil,tostring(value) end
                input=value
            end
            planner.resumeCalculation(p,input)
        end
        if not p.success then return nil,p.error end
        if not p.craftable then return nil,"Missing allowed inputs: "..require("serialization").serialize(p.external_needed) end
        return plans.prepare(p)
    end)
    if not ok then return nil,tostring(result) end
    return result,problem
end
function commands.createPlan(label,item,quantity,options,selectChoice)
    if not require("craft_store").validName(label) then return nil,"Invalid plan label." end
    local p,err=commands.calculatePlan(item,quantity,options,selectChoice)
    if not p then return nil,err end
    local saved,problem=require("craft_plans").save(label,p)
    if not saved then return nil,problem end
    return p
end
function commands.resultCode(result)
    if result.status=="complete" or result.status=="skipped" then return 0 end
    if result.status=="unknown" or result.status=="running" or result.status=="not_found" then return 3 end
    return 1
end
function commands.report(result,options)
    if options and options.resultId then require("craft_handoff").report(options.resultId,result) end
end
function commands.receiptLines(result)
    local out,seen={},{}
    local function visit(r)
        if r.jobId and r.serverAddress then
            local key=r.serverAddress..":"..r.jobId
            if not seen[key] then seen[key]=true;out[#out+1]="Receipt: craftplan status "..r.serverAddress.." "..r.jobId end
        end
        for _,child in ipairs(r.entries or {}) do visit(child) end
    end
    visit(result);return out
end
local usage={
    tools="crafttools list | set ITEM --durability=N --wear=N | remove ITEM | --interactive",
    plans="craftplan list | show LABEL | preview LABEL | edit LABEL --node=ID --stock=true|false OR --recipe=N OR --slot=N --material=ID [--save --to=LABEL] | status ROBOT JOBID | create LABEL ITEM [QTY] | run LABEL [--accounting=saved|refresh] | copy LABEL NEWLABEL | remove LABEL | --interactive",
    kits="craftkit list | show LABEL | create LABEL PLAN... [--binding=live|pinned] | add LABEL PLAN | remove-entry LABEL INDEX | bind LABEL INDEX live|pinned [--plan=LABEL] | set LABEL --mode=separate|merged [--accounting=saved|refresh] | run LABEL | copy LABEL NEWLABEL | remove LABEL | --interactive",
    stockkeeper="stockkeeper list | show LABEL | create LABEL --plan=PLAN|--kit=KIT --item=ID --quantity=N [--interval=SECONDS --trigger=replacement|level --use-existing] | set LABEL [same flags] | enable|disable|resume|check|status|remove LABEL | start | stop | --interactive",
}
local function stockCommand(args,flags,opts)
    local lib=require "stockkeeper"
    local action,name=args[1] or "list",args[2]
    -- Long-lived checks don't print into whichever menu happens to be open.
    opts.onMessage=nil
    if action=="list" then
        for _,label in ipairs(assert(lib.list())) do print(label) end
    elseif action=="start" then
        local r=assert(lib.start(opts));print("Started: "..r.started.."; already running: "..r.alreadyRunning)
        for label,err in pairs(r.errors) do print(label..": "..err) end
        if next(r.errors) then return 1,"Some rules could not be started." end
    elseif action=="stop" then
        local stopped,errors=lib.stop()
        for label,err in pairs(errors) do print(label..": "..err) end
        if not stopped then return 1,"Some rules could not be disabled." end
    else
        assert(name,usage.stockkeeper)
        if action=="create" or action=="set" then
            assert(not (flags.plan and flags.kit),"Choose one plan or kit source.")
            assert(flags.accounting==nil and flags.mode==nil and flags["execution-mode"]==nil,
                "Use --use-existing for stock reuse; execution mode comes from the kit.")
            local rule=action=="set" and assert(lib.load(name)) or {interval=60,trigger="replacement"}
            rule.item=flags.item or rule.item
            rule.quantity=number(flags,"quantity",0,true) or rule.quantity
            rule.interval=number(flags,"interval",0) or rule.interval
            rule.trigger=flags.trigger or rule.trigger
            if flags.plan then rule.source={kind="plan",name=flags.plan}
            elseif flags.kit then rule.source={kind="kit",name=flags.kit} end
            if flags["use-existing"]~=nil then
                local v=flags["use-existing"]
                assert(v==true or v=="true" or v=="false","--use-existing accepts true or false.")
                rule.useExisting=(v==true or v=="true") or nil
            end
            for _,key in ipairs({"storageSide","port","connectTimeout","idleTimeout","discoveryTimeout","jobTimeout"}) do
                if opts[key]~=nil then rule[key]=opts[key] end
            end
            assert(lib.save(name,rule))
        elseif action=="show" or action=="status" then
            print(require("serialization").serialize(assert(lib[action=="show" and "load" or "status"](name))))
        elseif action=="check" then
            local r=lib.check(name,opts);print(r.status..": "..tostring(r.message or ""))
            commands.report(r,opts)
            for _,line in ipairs(commands.receiptLines(r)) do print(line) end
            if r.status=="unknown" then print("Inspect storage, then use stockkeeper resume LABEL.") end
            if r.persistenceError then print(r.persistenceError) end
            return commands.resultCode(r),not r.success and r.message or nil
        elseif action=="enable" or action=="resume" then assert(lib[action](name,opts))
        elseif action=="disable" or action=="remove" then assert(lib[action](name))
        else error(usage.stockkeeper) end
    end
    return 0
end
function commands.main(kind,...)
    local args,flags=shell.parse(...)
    if flags.help or flags.h then print(usage[kind]);return 0 end
    local ok,code,message=pcall(function()
        local opts=commands.options(flags)
        if flags.interactive or flags.i then
            opts.new=flags.new
            return require("craft_management_ui").show(kind,opts)
        end
        if kind=="stockkeeper" then return stockCommand(args,flags,opts) end
        local action=args[1] or "list"
        local lib=kind=="tools" and require("craft_tools") or kind=="plans" and require("craft_plans") or require("craft_kits")
        if action=="list" then
            local values=assert(lib.list())
            if kind=="tools" then
                local names={};for name in pairs(values) do names[#names+1]=name end;table.sort(names)
                for _,name in ipairs(names) do local p=values[name];print(name.." durability="..p.durability.." wear="..p.durabilityPerUse) end
            else for _,name in ipairs(values) do print(name) end end
        elseif kind=="tools" and action=="set" then
            assert(args[2],usage[kind]);assert(lib.set(args[2],number(flags,"durability",1,true),number(flags,"wear",0,true)))
        elseif action=="remove" then assert(args[2],usage[kind]);assert(lib.remove(args[2]))
        elseif action=="show" and kind~="tools" then
            assert(args[2],usage[kind]);print(require("serialization").serialize(assert(lib.load(args[2]))))
        elseif action=="status" and kind=="plans" then
            local r=lib.query(assert(args[2],"Specify robot address."),assert(args[3],"Specify job ID."),opts)
            print(r.status..": "..tostring(r.message or ""))
            return commands.resultCode(r),not r.success and r.message or nil
        elseif action=="preview" and kind=="plans" then
            local p=assert(lib.load(assert(args[2],usage[kind])))
            for _,line in ipairs(assert(require("craft_preview").lines(p))) do print(line) end
        elseif action=="edit" and kind=="plans" then
            local kinds=(flags.stock~=nil and 1 or 0)+(flags.material~=nil and 1 or 0)+(flags.recipe~=nil and 1 or 0)
            assert(kinds==1,"Choose exactly one edit kind: --stock, --recipe or --material.")
            assert(flags.save==nil or flags.save==true or flags.save=="true" or flags.save=="false","--save accepts true or false.")
            local p=assert(lib.load(assert(args[2],usage[kind])))
            local node=assert(flags.node,"Specify --node from the preview.")
            local change={node=node}
            if flags.stock~=nil then
                assert(flags.stock=="true" or flags.stock=="false","--stock accepts true or false.")
                change.kind="stock";change.useStock=flags.stock=="true"
            elseif flags.material then
                change.kind="material";change.slot=number(flags,"slot",1,true);change.item=flags.material
            else
                change.kind="recipe"
                local n=assert(p.blueprint and p.blueprint.nodes[node],"Unknown captured branch.")
                local all=assert(require("craft_edit").recipes(n.item))
                change.recipe=assert(all[number(flags,"recipe",1,true)],"Invalid recipe index.")
            end
            local candidate,diff=require("craft_edit").candidate(p,change,opts)
            assert(candidate,diff)
            for _,line in ipairs(diff) do print(line) end
            if flags.save==true or flags.save=="true" then assert(lib.save(flags.to or args[2],candidate));print("Candidate saved.")
            else print("Not saved. Review, then explicitly use --save (optionally --to=LABEL).") end
        elseif action=="copy" and kind~="tools" then
            assert(args[2] and args[3],usage[kind]);assert(lib.save(args[3],assert(lib.load(args[2]))))
        elseif action=="run" and kind~="tools" then
            assert(args[2],usage[kind]);local r=lib.run(args[2],opts)
            commands.report(r,opts)
            print(r.status..": "..tostring(r.message or ""))
            if r.status=="unknown" then print("Check storage before retrying: output may already exist.") end
            if r.cleanupError then print(r.cleanupError) end
            if r.hookError then print(r.hookError) end
            for _,line in ipairs(commands.receiptLines(r)) do print(line) end
            return commands.resultCode(r),not r.success and r.message or nil
        elseif action=="create" and kind=="plans" then
            assert(args[2] and args[3],usage[kind]);opts.leaf=flags.leaf;opts.make=flags.make
            assert(commands.createPlan(args[2],args[3],args[4],opts))
        elseif kind=="kits" then
            assert(args[2],usage[kind])
            local function entry(name,binding)
                assert(require("craft_store").validName(name),"Invalid plan label.")
                if binding=="pinned" then return assert(lib.pin(name)) end
                assert(binding=="live","Binding must be live or pinned.")
                return {binding="live",planName=name}
            end
            if action=="create" then
                local kit={executionMode=opts.executionMode or "separate",accounting=opts.accounting or "saved",entries={}}
                for i=3,#args do kit.entries[#kit.entries+1]=entry(args[i],flags.binding or "live") end
                assert(lib.save(args[2],kit))
            else
                local kit=assert(lib.load(args[2]))
                if action=="add" then kit.entries[#kit.entries+1]=entry(args[3],flags.binding or "live")
                elseif action=="set" then
                    kit.executionMode=opts.executionMode or kit.executionMode;kit.accounting=opts.accounting or kit.accounting
                elseif action=="remove-entry" or action=="bind" then
                    local i=tonumber(args[3]);assert(i and i%1==0 and kit.entries[i],"Invalid entry index.")
                    if action=="remove-entry" then table.remove(kit.entries,i)
                    else
                        local old=kit.entries[i];local name=flags.plan or old.planName or old.sourceName
                        kit.entries[i]=entry(name,args[4])
                    end
                else error(usage[kind]) end
                assert(lib.save(args[2],kit))
            end
        else error(usage[kind]) end
        return 0
    end)
    if not ok then return 2,tostring(code) end
    return code,message
end
return commands
