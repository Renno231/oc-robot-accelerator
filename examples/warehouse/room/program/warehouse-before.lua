local map=require("logistics.map")
local logistics=require("logistics")
local event=require("event")
local serialization=require("serialization")
local computer=require("computer")
local M={}
local function copy(t) return serialization.unserialize(serialization.serialize(t)) end
local function read(path,default)
  local f=io.open(path,"r");if not f then return default end
  local t=serialization.unserialize(f:read("*a"));f:close();assert(type(t)=="table","invalid "..path);return t
end
local cfg=read("/etc/warehouse.cfg",{members={},groups={}})
local db={}
local rows,keys,staging=0,{},nil
-- Append one inventory record, not the entire catalogue, on an observation.
-- Replay streams the journal; memory remains proportional to current inventory types.
do local f=io.open("/etc/warehouse.db","r");if f then
  for line in f:lines() do local r=assert(serialization.unserialize(line),"invalid warehouse journal");db[r.key]=r.value;rows=rows+1 end
  f:close()
end end
local function saveConfig()
  local f=assert(io.open("/etc/warehouse.cfg","w"));f:write(serialization.serialize(cfg));f:close()
end
local function saveInventory(key)
  local line=serialization.serialize({key=key,value=db[key]},false).."\n"
  local f=assert(io.open("/etc/warehouse.db","a"));f:write(line);f:close();rows=rows+1
  if staging then staging.file:write(line);staging.rows=staging.rows+1 end
end
local function compact()
  if staging then staging.file:close();staging=nil end
  local tmp="/etc/warehouse.db.new";local f=assert(io.open(tmp,"w"))
  rows=0;for key,value in pairs(db) do f:write(serialization.serialize({key=key,value=value},false),"\n");rows=rows+1 end
  f:close();assert(os.rename(tmp,"/etc/warehouse.db"))
end
-- Event-driven incremental compaction: copy at most one inventory per finished
-- job. New observations go to both files while copying; a rename commits the
-- complete snapshot. A reboot during copying still replays the intact old log.
-- Journal/replay work is O(inventories * bounded endpoints per job), not uptime.
local function maintain()
  if not staging and rows>math.max(8,2*#keys) then
    staging={file=assert(io.open("/etc/warehouse.db.new","w")),cursor=1,rows=0}
  end
  if not staging then return end
  local key=keys[staging.cursor]
  if key and db[key] then
    staging.file:write(serialization.serialize({key=key,value=db[key]},false),"\n");staging.rows=staging.rows+1
  end
  staging.cursor=staging.cursor+1
  if staging.cursor>#keys then
    staging.file:close();assert(os.rename("/etc/warehouse.db.new","/etc/warehouse.db"));rows=staging.rows;staging=nil
  end
end
local function item(i)
  assert(type(i)=="table" and type(i.name)=="string" and (i.label==nil or type(i.label)=="string"),"item required")
  local damage=i.damage or 0;assert(type(damage)=="number" and damage>=0 and damage%1==0,"invalid damage")
  return {name=i.name,damage=damage,label=i.label}
end
local function matches(a,b) return a.name==b.name and a.damage==(b.damage or 0) and (not b.label or a.label==b.label) end
local function itemKey(i) return serialization.serialize({i.name,i.damage or 0,i.label},false) end
local function grouped(storage)
  for _,g in pairs(cfg.groups) do for _,s in pairs(g.roles) do if s==storage then return true end end end
end
local function inventory(storage) local s=cfg.members[storage];return s and (s.inventory or storage) end
local function rebuildKeys()
  local seen={};keys={}
  for storage in pairs(cfg.members) do local key=inventory(storage);if not seen[key] then seen[key]=true;keys[#keys+1]=key end end
  table.sort(keys)
end
rebuildKeys()
local function entries()
  local out={}
  for s,settings in pairs(cfg.members) do if not grouped(s) and map.storage(s) then
    local key=inventory(s);out[key]=out[key] or {};out[key][#out[key]+1]={storage=s,settings=settings,entry=db[key],key=key}
  end end
  for _,list in pairs(out) do table.sort(list,function(a,b) return a.storage<b.storage end) end
  return out
end
local function prune()
  local used={};for s in pairs(cfg.members) do used[inventory(s)]=true end
  for key in pairs(db) do if not used[key] then db[key]=nil end end
  compact();rebuildKeys()
end
function M.add(storage,settings)
  assert(map.storage(storage),"unknown storage");settings=copy(settings or {})
  for k in pairs(settings) do assert(k=="filter" or k=="priority" or k=="inventory","unsupported setting "..k) end
  assert(settings.priority==nil or (type(settings.priority)=="number" and math.abs(settings.priority)<math.huge),"invalid priority")
  assert(settings.inventory==nil or (type(settings.inventory)=="string" and settings.inventory~=""),"invalid inventory")
  if settings.filter then assert(type(settings.filter)=="table","filter list required");for i,v in ipairs(settings.filter) do settings.filter[i]=item(v) end end
  cfg.members[storage]=settings;saveConfig();prune();return true
end
function M.remove(storage) local existed=cfg.members[storage]~=nil;cfg.members[storage]=nil;saveConfig();prune();return existed end
function M.members() return copy(cfg.members) end
function M.group(name,kind,roles)
  assert(type(name)=="string" and name~="" and type(kind)=="string" and type(roles)=="table" and next(roles),"group name, type and roles required")
  for role,s in pairs(roles) do assert(type(role)=="string" and map.storage(s),"invalid group role/storage") end
  cfg.groups[name]={type=kind,roles=copy(roles)};saveConfig();return true
end
function M.ungroup(name) local existed=cfg.groups[name]~=nil;cfg.groups[name]=nil;saveConfig();return existed end
function M.groups(kind) local out={};for n,g in pairs(cfg.groups) do if not kind or g.type==kind then out[n]=copy(g) end end;return out end
local function quantity(e,i)
  local n=0;for _,v in pairs(e and e.items or {}) do if matches(v.item,i) then n=n+v.count end end;return n
end
function M.find(i)
  i=item(i);local out={}
  for _,list in pairs(entries()) do local c=quantity(list[1].entry,i);if c>0 then out[#out+1]={storage=list[1].storage,count=c} end end
  table.sort(out,function(a,b) return a.storage<b.storage end);return out
end
function M.count(i) local n=0;for _,v in ipairs(M.find(i)) do n=n+v.count end;return n end
function M.contents(storage) local key=inventory(storage);return key and db[key] and copy(db[key]) or nil end
local function observe(storage,step)
  local key=inventory(storage);if not key or not step.listing or not step.size then return end
  local e={items={},slots=step.size,freeSlots=step.size,time=computer.uptime(),verified=true}
  for _,stack in pairs(step.listing) do
    local i=item(stack);local k=itemKey(i);local v=e.items[k] or {item=i,count=0,maxSize=stack.maxSize,stacks=0,room=0}
    v.count=v.count+stack.size;v.stacks=v.stacks+1;v.room=v.room+stack.maxSize-stack.size;e.items[k]=v;e.freeSlots=e.freeSlots-1
  end
  -- Retain a seen item's real stack limit even when its last stack disappears.
  for k,v in pairs(db[key] and db[key].items or {}) do if not e.items[k] then
    e.items[k]={item=v.item,count=0,maxSize=v.maxSize,stacks=0,room=0}
  end end
  db[key]=e;saveInventory(key)
end
local function at(endpoint)
  if not endpoint then return end
  for s in pairs(cfg.members) do local e=map.storage(s);if e and e.node==endpoint.node and e.side==endpoint.side then return s end end
end
local function readStorage(storage)
  return logistics.job({{read=storage}},{drones=1,retries=0})
end
-- Explicit scans are independent one-face read jobs: even a completely full
-- chest fits the existing result packet bound, unlike a 64-face result.
function M.scan(storages)
  local list={}
  if type(storages)=="string" then storages={storages} end
  if storages then for _,s in ipairs(storages) do assert(inventory(s),"not a warehouse member");list[#list+1]=s end
  else for _,faces in pairs(entries()) do list[#list+1]=faces[1].storage end end
  table.sort(list);compact();local ids,seen={},{}
  for _,s in ipairs(list) do local key=inventory(s);if not seen[key] then ids[#ids+1]=readStorage(s);seen[key]=true end end
  return ids
end
local function adjust(storage,i,delta,maximum,touched)
  if not storage or delta==0 then return end
  local key=inventory(storage);local e=db[key];touched[key]=storage
  if not e then e={items={},capacityUnknown=true,estimated=true};db[key]=e end
  local function change(k,v,n)
    v.maxSize=maximum or v.maxSize
    if not v.maxSize then
      -- An interrupted job may expose counts but no stack limit. Never invent
      -- a 64-stack capacity: an explicit read is required for this inventory.
      e.capacityUnknown=true;v.count=math.max(0,v.count+n);e.items[k]=v;return
    end
    if n>0 then
      local new=math.ceil(math.max(0,n-v.room)/v.maxSize);v.stacks=v.stacks+new
      if e.freeSlots then e.freeSlots=math.max(0,e.freeSlots-new) end
    end
    v.count=math.max(0,v.count+n);v.room=math.max(0,v.stacks*v.maxSize-v.count)
    if v.count==0 then if e.slots then e.freeSlots=math.min(e.slots,e.freeSlots+v.stacks) end;v.stacks=0;v.room=0 end
    e.items[k]=v
  end
  if delta<0 then
    local remaining=-delta
    for k,v in pairs(e.items) do if matches(v.item,i) then local n=math.min(remaining,v.count);change(k,v,-n);remaining=remaining-n end end
  else
    local k=itemKey(i);local v=e.items[k]
    if not v then for other,value in pairs(e.items) do if matches(value.item,i) then k,v=other,value;break end end end
    change(k,v or {item=item(i),count=0,maxSize=maximum,stacks=0,room=0},delta)
  end
  e.estimated=true
end
local function short(storage,i,returned,touched)
  if not storage then return end
  local key=inventory(storage);local e=db[key];if not e then e={items={},capacityUnknown=true,estimated=true};db[key]=e end
  local n=quantity(e,i);adjust(storage,i,-n,nil,touched)
  if returned>0 then adjust(storage,i,returned,nil,touched) end
  touched[key]=storage
end
local function full(storage,i,touched)
  if not storage then return end
  local key=inventory(storage);local e=db[key];if not e then e={items={},capacityUnknown=true,estimated=true};db[key]=e end
  e.full=e.full or {};e.full[itemKey(i)]=true;e.freeSlots=0
  for _,v in pairs(e.items) do if matches(v.item,i) then v.room=0 end end
  e.estimated=true;touched[key]=storage
end
local function finished(_,id)
  local s=logistics.status(id);if not s then return end
  local touched={}
  if s.steps then
    -- Agent ledger subtracts returns AND overflow from take.moved, so use
    -- taken-returned for the source, not moved. Puts report actual deliveries.
    for _,step in ipairs(s.steps) do
      if step.read then local storage=at(step.read);if storage and not step.read.slots then observe(storage,step) end
      elseif step.take then
        local storage=at(step.take);adjust(storage,step.item,-(step.taken or 0)+(step.returned or 0),step.maxSize,touched)
        -- A full-face short reports observed remaining stock, not necessarily
        -- zero (e.g. unmergeable NBT variants filled the drone's cargo slots).
        if step.short and not step.take.slots then short(storage,step.item,step.found or 0,touched) end
        adjust(at(s.overflowEndpoint),step.item,step.overflow or 0,step.maxSize,touched)
      elseif step.put then
        adjust(at(step.put),step.item,step.moved or 0,step.maxSize,touched)
        if (step.refused or 0)>0 and not step.put.slots then full(at(step.put),step.item,touched) end
      end
    end
  elseif s.item then
    adjust(at(s.from),s.item,-(s.taken or 0)+(s.returned or 0),s.maxSize,touched)
    if s.short and s.from and not s.from.slots then short(at(s.from),s.item,s.found or 0,touched) end
    adjust(at(s.to),s.item,s.moved or 0,s.maxSize,touched)
    adjust(at(s.overflowEndpoint),s.item,s.overflow or 0,s.maxSize,touched)
    if (s.refused or 0)>0 and s.to and not s.to.slots then full(at(s.to),s.item,touched) end
  end
  for key in pairs(touched) do if db[key] then saveInventory(key) end end
  maintain()
end
event.listen("logistics",finished)
local function positive(n) assert(type(n)=="number" and n>0 and n<math.huge and n%1==0,"positive count required") end
local function node(endpoint)
  if type(endpoint)=="string" then return assert(map.place(endpoint),"unknown endpoint") end
  return endpoint.storage and assert(map.place(endpoint.storage)) or endpoint.node
end
local function distance(a,b)
  local ok,path=pcall(logistics.plan,a,b);if not ok then return math.huge end
  local d=0;for k=2,#path do local p,q=path[k-1],path[k];d=d+math.sqrt((p.x-q.x)^2+(p.y-q.y)^2+(p.z-q.z)^2) end;return d
end
function M.fetch(i,n,to,opts)
  i=item(i);positive(n);local candidates,total={},0
  for _,faces in pairs(entries()) do
    local best,dist;for _,face in ipairs(faces) do local d=distance(face.storage,node(to));if not best or d<dist then best,dist=face,d end end
    local count=quantity(best.entry,i);if count>0 and dist<math.huge then candidates[#candidates+1]={storage=best.storage,count=count,distance=dist};total=total+count end
  end
  if total<n then return nil,"requested "..n..", available "..total end
  table.sort(candidates,function(a,b) if a.count~=b.count then return a.count>b.count end;if a.distance~=b.distance then return a.distance<b.distance end;return a.storage<b.storage end)
  local steps,remaining={},n
  for _,c in ipairs(candidates) do if remaining==0 then break end;local take=math.min(remaining,c.count);steps[#steps+1]={take=c.storage,item=i,count=take};remaining=remaining-take end
  steps[#steps+1]={put=to,item=i,rest=true};return logistics.job(steps,opts)
end
local function accepts(settings,i)
  if not settings.filter then return nil end
  for _,v in ipairs(settings.filter) do if matches(i,v) then return true end end;return false
end
function M.store(i,n,from,opts)
  i=item(i);positive(n);local candidates,total,unknown={},0,0;local maximum
  for _,e in pairs(db) do for _,v in pairs(e.items) do if matches(v.item,i) and v.maxSize then maximum=maximum and math.min(maximum,v.maxSize) or v.maxSize end end end
  for _,faces in pairs(entries()) do
    local best,uncertain
    for _,face in ipairs(faces) do
      local e=face.entry;local accept=accepts(face.settings,i)
      if accept~=false and e and not e.capacityUnknown and maximum then
        local held=quantity(e,i);local room=0;for _,v in pairs(e.items) do if matches(v.item,i) then room=room+v.room end end
        local occupied=0;for _,v in pairs(e.items) do occupied=occupied+v.count end
        local tier=accept and 1 or held>0 and 2 or occupied==0 and 3 or nil
        local capacity=e.full and e.full[itemKey(i)] and 0 or e.freeSlots*maximum+room
        if tier and capacity>0 and distance(node(from),face.storage)<math.huge then
          local c={storage=face.storage,tier=tier,priority=face.settings.priority or 0,capacity=capacity}
          if not best or c.tier<best.tier or (c.tier==best.tier and (c.priority>best.priority or (c.priority==best.priority and c.storage<best.storage))) then best=c end
        end
      elseif accept~=false and (not e or e.capacityUnknown or not maximum) then uncertain=true end
    end
    if best then candidates[#candidates+1]=best;total=total+best.capacity end
    if uncertain then unknown=unknown+1 end
  end
  if total<n then return nil,"requested "..n..", capacity "..total..", unknown inventories "..unknown end
  table.sort(candidates,function(a,b) if a.tier~=b.tier then return a.tier<b.tier end;if a.priority~=b.priority then return a.priority>b.priority end;return a.storage<b.storage end)
  -- Interleave takes and puts, allowing a large request to split naturally.
  local steps,remaining={},n
  for _,c in ipairs(candidates) do if remaining==0 then break end;local amount=math.min(remaining,c.capacity)
    steps[#steps+1]={take=from,item=i,count=amount};steps[#steps+1]={put=c.storage,item=i,count=amount};remaining=remaining-amount
  end
  return logistics.job(steps,opts)
end
return M
