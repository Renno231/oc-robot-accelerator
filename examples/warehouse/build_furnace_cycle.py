"""Generated native furnace cycle; canonical APIs are copied, never patched."""
import copy
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]


def build(target=None, seed=128, shortfall=False, ram=1):
    target = Path(target or ROOT / 'examples/warehouse/furnace-cycle')
    program = target / 'program'
    program.mkdir(parents=True, exist_ok=True)
    value = copy.deepcopy(json.loads((ROOT / 'examples/warehouse/room/scenario.json').read_text()))
    value['id'] = 'warehouse-furnace-cycle'
    value['computer']['hardware']['memory'] = ['ram6'] * ram
    value['blocks'] = [b for b in value['blocks'] if b['block'] != 'minecraft:furnace']
    value['world']['blocks'].append({'min': [9,63,7], 'max': [10,63,9], 'block':'minecraft:air'})
    for chest in value['containers']:
        p = tuple(chest['position'])
        chest['slots'] = []
        if p in ((0,65,1), (7,68,3), (3,67,1)):
            n = {(0,65,1):50, (7,68,3):50, (3,67,1):seed-100}[p]
            if n:
                chest['slots'] = [{'slot':1,'item':'minecraft:clay_ball','count':n}]
        if p == (2,66,3):
            chest['slots'] = [{'slot':1,'item':'minecraft:coal','count':20}]
        if p == (6,65,1):
            chest['slots'] = [{'slot':s,'item':'minecraft:stone','count':64} for s in range(1,27)]
        if p == (4,68,1):
            chest['slots'] = [{'slot':1,'item':'minecraft:iron_ingot','count':17}]
    for z in (7,9):
        value['blocks'].append({'position':[10,64,z],'block':'minecraft:furnace'})
    # Finite connected capacitor bank for the controller's 640-second sleep.
    for y in range(68,71):
        for z in range(-1,6):
            value['blocks'].append({'position':[-6,y,z],'block':'opencomputers:capacitor','energy':1600})
    # Additional finite charger supply for two scans plus a 640-second smelt.
    for z in (0,1,3,4,6,7):
        value['blocks'].append({'position':[-3,64,z],'block':'opencomputers:capacitor','energy':1600})
    value['execution'] = {'mode':'coordinated','maxTicks':36000,'timeoutSeconds':2100}
    value['observations'] = {'everyTicks':10}
    value['containerEdits'] = ([{'position':[7,68,3],'slot':1,'count':20,'expectedCount':50,
                               'request':{'computer':0,'marker':'home/warehouse-remove-items',
                                          'signal':'warehouse_items_removed'}}] if shortfall else [])
    total = seed - (20 if shortfall else 0)
    value['expect']['containers'] = [
        {'position':[6,65,1],'slots':[{'slot':27,'item':'minecraft:brick','count':64}]},
        {'position':[5,65,1],'slots':[{'slot':1,'item':'minecraft:brick','count':total-64}]},
        {'position':[2,66,3],'slots':[{'slot':1,'item':'minecraft:coal','count':4}]}]
    for p in ((0,65,1),(7,68,3),(3,67,1)):
        value['expect']['containers'].append({'position':list(p),'slots':[{'slot':1,'count':0}]})
    (target/'scenario.json').write_text(json.dumps(value,indent=2)+'\n')
    for path in ('usr/lib/logistics/map.lua','usr/lib/logistics/init.lua','usr/lib/logistics/warehouse.lua','usr/lib/cbor.lua','usr/lib/logistics/store.lua','usr/lib/logistics/warehouse/view.lua','usr/lib/logistics/warehouse/ui.lua','usr/lib/logistics/drone/agent.lua'):
        dest=program/path;dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/'drone-logistics'/path,dest)
    shutil.copyfile(ROOT/'fixtures/qmenu.lua',program/'lib/qmenu.lua')
    shutil.copyfile(ROOT/'drone-logistics/drone/loader.lua',target/'loader.lua')
    shutil.copyfile(ROOT/'examples/warehouse/furnace-cycle.lua',program/'main.lua')
    shutil.copyfile(ROOT/'examples/warehouse/deployment-memory.lua',program/'deployment-memory.lua')
    (program/'cycle-config.lua').write_text('return {seed='+str(seed)+',shortfall='+str(shortfall).lower()+'}\n')
    (program/'route-metrics-enabled').write_text('native per-tick positions and energy\n')
    return target/'scenario.json'


if __name__ == '__main__':
    build()
