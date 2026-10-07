"""Native 64-chest warehouse acceptance room, using the T7 finite-power layout."""
import copy
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]


def build():
    target = ROOT / 'examples/warehouse/room'
    program = target / 'program'
    program.mkdir(parents=True, exist_ok=True)
    value = copy.deepcopy(json.loads((ROOT / 'examples/logistics/storage-room/scenario.json').read_text()))
    value['id'] = 'warehouse-room'
    value['world']['region']['max'] = [12, 71, 11]
    value['world']['blocks'][0]['max'] = [12, 71, 11]
    value['world']['blocks'][1]['max'] = [12, 63, 11]
    # The explicit 64-face read sweep is longer than T7's sampled transfers.
    # Extend the real controller network with finite charged capacitors.
    for y in range(65, 68):
        for z in range(1, 5):
            value['blocks'].append({'position': [-6, y, z], 'block': 'opencomputers:capacitor', 'energy': 1600})
    # UI acceptance adds real fetch/return and queued-cancellation go jobs.
    # Extend only the finite native charger bank; never top up running drones.
    for z in (0,-1,-2,7,8,9):
        value['blocks'].append({'position': [-2,64,z], 'block': 'opencomputers:capacitor', 'energy': 1600})
    for chest in value['containers']:
        x, y, z = chest['position']
        # Adjacent vanilla chests can expose a combined Forge inventory. Alternate
        # normal/trapped types so each declared room inventory is a single chest.
        chest['block'] = 'minecraft:trapped_chest' if x % 2 else 'minecraft:chest'
        chest['slots'] = []
        if x == 0 and z == 1 and y in (65, 67, 68):
            chest['slots'] = [{'slot': 1, 'item': 'minecraft:iron_ingot', 'count': {65: 40, 67: 30, 68: 20}[y]}]
        if z == 1 and y == 65 and x in (1, 2, 3, 4):
            chest['slots'] = [{'slot': s, 'item': 'minecraft:stone', 'count': 64} for s in range(1, 27)]
            chest['slots'].append({'slot': 27, 'item': 'minecraft:iron_ingot', 'count': {1: 56, 2: 58, 3: 54, 4: 60}[x]})
        if x == 7 and y == 65 and z == 1:
            chest['slots'] = [{'slot': 1, 'item': 'minecraft:iron_ingot', 'count': 64}]
    value['blocks'].append({'position': [10, 64, 7], 'block': 'minecraft:furnace'})
    value['world']['blocks'].append({'min': [10, 63, 7], 'max': [10, 63, 7], 'block': 'minecraft:air'})
    value['execution']['maxTicks'] = 30000
    value['execution']['timeoutSeconds'] = 1800
    value['observations'] = {'everyTicks': 10}
    value['containerEdits'] = [{'position':[0,65,1],'slot':1,'count':24,'expectedCount':40,
                               'request':{'computer':0,'marker':'home/warehouse-remove-items',
                                          'signal':'warehouse_items_removed'}}]
    expected = {(0, 65, 1): 0, (0, 67, 1): 0, (0, 68, 1): 15,
                (1, 65, 1): 64, (2, 65, 1): 64, (3, 65, 1): 64,
                (4, 65, 1): 60, (5, 65, 1): 27, (6, 65, 1): 0,
                (7, 65, 1): 57, (7, 68, 3): 0}
    value['expect']['containers'] = [{'position': list(p), 'slots': [{'slot': 27 if p[0] in (1, 2, 3, 4) else 1,
                                       'item': 'minecraft:iron_ingot', 'count': n}]} for p, n in expected.items()]
    (target / 'scenario.json').write_text(json.dumps(value, indent=2) + '\n')
    for path in ('lib/map.lua', 'lib/logistics.lua', 'lib/warehouse.lua', 'drone/agent.lua', 'bin/warehouse.lua'):
        destination = program / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / 'drone-logistics' / path, destination)
    shutil.copyfile(ROOT / 'drone-logistics/drone/loader.lua', target / 'loader.lua')
    shutil.copyfile(ROOT / 'examples/warehouse/room.lua', program / 'main.lua')
    for path in ('lib/warehouse/view.lua', 'lib/warehouse/ui.lua'):
        destination=program/path;destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/'drone-logistics'/path,destination)
    shutil.copyfile(ROOT/'fixtures/qmenu.lua',program/'lib/qmenu.lua')
    for name in ('ui-tests.lua','warehouse-before.lua'):
        shutil.copyfile(ROOT/'examples/warehouse'/name,program/name)
    build_slots()
    build_nbt()
    # Keep the machine-cycle fixtures generated from this finite-power room.
    import importlib.util
    spec=importlib.util.spec_from_file_location('build_furnace_cycle',ROOT/'examples/warehouse/build_furnace_cycle.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.build()


def build_slots():
    target = ROOT / 'examples/warehouse/slots'
    program = target / 'program'
    program.mkdir(parents=True, exist_ok=True)
    value = copy.deepcopy(json.loads((ROOT / 'examples/logistics/transfer/scenario.json').read_text()))
    value['id'] = 'warehouse-slots'
    for x, y, z in [(-5,65,2),(-5,65,3),(-5,66,2),(-5,66,3),(0,64,1),(0,64,-1),(-1,64,0)]:
        value['blocks'].append({'position':[x,y,z],'block':'opencomputers:capacitor','energy':1600})
    value['containers'] = [
        {'position': [0, 64, 2], 'block': 'minecraft:chest', 'slots': [
            {'slot': 1, 'item': 'minecraft:iron_ingot', 'count': 16},
            {'slot': 2, 'item': 'minecraft:iron_ingot', 'count': 48},
            {'slot': 3, 'item': 'minecraft:ender_pearl', 'count': 16}]},
        {'position': [6, 64, 2], 'block': 'minecraft:chest', 'slots': [
            *[{'slot': s, 'item': 'minecraft:stone', 'count': 64} for s in range(1, 27)],
            {'slot': 27, 'item': 'minecraft:ender_pearl', 'count': 14}]},
        {'position': [6, 64, 6], 'block': 'minecraft:chest', 'slots': []}]
    value['expect']['containers'] = [
        {'position': [0, 64, 2], 'slots': [{'slot': 1, 'item': 'minecraft:iron_ingot', 'count': 63},
                                          {'slot': 2, 'count': 0}, {'slot': 3, 'item': 'minecraft:ender_pearl', 'count': 14}]},
        {'position': [6, 64, 2], 'slots': [{'slot': 27, 'item': 'minecraft:ender_pearl', 'count': 16}]},
        {'position': [6, 64, 6], 'slots': [{'slot': 1, 'item': 'minecraft:iron_ingot', 'count': 1}]}]
    (target / 'scenario.json').write_text(json.dumps(value, indent=2) + '\n')
    for path in ('lib/map.lua', 'lib/logistics.lua', 'lib/warehouse.lua', 'drone/agent.lua', 'bin/warehouse.lua'):
        destination = program / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / 'drone-logistics' / path, destination)
    shutil.copyfile(ROOT / 'drone-logistics/drone/loader.lua', target / 'loader.lua')
    shutil.copyfile(ROOT / 'examples/warehouse/slots.lua', program / 'main.lua')


def build_nbt():
    target=ROOT/'examples/warehouse/nbt'
    program=target/'program';program.mkdir(parents=True,exist_ok=True)
    value=copy.deepcopy(json.loads((ROOT/'examples/logistics/transfer/scenario.json').read_text()))
    value['id']='warehouse-nbt'
    value['containers'][0]['slots']=[{'slot':i,'item':'minecraft:iron_ingot','count':16,'nbt':'{variant:'+str(i)+'}'} for i in range(1,6)]
    value['containers'][1]['slots']=[]
    value['expect']['containers']=[
        {'position':[0,64,2],'slots':[{'slot':i,'count':0} for i in range(1,6)]},
        {'position':[6,64,2],'slots':[{'slot':i,'item':'minecraft:iron_ingot','count':16} for i in range(1,6)]}]
    (target/'scenario.json').write_text(json.dumps(value,indent=2)+'\n')
    for path in ('lib/map.lua','lib/logistics.lua','lib/warehouse.lua','drone/agent.lua','bin/warehouse.lua'):
        destination=program/path;destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/'drone-logistics'/path,destination)
    shutil.copyfile(ROOT/'drone-logistics/drone/loader.lua',target/'loader.lua')
    shutil.copyfile(ROOT/'examples/warehouse/nbt.lua',program/'main.lua')


if __name__ == '__main__':
    build()
