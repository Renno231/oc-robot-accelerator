-- UI-lab fake of mes.lua implementing the T11 API contract with canned plans
-- and timer-driven runs.
local event=require("event");local computer=require("computer")
local wh=require("warehouse")
local M={}
local function copy(t) if type(t)~="table" then return t end;local o={};for k,v in pairs(t) do o[k]=copy(v) end;return o end
local types={furnace={roles={"input","fuel","output"},inputs={"input"},output="output",fuel={role="fuel",item="minecraft:coal",per=8},batch=64,seconds=10}}
local crafters={cpu1={robot="7f3a91c2-55e1-4b0e-9d3c-2a6f1e0b8c44",buffer="cpu1.buf"}}
local runs={};local recipes={}
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
function M.plan(item,qty,opts)
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
-- Recipe import
function M.transposerInventories() return {{address="3fa2c1d0-aaaa-bbbb-cccc-000000000001",side=2,size=27,used=2},{address="3fa2c1d0-aaaa-bbbb-cccc-000000000001",side=1,size=27,used=10}} end
function M.readSlots(src)
  if src.side==1 then
    local s={};for _,k in ipairs({1,2,3,10,11,12}) do s[k]={name="minecraft:planks",damage=0,label="Oak Wood Planks",size=1} end
    s[14]={name="minecraft:crafting_table",damage=0,label="Crafting Table",size=1}
    -- not a crafting table recipe shape, but a 2x3 stand-in for the lab
    return s,27
  end
  return {[1]={name="minecraft:log",damage=0,label="Oak Wood",size=1},[24]={name="minecraft:coal",damage=1,label="Charcoal",size=1}},27
end
function M.slotsFromListing(listing,size) local s={};for k,v in pairs(listing) do s[k]={name=v.name,damage=v.damage,label=v.label,size=v.size} end;return s,size end
local function id(st) return st.name..((st.damage or 0)~=0 and ":"..st.damage or "") end
function M.recipeFromSlots(kind,slots,size,machineType)
  local d={kind=kind,machineType=machineType,inputs={},outputs={},grid={},labels={}}
  if kind=="processing" then
    assert(machineType and types[machineType],"pick a machine type")
    for k=1,size do local st=slots[k];if st then
      d.labels[id(st)]=st.label
      if k>size-4 then d.outputs[#d.outputs+1]={slot=k,item=id(st),qty=st.size} else d.inputs[#d.inputs+1]={slot=k,item=id(st),qty=st.size} end
    end end
    if #d.inputs==0 then return nil,"no inputs: put ingredients in the first slots" end
    if #d.inputs>16 then return nil,"at most 16 inputs" end
    if #d.outputs==0 then return nil,"no output: put the product in one of the last four slots" end
  else
    if size%9~=0 or size<27 then return nil,"crafting import needs a 9-wide chest (27+ slots)" end
    local map={1,2,3,10,11,12,19,20,21}
    for g,k in ipairs(map) do local st=slots[k];if st then d.grid[g]=id(st);d.labels[id(st)]=st.label;d.inputs[#d.inputs+1]={slot=k,item=id(st),qty=1} end end
    local out=slots[14];if not out then return nil,"put the crafted item in slot 14" end
    d.labels[id(out)]=out.label;d.outputs[1]={slot=14,item=id(out),qty=out.size}
    if #d.inputs==0 then return nil,"the 3x3 grid is empty" end
    for k=1,size do if slots[k] and k~=14 then local inGrid=false;for _,g in ipairs(map) do if g==k then inGrid=true end end
      if not inGrid then return nil,"slot "..k.." is outside the grid; leave it empty" end end end
  end
  return d
end
function M.saveRecipe(d)
  local key=d.outputs[1].item;recipes[key]=recipes[key] or {}
  local sig=d.kind..(d.machineType or "");for _,i in ipairs(d.inputs) do sig=sig..i.item..i.qty end
  for _,r in ipairs(recipes[key]) do if r.sig==sig then return nil,"duplicate" end end
  local r=copy(d);r.sig=sig;r.source=d.kind=="processing" and "processing" or "user";table.insert(recipes[key],r);return true
end
function M.recipes(item)
  local out={};for _,r in ipairs(recipes[item] or {}) do out[#out+1]=copy(r) end
  if item=="minecraft:torch" then out[#out+1]={kind="crafting",source="db",grid={nil,"minecraft:coal:1",nil,nil,"minecraft:stick"},inputs={{item="minecraft:coal:1",qty=1},{item="minecraft:stick",qty=1}},outputs={{item="minecraft:torch",qty=4}}} end
  return out
end
function M.removeRecipe(item,i) local l=recipes[item];if not l or not l[i] then return nil,"only user and processing recipes can be removed" end;table.remove(l,i);return true end
function M.oreFamilies(item) if item:find("planks") then return {"plankWood"} elseif item:find("log") then return {"logWood"} end;return {} end
return M
