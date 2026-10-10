local M={}
local S=require('mes_state')
local function pick(t,fields)
 local o={};for k in fields:gmatch('%S+') do o[k]=t[k] end;return o
end
local function opts(t)
 if type(t)=='function' then return nil end
 if type(t)~='table' then return t end
 local o={};for k,v in pairs(t) do o[k]=opts(v) end;return o
end
local function idx(list,value)
 for n,v in ipairs(list or {}) do if v==value then return n end end
end
local function ref(r)
 if r then return {run=r.run.id,stage=r.stage.index,group=r.group} end
end
local af='kind token ids submitted error partialOk sourceRetry accounted problem'
local function act(a) return a and pick(a,af) end
local function pack(b)
 if not b then return end
 local o=pick(b,'kind endpoint registered finished partial error role')
 o.records={};o.physical={};o.action=act(b.action)
 for _,r in ipairs(b.records) do o.records[#o.records+1]=idx(b.stage.itemsMoved,r) end
 for _,r in ipairs(b.physical) do o.physical[#o.physical+1]=idx(b.stage.physicalJobs,r) end
 return o
end
local rf='id item qty status started now trips sequence claims inflight fuelAvailable stopping reason error uncertain served callbackError'
local sf='state status detail error done total crafter groups locations assigned started craftStarted craftFinished released finished jobId submitted admission receipt toolReservations loadsDelivered phase robotLock bufferLock buffer prepared toolWithdrawals robotResult robotResultAt'
local wf='group left active blocked admitting error deadline'
local lf='sequence ops remaining consumed fuelAdditional position duration quarantined unresolved'
local lists={mv='itemsMoved',pj='physicalJobs',ld='loadLedger',sa='storeAllocations'}
function M.open()
 local store=require('store').open('/etc/mes.state')
 local db=store:load()
 return {store=store,db=db,known={},done=(db.ids or {}).done or {}}
end
function M.plan(p,run)
 local key='plan_'..run.id
 p.store:put(key,{plan=run.plan,opts=opts(run.opts)});p.known[key]=true
end
function M.save(p,w,h,active,seq,snap)
 local keep={}
 local function put(k,v) keep[k]=true;p.known[k]=true;p.store:put(k,v) end
 local finished={};local old={}
 for _,id in ipairs(p.done) do old[id]=true end
 for id,r in pairs(h) do
  if r.status~='running' and not old[id] then finished[#finished+1]=id end
 end
 table.sort(finished)
 for _,id in ipairs(finished) do
  h[id]=snap(h[id]);put('done_'..id,h[id]);p.done[#p.done+1]=id
 end
 while #p.done>20 do local id=table.remove(p.done,1);h[id]=nil;keep['done_'..id]=nil end
 for _,id in ipairs(p.done) do keep['done_'..id]=true end
 put('ids',{run=seq,done=p.done})
 for _,r in ipairs(active) do
  local id=r.id
  keep['plan_'..id]=true;put('run_'..id,pick(r,rf))
  for i,s in ipairs(r.stages) do
   local key=id..'_'..i
   local v=pick(s,sf)
   v.bundle=pack(s.bundle);v.bufferRead=act(s.bufferRead);v.robotAction=act(s.robotAction)
   if s.machineWork then
    v.work={};for _,request in ipairs(s.machineWork.requests) do v.work[#v.work+1]=pick(request,wf) end
   end
   put('st_'..key,v)
   for prefix,field in pairs(lists) do
    for n,row in ipairs(s[field] or {}) do put(prefix..'_'..key..'_'..n,row) end
   end
  end
 end
 local world={robots={},buffers={},toolReservations=w.toolReservations,waiting=w.waiting,serves=w.serves}
 for addr,r in pairs(w.robots) do world.robots[addr]=pick(r,'state run step last') end
 for key,b in pairs(w.buffers) do world.buffers[key]=pick(b,'state owner run step') end
 put('world',world)
 for name,m in pairs(w.machines) do
  put('mach_'..name,{state=m.state,type=m.type,fuel=m.fuel and pick(m.fuel,'credit admitted processed')})
 end
 for name,loads in pairs(w.stuck or {}) do
  local v={};for _,l in ipairs(loads) do
   v[#v+1]={unresolved=l.unresolved,record=l.record,inputs=l.request.inputs,outputs=l.request.outputs}
  end
  put('stuck_'..name,v)
 end
 for name,g in pairs(w.groups) do
  local v=pick(g,'name roles phase awaitCollection inputRecipe sequence tripSeconds')
  v.type=w.machines[name].type;v.runs={};v.pending={};v.loads={}
  for id in pairs(g.runs) do v.runs[#v.runs+1]=id end;table.sort(v.runs)
  for _,r in ipairs(g.pending) do v.pending[#v.pending+1]=ref(r) end
  v.loading=g.loading and g.loading.sequence
  for _,l in ipairs(g.loads) do
   local q=pick(l,lf);q.request=ref(l.request);q.donor=ref(l.donor)
   q.record=idx(l.request.stage.loadLedger,l.record);q.fetches={};q.bundle=pack(l.bundle)
   for _,f in ipairs(l.fetches) do
    local a=pick(f,'item count endpoint fuel role');a.receipt=idx(l.request.stage.itemsMoved,f.receipt)
    q.fetches[#q.fetches+1]=a
   end
   v.loads[#v.loads+1]=q
  end
  if g.collection then
   local c=g.collection;v.collection={requests={},byItem={},bundle=pack(c.bundle)}
   for _,r in ipairs(c.requests) do
    local q=pick(r,'item count waitFor');q.receipt=idx(c.bundle.stage.itemsMoved,r.receipt)
    v.collection.requests[#v.collection.requests+1]=q
   end
   for item,rows in pairs(c.byItem) do
    local a={};for _,row in ipairs(rows) do a[#a+1]={load=row.load.sequence,count=row.count} end
    v.collection.byItem[item]=a
   end
  end
  if g.recovery then
   local c=g.recovery;v.recovery={request=ref(c.request),phase=c.phase,read=act(c.read)}
   if c.bundles then v.recovery.bundles={};for _,b in ipairs(c.bundles) do
    v.recovery.bundles[#v.recovery.bundles+1]=pack(b)
   end end
  end
  put('grp_'..name,v)
 end
 for key in pairs(p.db) do p.known[key]=true end
 for key in pairs(p.known) do if not keep[key] then p.store:delete(key) end end
 p.known=keep;p.db={};p.store:flush()
end
local function ov(t,v) for k,x in pairs(v or {}) do t[k]=x end;return t end
function M.restore(p,w,config,ports,client,now)
 local cfg
 local db=p.db;local h,active,watched={},{},{}
 local seq=(db.ids or {}).run or 0
 ov(w,db.world);w.now=now;w.stuck={}
 for _,id in ipairs(p.done) do h[id]=db['done_'..id] end
 for key,v in pairs(db) do
  local name=key:match('^mach_(.*)')
  if name then w.machines[name]=ov({loads={}},v) end
  name=key:match('^stuck_(.*)')
  if name then
   w.stuck[name]={};for _,l in ipairs(v) do
    w.stuck[name][#w.stuck[name]+1]={unresolved=l.unresolved,record=l.record,request={inputs=l.inputs,outputs=l.outputs}}
   end
  end
 end
 local function ra(a,r)
  if not a then return end
  if a.accounted then a.results={} else
   r.actions[a.token]=a;for _,id in ipairs(a.ids or {}) do watched[id]=r.id end
  end
  return a
 end
 local function rb(b,r,s)
  if not b then return end
  b.run=r;b.stage=s;b.action=ra(b.action,r)
  for i,n in ipairs(b.records) do b.records[i]=s.itemsMoved[n] end
  for i,n in ipairs(b.physical) do b.physical[i]=s.physicalJobs[n] end
  return b
 end
 for id=1,seq do
  local saved=db['run_'..id]
  if saved then
   cfg=cfg or config()
   local plan=db['plan_'..id]
   local r=S.new(id,plan.plan,cfg,plan.opts,w,ports(id,cfg),now)
   ov(r,saved);r.now=now;r.started=r.started+now-saved.now
   h[id]=r;active[#active+1]=r
   for i,s in ipairs(r.stages) do
    local key=id..'_'..i;local v=db['st_'..key]
    ov(s,v)
    for _,field in ipairs({'started','assigned','craftStarted'}) do
     if s[field] then s[field]=s[field]+now-saved.now end
    end
    for prefix,field in pairs(lists) do
     s[field]={};local n=1
     while db[prefix..'_'..key..'_'..n] do
      s[field][n]=db[prefix..'_'..key..'_'..n];n=n+1
     end
    end
    s.bundle=rb(s.bundle,r,s)
    s.bufferRead=ra(s.bufferRead,r);s.robotAction=ra(s.robotAction,r)
    if v.work then
     local work=S.machineRequests(r,s)
     for n,request in ipairs(work.requests) do ov(request,v.work[n]);request.deadline=now+60 end
     s.work=nil
    end
    if s.state~='waiting' and s.state~='done' and s.state~='failed' then r.active[#r.active+1]=i end
   end
   r.stage=r.active[1]
  end
 end
 local function request(ref)
  if not ref then return end
  for _,r in ipairs(h[ref.run].stages[ref.stage].machineWork.requests) do
   if r.group==ref.group then return r end
  end
 end
 for key,v in pairs(db) do
  local name=key:match('^grp_(.*)')
  if name then
   local g=ov({mt=cfg.machineTypes[v.type],pending={},runs={},loads={}},v)
   g.type=nil;g.opts=h[v.runs[1]].opts;g.fuel=w.machines[name].fuel
   g.quarantined=w.stuck[name] or {};g.inputDue=now;g.outputDue=math.huge
   g.inputBackoff=0.5;g.outputBackoff=0.5
   g.runs={};for _,id in ipairs(v.runs) do g.runs[id]=true end
   g.pending={};for _,ref in ipairs(v.pending) do g.pending[#g.pending+1]=request(ref) end
   local loads={};g.loads={}
   for _,l in ipairs(v.loads) do
    if l.duration~=nil then g.outputDue=now end
    l.request=request(l.request);l.donor=request(l.donor)
    local r,s=l.request.run,l.request.stage
    l.record=s.loadLedger[l.record];l.due=now;l.deadline=now+(l.duration or 0)+60
    for _,f in ipairs(l.fetches) do f.receipt=s.itemsMoved[f.receipt] end
    l.bundle=rb(l.bundle,r,s);g.loads[#g.loads+1]=l;loads[l.sequence]=l
   end
   g.loading=loads[v.loading]
   if g.collection then
    local c=g.collection;local owner
    for _,l in ipairs(g.loads) do for _,n in pairs(l.remaining) do if n>0 then owner=owner or l.request end end end
    for _,r in ipairs(c.requests) do r.receipt=owner.stage.itemsMoved[r.receipt] end
    for _,rows in pairs(c.byItem) do for _,row in ipairs(rows) do row.load=loads[row.load] end end
    c.bundle=rb(c.bundle,owner.run,owner.stage)
   end
   if g.recovery then
    local c=g.recovery;c.request=request(c.request)
    c.read=ra(c.read,c.request.run)
    for i,b in ipairs(c.bundles or {}) do c.bundles[i]=rb(b,c.request.run,c.request.stage) end
   end
   w.groups[name]=g
   for _,l in ipairs(g.loads) do w.machines[name].loads[#w.machines[name].loads+1]=S.copy(l.record) end
   for _,l in ipairs(g.quarantined) do w.machines[name].loads[#w.machines[name].loads+1]=S.copy(l.record) end
  end
 end
 for _,r in ipairs(active) do for _,s in ipairs(r.stages) do
  if s.phase=='robot_crafting' and not s.robotResult then client.adopt(s.robotAction.token,s.robotLock,s.jobId,r.opts.client) end
 end end
 return h,active,seq,watched
end
return M
