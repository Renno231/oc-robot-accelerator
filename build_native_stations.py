"""Isolated S1: six drones, new storage/row, and a shared-inventory transfer."""
import argparse
import json
from pathlib import Path
from examples.mes.build_fixtures import build_native, write_fixture


PROGRAM = r'''
assert(loadfile('/home/program/install.lua'))()
local event=require('event');local computer=require('computer');local ser=require('serialization')
local function save(p,v)
  local f=assert(io.open(p,'w'));assert(f:write(ser.serialize(v,false)));f:close()
end
save('/etc/store.cfg',{variant='log'})
local distances={}
event.listen('modem_message',function(_,_,sender,port,distance,token)
  if port==27103 and token=='lgx_hello' then distances[sender]=distance end
end)
local map=require('logistics.map');local lg=require('logistics');local wh=require('logistics.warehouse')
for i=1,6 do local n='home'..i;map.add(n,-2,65,i+1,{charger=true})
  if i>1 then map.link('home'..(i-1),n) end
end
map.add('corridor2',0,65,2);map.add('corridor8',0,65,8)
map.link('home1','corridor2');map.link('corridor2','corridor8');map.save()
local st=require('logistics.stations')
local function wait(fn)
  local deadline=computer.uptime()+180
  repeat if fn() then return end;event.pull(.1) until computer.uptime()>deadline
  error('stations native timeout')
end
wait(function() return #lg.pending()==6 end)
local pending=lg.pending();table.sort(pending,function(a,b) return distances[a]<distances[b] end)
for i,a in ipairs(pending) do assert(lg.register(a,'d'..i,'home'..i)) end
wait(function() for _,d in ipairs(lg.drones()) do if d.state~='idle' then return false end end;return true end)
local result={stations={},jobs={},reasons={},catalogue={}}
local function ready(name)
  wait(function() local r=st.get(name);assert(r.state~='failed',r.reason);return r.state=='ready' end)
end
local function commission(kind,spec)
  local first=#lg.jobs()+1;local start=computer.uptime()
  local name=assert(st.add(kind,spec));ready(name)
  result.stations[name]={seconds=computer.uptime()-start,record=st.get(name)}
  for _,j in ipairs(lg.jobs()) do if j.id>=first then
    local s=lg.status(j.id);result.jobs[j.id]=s
    result.reasons[j.id]=s.test and (kind=='row' and j.id==first+1 and 'new row hover line' or 'new hover link to network') or 'new inventory commissioning read'
  end end
end
commission('storage',{x=0,y=64,z=10,face='top',name='single',role='stock'})
commission('row',{x=2,y=64,z=10,face='top',rowDir='east',count=8,spacing=1,prefix='row',role='stock',pair=2})
local tests,reads=0,0
for _,s in pairs(result.jobs) do
  assert(s.state=='done');if s.test then tests=tests+1 end
  for _,v in ipairs(s.steps or {}) do if v.read then reads=reads+1;assert(v.size==(v.read.node=='h0_65_10' and 27 or 54)) end end
end
result.tests=tests;result.reads=reads;assert(tests==3 and reads==5)
local item={name='minecraft:coal',damage=0}
result.before=wh.count(item)
assert(result.before==100,'paired row catalogue does not conserve all nine seeded inventories: '..result.before)
local id=assert(wh.fetch(item,1,'row2'))
wait(function() local s=lg.status(id);return s.state=='done' and wh.settled(id) end)
result.jobs[id]=lg.status(id);result.reasons[id]='requested transfer into second block of a shared pair'
assert(result.jobs[id].steps[1].take.node=='h0_65_10')
assert(result.jobs[id].steps[2].put.node=='h3_65_10')
result.after=wh.count(item);assert(result.after==100)
result.catalogue=wh.totals();result.members=wh.members()
result.pair=wh.contents('row2');assert(result.members.row2.inventory=='row1')
local n=0;for _,v in pairs(result.pair.items) do n=n+v.count end
assert(n==4,'second-face transfer must appear once in shared pair')
return true
'''


def build(root):
    path = build_native(Path(root) / 'fixture', 'bricks16')
    program = path.parent / 'program'
    (program / 'main.lua').write_text(PROGRAM)
    value = json.loads(path.read_text()); value['id'] = 'stations-row'
    value.pop('robots', None); value['blocks'] = [b for b in value['blocks'] if b['block'] != 'minecraft:furnace']
    value['containers'] = [{'position': [0, 64, 10], 'block': 'minecraft:chest',
                            'slots': [{'slot': 1, 'item': 'minecraft:coal', 'count': 64}]}]
    value['containers'] += [{'position': [i + 2, 64, 10], 'block': 'minecraft:chest',
                             'slots': [{'slot': 1, 'item': 'minecraft:coal', 'count': i + 1}]}
                            for i in range(8)]
    value['expect'] = {'drones': value['expect']['drones']}
    value['execution'].update(maxTicks=12000, timeoutSeconds=600)
    return write_fixture(path, value)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    print(build(parser.parse_args().root))
