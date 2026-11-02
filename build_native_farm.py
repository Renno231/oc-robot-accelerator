"""Native farm trickle: a feeder microcontroller drips coal into a sensor-watched In chest."""
import argparse
import json
from pathlib import Path
from examples.mes.build_fixtures import build_native, write_fixture

COUNT, EVERY = 48, 5

# The farm: one item from its source chest into the In chest every EVERY seconds, once told to start.
FEEDER = r'''
local t=component.proxy(component.list('transposer')())
local m=component.proxy(component.list('modem')());m.open(27199)
local function wait(s) local d=computer.uptime()+s;repeat computer.pullSignal(d-computer.uptime()) until computer.uptime()>=d end
local src,dst
for side=0,5 do if t.getInventorySize(side) then if t.getSlotStackSize(side,1)>0 then src=side else dst=side end end end
repeat local e={computer.pullSignal()} until e[1]=='modem_message' and e[4]==27199 and e[6]=='farm_start'
for i=1,%d do wait(%d);assert(t.transferItem(src,dst,1)==1) end
m.broadcast(27199,'farm_done')
while true do computer.pullSignal() end
''' % (COUNT, EVERY)

PROGRAM = r'''
assert(loadfile('/home/program/install.lua'))()
local event=require('event');local computer=require('computer');local ser=require('serialization')
local function save(p,v) local f=assert(io.open(p,'w'));assert(f:write(ser.serialize(v,false)));f:close() end
save('/etc/store.cfg',{variant='log'})
local map=require('logistics.map');local lg=require('logistics');local wh=require('logistics.warehouse')
-- Drones have no hitboxes for each other: they all share one charger, as in the MES fixtures.
map.add('home',-2,65,2,{charger=true});map.add('corridor2',0,65,2);map.add('corridor8',0,65,8)
map.link('home','corridor2');map.link('corridor2','corridor8');map.save()
local st=require('logistics.stations');local ic=require('logistics.iochest')
local function wait(fn,seconds)
 local deadline=computer.uptime()+(seconds or 180)
 repeat if fn() then return end;event.pull(.1) until computer.uptime()>deadline
 error('farm native timeout')
end
wait(function() return #lg.pending()==6 and #lg.pendingSensors()==1 end)
local drones=lg.pending()
for i,a in ipairs(drones) do assert(lg.register(a,'d'..i,'home')) end
assert(lg.registerSensor(lg.pendingSensors()[1],'s1'))
local reported;event.listen('logistics_sensor',function(_,n,kind) if kind=='report' then reported=true end end)
wait(function() for _,d in ipairs(lg.drones()) do if d.state~='idle' then return false end end;return reported end)
for _,v in ipairs({{'stock',0,'stock'},{'in1',2,'import'}}) do
 assert(st.add('storage',{name=v[1],x=v[2],y=64,z=8,face='top',role=v[3]}))
 wait(function() local s=st.get(v[1]);assert(s.state~='failed',v[1]..': '..tostring(s.reason));return s.state=='ready' end)
end
local function record(n) for _,r in ipairs(ic.list()) do if r.name==n then return r end end end
local coal={name='minecraft:coal',damage=0,label='Coal'}
assert(ic.attach('s1','in1'))
local first=#lg.jobs()+1;local done
event.listen('modem_message',function(_,_,_,port,_,token) if port==27199 and token=='farm_done' then done=computer.uptime() end end)
require('component').modem.open(27199)
local start=computer.uptime();require('component').modem.broadcast(27199,'farm_start')
wait(function() return done end,%d)
wait(function() local r=record('in1');return wh.count(coal)==%d and not next(r.pending) and not r.refresh end,180)
local result={collects=0,trips=0,items={},finished=computer.uptime()-start,lastItemWait=computer.uptime()-done}
for _,j in ipairs(lg.jobs()) do if j.id>=first then local s=lg.status(j.id)
 assert(s.state=='done',s.reason);result.collects=result.collects+1;result.trips=result.trips+s.trips
 local n=0;for _,v in ipairs(s.steps or {}) do if v.take then n=n+(v.taken or 0) end end;result.items[#result.items+1]=n
end end
save('/home/farm-result',result)
print('farm passed',ser.serialize(result))
return true
''' % (COUNT * EVERY + 60, COUNT)


def build(root):
    path = build_native(Path(root) / 'fixture', 'bricks16')
    program = path.parent / 'program'
    (program / 'main.lua').write_text(PROGRAM)
    (path.parent / 'feeder.lua').write_text(FEEDER)
    value = json.loads(path.read_text()); value['id'] = 'farm-trickle'
    value.pop('robots', None)
    value['blocks'] = [b for b in value['blocks'] if b['block'] != 'minecraft:furnace']
    # Keep the cleared room and floor, not the removed furnaces' bottom-access holes.
    value['world']['blocks'] = value['world']['blocks'][:2]
    value['containers'] = [
        {'position': [0, 64, 8], 'block': 'minecraft:chest', 'slots': []},
        {'position': [2, 64, 8], 'block': 'minecraft:chest', 'slots': []},
        {'position': [3, 64, 7], 'block': 'minecraft:chest', 'slots': [{'slot': 1, 'item': 'minecraft:coal', 'count': COUNT}]},
    ]
    hardware = {'tier': 2, 'cpu': 'cpu1', 'memory': ['ram1'], 'cards': ['wlancard2'], 'upgrades': ['transposer']}
    value['microcontrollers'] = [{'position': [2, 64, 9], 'eeprom': 'loader.lua', 'hardware': hardware},
                                 {'position': [3, 64, 8], 'eeprom': 'feeder.lua', 'hardware': hardware}]
    value['expect'] = {'drones': value['expect']['drones'], 'containers': [
        {'position': [2, 64, 8], 'slots': [{'slot': 1, 'count': 0}]},
        {'position': [3, 64, 7], 'slots': [{'slot': 1, 'count': 0}]},
    ]}
    value['execution'].update(maxTicks=20000, timeoutSeconds=900, infiniteEnergy=True)
    return write_fixture(path, value)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    print(build(parser.parse_args().root))
