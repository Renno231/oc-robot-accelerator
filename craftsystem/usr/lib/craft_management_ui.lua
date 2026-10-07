-- Interactive management shared by purpose binaries and craft's shell wrappers.
-- Hardware/qmenu are loaded only when this explicitly interactive module is used.
local component=require "component"
local event=require "event"
local keyboard=require "keyboard"
local qmenu=require "qmenu"
local tty=require "tty"
local term=require "term"
local ui={}
-- Clip by a conservative byte budget without splitting a UTF-8 character.
local function clip(text,width)
    text=tostring(text);local stop=math.min(#text,width)
    while stop>0 do
        local byte=text:byte(stop+1)
        if not byte or byte<128 or byte>=192 then break end
        stop=stop-1
    end
    return text:sub(1,stop)
end
function ui.show(kind,options)
    options=options or {}
    local gpu=assert(component.gpu,"A GPU is required for interactive management.")
    local w,h=gpu.getResolution();local viewport={tty.getViewport()}
    local running=true
    local lastJob
    local function interrupted() running=false end
    local function pick(title,rows,default)
        local page,pageSize=1,math.max(1,h-7)
        while running do
            term.clear();gpu.set(2,2,clip(title,w-3))
            local menu=qmenu.create();local choice,changed,done
            local nav={};local first=(page-1)*pageSize+1
            for i=first,math.min(#rows,first+pageSize-1) do
                local row=rows[i]
                local option=menu:addOption(row.id or "item"..i,2,4+i-first,clip(row.text,w-3))
                option:onActivate(function()
                    choice=row.value;if choice==nil then choice=row.id end;done=true
                end)
                nav[#nav+1]=option
            end
            if page>1 then
                local o=menu:addOption("previousPage",2,h-3,"< Previous page")
                o:onActivate(function() page=page-1;changed=true end);nav[#nav+1]=o
            end
            if first+pageSize<=#rows then
                local o=menu:addOption("nextPage",2,h-2,"> Next page")
                o:onActivate(function() page=page+1;changed=true end);nav[#nav+1]=o
            end
            local back=menu:addOption("back",2,h-1,"Back / q")
            back:onActivate(function() done=true end);nav[#nav+1]=back
            for i,o in ipairs(nav) do
                if i>1 then o:bind(keyboard.keys.up,nav[i-1].name) end
                if i<#nav then o:bind(keyboard.keys.down,nav[i+1].name) end
            end
            if default then menu:setSelected(default) end
            menu:draw(true)
            while running and not done and not changed do
                local _,_,_,key=event.pull(0.25,"key_down")
                if key==keyboard.keys.q then return nil end
                if key then menu:handleEvent(key);menu:draw() end
            end
            if not running then return nil end
            if done then return choice end
        end
    end
    local function input(prompt,default)
        if not running then return nil end
        term.clear();gpu.set(2,2,clip(prompt..(default and " ["..default.."]" or ""),w-3))
        local menu=qmenu.create();menu:draw()
        local value=menu:read(2,4,math.max(1,w-4))
        if not running then return nil end
        if value=="" then value=default end
        return value
    end
    local function message(text)
        print(text);pick(tostring(text),{{id="ok",text="Continue"}})
    end
    local function details(title,lines)
        local rows={}
        for i,line in ipairs(lines) do
            -- Wrap long explanations into paged rows instead of clipping them.
            local remaining=tostring(line)
            repeat
                local part=clip(remaining,math.max(4,w-4))
                rows[#rows+1]={id="line"..#rows+1,text=part}
                remaining=remaining:sub(#part+1)
            until remaining==""
        end
        while running and pick(title,rows) do end
    end
    local function confirm(text)
        return pick(text,{{id="yes",text="Yes"},{id="no",text="No"}},"no")=="yes"
    end
    local function selectName(lib,title)
        local names,err=lib.list();if not names then message(err);return nil end
        local rows={};for i,name in ipairs(names) do rows[i]={id="item"..i,text=name,value=name} end
        return pick(title,rows)
    end
    local function outcome(result)
        require("craft_commands").report(result,options)
        local text=result.status..": "..tostring(result.message or "")
        if result.status=="unknown" then text=text.."; check storage before retrying." end
        if result.partial then text=text.."; "..result.completedEntries.." component(s) completed." end
        if result.cleanupError then text=text.."; "..result.cleanupError end
        if result.persistenceError then text=text.."; "..result.persistenceError end
        for _,line in ipairs(require("craft_commands").receiptLines(result)) do print(line) end
        if result.jobId and result.serverAddress then lastJob=result end
        for _,entry in ipairs(result.entries or {}) do if entry.jobId and entry.serverAddress then lastJob=entry end end
        message(text)
    end
    local runOptions={};for k,v in pairs(options) do runOptions[k]=v end
    runOptions.shouldContinue=function() return running end
    runOptions.onMessage=print
    local function executionOptions(overrides)
        local o={};for k,v in pairs(runOptions) do o[k]=v end
        for k,v in pairs(overrides or {}) do o[k]=v end
        return o
    end
    local plans=require "craft_plans"
    local function previewPlan(p)
        local lines,err=require("craft_preview").lines(p)
        if not lines then message(err);return end
        details("Plan preview (recorded costs)",lines)
    end
    local function calculationChoice(y)
        local selected
        if y[1]=="select_recipe" then
            local rows={}
            for i,recipe in ipairs(y[3]) do
                rows[#rows+1]={id="recipe"..i,text="Recipe "..i..": "..require("serialization").serialize(recipe),value=recipe}
            end
            rows[#rows+1]={id="terminal",text="External material only (do not manufacture)",value=false}
            selected=pick("Choose route for "..y[2],rows)
        elseif y[1]=="skip_inventory_check" then
            selected=pick("Stock policy for "..y[2],{
                {id="stock",text="Allow stock (origin materials may be unknown)",value=false},
                {id="make",text="Always manufacture using the chosen route",value=true}})
        elseif y[1]=="select_oredict" then
            local names,seen={},{}
            local function add(n) if not seen[n] then seen[n]=true;names[#names+1]=n end end
            for _,name in ipairs(y[3]) do add(name) end
            for _,wildcard in ipairs(y[3].wildcards or {}) do
                local _,slots=y[6]:countItemByName(wildcard)
                for _,slot in ipairs(slots) do add(require("item_identity").stackName(y[6]:getItemInSlot(slot))) end
                if #slots==0 then add(wildcard:gsub(":%*%s*$","")) end
            end
            local rows={};for i,name in ipairs(names) do rows[i]={id="item"..i,text=name,value=name} end
            selected=pick("Lock ingredient for "..y[2],rows)
        end
        if selected==nil then error("Crafting calculation cancelled.") end
        return selected
    end
    local function createPlan()
        local item=input("Item ID to craft");if not item then return end
        local qty=input("Quantity","1");if not qty then return end
        local plan,err=require("craft_commands").calculatePlan(item,qty,runOptions,calculationChoice)
        if not plan then message(err);return end
        print("Cost: "..require("serialization").serialize(plan.inventory_needed))
        print("Tools: "..require("serialization").serialize(plan.tool_stock or {}))
        local choice
        repeat
            choice=pick("Calculated plan: "..item,{
            {id="preview",text="Explain this plan"},
            {id="save",text="Save only"},{id="saveRun",text="Save and execute"},
            {id="run",text="Execute without saving"}})
            if choice=="preview" then previewPlan(plan) end
        until choice~="preview" or not running
        if not choice then return end
        if choice=="save" or choice=="saveRun" then
            local label=input("Plan label");if not label then return end
            local saved,problem=plans.save(label,plan);if not saved then message(problem);return end
        end
        if choice=="run" or choice=="saveRun" then outcome(plans.run(plan,runOptions)) end
    end
    local function editPlan(name)
        local original,err=plans.load(name);if not original then message(err);return false end
        if not original.blueprint then message("Legacy snapshot: explicitly capture choices in a new plan before editing.");return false end
        local draft=original
        while running do
            local rows={}
            local ids={};for id in pairs(draft.blueprint.nodes) do ids[#ids+1]=id end;table.sort(ids)
            for _,id in ipairs(ids) do rows[#rows+1]={id="node"..#rows+1,text="["..id.."] "..draft.blueprint.nodes[id].item,value=id} end
            rows[#rows+1]={id="review",text="Review differences / save",value={review=true}}
            local selected=pick("Edit captured branch (shared references change together)",rows)
            if not selected then return false end
            if type(selected)=="table" then
                details("Before -> candidate",assert(require("craft_preview").diff(original,draft)))
                if confirm("Save candidate over "..name.."?") then
                    local saved,why=plans.save(name,draft);message(saved and "Edited plan saved." or why);return saved or false
                end
            else
                local n=draft.blueprint.nodes[selected]
                local action=pick("Edit ["..selected.."] "..n.item,{
                    {id="stock",text="Change intermediate stock policy"},
                    {id="recipe",text="Replace recipe (capture its dependencies)"},
                    {id="material",text="Change an allowed ingredient material"}})
                local change={node=selected,kind=action}
                if action=="stock" then
                    local policy=pick("Stock policy (root requests always manufacture)",{
                        {id="allow",text="Use existing stock first"},{id="make",text="Manufacture rather than borrow"}})
                    if policy then change.useStock=policy=="allow" else change=nil end
                elseif action=="recipe" then
                    local all,why=require("craft_edit").recipes(n.item)
                    if not all then message(why or "No recipes.");change=nil else
                        local recipes={};for i,r in ipairs(all) do recipes[#recipes+1]={id="recipe"..i,text="Recipe "..i..": "..require("serialization").serialize(r),value=r} end
                        recipes[#recipes+1]={id="terminal",text="External input only",value=false}
                        change.recipe=pick("Choose replacement recipe",recipes)
                        if change.recipe==nil then change=nil end
                    end
                elseif action=="material" then
                    local slots={};for slot,item in pairs(n.recipe or {}) do slots[#slots+1]={id="slot"..slot,text=slot..": "..item,value=slot} end
                    change.slot=pick("Ingredient slot",slots)
                    if change.slot then change.item=input("Allowed replacement item ID") else change=nil end
                    if change and not change.item then change=nil end
                else change=nil end
                if change then
                    local candidate,diff=require("craft_edit").candidate(draft,change,runOptions,calculationChoice)
                    if candidate then details("Recalculated candidate",diff);draft=candidate
                    else message(diff) end
                end
            end
        end
        return false
    end
    local function planMenu(name)
        local changed=false
        while running do
            local choice=pick("Plan: "..name,{{id="run",text="Execute"},{id="preview",text="Explain recorded plan"},
                {id="edit",text="Edit choices / recalculate / review"},{id="receipt",text="Query a robot job receipt"},
                {id="copy",text="Copy to another label"},{id="delete",text="Delete"}})
            if not choice then return changed end
            if choice=="run" then
                local accounting=pick("Accounting",{{id="saved",text="Saved operations and costs"},{id="refresh",text="Refresh amounts within locked choices"}},"saved")
                if accounting and confirm("Execute "..name.."?") then
                    outcome(plans.run(name,executionOptions({accounting=accounting})))
                end
            elseif choice=="preview" then
                local p,why=plans.load(name);if p then previewPlan(p) else message(why) end
            elseif choice=="edit" then changed=editPlan(name) or changed
            elseif choice=="receipt" then
                local address=input("Original robot address",lastJob and lastJob.serverAddress)
                local id=address and input("Job ID",lastJob and lastJob.jobId)
                if id then
                    local r=plans.query(address,id,runOptions)
                    message(r.status..": "..tostring(r.message or "").." (query only; no craft submitted)")
                end
            elseif choice=="copy" then
                local label=input("New plan label");if label then
                    local p,err=plans.load(name);local saved,why
                    if p then saved,why=plans.save(label,p) end
                    changed=changed or saved or false
                    message(saved and "Plan copied." or err or why or "Copy failed.")
                end
            elseif choice=="delete" and confirm("Delete "..name.."?") then
                local removed,err=plans.remove(name);message(removed and "Plan deleted." or err);if removed then return true end
            end
        end
    end
    local function plansMenu()
        if options.new then createPlan() end
        local names,err=plans.list();if not names then message(err);return end
        while running do
            local rows={{id="new",text="Create a plan"}}
            for i,name in ipairs(names) do rows[#rows+1]={id="plan"..i,text=name,value={name=name}} end
            local choice=pick("Craft Plans",rows);if not choice then return end
            local changed
            if choice=="new" then createPlan();changed=true else changed=planMenu(choice.name) end
            if changed then names,err=plans.list();if not names then message(err);return end end
        end
    end
    local function toolsMenu()
        local tools=require "craft_tools"
        local function edit(item,profile,hint)
            local durability=input("Maximum durability",tostring(profile and profile.durability or hint or 1));if not durability then return end
            local wear=input("Durability per operation per tool slot",tostring(profile and profile.durabilityPerUse or 1));if not wear then return end
            local saved,err=tools.set(item,tonumber(durability),tonumber(wear));message(saved and "Tool profile saved." or err)
        end
        while running do
            local profiles=tools.list();local names={};for name in pairs(profiles) do names[#names+1]=name end;table.sort(names)
            local rows={{id="register",text="Enter an item name"},{id="fromStock",text="Select an item from storage"}}
            for i,name in ipairs(names) do
                local p=profiles[name];rows[#rows+1]={id="tool"..i,text=name.." ("..p.durability..", wear "..p.durabilityPerUse..")",value=name}
            end
            local choice=pick("Tool Profiles",rows);if not choice then return end
            if choice=="register" then local name=input("Tool item ID");if name then edit(name,tools.get(name)) end
            elseif choice=="fromStock" then
                local inventory=plans.inventory(options);local items,seen={},{}
                for _,s in inventory:iter() do
                    if s.size>0 and not seen[s.name] then
                        seen[s.name]=true;items[#items+1]={id="item"..(#items+1),text=s.name,value=s}
                    end
                end
                local stack=pick("Select item to flag as reusable",items)
                if stack then edit(stack.name,tools.get(stack.name),stack.maxDamage and stack.maxDamage>0 and stack.maxDamage or nil) end
            else
                local action=pick(choice,{{id="edit",text="Edit durability/wear"},{id="delete",text="Remove profile"}})
                if action=="edit" then edit(choice,profiles[choice])
                elseif action=="delete" and confirm("Remove profile "..choice.."?") then
                    local removed,err=tools.remove(choice);message(removed and "Profile removed." or err)
                end
            end
        end
    end
    local function kitsMenu()
        local kits=require "craft_kits"
        local function entry()
            local name=selectName(plans,"Select component plan");if not name then return nil end
            local binding=pick("Binding for "..name,{{id="live",text="Live: follow source plan edits"},{id="pinned",text="Pinned: embed current copy"}},"live")
            if not binding then return nil end
            if binding=="pinned" then return assert(kits.pin(name)) end
            return {binding="live",planName=name}
        end
        while running do
            local names,err=kits.list();if not names then message(err);return end
            local rows={{id="new",text="Create kit"}}
            for i,name in ipairs(names) do rows[#rows+1]={id="kit"..i,text=name,value={name=name}} end
            local selected=pick("Craft Kits",rows);if not selected then return end
            if selected=="new" then
                local label=input("Kit label");if label then
                    local first=entry();if first then
                        local saved,problem=kits.save(label,{entries={first},executionMode="separate",accounting="saved"})
                        message(saved and "Kit created; select it to add components or change defaults." or problem)
                    end
                end
            else
                local name=selected.name
                local editing=true
                while running and editing do
                    local kit,problem=kits.load(name);if not kit then message(problem);break end
                    local actions={{id="run",text="Execute"},{id="add",text="Add component"},
                        {id="defaults",text="Save defaults ("..kit.executionMode..", "..kit.accounting..")"},
                        {id="copy",text="Copy kit"},{id="delete",text="Delete kit"}}
                    for i,e in ipairs(kit.entries) do
                        actions[#actions+1]={id="entry"..i,text=i..": ["..e.binding.."] "..(e.planName or e.sourceName or "Embedded plan"),value=i}
                    end
                    local action=pick("Kit: "..name,actions)
                    if not action then editing=false
                    elseif action=="run" or action=="defaults" then
                        local mode=pick("Execution mode",{{id="separate",text="Separate jobs"},{id="merged",text="One merged multi-output job"}},options.executionMode or kit.executionMode)
                        local accounting=mode and pick("Accounting",{{id="saved",text="Replay recorded operations/costs"},
                            {id="refresh",text="Refresh within locked choices; share compatible merged work"}},options.accounting or kit.accounting)
                        if mode and accounting then
                            if action=="defaults" then
                                kit.executionMode=mode;kit.accounting=accounting
                                local saved,why=kits.save(name,kit);message(saved and "Defaults saved." or why)
                            elseif confirm("Execute "..name.." with one-run overrides?") then
                                outcome(kits.run(name,executionOptions({executionMode=mode,accounting=accounting})))
                            end
                        end
                    elseif action=="add" then
                        local e=entry();if e then kit.entries[#kit.entries+1]=e;local saved,why=kits.save(name,kit);message(saved and "Entry added." or why) end
                    elseif type(action)=="number" then
                        local e=kit.entries[action]
                        local operation=pick("["..e.binding.."] "..(e.planName or e.sourceName or "Embedded"),{
                            {id="replace",text="Replace / rebind explicitly"},{id="remove",text="Remove entry"},
                            {id="up",text="Move earlier"},{id="down",text="Move later"}})
                        local changed=false
                        if operation=="replace" then local replacement=entry();if replacement then kit.entries[action]=replacement;changed=true end
                        elseif operation=="remove" and confirm("Remove this component?") then table.remove(kit.entries,action);changed=true
                        elseif operation=="up" and action>1 then kit.entries[action],kit.entries[action-1]=kit.entries[action-1],kit.entries[action];changed=true
                        elseif operation=="down" and action<#kit.entries then kit.entries[action],kit.entries[action+1]=kit.entries[action+1],kit.entries[action];changed=true end
                        if changed then local saved,why=kits.save(name,kit);message(saved and "Entry updated." or why) end
                    elseif action=="copy" then
                        local label=input("New kit label");if label then local saved,why=kits.save(label,kit);message(saved and "Kit copied." or why) end
                    elseif action=="delete" and confirm("Delete "..name.."?") then
                        local removed,why=kits.remove(name);message(removed and "Kit deleted." or why);if removed then editing=false end
                    end
                end
            end
        end
    end
    local function stockkeeperMenu()
        local keeper=require "stockkeeper"
        local function edit(name,rule)
            rule=rule or {interval=60,trigger="replacement"}
            if not name then name=input("Stockkeeper rule label");if not name then return end end
            local kind=pick("Supplying source",{{id="plan",text="Saved plan"},{id="kit",text="Saved kit"}},rule.source and rule.source.kind or "plan")
            if not kind then return end
            local sourceName=selectName(kind=="plan" and plans or require("craft_kits"),"Select supplying "..kind)
            if not sourceName then return end
            rule.source={kind=kind,name=sourceName}
            local item=input("Exact watched output item ID",rule.item);if not item then return end
            rule.item=item
            local trigger=pick("Stock trigger",{{id="replacement",text="Replacement: wait for a full batch deficit"},
                {id="level",text="Level: run at or below the configured count"}},rule.trigger)
            if not trigger then return end
            rule.trigger=trigger
            local quantity=input(trigger=="replacement" and "Target stock quantity" or "Trigger at or below this stock count",tostring(rule.quantity or 64))
            if not quantity then return end;rule.quantity=tonumber(quantity)
            local interval=input("Check interval in seconds",tostring(rule.interval));if not interval then return end
            rule.interval=tonumber(interval)
            local reuse=pick("Intermediate stock",{{id="saved",text="Execute source as written"},
                {id="reuse",text="Use existing stock within captured choices"}},rule.useExisting and "reuse" or "saved")
            if not reuse then return end;rule.useExisting=reuse=="reuse" or nil
            for _,key in ipairs({"storageSide","port","connectTimeout","idleTimeout","discoveryTimeout","jobTimeout"}) do
                if rule[key]==nil then rule[key]=options[key] end
            end
            local saved,err=keeper.save(name,rule)
            message(saved and (rule.enabled and not rule.paused and "Rule saved; enabled checks updated." or
                "Rule saved. Enable it explicitly to start checks.") or err)
        end
        while running do
            local names,err=keeper.list();if not names then message(err);return end
            local rows={{id="new",text="Create stock rule"},{id="start",text="Restore enabled rules"},
                {id="stop",text="Disable all running rules"}}
            for i,name in ipairs(names) do rows[#rows+1]={id="rule"..i,text=name,value={name=name}} end
            local selected=pick("Stockkeeper",rows);if not selected then return end
            if selected=="new" then edit()
            elseif selected=="start" then
                local result,why=keeper.start()
                message(result and ("Started: "..result.started.."; already running: "..result.alreadyRunning..
                    "; errors: "..require("serialization").serialize(result.errors)) or why)
            elseif selected=="stop" then
                if confirm("Disable all running Stockkeeper rules?") then
                    local stopped,errors=keeper.stop();message(stopped and "Rules disabled." or require("serialization").serialize(errors))
                end
            else
                local name=selected.name
                while running do
                    local status,why=keeper.status(name);if not status then message(why);break end
                    local title="Rule: "..name.." ["..(status.paused and "UNKNOWN / paused" or status.enabled and "enabled" or "disabled").."]"
                    local actions={{id="status",text="Show configuration / last outcome"},
                        {id="enable",text=status.paused and "Resume after inspecting storage" or "Enable checks"},
                        {id="disable",text="Disable checks"},{id="check",text="Check trigger once (may execute)"},
                        {id="edit",text="Edit rule"},{id="delete",text="Delete rule"}}
                    local action=pick(title,actions);if not action then break end
                    if action=="status" then message(require("serialization").serialize(status))
                    elseif action=="enable" then
                        if not status.paused or confirm("Inspected storage and ready to permit another batch?") then
                            local enabled,problem
                            if status.paused then enabled,problem=keeper.resume(name) else enabled,problem=keeper.enable(name) end
                            message(enabled and "Checks enabled; they remain active after this menu closes." or problem)
                        end
                    elseif action=="disable" then
                        local disabled,problem=keeper.disable(name);message(disabled and "Checks disabled. An already-running job is not cancelled." or problem)
                    elseif action=="check" and confirm("Check and execute a full batch if the trigger is met?") then
                        outcome(keeper.check(name,executionOptions()))
                    elseif action=="edit" then edit(name,status.rule)
                    elseif action=="delete" and confirm("Delete rule "..name.."?") then
                        local removed,problem=keeper.remove(name);message(removed and "Rule deleted." or problem);if removed then break end
                    end
                end
            end
        end
    end
    event.listen("interrupted",interrupted)
    local ok,err=xpcall(function()
        tty.setViewport(w,h,0,0)
        if kind=="preview" then previewPlan(assert(options.plan))
        elseif kind=="tools" then toolsMenu() elseif kind=="plans" then plansMenu() elseif kind=="kits" then kitsMenu()
        elseif kind=="stockkeeper" then stockkeeperMenu() else error("Unknown management view.") end
    end,debug.traceback)
    local restored,restoreError=pcall(tty.setViewport,table.unpack(viewport))
    local ignored,ignoreError=pcall(event.ignore,"interrupted",interrupted)
    if not ok then return 2,tostring(err) end
    if not restored then return 2,"Viewport restore failed: "..tostring(restoreError) end
    if not ignored then return 2,"Listener cleanup failed: "..tostring(ignoreError) end
    return 0
end
return ui
