"""Minimal real microcontroller loader/transposer/card probes, before IO code."""
import argparse
import copy
import json
from pathlib import Path


def build(root, case):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    (root / 'program').mkdir()
    value = json.loads(Path('examples/drones/link/scenario.json').read_text())
    value['id'] = 'io-probe-' + case
    value['drones'] = []
    far = case == 'tier1-far'
    value['computer']['position'] = [-20 if far else -3, 65, 2]
    value['world']['region']['min'][0] = -22
    for area in value['world']['blocks']: area['min'][0] = -22
    value['blocks'] = [{'position': [-21 if far else -4, 65, 2], 'block': 'opencomputers:capacitor', 'energy': 1600},
                       {'position': [-21 if far else -4, 65, 3], 'block': 'opencomputers:capacitor', 'energy': 1600}]
    value['containers'] = [{'position': [0, 64, 0], 'block': 'minecraft:chest',
        'slots': [{'slot': 1, 'item': 'minecraft:coal', 'count': 4}]}]
    value['expect'] = {'drones': [], 'containers': copy.deepcopy(value['containers'])}
    del value['expect']['containers'][0]['block']
    tier = 2 if case == 'tier2' else 1
    value['microcontrollers'] = [{'position': [0, 65, 0], 'eeprom': 'loader.lua',
        'hardware': {'tier': tier, 'cpu': 'cpu1', 'memory': ['ram1'],
            'cards': ['wlancard' + str(tier)], 'upgrades': ['transposer']}}]
    value['execution'] = {'mode': 'coordinated', 'maxTicks': 3000, 'timeoutSeconds': 180, 'infiniteEnergy': True}
    (root / 'loader.lua').write_bytes(Path('drone-logistics/drone/loader.lua').read_bytes())
    program = '''local component=require('component');local event=require('event');local computer=require('computer')
local modem=component.modem;local port=27103;modem.open(port);modem.setStrength(64)
local address,hello,boot,seen=nil,0,0,nil
local code=[=[local m,t,c,n,p=...
local tr=assert(component.proxy(component.list('transposer')()))
local function report()
 for side=0,5 do local size=tr.getInventorySize(side)
  if size then local rows=tr.getAllStacks(side).getAll();local stack=rows[1]
   m.send(c,p,t,'probe',size,side,stack and stack.name or '',stack and stack.size or 0)
  end
 end
end
report();while true do local e={computer.pullSignal(2)};if e[1]=='modem_message' and e[7]=='status' then report() end end]=]
local started=computer.uptime()
repeat
 local e={event.pull(1,'modem_message')}
 if e[4]==port then
  if e[6]=='lgx_hello' then hello=hello+1;address=e[3];modem.send(address,port,'lgx_pair','probe1','probe')
  elseif e[6]=='probe1' and e[7]=='boot' then
   boot=boot+1;modem.send(e[3],port,'probe1','code',1,1,code);modem.send(e[3],port,'probe1','start')
  elseif e[6]=='probe1' and e[7]=='probe' then seen={size=e[8],side=e[9],item=e[10],count=e[11]} end
 end
until seen or computer.uptime()-started>20
if FAR then assert(hello==0 and boot==0 and not seen,'tier1 unexpectedly reached >16 blocks')
else assert(hello>0 and boot>0 and seen,'loader did not download probe')
 assert(seen.size==27 and seen.item=='minecraft:coal' and seen.count==4,'transposer chest mismatch') end
print('io native probe',CASE,'hello',hello,'boot',boot,'size',seen and seen.size,'count',seen and seen.count)
'''.replace('FAR', 'true' if far else 'false').replace('CASE', repr(case))
    (root / 'program/main.lua').write_text(program)
    path = root / 'scenario.json'
    path.write_text(json.dumps(value, indent=2) + '\n')
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('case', choices=('tier1', 'tier2', 'tier1-far'))
    args = parser.parse_args()
    print(build(args.root, args.case))
