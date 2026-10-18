"""Current-source MES acceptance worlds: real registration and rc services."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'examples/mes'
ALL_CASES = ('torches16', 'bricks16', 'specific-group', 'shortfall', 'concurrent-fetch', 'ocparts', 'ocparts-repeat', 'robot-parts', 'robot-expand', 'concurrent', 'merged-kit', 'stockkeeper', 'selected-kit', 'order-control')
ROBOT_LIBRARIES = ('api', 'tnet', 'hosts', 'pubsub', 'craft_executor', 'craft_receipts',
                   'craft_plan', 'craft_resources', 'craft_tool_budget', 'craft_tool_rules',
                   'item_identity', 'robinv')
OCPARTS_QTY = 64
OCPARTS_BATCH = 16
OCPARTS_STOCK = {'minecraft:iron_ingot': 128, 'minecraft:gold_ingot': 32,
                 'minecraft:redstone': 64, 'minecraft:clay': 16,
                 'minecraft:dye:2': 16, 'minecraft:paper': 16, 'minecraft:coal': 32}
OCPARTS_FINAL = {'minecraft:iron_ingot': 104, 'minecraft:gold_ingot': 23,
                 'minecraft:redstone': 30, 'minecraft:clay': 8,
                 'minecraft:dye:2': 8, 'minecraft:paper': 14, 'minecraft:coal': 24,
                 'minecraft:iron_nugget': 2, 'minecraft:gold_nugget': 5,
                 'opencomputers:material:6': 0, 'opencomputers:component:6': OCPARTS_QTY,
                 'opencomputers:material:2': 0, 'opencomputers:material:4': 0,
                 'opencomputers:material:7': 0}
OCPARTS_REPEAT_FINAL = {'minecraft:iron_ingot': 122, 'minecraft:gold_ingot': 30,
                       'minecraft:redstone': 59, 'minecraft:clay': 15,
                       'minecraft:dye:2': 15, 'minecraft:paper': 15, 'minecraft:coal': 28,
                       'minecraft:iron_nugget': 7, 'minecraft:gold_nugget': 7,
                       'opencomputers:material:6': 6, 'opencomputers:component:6': 8}

# The existing 85-slot robot: 31/32 assembler complexity, three built-in
# inventory upgrades plus three removable ones. Blank disks still need installation.
ROBOT_PARTS = {'opencomputers:case3': 1, 'opencomputers:component:2': 1,
               'opencomputers:component:11': 2, 'opencomputers:storage:4': 1,
               'opencomputers:card:7': 1, 'opencomputers:upgrade:11': 1,
               'opencomputers:upgrade:18': 1, 'opencomputers:upgrade:17': 6,
               'opencomputers:upgrade:10': 1, 'opencomputers:upgrade:9': 2,
               'opencomputers:storage': 1, 'opencomputers:charger': 1,
               'minecraft:chest': 1}  # Buffer last: earlier recipes consume chests.
ROBOT_PARTS_STOCK = dict(OCPARTS_STOCK, **{'minecraft:diamond': 32, 'minecraft:log': 64,
                                        'minecraft:cobblestone': 128, 'minecraft:ender_pearl': 1})
ROBOT_PARTS_FINAL = dict(ROBOT_PARTS, **{
    'minecraft:iron_ingot': 43, 'minecraft:gold_ingot': 12, 'minecraft:redstone': 15,
    'minecraft:clay': 14, 'minecraft:dye:2': 14, 'minecraft:paper': 9, 'minecraft:coal': 19,
    'minecraft:diamond': 19, 'minecraft:log': 12, 'minecraft:cobblestone': 35,
    'minecraft:planks': 3, 'minecraft:iron_nugget': 7, 'minecraft:gold_nugget': 6,
    'minecraft:iron_bars': 14, 'opencomputers:material:29': 2, 'opencomputers:material:6': 3,
    'opencomputers:material:9': 1, 'opencomputers:material:2': 2,
    'opencomputers:material:7': 6, 'opencomputers:material:8': 2})
ROBOT_EXPAND_FINAL = {
    'opencomputers:component:11': 2, 'minecraft:chest': 2, 'minecraft:iron_ingot': 40,
    'minecraft:gold_ingot': 11, 'minecraft:redstone': 6, 'minecraft:clay': 14,
    'minecraft:dye:2': 14, 'minecraft:paper': 8, 'minecraft:coal': 17,
    'minecraft:diamond': 16, 'minecraft:log': 7, 'minecraft:cobblestone': 35,
    'minecraft:planks': 3, 'minecraft:iron_nugget': 4, 'minecraft:gold_nugget': 7,
    'minecraft:iron_bars': 14, 'opencomputers:material:29': 2, 'opencomputers:material:6': 7,
    'opencomputers:material:9': 1, 'opencomputers:material:7': 6,
    'opencomputers:material:8': 2, 'minecraft:stick': 2}

# User database rows plus the native OC recipe imports below.
OCPARTS_RECIPES = """minecraft:iron_nugget\t{qty=9,[1]='minecraft:iron_ingot'}
minecraft:gold_nugget\t{qty=9,[1]='minecraft:gold_ingot'}
opencomputers:material:2\t{qty=8,[1]='minecraft:gold_ingot',[2]='minecraft:clay_ball',[3]='minecraft:dye:2'}
opencomputers:material:6\t{qty=8,[1]='minecraft:iron_ingot',[2]='minecraft:iron_ingot',[3]='minecraft:iron_ingot',[4]='minecraft:gold_nugget',[5]='minecraft:paper',[6]='minecraft:gold_nugget',[8]='minecraft:redstone'}
opencomputers:material:7\t{qty=8,[1]='minecraft:iron_nugget',[2]='minecraft:iron_nugget',[3]='minecraft:iron_nugget',[4]='minecraft:redstone',[5]='opencomputers:material:6',[6]='minecraft:redstone',[7]='minecraft:iron_nugget',[8]='minecraft:iron_nugget',[9]='minecraft:iron_nugget'}
opencomputers:component:6\t{qty=1,[1]='opencomputers:material:7',[2]='minecraft:iron_nugget',[3]='opencomputers:material:7',[5]='opencomputers:material:4'}
"""
OCPARTS_IMPORTS = r"""
local recipes=require('recipes')
-- Native OC consumes clay blocks; the user's modded ore cache resolves clay
-- to clay balls. Import the native recipe without changing the user's row.
local rawSlots={[1]={name='minecraft:gold_ingot',size=1},
                [2]={name='minecraft:clay',size=1},
                [3]={name='minecraft:dye',damage=2,size=1},
                [14]={name='opencomputers:material',damage=2,size=8}}
assert(recipes.save(assert(recipes.recipeFromSlots('crafting',rawSlots,27))))
-- Processing recipes are absent from the crafting database.
local slots={[1]={name='opencomputers:material',damage=2,size=1},
             [24]={name='opencomputers:material',damage=4,size=1}}
assert(recipes.save(assert(recipes.recipeFromSlots('processing',slots,27,'furnace'))))
"""


def split_item(identity):
    parts = identity.rsplit(':', 1)
    return (parts[0], int(parts[1])) if parts[1].isdigit() else (identity, 0)


def rack_controller(position, program):
    return {'kind': 'rack', 'position': list(position), 'program': copy.deepcopy(program),
            'hardware': {'tier': 3, 'cpu': 'cpu3', 'memory': ['ram6'] * 4,
                         'buses': ['componentbus3'] * 3,
                         'cards': ['graphicscard3', 'datacard3', 'wlancard2', 'internetcard'],
                         'storage': ['hdd3'] * 4, 'bootDrive': 0}}


def build_native(target, case, mode='coordinated', seconds=10):
    if case not in ALL_CASES or mode not in ('coordinated', 'baseline'):
        raise ValueError('unknown MES case or execution mode')
    scenario_case = case
    if case in ('merged-kit', 'selected-kit'): case = 'concurrent'  # Same build and stock, ordered through a saved kit.
    if case == 'order-control': case = 'concurrent'  # Same build; stop one order while another owns its selected robot.
    if case == 'stockkeeper': case = 'bricks16'  # Same build, replenished in two saved batches.
    parts = case in ('robot-parts', 'robot-expand')
    ocparts = case in ('ocparts', 'ocparts-repeat') or parts
    target = Path(target)
    target.mkdir(parents=True)  # Never overwrite an existing run's evidence.
    value = copy.deepcopy(json.loads((ROOT / 'examples/warehouse/room/scenario.json').read_text()))
    value['id'] = 'mes-' + scenario_case
    controller = value.pop('computer')
    value['controller'] = rack_controller(controller['position'], controller['program'])
    x, y, z = controller['position']
    value['blocks'] = [b for b in value['blocks'] if b['block'] != 'minecraft:furnace'
                       and b['position'] not in ([x-1,y,z], [x-1,y+1,z])]
    value['world']['blocks'].append({'min': [9, 63, 7], 'max': [10, 63, 9], 'block': 'minecraft:air'})
    for z in (7, 9):
        value['blocks'].append({'position': [10, 64, z], 'block': 'minecraft:furnace'})
    for chest in value['containers']:
        chest['slots'] = []
        if chest['position'] == [0, 65, 1]:
            chest['slots'] = [{'slot': 1, 'item': 'minecraft:log' if case == 'torches16' else 'minecraft:clay_ball',
                               'count': 8 if case == 'torches16' else 64}]
        if chest['position'] == [1, 65, 1] and case in ('concurrent-fetch', 'concurrent'):
            chest['slots'] = [{'slot': 1, 'item': 'minecraft:clay_ball' if case == 'concurrent-fetch' else 'minecraft:log',
                               'count': 64 if case == 'concurrent-fetch' else 8}]
        if chest['position'] == [2, 66, 3]:
            chest['slots'] = [{'slot': 1, 'item': 'minecraft:coal', 'count': 16}]
    value['containers'].append({'position': [8, 65, 1], 'block': 'minecraft:chest', 'slots': []})
    for z in (7, 9):
        value['containers'].append({'position': [10, 64, z], 'block': 'minecraft:furnace', 'slots': []})
    hardware = copy.deepcopy(controller['hardware'])
    hardware.update(memory=['ram6', 'ram6'],
                    containers=[{'item': name, 'component': 'inventoryupgrade'} for name in
                                ('upgradecontainer3', 'upgradecontainer2', 'upgradecontainer2')],
                    upgrades=['craftingupgrade', 'inventorycontrollerupgrade'] + ['inventoryupgrade'] * 3)
    value['robots'] = [{'position': [8, 65, 0], 'facing': 'south', 'hardware': hardware,
                        'program': {'directory': 'robot-program', 'entry': 'main.lua'},
                        'inventory': [], 'energy': 20000}]
    for z in (3, 4, 6, 7):
        drone = copy.deepcopy(value['drones'][0]);drone['position'] = [-2, 65, z]
        value['drones'].append(drone)
        value['blocks'] = [b for b in value['blocks'] if b['position'] != [-2, 64, z]]
        value['blocks'].append({'position': [-2, 64, z], 'block': 'opencomputers:charger',
                                'properties': {'facing': 'north'}})
    value['execution'] = {'mode': mode, 'maxTicks': 72000, 'timeoutSeconds': 3600, 'infiniteEnergy': True}
    value['observations'] = {'everyTicks': 10}
    value['containerEdits'] = ([{'position': [0, 65, 1], 'slot': 1, 'count': 16, 'expectedCount': 64,
                                'request': {'computer': 0, 'marker': 'home/warehouse-remove-items',
                                            'signal': 'warehouse_items_removed'}}] if case == 'shortfall' else [])
    if case == 'shortfall':
        # Outside warehouse membership until a normal transfer replenishes stock.
        reserve = next(c for c in value['containers'] if c['position'] == [7, 68, 3])
        reserve['slots'] = [{'slot': 1, 'item': 'minecraft:clay_ball', 'count': 16}]
    expected = [{'position': [8, 65, 1], 'slots': [{'slot': n, 'count': 0} for n in range(1, 28)]}]
    if case == 'torches16':
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
    if ocparts or case == 'concurrent':
        if ocparts:
            for chest in value['containers']: chest['slots'] = []
            for identity, qty in (ROBOT_PARTS_STOCK if parts else OCPARTS_STOCK).items():
                name, damage = split_item(identity)
                for stack in range((qty + 63) // 64):
                    chest = value['containers'][stack]
                    chest['slots'].append({'slot': len(chest['slots']) + 1, 'item': name,
                                          'metadata': damage, 'count': min(64, qty - stack * 64)})
        value['containers'].append({'position': [10, 65, 1], 'block': 'minecraft:chest', 'slots': []})
        for i, x in enumerate((8, 10)):
            value['blocks'].append({'position': [x, 64, 0], 'block': 'opencomputers:charger',
                                    'properties': {'facing': 'north'}})
            if i:
                robot = copy.deepcopy(value['robots'][0]);robot['position'] = [x, 65, 0]
                robot['program']['directory'] = 'robot-program-2';value['robots'].append(robot)
        expected = [{'position': [x, 65, 1], 'slots': [{'slot': n, 'count': 0} for n in range(1, 28)]}
                    for x in (8, 10)] + [{'position': [10, 64, z], 'slots': [{'slot': n, 'count': 0} for n in range(1, 4)]}
                                         for z in (7, 9)]
    if case == 'robot-expand':
        value['containers'].append({'position': [11, 65, 3], 'block': 'minecraft:chest', 'slots': []})
        value['world']['blocks'].append({'min': [12, 64, 0], 'max': [12, 65, 1], 'block': 'minecraft:air'})
        robot = copy.deepcopy(value['robots'][0]);robot['position'] = [12, 65, 0]
        robot['program']['directory'] = 'robot-program-3'
        robot['assembly'] = {'source': [11, 65, 3],
            'blocks': [{'position': [12, 64, 0], 'block': 'opencomputers:charger', 'properties': {'facing': 'north'}},
                       {'position': [12, 65, 1], 'block': 'minecraft:chest'}],
            'request': {'computer': 0, 'marker': 'home/assemble-robot', 'signal': 'robot_assembled'}}
        value['robots'].append(robot)
        expected += [{'position': p, 'slots': [{'slot': n, 'count': 0} for n in range(1, 28)]}
                     for p in ([11, 65, 3], [12, 65, 1])]
    value['expect'] = {'containers': expected,
        'robots': [{'index': i, 'inventory': [{'slot': n, 'count': 0} for n in range(1, 86)]} for i in range(len(value['robots']))],
        'drones': [{'index': i, 'inventory': [{'slot': n, 'count': 0} for n in range(1, 5)]} for i in range(6)]}

    program = target / 'program'
    shutil.copytree(ROOT / 'craftsystem/usr', program / 'usr',
                    ignore=shutil.ignore_patterns('mes_ui', 'mesui.lua'))
    for disk in [program] + [target / r['program']['directory'] for r in value['robots']]:
        if disk != program:
            (disk / 'usr/bin').mkdir(parents=True)
            (disk / 'usr/lib').mkdir()
            shutil.copyfile(ROOT / 'craftsystem/usr/bin/cproc.lua', disk / 'usr/bin/cproc.lua')
            for name in ROBOT_LIBRARIES:
                shutil.copyfile(ROOT / 'craftsystem/usr/lib' / (name + '.lua'), disk / 'usr/lib' / (name + '.lua'))
        shutil.copyfile(SOURCE / 'install.lua', disk / 'install.lua')
    shutil.copytree(ROOT / 'craftsystem/etc', program / 'etc')
    for folder in ('lib', 'bin'):
        shutil.copytree(ROOT / 'drone-logistics' / folder, program / 'usr' / folder, dirs_exist_ok=True)
    (program / 'usr/lib/logistics').mkdir()
    for name in ('agent', 'sensor', 'survey'):
        shutil.copyfile(ROOT / 'drone-logistics/drone' / (name + '.lua'), program / 'usr/lib/logistics' / (name + '.lua'))
    shutil.copyfile(ROOT / 'drone-logistics/drone/loader.lua', target / 'loader.lua')
    shutil.copyfile(SOURCE / 'native.lua', program / 'main.lua')
    setup = (SOURCE / 'setup.lua').read_text()
    if ocparts or case == 'concurrent':
        setup = setup.replace("wh.group('cpu1','crafter',{buffer='cpu1.buf'})",
                              "wh.group('cpu1','crafter',{buffer='cpu1.buf'})\nmap.name('cpu2.buf','10:65:2',2)\nwh.group('cpu2','crafter',{buffer='cpu2.buf'})")
    if ocparts: setup = setup.split('-- Dedicated destinations')[0] + '\nreturn {homes=homes}\n'
    (program / 'setup.lua').write_text(setup)
    recipes = OCPARTS_RECIPES if ocparts else (SOURCE / 'recipes.tsv').read_text()
    if parts: recipes += (SOURCE / 'robot-parts.tsv').read_text()
    (program / 'recipes.tsv').write_text(recipes)
    (program / 'ocparts-imports.lua').write_text(OCPARTS_IMPORTS)
    orders = '{' + ','.join("{'%s',%d}" % order for order in ROBOT_PARTS.items()) + '}' if parts else 'nil'
    (program / 'case.lua').write_text("return {name='%s',robots=%d,batch=%d,quantity=%d,seconds=%s,orders=%s}\n" % (
        scenario_case, 2 if case == 'robot-expand' else len(value['robots']), 1 if case == 'torches16' else OCPARTS_BATCH if ocparts else 64,
        5 if case == 'ocparts-repeat' else OCPARTS_QTY if ocparts else 16, 'nil' if seconds is None else seconds, orders))
    for robot in value['robots']:
        disk = target / robot['program']['directory']
        shutil.copyfile(SOURCE / 'robot.lua', disk / 'main.lua')
        (disk / 'etc/rc.d').mkdir(parents=True)
        shutil.copyfile(ROOT / 'craftsystem/etc/rc.d/cproc.lua', disk / 'etc/rc.d/cproc.lua')
        (disk / 'etc/rc.cfg').write_text('enabled = {"cproc"}\ncproc = "--side=3"\n')
    return write_fixture(target / 'scenario.json', value)


def write_fixture(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')
    hashes = {p.relative_to(path.parent).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in path.parent.rglob('*') if p.is_file() and p != path.parent / 'source-hashes.json'}
    (path.parent / 'source-hashes.json').write_text(json.dumps(hashes, indent=2) + '\n')
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--case', choices=ALL_CASES, required=True)
    args = parser.parse_args()
    print(build_native(args.root, args.case))
