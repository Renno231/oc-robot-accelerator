local fs=require('filesystem')
local serialization=require('serialization')
local computer=require('computer')
local event=require('event')
fs.makeDirectory('/lib/logistics')
for _,n in ipairs({'map','logistics','warehouse'}) do assert(fs.copy('/home/program/lib/'..n..'.lua','/lib/'..n..'.lua')) end
assert(fs.copy('/home/program/drone/agent.lua','/lib/logistics/agent.lua'))
assert(fs.copy('/home/program/bin/warehouse.lua','/bin/warehouse.lua'))
local map=require('map')
local iron={name='minecraft:iron_ingot',damage=0}
local gold={name='minecraft:gold_ingot',damage=0}
local function load(path) local f=assert(io.open(path,'r'));local t=assert(serialization.unserialize(f:read('*a')));f:close();return t end
local function save(path,t) local f=assert(io.open(path,'w'));f:write(serialization.serialize(t,false));f:close() end
local function equal(a,b)
  if type(a)~=type(b) then return false end
  if type(a)~='table' then return a==b end
  for k,v in pairs(a) do if not equal(v,b[k]) then return false end end
  for k in pairs(b) do if a[k]==nil then return false end end;return true
end
local restart=io.open('/home/warehouse-reboot','r')
if restart then
  restart:close();assert(map.load())
  local wh=require('warehouse');local expected=load('/home/warehouse-expected')
  assert(wh.count(iron)==expected.count,'catalogue lost on native controller reboot')
  assert(equal(wh.members(),expected.members),'members lost')
  assert(equal(wh.groups(),expected.groups),'groups lost')
  for storage,entry in pairs(expected.catalogue) do assert(equal(wh.contents(storage),entry),'catalogue entry lost') end
  local evidence=load('/home/warehouse-results.lua');evidence.reboot=true;save('/home/warehouse-results.lua',evidence)
  print('warehouse native reboot verified',wh.count(iron));return
end
map.add('H',-2,65,2,{charger=true});map.add('H2',-2,65,5,{charger=true});map.link('H','H2')
local function name(x,y) return 'N'..x..'_'..y end
local function storage(x,y,wall) return 's'..x..'_'..y..'_'..wall end
for x=0,7 do for y=0,3 do
  map.add(name(x,y),x,65+y,2,{faces={[2]=true,[3]=true}})
  if x>0 then map.link(name(x-1,y),name(x,y)) end
  if y>0 then map.link(name(x,y-1),name(x,y)) end
  map.name(storage(x,y,'N'),name(x,y),2);map.name(storage(x,y,'S'),name(x,y),3)
end end
map.link('H',name(0,0))
map.add('alias',-1,65,1,{faces={[5]=true}});map.link('H','alias');map.name('shared','alias',5)
map.add('FT',10,65,7,{faces={[0]=true}});map.add('FS',9,64,7,{faces={[5]=true}});map.add('FB',10,63,7,{faces={[1]=true}})
map.name('furnace-input','FT',0);map.name('furnace-fuel','FS',5);map.name('furnace-output','FB',1)
map.link(name(7,0),'FT');map.save()
local distances={}
event.listen('modem_message',function(_,_,sender,port,distance,token) if port==27103 and token=='lgx_hello' then distances[sender]=distance end end)
local lg=require('logistics')
local function wait(predicate,seconds)
  local deadline=computer.uptime()+seconds
  repeat if predicate() then return end;event.pull(0.1) until computer.uptime()>deadline
  error('warehouse native timeout')
end
wait(function() return #lg.pending()==2 end,20)
local pending=lg.pending();table.sort(pending,function(a,b) return distances[a]<distances[b] end)
for i=1,2 do assert(lg.register(pending[i],'d'..i,i==1 and 'H' or 'H2')) end
wait(function() local d=lg.drones();return #d==2 and d[1].state=='idle' and d[2].state=='idle' end,30)
local gc=pcall(collectgarbage,'collect')
local before=computer.freeMemory()
local performance={events=0,cpuSeconds=0,maxCpuSeconds=0}
local listen=event.listen
event.listen=function(signal,handler)
  if signal~='logistics' then return listen(signal,handler) end
  return listen(signal,function(...)
    local start=os.clock();handler(...);local elapsed=os.clock()-start
    performance.events=performance.events+1;performance.cpuSeconds=performance.cpuSeconds+elapsed
    performance.maxCpuSeconds=math.max(performance.maxCpuSeconds,elapsed)
  end)
end
local wh=require('warehouse')
event.listen=listen
pcall(collectgarbage,'collect')
local afterLibrary=computer.freeMemory()
local completed={}
event.listen('logistics',function(_,id) completed[id]=true end)
local function done(id)
  assert(id);wait(function() return completed[id] end,1200)
  local s=assert(lg.status(id));assert(s.state=='done' or s.state=='partial' or s.state=='failed')
  return s
end
local function scan(list) local ids=wh.scan(list);for _,id in ipairs(ids) do assert(done(id).state=='done','scan failed') end;return #ids end
local function count(storage)
  local n=0;for _,v in pairs(assert(wh.contents(storage)).items) do if v.item.name==iron.name then n=n+v.count end end;return n
end
for x=0,7 do for y=0,3 do for _,wall in ipairs({'N','S'}) do
  assert(wh.add(storage(x,y,wall),x==0 and y==0 and wall=='N' and {inventory='chest00'} or nil))
end end end
assert(wh.add('shared',{inventory='chest00'}))
assert(scan()==64)
-- All room chests have exactly one independently accessed native inventory.
local total=0
for x=0,7 do for y=0,3 do for _,wall in ipairs({'N','S'}) do
  local s=storage(x,y,wall);local entry=assert(wh.contents(s));assert(entry.slots==27,'combined chest view')
  total=total+count(s)
end end end
assert(total==382 and wh.count(iron)==382,'scan/find/count do not match real chests')
local finds=wh.find(iron);local found=0;for _,v in ipairs(finds) do found=found+v.count end;assert(found==382)
assert(scan({storage(0,0,'N')})==1);assert(scan({'shared'})==1)
assert(wh.count(iron)==382 and count('shared')==40,'shared inventory counted twice')
pcall(collectgarbage,'collect')
local memory={before=before,afterLibrary=afterLibrary,after=computer.freeMemory(),total=computer.totalMemory(),roomInventories=64,itemTypes=12,gc=gc}
print('warehouse memory',serialization.serialize(memory))
save('/home/warehouse-memory.lua',memory)
assert(loadfile('/home/program/ui-tests.lua'))()(done,wait)
local source=storage(0,0,'N');local second=storage(0,2,'N');local third=storage(0,3,'N')
local external=storage(7,3,'S');local outsider=storage(7,0,'N')
-- Keep only explicitly opted-in sources during fetch acceptance.
for s in pairs(wh.members()) do if s~=source and s~=second and s~=third and s~='shared' then wh.remove(s) end end
assert(wh.count(iron)==90)
wh.group('smelter','furnace',{input='furnace-input',fuel='furnace-fuel',output='furnace-output'})
for _,s in ipairs({'furnace-input','furnace-fuel','furnace-output'}) do wh.add(s) end
assert(scan({'furnace-input'})==1 and count('furnace-input')==0 and wh.count(iron)==90,'group faces treated as stock')
assert(done(lg.transfer(iron,7,outsider,'furnace-input',{drones=1,retries=0})).state=='done')
assert(count('furnace-input')==7 and wh.count(iron)==90,'group contents counted as stock')
assert(wh.groups('furnace').smelter and not next(wh.groups('other')))
assert(wh.ungroup('smelter') and wh.count(iron)==97)
wh.group('smelter','furnace',{input='furnace-input',fuel='furnace-fuel',output='furnace-output'})
assert(wh.count(iron)==90)
local results={}
local id=assert(wh.fetch(iron,75,external,{drones=1,retries=0}))
local s=done(id);assert(s.state=='done' and s.moved==75)
assert(#s.steps==4 and s.steps[1].take.node==name(0,0) and s.steps[2].take.node==name(0,2) and s.steps[3].take.node==name(0,3),'largest-count source order')
assert(wh.count(iron)==15 and count(source)==0 and count(second)==0 and count(third)==15)
results.fetch=s
-- Nonmember observations now remain available to the UI. Re-adding a formerly
-- scanned face retains its known contents/capacity, rather than erasing stock.
wh.add(external)
assert(done(lg.transfer(iron,3,outsider,external,{drones=1,retries=0})).state=='done')
assert(count(external)==78 and wh.contents(external).slots==27,'nonmember observation was lost')
assert(done(lg.transfer(iron,3,external,outsider,{drones=1,retries=0})).state=='done')
assert(count(external)==75);wh.remove(external)
-- A truly unread face still learns only the delivery, not pre-existing slots.
-- Approach the now-empty first chest from below using a temporary named face.
map.add('unreadFace',0,64,1,{faces={[1]=true}});map.link('H','unreadFace');map.name('unread','unreadFace',1)
wh.add('unread')
assert(done(lg.transfer(iron,3,outsider,'unread',{drones=1,retries=0})).state=='done')
assert(count('unread')==3 and wh.contents('unread').capacityUnknown,'unscanned delivery invented capacity')
assert(done(lg.transfer(iron,3,'unread',outsider,{drones=1,retries=0})).state=='done')
assert(count('unread')==0);wh.remove('unread');map.unname('unread');map.remove('unreadFace')
-- Someone else submitted this transfer: warehouse must observe it too.
s=done(lg.transfer(iron,40,external,source,{drones=1,retries=0}))
assert(s.state=='done' and s.item.name==iron.name and s.from.node==name(7,3) and s.to.node==name(0,0))
assert(count(source)==40 and wh.count(iron)==55);results.direct=s
local marker=assert(io.open('/home/warehouse-remove-items','w'));marker:write('remove 24 from the native chest after scan');marker:close()
assert(event.pull(10,'warehouse_items_removed'),'native player removal missing')
s=done(assert(wh.fetch(iron,40,external,{drones=1,retries=0})))
assert(s.state=='partial' and s.moved==16 and s.steps[1].short,'shortfall not observable')
assert(count(source)==0 and wh.count(iron)==15,'shortfall did not correct actual source count');results.shortfall=s
-- Policy test inventories are no longer fetch sources. Register only these
-- destinations; a rejecting filter must stay excluded even with priority 999.
for _,v in ipairs({source,second,third,'shared'}) do wh.remove(v) end
local high,low,held,reject,empty,emptyLow=storage(1,0,'N'),storage(2,0,'N'),storage(3,0,'N'),storage(4,0,'N'),storage(5,0,'N'),storage(6,0,'N')
wh.add(high,{filter={iron},priority=20});wh.add(low,{filter={iron},priority=10})
wh.add(held,{priority=500});wh.add(reject,{filter={gold},priority=999})
wh.add(empty,{priority=10});wh.add(emptyLow)
assert(scan()==6)
s=done(assert(wh.store(iron,51,external,{drones=1,retries=0})))
assert(s.state=='done' and s.moved==51 and #s.steps==8)
local expected={high,low,held,empty};local amounts={8,6,10,27}
for i,v in ipairs(expected) do assert(s.steps[i*2].put.node==map.storage(v).node and s.steps[i*2].moved==amounts[i],'store tier/priority order') end
assert(count(high)==64 and count(low)==64 and count(held)==64 and count(reject)==60 and count(empty)==27 and count(emptyLow)==0)
results.store=s
-- Ordinary transfer overflow, return, and step-list return accounting.
s=done(lg.transfer(iron,10,outsider,high,{drones=1,retries=0,overflow=emptyLow}))
assert(s.state=='failed' and s.taken==10 and s.moved==0 and s.overflow==10 and s.overflowEndpoint.node==map.storage(emptyLow).node)
assert(count(high)==64 and count(emptyLow)==10);results.overflow=s
assert(done(lg.transfer(iron,10,emptyLow,outsider,{drones=1,retries=0})).state=='done')
s=done(lg.transfer(iron,10,outsider,high,{drones=1,retries=0}))
assert(s.taken==10 and s.returned==10 and count(high)==64);results.returned=s
s=done(lg.job({{take=empty,item=iron,count=10},{put=high,item=iron,rest=true}},{drones=1,retries=0}))
assert(s.state=='failed' and s.steps[1].taken==10 and s.steps[1].returned==10 and s.steps[1].moved==0 and count(empty)==27);results.stepReturned=s
s=done(lg.job({{take=outsider,item=iron,count=10},{put=high,item=iron,rest=true}},{drones=1,retries=0,overflow=emptyLow}))
assert(s.steps[1].taken==10 and s.steps[1].overflow==10 and s.steps[1].moved==0 and count(emptyLow)==10);results.stepOverflow=s
assert(done(lg.transfer(iron,10,emptyLow,outsider,{drones=1,retries=0})).state=='done')
wh.remove(empty);wh.remove(emptyLow)
local none,why=wh.store(iron,1,outsider);assert(not none and why:find('requested 1, capacity 0',1,true),'no-room failure guesses capacity');results.noRoom=why
none,why=wh.fetch(iron,1000,external);assert(not none and why:find('available 252',1,true),'nonmembers used as fetch sources');results.noStock=why
assert(not wh.members()[outsider] and not wh.members()[external])
-- Same API from the CLI; no private controller/menu implementation.
assert(loadfile('/bin/warehouse.lua'))('count',iron.name,'0')
assert(loadfile('/bin/warehouse.lua'))('groups','furnace')
local catalogue={};for member in pairs(wh.members()) do catalogue[member]=wh.contents(member) end
local snapshot={count=wh.count(iron),members=wh.members(),groups=wh.groups(),catalogue=catalogue}
save('/home/warehouse-expected',snapshot)
save('/home/warehouse-results.lua',{jobs=results,catalogue=catalogue,count=snapshot.count,groups=snapshot.groups,members=snapshot.members,reboot=false})
save('/home/warehouse-performance.lua',performance)
wait(function() local ds=lg.drones();return ds[1].state=='idle' and ds[2].state=='idle' end,30)
save('/home/warehouse-reboot',{ready=true})
computer.shutdown(true)
