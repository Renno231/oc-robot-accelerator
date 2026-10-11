"""Isolated real IO/lost-drone/MES-failure fixtures with incident snapshots."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
from build_machine_comparisons import prepare
from build_native_io_flow import build as io_build

DRONE=('cbor','store','map','logistics','warehouse','stations','stats','iochest')
PREFIX=r'''
local afs=require('filesystem');local aevent=require('event');local aser=require('serialization')
afs.makeDirectory('/lib/logistics')
for _,n in ipairs({'cbor','store','map','logistics','warehouse','stations','stats','iochest','mes_alerts','mes_alert_sources'}) do
 assert(afs.copy('/home/program/lib/'..n..'.lua','/lib/'..n..'.lua'))
end
for _,n in ipairs({'agent','sensor'}) do assert(afs.copy('/home/program/drone/'..n..'.lua','/lib/logistics/'..n..'.lua')) end
ALERT_EVENTS={}
function alertSnapshot()
 local evidence={events=ALERT_EVENTS,list=require('mes_alerts').list(),settings=require('mes_alerts').settings()}
 local f=assert(io.open('/home/alerts-evidence.lua','w'));assert(f:write(aser.serialize(evidence,false)));f:close()
 return evidence
end
function alertState(kind,state)
 for _,r in ipairs(require('mes_alerts').list()) do if r.kind==kind and r.state==state then return r end end
end
function alertEvent(kind,state,id)
 for _,r in ipairs(ALERT_EVENTS) do if r.kind==kind and r.state==state and r.id==id then return true end end
end
aevent.listen('alert',function(_,id,kind,state)
 ALERT_EVENTS[#ALERT_EVENTS+1]={id=id,kind=kind,state=state,time=require('computer').uptime()}
 alertSnapshot()
end)
'''


def build(root,case):
    root=Path(root)
    if case=='io':
        path=io_build(root)
        entry=path.parent/'program/native-main.lua'
        program=entry.read_text()
        program=program.replace("local coal={name='minecraft:coal',damage=0,label='Coal'}",
                                "local coal={name='minecraft:coal',damage=0,label='Coal'}\nassert(wh.add('stock',{filter={coal}}))")
        program=program.replace("result.steps.stockFull={stock=wh.count(coal),record=record('in2')}",'''result.steps.stockFull={stock=wh.count(coal),record=record('in2')}
wait(function() return alertState('importBlocked','active') end)
local recoveryJob=assert(ic.fetch(coal,256,'out1'))
wait(function() return wh.settled(recoveryJob) and idle('out1') end)
assert(wh.count(coal)==0 and count('out1')==256)
wait(function() return not alertState('stockFull','active') and alertState('stockFull','cleared') end)
assert(ic.importNow('in2'))
wait(function() return idle('in2') and count('in2')==0 and wh.count(coal)==104 and not record('in2').reason and not alertState('importBlocked','active') and alertState('importBlocked','cleared') end)
assert(alertState('stockFull','cleared'))
result.steps.alertRecovery={stock=wh.count(coal),record=record('in2'),export=record('out1')}
alertSnapshot()''')
        program=PREFIX+"require('mes_alerts').start({groups={}})\n"+program
        value=json.loads(path.read_text())
        for container in value['expect']['containers']:
            if container['position']==[6,64,8]:
                container['slots']=[{'slot':s,'count':0} for s in range(1,5)]
            elif container['position']==[10,64,8]:
                container['slots']=[{'slot':s,'item':'minecraft:coal','count':64} for s in range(1,5)]
            elif container['position']==[0,64,8]:
                container['slots']=container['slots'][:23]+[
                    {'slot':24,'item':'minecraft:coal','count':64},{'slot':25,'item':'minecraft:coal','count':40},
                    {'slot':26,'count':0},{'slot':27,'count':0}]
    elif case=='lost':
        path=prepare('examples/logistics/fixes',root/'fixture','coordinated',observe=False)
        entry=path.parent/'program/main.lua'
        entry.write_text(PREFIX+"require('mes_alerts').start({groups={}})\n"+entry.read_text()+
            "\nrequire('event').pull(.1);assert(alertState('droneLost','cleared'));alertSnapshot()\n")
        suite=Path('examples/logistics/testsuite.lua').read_text()
        suite=suite.replace('check(not logistics.release("d1"),"lost release accepted")',
                            'check(not logistics.release("d1"),"lost release accepted");event.pull(.1);assert(alertState("droneLost","active"))')
        suite=suite.replace('local cargo=assert(logistics.release("d1"))','''local function releaseCargo()
      assert(logistics.release("d1"))
      untilTrue(function() return not logistics.drones()[1].releasePending end,10,"release reply missing")
      return assert(logistics.drones()[1].cargo)
    end
    local cargo=releaseCargo()''')
        suite=suite.replace('not next(assert(logistics.release("d1")))','not next(releaseCargo())')
        (path.parent/'program/testsuite.lua').write_text(suite)
        value=json.loads(path.read_text())
        program=None
    else:
        spec=importlib.util.spec_from_file_location('alerts_mes_builder','examples/mes/build_fixtures.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        module.build(root/'fixture','shortfall')
        path=root/'fixture/scenario.json';entry=path.parent/'program/main.lua'
        program=PREFIX+entry.read_text()+'''
require('event').pull(.1)
local failed=assert(alertState('runFailed','active'))
assert(require('mes_alerts').dismiss(failed.id));assert(alertState('runFailed','dismissed'))
local deadline=require('computer').uptime()+10
while not alertEvent('runFailed','dismissed',failed.id) do
 assert(require('computer').uptime()<deadline,'dismiss event missing');require('event').pull(.1)
end
alertSnapshot()
'''
        value=json.loads(path.read_text())
    destination=path.parent/'program'
    for name in DRONE:
        target=destination/'lib'/f'{name}.lua';target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(Path('drone-logistics/lib')/f'{name}.lua',target)
    for name in ('mes_alerts','mes_alert_sources'):
        shutil.copyfile(Path('craftsystem/usr/lib')/f'{name}.lua',destination/'lib'/f'{name}.lua')
    for name in ('agent','sensor'):
        target=destination/'drone'/f'{name}.lua';target.parent.mkdir(parents=True,exist_ok=True)
        if case=='lost' and name=='agent':
            target.write_bytes(Path('examples/logistics/fixes-hook.lua').read_bytes()+b'\n'+Path('drone-logistics/drone/agent.lua').read_bytes())
        else:
            shutil.copyfile(Path('drone-logistics/drone')/f'{name}.lua',target)
    shutil.copyfile('drone-logistics/drone/loader.lua',path.parent/'loader.lua')
    if program is not None:
        entry.write_text(program)
    value['id']='alerts-'+case
    path.write_text(json.dumps(value,indent=2)+'\n')
    return path


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--case',choices=('io','lost','failed'),required=True)
    args=parser.parse_args();print(build(args.root,args.case))
