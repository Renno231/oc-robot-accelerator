"""Real unpaired registration followed by work on both robots, or robot reboot."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from examples.mes.build_fixtures import build_native, write_fixture
from build_native_restarts import build as restart
from supervisor import NO_WINDOW


RUN = r'''
return assert(loadfile('/home/program/main.lua'))(function(wait)
  local mes,wh,lg=require('mes'),require('logistics.warehouse'),require('logistics')
  local ids={}
  for i=1,2 do
    local plan=assert(mes.plan('minecraft:brick_block',8))
    for n,s in ipairs(plan.stages) do
      if s.kind=='robot' then assert(mes.choose(plan,n,'cpu'..i)) end
    end
    ids[i]=assert(mes.run(plan))
  end
  for i,id in ipairs(ids) do
    local r=assert(mes.wait(id));assert(r.status=='complete',r.reason)
    for _,s in ipairs(r.stages) do if s.kind=='robot' then assert(s.crafter=='cpu'..i) end end
  end
  assert(wh.count({name='minecraft:brick_block',damage=0})==16)
  wait(function() for _,d in ipairs(lg.drones()) do if d.state~='idle' then return end end;return true end)
  return 'Both registered robots completed their plans'
end)
'''


def build(root, case):
    if case == 'robot-reboot': return restart(root, 'robot-craft')
    if case != 'robot-register': raise ValueError('unknown registration case')
    path = build_native(Path(root) / 'fixture', 'concurrent')
    (path.parent / 'program/registration.lua').write_text(RUN)
    value = json.loads(path.read_text());value['id'] = 'robot-register'
    value['controller']['program']['entry'] = 'registration.lua'
    return write_fixture(path, value)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--jobs-root', type=Path, required=True)
    parser.add_argument('--case', choices=('robot-register', 'robot-reboot'), required=True)
    parser.add_argument('--installation', type=Path, default=Path('C:/or/drone-install-MES-E2E-finalization'))
    args = parser.parse_args()
    path = build(args.root, args.case)
    command = [sys.executable, 'runner.py', 'run', str(path), '--installation',
               str(args.installation), '--jobs-root', str(args.jobs_root)]
    with (args.root / 'native-command.log').open('w') as output:
        result = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
    print((args.root / 'native-command.log').read_text())
    sys.exit(result.returncode)
