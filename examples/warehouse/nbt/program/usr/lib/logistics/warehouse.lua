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
local db_store=require("logistics.store").open("/etc/warehouse.db","log")
local db=db_store:load()
local observed={}
-- Reservations belong to warehouse-submitted jobs, not the logistics router.
-- Inventory aliases share a key, so two faces cannot reserve the same stock.
local inFlight={}
local pendingCatalogue={}
local flight_store=require("logistics.store").open("/etc/warehouse.flight")
for key,r in pairs(flight_store:load()) do
  local id=tonumber(key:sub(5));inFlight[id]=r;pendingCatalogue[id]=true
end
-- Volatile, exact-sided observations. Physical identities are ONLY for
-- invalidation; they never authorize reuse of another face's slot indices.
local roleCache,pendingReads,pendingMutations,mutationCounts={},{},{},{}
local identityIndex=nil
local identityGeneration,mutationEpochs=0,{}
local function metadataChanged()
  roleCache={};identityIndex=nil;identityGeneration=identityGeneration+1
end
-- Stack sizes other than 64, as scans saw them; anything not listed is 64.
local limits=read("/etc/warehouse.stacks",{})
local limitsDirty=false
for k,v in pairs(limits) do if v==64 then limits[k]=nil;limitsDirty=true end end
local function limitKey(i) return i.name..":"..tostring(i.damage or 0) end
local function limit(i) return limits[limitKey(i)] or 64 end
local function learn(i,maximum)
  if i and type(maximum)=="number" and maximum>0 then
    local k=limitKey(i);local v=maximum~=64 and maximum or nil
    if limits[k]~=v then limits[k]=v;limitsDirty=true end
  end
end
local function saveLimits()
  if not limitsDirty then return end
  local f=assert(io.open("/etc/warehouse.stacks","w"));f:write(serialization.serialize(limits));f:close();limitsDirty=false
end
for _,e in pairs(db) do for _,v in pairs(e.items or {}) do learn(v.item,v.maxSize) end end
local function saveConfig()
  local f=assert(io.open("/etc/warehouse.cfg","w"));f:write(serialization.serialize(cfg));f:close()
end
local revision,totalsCache=0,nil
local function changed(id) revision=revision+1;totalsCache=nil;event.push("warehouse","changed",id) end
local mapRevision=map.revision and map.revision() or 0
-- Eligibility depends on named map faces as well as warehouse observations.
-- Only compare a scalar on redraw; rebuild the shared totals on demand.
local function syncMapRevision()
  local current=map.revision and map.revision() or 0
  if current~=mapRevision then mapRevision=current;metadataChanged();changed() end
end
function M.revision() syncMapRevision();return revision end
local function saveInventory(key)
  db_store:put(key,db[key])
end
local function item(i)
  assert(type(i)=="table" and type(i.name)=="string" and (i.label==nil or type(i.label)=="string"),"item required")
  local damage=i.damage or 0;assert(type(damage)=="number" and damage>=0 and damage%1==0,"invalid damage")
  return {name=i.name,damage=damage,label=i.label}
end
local function matches(a,b) return a.name==b.name and a.damage==(b.damage or 0) and (not b.label or a.label==b.label) end
local function itemKey(i) return serialization.serialize({i.name,i.damage or 0,i.label},false) end
local function inventory(storage) local s=cfg.members[storage];return s and (s.inventory or storage) end
local offsets={{0,-1,0},{0,1,0},{0,0,-1},{0,0,1},{-1,0,0},{1,0,0}}
local function endpoint(value)
  if type(value)=="string" then return map.storage(value) end
  if type(value)=="table" then return value.storage and map.storage(value.storage) or value end
end
local function faceIdentities(e)
  local ids={"face:"..e.node..":"..e.side}
  local p=map.node and map.node(e.node);local d=offsets[e.side+1]
  if p and d and type(p.x)=="number" and type(p.y)=="number" and type(p.z)=="number" then
    ids[#ids+1]=string.format("xyz:%.17g:%.17g:%.17g",p.x+d[1],p.y+d[2],p.z+d[3])
  end
  return ids
end
local function metadata()
  if identityIndex then return identityIndex end
  local index={faces={},clusters={}};local parent={}
  local function root(key)
    if not parent[key] then parent[key]=key end
    if parent[key]~=key then parent[key]=root(parent[key]) end
    return parent[key]
  end
  -- One descriptor per member on an edit, never N descriptors per endpoint.
  for storage,settings in pairs(cfg.members) do
    local e=map.storage(storage)
    if e then
      local faces=index.faces[e.node] or {};index.faces[e.node]=faces
      local ids=faces[e.side] or faceIdentities(e);faces[e.side]=ids
      ids[#ids+1]="alias:"..(settings.inventory or storage)
      local first=root(ids[1])
      for k=2,#ids do local other=root(ids[k]);if other~=first then parent[other]=first end end
    end
  end
  local groups={}
  for key in pairs(parent) do
    local first=root(key);local group=groups[first] or {};groups[first]=group
    group[#group+1]=key;index.clusters[key]=group
  end
  identityIndex=index;return index
end
local function identities(value)
  local e=endpoint(value);if not e or not e.node or e.side==nil then return end
  local index=metadata();local faces=index.faces[e.node]
  return faces and faces[e.side] or faceIdentities(e),e
end
local function invalidate(ids)
  if not ids then return end
  local affected={};for _,key in ipairs(ids) do affected[key]=true end
  for node,faces in pairs(roleCache) do for side,view in pairs(faces) do
    for _,key in ipairs(view.ids) do if affected[key] then faces[side]=nil;break end end
  end;if not next(faces) then roleCache[node]=nil end end
end
local function mutationKeys(endpoints)
  local keys,expanded={},{};local index=metadata()
  for _,e in ipairs(endpoints) do
    local ids=identities(e)
    for _,key in ipairs(ids or {}) do
      keys[key]=true
      local cluster=index.clusters[key]
      if cluster and not expanded[cluster] then
        expanded[cluster]=true
        for _,joined in ipairs(cluster) do keys[joined]=true end
      end
    end
  end
  local ids={};for key in pairs(keys) do ids[#ids+1]=key end;invalidate(ids)
  return keys
end
-- Carry observed slot counts on the step, before invalidation.
local function claim(steps)
  for _,s in ipairs(steps or {}) do
    local e=s.take and endpoint(s.take)
    local slots=type(s.take)=="table" and s.take.slots
    if e and slots then
      s.claimed=nil
      local v=roleCache[e.node] and roleCache[e.node][e.side]
      if v then
        s.claimed=0
        for _,slot in ipairs(slots) do
          local r=v.listing[slot]
          if r==nil then s.claimed=nil;break end
          if r and matches(r,s.item) then s.claimed=s.claimed+r.size end
        end
      end
    end
  end
end
local function beginMutation(id,endpoints,steps)
  syncMapRevision()
  claim(steps)
  local keys=mutationKeys(endpoints)
  if pendingMutations[id] then return end
  pendingMutations[id]=keys
  pendingCatalogue[id]=true
  for key in pairs(keys) do
    mutationCounts[key]=(mutationCounts[key] or 0)+1
    mutationEpochs[key]=(mutationEpochs[key] or 0)+1
  end
end
logistics.onMutation("warehouse.role-cache",beginMutation)
local function invalidateRead(e)
  local cached=roleCache[e.node] and roleCache[e.node][e.side]
  if not cached then return end
  if e.slots then for _,slot in ipairs(e.slots) do cached.listing[slot]=nil end
  else roleCache[e.node][e.side]=nil end
end
local function readProvenance(endpoints)
  local reads={}
  for _,e in ipairs(endpoints) do
    local r={node=e.node,side=e.side,generation=identityGeneration,epochs={},blocked=false}
    if e.slots then r.slots={};for k,v in ipairs(e.slots) do r.slots[k]=v end end
    for _,key in ipairs(identities(e) or {}) do
      r.epochs[key]=mutationEpochs[key] or 0
      if mutationCounts[key] then r.blocked=true end
    end
    reads[#reads+1]=r;invalidateRead(r)
  end
  return reads
end
local function beginRead(id,endpoints)
  syncMapRevision()
  pendingReads[id]=readProvenance(endpoints);pendingCatalogue[id]=true
end
logistics.onRead("warehouse.role-cache",beginRead)
local function readCurrent(reads,e)
  for _,r in ipairs(reads or {}) do
    local same=r.node==e.node and r.side==e.side and (r.slots==nil)==(e.slots==nil)
    if same and r.slots then
      same=#r.slots==#e.slots
      for k,v in ipairs(r.slots) do if v~=e.slots[k] then same=false;break end end
    end
    if same then
      if r.blocked then return false end
      if r.generation~=identityGeneration then
        local current={}
        for _,key in ipairs(identities(e) or {}) do current[key]=true end
        -- Epoch keys also preserve the endpoint's original identity set.
        for key in pairs(r.epochs) do
          if not current[key] then return false end;current[key]=nil
        end
        if next(current) then return false end
      end
      for key,epoch in pairs(r.epochs) do
        if mutationCounts[key] or (mutationEpochs[key] or 0)~=epoch then return false end
      end
      return true
    end
  end
  return false
end
local function grouped(storage)
  local key=inventory(storage) or storage
  for _,g in pairs(cfg.groups) do for _,s in pairs(g.roles) do
    if (inventory(s) or s)==key then return true end
  end end
end
local function entries()
  local out={}
  for s,settings in pairs(cfg.members) do if not grouped(s) and map.storage(s) then
    local key=inventory(s);out[key]=out[key] or {};out[key][#out[key]+1]={storage=s,settings=settings,entry=db[key],key=key}
  end end
  for _,list in pairs(out) do table.sort(list,function(a,b) return a.storage<b.storage end) end
  return out
end
local function prune()
  local used,removed={},false;for s in pairs(cfg.members) do used[inventory(s)]=true end
  for key in pairs(db) do if not used[key] and not map.storage(key) then db[key]=nil;db_store:delete(key);removed=true end end
  if removed then db_store:flush() end
end
function M.add(storage,settings)
  assert(map.storage(storage),"unknown storage");settings=copy(settings or {})
  for k in pairs(settings) do assert(k=="filter" or k=="priority" or k=="inventory","unsupported setting "..k) end
  assert(settings.priority==nil or (type(settings.priority)=="number" and math.abs(settings.priority)<math.huge),"invalid priority")
  assert(settings.inventory==nil or (type(settings.inventory)=="string" and settings.inventory~=""),"invalid inventory")
  if settings.filter then assert(type(settings.filter)=="table","filter list required");for i,v in ipairs(settings.filter) do settings.filter[i]=item(v) end end
  cfg.members[storage]=settings;metadataChanged();saveConfig();prune();changed();return true
end
function M.remove(storage) local existed=cfg.members[storage]~=nil;cfg.members[storage]=nil;metadataChanged();saveConfig();prune();changed();return existed end
function M.members() return copy(cfg.members) end
function M.group(name,kind,roles)
  assert(type(name)=="string" and name~="" and type(kind)=="string" and type(roles)=="table" and next(roles),"group name, type and roles required")
  for role,s in pairs(roles) do assert(type(role)=="string" and map.storage(s),"invalid group role/storage") end
  cfg.groups[name]={type=kind,roles=copy(roles)};saveConfig();changed();return true
end
function M.ungroup(name) local existed=cfg.groups[name]~=nil;cfg.groups[name]=nil;saveConfig();changed();return existed end
function M.groups(kind) local out={};for n,g in pairs(cfg.groups) do if not kind or g.type==kind then out[n]=copy(g) end end;return out end
local function quantity(e,i)
  local n=0;for _,v in pairs(e and e.items or {}) do if matches(v.item,i) then n=n+v.count end end;return n
end
local function reserved(key,i,direction)
  local count=0
  for _,job in pairs(inFlight) do for _,r in ipairs(job) do
    if r.key==key and r.direction==direction and matches(r.item,i) then count=count+r.count end
  end end
  return count
end
local function incomingCapacity(key,i,maximum,planned)
  local same,other=0,{}
  local function include(r)
    if r.key==key and r.direction=='put' then
      if matches(r.item,i) then same=same+r.count
      else local k=planned and itemKey(r.item) or limitKey(r.item);other[k]=other[k] or {item=r.item,count=0,maximum=r.maximum};other[k].count=other[k].count+r.count end
    end
  end
  for _,job in pairs(inFlight) do for _,r in ipairs(job) do include(r) end end
  for _,r in ipairs(planned or {}) do include(r) end
  local used=same
  for _,r in pairs(other) do
    local room=0;for _,v in pairs(db[key] and db[key].items or {}) do if matches(v.item,r.item) then room=room+v.room end end
    used=used+math.ceil(math.max(0,r.count-room)/r.maximum)*maximum
  end
  return used
end
local function submit(steps,opts,reservations)
  local id,err=logistics.job(steps,opts)
  local s=id and logistics.status(id)
  if id and s and s.state~='done' and s.state~='failed' and s.state~='partial' then
    inFlight[id]=reservations;pendingCatalogue[id]=true
    flight_store:put("job_"..id,reservations);flight_store:flush()
  end
  return id,err
end
-- A logistics terminal state can precede delivery of its completion event.
-- Callers requiring a catalogue barrier wait until that event is incorporated.
function M.settled(id) return not pendingCatalogue[id] end
function M.find(i)
  i=item(i);local out={}
  for _,list in pairs(entries()) do local c=quantity(list[1].entry,i);if c>0 then out[#out+1]={storage=list[1].storage,count=c} end end
  table.sort(out,function(a,b) return a.storage<b.storage end);return out
end
function M.count(i) local n=0;for _,v in ipairs(M.find(i)) do n=n+v.count end;return n end
-- Stock no drone is already on its way to take.
function M.available(i)
  i=item(i);local n=0
  for key,list in pairs(entries()) do n=n+math.max(0,quantity(list[1].entry,i)-reserved(key,i,'take')) end
  return n
end
function M.entries()
  syncMapRevision();local out=copy(entries())
  for key,faces in pairs(out) do for _,v in ipairs(faces) do
    if v.entry then v.entry.beforeRestart=not observed[key] end
  end end
  return out
end
-- SHARED/read-only: aggregate physical stock inventories once per change.
function M.totals()
  syncMapRevision()
  if totalsCache then return totalsCache end
  local out,byItem={},{}
  for _,faces in pairs(entries()) do
    for _,v in pairs(faces[1].entry and faces[1].entry.items or {}) do if v.count>0 then
      local i=v.item
      byItem[i.name]=byItem[i.name] or {};local damages=byItem[i.name]
      damages[i.damage or 0]=damages[i.damage or 0] or {};local labels=damages[i.damage or 0]
      local label=i.label or false;local total=labels[label]
      if not total then
        total={item=item(i),count=0,storages=0};labels[label]=total;out[#out+1]=total
      end
      total.count=total.count+v.count;total.storages=total.storages+1
    end end
  end
  table.sort(out,function(a,b)
    if a.item.name~=b.item.name then return a.item.name<b.item.name end
    if a.item.damage~=b.item.damage then return a.item.damage<b.item.damage end
    return (a.item.label or "")<(b.item.label or "")
  end)
  totalsCache=out;return out
end
function M.inflight()
  local out={}
  for id,job in pairs(inFlight) do for _,r in ipairs(job) do
    out[#out+1]={job=id,item=item(r.item),count=r.count,storage=r.storage,
      kind=r.direction=='take' and 'fetch' or 'store'}
  end end
  table.sort(out,function(a,b) if a.job~=b.job then return a.job<b.job end;return a.storage<b.storage end)
  return out
end
function M.contents(storage) local key=inventory(storage) or storage;return db[key] and copy(db[key]) or nil end
function M.stackSize(i) return limit(item(i)) end
local function roleSlots(slots,size)
  assert(type(slots)=="table" and next(slots),"nonempty slots required")
  if size~=nil then assert(type(size)=="number" and size>=0 and size<math.huge and size%1==0,"invalid inventory size") end
  local n=0
  for k in pairs(slots) do
    assert(type(k)=="number" and k>0 and k%1==0,"dense slots required");n=n+1
  end
  local out,seen={},{}
  for k=1,n do
    local slot=slots[k]
    assert(type(slot)=="number" and slot>0 and slot<math.huge and slot%1==0 and not seen[slot],"invalid/duplicate slot")
    assert(not size or slot<=size,"slot outside inventory")
    out[k]=slot;seen[slot]=true
  end
  return out
end
local function observeRole(e,step)
  invalidateRead(e)
  if type(step.listing)~="table" or type(step.size)~="number" or step.size<0 or step.size%1~=0 or step.size==math.huge then return end
  local ids=identities(e);if not ids then return end
  local faces=roleCache[e.node] or {};roleCache[e.node]=faces
  local cached=faces[e.side] or {listing={}};faces[e.side]=cached
  cached.ids=ids;cached.size=step.size
  -- Discard observations outside the latest reported face size.
  for slot in pairs(cached.listing) do if slot>step.size then cached.listing[slot]=nil end end
  local function slot(slot)
    if type(slot)~="number" or slot<1 or slot>step.size or slot%1~=0 then return end
    local stack=step.listing[slot]
    if not stack then cached.listing[slot]=false;return end -- verified empty
    local ok,i=pcall(item,stack)
    if ok and type(stack.size)=="number" and stack.size>0 and stack.size%1==0
      and type(stack.maxSize)=="number" and stack.maxSize>0 and stack.maxSize<math.huge
      and stack.maxSize%1==0 and stack.size<=stack.maxSize then
      cached.listing[slot]={name=i.name,damage=i.damage,label=i.label,size=stack.size,maxSize=stack.maxSize}
    else cached.listing[slot]=nil end
  end
  if e.slots then for _,index in ipairs(e.slots) do slot(index) end
  else cached.listing={};for index=1,step.size do slot(index) end end
end
local function observe(storage,step)
  local key=inventory(storage) or storage;if not key or not step.listing or not step.size then return end
  local e={items={},slots=step.size,freeSlots=step.size,time=computer.uptime(),verified=true}
  for _,stack in pairs(step.listing) do
    local i=item(stack);local k=itemKey(i);local v=e.items[k] or {item=i,count=0,maxSize=stack.maxSize,stacks=0,room=0}
    v.count=v.count+stack.size;v.stacks=v.stacks+1;v.room=v.room+stack.maxSize-stack.size;e.items[k]=v;e.freeSlots=e.freeSlots-1
  end
  -- Retain a seen item's real stack limit even when its last stack disappears.
  for k,v in pairs(db[key] and db[key].items or {}) do if not e.items[k] then
    e.items[k]={item=v.item,count=0,maxSize=v.maxSize,stacks=0,room=0}
  end end
  db[key]=e;observed[key]=true;saveInventory(key);return true
end
local endpointStorages
local function at(endpoint)
  if not endpoint then return end
  for s,e in pairs(endpointStorages) do if e.node==endpoint.node and e.side==endpoint.side then return s end end
end
local function readStorage(storage,linger)
  return submit({{read=storage}},{drones=1,retries=0,linger=linger},{})
end
-- Explicit scans are independent one-face read jobs: even a completely full
-- chest fits the existing result packet bound, unlike a 64-face result.
-- opts.linger: the drone waits at the storage for a follow-up job. Scans of
-- several storages always linger, so a drone goes from read to read.
function M.scan(storages,opts)
  local list={}
  if type(storages)=="string" then storages={storages} end
  if storages then for _,s in ipairs(storages) do assert(map.storage(s),"unknown storage");list[#list+1]=s end
  else for _,faces in pairs(entries()) do list[#list+1]=faces[1].storage end end
  table.sort(list);local ids,seen={},{};local linger=opts and opts.linger or #list>1
  for _,s in ipairs(list) do local key=inventory(s) or s;if not seen[key] then ids[#ids+1]=readStorage(s,linger);seen[key]=true end end
  return ids
end
local function adjust(storage,i,delta,maximum,touched,empty)
  if not storage or delta==0 then return end
  local key=inventory(storage) or storage;local e=db[key];touched[key]=storage
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
    v.count=math.max(0,v.count+n)
    if n<0 then
      local stacks=math.max(0,math.min(v.count,empty and v.stacks-empty or v.stacks))
      if e.slots then e.freeSlots=math.min(e.slots,e.freeSlots+v.stacks-stacks) end
      v.stacks=stacks
    end
    v.room=math.max(0,v.stacks*v.maxSize-v.count)
    e.items[k]=v
  end
  if delta<0 then
    if empty then
      local seen
      for _,v in pairs(e.items) do if v.count>0 and matches(v.item,i) then
        if seen then empty=nil;break end;seen=true
      end end
    end
    local remaining=-delta
    for k,v in pairs(e.items) do if matches(v.item,i) then local n=math.min(remaining,v.count);change(k,v,-n);remaining=remaining-n end end
  else
    local k=itemKey(i);local v=e.items[k]
    if not v then for other,value in pairs(e.items) do if matches(value.item,i) then k,v=other,value;break end end end
    change(k,v or {item=item(i),count=0,maxSize=maximum,stacks=0,room=0},delta)
  end
  e.estimated=true
end
local function emptied(s)
  return s.knownTaken==s.taken and (s.returned or 0)==0 and s.emptied or nil
end
local function short(storage,i,returned,touched)
  if not storage then return end
  local key=inventory(storage) or storage;local e=db[key];if not e then e={items={},capacityUnknown=true,estimated=true};db[key]=e end
  local n=quantity(e,i);adjust(storage,i,-n,nil,touched)
  if returned>0 then adjust(storage,i,returned,nil,touched) end
  touched[key]=storage
end
local function full(storage,i,touched)
  if not storage then return end
  local key=inventory(storage) or storage;local e=db[key];if not e then e={items={},capacityUnknown=true,estimated=true};db[key]=e end
  e.full=e.full or {};e.full[itemKey(i)]=true;e.freeSlots=0
  for _,v in pairs(e.items) do if matches(v.item,i) then v.room=0 end end
  e.estimated=true;touched[key]=storage
end
local storeTargets
-- A drone left holding items takes them to stock; the put receipts book them back.
local function deliverHeld(name)
  local d;for _,x in ipairs(logistics.drones()) do if x.name==name then d=x end end
  if not d or d.state~="held" or not d.held then return end
  local stock,source=entries(),map.place(d.home);local planned,steps={},{}
  for _,h in ipairs(d.held) do
    local i=item(h.item);local maximum=limit(i);local remaining=h.count
    for _,c in ipairs(storeTargets(stock,i,nil,source,maximum,planned)) do
      if remaining==0 then break end
      local n=math.min(remaining,c.capacity)
      planned[#planned+1]={key=c.key,storage=c.storage,item=i,count=n,direction='put',maximum=maximum}
      steps[#steps+1]={put=c.storage,item=i,count=n,maxSize=maximum};remaining=remaining-n
    end
  end
  if #steps>0 then submit(steps,{drone=name,cargo=true,drones=1,retries=0},planned) end
end
local function finished(_,id)
  local s=logistics.status(id);if not s then return end
  syncMapRevision()
  -- Missing/failed read legs must not leave previous fuel observations valid.
  local reads=pendingReads[id]
  for _,e in ipairs(reads or {}) do invalidateRead(e) end
  pendingReads[id]=nil
  endpointStorages=map.storages()
  local touched={};local observed=false
  learn(s.item,s.maxSize)
  if s.steps then
    -- Agent ledger subtracts returns AND overflow from take.moved, so use
    -- taken-returned for the source, not moved. Puts report actual deliveries.
    for _,step in ipairs(s.steps) do
      learn(step.item,step.maxSize)
      for _,stack in pairs(step.listing or {}) do learn(stack,stack.maxSize) end
      if step.read then
        if readCurrent(reads,step.read) then
          observeRole(step.read,step)
          local storage=at(step.read);if storage and not step.read.slots then observed=observe(storage,step) or observed end
        else invalidateRead(step.read) end
      elseif step.take then
        mutationKeys({step.take})
        local storage=at(step.take);adjust(storage,step.item,-(step.taken or 0)+(step.returned or 0),step.maxSize,touched,emptied(step))
        -- A full-face short reports observed remaining stock, not necessarily
        -- zero (e.g. unmergeable NBT variants filled the drone's cargo slots).
        -- A single-slot short shows that slot held less than planned.
        if step.short and not step.take.slots then short(storage,step.item,step.found or 0,touched)
        elseif step.short and step.claimed then adjust(storage,step.item,-math.max(0,step.claimed-(step.taken or 0)-(step.found or 0)),nil,touched) end
        adjust(at(s.overflowEndpoint),step.item,step.overflow or 0,step.maxSize,touched)
      elseif step.put then
        mutationKeys({step.put})
        adjust(at(step.put),step.item,step.moved or 0,step.maxSize,touched)
        if (step.refused or 0)>0 and not step.put.slots then full(at(step.put),step.item,touched) end
      end
    end
  elseif s.item then
    if s.from then mutationKeys({s.from}) end;if s.to then mutationKeys({s.to}) end
    adjust(at(s.from),s.item,-(s.taken or 0)+(s.returned or 0),s.maxSize,touched,emptied(s))
    if s.short and s.from and not s.from.slots then short(at(s.from),s.item,s.found or 0,touched) end
    adjust(at(s.to),s.item,s.moved or 0,s.maxSize,touched)
    adjust(at(s.overflowEndpoint),s.item,s.overflow or 0,s.maxSize,touched)
    if (s.refused or 0)>0 and s.to and not s.to.slots then full(at(s.to),s.item,touched) end
  end
  if s.overflowEndpoint then mutationKeys({s.overflowEndpoint}) end
  local holders={};for _,h in ipairs(s.held or {}) do if not holders[h.drone] then holders[h.drone]=true;deliverHeld(h.drone) end end
  local mutation=pendingMutations[id]
  if mutation then
    local ids={};for key in pairs(mutation) do ids[#ids+1]=key end;invalidate(ids)
    for key in pairs(mutation) do
      mutationEpochs[key]=(mutationEpochs[key] or 0)+1
      local count=mutationCounts[key]-1;mutationCounts[key]=count>0 and count or nil
    end
    pendingMutations[id]=nil
  end
  for key in pairs(touched) do if db[key] then saveInventory(key) end end
  -- Release only after the final ledger has been incorporated in the catalogue.
  inFlight[id]=nil
  pendingCatalogue[id]=nil
  if observed or next(touched) then db_store:flush() end
  flight_store:delete("job_"..id);flight_store:flush()
  local learned=limitsDirty;saveLimits()
  if observed or next(touched) or learned then changed(id)
  else event.push('warehouse','settled',id) end
  endpointStorages=nil
end
event.listen("logistics",finished)
event.listen("logistics_held",function(_,name) deliverHeld(name) end)
local function positive(n) assert(type(n)=="number" and n>0 and n<math.huge and n%1==0,"positive count required") end
local function node(endpoint)
  if type(endpoint)=="string" then return assert(map.place(endpoint),"unknown endpoint") end
  return endpoint.storage and assert(map.place(endpoint.storage)) or endpoint.node
end
local function distance(a,b)
  return map.distances(map.place(b))[map.place(a)] or math.huge
end
-- Something else read this inventory whole (a robot its buffer): those counts are the truth.
function M.observed(storage,counts)
  local key=inventory(storage) or storage;local touched={}
  for _,v in pairs(db[key] and db[key].items or {}) do short(storage,v.item,0,touched) end
  for _,c in ipairs(counts) do short(storage,item(c.item),c.count,touched) end
  for k in pairs(touched) do if db[k] then saveInventory(k) end end
  if next(touched) then db_store:flush();changed() end
end
-- A machine used up n of an item it was given (known from the output collected).
function M.consumed(storage,i,n)
  local touched={};adjust(storage,item(i),-n,nil,touched)
  for key in pairs(touched) do if db[key] then saveInventory(key) end end
  if next(touched) then db_store:flush();changed() end
end
function M.fetch(i,n,to,opts)
  i=item(i);positive(n);local candidates,total={},0
  for _,faces in pairs(entries()) do
    local count=math.max(0,quantity(faces[1].entry,i)-reserved(faces[1].key,i,'take'))
    if count>0 then candidates[#candidates+1]={faces=faces,count=count};total=total+count end
  end
  if total<n then return nil,"requested "..n..", available "..total end
  table.sort(candidates,function(a,b) return a.count>b.count end)
  local steps,reservations,remaining,cursor={},{},n,1;total=0;local target=node(to)
  while remaining>0 and cursor<=#candidates do
    -- Route all equal-count inventories at the cut-off, preserving the
    -- distance tie-break, but never route lower-count unused inventories.
    local batch={};local count=candidates[cursor].count
    repeat
      local c=candidates[cursor];local best,dist=nil,math.huge
      for _,face in ipairs(c.faces) do local d=distance(face.storage,target)
        if d<dist or (d==dist and best and face.storage<best) then best,dist=face.storage,d end
      end
      if best then batch[#batch+1]={storage=best,distance=dist,count=count};total=total+count end
      cursor=cursor+1
    until cursor>#candidates or candidates[cursor].count~=count
    table.sort(batch,function(a,b) if a.distance~=b.distance then return a.distance<b.distance end;return a.storage<b.storage end)
    for _,c in ipairs(batch) do if remaining==0 then break end;local take=math.min(remaining,c.count)
      steps[#steps+1]={take=c.storage,item=i,count=take};remaining=remaining-take
      reservations[#reservations+1]={key=inventory(c.storage),storage=c.storage,item=i,count=take,direction='take'}
    end
  end
  if remaining>0 then return nil,"requested "..n..", available "..total end
  steps[#steps+1]={put=to,item=i,rest=true};return submit(steps,opts,reservations)
end
local function accepts(settings,i)
  if not settings.filter then return nil end
  for _,v in ipairs(settings.filter) do if matches(i,v) then return true end end;return false
end
local function targetOrder(a,b)
  if a.tier~=b.tier then return a.tier<b.tier end
  if a.tier==4 then
    if a.freeSlots~=b.freeSlots then return a.freeSlots>b.freeSlots end
  elseif a.priority~=b.priority then return a.priority>b.priority end
  return a.storage<b.storage
end
function M.store(i,n,from,opts)
  i=item(i);positive(n);local candidates,total,unknown={},0,0;local maximum=limit(i)
  for _,faces in pairs(entries()) do
    local uncertain
    for _,face in ipairs(faces) do
      local e=face.entry;local accept=accepts(face.settings,i)
      if accept~=false and e and not e.capacityUnknown then
        local held=quantity(e,i);local room=0;for _,v in pairs(e.items) do if matches(v.item,i) then room=room+v.room end end
        local occupied=0;for _,v in pairs(e.items) do occupied=occupied+v.count end
        local tier=accept and 1 or held>0 and 2 or occupied==0 and 3 or e.freeSlots>0 and 4 or nil
        local capacity=e.full and e.full[itemKey(i)] and 0 or math.max(0,e.freeSlots*maximum+room-incomingCapacity(face.key,i,maximum))
        if tier and capacity>0 then
          candidates[#candidates+1]={storage=face.storage,key=face.key,tier=tier,priority=face.settings.priority or 0,capacity=capacity,freeSlots=e.freeSlots}
        end
      elseif accept~=false and (not e or e.capacityUnknown) then uncertain=true end
    end
    if uncertain then unknown=unknown+1 end
  end
  table.sort(candidates,targetOrder)
  -- Interleave takes and puts, allowing a large request to split naturally.
  local steps,reservations,remaining,used={},{},n,{};local source=node(from)
  for _,c in ipairs(candidates) do if remaining==0 then break end
    if not used[c.key] and distance(c.storage,source)<math.huge then
      used[c.key]=true;total=total+c.capacity;local amount=math.min(remaining,c.capacity)
      steps[#steps+1]={take=from,item=i,count=amount};steps[#steps+1]={put=c.storage,item=i,count=amount};remaining=remaining-amount
      reservations[#reservations+1]={key=c.key,storage=c.storage,item=i,count=amount,direction='put',maximum=maximum}
    end
  end
  if remaining>0 then return nil,"requested "..n..", capacity "..total..", unknown inventories "..unknown end
  return submit(steps,opts,reservations)
end
-- Packed APIs keep one tracked job per confirmed cargo-sized tour. Fetches use
-- known stock; collections take expected output and settle from the receipt.
local function manyRequests(requests)
  assert(type(requests)=="table","requests required")
  local n=0;for k in pairs(requests) do
    assert(type(k)=="number" and k>0 and k%1==0,"dense requests required");n=n+1
  end
  local out={}
  for k=1,n do
    local r=requests[k];assert(type(r)=="table","item request required")
    positive(r.count);out[k]={item=item(r.item),count=r.count,to=r.to,waitFor=r.waitFor}
  end
  return out
end
local function cargoSlots()
  local minimum
  for _,d in ipairs(logistics.drones and logistics.drones() or {}) do
    local n=d.cargoSlots
    if type(n)=="number" and n>0 and n<math.huge and n%1==0 then minimum=math.min(minimum or n,n) end
  end
  assert(minimum,"unknown fleet cargo slots; wait for a confirmed drone")
  return minimum
end
local function overlap(a,b)
  return a.name==b.name and (a.damage or 0)==(b.damage or 0)
    and (not a.label or not b.label or a.label==b.label)
end
local function manyReserved(key,i,direction,planned)
  local count=0
  local function include(r)
    if r.key==key and r.direction==direction and overlap(r.item,i) then count=count+r.count end
  end
  for _,job in pairs(inFlight) do for _,r in ipairs(job) do include(r) end end
  for _,r in ipairs(planned) do include(r) end
  return count
end
local function sameInventory(a,b)
  local index=metadata();local seen={}
  for _,key in ipairs(identities(a) or {}) do seen[key]=true;local c=index.clusters[key];if c then seen[c]=true end end
  for _,key in ipairs(identities(b) or {}) do if seen[key] or seen[index.clusters[key]] then return true end end
  return false
end
local function sourceReservation(storage,i,count)
  return {key=inventory(storage) or storage,storage=storage,item=i,count=count,direction='take'}
end
local function manyEndpoint(value)
  local e=endpoint(value)
  assert(e and type(e.node)=="string" and type(e.side)=="number" and e.side>=0 and e.side<=5 and e.side%1==0,"unknown/invalid endpoint")
  assert(not map.node or map.node(e.node),"unknown endpoint node")
  if type(value)=="string" then return value end
  local out={node=e.node,side=e.side}
  if value.storage then out={storage=value.storage} end
  if value.slots then
    local cached=roleCache[e.node] and roleCache[e.node][e.side]
    out.slots=roleSlots(value.slots,cached and cached.size)
  end
  return out
end
local function observedSource(storage,i,reservedCount)
  local e=endpoint(storage);local cached=roleCache[e.node] and roleCache[e.node][e.side]
  if not cached then return end
  for _,key in ipairs(cached.ids) do if mutationCounts[key] then return end end
  local rows={}
  for slot=1,cached.size do
    local stack=cached.listing[slot];if stack==nil then return end
    if stack and matches(stack,i) then
      local skipped=math.min(reservedCount,stack.size);reservedCount=reservedCount-skipped
      if stack.size>skipped then rows[#rows+1]={slot=slot,count=stack.size-skipped,maxSize=stack.maxSize,
        stackKey="stack:"..e.node..":"..e.side..":"..slot} end
    end
  end
  return rows
end
local function addPieces(pieces,requestIndex,i,count,maximum,stacks,from,to,take,put)
  -- Separate observed stacks/source allocations are not assumed NBT-mergeable.
  local units=math.max(math.ceil(count/maximum),math.min(count,stacks or 1))
  while count>0 do
    local n=math.min(maximum,math.ceil(count/units))
    pieces[#pieces+1]={requestIndex=requestIndex,item=i,count=n,maximum=maximum,
      from=from,to=to,take=take,put=put}
    count=count-n;units=units-1
  end
end
local function packedJobs(requests,pieces,missing,slots,opts)
  -- Router identity limits must be consistent across every leg in a job.
  local maxima={}
  for _,p in ipairs(pieces) do local key=itemKey(p.item);maxima[key]=math.min(maxima[key] or p.maximum,p.maximum) end
  local normalized={}
  for _,p in ipairs(pieces) do
    local maximum=maxima[itemKey(p.item)];local count=p.count;local wait=p.waitFor or 0
    while count>0 do
      local part={};for key,value in pairs(p) do part[key]=value end
      part.maximum=maximum;part.count=math.min(count,maximum)
      part.waitFor=p.waitFor and math.min(wait,part.count);wait=wait-(part.waitFor or 0)
      normalized[#normalized+1]=part;count=count-part.count
    end
  end
  pieces=normalized
  local out={};local cursor=1
  while cursor<=#pieces do
    local job={steps={},reservations={},expected={}};local indexes={}
    local last=cursor-1;local occupied,held=0,{}
    for k=cursor,#pieces do
      local p=pieces[k];local key=p.stackKey or p
      local before=held[key] or 0
      local extra=math.ceil((before+p.count)/p.maximum)-math.ceil(before/p.maximum)
      if occupied+extra>slots then break end
      held[key]=before+p.count;occupied=occupied+extra;last=k
    end
    assert(last>=cursor,"allocation exceeds confirmed cargo slots")
    local function expect(index,count)
      local row=indexes[index]
      if not row then
        row=#job.expected+1;indexes[index]=row
        job.expected[row]={item=item(requests[index].item),count=0,requestIndex=index}
      end
      job.expected[row].count=job.expected[row].count+count;return row
    end
    if #out==0 then for index=1,#requests do local count=missing[index] or 0;if count>0 then expect(index,count) end end end
    for k=cursor,last do local p=pieces[k];local index=expect(p.requestIndex,p.count)
      job.steps[#job.steps+1]={take=p.from,item=item(p.item),count=p.count,maxSize=p.maximum,expectedIndex=index,waitFor=p.waitFor}
      if p.take then local r=copy(p.take);r.count=p.count;job.reservations[#job.reservations+1]=r end
      if p.put then local r=copy(p.put);r.count=p.count;job.reservations[#job.reservations+1]=r end
    end
    -- Visit sources before delivery. Only fragments proven to be from the
    -- same exact observed stack may share a cargo slot across requests.
    for k=cursor,last do local p=pieces[k]
      job.steps[#job.steps+1]={put=p.to,item=item(p.item),count=p.count,maxSize=p.maximum,
        expectedIndex=indexes[p.requestIndex]}
    end
    job.opts=copy(opts or {});job.opts.requests=nil
    job.opts.drones=1;job.opts.split=false;job.opts.expectedItems=job.expected
    out[#out+1]=job;cursor=last+1
  end
  return out
end
local function submitPacked(jobs)
  local ids={}
  for _,job in ipairs(jobs) do
    local ok,id,err=pcall(submit,job.steps,job.opts,job.reservations)
    if not ok then return nil,id,ids end
    if not id then return nil,err,ids end
    ids[#ids+1]=id
  end
  return ids
end
function M.fetchMany(requests,to,opts)
  local ok,jobs=pcall(function()
    syncMapRevision();requests=manyRequests(requests)
    assert(opts==nil or type(opts)=="table","options required")
    for _,r in ipairs(requests) do
      local destination=r.to;if destination==nil then destination=to end
      r.to=manyEndpoint(destination);r.target=node(r.to)
    end
    local slots=cargoSlots();local stock=entries()
    local pieces,planned,missing={},{},{}
    for index,r in ipairs(requests) do
      local i,remaining=r.item,r.count;local maximum=limit(r.item)
      local candidates={}
      for _,faces in pairs(stock) do
        local e=faces[1].entry;local held=quantity(e,i)
        local available=math.max(0,held-manyReserved(faces[1].key,i,'take',planned))
        if available>0 then
          local best,dist,bestObserved
          for _,face in ipairs(faces) do
            if not sameInventory(face.storage,r.to) then
              local d=distance(face.storage,r.target)
              local ep=endpoint(face.storage)
              local observed=roleCache[ep.node] and roleCache[ep.node][ep.side]~=nil or false
              if d<math.huge and (not dist or d<dist or (d==dist and
                ((observed and not bestObserved) or (observed==bestObserved and face.storage<best)))) then
                best,dist,bestObserved=face.storage,d,observed
              end
            end
          end
          if best then
            local stacks=0
            for _,v in pairs(e.items) do if matches(v.item,i) then
              local size=v.maxSize or maximum
              stacks=stacks+(v.stacks or math.ceil(v.count/size))
              maximum=math.min(maximum,size)
            end end
            candidates[#candidates+1]={storage=best,key=faces[1].key,count=available,stacks=stacks,distance=dist,
              rows=observedSource(best,i,manyReserved(faces[1].key,i,'take',planned))}
          end
        end
      end
      table.sort(candidates,function(a,b)
        if a.count~=b.count then return a.count>b.count end
        if a.distance~=b.distance then return a.distance<b.distance end
        return a.storage<b.storage
      end)
      for _,c in ipairs(candidates) do if remaining==0 then break end
        local n=math.min(remaining,c.count);local reservation=sourceReservation(c.storage,i,n)
        planned[#planned+1]=reservation
        if c.rows then
          local left=n
          for _,row in ipairs(c.rows) do if left==0 then break end
            local amount=math.min(left,row.count);local first=#pieces+1
            addPieces(pieces,index,i,amount,math.min(maximum,row.maxSize),1,
              {storage=c.storage,slots={row.slot}},r.to,reservation)
            for k=first,#pieces do pieces[k].stackKey=row.stackKey end
            left=left-amount
          end
          assert(left==0,"observed source disagrees with stock catalogue; rescan source")
        else addPieces(pieces,index,i,n,maximum,c.stacks,c.storage,r.to,reservation) end
        remaining=remaining-n
      end
      missing[index]=remaining
    end
    assert(#pieces>0 or #requests==0,"requested items unavailable")
    return packedJobs(requests,pieces,missing,slots,opts)
  end)
  if not ok then return nil,jobs,{} end
  return submitPacked(jobs)
end
-- Stock storages that can take item i coming from `from`, best first.
function storeTargets(stock,i,from,source,maximum,planned)
  local candidates={}
  for _,faces in pairs(stock) do for _,face in ipairs(faces) do
    local entry=face.entry;local accept=accepts(face.settings,i)
    if accept~=false and entry and not entry.capacityUnknown and not sameInventory(face.storage,from) then
      local held=quantity(entry,i);local room,occupied=0,0
      for _,v in pairs(entry.items) do occupied=occupied+v.count;if matches(v.item,i) then room=room+v.room end end
      local tier=accept and 1 or held>0 and 2 or occupied==0 and 3 or entry.freeSlots>0 and 4 or nil
      local capacity=entry.full and entry.full[itemKey(i)] and 0 or math.max(0,
        entry.freeSlots*maximum+room-incomingCapacity(face.key,i,maximum,planned))
      if tier and capacity>0 and distance(face.storage,source)<math.huge then
        candidates[#candidates+1]={storage=face.storage,key=face.key,tier=tier,
          priority=face.settings.priority or 0,capacity=capacity,freeSlots=entry.freeSlots}
      end
    end
  end end
  table.sort(candidates,targetOrder)
  return candidates
end
-- Take up to the expected count of each item from a machine role or robot buffer
-- (a storage name, or {storage,slots}) and put it in stock, without looking
-- first: the MES knows what should be there. Each item's receipt says how many
-- were actually taken.
function M.collect(from,requests,opts)
  local ok,jobs=pcall(function()
    syncMapRevision();if type(from)=="string" then from={storage=from} end
    assert(type(from)=="table" and from.storage,"source storage required")
    assert(endpoint(from),"unknown source");requests=manyRequests(requests)
    local stock=entries();local source=node(from);local planned,pieces,missing={},{},{}
    for index,r in ipairs(requests) do
      -- An item never seen yet is planned at 64; the drone's report teaches the real limit.
      local i=r.item;local maximum=limit(i);local remaining=r.count
      local to=r.to and manyEndpoint(r.to)
      for _,c in ipairs(storeTargets(stock,i,from,source,maximum,planned)) do
        if remaining==0 then break end
        if not to or sameInventory(c.storage,to) then
        local n=math.min(remaining,c.capacity)
        local put={key=c.key,storage=c.storage,item=i,count=n,direction='put',maximum=maximum}
        local take=stock[inventory(from.storage)] and sourceReservation(from.storage,i,n)
        planned[#planned+1]=put
        addPieces(pieces,index,i,n,maximum,1,{storage=from.storage,slots=from.slots},to or c.storage,take,put)
        remaining=remaining-n
        end
      end
      assert(remaining==0 or opts and opts.partial,"requested "..r.count..", insufficient warehouse capacity for "..limitKey(i));missing[index]=remaining
    end
    local o=copy(opts or {});o.partial=nil;o.oneTour=nil;o.retries=0
    local left={};for _,p in ipairs(pieces) do local i=p.requestIndex;left[i]=left[i] or requests[i].waitFor or 0;p.waitFor=math.min(left[i],p.count);left[i]=left[i]-p.waitFor end
    local jobs=packedJobs(requests,pieces,missing,cargoSlots(),o)
    if opts and opts.oneTour then while #jobs>1 do table.remove(jobs) end end
    return jobs
  end)
  if not ok then return nil,jobs,{} end
  return submitPacked(jobs)
end
for id in pairs(inFlight) do
  local s=logistics.status(id)
  if not s then
    inFlight[id]=nil;pendingCatalogue[id]=nil;flight_store:delete("job_"..id);flight_store:flush()
  elseif s.state=="done" or s.state=="failed" or s.state=="partial" then finished("logistics",id) end
end
-- Restore all mutations before capturing read provenance.
local reads={}
for id in pairs(inFlight) do
  local movements={};reads[id]={}
  for _,s in ipairs(logistics.status(id).steps or {}) do
    if s.take or s.put then movements[#movements+1]=s.take or s.put end
    if s.read then reads[id][#reads[id]+1]=s.read end
  end
  if #movements>0 then beginMutation(id,movements) end
end
for id,endpoints in pairs(reads) do
  if #endpoints>0 then pendingReads[id]=readProvenance(endpoints) end
end
return M
