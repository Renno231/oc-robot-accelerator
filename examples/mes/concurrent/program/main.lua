local fs=require('filesystem');local computer=require('computer');local event=require('event')
local serialization=require('serialization');local component=require('component')
assert(loadfile('/home/program/install.lua'))()
local hosts=require('hosts');local fixtureWake='T13Fixture-controller'
assert(hosts.addHost(component.modem.address,computer.address(),'controller',fixtureWake,{}))
for _,name in ipairs({'cbor','store','map','logistics','warehouse','stations','iochest','stats','housekeeping'}) do
  assert(fs.copy('/home/program/lib/'..name..'.lua','/lib/'..name..'.lua'))
end
fs.makeDirectory('/lib/logistics')
assert(fs.copy('/home/program/drone/agent.lua','/lib/logistics/agent.lua'))
assert(fs.copy('/home/program/drone/sensor.lua','/lib/logistics/sensor.lua'))
local lg=require('logistics');local wh=require('warehouse');local mes=require('mes')
local case=assert(loadfile('/home/program/case.lua'))().name
local start=computer.uptime();local totals={trips=0,moved=0,jobs=0};local jobs={}
local function save(path,value)
  local data=serialization.serialize(value,false)
  local f=assert(io.open(path,'w'));assert(f:write(data),'evidence write failed: '..path)
  if f.flush then assert(f:flush(),'evidence flush failed: '..path) end
  local closed,err=f:close();assert(closed~=false and not err,err or ('evidence close failed: '..path))
end
local componentCounter=package.loaded.runner_component_calls
local function startComponentCalls()
  return componentCounter and componentCounter.snapshot()
end
local function finishComponentCalls(result,before)
  if before then
    result.componentCalls=componentCounter.delta(before,componentCounter.snapshot())
    save('/home/component-calls.lua',result.componentCalls)
  end
end
local function wait(fn,seconds)
  local untilTime=computer.uptime()+seconds
  repeat if fn() then return end;event.pull(0.1) until computer.uptime()>untilTime
  error('MES fixture timeout')
end
local function done(id)
  assert(id);wait(function()
    local s=lg.status(id)
    local terminal=s and (s.state=='done' or s.state=='partial' or s.state=='failed')
    return terminal and (not wh.settled or wh.settled(id)==true)
  end,1800)
  return assert(lg.status(id))
end
event.listen('logistics',function(_,id)
  local s=assert(lg.status(id));jobs[id]=s
  totals.trips=totals.trips+(s.trips or 0);totals.moved=totals.moved+(s.moved or 0);totals.jobs=totals.jobs+1
end)
local function latestJobId()
  local rows=lg.jobs(true,1,1);return rows[1] and rows[1].id or 0
end
local function finishTripAccounting(result)
  -- Warehouse settlement can precede this fixture's completion callback.
  -- Drain it before serializing counters (T11 omitted its final empty-check).
  local last=latestJobId()
  wait(function() for id=1,last do if not jobs[id] then return false end end;return true end,60)
  local total,mesTrips=0,0
  local window=result.mesTripWindow
  for id,s in pairs(jobs) do
    total=total+(s.trips or 0)
    if window and id>=window.first and id<=window.last then mesTrips=mesTrips+(s.trips or 0) end
  end
  assert(total==totals.trips,'trip observer accounting mismatch')
  result.trips=total;result.mesTrips=mesTrips;result.harnessTrips=total-mesTrips
  local busy={}
  for _,d in ipairs(lg.drones()) do busy[d.name]={seconds=0,mesSeconds=0,trips=0,mesTrips=0} end
  for id,s in pairs(jobs) do for _,t in ipairs(s.tripTimings or {}) do
    local b=busy[t.drone]
    if b and t.startedAt and t.finishedAt and not t.uncertain then
      local seconds=t.finishedAt-t.startedAt;b.seconds=b.seconds+seconds;b.trips=b.trips+1
      if window and id>=window.first and id<=window.last then
        b.mesSeconds=b.mesSeconds+seconds;b.mesTrips=b.mesTrips+1
      end
    end
  end end
  
  local kinds={movement=0,shortCollect=0,first=0,input=0,output=0,shorts={},refusals={},jobs={}}
  local collect={};for _,r in ipairs(mes.runs()) do for _,s in ipairs(mes.status(r.id).stages) do
    for _,p in ipairs(s.physicalJobs or {}) do if p.kind=='collect' then collect[p.job]=true end end
  end end
  local roles,fed={},{};local map=require('map')
  local function key(e) return e.node..':'..e.side end
  for name,g in pairs(wh.groups()) do for role,storage in pairs(g.roles) do
    roles[key(assert(map.storage(storage))) ]={role=role,group=name}
  end end
  if window then for id=window.first,window.last do
    local j=assert(jobs[id]);local kind,group='input'
    for _,s in ipairs(j.steps or {}) do
      if s.take or s.put then kind='movement';local e=s.put or s.take;local r=roles[key(e)]
        if r then group=r.group;if r.role=='buffer' then fed[key(e)]=s.put~=nil end end
      elseif s.roleKey then kind='first'
      elseif s.read then local r=roles[key(s.read)]
        if r and r.role=='output' then kind='output'
        elseif r and r.role=='buffer' then kind=fed[key(s.read)] and 'output' or 'first' end
      end
    end
    if collect[id] then
      local need,moved,short=0,0,false
      for _,r in ipairs(j.perItem or {}) do need=need+r.requested;moved=moved+r.moved;short=short or r.moved<r.requested end
      if short then kind='shortCollect';kinds.shorts[#kinds.shorts+1]={job=id,trips=j.trips,requested=need,moved=moved,items=j.perItem} end
    end
    kinds[kind]=kinds[kind]+(j.trips or 0)
    kinds.jobs[#kinds.jobs+1]={id=id,kind=kind,trips=j.trips,queuedAt=j.queuedAt,tripTimings=j.tripTimings,collectItems=collect[id] and j.perItem or nil}
    if (j.refused or 0)>0 then kinds.refusals[#kinds.refusals+1]={job=id,group=group,refused=j.refused,items=j.perItem,finishedAt=j.finishedAt} end
  end end
  kinds.following={}
  if window then for id,j in pairs(jobs) do if id>window.last then for _,t in ipairs(j.tripTimings or {}) do
    local p=kinds.following[t.drone]
    if not p or t.startedAt<p.startedAt then kinds.following[t.drone]={job=id,trip=t.trip,startedAt=t.startedAt,queuedAt=j.queuedAt} end
  end end end end
  assert(kinds.movement+kinds.shortCollect+kinds.first+kinds.input+kinds.output==mesTrips,'trip kind accounting mismatch')
  result.tripKinds=kinds

  result.droneBusy=busy
end
local function mesTiming(outcome)
  local timing={droneCount=#lg.drones(),cpus={},fetches={},arrivalBasis='controller-observed job completion (delivery plus return), warehouse settled before mes.wait'}
  for i,s in ipairs(outcome.stages) do
    if s.kind=='robot' then
      timing.cpus[#timing.cpus+1]={stage=i,crafter=s.crafter,assigned=s.assigned or s.started,
        released=s.released,craftStarted=s.craftStarted,craftFinished=s.craftFinished}
    end
    for _,move in ipairs(s.physicalJobs or s.itemsMoved or {}) do
      if move.kind=='fetch' and move.job then
        local j=assert(jobs[move.job],'fetch observer missing')
        timing.fetches[#timing.fetches+1]={stage=i,item=move.item,storage=move.storage,job=move.job,
          queuedAt=j.queuedAt,dispatchedAt=j.dispatchedAt,arrivedAt=j.finishedAt}
      end
    end
  end
  return timing
end
local address,distances;local addresses={}
distances={};component.modem.open(27105)
event.listen('modem_message',function(_,_,sender,port,distance,token,robot,cpu,cid,wake)
  if port==27105 and token=='mes_robot_ready' then
    assert(robot==sender and type(cid)=='string' and type(wake)=='string')
    assert(hosts.addHost(robot,cid,cpu,wake,{service='craftServer'},true))
    addresses[cpu]=robot;address=robot
  end
  if port==27103 and token=='lgx_hello' then distances[sender]=distance end
end)
local setup=assert(loadfile('/home/program/setup.lua'))()
wait(function() component.modem.broadcast(27105,'mes_robot_query',computer.address(),fixtureWake);return addresses.cpu1~=nil and addresses.cpu2~=nil end,60)
save('/etc/mes.cfg',{crafters={cpu1={robot=addresses.cpu1},cpu2={robot=addresses.cpu2}},machineTypes={furnace={inputs={'input'},output='output',
  roles={'input','fuel','output'},roleSlots={input={1},fuel={1},output={1}},
  fuel={role='fuel',item='minecraft:coal',per=8},batch=64,seconds=10,blocking=false}}})
wait(function() return #lg.pending()==6 end,60)
local pending=lg.pending();table.sort(pending,function(a,b) return (distances[a] or math.huge)<(distances[b] or math.huge) end)
for i,id in ipairs(pending) do assert(lg.register(id,'d'..i,setup.homes[i])) end
wait(function() local ds=lg.drones();if #ds~=6 then return false end;for _,d in ipairs(ds) do if d.state~='idle' then return false end end;return true end,60)
local function scan(storages)
  for _,id in ipairs(wh.scan(storages)) do assert(done(id).state=='done') end
end
scan()
local function item(id)
  local name,damage=id:match('^(.*):(%d+)$');return {name=name or id,damage=tonumber(damage) or 0}
end
local function count(id) return wh.count(item(id)) end
local function read(storage)
  local s=done(lg.job({{read=storage}},{drones=1,retries=0}));assert(s.state=='done')
  return s.steps[1].listing or {}
end
local function amount(listing,id)
  local i=item(id);local n=0
  for _,s in pairs(listing) do if s.name==i.name and (s.damage or 0)==i.damage then n=n+s.size end end
  return n
end


local result={case=case,status='running',runs={},robotIntervals={},furnaceLoads={}}
local f=assert(io.open('/home/program/recipes.tsv'));local text=f:read('*a');f:close()
local archive=assert(require('liblz16').open('/usr/lib/recipes/minecraft.dblz','wb'));assert(archive:write(text));archive:close()
local builder=require('recipes.build');local db=builder.build();assert(builder.save(db));require('recipes').install(db)
local recipes=require('recipes')
assert(recipes.registerProcessingRecipe('minecraft:coal:1','furnace',{recipe={'minecraft:log'},qty=1}))
assert(recipes.registerProcessingRecipe('minecraft:brick','furnace',{recipe={'minecraft:clay_ball'},qty=1}))
local a=assert(mes.plan('minecraft:torch',16));local b=assert(mes.plan('minecraft:brick_block',16))
local names={};event.listen('mes',function(_,kind,id)
  if kind=='done' then save('/home/concurrent-done'..assert(names[id]),{id=id,at=computer.uptime()}) end
end)
result.mesTripWindow={first=latestJobId()+1}
save('/home/concurrent-submit1',{at=computer.uptime()})
local first=assert(mes.run(a));names[first]=1
save('/home/concurrent-submit2',{at=computer.uptime()})
local second=assert(mes.run(b));names[second]=2
assert(first~=second and mes.status(first).status=='running' and mes.status(second).status=='running','submissions did not coexist')
for i,id in ipairs({first,second}) do
  local r=assert(mes.wait(id));save('/home/mes-execution-'..i..'.lua',r)
  result.runs[i]={id=id,item=r.item,status=r.status,reason=r.reason,started=r.started,finished=r.finished,gameSeconds=r.finished-r.started,mesTrips=r.trips}
  for _,s in ipairs(r.stages) do
    if s.kind=='robot' and s.craftStarted then
      result.robotIntervals[#result.robotIntervals+1]={run=id,crafter=s.crafter,started=s.craftStarted,finished=s.craftFinished}
    end
    for _,load in ipairs(s.loadLedger or {}) do
      local g=load.group;result.furnaceLoads[g]=result.furnaceLoads[g] or {};result.furnaceLoads[g][#result.furnaceLoads[g]+1]=load
    end
  end
end
result.mesTripWindow.last=latestJobId();finishTripAccounting(result)
result.combinedGameSeconds=math.max(result.runs[1].finished,result.runs[2].finished)-result.runs[1].started
result.robotOverlapSeconds=0;result.sameRobotOverlap=false
for i,a in ipairs(result.robotIntervals) do
  assert(a.finished and a.finished>=a.started,'missing craft interval')
  for j=i+1,#result.robotIntervals do local b=result.robotIntervals[j]
    local overlap=math.max(0,math.min(a.finished,b.finished)-math.max(a.started,b.started))
    if a.crafter==b.crafter and overlap>0 then result.sameRobotOverlap=true end
    if a.run~=b.run and a.crafter~=b.crafter then result.robotOverlapSeconds=result.robotOverlapSeconds+overlap end
  end
end
result.status='complete';save('/home/mes-progress.lua',result)
for _,r in ipairs(result.runs) do assert(r.status=='complete',r.reason or r.status) end
assert(not result.sameRobotOverlap,'one robot ran overlapping jobs')
scan();result.afterScan={torch=count('minecraft:torch'),brick_block=count('minecraft:brick_block')}
assert(result.afterScan.torch==16 and result.afterScan.brick_block==16,'final outputs missing')
wait(function() for _,d in ipairs(lg.drones()) do if d.state~='idle' then return false end end;return true end,60)
finishTripAccounting(result);save('/home/warehouse-results.lua',result);save('/home/mes-results.lua',result)
print('MES verified',case,result.status)
