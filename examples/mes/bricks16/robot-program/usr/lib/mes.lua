-- Headless manufacturing coordinator. Warehouse jobs own all physical movement.
local M = {}
local identity = require "item_identity"
local event = require "event"
local computer = require "computer"
local busy, current = false, {status="idle", stages={}}
local crafterState={}
local function copy(t)
  if type(t)~="table" then return t end
  local out={}; for k,v in pairs(t) do out[k]=copy(v) end; return out
end
local function sorted(t) local out={};for k in pairs(t) do out[#out+1]=k end;table.sort(out);return out end
local function positive(n) return type(n)=="number" and n>0 and n<math.huge and n%1==0 end
local function concrete(id)
  return type(id)=="string" and id:match("^[^:]+:[^:]+:?[0-9]*$") and
    id~="minecraft:air" and not id:find("*",1,true) and not id:find(" | ",1,true) and id:sub(1,4)~="ore:"
end
local function item(id)
  id=identity.canonical(id)
  local name,damage=id:match("^(.*):(%d+)$")
  return {name=name or id,damage=tonumber(damage) or 0}
end
local function config(opts)
  if opts and opts.config then return opts.config end
  local f=assert(io.open("/etc/mes.cfg","r"),"Cannot read /etc/mes.cfg")
  local text=f:read("*a");f:close()
  return assert(require("serialization").unserialize(text),"Invalid /etc/mes.cfg")
end
function M.status() return copy(current) end
function M.crafters(opts)
  local out=copy(config(opts).crafters or {})
  local groups=require("warehouse").groups("crafter")
  for name,c in pairs(out) do c.buffer=groups[name] and groups[name].roles.buffer;c.status=crafterState[name] or "idle" end
  return out
end
function M.types(opts) return copy(config(opts).machineTypes or {}) end
function M.importRecipes(db) return require("recipes").install(db) end
function M.importProcessingRecipe(id,kind,recipe)
  return require("recipes").registerProcessingRecipe(id,kind,recipe)
end
local function stockSnapshot()
  local wh=require "warehouse"
  local members=wh.members()
  local grouped,groupKeys={},{}
  for _,g in pairs(wh.groups()) do for _,s in pairs(g.roles) do
    grouped[s]=true;groupKeys[(members[s] or {}).inventory or s]=true
  end end
  local stacks,seen={},{}
  for _,s in ipairs(sorted(members)) do
    local settings=members[s];local key=settings.inventory or s
    if not grouped[s] and not groupKeys[key] and not seen[key] then
      seen[key]=true
      for _,v in pairs((wh.contents(s) or {}).items or {}) do
        if v.count>0 then stacks[#stacks+1]={name=v.item.name,damage=v.item.damage or 0,size=v.count,maxSize=v.maxSize or 64} end
      end
    end
  end
  return assert(require("inventory").new({getAllStacks=function()
    return {getAll=function() return stacks end}
  end},0))
end
function M.plan(id,qty,opts)
  opts=opts or {}
  local ok,p,err=pcall(function()
    assert(positive(qty),"Quantity must be a positive integer")
    local snapshot=require("craft_plans").inventory{inventory=stockSnapshot()}
    local all={};for i=1,snapshot:getInventorySize() do all[i]=snapshot:getItemInSlot(i) end
    local planner=require "craftingv4_4"
    local result=planner.calculateCraftingPlan(identity.canonical(id),qty,
      {getAllStacks=function() return {getAll=function() return all end} end},0,true,{toolProfiles=opts.toolProfiles})
    while result.yield_data do
      local choice
      if opts.selectChoice then choice=opts.selectChoice(result.yield_data) end
      planner.resumeCalculation(result,choice)
    end
    if not result.success then return nil,result.error end
    if not result.craftable then return nil,"Missing inputs",result end
    return result
  end)
  if not ok then return nil,tostring(p) end
  return p,err
end

-- Prefix deficits, rather than just final balance, preserve task ordering.
function M.robotPlan(plan,first,last,inventory)
  local sub={success=true,craftable=true,tasks={},inventory_needed={},requestOutputs={},tools=copy(plan.tools or {}),tool_stock={}}
  local balance,usedTools,manufacturedTools={},{},{}
  for i=first,last do
    local t=copy(plan.tasks[i]);t.node=nil;t.input_nodes=nil
    sub.tasks[#sub.tasks+1]=t
    local ops=t.qty_produced/t.recipeOutput
    for slot,id in pairs(t.recipe) do
      id=identity.canonical(id)
      if id~="minecraft:air" then
        if (t.tool_slots or {})[slot] then usedTools[id]=true
        else
          local deficit=math.max(0,ops-(balance[id] or 0))
          sub.inventory_needed[id]=(sub.inventory_needed[id] or 0)+deficit
          balance[id]=(balance[id] or 0)+deficit-ops
        end
      end
    end
    local id=identity.canonical(t.item);balance[id]=(balance[id] or 0)+t.qty_produced
    local family=require("craft_tool_rules").family(id)
    if sub.tools[family] then manufacturedTools[family]=true end
  end
  for id,n in pairs(balance) do
    local net=n-(sub.inventory_needed[id] or 0)
    if net>0 then sub.requestOutputs[id]=net end
  end
  for id in pairs(usedTools) do
    if manufacturedTools[id] then
      return nil,"Unsupported stage-tool contract: a tool is manufactured and reused in the same robot stage ("..id.."); fresh-output protection needs branch-aware tool accounting"
    end
    if (plan.tool_stock or {})[id] then sub.tool_stock[id]=copy(plan.tool_stock[id]) end
  end
  for id,n in pairs(sub.inventory_needed) do if n==0 then sub.inventory_needed[id]=nil end end
  local withdrawals={}
  if inventory and next(usedTools) then
    -- Rebudget tools at every barrier: returned tools may now have different
    -- metadata, and tools manufactured by an earlier stage are warehouse stock.
    local reserved=copy(sub.inventory_needed)
    local pool=require("craft_tool_budget").new(inventory,sub.tools,false,reserved)
    for _,t in ipairs(sub.tasks) do
      local slots={}
      for _,family in pairs(t.tool_slots or {}) do slots[family]=(slots[family] or 0)+1 end
      for family,n in pairs(slots) do
        local missing=pool.charge(family,n,t.qty_produced/t.recipeOutput,family,true)
        if missing>0 then return nil,"Insufficient stage tool wear budget: "..family end
      end
    end
    local _,stock=pool.snapshot();sub.tool_stock=stock
    for exact,n in pairs(reserved) do
      local toolCount=n-(sub.inventory_needed[exact] or 0)
      if toolCount>0 then withdrawals[exact]=toolCount end
    end
  else
    for family,units in pairs(sub.tool_stock) do withdrawals[family]=#units end
  end
  local valid,err=require("craft_plan").validate(sub)
  if not valid then return nil,err end
  local flow,problem=require("craft_plan").validateFlow(sub)
  if not flow then return nil,problem end
  return sub,nil,withdrawals
end

local function wait(id,why,opts)
  assert(id,why or "Warehouse job submission failed")
  local logistics=require "logistics"
  local wh=require "warehouse"
  while true do
    local s=assert(logistics.status(id),"Missing logistics job "..tostring(id))
    local terminal=s.state=="done" or s.state=="failed" or s.state=="partial"
    if terminal and (not wh.settled or wh.settled(id)==true) then
      if s.state=="done" then return s end
      error(s.reason or ("Logistics "..s.state),0)
    end
    event.pull(opts.pollSeconds or 0.2)
  end
end
local function scan(s,opts)
  local wh=require "warehouse"
  for _,id in ipairs(wh.scan(s)) do wait(id,nil,opts) end
  return wh.contents(s) or {items={}}
end
local function count(contents,id)
  local n=0;for _,v in pairs(contents.items or {}) do if identity.stackName(v.item)==identity.canonical(id) then n=n+v.count end end;return n
end
local function move(stage,kind,id,n,s,opts)
  if n<=0 then return end
  local record={kind=kind,item=identity.canonical(id),quantity=n,storage=s,status="pending"}
  stage.itemsMoved[#stage.itemsMoved+1]=record
  local job,err=require("warehouse")[kind](item(id),n,s,opts.logistics)
  record.job=job
  local ok,result=pcall(wait,job,err,opts)
  local ledger=job and require("logistics").status(job)
  if ledger then
    record.moved=ledger.moved;record.taken=ledger.taken;record.returned=ledger.returned
    record.held=copy(ledger.held);record.status=ledger.state;record.reason=ledger.reason
  else record.status="failed";record.moved=0;record.reason=err end
  if not ok then error(result,0) end
  record.status="complete"
end
local function robot(stage,plan,first,last,cfg,opts)
  local sub,problem,toolWithdrawals=M.robotPlan(plan,first,last,stockSnapshot())
  assert(sub,problem)
  local crafters=M.crafters{config=cfg};local name
  for _,candidate in ipairs(opts.crafter and {opts.crafter} or sorted(crafters)) do
    local c=assert(crafters[candidate],"Unknown crafter "..tostring(candidate))
    local idle=c.status=="idle"
    if opts.isCrafterIdle then idle=opts.isCrafterIdle(candidate,copy(c))==true end
    if idle then name=candidate;break end
  end
  assert(name,"No idle crafter")
  local c=assert(crafters[name],"No configured crafter")
  assert(c.buffer and c.robot,"Crafter needs a robot and warehouse buffer")
  stage.crafter=name;stage.locations={c.buffer};crafterState[name]="busy"
  -- A dirty station is unsafe: cproc must receive only this run's inputs.
  local before=scan(c.buffer,opts)
  for _,v in pairs(before.items) do assert(v.count==0,"Crafter buffer is not empty") end
  local needed=copy(sub.inventory_needed)
  for id,n in pairs(toolWithdrawals) do needed[id]=(needed[id] or 0)+n end
  for _,id in ipairs(sorted(needed)) do move(stage,"fetch",id,needed[id],c.buffer,opts) end
  stage.submitted=true
  local clientOpts=copy(opts.client or {});clientOpts.serverAddress=c.robot
  local result=require("craft_client").runDetailed(sub,clientOpts)
  stage.receipt=result;stage.status=result.status
  if result.status~="complete" then error(result.message or "Robot did not complete",0) end
  for _,v in pairs(scan(c.buffer,opts).items) do
    if v.count>0 then move(stage,"store",identity.stackName(v.item),v.count,c.buffer,opts) end
  end
end
local function machine(stage,t,cfg,opts,plan)
  local kind=assert(t.machineType,"Processing task has no machine type")
  local mt=assert((cfg.machineTypes or {})[kind],"Unknown machine type "..kind)
  assert(positive(mt.batch) and type(mt.seconds)=="number" and mt.seconds>=0 and mt.seconds<math.huge,"Invalid batch/deadline configuration")
  assert(type(mt.inputs)=="table" and #mt.inputs>0 and mt.output,"Machine input/output roles required")
  local available=require("warehouse").groups(kind)
  local selection=(opts.machines or {})[kind]
  local names=selection
  if selection==nil or selection=="any" then names=sorted(available) end
  if type(names)=="string" then names={names} end
  assert(type(names)=="table" and #names>0,"No machine groups")
  stage.groups=copy(names);stage.locations={};local seen={}
  for _,name in ipairs(names) do
    assert(not seen[name],"Duplicate machine group");seen[name]=true
    local g=assert(available[name],"Unknown machine group "..tostring(name))
    for _,s in pairs(g.roles) do stage.locations[#stage.locations+1]=s end
    assert(g.roles[mt.output],"Missing output role")
  end
  -- Captured planner tasks omit input_quantities; the blueprint retains them.
  local quantities=t.input_quantities or
    (plan.blueprint and plan.blueprint.nodes[t.node] and plan.blueprint.nodes[t.node].input_quantities) or {}
  local slots=sorted(t.recipe);local perOp=0
  for _,slot in ipairs(slots) do
    if t.recipe[slot]~="minecraft:air" then
      assert(positive(quantities[slot] or 1),"Machine ingredient quantities must be positive integers")
      perOp=perOp+(quantities[slot] or 1)
    end
  end
  assert(perOp>0 and perOp<=mt.batch,"Recipe inputs exceed machine load batch")
  local operations=t.qty_produced/t.recipeOutput
  local capacity=math.floor(mt.batch/perOp);local stop=false;local failures={}
  local function worker(index,name)
    local ok,err=pcall(function()
      local roles=available[name].roles
      local left=math.floor(operations/#names)+(index<=operations%#names and 1 or 0)
      while left>0 and not stop do
        local ops=math.min(left,capacity);local inputs=ops*perOp
        local pending={}
        local order=0
        for _,slot in ipairs(slots) do
          local id=t.recipe[slot]
          if id~="minecraft:air" then
            order=order+1
            local role=mt.inputs[math.min(order,#mt.inputs)]
            local s=assert(roles[role],"Missing input role "..tostring(role))
            pending[s]=pending[s] or {};pending[s][id]=(pending[s][id] or 0)+ops*(quantities[slot] or 1)
          end
        end
        local output=roles[mt.output]
        assert(count(scan(output,opts),t.item)==0,"Machine output is not empty")
        -- Fuel is prepared first so fast machines cannot consume unfuelled loads.
        if mt.fuel then
          assert(type(mt.fuel.per)=="number" and mt.fuel.per>0,"Invalid fuel ratio")
          local s=assert(roles[mt.fuel.role],"Missing fuel role")
          local held=count(scan(s,opts),mt.fuel.item)
          move(stage,"fetch",mt.fuel.item,math.max(0,math.ceil(inputs/mt.fuel.per)-held),s,opts)
        end
        for _,s in ipairs(sorted(pending)) do for _,id in ipairs(sorted(pending[s])) do move(stage,"fetch",id,pending[s][id],s,opts) end end
        local deadline=computer.uptime()+inputs*mt.seconds*2+60
        while count(scan(output,opts),t.item)<ops*t.recipeOutput do
          assert(computer.uptime()<deadline,"Machine output deadline exceeded: "..name)
          event.pull(opts.machinePollSeconds or 2)
        end
        move(stage,"store",t.item,ops*t.recipeOutput,output,opts)
        left=left-ops
      end
    end)
    if not ok then stop=true;failures[#failures+1]=name..": "..tostring(err) end
  end
  if #names==1 then worker(1,names[1])
  else
    local thread=require "thread";local workers={}
    for i,name in ipairs(names) do workers[#workers+1]=thread.create(worker,i,name) end
    for _,w in ipairs(workers) do w:join() end
  end
  if #failures>0 then error(table.concat(failures,"; "),0) end
end
function M.run(plan,opts)
  if busy then return nil,"busy" end
  busy=true;opts=opts or {};current={status="running",stages={}}
  local active
  local ok,err=pcall(function()
    if type(plan)=="string" then
      if plan:find("/",1,true) or plan:sub(-5)==".plan" then
        local f=assert(io.open(plan,"r"));local text=f:read("*a");f:close()
        plan=assert(require("serialization").unserialize(text),"Invalid saved plan")
      else plan=assert(require("craft_plans").load(plan)) end
    end
    assert(type(plan)=="table" and type(plan.tasks)=="table" and plan.success~=false and plan.craftable~=false,"Invalid plan")
    local taskCount=0
    for index,t in pairs(plan.tasks) do
      taskCount=taskCount+1
      assert(positive(index) and index<=#plan.tasks and type(t)=="table" and concrete(t.item) and
        positive(t.qty_produced) and positive(t.recipeOutput) and t.qty_produced%t.recipeOutput==0 and
        type(t.recipe)=="table" and next(t.recipe),"Invalid task")
      assert(t.isProcessing==nil or type(t.isProcessing)=="boolean","Invalid processing flag")
      assert(t.machineType==nil or (type(t.machineType)=="string" and #t.machineType>0),"Invalid machine type")
      for slot,id in pairs(t.recipe) do
        assert(positive(slot) and (id=="minecraft:air" or concrete(id)),"Invalid recipe ingredient")
      end
    end
    assert(taskCount==#plan.tasks,"Sparse task list")
    local cfg=config(opts);local i=1
    while i<=#plan.tasks do
      local t=plan.tasks[i]
      assert(type(t)=="table" and positive(t.qty_produced) and positive(t.recipeOutput) and t.qty_produced%t.recipeOutput==0 and type(t.recipe)=="table","Invalid task")
      local processing=t.isProcessing or t.machineType
      active={kind=processing and "machine" or "robot",status="running",itemsMoved={},firstTask=i}
      current.stages[#current.stages+1]=active
      event.push("mes","stage",#current.stages,copy(active))
      if opts.onStage then opts.onStage(copy(active),#current.stages) end
      if processing then machine(active,t,cfg,opts,plan);i=i+1
      else
        local last=i
        while last<#plan.tasks and not (plan.tasks[last+1].isProcessing or plan.tasks[last+1].machineType) do last=last+1 end
        robot(active,plan,i,last,cfg,opts);i=last+1
      end
      active.status="complete";event.push("mes","stage",#current.stages,copy(active))
      if active.crafter then crafterState[active.crafter]=nil end
    end
    current.status="complete"
  end)
  if not ok then
    current.status=active and (active.status=="unknown" or (active.submitted and not active.receipt)) and "unknown" or "failed"
    current.error=tostring(err)
    if active then
      active.status=current.status;active.error=current.error;active.remaining={}
      if active.crafter then crafterState[active.crafter]=current.status=="unknown" and "unknown" or nil end
      for _,s in ipairs(active.locations or {}) do
        local scanned,scanError=pcall(scan,s,opts)
        local readable,contents=pcall(require("warehouse").contents,s)
        active.remaining[s]={contents=readable and contents or nil,verified=scanned and readable and contents~=nil,
          unknown=not (scanned and readable and contents~=nil),
          error=not scanned and tostring(scanError) or not readable and tostring(contents) or nil}
      end
      event.push("mes","stage",#current.stages,copy(active))
    end
  end
  busy=false;event.push("mes","done",current.status)
  return copy(current)
end
return M
