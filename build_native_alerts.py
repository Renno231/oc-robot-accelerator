"""Native incident assertions over IO, lost-drone recovery and MES failure."""
import argparse
import json
from pathlib import Path
from build_native_io_flow import build as io_build
from build_native_restarts import build as restart_build
from examples.mes.build_fixtures import build_native, write_fixture

PREFIX=r'''
assert(loadfile('/home/program/install.lua'))()
local aevent=require('event')
ALERT_EVENTS={}
function alertState(kind,state)
 for _,r in ipairs(require('mes.alerts').list()) do if r.kind==kind and r.state==state then return r end end
end
function alertEvent(kind,state,id)
 for _,r in ipairs(ALERT_EVENTS) do if r.kind==kind and r.state==state and r.id==id then return true end end
end
aevent.listen('alert',function(_,id,kind,state)
 ALERT_EVENTS[#ALERT_EVENTS+1]={id=id,kind=kind,state=state,time=require('computer').uptime()}
end)
'''


def build(root,case):
    root=Path(root)
    if case=='lost': return restart_build(root,'drone-trip')
    if case=='io':
        path=io_build(root)
        entry=path.parent/'program/main.lua'
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
''')
        program=PREFIX+"require('mes.alerts').start({groups={}})\n"+program
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
    else:
        path=build_native(root/'fixture','shortfall')
        entry=path.parent/'program/alerts.lua'
        program=PREFIX+"assert(loadfile('/home/program/main.lua'))()\n"+'''
while not alertState('runFailed','active') do require('event').pull() end
local failed=assert(alertState('runFailed','active'))
assert(require('mes.alerts').dismiss(failed.id));assert(alertState('runFailed','dismissed'))
while not alertEvent('runFailed','dismissed',failed.id) do
 require('event').pull()
end
'''
        value=json.loads(path.read_text())
        value['controller']['program']['entry']='alerts.lua'
    entry.write_text(program)
    value['id']='alerts-'+case
    return write_fixture(path, value)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--case',choices=('io','lost','failed'),required=True)
    args=parser.parse_args();print(build(args.root,args.case))
