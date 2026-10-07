"""T11 acceptance worlds. Canonical Lua is copied verbatim; no UI is booted."""
import copy
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
CASES = ('torches16', 'bricks16', 'specific-group', 'shortfall', 'concurrent-fetch')
SOURCE = ROOT / 'examples/mes'


def build(target=None, case='torches16', mode='coordinated'):
    if case not in CASES:
        raise ValueError('unknown MES case')
    if mode not in ('coordinated', 'baseline'):
        raise ValueError('unknown execution mode')
    target = Path(target or SOURCE / case)
    program = target / 'program'
    program.mkdir(parents=True, exist_ok=True)
    value = copy.deepcopy(json.loads((ROOT / 'examples/warehouse/room/scenario.json').read_text()))
    value['id'] = 'mes-' + case
    value['computer']['hardware']['memory'] = ['ram6', 'ram6']
    value['blocks'] = [b for b in value['blocks'] if b['block'] != 'minecraft:furnace']
    value['world']['blocks'].append({'min': [9, 63, 7], 'max': [10, 63, 9], 'block': 'minecraft:air'})
    for z in (7, 9):
        value['blocks'].append({'position': [10, 64, z], 'block': 'minecraft:furnace'})
    torch = case == 'torches16'
    probe = case == 'concurrent-fetch'
    for chest in value['containers']:
        chest['slots'] = []
        if chest['position'] == [0, 65, 1]:
            chest['slots'] = ([{'slot': 1, 'item': 'minecraft:log', 'count': 8}] if torch else
                              [{'slot': 1, 'item': 'minecraft:clay_ball', 'count': 64}])
        if probe and chest['position'] == [1, 65, 1]:
            chest['slots'] = [{'slot': 1, 'item': 'minecraft:clay_ball', 'count': 64}]
        if chest['position'] == [2, 66, 3]:
            chest['slots'] = [{'slot': 1, 'item': 'minecraft:coal', 'count': 16}]
    value['containers'].append({'position': [8, 65, 1], 'block': 'minecraft:chest', 'slots': []})
    for z in (7, 9):
        value['containers'].append({'position': [10, 64, z], 'block': 'minecraft:furnace', 'slots': []})
    hardware = copy.deepcopy(value['computer']['hardware'])
    hardware.update(containers=[], upgrades=['craftingupgrade', 'inventorycontrollerupgrade', 'inventoryupgrade'])
    value['robots'] = [{'position': [8, 65, 0], 'facing': 'south', 'hardware': hardware,
                        'program': {'directory': 'robot-program', 'entry': 'main.lua'},
                        'inventory': [], 'energy': 20000}]
    value['execution'] = {'mode': mode, 'maxTicks': 72000, 'timeoutSeconds': 3600, 'infiniteEnergy': True}
    value['observations'] = {'everyTicks': 10}
    value['containerEdits'] = ([{'position': [0, 65, 1], 'slot': 1, 'count': 16, 'expectedCount': 64,
                                'request': {'computer': 0, 'marker': 'home/warehouse-remove-items',
                                            'signal': 'warehouse_items_removed'}}] if case == 'shortfall' else [])
    expected = [{'position': [8, 65, 1], 'slots': [{'slot': n, 'count': 0} for n in range(1, 28)]}]
    if torch:
        expected += [{'position': [0, 65, 1], 'slots': [{'slot': 1, 'item': 'minecraft:log', 'count': 3}]},
                     {'position': [3, 65, 1], 'slots': [{'slot': 1, 'item': 'minecraft:planks', 'count': 2}]},
                     {'position': [5, 65, 1], 'slots': [{'slot': 1, 'item': 'minecraft:torch', 'count': 16}]},
                     {'position': [2, 66, 3], 'slots': [{'slot': 1, 'item': 'minecraft:coal', 'count': 14}]}]
    elif case in ('bricks16', 'specific-group'):
        expected += [{'position': [0, 65, 1], 'slots': [{'slot': 1, 'count': 0}]},
                     {'position': [5, 65, 1], 'slots': [{'slot': 1, 'item': 'minecraft:brick_block', 'count': 16}]},
                     {'position': [2, 66, 3], 'slots': [{'slot': 1, 'item': 'minecraft:coal', 'count': 8}]}]
    if case in ('torches16', 'bricks16', 'specific-group'):
        expected += [{'position': [10, 64, z], 'slots': [{'slot': 1, 'count': 0}, {'slot': 3, 'count': 0}]} for z in (7, 9)]
    value['expect'] = {'containers': expected,
                       'robots': [{'index': 0, 'inventory': [{'slot': n, 'count': 0} for n in range(1, 17)]}],
                       'drones': [{'index': i, 'inventory': [{'slot': n, 'count': 0} for n in range(1, 5)]} for i in range(2)]}
    (target / 'scenario.json').write_text(json.dumps(value, indent=2) + '\n')
    for relative in ('lib/map.lua', 'lib/logistics.lua', 'lib/warehouse.lua', 'drone/agent.lua'):
        dest = program / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / 'drone-logistics' / relative, dest)
    shutil.copyfile(ROOT / 'drone-logistics/drone/loader.lua', target / 'loader.lua')
    for dest in (program, target / 'robot-program'):
        # Headless deployment excludes coordinator-owned UI additions. Remove
        # stale copies as well so regeneration never retains an earlier UI.
        shutil.rmtree(dest / 'usr', ignore_errors=True)
        shutil.copytree(ROOT / 'craftsystem/usr', dest / 'usr',
                        ignore=shutil.ignore_patterns('mes_ui', 'mesui.lua'))
        shutil.copyfile(SOURCE / 'install.lua', dest / 'install.lua')
    for name in ('main.lua', 'setup.lua', 'recipes.tsv'):
        shutil.copyfile(SOURCE / name, program / name)
    shutil.copyfile(SOURCE / 'robot.lua', target / 'robot-program/main.lua')
    (program / 'case.lua').write_text("return {name='" + case + "'}\n")
    (program / 'route-metrics-enabled').write_text('native per-tick route metrics\n')
    return target / 'scenario.json'


if __name__ == '__main__':
    for name in CASES:
        build(case=name)
