"""Native IO flow: shared loader, three real sensors, six native drones."""
import argparse
import json
from pathlib import Path
import shutil
from build_machine_comparisons import prepare


PROGRAM = r'''
local fs=require('filesystem');local event=require('event');local computer=require('computer')
local ser=require('serialization');local component=require('component')
for _,n in ipairs({'cbor','store','map','logistics','warehouse','stations','iochest'}) do
 assert(fs.copy('/home/program/lib/'..n..'.lua','/lib/'..n..'.lua'))
end
fs.makeDirectory('/lib/logistics')
for _,n in ipairs({'agent','sensor'}) do assert(fs.copy('/home/program/drone/'..n..'.lua','/lib/logistics/'..n..'.lua')) end
local function save(p,v) local f=assert(io.open(p,'w'));assert(f:write(ser.serialize(v,false)));f:close() end
save('/etc/store.cfg',{variant='log'})
local distances={};event.listen('modem_message',function(_,_,sender,port,distance,token)
 if port==27103 and token=='lgx_hello' then distances[sender]=distance end
end)
local map=require('map');local lg=require('logistics');local wh=require('warehouse')
for i=1,6 do local n='home'..i;map.add(n,-2,65,i+1,{charger=true});if i>1 then map.link('home'..(i-1),n) end end
map.add('corridor2',0,65,2);map.add('corridor8',0,65,8)
map.link('home1','corridor2');map.link('corridor2','corridor8');map.save()
local st=require('stations');local ic=require('iochest')
local function wait(fn)
 local deadline=computer.uptime()+180
 repeat if fn() then return end;event.pull(.1) until computer.uptime()>deadline
 error('io native timeout')
end
wait(function() return #lg.pending()==6 and #lg.pendingSensors()==3 end)
local drones=lg.pending();table.sort(drones,function(a,b) return distances[a]<distances[b] end)
for i,a in ipairs(drones) do assert(lg.register(a,'d'..i,'home'..i)) end
local sensors=lg.pendingSensors();table.sort(sensors,function(a,b) return distances[a]<distances[b] end)
for i,a in ipairs(sensors) do assert(lg.registerSensor(a,'s'..i)) end
local reports={};event.listen('logistics_sensor',function(_,n,kind,data)
 if kind=='report' then reports[n]=ser.unserialize(data) end
end)
wait(function() for _,d in ipairs(lg.drones()) do if d.state~='idle' then return false end end;return true end)
wait(function() return reports.s1 and reports.s2 and reports.s3 end)
for n,p in pairs(reports) do assert(p.size==27 and not p.state,n..':'..tostring(p.reason)) end
local result={jobs={},reasons={},reports=reports,steps={}}
for _,v in ipairs({{'stock',0,'stock'},{'in1',2,'import'},{'in2',6,'import'},{'out1',10,'export'}}) do
 local first=#lg.jobs()+1;assert(st.add('storage',{name=v[1],x=v[2],y=64,z=8,face='top',role=v[3]}))
 wait(function() local s=st.get(v[1]);assert(s.state~='failed',s.reason);return s.state=='ready' end)
 for _,j in ipairs(lg.jobs()) do if j.id>=first then result.reasons[j.id]=lg.status(j.id).test and 'usual station link check' or 'usual station commissioning read' end end
end
assert(wh.members().stock and not wh.members().in1 and not wh.members().in2 and not wh.members().out1)
local function record(n) for _,r in ipairs(ic.list()) do if r.name==n then return r end end end
local function count(n) local r=record(n);local v=r.listing['minecraft:coal:0'];return v and v.count or 0 end
local coal={name='minecraft:coal',damage=0,label='Coal'}
local function idle(n) local r=record(n);return not next(r.pending) and not r.refresh end
assert(ic.attach('s1','in1'));assert(ic.attach('s3','out1'))
wait(function() return idle('in1') and wh.count(coal)==256 end)
result.steps.import3={stock=wh.count(coal),record=record('in1')};assert(count('in1')==0)
local id=assert(ic.fetch(coal,128,'out1'))
wait(function() local s=lg.status(id);return wh.settled(id) and idle('out1') and s.state~='active' and s.state~='queued' end)
assert(lg.status(id).state=='done' and lg.status(id).moved==128)
result.steps.fetch2={stock=wh.count(coal),record=record('out1')};assert(wh.count(coal)==128)
assert(count('out1')==128,'sensor export was counted twice')
local seq=record('out1').seq
assert(io.open('/home/io-take-output','w')):close()
wait(function() return record('out1').seq>seq and count('out1')==0 end)
result.steps.playerEmpty=record('out1')
assert(ic.attach('s2','in2'))
wait(function() return idle('in2') and wh.count(coal)==256 and record('in2').reason end)
-- Let the settled remaining inventory report arrive; this must not create a retry loop.
event.pull(5)
local before=#lg.jobs();event.pull(3);assert(#lg.jobs()==before)
assert(count('in2')==104 and record('in2').reason:find('104',1,true),record('in2').reason)
result.steps.stockFull={stock=wh.count(coal),record=record('in2')}
wait(function() for _,d in ipairs(lg.drones()) do if d.state~='idle' then return false end end;return true end)
local reads,trips=0,0
for _,j in ipairs(lg.jobs()) do
 local s=lg.status(j.id);result.jobs[j.id]=s;trips=trips+s.trips
 for _,v in ipairs(s.steps or {}) do
  if v.read then reads=reads+1;assert(result.reasons[j.id]=='usual station commissioning read') end
  if v.take then assert(v.take.node~='h10_65_8','export was a fetch source') end
 end
 if not result.reasons[j.id] then result.reasons[j.id]='IO receipt-driven movement; no inventory read';assert(s.state=='done' or s.state=='partial',s.reason) end
end
assert(reads==4,'extra IO/controller read');result.commissioningReads=reads;result.ioReads=0;result.trips=trips
result.io=ic.list();result.members=wh.members();save('/home/warehouse-results.lua',result)
print('io-flow passed',trips,'trips',reads,'commissioning reads, zero IO reads')
return true
'''


def build(root):
    path = prepare('examples/mes/bricks16', Path(root) / 'fixture', 'coordinated')
    program = path.parent / 'program'
    (program / 'native-main.lua').write_text(PROGRAM)
    for name in ('cbor', 'store', 'map', 'logistics', 'warehouse', 'stations', 'iochest'):
        shutil.copyfile(Path('drone-logistics/lib') / f'{name}.lua', program / 'lib' / f'{name}.lua')
    for name in ('agent', 'sensor'):
        shutil.copyfile(f'drone-logistics/drone/{name}.lua', program / f'drone/{name}.lua')
    shutil.copyfile('drone-logistics/drone/loader.lua', path.parent / 'loader.lua')
    value = json.loads(path.read_text()); value['id'] = 'io-flow'
    value.pop('robots', None)
    value['blocks'] = [b for b in value['blocks'] if b['block'] != 'minecraft:furnace']
    coal = lambda slot, count: {'slot': slot, 'item': 'minecraft:coal', 'count': count}
    stones = [{'slot': s, 'item': 'minecraft:stone', 'count': 64} for s in range(1, 24)]
    value['containers'] = [
        {'position': [0, 64, 8], 'block': 'minecraft:chest', 'slots': stones + [coal(24, 64)]},
        {'position': [2, 64, 8], 'block': 'minecraft:chest', 'slots': [coal(s, 64) for s in range(1, 4)]},
        {'position': [6, 64, 8], 'block': 'minecraft:chest', 'slots': [coal(s, 64) for s in range(1, 4)] + [coal(4, 40)]},
        {'position': [10, 64, 8], 'block': 'minecraft:chest', 'slots': []},
    ]
    value['microcontrollers'] = [{'position': [x, 64, 9], 'eeprom': 'loader.lua',
        'hardware': {'tier': 2, 'cpu': 'cpu1', 'memory': ['ram1'], 'cards': ['wlancard2'], 'upgrades': ['transposer']}}
        for x in (2, 6, 10)]
    value['containerEdits'] = [{'position': [10, 64, 8], 'slot': s, 'count': 64, 'expectedCount': 64,
        'request': {'computer': 0, 'marker': 'home/io-take-output', 'signal': 'io_player_emptied'}} for s in (1, 2)]
    value['expect'] = {'drones': value['expect']['drones'], 'containers': [
        {'position': [0, 64, 8], 'slots': stones + [coal(s, 64) for s in range(24, 28)]},
        {'position': [2, 64, 8], 'slots': [{'slot': s, 'count': 0} for s in range(1, 4)]},
        {'position': [6, 64, 8], 'slots': [{'slot': 1, 'count': 0}, {'slot': 2, 'count': 0}, coal(3, 64), coal(4, 40)]},
        {'position': [10, 64, 8], 'slots': [{'slot': s, 'count': 0} for s in (1, 2)]},
    ]}
    value['execution'].update(maxTicks=12000, timeoutSeconds=600, infiniteEnergy=True)
    path.write_text(json.dumps(value, indent=2) + '\n')
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    print(build(parser.parse_args().root))
