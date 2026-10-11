"""T11 acceptance worlds. Canonical Lua is copied verbatim; no UI is booted."""
import copy
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
CASES = ('torches16', 'bricks16', 'specific-group', 'shortfall', 'concurrent-fetch')
ALL_CASES = CASES + ('ocparts', 'concurrent')
SOURCE = ROOT / 'examples/mes'
OCPARTS_QTY = 64
OCPARTS_BATCH = OCPARTS_QTY // 4  # Two loads in each of two furnaces.
OCPARTS_DRONES = 6

# User DB rows resolved through the user's ore cache. Its clay alias differs
# from pure Forge/OC; import the authentic native variant through recipes.save.
# PCB smelting is absent from the crafting DB and is imported through recipes.
OCPARTS_RECIPES = """minecraft:iron_nugget\t{qty=9,[1]='minecraft:iron_ingot'}
minecraft:gold_nugget\t{qty=9,[1]='minecraft:gold_ingot'}
opencomputers:material:2\t{qty=8,[1]='minecraft:gold_ingot',[2]='minecraft:clay_ball',[3]='minecraft:dye:2'}
opencomputers:material:6\t{qty=8,[1]='minecraft:iron_ingot',[2]='minecraft:iron_ingot',[3]='minecraft:iron_ingot',[4]='minecraft:gold_nugget',[5]='minecraft:paper',[6]='minecraft:gold_nugget',[8]='minecraft:redstone'}
opencomputers:material:7\t{qty=8,[1]='minecraft:iron_nugget',[2]='minecraft:iron_nugget',[3]='minecraft:iron_nugget',[4]='minecraft:redstone',[5]='opencomputers:material:6',[6]='minecraft:redstone',[7]='minecraft:iron_nugget',[8]='minecraft:iron_nugget',[9]='minecraft:iron_nugget'}
opencomputers:component:6\t{qty=1,[1]='opencomputers:material:7',[2]='minecraft:iron_nugget',[3]='opencomputers:material:7',[5]='opencomputers:material:4'}
"""
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

# Share actual API imports with the real-compiler headless conservation tests.
OCPARTS_IMPORTS = r"""
local recipes=require('recipes')
-- In the native Forge+OC game no ore entry named clay exists. OC's default
-- parser resolves its literal clay ingredient to minecraft:clay (the block).
-- The user's modded ore cache maps it to clay_ball instead; retain that DB row
-- and import the authentic default.recipes variant as a crafting overlay.
local rawSlots={[1]={name='minecraft:gold_ingot',size=1},
                [2]={name='minecraft:clay',size=1},
                [3]={name='minecraft:dye',damage=2,size=1},
                [14]={name='opencomputers:material',damage=2,size=8}}
local rawDraft=assert(recipes.recipeFromSlots('crafting',rawSlots,27))
assert(recipes.save(rawDraft))
-- The user's crafting DB has no smelting registry. Import the real OC recipe.
local slots={[1]={name='opencomputers:material',damage=2,size=1},
             [24]={name='opencomputers:material',damage=4,size=1}}
local draft=assert(recipes.recipeFromSlots('processing',slots,27,'furnace'))
assert(recipes.save(draft))
"""


def build(target=None, case='torches16', mode='coordinated', ocparts_drones=OCPARTS_DRONES):
    if case not in ALL_CASES:
        raise ValueError('unknown MES case')
    if mode not in ('coordinated', 'baseline'):
        raise ValueError('unknown execution mode')
    if ocparts_drones not in (2, OCPARTS_DRONES):
        raise ValueError('ocparts drone count must be 2 (diagnostic) or 6')
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
        if case == 'concurrent' and chest['position'] == [1, 65, 1]:
            chest['slots'] = [{'slot': 1, 'item': 'minecraft:log', 'count': 8}]
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
    drone_count = ocparts_drones if case == 'ocparts' else OCPARTS_DRONES
    if drone_count == OCPARTS_DRONES:
        for z in (3, 4, 6, 7):
            drone = copy.deepcopy(value['drones'][0]);drone['position'] = [-2, 65, z]
            value['drones'].append(drone)
            value['blocks'] = [b for b in value['blocks'] if b['position'] != [-2, 64, z]]
            value['blocks'].append({'position': [-2, 64, z], 'block': 'opencomputers:charger',
                                    'properties': {'facing': 'north'}})
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
                       'drones': [{'index': i, 'inventory': [{'slot': n, 'count': 0} for n in range(1, 5)]} for i in range(drone_count)]}
    if case in ('ocparts', 'concurrent'):
        # Original robinv reserves slots 1..12. Two genuine inventory upgrades
        # provide 32 physical slots for simultaneous ingredients and outputs.
        value['robots'][0]['hardware']['upgrades'].append('inventoryupgrade')
        value['expect']['drones'] = [
            {'index': i, 'inventory': [{'slot': n, 'count': 0} for n in range(1, 5)]}
            for i in range(ocparts_drones)]
        if case == 'ocparts':
            for chest in value['containers']:
                chest['slots'] = []
        stock = [c for c in value['containers'] if c['block'] in ('minecraft:chest', 'minecraft:trapped_chest')][:64]
        # Organized mixed stock: one stack of each raw material in a nearby
        # chest, with overflow in the adjacent chest. All 64 members remain.
        # This models normal shared storage; it changes no stock quantities.
        for identity, qty in (OCPARTS_STOCK.items() if case == 'ocparts' else []):
            name, damage = split_item(identity)
            for stack in range((qty + 63) // 64):
                chest = stock[stack]
                chest['slots'].append({'slot': len(chest['slots']) + 1, 'item': name,
                                       'metadata': damage, 'count': min(64, qty - stack * 64)})
        value['containers'].append({'position': [10, 65, 1], 'block': 'minecraft:chest', 'slots': []})
        for i, x in enumerate((8, 10)):
            value['blocks'].append({'position': [x, 64, 0], 'block': 'opencomputers:charger',
                                    'properties': {'facing': 'north'}})
            if i:
                robot = copy.deepcopy(value['robots'][0])
                robot['position'] = [x, 65, 0]
                robot['program']['directory'] = 'robot-program-2'
                value['robots'].append(robot)
        # Fuel must be consumed too: each group smelts half the requested PCBs.
        value['expect']['containers'] = [
            {'position': [x, 65, 1], 'slots': [{'slot': n, 'count': 0} for n in range(1, 28)]}
            for x in (8, 10)] + [
            {'position': [10, 64, z], 'slots': [{'slot': n, 'count': 0} for n in range(1, 4)]}
            for z in (7, 9)]
        value['expect']['robots'] = [
            {'index': i, 'inventory': [{'slot': n, 'count': 0} for n in range(1, 33)]} for i in range(2)]
    (target / 'scenario.json').write_text(json.dumps(value, indent=2) + '\n')
    for relative in ('lib/map.lua', 'lib/logistics.lua', 'lib/warehouse.lua', 'lib/stations.lua', 'lib/iochest.lua', 'lib/stats.lua', 'lib/cbor.lua', 'lib/store.lua', 'drone/agent.lua', 'drone/sensor.lua'):
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
    shutil.copytree(ROOT / 'craftsystem/etc', program / 'etc', dirs_exist_ok=True)
    for name in ('main.lua', 'setup.lua', 'recipes.tsv'):
        shutil.copyfile(SOURCE / name, program / name)
    shutil.copyfile(SOURCE / 'robot.lua', target / 'robot-program/main.lua')
    (program / 'case.lua').write_text("return {name='" + case + "'}\n")
    (program / 'route-metrics-enabled').write_text('native per-tick route metrics\n')
    if case == 'ocparts':
        build_ocparts_program(target, ocparts_drones)
    elif case == 'concurrent':
        build_ocparts_program(target)
        setup = (SOURCE / 'setup.lua').read_text().replace(
            "wh.group('cpu1','crafter',{buffer='cpu1.buf'})",
            "wh.group('cpu1','crafter',{buffer='cpu1.buf'})\nmap.name('cpu2.buf','10:65:2',2)\nwh.group('cpu2','crafter',{buffer='cpu2.buf'})")
        (program / 'setup.lua').write_text(setup)
        shutil.copyfile(SOURCE / 'recipes.tsv', program / 'recipes.tsv')
        main = (program / 'main.lua').read_text().split('local result={case=case')[0]
        main = main.replace(f'batch={OCPARTS_BATCH}', 'batch=64')
        (program / 'main.lua').write_text(main + CONCURRENT_RUN)
        (program / 'recipe-provenance.json').unlink()
    entry = program / 'main.lua'
    newline = '\r\n' if b'\r\n' in entry.read_bytes() else '\n'
    main = entry.read_text()
    entry.write_text(main.replace('result.droneBusy=busy', TRIP_KINDS + '\n  result.droneBusy=busy'), newline=newline)
    return target / 'scenario.json'


def split_item(identity):
    parts = identity.rsplit(':', 1)
    return (parts[0], int(parts[1])) if parts[1].isdigit() else (identity, 0)


def build_ocparts_program(target, drone_count=OCPARTS_DRONES):
    program = target / 'program'
    setup = (SOURCE / 'setup.lua').read_text().split('-- Dedicated destinations')[0]
    setup = setup.replace("wh.group('cpu1','crafter',{buffer='cpu1.buf'})",
                          "wh.group('cpu1','crafter',{buffer='cpu1.buf'})\n"
                          "map.name('cpu2.buf','10:65:2',2)\n"
                          "wh.group('cpu2','crafter',{buffer='cpu2.buf'})")
    if drone_count == 2:
        setup = setup.replace('for z=2,7 do', 'for _,z in ipairs({2,5}) do')
    (program / 'setup.lua').write_text(setup + '\nreturn {homes=' +
                                      ('homes' if drone_count == OCPARTS_DRONES else '{H,H2}') + '}\n')
    (program / 'recipes.tsv').write_text(OCPARTS_RECIPES)
    main = (SOURCE / 'main.lua').read_text().split('local result={case=case')[0]
    main = main.replace('local address,distances', 'local address,distances;local addresses={}')
    main = main.replace('    address=robot', '    addresses[cpu]=robot;address=robot')
    main = main.replace('return address~=nil', "return addresses.cpu1~=nil and addresses.cpu2~=nil")
    main = main.replace('crafters={cpu1={robot=address}}',
                        'crafters={cpu1={robot=addresses.cpu1},cpu2={robot=addresses.cpu2}}')
    main = main.replace('#lg.pending()==6', f'#lg.pending()=={drone_count}')
    main = main.replace('if #ds~=6', f'if #ds~={drone_count}')
    main = main.replace("batch=(case=='torches16' and 1 or 64)", f'batch={OCPARTS_BATCH}')
    expected = '{' + ','.join("['" + k + "']=" + str(v) for k, v in OCPARTS_FINAL.items()) + '}'
    main += OCPARTS_RUN.replace('__EXPECTED__', expected)
    (program / 'main.lua').write_text(main)
    robot_source = (SOURCE / 'robot.lua').read_text()
    for i, directory in enumerate(('robot-program', 'robot-program-2'), 1):
        dest = target / directory
        if i == 2:
            shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(target / 'robot-program', dest)
        (dest / 'main.lua').write_text(robot_source.replace(
            "local fixtureName='cpu1'", "local fixtureName='cpu" + str(i) + "'"))
    provenance = {'crafting': 'OC-Utilities/recipe_db/raw/{minecraft,opencomputers}.db',
                  'processing': 'OpenComputers-1.8.9a.jar/assets/opencomputers/recipes/default.recipes:printedcircuitboard',
                  'processingImport': 'recipes.recipeFromSlots + recipes.save',
                  'craftingImport': 'recipes.recipeFromSlots + recipes.save (authentic native rawcircuitboard)',
                  'oreResolution': 'vanilla ingots/nuggets, native clay block, dye:2, paper; OC metadata from Items.scala',
                  'nativeClayCorrection': {'userOreCache': 'ore:clay -> minecraft:clay_ball',
                    'nativeIngredient': 'minecraft:clay',
                    'reason': 'Pure Forge has no clay ore entry; OC Recipes.parseIngredient resolves literal clay via the item registry',
                    'source': 'OpenComputers-1.8.9a default.recipes:rawcircuitboard; Recipes.scala:414-425'},
                  'sourceSHA256': {
                      'opencomputers.db': '7287a567abacc89a39131c4e32beb7638506eaad5d55c96d376c0f7bb95b00e9',
                      'minecraft.db': '86f5aa18199d29036b600e567d6d9ec31626a3578873b34d9047271964d3edd7',
                      'default.recipes': '83e92db8906351e470d13907bab0516febfdba6abf9de6f7abe3970cdc64302a'},
                  'selectedRecipesSHA256': hashlib.sha256(OCPARTS_RECIPES.encode()).hexdigest()}
    (program / 'recipe-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')


OCPARTS_RUN = r"""
local result={case=case,robots=addresses,status='running'}
local function saveProgress()
  -- Full physical ledgers already have their own durable files. Avoid
  -- serializing a second copy of them on the T3 controller just for progress.
  local summary={}
  for _,key in ipairs({'case','status','submitterExit','componentCalls','mesTripWindow',
    'mesTrips','harnessTrips','trips','droneBusy','robotIntervals','robotOverlap','tripKinds'}) do
    summary[key]=result[key]
  end
  save('/home/mes-progress.lua',summary)
end
local source=assert(io.open('/home/program/recipes.tsv','r'));local text=source:read('*a');source:close()
for _,namespace in ipairs({'minecraft','opencomputers'}) do
  local lines={};for line in text:gmatch('[^\n]+') do
    if line:sub(1,#namespace+1)==namespace..':' then lines[#lines+1]=line end
  end
  local archive=assert(require('liblz16').open('/usr/lib/recipes/'..namespace..'.dblz','wb'))
  assert(archive:write(table.concat(lines,'\n')..'\n'));archive:close()
end
local builder=require('recipes.build');local db=builder.build();assert(builder.save(db));require('recipes').install(db)
""" + OCPARTS_IMPORTS + r"""
local plan,why=mes.plan('opencomputers:component:6',__QTY__);assert(plan,why)
assert(#plan.missing==0,'raw stock unexpectedly short')
save('/home/mes.plan',plan)
result.mesTripWindow={first=latestJobId()+1}
-- A separate foreground command submits, writes its ID, and exits immediately.
-- The installed MES service must keep advancing after that process is closed.
local submit=assert(io.open('/home/mes-submit.lua','w'))
assert(submit:write([[
local mes=require('mes')
local counter=package.loaded.runner_component_calls
local before=counter and counter.snapshot()
local id=assert(mes.run('/home/mes.plan',{pollSeconds=0.2}))
if counter then counter.submittedBefore=before end
assert(mes.status(id).status=='running','submit did not return mid-run')
local file=assert(io.open('/home/mes-submitted-id','w'));assert(file:write(tostring(id)))
if file.flush then assert(file:flush()) end
local closed,err=file:close();assert(closed~=false and not err,err)
return 0
]]))
if submit.flush then assert(submit:flush()) end
local closed,err=submit:close();assert(closed~=false and not err,err)
assert(require('shell').execute('/home/mes-submit.lua'),'submitter command failed')
local submitted=assert(io.open('/home/mes-submitted-id','r'))
local runId=assert(tonumber(submitted:read('*a')));submitted:close();result.runId=runId
result.submitterExit={returned=true,statusAtReturn=mes.status(runId).status}
assert(result.submitterExit.statusAtReturn=='running','submitter did not exit mid-run')
local componentBefore=componentCounter and componentCounter.submittedBefore
local outcome=assert(mes.wait(runId));finishComponentCalls(result,componentBefore)
result.mesTripWindow.last=latestJobId();save('/home/mes-execution.lua',outcome)
finishTripAccounting(result);result.timing=mesTiming(outcome);save('/home/mes-fetch-timings.lua',result.timing)
result.status=outcome.status;result.stages=outcome.stages
saveProgress()
assert(outcome.status=='complete',outcome.reason or outcome.error)
local overlap=false;local used={};result.robotIntervals={}
for i,a in ipairs(outcome.stages) do
  if a.kind=='robot' then
    assert(a.receipt and a.receipt.status=='complete','verified robot receipt missing')
    assert(a.craftStarted and a.craftFinished and a.craftFinished>=a.craftStarted,'robot call interval missing')
    used[a.crafter]=true
    result.robotIntervals[#result.robotIntervals+1]={stage=i,crafter=a.crafter,started=a.craftStarted,finished=a.craftFinished}
    for _,b in ipairs(outcome.stages) do
      if b.kind=='robot' and a.crafter~=b.crafter and b.craftStarted and b.craftFinished then
        if math.max(a.craftStarted,b.craftStarted)<math.min(a.craftFinished,b.craftFinished) then overlap=true end
      end
    end
  end
end
result.robotOverlap=overlap
saveProgress()
-- Genuine overlap remains measured. The approved T13 gate requires answered
-- jobs on both connected CPUs; concurrent request overlap is the T14 gate.
assert(used.cpu1 and used.cpu2,'both robots did not execute answered jobs')
assert(#result.robotIntervals>=4,'fewer than four answered robot jobs')
result.loads={};result.topups={}
for _,stage in ipairs(outcome.stages) do if stage.kind=='machine' then
  for _,move in ipairs(stage.itemsMoved or {}) do
    if move.kind=='fetch' and move.item=='opencomputers:material:2' then
      result.loads[move.storage]=(result.loads[move.storage] or 0)+(move.moved or 0)
    end
  end
  for _,group in ipairs({'furnaceA','furnaceB'}) do
    local rows={};for _,load in ipairs(stage.loadLedger or {}) do
      if load.group==group then rows[#rows+1]=load end
    end
    assert(#rows==2 and rows[1].items==__BATCH__ and rows[2].items==__BATCH__,'PCB load ledger missing')
    assert(rows[2].delivered<rows[1].collected,'PCB load did not top up while smelting')
    result.topups[group]=rows
  end
end end
assert(result.loads['furnA.in']==__GROUP__ and result.loads['furnB.in']==__GROUP__,'PCB furnace groups did not split evenly')
scan();local expected=__EXPECTED__;result.afterScan={}
for id,n in pairs(expected) do result.afterScan[id]=count(id);assert(count(id)==n,'stock mismatch: '..id) end
-- No unlisted manufactured items are permitted, not merely target equality.
for _,s in pairs(wh.totals()) do
  local id=s.item.name;if (s.item.damage or 0)~=0 then id=id..':'..s.item.damage end
  assert(expected[id]~=nil and expected[id]==s.count,'unexpected final stock: '..id)
end
result.buffers={};for _,cpu in ipairs({'cpu1','cpu2'}) do
  result.buffers[cpu]=read(cpu..'.buf');assert(not next(result.buffers[cpu]),'buffer not empty')
end
result.furnaces={};for _,n in ipairs({'A','B'}) do
  local input=read('furn'..n..'.in');local output=read('furn'..n..'.out');local fuel=read('furn'..n..'.fuel')
  assert(not next(input) and not next(output) and not next(fuel),'furnace inventory not empty')
  result.furnaces[n]={input=input,output=output,fuel=fuel}
end
wait(function() for _,d in ipairs(lg.drones()) do if d.state~='idle' then return false end end;return true end,60)
for _,d in ipairs(lg.drones()) do assert(not d.cargo or d.cargo==0 or (type(d.cargo)=='table' and not next(d.cargo)),'drone cargo remains') end
-- Full execution and timing receipts are already saved separately. Retain
-- compact result summaries instead of duplicating all ledgers in one string.
result.jobs={};for id,job in pairs(jobs) do
  result.jobs[id]={state=job.state,trips=job.trips,moved=job.moved,requested=job.requested,shortfalls=job.shortfalls}
end
result.stages={};for i,stage in ipairs(outcome.stages) do
  result.stages[i]={kind=stage.kind,state=stage.state,crafter=stage.crafter,done=stage.done,total=stage.total,
    assigned=stage.assigned,released=stage.released,craftStarted=stage.craftStarted,craftFinished=stage.craftFinished}
end
result.executionLedger='/home/mes-execution.lua';result.timingFile='/home/mes-fetch-timings.lua';result.timing=nil
result.trips=totals.trips;result.itemsMoved=totals.moved;result.gameSeconds=computer.uptime()-start
finishTripAccounting(result)
outcome=nil
save('/home/warehouse-results.lua',result);save('/home/mes-results.lua',result)
print('MES verified',case,result.status,result.gameSeconds,result.trips)
"""
OCPARTS_RUN = (OCPARTS_RUN.replace('__QTY__', str(OCPARTS_QTY))
               .replace('__BATCH__', str(OCPARTS_BATCH))
               .replace('__GROUP__', str(OCPARTS_QTY // 2)))

TRIP_KINDS = r"""
  local kinds={movement=0,shortCollect=0,first=0,input=0,output=0,shorts={},refusals={},jobs={}}
  local collect={};for _,r in ipairs(mes.runs()) do for _,s in ipairs(mes.status(r.id).stages) do
    for _,p in ipairs(s.physicalJobs or {}) do if p.kind=='collect' then collect[p.job]=true end end
  end end
  local roles,fed={},{};local map=require('map')
  local function key(e) return e.node..':'..e.side end
  for name,g in pairs(wh.groups()) do for role,storage in pairs(g.roles) do
    roles[key(assert(map.storage(storage))) ]={role=role,group=name}
  end end
  if window then for id=window.first,window.last do
    local j=assert(jobs[id]);local kind,group='input'
    for _,s in ipairs(j.steps or {}) do
      if s.take or s.put then kind='movement';local e=s.put or s.take;local r=roles[key(e)]
        if r then group=r.group;if r.role=='buffer' then fed[key(e)]=s.put~=nil end end
      elseif s.roleKey then kind='first'
      elseif s.read then local r=roles[key(s.read)]
        if r and r.role=='output' then kind='output'
        elseif r and r.role=='buffer' then kind=fed[key(s.read)] and 'output' or 'first' end
      end
    end
    if collect[id] then
      local need,moved,short=0,0,false
      for _,r in ipairs(j.perItem or {}) do need=need+r.requested;moved=moved+r.moved;short=short or r.moved<r.requested end
      if short then kind='shortCollect';kinds.shorts[#kinds.shorts+1]={job=id,trips=j.trips,requested=need,moved=moved,items=j.perItem} end
    end
    kinds[kind]=kinds[kind]+(j.trips or 0)
    kinds.jobs[#kinds.jobs+1]={id=id,kind=kind,trips=j.trips,queuedAt=j.queuedAt,tripTimings=j.tripTimings,collectItems=collect[id] and j.perItem or nil}
    if (j.refused or 0)>0 then kinds.refusals[#kinds.refusals+1]={job=id,group=group,refused=j.refused,items=j.perItem,finishedAt=j.finishedAt} end
  end end
  kinds.following={}
  if window then for id,j in pairs(jobs) do if id>window.last then for _,t in ipairs(j.tripTimings or {}) do
    local p=kinds.following[t.drone]
    if not p or t.startedAt<p.startedAt then kinds.following[t.drone]={job=id,trip=t.trip,startedAt=t.startedAt,queuedAt=j.queuedAt} end
  end end end end
  assert(kinds.movement+kinds.shortCollect+kinds.first+kinds.input+kinds.output==mesTrips,'trip kind accounting mismatch')
  result.tripKinds=kinds
"""

CONCURRENT_RUN = r"""
local result={case=case,status='running',runs={},robotIntervals={},furnaceLoads={}}
local f=assert(io.open('/home/program/recipes.tsv'));local text=f:read('*a');f:close()
local archive=assert(require('liblz16').open('/usr/lib/recipes/minecraft.dblz','wb'));assert(archive:write(text));archive:close()
local builder=require('recipes.build');local db=builder.build();assert(builder.save(db));require('recipes').install(db)
local recipes=require('recipes')
assert(recipes.registerProcessingRecipe('minecraft:coal:1','furnace',{recipe={'minecraft:log'},qty=1}))
assert(recipes.registerProcessingRecipe('minecraft:brick','furnace',{recipe={'minecraft:clay_ball'},qty=1}))
local a=assert(mes.plan('minecraft:torch',16));local b=assert(mes.plan('minecraft:brick_block',16))
local names={};event.listen('mes',function(_,kind,id)
  if kind=='done' then save('/home/concurrent-done'..assert(names[id]),{id=id,at=computer.uptime()}) end
end)
result.mesTripWindow={first=latestJobId()+1}
save('/home/concurrent-submit1',{at=computer.uptime()})
local first=assert(mes.run(a));names[first]=1
save('/home/concurrent-submit2',{at=computer.uptime()})
local second=assert(mes.run(b));names[second]=2
assert(first~=second and mes.status(first).status=='running' and mes.status(second).status=='running','submissions did not coexist')
for i,id in ipairs({first,second}) do
  local r=assert(mes.wait(id));save('/home/mes-execution-'..i..'.lua',r)
  result.runs[i]={id=id,item=r.item,status=r.status,reason=r.reason,started=r.started,finished=r.finished,gameSeconds=r.finished-r.started,mesTrips=r.trips}
  for _,s in ipairs(r.stages) do
    if s.kind=='robot' and s.craftStarted then
      result.robotIntervals[#result.robotIntervals+1]={run=id,crafter=s.crafter,started=s.craftStarted,finished=s.craftFinished}
    end
    for _,load in ipairs(s.loadLedger or {}) do
      local g=load.group;result.furnaceLoads[g]=result.furnaceLoads[g] or {};result.furnaceLoads[g][#result.furnaceLoads[g]+1]=load
    end
  end
end
result.mesTripWindow.last=latestJobId();finishTripAccounting(result)
result.combinedGameSeconds=math.max(result.runs[1].finished,result.runs[2].finished)-result.runs[1].started
result.robotOverlapSeconds=0;result.sameRobotOverlap=false
for i,a in ipairs(result.robotIntervals) do
  assert(a.finished and a.finished>=a.started,'missing craft interval')
  for j=i+1,#result.robotIntervals do local b=result.robotIntervals[j]
    local overlap=math.max(0,math.min(a.finished,b.finished)-math.max(a.started,b.started))
    if a.crafter==b.crafter and overlap>0 then result.sameRobotOverlap=true end
    if a.run~=b.run and a.crafter~=b.crafter then result.robotOverlapSeconds=result.robotOverlapSeconds+overlap end
  end
end
result.status='complete';save('/home/mes-progress.lua',result)
for _,r in ipairs(result.runs) do assert(r.status=='complete',r.reason or r.status) end
assert(not result.sameRobotOverlap,'one robot ran overlapping jobs')
scan();result.afterScan={torch=count('minecraft:torch'),brick_block=count('minecraft:brick_block')}
assert(result.afterScan.torch==16 and result.afterScan.brick_block==16,'final outputs missing')
wait(function() for _,d in ipairs(lg.drones()) do if d.state~='idle' then return false end end;return true end,60)
finishTripAccounting(result);save('/home/warehouse-results.lua',result);save('/home/mes-results.lua',result)
print('MES verified',case,result.status)
"""


if __name__ == '__main__':
    for name in ALL_CASES:
        build(case=name)
