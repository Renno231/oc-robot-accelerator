"""Generate the native T4 scenario layouts; programs come from the sync script."""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
base = json.loads((ROOT / 'transfer/scenario.json').read_text())
two = json.loads((ROOT / 'split/scenario.json').read_text())

def chest(position, item=None, count=0):
    slots = []
    while count:
        n = min(count, 64)
        slots.append(dict(slot=len(slots)+1, item=item, count=n))
        count -= n
    return dict(position=position, block='minecraft:chest', slots=slots)

for name in ('steps', 'wait', 'blocked', 'blocked-held', 'furnace', 'fixes'):
    spec = copy.deepcopy(two if name in ('wait', 'fixes', 'steps') else base)
    spec['id'] = 'logistics-' + name
    spec['expect'] = {'drones': [dict(index=i, blockPosition=d['position'], running=True) for i,d in enumerate(spec['drones'])]}
    if name == 'steps':
        spec['containers'] = [chest([0,64,2], 'minecraft:iron_ingot', 620), chest([6,64,2], 'minecraft:iron_ingot', 20),
                              chest([6,64,4], 'minecraft:iron_ingot', 20), chest([6,64,6]), chest([3,64,6])]
        spec['expect']['containers'] = [dict(position=[6,64,6], slots=[dict(slot=1,item='minecraft:iron_ingot',count=20)]),
                                       dict(position=[3,64,6],slots=[dict(slot=1,count=0)]+[dict(slot=i,item='minecraft:iron_ingot',count=64) for i in range(2,11)]),
                                       dict(position=[0,64,2],slots=[dict(slot=1,item='minecraft:iron_ingot',count=64)])]
    elif name == 'wait':
        spec['containers'] = [chest([0,64,2]),chest([6,64,2]),chest([6,64,4],'minecraft:iron_ingot',64)]
        spec['expect']['containers'] = [dict(position=[6,64,2],slots=[dict(slot=1,item='minecraft:iron_ingot',count=64)])]
    elif name.startswith('blocked'):
        spec['blocks'].append(dict(position=[4,65,2],block='minecraft:stone'))
        spec['observations']['everyTicks']=1
        if name == 'blocked-held':
            spec['expect']['drones'][0]['inventory']=[dict(slot=1,item='minecraft:iron_ingot',count=64)]
        else:
            spec['expect']['containers']=[dict(position=[6,64,2],slots=[dict(slot=1,item='minecraft:iron_ingot',count=64)])]
    elif name == 'furnace':
        spec['containers']=[chest([0,64,2],'minecraft:iron_ore',1),chest([6,64,4],'minecraft:coal',2),dict(position=[6,64,2],block='minecraft:furnace',slots=[])]
        spec['blocks'] += [dict(position=[5,63,2],block='minecraft:air'),dict(position=[6,63,2],block='minecraft:air')]
    elif name == 'fixes':
        spec['containers']=[chest([0,64,2],'minecraft:iron_ingot',64),chest([6,64,2]),chest([6,64,4],'minecraft:cobblestone',64),chest([6,64,6]),chest([1,65,0])]
    case=ROOT/name
    (case/'program').mkdir(parents=True,exist_ok=True)
    (case/'scenario.json').write_text(json.dumps(spec,indent=2)+'\n')
    (case/'program/main.lua').write_text('require("testsuite")("'+name+'")\n')
