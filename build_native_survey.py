"""Independent roots for overlapping survey-wall and survey-mixed native runs."""
import argparse
import json
from pathlib import Path
import shutil
from build_machine_comparisons import prepare


PROGRAM = r'''
local fs=require('filesystem');local event=require('event');local computer=require('computer')
local ser=require('serialization');local component=require('component')
for _,n in ipairs({'cbor','store','map','logistics','warehouse','stations','survey'}) do
  assert(fs.copy('/home/program/lib/'..n..'.lua','/lib/'..n..'.lua'))
end
fs.makeDirectory('/lib/logistics')
for _,n in ipairs({'agent','survey'}) do assert(fs.copy('/home/program/drone/'..n..'.lua','/lib/logistics/'..n..'.lua')) end
local function save(p,v) local f=assert(io.open(p,'w'));assert(f:write(ser.serialize(v,false)));f:close() end
local eventFailure
event.onError=function(reason) eventFailure=tostring(reason);print('EVENT ERROR',reason);save('/home/survey-event-error.lua',{reason=eventFailure}) end
save('/etc/store.cfg',{variant='log'})
local fixture=assert(loadfile('/home/program/survey-case.lua'))()
local map=require('map');local lg=require('logistics');local wh=require('warehouse')
local distances={}
event.listen('modem_message',function(_,_,sender,port,distance,token)
  if port==27103 and token=='lgx_hello' then distances[sender]=distance end
end)
for i=1,6 do local n='home'..i;map.add(n,-2,65,i+1,{charger=true})
  if i>1 then map.link('home'..(i-1),n) end
end
map.add('corridor',0,65,8);map.link('home6','corridor');map.save()
local st=require('stations')
local function wait(fn)
  local deadline=computer.uptime()+1200
  repeat assert(not eventFailure,eventFailure);if fn() then return end;event.pull(.1) until computer.uptime()>deadline
  error('survey native timeout')
end
wait(function() return #lg.pending()==6 end)
local pending=lg.pending();table.sort(pending,function(a,b) return distances[a]<distances[b] end)
for i,a in ipairs(pending) do assert(lg.register(a,'d'..i,'home'..i)) end
wait(function() for _,d in ipairs(lg.drones()) do if d.state~='idle' then return false end end;return true end)
local carrier
for _,d in ipairs(lg.drones()) do if d.survey then assert(not carrier);carrier=d end end
assert(carrier and carrier.cargoSlots==4)
local result={case=fixture.name,carrier=carrier,controllerMemory={before=computer.freeMemory()},jobs={}}
local sv=require('survey');result.controllerMemory.after=computer.freeMemory()
save('/home/survey-results.lua',result)
-- Freeze each exact dispatched route/command without retaining a second ledger.
local modem=component.modem;local send=modem.send
modem.send=function(address,port,token,kind,trip,payload,...)
  if kind=='trip' then save('/home/survey-trip-'..trip..'.lua',
    {address=address,trip=trip,task=ser.unserialize(payload)}) end
  return send(address,port,token,kind,trip,payload,...)
end
local id=assert(sv.request(fixture.area))
wait(function() local r=sv.list()[id];assert(r.state~='failed',r.reason);return r.state=='proposed' end)
local r=sv.get(id);result.proposal=r;local choices={};local wall,double,choose,machine,torch
save('/home/survey-proposal.lua',r)
for _,g in ipairs(r.groups) do
  if g.kind=='wall' then wall=g end
  if g.pair==2 then double=g end
  if g.face=='choose' then choose=g end
  choices[g.id]={role='stock',prefix='found'..g.id,face=g.face=='choose' and 'north' or nil}
end
for _,v in ipairs(r.ignored) do
  if v.name=='minecraft:furnace' then machine=v end
  if v.name=='minecraft:torch' then torch=v end
end
if fixture.name=='survey-wall' then assert(wall and wall.levels==3 and #r.groups==1,'wall not grouped')
else
  assert(double and double.spacing==2 and #double.inventories==3,'double row evidence')
  assert(choose and #choose.faces==2,'free chest face choice')
  assert(machine and machine.kind:find('S2'),'furnace missing')
  assert(torch,'torch not analyzed and proven')
  local missing={};for k,v in pairs(choices) do missing[k]={role=v.role,prefix=v.prefix} end
  assert(not sv.approve(id,missing),'face defaulted')
end
assert(sv.approve(id,choices))
for _,n in ipairs(sv.get(id).stations) do
  wait(function() local s=st.get(n);assert(s.state~='failed',s.reason);return s.state=='ready' end)
end
result.stations={};for _,n in ipairs(sv.get(id).stations) do result.stations[n]=st.get(n) end
local buffer=assert(st.add('storage',{x=0,y=64,z=10,face='top',name='buffer',role='other'}))
wait(function() local s=st.get(buffer);assert(s.state~='failed',s.reason);return s.state=='ready' end)
local item={name='minecraft:coal',damage=0}
result.before=wh.count(item);assert(result.before==fixture.coal,'inventory counted twice or missed: '..result.before)
local function done(job)
  wait(function() local s=lg.status(job);assert(s.state~='failed',s.reason);return s.state=='done' and wh.settled(job) end)
end
done(assert(wh.fetch(item,1,'buffer')));done(assert(wh.store(item,1,'buffer')))
result.after=wh.count(item);assert(result.after==result.before)
for _,j in ipairs(lg.jobs()) do result.jobs[j.id]=lg.status(j.id) end
result.record=sv.get(id);result.fleet=lg.drones();result.controllerMemory.finished=computer.freeMemory()
local marked=0;for _,d in ipairs(result.fleet) do assert(type(d.survey)=='boolean');if d.survey then marked=marked+1 end end
assert(marked==1,'survey capability mark was replaced by scan payload')
save('/home/survey-results.lua',result)
print(fixture.name,'passed',r.metrics.scans,'scans',r.metrics.hops,'hops',r.metrics.analyzes,'analyzes',r.metrics.energy,'energy')
return true
'''


def build(root, case):
    path = prepare('examples/mes/bricks16', Path(root) / 'fixture', 'coordinated')
    program = path.parent / 'program'
    # Exact trip packets suffice; the inherited optional per-tick stream hits
    # its 32 MB bound during long surveys with six carriers.
    (program / 'route-metrics-enabled').unlink(missing_ok=True)
    (program / 'native-main.lua').write_text(PROGRAM)
    for name in ('cbor', 'store', 'map', 'logistics', 'warehouse', 'stations', 'survey'):
        shutil.copyfile(f'drone-logistics/lib/{name}.lua', program / f'lib/{name}.lua')
    for name in ('agent', 'survey'):
        shutil.copyfile(f'drone-logistics/drone/{name}.lua', program / f'drone/{name}.lua')
    shutil.copyfile('drone-logistics/drone/loader.lua', path.parent / 'loader.lua')
    value = json.loads(path.read_text())
    value['id'] = case
    value.pop('robots', None)
    value['drones'][0]['hardware']['upgrades'].append('geolyzer')
    value['world'] = {'region': {'min': [-6, 62, -2], 'max': [14, 71, 12]}, 'blocks': [
        {'min': [-6, 62, -2], 'max': [14, 71, 12], 'block': 'minecraft:air'},
        {'min': [-6, 62, -2], 'max': [14, 63, 12], 'block': 'minecraft:stone'}]}
    value['blocks'] = [b for b in value['blocks'] if b['block'] != 'minecraft:furnace']
    # The seed fixture powers only its first two chargers. Enable all six:
    # an idle carrier on the last unpowered charger otherwise drains its battery.
    placed = {tuple(b['position']) for b in value['blocks']}
    for z in range(2, 8):
        if (-2, 63, z) not in placed:
            value['blocks'].append({'position': [-2, 63, z], 'block': 'minecraft:redstone_block'})
    # Survey leaves five carriers idle for longer than the transport fixture.
    # Power the physical charger bus; keep infiniteEnergy=False for real costs.
    for x in range(-5, 0):
        for z in range(-1, 10):
            value['blocks'].append({'position': [x, 62, z], 'block': 'opencomputers:capacitor', 'energy': 1600})
    for p in ([-3, 63, 2], [-5, 63, 2], [-5, 64, 2]):
        value['blocks'].append({'position': p, 'block': 'opencomputers:capacitor', 'energy': 1600})

    def stone(x, y, z):
        value['blocks'].append({'position': [x, y, z], 'block': 'minecraft:stone'})

    chests = []
    if case == 'survey-wall':
        for y in range(64, 67):
            for x in range(2, 6):
                chests.append([x, y, 10]);stone(x, y, 11)
            stone(1, y, 10);stone(6, y, 10)
        for x in range(2, 6):
            stone(x, 67, 10)
        area = '{x1=2,y1=64,z1=10,x2=5,y2=66,z2=10}'
    else:
        for x in range(2, 8):
            chests.append([x, 64, 10]);stone(x, 65, 10);stone(x, 64, 11)
        stone(1, 64, 10);stone(8, 64, 10)
        chests.append([9, 64, 10]);stone(10, 64, 10);stone(9, 64, 11)
        value['blocks'].append({'position': [11, 64, 10], 'block': 'minecraft:furnace', 'properties': {'facing': 'north'}})
        stone(8, 64, 9)
        value['blocks'].append({'position': [8, 65, 9], 'block': 'minecraft:torch'})
        area = '{x1=1,y1=64,z1=9,x2=11,y2=65,z2=10}'
    value['containers'] = [{'position': p, 'block': 'minecraft:chest', 'slots': [
        {'slot': 1, 'item': 'minecraft:coal', 'count': 2}]} for p in chests]
    value['containers'].append({'position': [0, 64, 10], 'block': 'minecraft:chest', 'slots': []})
    (program / 'survey-case.lua').write_text("return {name='%s',area=%s,coal=%s}\n" % (case, area, len(chests)*2))
    value['expect'] = {'drones': value['expect']['drones']}
    value['execution'].update(maxTicks=48000, timeoutSeconds=2400, infiniteEnergy=False)
    path.write_text(json.dumps(value, indent=2) + '\n')
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--case', choices=('survey-wall', 'survey-mixed'), required=True)
    args = parser.parse_args()
    print(build(args.root, args.case))
