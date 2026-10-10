local fs=require('filesystem');local computer=require('computer');local event=require('event')
local serialization=require('serialization');local component=require('component')
assert(loadfile('/home/program/install.lua'))()
local hosts=require('hosts');local fixtureWake='T13Fixture-controller'
assert(hosts.addHost(component.modem.address,computer.address(),'controller',fixtureWake,{}))
for _,name in ipairs({'map','logistics','warehouse'}) do
  assert(fs.copy('/home/program/lib/'..name..'.lua','/lib/'..name..'.lua'))
end
fs.makeDirectory('/lib/logistics')
assert(fs.copy('/home/program/drone/agent.lua','/lib/logistics/agent.lua'))
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
    kinds.jobs[#kinds.jobs+1]={id=id,kind=kind,trips=j.trips,queuedAt=j.queuedAt,tripTimings=j.tripTimings,collectItems=collect[id] and j.perItem or nil,collectSteps=collect[id] and j.steps or nil}
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
  fuel={role='fuel',item='minecraft:coal',per=8},batch=16,seconds=10,blocking=false}}})
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

local result={case=case,robots=addresses,status='running'}
local function saveProgress()
  -- Full physical ledgers already have their own durable files. Avoid
  -- serializing a second copy of them on the T3 controller just for progress.
  local summary={}
  for _,key in ipairs({'case','status','submitterExit','componentCalls','mesTripWindow',
    'mesTrips','harnessTrips','trips','droneBusy','robotIntervals','robotOverlap','tripKinds'}) do
    summary[key]=result[key]
  end
  save('/home/mes-progress.lua',summary)
end
local source=assert(io.open('/home/program/recipes.tsv','r'));local text=source:read('*a');source:close()
for _,namespace in ipairs({'minecraft','opencomputers'}) do
  local lines={};for line in text:gmatch('[^\n]+') do
    if line:sub(1,#namespace+1)==namespace..':' then lines[#lines+1]=line end
  end
  local archive=assert(require('liblz16').open('/usr/lib/recipes/'..namespace..'.dblz','wb'))
  assert(archive:write(table.concat(lines,'\n')..'\n'));archive:close()
end
local builder=require('recipes.build');local db=builder.build();assert(builder.save(db));require('recipes').install(db)

local recipes=require('recipes')
-- In the native Forge+OC game no ore entry named clay exists. OC's default
-- parser resolves its literal clay ingredient to minecraft:clay (the block).
-- The user's modded ore cache maps it to clay_ball instead; retain that DB row
-- and import the authentic default.recipes variant as a crafting overlay.
local rawSlots={[1]={name='minecraft:gold_ingot',size=1},
                [2]={name='minecraft:clay',size=1},
                [3]={name='minecraft:dye',damage=2,size=1},
                [14]={name='opencomputers:material',damage=2,size=8}}
local rawDraft=assert(recipes.recipeFromSlots('crafting',rawSlots,27))
assert(recipes.save(rawDraft))
-- The user's crafting DB has no smelting registry. Import the real OC recipe.
local slots={[1]={name='opencomputers:material',damage=2,size=1},
             [24]={name='opencomputers:material',damage=4,size=1}}
local draft=assert(recipes.recipeFromSlots('processing',slots,27,'furnace'))
assert(recipes.save(draft))

local plan,why=mes.plan('opencomputers:component:6',64);assert(plan,why)
assert(#plan.missing==0,'raw stock unexpectedly short')
save('/home/mes.plan',plan)
result.mesTripWindow={first=latestJobId()+1}
-- A separate foreground command submits, writes its ID, and exits immediately.
-- The installed MES service must keep advancing after that process is closed.
local submit=assert(io.open('/home/mes-submit.lua','w'))
assert(submit:write([[
local mes=require('mes')
local counter=package.loaded.runner_component_calls
local before=counter and counter.snapshot()
local id=assert(mes.run('/home/mes.plan',{pollSeconds=0.2}))
if counter then counter.submittedBefore=before end
assert(mes.status(id).status=='running','submit did not return mid-run')
local file=assert(io.open('/home/mes-submitted-id','w'));assert(file:write(tostring(id)))
if file.flush then assert(file:flush()) end
local closed,err=file:close();assert(closed~=false and not err,err)
return 0
]]))
if submit.flush then assert(submit:flush()) end
local closed,err=submit:close();assert(closed~=false and not err,err)
assert(require('shell').execute('/home/mes-submit.lua'),'submitter command failed')
local submitted=assert(io.open('/home/mes-submitted-id','r'))
local runId=assert(tonumber(submitted:read('*a')));submitted:close();result.runId=runId
result.submitterExit={returned=true,statusAtReturn=mes.status(runId).status}
assert(result.submitterExit.statusAtReturn=='running','submitter did not exit mid-run')
local componentBefore=componentCounter and componentCounter.submittedBefore
local outcome=assert(mes.wait(runId));finishComponentCalls(result,componentBefore)
result.mesTripWindow.last=latestJobId();save('/home/mes-execution.lua',outcome)
finishTripAccounting(result);result.timing=mesTiming(outcome);save('/home/mes-fetch-timings.lua',result.timing)
result.status=outcome.status;result.stages=outcome.stages
saveProgress()
assert(outcome.status=='complete',outcome.reason or outcome.error)
local overlap=false;local used={};result.robotIntervals={}
for i,a in ipairs(outcome.stages) do
  if a.kind=='robot' then
    assert(a.receipt and a.receipt.status=='complete','verified robot receipt missing')
    assert(a.craftStarted and a.craftFinished and a.craftFinished>=a.craftStarted,'robot call interval missing')
    used[a.crafter]=true
    result.robotIntervals[#result.robotIntervals+1]={stage=i,crafter=a.crafter,started=a.craftStarted,finished=a.craftFinished}
    for _,b in ipairs(outcome.stages) do
      if b.kind=='robot' and a.crafter~=b.crafter and b.craftStarted and b.craftFinished then
        if math.max(a.craftStarted,b.craftStarted)<math.min(a.craftFinished,b.craftFinished) then overlap=true end
      end
    end
  end
end
result.robotOverlap=overlap
saveProgress()
-- Genuine overlap remains measured. The approved T13 gate requires answered
-- jobs on both connected CPUs; concurrent request overlap is the T14 gate.
assert(used.cpu1 and used.cpu2,'both robots did not execute answered jobs')
assert(#result.robotIntervals>=4,'fewer than four answered robot jobs')
result.loads={};result.topups={}
for _,stage in ipairs(outcome.stages) do if stage.kind=='machine' then
  for _,move in ipairs(stage.itemsMoved or {}) do
    if move.kind=='fetch' and move.item=='opencomputers:material:2' then
      result.loads[move.storage]=(result.loads[move.storage] or 0)+(move.moved or 0)
    end
  end
  for _,group in ipairs({'furnaceA','furnaceB'}) do
    local rows={};for _,load in ipairs(stage.loadLedger or {}) do
      if load.group==group then rows[#rows+1]=load end
    end
    assert(#rows==2 and rows[1].items==16 and rows[2].items==16,'PCB load ledger missing')
    assert(rows[2].delivered<rows[1].collected,'PCB load did not top up while smelting')
    result.topups[group]=rows
  end
end end
assert(result.loads['furnA.in']==32 and result.loads['furnB.in']==32,'PCB furnace groups did not split evenly')
scan();local expected={['minecraft:iron_ingot']=104,['minecraft:gold_ingot']=23,['minecraft:redstone']=30,['minecraft:clay']=8,['minecraft:dye:2']=8,['minecraft:paper']=14,['minecraft:coal']=24,['minecraft:iron_nugget']=2,['minecraft:gold_nugget']=5,['opencomputers:material:6']=0,['opencomputers:component:6']=64,['opencomputers:material:2']=0,['opencomputers:material:4']=0,['opencomputers:material:7']=0};result.afterScan={}
for id,n in pairs(expected) do result.afterScan[id]=count(id);assert(count(id)==n,'stock mismatch: '..id) end
-- No unlisted manufactured items are permitted, not merely target equality.
for _,s in pairs(wh.totals()) do
  local id=s.item.name;if (s.item.damage or 0)~=0 then id=id..':'..s.item.damage end
  assert(expected[id]~=nil and expected[id]==s.count,'unexpected final stock: '..id)
end
result.buffers={};for _,cpu in ipairs({'cpu1','cpu2'}) do
  result.buffers[cpu]=read(cpu..'.buf');assert(not next(result.buffers[cpu]),'buffer not empty')
end
result.furnaces={};for _,n in ipairs({'A','B'}) do
  local input=read('furn'..n..'.in');local output=read('furn'..n..'.out');local fuel=read('furn'..n..'.fuel')
  assert(not next(input) and not next(output) and not next(fuel),'furnace inventory not empty')
  result.furnaces[n]={input=input,output=output,fuel=fuel}
end
wait(function() for _,d in ipairs(lg.drones()) do if d.state~='idle' then return false end end;return true end,60)
for _,d in ipairs(lg.drones()) do assert(not d.cargo or d.cargo==0 or (type(d.cargo)=='table' and not next(d.cargo)),'drone cargo remains') end
-- Full execution and timing receipts are already saved separately. Retain
-- compact result summaries instead of duplicating all ledgers in one string.
result.jobs={};for id,job in pairs(jobs) do
  result.jobs[id]={state=job.state,trips=job.trips,moved=job.moved,requested=job.requested,shortfalls=job.shortfalls}
end
result.stages={};for i,stage in ipairs(outcome.stages) do
  result.stages[i]={kind=stage.kind,state=stage.state,crafter=stage.crafter,done=stage.done,total=stage.total,
    assigned=stage.assigned,released=stage.released,craftStarted=stage.craftStarted,craftFinished=stage.craftFinished}
end
result.executionLedger='/home/mes-execution.lua';result.timingFile='/home/mes-fetch-timings.lua';result.timing=nil
result.trips=totals.trips;result.itemsMoved=totals.moved;result.gameSeconds=computer.uptime()-start
finishTripAccounting(result)
outcome=nil
save('/home/warehouse-results.lua',result);save('/home/mes-results.lua',result)
print('MES verified',case,result.status,result.gameSeconds,result.trips)
