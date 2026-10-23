-- UI-lab fake of drone-logistics iochest: same calls, record shapes and io
-- signal. Records: {name,role,sensor,listing={[key]={item,count}},
-- pending={[jobId]={a=counts,read=bool}},reason}. Jobs are logistics fakes;
-- their logistics signal finishes them. Lab hooks at the end.
local event=require("event");local lg=require("logistics");local wh=require("logistics.warehouse")
local M={}
local function copy(t) if type(t)~="table" then return t end;local o={};for k,v in pairs(t) do o[k]=copy(v) end;return o end
local function key(i) return i.name..":"..(i.damage or 0) end
local function stack(name,damage,label,count) return {item={name=name,damage=damage,label=label},count=count} end
local function listing(...) local o={};for _,e in ipairs({...}) do o[key(e.item)]=e end;return o end
local rows={
  in1={name="in1",role="import",sensor="sensor1",listing={},pending={}},
  in2={name="in2",role="import",listing=listing(stack("minecraft:cobblestone",0,"Cobblestone",40)),pending={},reason="stock full: 40 Cobblestone left in in2"},
  out1={name="out1",role="export",listing=listing(stack("minecraft:iron_ingot",0,"Iron Ingot",1216)),pending={}}}
local sizes={in1=27,in2=27,out1=27}
-- Sensor reports seen: sensor3 sits on a double chest.
local seen={sensor1={size=27},sensor2={size=27},sensor3={size=54}}
local function state(r) return next(r.pending) and "active" or r.reason and "partial" or "idle" end
local function save(r) event.push("io",r.name,state(r),r.reason) end
local function row(n,role) local r=rows[n];assert(r and (not role or r.role==role),"invalid IO role");return r end
local function add(out,i,n) local k=key(i);local e=out[k] or {item=copy(i),count=0};e.count=math.max(0,e.count+n);out[k]=e end
function M.list()
  local out={};for _,r in pairs(rows) do out[#out+1]=copy(r) end
  table.sort(out,function(a,b) return a.name<b.name end);return out
end
-- Import: stock takes everything except cobblestone (stock full).
local function import(r)
  r.reason=nil;local take={}
  for _,e in pairs(r.listing) do if e.count>0 then
    if e.item.name=="minecraft:cobblestone" then r.reason="stock full: "..e.count.." "..e.item.label.." left in "..r.name else take[#take+1]=e end
  end end
  if #take>0 then local id=lg.fake("store",{storage=r.name},take[1].item,take[1].count,4);local a={};for _,e in ipairs(take) do add(a,e.item,e.count) end;r.pending[id]={a=a} end
  save(r)
end
function M.attach(sensor,n)
  local r=row(n);if r.sensor then return r.sensor==sensor or nil,"inventory already has sensor "..r.sensor end
  local p=seen[sensor];if not p then return nil,"waiting for sensor report" end
  if p.size~=sizes[r.name] then return nil,"sensor sees "..tostring(p.size).." slots, expected "..sizes[r.name] end
  for _,v in pairs(rows) do if v.sensor==sensor then return nil,"sensor already attached to "..v.name end end
  r.sensor=sensor;save(r);return true
end
function M.importNow(n)
  local r=row(n,"import");if r.sensor then import(r);return true end
  local id=lg.fake("read",{storage=r.name},nil,nil,3);r.pending[id]={a={},read=true};save(r);return id
end
local function fetch(req,n,one)
  local r=row(n,"export");local stock=copy(r.listing)
  local free=sizes[r.name];for _,v in pairs(stock) do free=free-math.ceil(v.count/(wh.stackSize(v.item) or 64)) end
  local out={};r.reason=nil
  for _,v in ipairs(req) do local k=key(v.item);local max=wh.stackSize(v.item) or 64;local old=stock[k] and stock[k].count or 0
    local slots=math.ceil(old/max);local count=math.min(v.count,math.max(0,(free+slots)*max-old))
    if count<v.count then r.reason="export chest full: take items from "..r.name end
    if count>0 then out[#out+1]={item=v.item,count=count};free=free-math.ceil((old+count)/max)+slots;stock[k]={item=v.item,count=old+count} end
  end
  local ids,err={},nil
  for _,v in ipairs(out) do local id;id,err=wh.fetch(v.item,v.count,r.name);if id then ids[#ids+1]=id;local a={};add(a,v.item,v.count);r.pending[id]={a=a} end end
  r.reason=err or r.reason;save(r);if one then return ids[1],r.reason end;return #ids>0 and ids or nil,r.reason
end
function M.fetch(i,count,n) return fetch({{item=i,count=count}},n,true) end
function M.fetchMany(req,n) return fetch(req,n,false) end
event.listen("logistics",function(_,id)
  for _,r in pairs(rows) do local p=r.pending[id];if p then r.pending[id]=nil
    if p.read then import(r)
    elseif r.sensor then r.listing={};save(r) -- the sensor reports the chest after the job
    else for _,e in pairs(p.a) do add(r.listing,e.item,r.role=="export" and e.count or -e.count) end;save(r) end
  end end
end)
-- Lab: items land in in1; its sensor reports them and the import starts.
function M.labDeposit()
  local r=rows.in1;r.listing=listing(stack("minecraft:sand",0,"Sand",128),stack("minecraft:iron_ore",0,"Iron Ore",12),stack("minecraft:gravel",0,"Gravel",64))
  if r.sensor then import(r) else save(r) end
end
return M
