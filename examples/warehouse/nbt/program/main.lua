local fs=require('filesystem');fs.makeDirectory('/lib/logistics')
for _,name in ipairs({'cbor','store','map','logistics','warehouse'}) do assert(fs.copy('/home/program/lib/'..name..'.lua','/lib/'..name..'.lua')) end
assert(fs.copy('/home/program/drone/agent.lua','/lib/logistics/agent.lua'))
local map=require('map');local event=require('event');local computer=require('computer')
map.add('H',0,65,0,{charger=true});map.add('A',0,65,2,{faces={[0]=true}})
map.add('M',3,65,2);map.add('B',6,65,2,{faces={[0]=true}})
map.link('H','A');map.link('A','M');map.link('M','B');map.name('a','A',0);map.name('b','B',0);map.save()
local lg=require('logistics')
local function wait(predicate)
  local deadline=computer.uptime()+120
  repeat if predicate() then return end;event.pull(0.1) until computer.uptime()>deadline;error('NBT accounting timeout')
end
wait(function() return #lg.pending()==1 end);assert(lg.register(lg.pending()[1],'d','H'))
wait(function() return lg.drones()[1].state=='idle' end)
local wh=require('warehouse');local complete={}
event.listen('logistics',function(_,id) complete[id]=true end)
local function done(id) assert(id);wait(function() return complete[id] end);return assert(lg.status(id)) end
local function scan(list) for _,id in ipairs(wh.scan(list)) do assert(done(id).state=='done') end end
local iron={name='minecraft:iron_ingot',damage=0}
local function quantity(storage) local n=0;for _,v in pairs(wh.contents(storage).items) do n=n+v.count end;return n end
wh.add('a');wh.add('b');scan()
assert(wh.count(iron)==80 and #wh.find(iron)==1,'NBT variants were not merged')
local s=done(assert(wh.fetch(iron,80,'b',{drones=1,retries=0})))
assert(s.state=='partial' and s.moved==64 and s.steps[1].short and s.steps[1].found==16,'unmergeable cargo did not report actual remaining stock')
assert(quantity('a')==16 and quantity('b')==64 and wh.count(iron)==80,'shortfall erased NBT stock still in source')
s=done(lg.job({{read='a'}},{drones=1}));assert(s.steps[1].listing[5].size==16,'native residual stack missing')
assert(done(lg.transfer(iron,16,'a','b',{drones=1,retries=0})).state=='done')
scan({'b'})
assert(quantity('a')==0 and quantity('b')==80 and wh.count(iron)==80)
local types=0;for _,v in pairs(wh.contents('b').items) do if v.count>0 then types=types+1;assert(v.stacks==5 and v.maxSize==64) end end
assert(types==1,'hidden NBT used as catalogue identity')
print('warehouse native NBT merge and nonzero shortfall remainder verified')
