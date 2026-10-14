"""Six drones/eight stock chests: packed HK, physical savings and real MES pre-emption."""
import argparse
import json
from pathlib import Path
from examples.mes.build_fixtures import build_native, write_fixture

RUN = r'''
return assert(loadfile('/home/program/main.lua'))(function(wait)
local mes,wh,lg,event=require('mes'),require('warehouse'),require('logistics'),require('event')
local function count(id) return wh.count({name=id,damage=0}) end
local plan,why=mes.plan('minecraft:brick_block',4);assert(plan,why)
local hk=require('housekeeping');hk.set('enabled',false);hk.set('minFill',0);hk.set('idleSeconds',0)
local result={case='housekeeping',before={coal=count('minecraft:coal'),clay=count('minecraft:clay_ball')},hkJobs={}}
local runId,first
event.listen('housekeeping',function()
  local h=hk.status()
  if h.job then
    result.hkJobs[h.job]=true
    if runId and mes.status(runId).status=='running' then assert(h.job==first,'HK successor delayed real MES') end
  end
end)
hk.set('enabled',true);first=assert(hk.status().job)
wait(function() return lg.status(first).state=='active' end,60)
result.first=first;result.firstTour=lg.status(first)
local kinds=0;for _,s in ipairs(result.firstTour.steps) do if s.take then kinds=kinds+1 end end
assert(kinds>=2,'HK did not pack several items')
runId=assert(mes.run(plan));result.runId=runId
wait(function() return mes.status(runId).status~='running' end,300)
result.mes=mes.status(runId);assert(result.mes.status=='complete',result.mes.reason)
wait(function() local s=hk.status();return not s.job and s.reason=='no worthwhile move' end,180)
hk.set('enabled',false)
result.hk=hk.status();result.after={coal=count('minecraft:coal'),clay=count('minecraft:clay_ball'),blocks=count('minecraft:brick_block')}
assert(result.after.clay==result.before.clay-16 and result.after.blocks==4)
local filtered=wh.contents('s7_0_N');local used=0
for _,v in pairs(filtered.items) do if v.count>0 then used=used+v.stacks end end
assert(used>0)
result.trips=0
for id in pairs(result.hkJobs) do
  local s=assert(lg.status(id));assert(s.state=='done',s.reason)
  for _,v in ipairs(s.steps) do assert(not v.read,'HK read inventory') end
  result.trips=result.trips+s.trips
end
assert(result.trips>=1)
print('HK complete',result.trips,'bounded tours, zero HK reads, real MES complete')
return true
end)
'''


def build(root):
    path = build_native(Path(root) / 'fixture', 'bricks16')
    program = path.parent / 'program'
    (program / 'housekeeping.lua').write_text(RUN)
    # Retain MES routes/buffers but only eight stock inventories, one filtered.
    setup = Path('examples/mes/setup.lua').read_text().split('-- Dedicated destinations')[0]
    setup += "\nfor name in pairs(wh.members()) do if not name:match('^s%d_0_N$') then wh.remove(name) end end\n"
    setup += "wh.add('s7_0_N',{filter={{name='minecraft:coal',damage=0},{name='minecraft:clay_ball',damage=0}}})\nreturn {homes=homes}\n"
    # The original return precedes the appended statements.
    setup = setup.replace('return {homes=homes}\n\nfor', 'for')
    (program / 'setup.lua').write_text(setup)
    value = json.loads(path.read_text()); value['id'] = 'housekeeping'
    value['controller']['program']['entry'] = 'housekeeping.lua'
    for c in value['containers']:
        c['slots'] = []
        x,y,z = c['position']
        if 0 <= x < 8 and y == 65 and z == 1:
            q = 16 if x == 7 else 4
            c['slots'] = [{'slot':s,'item':item,'count':q}
                          for s,item in ((1,'minecraft:coal'),(2,'minecraft:coal'),
                                         (3,'minecraft:clay_ball'),(4,'minecraft:clay_ball'))]
    value['expect'] = {'drones': value['expect']['drones']}
    value['execution'].update(maxTicks=20000,timeoutSeconds=1000)
    return write_fixture(path, value)


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True)
    print(build(p.parse_args().root))
