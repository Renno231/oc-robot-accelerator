"""RR native worlds: real unpaired boot/register and boot-driven R4 recovery."""
import argparse
import copy
import json
import shutil
from pathlib import Path
import subprocess
import sys
from build_machine_comparisons import prepare
from build_native_restarts import build as restart
from supervisor import NO_WINDOW


def build(root, case):
    root = Path(root)
    if case == 'robot-reboot':
        path = restart(root, 'robot-craft')
        observer = path.parent / 'program/main.lua'
        source = observer.read_text()
        source = source.replace("local ok,err=xpcall", '''
event.listen('modem_message',function(_,_,sender,port,_,kind,name,cid)
  if port==27105 and kind=='mes_robot_boot' then clientTrace('boot notice',{address=sender,name=name,cid=cid}) end
end)
local ok,err=xpcall''', 1)
        observer.write_text(source)
        return path

    path = prepare('examples/mes/bricks16', root / 'fixture', 'coordinated')
    fixture = path.parent
    observer = fixture / 'program/main.lua'
    observer.write_text(observer.read_text().replace('local ok,err=xpcall', '''
-- Preserve every completed trip/read, not just logistics' final retention window.
event.listen('logistics',function(_,id)
  local lg=package.loaded.logistics
  local status=lg and lg.status(id)
  if status then
    local f=assert(io.open('/home/r4-jobs.ndjson','a'))
    json(f,{id=id,status=status,boot=count+1});f:write('\\n');f:close()
  end
end)
local ok,err=xpcall''', 1))
    main = fixture / 'program/native-main.lua'
    source = main.read_text()
    source = source.replace("{'map','logistics','warehouse'}", "{'cbor','store','map','logistics','warehouse'}", 1)
    source = source.replace("assert(hosts.addHost(component.modem.address,computer.address(),'controller',fixtureWake,{}))",
                            "local f=assert(io.open('/etc/hostname','w'));f:write('controller');f:close()", 1)
    begin = source.index('local address,distances')
    end = source.index("wait(function() return #lg.pending()==6", begin)
    source = source[:begin] + '''
local distances,robotDistances={},{}
event.listen('modem_message',function(_,_,sender,port,distance,kind)
  if port==27103 and kind=='lgx_hello' then distances[sender]=distance end
  if port==27105 and kind=='mes_robot_hello' then robotDistances[sender]=distance end
end)
local setup=assert(loadfile('/home/program/setup.lua'))()
local map=require('map');map.add('cpu2-hover',8,65,3,{faces={[3]=true}})
map.link('8:65:2','cpu2-hover');map.link('cpu2-hover','9:65:3')
map.name('cpu2.buf','cpu2-hover',3);map.save()
save('/etc/mes.cfg',{crafters={},machineTypes={furnace={inputs={'input'},output='output',
  roles={'input','fuel','output'},roleSlots={input={1},fuel={1},output={1}},
  fuel={role='fuel',item='minecraft:coal',per=8},batch=64,seconds=10,blocking=false}}})
assert(mes.start())
wait(function() return #mes.pendingRobots()==2 end,60)
local pendingRobots=mes.pendingRobots()
table.sort(pendingRobots,function(a,b) return robotDistances[a.address]<robotDistances[b.address] end)
save('/home/rr-unpaired.lua',{pending=pendingRobots,hosts=hosts.getAll(),time=computer.uptime()})
for i,r in ipairs(pendingRobots) do
  assert(not hosts.getHost(r.address),'fixture robot must be unpaired')
  assert(mes.registerRobot(r.address,'cpu'..i,'cpu'..i..'.buf'))
end
assert(#mes.pendingRobots()==0)
save('/home/rr-registered.lua',mes.crafters())
''' + source[end:]
    source = source.replace('mes.plan(target,16)', 'mes.plan(target,8)', 1)
    source = source.replace("local each=case=='torches16' and 2 or 32", "local each=16", 1)
    source = source.replace('local outcome=assert(mes.wait(runId));', '''
  local secondId=assert(mes.run('/home/mes.plan',{crafter='cpu2',pollSeconds=0.2}))
  local outcome=assert(mes.wait(runId));local second=assert(mes.wait(secondId))
  assert(outcome.status=='complete' and second.status=='complete')
  for _,s in ipairs(outcome.stages) do if s.kind=='robot' then assert(s.crafter=='cpu1') end end
  for _,s in ipairs(second.stages) do if s.kind=='robot' then assert(s.crafter=='cpu2') end end
  result.second=second;result.secondTiming=mesTiming(second)
  save('/home/rr-second-execution.lua',second)
  assert(not next(read('cpu2.buf')))
  ''', 1)
    main.write_text(source)
    (fixture / 'robot-program/main.lua').write_text(
        "assert(loadfile('/home/program/install.lua'))()\n"
        "assert(loadfile('/usr/bin/cproc.lua'))('--side=3')\n")
    value = json.loads(path.read_text())
    value['id'] = 'rr-robot-register'
    robot = copy.deepcopy(value['robots'][0])
    robot['position'] = [8, 65, 5]
    robot['facing'] = 'north'
    shutil.copytree(fixture / 'robot-program', fixture / 'robot2-program')
    robot['program']['directory'] = 'robot2-program'
    value['robots'].append(robot)
    value['containers'].append({'position': [8, 65, 4], 'block': 'minecraft:chest', 'slots': []})
    value['expect']['containers'].append({'position': [8, 65, 4], 'slots':
        [{'slot': n, 'count': 0} for n in range(1, 28)]})
    check = copy.deepcopy(value['expect']['robots'][0]);check['index'] = 1
    value['expect']['robots'].append(check)
    path.write_text(json.dumps(value, indent=2) + '\n')
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--jobs-root', type=Path, required=True)
    parser.add_argument('--case', choices=('robot-register', 'robot-reboot'), required=True)
    parser.add_argument('--installation', type=Path, default=Path('C:/or/drone-install-T11'))
    args = parser.parse_args()
    path = build(args.root, args.case)
    command = [sys.executable, 'runner.py', 'run', str(path), '--installation',
               str(args.installation), '--jobs-root', str(args.jobs_root)]
    with (args.root / 'native-command.log').open('w') as output:
        result = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
    text = (args.root / 'native-command.log').read_text()
    state = json.loads(text.strip().splitlines()[-1])
    summary = {'case': args.case, 'command': command, 'commandExit': result.returncode,
               'root': str(args.root), 'jobsRoot': str(args.jobs_root), 'state': state}
    (args.root / 'run.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary), flush=True)
    sys.exit(result.returncode)
