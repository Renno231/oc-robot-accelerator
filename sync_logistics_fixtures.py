"""Copy the canonical deployment into native acceptance program trees."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent
for case in sorted((ROOT / 'examples/logistics').iterdir()):
    if not case.is_dir() or not (case / 'scenario.json').exists():
        continue
    shutil.copyfile(ROOT / 'drone-logistics/drone/loader.lua', case / 'loader.lua')
    for path in ('lib/map.lua', 'lib/logistics.lua', 'bin/logistics.lua', 'drone/agent.lua'):
        target = case / 'program' / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / 'drone-logistics' / path, target)
    agent = case / 'program/drone/agent.lua'
    if case.name == 'security':
        prefix = '-- Native adversarial fixture: wrong-token report from the registered drone card.\n' + \
                 'do local m,t,c,n,p=...;m.send(c,p,"WRONG!","report",0,"{state=\'ready\',energy=0,cargoSlots=0}") end\n'
        agent.write_bytes(prefix.encode() + agent.read_bytes())
    elif case.name == 'fixes':
        agent.write_bytes((ROOT / 'examples/logistics/fixes-hook.lua').read_bytes() + b'\n' + agent.read_bytes())
    shutil.copyfile(ROOT / 'examples/logistics/testsuite.lua', case / 'program/testsuite.lua')
