local fs=require('filesystem')
fs.makeDirectory('/lib/logistics')
for _,name in ipairs({'cbor','store','map','logistics','warehouse'}) do assert(fs.copy('/home/program/lib/'..name..'.lua','/lib/'..name..'.lua')) end
assert(fs.copy('/home/program/drone/agent.lua','/lib/logistics/agent.lua'))
local map=require('map');local event=require('event');local computer=require('computer')
local restarting=io.open('/home/warehouse-journal-reboot','r')
if restarting then
  restarting:close();assert(map.load())
  local wh=require('warehouse')
  assert(wh.stackSize({name='minecraft:iron_ingot',damage=0})==64 and wh.stackSize({name='minecraft:ender_pearl',damage=0})==16,'learned stack sizes lost on reboot')
  assert(wh.count({name='minecraft:iron_ingot',damage=0})==1 and wh.count({name='minecraft:ender_pearl',damage=0})==16,'incomplete compaction lost data on reboot')
  local members=wh.members();assert(not members.a and members.b.filter[1].name=='minecraft:ender_pearl' and members.c)
  print('warehouse incremental journal and interrupted-compaction reboot verified');return
end
map.add('H',0,65,0,{charger=true});map.add('A',0,65,2,{faces={[0]=true}})
map.add('M',3,65,2);map.add('B',6,65,2,{faces={[0]=true}});map.add('C',6,65,6,{faces={[0]=true}})
map.link('H','A');map.link('A','M');map.link('M','B');map.link('B','C')
map.name('a','A',0);map.name('b','B',0);map.name('c','C',0);map.save()
local lg=require('logistics')
local function wait(predicate)
  local endTime=computer.uptime()+120
  repeat if predicate() then return end;event.pull(0.1) until computer.uptime()>endTime;error('warehouse slots timeout')
end
wait(function() return #lg.pending()==1 end);assert(lg.register(lg.pending()[1],'d','H'))
wait(function() return lg.drones()[1].state=='idle' end)
local wh=require('warehouse');local complete={}
event.listen('logistics',function(_,id) complete[id]=true end)
local function done(id) assert(id);wait(function() return complete[id] end);return assert(lg.status(id)) end
local function scan(storages) for _,id in ipairs(wh.scan(storages)) do assert(done(id).state=='done') end end
local iron={name='minecraft:iron_ingot',damage=0};local pearl={name='minecraft:ender_pearl',damage=0}
local gold={name='minecraft:gold_ingot',damage=0}
wh.add('b',{filter={pearl}});wh.add('c');scan()
-- A read at a nonmember endpoint teaches limits even though it is not stock.
assert(done(lg.job({{read='a'}},{drones=1})).state=='done')
assert(wh.stackSize(iron)==64 and wh.contents('a').slots==27 and wh.count(iron)==0,'nonmember read did not teach the stack limit')
wh.add('a');scan({'a'})
wh.remove('a')
local none,reason=wh.store(pearl,435,'a')
assert(not none and reason:find('capacity 434',1,true),'real 16-item stack limit not used')
assert(done(assert(wh.store(pearl,2,'a',{drones=1,retries=0}))).state=='done')
assert(wh.count(pearl)==16)
wh.add('a');scan({'a'})
local s=done(lg.job({{take={storage='a',slots={1}},item=iron,count=32},{put='c',item=iron,rest=true}},{drones=1,retries=0}))
assert(s.state=='partial' and s.moved==16 and s.steps[1].short)
assert(wh.count(iron)==64,'slot-scoped shortfall zeroed unvisited stock')
local e=wh.contents('a');local n=0;for _,v in pairs(e.items) do if v.item.name==iron.name then n=n+v.count end end;assert(n==48)
-- A partial read is not a whole-inventory catalogue snapshot.
assert(done(lg.job({{read={storage='a',slots={2}}}},{drones=1})).state=='done')
assert(wh.count(iron)==64,'partial read overwrote full catalogue')
assert(done(lg.transfer(iron,16,'a','c',{drones=1,retries=0})).state=='done')
-- Equal 32-count sources: C -> B is 4 blocks, A -> B is 6.
s=done(assert(wh.fetch(iron,1,'b',{drones=1,retries=0})))
assert(s.state=='failed' and s.steps[1].take.node=='C' and s.steps[1].returned==1,'distance tie breaker failed')
assert(wh.count(iron)==64)
s=done(lg.transfer(iron,60,'a','c',{drones=1,retries=0}))
assert(s.state=='partial' and s.taken==32 and s.short and s.found==0 and wh.count(iron)==64)
assert(done(assert(wh.fetch(iron,64,'a',{drones=1,retries=0}))).state=='done')
wh.remove('a')
-- C is empty but remembers the real stack limit of its previously seen iron.
none,reason=wh.store(iron,1729,'a')
assert(not none and reason:find('capacity 1728',1,true),'empty inventory forgot seen maxSize')
none,reason=wh.store(gold,1,'a')
assert(not none and reason:find('capacity 0',1,true) and reason:find('unknown stack size for minecraft:gold_ingot:0',1,true) and reason:find('reading the source teaches it',1,true),'unseen item size guessed')
assert(done(assert(wh.store(iron,1,'a',{drones=1,retries=0}))).state=='done')
assert(wh.count(iron)==1 and wh.count(pearl)==16)
-- Thirteen real read jobs exercise complete incremental snapshots, followed
-- by a reboot with the next snapshot unfinished. No fake reports or timers.
for i=1,13 do assert(done(lg.job({{read='c'}},{drones=1})).state=='done') end
-- Nonmember observations are now retained for the UI. Reach the same unfinished
-- replacement seam without assuming the old member-only journal row count.
for i=1,20 do if fs.exists('/etc/warehouse.db.new') then break end;assert(done(lg.job({{read='c'}},{drones=1})).state=='done') end
local records=0;local file=assert(io.open('/etc/warehouse.db','r'));for _ in file:lines() do records=records+1 end;file:close()
assert(records<=12,'journal grows with history instead of inventory count')
assert(fs.exists('/etc/warehouse.db.new'),'interrupted compaction seam not reached')
print('warehouse slot scope, distance tie, 16-stack and retained limits verified')
local mark=assert(io.open('/home/warehouse-journal-reboot','w'));mark:write('restart with unfinished incremental snapshot');mark:close()
computer.shutdown(true)
