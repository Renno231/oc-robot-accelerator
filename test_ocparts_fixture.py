"""T13 OC acceptance fixture: Python-only structure and real planner arithmetic."""
import json
from pathlib import Path
import tempfile
import unittest

from lupa.lua53 import LuaRuntime
import runner_scenario
from test_mes_fixtures import generator, module, ROOT


class OcpartsFixtureTests(unittest.TestCase):
    def test_progress_summary_does_not_duplicate_physical_ledgers(self):
        body = generator.OCPARTS_RUN.split('local function saveProgress()', 1)[1].split('\nend\n', 1)[0]
        lua = LuaRuntime()
        lua.execute('''
          local result={status='complete',submitterExit={returned=true,statusAtReturn='running'},
            stages={huge=string.rep('x',100000)},timing={huge=string.rep('y',100000)},
            mesTrips=38,robotOverlap=false}
          local function save(path,data)
            assert(path=='/home/mes-progress.lua')
            assert(data.stages==nil and data.timing==nil)
            assert(data.status=='complete' and data.mesTrips==38 and data.robotOverlap==false)
            assert(data.submitterExit.statusAtReturn=='running')
          end
        ''' + 'local function saveProgress()' + body + '\nend\nsaveProgress()')

    def test_overlap_requires_distinct_actual_robot_call_intervals(self):
        proof = generator.OCPARTS_RUN.split('local overlap=false;')[1].split('result.loads=')[0]
        lua = LuaRuntime()
        lua.execute('saveProgress=function() end')
        def stages(start, finish, crafter='cpu2'):
            lua.execute(f'''result={{}};outcome={{stages={{
              {{kind='robot',receipt={{status='complete'}},crafter='cpu1',craftStarted=2,craftFinished=5}},
              {{kind='robot',receipt={{status='complete'}},crafter='{crafter}',craftStarted={start},craftFinished={finish}}},
              {{kind='robot',receipt={{status='complete'}},crafter='cpu1',craftStarted=10,craftFinished=12}},
              {{kind='robot',receipt={{status='complete'}},crafter='cpu1',craftStarted=14,craftFinished=16}}
            }}}}''')
        stages(3, 6)
        lua.execute('local overlap=false;' + proof)
        self.assertTrue(lua.globals().result['robotOverlap'])
        lua.execute('table.remove(outcome.stages)')
        with self.assertRaises(Exception):
            lua.execute('local overlap=false;' + proof)
        for start, finish in ((5, 8), (6, 8)):
            stages(start, finish)
            lua.execute('local overlap=false;' + proof)
            self.assertFalse(lua.globals().result['robotOverlap'])
        for start, finish, crafter in ((3, 6, 'cpu1'),):
            stages(start, finish, crafter)
            with self.assertRaises(Exception):
                lua.execute('local overlap=false;' + proof)

    def test_topup_requires_unsettled_prior_output(self):
        proof = generator.OCPARTS_RUN.split("  for _,group in ipairs({'furnaceA','furnaceB'}) do")[1].split('end end')[0]
        proof = "for _,group in ipairs({'furnaceA','furnaceB'}) do" + proof
        lua = LuaRuntime()
        def loads(delivered, collected):
            lua.execute(f'''result={{topups={{}}}};stage={{loadLedger={{
              {{group='furnaceA',items={generator.OCPARTS_BATCH},delivered=1,collected={collected}}},
              {{group='furnaceA',items={generator.OCPARTS_BATCH},delivered={delivered},collected=20}},
              {{group='furnaceB',items={generator.OCPARTS_BATCH},delivered=1,collected={collected}}},
              {{group='furnaceB',items={generator.OCPARTS_BATCH},delivered={delivered},collected=20}}
            }}}}''')
        loads(5, 10)
        lua.execute(proof)
        for delivered, collected in ((10, 10), (11, 10)):
            loads(delivered, collected)
            with self.assertRaises(Exception):
                lua.execute(proof)

    def test_world_resources_and_empty_oracles(self):
        with tempfile.TemporaryDirectory() as tmp:
            scenario = generator.build(tmp, 'ocparts')
            value = runner_scenario.load(scenario).normalized
            self.assertEqual(generator.OCPARTS_DRONES, len(value['drones']))
            self.assertEqual(68, len(value['containers']))
            self.assertEqual(64, sum(c['block'] in ('minecraft:chest', 'minecraft:trapped_chest') for c in value['containers']) - 2)
            self.assertEqual(2, len(value['robots']))
            self.assertEqual(generator.OCPARTS_DRONES, len(value['drones']))
            self.assertTrue(value['execution']['infiniteEnergy'])
            stock = [c for c in value['containers']
                     if c['block'] in ('minecraft:chest', 'minecraft:trapped_chest')][:64]
            totals = {}
            for chest in stock:
                identities = set()
                for entry in chest['slots']:
                    identity = entry['item']
                    if entry.get('metadata', 0):
                        identity += ':' + str(entry['metadata'])
                    self.assertNotIn(identity, identities, 'one stack per item per source')
                    identities.add(identity)
                    totals[identity] = totals.get(identity, 0) + entry['count']
            self.assertEqual(generator.OCPARTS_STOCK, totals)
            self.assertGreater(len(stock[0]['slots']), 1, 'organized mixed stock')
            for robot in value['robots']:
                x, y, z = robot['position']
                self.assertTrue(any(b['position'] == [x, y-1, z] and b['block'] == 'opencomputers:charger'
                                    for b in value['blocks']))
                self.assertTrue(any(c['position'] == [x, y, z+1] for c in value['containers']))
            self.assertEqual(2, len(value['expect']['robots']))
            for expectation in value['expect']['robots']:
                self.assertEqual(32, len(expectation['inventory']))
                self.assertTrue(all(s['count'] == 0 for s in expectation['inventory']))
            for robot in value['robots']:
                self.assertEqual(2, robot['hardware']['upgrades'].count('inventoryupgrade'))
            for c in value['expect']['containers']:
                self.assertTrue(all(s['count'] == 0 for s in c['slots']))
            self.assertEqual(2, sum(c['slots'] == [{'slot': n, 'count': 0} for n in range(1, 4)]
                                    for c in value['expect']['containers']))

    def test_program_contract_and_lua_syntax(self):
        lua = LuaRuntime()
        compile_lua = lua.eval('function(s) local f,e=load(s);assert(f,e);return true end')
        with tempfile.TemporaryDirectory() as tmp:
            generator.build(tmp, 'ocparts')
            root = Path(tmp)
            for p in (root/'program/main.lua', root/'program/setup.lua',
                      root/'robot-program/main.lua', root/'robot-program-2/main.lua'):
                self.assertTrue(compile_lua(p.read_text()), str(p))
            main = (root/'program/main.lua').read_text()
            for text in ('mes.plan(', 'mes.run(', 'mes.wait(runId)', 'recipes.recipeFromSlots(',
                         'recipes.save(draft)', 'a.craftStarted', 'b.craftFinished',
                         'used.cpu1 and used.cpu2', 'wh.totals()',
                         "'/home/warehouse-results.lua'", 'result.trips=totals.trips'):
                self.assertIn(text, main)
            self.assertNotIn("{crafter='cpu1'", main)
            self.assertIn(f'batch={generator.OCPARTS_BATCH}', main)
            self.assertNotIn('verifyTopups', main)
            self.assertNotIn('collectgarbage(', main, 'OC sandbox has no public collectgarbage')
            self.assertIn("roles={'input','fuel','output'},roleSlots={input={1},fuel={1},output={1}}", main)
            self.assertIn("mes.wait(runId));finishComponentCalls(result,componentBefore)", main)
            self.assertIn("result.mesTripWindow.last=latestJobId();save('/home/mes-execution.lua',outcome)", main)
            self.assertIn("require('shell').execute('/home/mes-submit.lua')", main)
            self.assertIn("result.submitterExit.statusAtReturn=='running'", main)
            self.assertIn("mes.status(id).status=='running'", main)
            self.assertIn('finishTripAccounting(result)', main)
            self.assertIn("assert(rows[2].delivered<rows[1].collected,'PCB", main)
            self.assertNotIn('inputBefore', main)
            self.assertIn("wh.group('cpu2','crafter'", (root/'program/setup.lua').read_text())
            for i, directory in enumerate(('robot-program', 'robot-program-2'), 1):
                self.assertIn("'cpu" + str(i) + "'", (root/directory/'main.lua').read_text())
                for src in (ROOT/'craftsystem/usr').rglob('*'):
                    if src.is_file() and 'mes_ui' not in src.parts and src.name != 'mesui.lua':
                        self.assertEqual(src.read_bytes(), (root/directory/'usr'/src.relative_to(ROOT/'craftsystem/usr')).read_bytes())
            provenance = json.loads((root/'program/recipe-provenance.json').read_text())
            self.assertIn('OpenComputers-1.8.9a.jar', provenance['processing'])
            self.assertEqual('recipes.recipeFromSlots + recipes.save', provenance['processingImport'])
            self.assertEqual('minecraft:clay', provenance['nativeClayCorrection']['nativeIngredient'])
            self.assertIn('clay_ball', provenance['nativeClayCorrection']['userOreCache'])
            self.assertIn('recipes.save(rawDraft)', main)
            self.assertNotIn('mes.saveRecipe', main)

    def test_real_compiler_planner_consumption_and_leftovers(self):
        support = module('ocparts_database_support', ROOT/'craftsystem/tests/test_database.py')
        lua = LuaRuntime(unpack_returned_tuples=True)
        lib = (ROOT/'craftsystem/usr/lib').as_posix()
        lua.execute(f'package.path="{lib}/?.lua;{lib}/?/init.lua;"..package.path')
        lua.execute(support.MOCKS)
        lua.globals().SOURCE_TEXT = generator.OCPARTS_RECIPES
        stacks = lua.table()
        for i, (identity, qty) in enumerate(generator.OCPARTS_STOCK.items(), 1):
            name, damage = generator.split_item(identity)
            stacks[i] = lua.table_from(dict(name=name, damage=damage, size=qty, maxSize=64))
        lua.globals().STOCK = stacks
        lua.globals().REQUEST_QTY = generator.OCPARTS_QTY
        lua.execute('''
          local fs=require('filesystem')
          fs.rename=function(a,b) if not files[a] then return nil,'missing source' end
            files[b]=files[a];files[a]=nil;return true end
          fs.remove=function(p) files[p]=nil;return true end
          package.preload.event=function() return {push=function() end} end
          listing['/usr/lib/recipes']={'minecraft.dblz','opencomputers.dblz'}
          for _,namespace in ipairs({'minecraft','opencomputers'}) do
            local lines={};for line in SOURCE_TEXT:gmatch('[^\\n]+') do
              if line:sub(1,#namespace+1)==namespace..':' then lines[#lines+1]=line end
            end
            files['/usr/lib/recipes/'..namespace..'.dblz']=table.concat(lines,'\\n')..'\\n'
          end
          local builder=require('recipes.build');local built=builder.build();assert(builder.save(built))
          local db=require('recipes');db.install(built)
        ''')
        lua.execute(generator.OCPARTS_IMPORTS)
        lua.execute('''
          package.preload.oredict=function() return {get=function() end,getByItemName=function() end} end
          package.preload.craft_tools=function() return {list=function() return {} end} end
          local planner=require('craftingv4_4')
          PLAN=planner.calculateCraftingPlan('opencomputers:component:6',REQUEST_QTY,
            {getAllStacks=function() return {getAll=function() return STOCK end} end},0,true)
          for i=1,100 do if not PLAN.yield_data then break end;planner.resumeCalculation(PLAN) end
          assert(not PLAN.yield_data and PLAN.craftable,PLAN.error)
        ''')
        plan = lua.globals().PLAN
        needed = dict(plan['inventory_needed'].items())
        for identity, consumed in {'minecraft:iron_ingot': 24, 'minecraft:gold_ingot': 9,
                                   'minecraft:redstone': 34, 'minecraft:paper': 2,
                                   'minecraft:clay': 8, 'minecraft:dye:2': 8}.items():
            self.assertEqual(consumed, needed[identity], identity)
        tasks = {t['item']: t for _, t in plan['tasks'].items()}
        board = plan['blueprint']['nodes'][tasks['opencomputers:material:2']['node']]
        transistor = plan['blueprint']['nodes'][tasks['opencomputers:material:6']['node']]
        self.assertNotIn('opencomputers:material:6', set(board['recipe'].values()))
        self.assertNotIn('opencomputers:material:2', set(transistor['recipe'].values()))
        self.assertEqual(generator.OCPARTS_QTY, tasks['opencomputers:component:6']['qty_produced'])
        self.assertEqual(64, tasks['opencomputers:material:2']['qty_produced'])
        self.assertEqual(64, tasks['opencomputers:material:4']['qty_produced'])
        self.assertEqual(16, tasks['opencomputers:material:6']['qty_produced'])
        self.assertEqual(128, tasks['opencomputers:material:7']['qty_produced'])
        # Replay every task's captured blueprint inputs and outputs as a stock
        # conservation oracle. Fuel is a MES load policy, not a planner ingredient.
        remaining = dict(generator.OCPARTS_STOCK)
        for _, task in plan['tasks'].items():
            node = plan['blueprint']['nodes'][task['node']]
            for slot, qty in node['input_quantities'].items():
                identity = node['recipe'][slot]
                remaining[identity] = remaining.get(identity, 0) - qty * task['repetitions']
            identity = task['item']
            remaining[identity] = remaining.get(identity, 0) + task['qty_produced']
        remaining['minecraft:coal'] -= generator.OCPARTS_QTY // 8
        self.assertEqual(generator.OCPARTS_FINAL, remaining)

    def test_existing_native_program_uses_async_contract_without_losing_oracles(self):
        main = (ROOT/'examples/mes/main.lua').read_text()
        self.assertIn('mes.wait(runId)', main)
        self.assertIn("mes.wait(runId));finishComponentCalls(result,componentBefore)", main)
        saved = "result.mesTripWindow.last=latestJobId();save('/home/mes-execution.lua',outcome)"
        self.assertIn(saved, main)
        self.assertLess(main.index('mes.wait(runId)'), main.index(saved))
        self.assertLess(main.index(saved), main.index("if case=='shortfall' then\n    assert(outcome.status=='failed')"))
        self.assertIn("assert(rows[2].delivered<rows[1].collected,'torch", main)
        self.assertNotIn("assert(rows[2].inputBefore>0", main)
        self.assertIn("event.listen('mes',function(_,kind,runId,index,state)", main)
        self.assertIn('blocking=false', main)
        self.assertIn("roles={'input','fuel','output'},roleSlots={input={1},fuel={1},output={1}}", main)
        self.assertIn("batch=(case=='torches16' and 1 or 64)", main)
        for oracle in ('conservation.total==48', "loads['furnA.in']==64", "count('minecraft:log')==3",
                       "count('minecraft:coal')==14", "count('minecraft:coal')==8",
                       "count('minecraft:brick_block')==16", "count('minecraft:torch')==16"):
            self.assertIn(oracle, main)


if __name__ == '__main__':
    unittest.main()
