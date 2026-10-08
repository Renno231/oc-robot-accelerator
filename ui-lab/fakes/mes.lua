-- UI-lab fake of mes.lua implementing the T11 API contract with canned plans
-- and timer-driven runs.
local event=require("event");local computer=require("computer")
local wh=require("warehouse")
local M={}
local function copy(t) if type(t)~="table" then return t end;local o={};for k,v in pairs(t) do o[k]=copy(v) end;return o end
local types={furnace={roles={"input","fuel","output"},inputs={"input"},output="output",fuel={role="fuel",item="minecraft:coal",per=8},batch=64,seconds=10}}
local crafters={cpu1={robot="7f3a91c2-55e1-4b0e-9d3c-2a6f1e0b8c44",buffer="cpu1.buf"}}
local runs={}
local function changed() event.push("mes","changed") end
function M.types() return copy(types) end
function M.crafters() return copy(crafters) end
function M.setType(name,def) assert(type(name)=="string" and name~="","type name required");assert(def.output and def.inputs and #def.inputs>0,"inputs and output required");types[name]=copy(def);changed();return true end
function M.removeType(name) types[name]=nil;changed();return true end
function M.setCrafter(name,c) assert(c.robot and c.buffer,"robot and buffer required");crafters[name]=copy(c);wh.group(name,"crafter",{buffer=c.buffer});changed();return true end
function M.removeCrafter(name) crafters[name]=nil;wh.ungroup(name);changed();return true end
function M.robots() return {{address="7f3a91c2-55e1-4b0e-9d3c-2a6f1e0b8c44",busy=false},{address="0b9e44d1-1c2d-4e3f-8a9b-7c6d5e4f3a2b",busy=true}} end
local names={"minecraft:torch","minecraft:brick_block","minecraft:brick","minecraft:coal:1","minecraft:planks","minecraft:stick",
  "minecraft:crafting_table","minecraft:chest","minecraft:furnace","minecraft:iron_ingot","minecraft:glass","minecraft:hopper",
  "minecraft:piston","minecraft:stone","minecraft:stonebrick","minecraft:iron_bars","minecraft:rail","minecraft:ladder",
  "opencomputers:material:4","opencomputers:material:7","opencomputers:material:8","opencomputers:case1","opencomputers:screen1",
  "opencomputers:keyboard","opencomputers:cpu1","opencomputers:ram1"}
function M.search(text,limit)
  local out={};text=(text or ""):lower()
  for _,n in ipairs(names) do if #out>=limit then break end;if n:lower():find(text,1,true) then out[#out+1]=n end end
  return out
end
local function have(id) local n,d=id:match("^([^:]+:[^:]+):(%d+)$");return wh.count(n and {name=n,damage=tonumber(d)} or {name=id,damage=0}) end
local function inp(id,n) return {item=id,need=n,have=have(id)} end
-- Planner choices, in craftingv4_4's order (recipe, stock policy, then each
-- slot's ingredient, then the ingredients' own nodes), with its yield_data.
local function stock()
  -- Minimal InventoryCache: what select_oredict's wildcard expansion reads.
  local slots={};for _,e in ipairs(wh.totals()) do slots[#slots+1]=e.item end
  return {countItemByName=function(_,n)
      local base=n:gsub(":%*%s*$","");local at,total={},0
      for k,i in ipairs(slots) do if i.name==base then at[#at+1]=k;total=total+wh.count(i) end end
      return total,at
    end,
    getItemInSlot=function(_,k) local i=slots[k];return {name=i.name,damage=i.damage,size=wh.count(i)} end}
end
local recipes={
  ["minecraft:torch"]={{[2]="minecraft:coal",[5]="minecraft:stick",qty=4},{[2]="minecraft:coal:1",[5]="minecraft:stick",qty=4}},
  ["minecraft:stick"]={{[2]="ore:plankWood",[5]="ore:plankWood",qty=4}},
  ["minecraft:planks"]={{[5]="ore:logWood",qty=4}},
  ["minecraft:coal:1"]={{[1]="ore:logWood,1",isProcessing=true,machineType="furnace",qty=1}},
  ["minecraft:brick_block"]={{[1]="minecraft:brick",[2]="minecraft:brick",[4]="minecraft:brick",[5]="minecraft:brick",qty=1}},
  ["minecraft:brick"]={{[1]="minecraft:clay_ball,1",isProcessing=true,machineType="furnace",qty=1}},
}
local ore={["ore:plankWood"]={"minecraft:planks","minecraft:planks:1","minecraft:planks:2","minecraft:planks:3","minecraft:planks:4","minecraft:planks:5",wildcards={}},
  ["ore:logWood"]={"minecraft:log","minecraft:log:1",wildcards={"minecraft:log2:*"}}}
local function choose(item,opts)
  local inv,seen,todo,picked=stock(),{},{item},{}
  while #todo>0 do
    local name=table.remove(todo)
    if not seen[name] and recipes[name] then seen[name]=true
      local chosen=opts.selectChoice({"select_recipe",name,recipes[name],inv})
      if chosen==nil then chosen=recipes[name][1] end
      picked[name]=chosen
      if chosen then
        opts.selectChoice({"skip_inventory_check",name,chosen})
        local slots={};for k in pairs(chosen) do if type(k)=="number" then slots[#slots+1]=k end end;table.sort(slots)
        for _,k in ipairs(slots) do
          local original=chosen[k]:match("^(.-),[%d%.]+$") or chosen[k]
          local candidates=ore[original] or {original,wildcards={}}
          local specific=opts.selectChoice({"select_oredict",original,candidates,chosen,k,inv}) or candidates[1]
          todo[#todo+1]=specific
        end
      end
    end
  end
  return picked
end
function M.plan(item,qty,opts)
  opts=opts or {}
  if opts.selectChoice then
    local ok,err=pcall(choose,item,opts);if not ok then return nil,tostring(err) end
  end
  local p={item=item,qty=qty,tasks={},missing={}}
  if item=="minecraft:torch" then
    local n=math.ceil(qty/4)
    p.stages={
      {kind="robot",crafter=nil,tasks={{item="minecraft:planks",qty=4},{item="minecraft:stick",qty=n}},inputs={inp("minecraft:log",1)},outputs={{item="minecraft:stick",qty=n}}},
      {kind="machine",machineType="furnace",loads=1,groups="any",inputs={inp("minecraft:log",n)},outputs={{item="minecraft:coal:1",qty=n}},fuel=inp("minecraft:coal",math.ceil(n/8))},
      {kind="robot",crafter=nil,tasks={{item="minecraft:torch",qty=qty}},inputs={inp("minecraft:stick",n),inp("minecraft:coal:1",0)},outputs={{item="minecraft:torch",qty=qty}}},
    }
  elseif item=="minecraft:brick_block" then
    p.stages={
      {kind="machine",machineType="furnace",loads=math.ceil(qty*4/64),groups="any",inputs={inp("minecraft:clay_ball",qty*4)},outputs={{item="minecraft:brick",qty=qty*4}},fuel=inp("minecraft:coal",math.ceil(qty*4/8))},
      {kind="robot",crafter=nil,tasks={{item="minecraft:brick_block",qty=qty}},inputs={inp("minecraft:brick",qty*4)},outputs={{item="minecraft:brick_block",qty=qty}}},
    }
  else
    p.stages={{kind="robot",crafter=nil,tasks={{item=item,qty=qty}},inputs={inp("minecraft:diamond",qty*3),inp("minecraft:iron_ingot",qty*2)},outputs={{item=item,qty=qty}}}}
  end
  -- Items an earlier stage makes count as available to later stages.
  local made={}
  for _,s in ipairs(p.stages) do
    for _,i in ipairs(s.inputs) do i.have=i.have+(made[i.item] or 0) end
    for _,o in ipairs(s.outputs) do made[o.item]=(made[o.item] or 0)+o.qty end
  end
  for _,s in ipairs(p.stages) do
    for _,i in ipairs(s.inputs) do if i.have<i.need then p.missing[#p.missing+1]={item=i.item,need=i.need,have=i.have} end end
    if s.fuel and s.fuel.have<s.fuel.need then p.missing[#p.missing+1]={item=s.fuel.item,need=s.fuel.need,have=s.fuel.have} end
  end
  return p
end
function M.choose(plan,i,choice)
  local s=assert(plan.stages[i],"no such stage")
  if s.kind=="machine" then
    if type(choice)=="string" and choice~="any" then assert(wh.groups(s.machineType)[choice],"no "..s.machineType.." named "..choice) end
    s.groups=choice
  else assert(crafters[choice],"no crafter "..tostring(choice));s.crafter=choice end
  return true
end
local busy
function M.run(plan)
  if busy then return nil,"busy" end
  if #plan.missing>0 then return nil,"missing inputs" end
  local id=#runs+1;local r={id=id,item=plan.item,qty=plan.qty,status="running",stage=1,started=computer.uptime(),stages={}}
  for k,s in ipairs(plan.stages) do r.stages[k]={kind=s.kind,state="waiting",done=0,total=s.outputs[1].qty,detail="",crafter=s.crafter or (s.kind=="robot" and "cpu1") or nil,groups=s.kind=="machine" and (s.groups=="any" and {"furnaceA","furnaceB"} or s.groups) or nil} end
  runs[id]=r;busy=id
  local seq={"fetching","crafting","storing","done"};local k,step=1,1
  local fail=plan.item=="minecraft:brick_block" and plan.qty>24
  local tick
  function tick()
    local s=r.stages[k];if not s then return end
    local states=s.kind=="machine" and {"fetching","processing","processing","processing","storing","done"} or seq
    s.state=states[step];s.detail=s.state=="fetching" and "3 trips" or s.state=="processing" and "furnaceA, furnaceB" or ""
    if s.state=="processing" then s.done=math.min(s.total,s.done+math.ceil(s.total/3)) elseif s.state=="done" or s.state=="storing" then s.done=s.total end
    if fail and k==1 and step==3 then s.state="failed";r.status="failed";r.reason="furnaceB output short: 24 of 32 after deadline";r.where={{item="minecraft:clay_ball",count=8,storage="furnB.in"},{item="minecraft:brick",count=24,storage="furnB.out"}};r.finished=computer.uptime();busy=nil
      event.push("mes","stage",id,k,"failed");event.push("mes","done",id,"failed");return end
    event.push("mes","stage",id,k,s.state)
    step=step+1;if step>#states then k=k+1;step=1;r.stage=k end
    if not r.stages[k] then r.status="complete";r.finished=computer.uptime();busy=nil;event.push("mes","done",id,"complete") else event.timer(1,tick) end
  end
  event.timer(1,tick)
  return id
end
function M.wait(id) while runs[id].status=="running" do event.pull(1) end;return copy(runs[id]) end
function M.status(id) return copy(runs[id]) end
function M.runs() local out={};for id=#runs,1,-1 do local r=runs[id];out[#out+1]={id=id,item=r.item,qty=r.qty,status=r.status,stage=r.stage,stages=#r.stages} end;return out end
return M
