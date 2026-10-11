local fs=require('filesystem');local computer=require('computer');local event=require('event')
local serialization=require('serialization')
-- Compile all acceptance/UI-driver code before taking deployment baselines.
local measure=assert(loadfile('/home/program/deployment-memory.lua'))()
local config=assert(loadfile('/home/program/cycle-config.lua'))()
for _,n in ipairs({'cbor','store','map','logistics','warehouse'}) do assert(fs.copy('/home/program/lib/'..n..'.lua','/lib/'..n..'.lua')) end
fs.makeDirectory('/lib/logistics');fs.makeDirectory('/lib/warehouse')
assert(fs.copy('/home/program/drone/agent.lua','/lib/logistics/agent.lua'))
for _,n in ipairs({'view','ui'}) do assert(fs.copy('/home/program/lib/warehouse/'..n..'.lua','/lib/warehouse/'..n..'.lua')) end
assert(fs.copy('/home/program/lib/qmenu.lua','/lib/qmenu.lua'))
local map=require('map');local lg=require('logistics');local wh=require('warehouse')
local clay={name='minecraft:clay_ball',damage=0};local coal={name='minecraft:coal',damage=0};local brick={name='minecraft:brick',damage=0}
local function save(path,t) local f=assert(io.open(path,'w'));f:write(serialization.serialize(t,false));f:close() end
local function wait(fn,seconds)
  local deadline=computer.uptime()+seconds
  repeat if fn() then return end;event.pull(0.1) until computer.uptime()>deadline
  error('furnace cycle timeout')
end
local completed={};local totals={trips=0,partial=0,done=0}
event.listen('logistics',function(_,id)
  completed[id]=true;local s=assert(lg.status(id));totals.trips=totals.trips+s.trips
  assert(s.state=='done' or ((config.shortfall or config.concurrentProbe) and s.state=='partial'),'unexpected job state '..s.state)
  totals[s.state]=totals[s.state]+1
end)
local function done(id)
  assert(id);wait(function() return completed[id] end,1500)
  return lg.status(id)
end
local function node(x,y,z,faces,charger)
  local name=x..':'..y..':'..z
  if not map.node(name) then map.add(name,x,y,z,{faces=faces,charger=charger}) end
  return name
end
local function sname(x,y,wall) return 's'..x..'_'..y..'_'..wall end
local H=node(-2,65,2,nil,true);local H2=node(-2,65,5,nil,true)
node(-2,65,3);node(-2,65,4);node(-1,65,2)
for x=0,7 do for y=0,3 do
  local n=node(x,65+y,2,{[2]=true,[3]=true})
  for _,w in ipairs({'N','S'}) do local s=sname(x,y,w);map.name(s,n,w=='N' and 2 or 3);wh.add(s) end
end end
for x=8,10 do node(x,65,2) end
for z=3,9 do node(9,65,z) end
for z=7,9 do node(9,64,z);node(9,63,z) end
for _,v in ipairs({{'A',7},{'B',9}}) do
  local n,z=v[1],v[2]
  map.name('furn'..n..'.in',node(10,65,z,{[0]=true}),0)
  map.name('furn'..n..'.fuel',node(9,64,z,{[5]=true}),5)
  map.name('furn'..n..'.out',node(10,63,z,{[1]=true}),1)
  wh.group('furnace'..n,'furnace',{input='furn'..n..'.in',fuel='furn'..n..'.fuel',output='furn'..n..'.out'})
end
-- Every declared link is exactly one block long; Theta* may shortcut in air.
local nodes=map.nodes()
for a,p in pairs(nodes) do for b,q in pairs(nodes) do if a<b and math.abs(p.x-q.x)+math.abs(p.y-q.y)+math.abs(p.z-q.z)==1 then map.link(a,b) end end end
map.save()
wh.add(sname(6,0,'N'),{filter={brick},priority=5});wh.add(sname(5,0,'N'),{priority=1})
local distances={}
event.listen('modem_message',function(_,_,sender,port,distance,token) if port==27103 and token=='lgx_hello' then distances[sender]=distance end end)
wait(function() return #lg.pending()==2 end,30)
local pending=lg.pending();table.sort(pending,function(a,b) return distances[a]<distances[b] end)
assert(lg.register(pending[1],'d1',H));assert(lg.register(pending[2],'d2',H2))
wait(function() local d=lg.drones();return #d==2 and d[1].state=='idle' and d[2].state=='idle' end,30)
local start=computer.uptime()
local function scan() local ids=wh.scan();assert(#ids==64);for _,id in ipairs(ids) do assert(done(id).state=='done') end end
scan();assert(wh.count(clay)==config.seed and wh.count(coal)==20 and wh.count(brick)==0)
if config.concurrentProbe then
  -- Both jobs are submitted before either finishes: warehouse reservations
  -- must select disjoint inputs across the room's stock inventory faces.
  local a=assert(wh.fetch(clay,64,'furnA.in',{drones=1,retries=0}))
  local b=assert(wh.fetch(clay,64,'furnB.in',{drones=1,retries=0}))
  local ca,cb=done(a),done(b)
  assert(ca.moved==64 and cb.moved==64 and ca.state=='done' and cb.state=='done','concurrent fetch reservation failed')
  local remaining=wh.count(clay)
  local reads=done(lg.job({{read='furnA.in'},{read='furnB.in'}},{drones=1,retries=0}))
  local inside=0;for _,step in ipairs(reads.steps) do for _,v in pairs(step.listing) do inside=inside+v.size end end
  assert(remaining+inside==128 and inside==ca.moved+cb.moved,'concurrent partial accounting')
  save('/home/warehouse-results.lua',{concurrent={a=ca,b=cb},stockClay=remaining,machineClay=inside,gameSeconds=computer.uptime()-start})
  wait(function() for _,d in ipairs(lg.drones()) do if d.state~='idle' then return false end end;return true end,30)
  return
end
local result={seed=config.seed,removed=config.shortfall and 20 or 0,loads={},outputs={},sourceFacts={cookTicks=200,coalTicks=1600}}
if config.shortfall then
  save('/home/warehouse-remove-items',{count=20});assert(event.pull(10,'warehouse_items_removed'),'native removal missing')
end
local groups=wh.groups('furnace');local names={};for n in pairs(groups) do names[#names+1]=n end;table.sort(names)
local amount=config.seed/2
-- Keep the cycle's historical sequential loading order for native regression;
-- the dedicated concurrent probe exercises overlapping warehouse submissions.
for _,name in ipairs(names) do
  local roles=groups[name].roles
  local a=assert(wh.fetch(clay,amount,roles.input,{drones=1,retries=0}))
  local b=assert(wh.fetch(coal,8,roles.fuel,{drones=1,retries=0}))
  local ca,fu=done(a),done(b);assert(fu.state=='done' and fu.moved==8)
  if config.shortfall and name=='furnaceA' then assert(ca.state=='partial' and ca.moved==amount-20)
  else assert(ca.state=='done' and ca.moved==amount) end
  result.loads[name]={requested=amount,moved=ca.moved,state=ca.state,job=a,fuelJob=b}
end
assert(wh.count(clay)==0 and wh.count(coal)==4,'stock after loading')
local id,why=wh.store(brick,amount,'furnA.out');assert(not id and why:find('unknown stack size',1,true));result.unknown=why
-- TileEntityFurnace.getCookTime = 200 ticks; coal = 1600 ticks. At 20 TPS,
-- 64 items need 640 seconds and eight coal. Only the test sleeps.
os.sleep(amount*200/20)
for _,name in ipairs(names) do
  local roles=groups[name].roles
  local readId=lg.job({{read=roles.output}},{drones=1,retries=0});local s=done(readId);assert(s.state=='done')
  local listing=s.steps[1].listing;local n=0
  for _,stack in pairs(listing or {}) do if stack.name==brick.name then n=n+stack.size end end
  assert(n==result.loads[name].moved,'real output count')
  result.outputs[name]={read=n,readJob=readId}
  local storeId=assert(wh.store(brick,n,roles.output,{drones=1,retries=0,wait={timeout=amount*10+60}}));local stored=done(storeId)
  assert(stored.state=='done' and stored.moved==n,'bounded store failed');result.outputs[name].storeJob=storeId
end
local expected=config.seed-result.removed
assert(wh.count(brick)==expected and wh.count(clay)==0 and wh.count(coal)==4,'catalogue before final scan')
local function quantity(storage,item)
  local n=0;for _,v in pairs(assert(wh.contents(storage)).items) do if v.item.name==item.name then n=n+v.count end end;return n
end
assert(quantity(sname(6,0,'N'),brick)==64 and quantity(sname(5,0,'N'),brick)==expected-64,'priority/capacity policy')
result.beforeScan={brick=wh.count(brick),clay=wh.count(clay),coal=wh.count(coal)}
scan();assert(wh.count(brick)==expected and wh.count(clay)==0 and wh.count(coal)==4,'real chests differ from catalogue')
result.afterScan={brick=wh.count(brick),clay=wh.count(clay),coal=wh.count(coal)}
result.furnaces={}
for _,name in ipairs(names) do
  local roles=groups[name].roles;local job=done(lg.job({{read=roles.input},{read=roles.output}},{drones=1,retries=0}))
  assert(job.state=='done');local input,output=job.steps[1].listing,job.steps[2].listing
  assert(not next(input),'furnace input remains')
  local fuel=0;for _,v in pairs(output) do assert(v.name==coal.name,'furnace output remains');fuel=fuel+v.size end
  result.furnaces[name]={fuel=fuel,input=0,output=0}
end
wait(function() for _,d in ipairs(lg.drones()) do if d.state~='idle' then return false end end;return true end,30)
for _,d in ipairs(lg.drones()) do assert(not d.cargo or d.cargo==0 or (type(d.cargo)=='table' and not next(d.cargo)),'drone cargo remains') end
for _,j in ipairs(lg.jobs(true)) do assert(j.state=='done','unfinished retained job') end
assert(totals.partial==(config.shortfall and 1 or 0));result.trips=totals.trips;result.partialJobs=totals.partial;result.doneJobs=totals.done;result.gameSeconds=computer.uptime()-start
result.stock={filtered=64,priority1=expected-64,shortage=result.removed}
save('/home/warehouse-results.lua',result)
measure(save)
print('furnace cycle verified',expected,result.gameSeconds)
