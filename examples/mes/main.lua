local fs=require('filesystem');local computer=require('computer');local event=require('event')
local serialization=require('serialization');local component=require('component')
assert(loadfile('/home/program/install.lua'))()
local hosts=require('hosts');local fixtureWake='T13Fixture-controller'
assert(hosts.addHost(component.modem.address,computer.address(),'controller',fixtureWake,{}))
for _,name in ipairs({'cbor','store','map','logistics','warehouse','stations','iochest'}) do
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
local address,distances
distances={};component.modem.open(27105)
event.listen('modem_message',function(_,_,sender,port,distance,token,robot,cpu,cid,wake)
  if port==27105 and token=='mes_robot_ready' then
    assert(robot==sender and type(cid)=='string' and type(wake)=='string')
    assert(hosts.addHost(robot,cid,cpu,wake,{service='craftServer'},true))
    address=robot
  end
  if port==27103 and token=='lgx_hello' then distances[sender]=distance end
end)
local setup=assert(loadfile('/home/program/setup.lua'))()
wait(function() component.modem.broadcast(27105,'mes_robot_query',computer.address(),fixtureWake);return address~=nil end,60)
save('/etc/mes.cfg',{crafters={cpu1={robot=address}},machineTypes={furnace={inputs={'input'},output='output',
  roles={'input','fuel','output'},roleSlots={input={1},fuel={1},output={1}},
  fuel={role='fuel',item='minecraft:coal',per=8},batch=(case=='torches16' and 1 or 64),seconds=10,blocking=false}}})
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
local result={case=case,robot=address,status='running',stages={},before={logs=count('minecraft:log'),coal=count('minecraft:coal'),clay=count('minecraft:clay_ball')}}
if case=='concurrent-fetch' then
  assert(result.before.clay==128)
  local a=assert(wh.fetch(item('minecraft:clay_ball'),64,'furnA.in',{drones=1,retries=0}))
  local b=assert(wh.fetch(item('minecraft:clay_ball'),64,'furnB.in',{drones=1,retries=0}))
  result.concurrent={a=done(a),b=done(b)}
  assert(result.concurrent.a.state=='done' and result.concurrent.a.moved==64)
  assert(result.concurrent.b.state=='done' and result.concurrent.b.moved==64)
  assert(amount(read('furnA.in'),'minecraft:clay_ball')==64 and amount(read('furnB.in'),'minecraft:clay_ball')==64)
  scan();assert(count('minecraft:clay_ball')==0);result.status='complete'
else
  -- Use the project's actual archive writer, compiler and processing registration.
  local source=assert(io.open('/home/program/recipes.tsv','r'));local text=source:read('*a');source:close()
  local archive=assert(require('liblz16').open('/usr/lib/recipes/minecraft.dblz','wb'));assert(archive:write(text));archive:close()
  local builder=require('recipes.build');local db=builder.build();assert(builder.save(db));require('recipes').install(db)
  assert(require('recipes').registerProcessingRecipe('minecraft:coal:1','furnace',{recipe={'minecraft:log'},qty=1}))
  assert(require('recipes').registerProcessingRecipe('minecraft:brick','furnace',{recipe={'minecraft:clay_ball'},qty=1}))
  local target=case=='torches16' and 'minecraft:torch' or 'minecraft:brick_block'
  local plan,why=mes.plan(target,16);assert(plan,why)
  result.rawTaskOrder={};for _,t in ipairs(plan.tasks) do result.rawTaskOrder[#result.rawTaskOrder+1]=t.item end
  if case=='specific-group' then
    for i,stage in ipairs(plan.stages) do
      if stage.kind=='machine' then assert(mes.choose(plan,i,'furnaceA')) end
    end
  end
  result.taskOrder={};for _,t in ipairs(plan.tasks) do result.taskOrder[#result.taskOrder+1]=t.item end
  save('/home/mes.plan',plan)
  if case=='shortfall' then
    save('/home/warehouse-remove-items',{count=16});assert(event.pull(10,'warehouse_items_removed'),'native removal missing')
  end
  event.listen('mes',function(_,kind,runId,index,state)
    if kind=='stage' then print('MES stage',runId,index,state) end
  end)
  local opts={crafter='cpu1',pollSeconds=0.2}
  if case=='specific-group' then opts.machines={furnace='furnaceA'} end
  result.mesTripWindow={first=latestJobId()+1}
  local componentBefore=startComponentCalls()
  local runId=assert(mes.run('/home/mes.plan',opts));result.runId=runId
  local outcome=assert(mes.wait(runId));finishComponentCalls(result,componentBefore)
  result.mesTripWindow.last=latestJobId();save('/home/mes-execution.lua',outcome)
  finishTripAccounting(result);result.timing=mesTiming(outcome);save('/home/mes-fetch-timings.lua',result.timing)
  result.status=outcome.status;result.stages=outcome.stages;result.error=outcome.reason or outcome.error
  if case=='shortfall' then
    assert(outcome.status=='failed')
    local failedMachine
    for _,s in ipairs(outcome.stages) do
      if s.kind=='machine' and (s.state=='failed' or s.status=='failed') then failedMachine=s end
      if s.kind=='robot' then assert(not s.receipt and not s.craftStarted,'robot executed after shortfall') end
    end
    assert(failedMachine,'machine failure missing')
    assert((failedMachine.remaining and next(failedMachine.remaining)) or (outcome.where and next(outcome.where)),'failure location report missing')
    assert(count('minecraft:brick_block')==0,'crafted beyond available inputs')
  else
    assert(outcome.status=='complete',outcome.error)
    local machine;local robotCount=0
    for _,stage in ipairs(outcome.stages) do
      assert(stage.state=='done' or stage.status=='complete')
      if stage.kind=='robot' then
        robotCount=robotCount+1;assert(stage.receipt and stage.receipt.status=='complete','robot receipt missing')
      elseif stage.kind=='machine' then assert(not machine,'unexpected extra machine stage');machine=stage end
    end
    assert(machine and robotCount>0,'robot/machine work missing')
    local loads={};for _,move in ipairs(machine.itemsMoved) do
      if move.kind=='fetch' and (move.item=='minecraft:clay_ball' or move.item=='minecraft:log') then
        loads[move.storage]=(loads[move.storage] or 0)+(move.moved or 0)
      end
    end
    result.loads=loads
    if case=='torches16' then
      result.topups={}
      for _,group in ipairs({'furnaceA','furnaceB'}) do
        local rows={};for _,load in ipairs(machine.loadLedger or {}) do
          if load.group==group then rows[#rows+1]=load end
        end
        assert(#rows==2 and rows[1].items==1 and rows[2].items==1,'torch load ledger missing')
        assert(rows[2].delivered<rows[1].collected,'torch second load gated on prior output collection')
        result.topups[group]=rows
      end
    end
    if case=='specific-group' then
      assert(#machine.groups==1 and machine.groups[1]=='furnaceA' and loads['furnA.in']==64 and not loads['furnB.in'])
    else
      local each=case=='torches16' and 2 or 32
      assert(#machine.groups==2 and loads['furnA.in']==each and loads['furnB.in']==each,'machine split not even')
    end
    scan()
    if case=='torches16' then
      assert(count('minecraft:torch')==16 and count('minecraft:log')==3 and count('minecraft:coal')==14)
      assert(count('minecraft:planks')==2 and count('minecraft:stick')==0 and count('minecraft:coal:1')==0)
    else assert(count('minecraft:brick_block')==16 and count('minecraft:clay_ball')==0 and count('minecraft:brick')==0 and count('minecraft:coal')==8) end
    assert(not next(read('cpu1.buf')),'station buffer not empty')
    result.furnaces={}
    for _,n in ipairs({'A','B'}) do
      local listing=read('furn'..n..'.in');result.furnaces[n]=listing
      for _,s in pairs(listing) do assert(s.name=='minecraft:coal' and (s.damage or 0)==0,'machine input/output not empty') end
      if case=='specific-group' and n=='B' then assert(not next(listing),'furnaceB touched') end
    end
  end
end
wait(function() for _,d in ipairs(lg.drones()) do if d.state~='idle' then return false end end;return true end,60)
for _,d in ipairs(lg.drones()) do assert(not d.cargo or d.cargo==0 or (type(d.cargo)=='table' and not next(d.cargo)),'drone cargo remains') end
if case=='shortfall' then
  scan()
  local stockClay,stockBrick=count('minecraft:clay_ball'),count('minecraft:brick')
  local conservation={stockClay=stockClay,stockBrick=stockBrick,total=stockClay+stockBrick,machines={}}
  result.furnaces={}
  for _,n in ipairs({'A','B'}) do
    -- Native sided reads: top exposes input; bottom exposes output and fuel.
    local input=read('furn'..n..'.in');local output=read('furn'..n..'.out')
    result.furnaces[n]={input=input,output=output}
    local clay,brick=amount(input,'minecraft:clay_ball'),amount(output,'minecraft:brick')
    conservation.machines[n]={clay=clay,brick=brick}
    conservation.total=conservation.total+clay+brick
    assert(amount(input,'minecraft:brick_block')+amount(output,'minecraft:brick_block')==0,'unexpected blocks in furnace')
  end
  result.buffer=read('cpu1.buf');assert(not next(result.buffer),'shortfall buffer not empty')
  result.conservation=conservation
  assert(count('minecraft:brick_block')==0,'shortfall produced blocks')
  assert(conservation.total==48,'shortfall clay/brick conservation failed')
end
result.afterScan={logs=count('minecraft:log'),coal=count('minecraft:coal'),planks=count('minecraft:planks'),sticks=count('minecraft:stick'),
                  torch=count('minecraft:torch'),clay=count('minecraft:clay_ball'),brick=count('minecraft:brick'),brick_block=count('minecraft:brick_block')}
-- Detailed MES receipts have separate durable files; avoid duplicating them
-- in one large serialized result on the T3 controller.
result.jobs={};for id,job in pairs(jobs) do
  result.jobs[id]={state=job.state,trips=job.trips,moved=job.moved,requested=job.requested,shortfalls=job.shortfalls}
end
local summaries={};for i,stage in ipairs(result.stages or {}) do
  summaries[i]={kind=stage.kind,state=stage.state,crafter=stage.crafter,done=stage.done,total=stage.total,
    assigned=stage.assigned,released=stage.released,craftStarted=stage.craftStarted,craftFinished=stage.craftFinished}
end
result.stages=summaries;result.timing=nil
result.executionLedger='/home/mes-execution.lua';result.timingFile='/home/mes-fetch-timings.lua'
result.trips=totals.trips;result.itemsMoved=totals.moved;result.gameSeconds=computer.uptime()-start
finishTripAccounting(result)
save('/home/warehouse-results.lua',result);save('/home/mes-results.lua',result)
print('MES verified',case,result.status,result.gameSeconds,result.trips)
