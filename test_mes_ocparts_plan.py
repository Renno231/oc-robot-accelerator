"""Real recipe compiler/planner to MES graph integration; no native substitute."""
import unittest

from lupa.lua53 import LuaRuntime
from examples.mes import build_fixtures as generator
from craftsystem.tests.test_database import MOCKS

ROOT = generator.ROOT


class OcpartsMesPlanTests(unittest.TestCase):
    def setUp(self, recipes=generator.OCPARTS_RECIPES, stock_items=generator.OCPARTS_STOCK):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        lib = (ROOT / 'craftsystem/usr/lib').as_posix()
        self.lua.execute(f'package.path="{lib}/?.lua;{lib}/?/init.lua;"..package.path')
        self.lua.execute(MOCKS)
        self.lua.globals().SOURCE_TEXT = recipes
        self.lua.globals().REQUEST_QTY = generator.OCPARTS_QTY
        self.lua.globals().BATCH = generator.OCPARTS_BATCH
        stock = self.lua.table()
        for identity, qty in stock_items.items():
            name, damage = generator.split_item(identity)
            stock[identity] = self.lua.table_from({
                'item': self.lua.table_from({'name': name, 'damage': damage}),
                'count': qty, 'maxSize': 64,
            })
        self.lua.globals().STOCK = stock
        self.lua.execute('''
          listing['/usr/lib/recipes']={'minecraft.dblz','opencomputers.dblz'}
          for _,namespace in ipairs({'minecraft','opencomputers'}) do
            local lines={};for line in SOURCE_TEXT:gmatch('[^\\n]+') do
              if line:sub(1,#namespace+1)==namespace..':' then lines[#lines+1]=line end
            end
            files['/usr/lib/recipes/'..namespace..'.dblz']=table.concat(lines,'\\n')..'\\n'
          end
          local builder=require('recipes.build');local built=builder.build();assert(builder.save(built))
          require('recipes').install(built)
          package.preload.oredict=function() return {get=function() end,getByItemName=function() end} end
          package.preload.craft_tools=function() return {list=function() return {} end} end
          package.preload.event=function() return {push=function() end} end
          -- This integration exercises the real compiler/planner/graph only;
          -- transport installation has its own actual-OpenOS/native gates.
          package.preload.mes_service=function() return {start=function() return true end,claims=function() return {} end,
            fuel=function() return {credit=0,admitted=0} end} end
          GROUPS={cpu1={type='crafter',roles={buffer='buf1'}},cpu2={type='crafter',roles={buffer='buf2'}},
            furnaceA={type='furnace',roles={input='ai',output='ao',fuel='af'}},
            furnaceB={type='furnace',roles={input='bi',output='bo',fuel='bf'}}}
          package.preload.warehouse=function() return {
            members=function() return {stock={}} end,
            contents=function(s) return {items=s=='stock' and STOCK or {}} end,
            groups=function(kind) local out={};for n,g in pairs(GROUPS) do
              if not kind or g.type==kind then out[n]=g end end;return out end
          } end
          MES=require('mes')
        ''')
        self.lua.execute(generator.OCPARTS_IMPORTS)
        self.lua.execute('''
          CFG={crafters={cpu1={robot='one'},cpu2={robot='two'}},machineTypes={furnace={
            inputs={'input'},output='output',fuel={role='fuel',item='minecraft:coal',per=8},
            batch=BATCH,seconds=10,blocking=false,roles={'input','fuel','output'},
            roleSlots={input={1},fuel={1},output={1}}}}}
        ''')

    def plan(self, target='opencomputers:component:6'):
        self.lua.globals().TARGET = target
        result = self.lua.execute("return MES.plan(TARGET,REQUEST_QTY,{config=CFG})")
        if isinstance(result, tuple):
            plan, error = result
        else:
            plan, error = result, None
        self.assertIsNotNone(plan, error)
        return plan

    def test_real_blueprint_dependencies_and_split_fuel(self):
        plan = self.plan()
        self.assertEqual(0, len(plan['missing']))
        stages = dict(plan['stages'].items())
        roots = [s for s in stages.values() if not len(s['after']) and s['kind'] == 'robot']
        self.assertGreaterEqual(len(roots), 2, 'independent robot branches must survive graph projection')
        pcb = next(s for s in stages.values() if s['kind'] == 'machine')
        self.assertEqual('furnace', pcb['machineType'])
        self.assertEqual(generator.OCPARTS_QTY // 8, pcb['fuel']['need'], 'round fuel independently for two physical furnaces')
        self.assertGreater(len(pcb['after']), 0)
        ram = next(s for s in stages.values()
                   if any(o['item'] == 'opencomputers:component:6' for _, o in s['outputs'].items()))
        pcb_index = next(i for i, s in stages.items() if s['kind'] == 'machine')
        self.assertIn(pcb_index, set(ram['after'].values()))
        self.assertGreaterEqual(len(ram['after']), 2, 'RAM must join PCB and chip branches')
        for _, ingredient in ram['inputs'].items():
            self.assertGreaterEqual(ingredient['have'], ingredient['need'])

    def test_real_plan_preserves_fuel_shortfall_as_plan(self):
        self.lua.execute("STOCK['minecraft:coal'].count=1")
        plan = self.plan()
        missing = [v for _, v in plan['missing'].items() if v['item'] == 'minecraft:coal']
        self.assertEqual(1, len(missing))
        self.assertEqual((generator.OCPARTS_QTY // 8, 1), (missing[0]['need'], missing[0]['have']))

    def test_successive_orders_reuse_surplus_and_make_additional_components(self):
        remaining = dict(generator.OCPARTS_STOCK)
        for quantity in (5, 3):
            self.lua.globals().REQUEST_QTY = quantity
            plan = self.plan()
            tasks = list(plan['tasks'].values())
            self.assertEqual(0, len(plan['missing']))
            if quantity == 3:
                self.assertEqual({'minecraft:iron_nugget', 'opencomputers:material:4',
                                  'opencomputers:component:6'}, {t['item'] for t in tasks})
                self.assertEqual(6, plan['inventory_needed']['opencomputers:material:7'])
                self.assertEqual(3, plan['inventory_needed']['opencomputers:material:2'])
                self.assertEqual(3, next(t['qty_produced'] for t in tasks
                                        if t['item'] == 'opencomputers:component:6'))
            for task in tasks:
                node = plan['blueprint']['nodes'][task['node']]
                for slot, qty in node['input_quantities'].items():
                    identity = node['recipe'][slot]
                    remaining[identity] = remaining.get(identity, 0) - qty * task['repetitions']
                identity = task['item']
                remaining[identity] = remaining.get(identity, 0) + task['qty_produced']
            for identity, count in remaining.items():
                name, damage = generator.split_item(identity)
                self.lua.globals().STOCK[identity] = self.lua.table_from({
                    'item': self.lua.table_from({'name': name, 'damage': damage}),
                    'count': count, 'maxSize': 64})
        # Furnace fuel credit is execution state, verified by the native case.
        self.assertEqual({k: v for k, v in generator.OCPARTS_REPEAT_FINAL.items() if k != 'minecraft:coal'},
                         {k: v for k, v in remaining.items() if v and k != 'minecraft:coal'})

    def test_real_blueprint_consumption_and_leftovers(self):
        plan = self.plan()
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
        for identity, qty in {'opencomputers:component:6':64, 'opencomputers:material:2':64,
                              'opencomputers:material:4':64, 'opencomputers:material:6':16,
                              'opencomputers:material:7':128}.items():
            self.assertEqual(qty, tasks[identity]['qty_produced'])
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

    def test_post_assembly_orders_use_remaining_stock_without_double_reserving(self):
        remaining = {k: v - generator.ROBOT_PARTS.get(k, 0) for k, v in generator.ROBOT_PARTS_FINAL.items()}
        self.setUp(generator.OCPARTS_RECIPES + (generator.SOURCE / 'robot-parts.tsv').read_text(), remaining)
        plans = []
        for item, quantity in [('opencomputers:component:11', 2), ('minecraft:chest', 1), ('minecraft:chest', 1)]:
            self.lua.globals().REQUEST_QTY = quantity
            plan = self.plan(item)
            self.assertEqual(0, len(plan['missing']), item)
            plans.append(plan)
            for key, count in plan['inventory_needed'].items():
                stock = self.lua.globals().STOCK[key]
                stock['count'] -= count
                self.assertGreaterEqual(stock['count'], 0, key)
        for plan in plans:
            for task in plan['tasks'].values():
                node = plan['blueprint']['nodes'][task['node']]
                for slot, qty in node['input_quantities'].items():
                    key = node['recipe'][slot]
                    remaining[key] = remaining.get(key, 0) - qty * task['repetitions']
                key = task['item']
                remaining[key] = remaining.get(key, 0) + task['qty_produced']
            for stage in plan['stages'].values():
                if stage['fuel']: remaining['minecraft:coal'] -= stage['fuel']['need']
        self.assertEqual(generator.ROBOT_EXPAND_FINAL, {k: v for k, v in remaining.items() if v})

    def test_complete_robot_parts_orders_from_raw_stock(self):
        self.setUp(generator.OCPARTS_RECIPES + (generator.SOURCE / 'robot-parts.tsv').read_text(),
                   generator.ROBOT_PARTS_STOCK)
        remaining = dict(generator.ROBOT_PARTS_STOCK)
        for identity, quantity in generator.ROBOT_PARTS.items():
            self.lua.globals().REQUEST_QTY = quantity
            plan = self.plan(identity)
            self.assertEqual(0, len(plan['missing']), identity)
            for task in plan['tasks'].values():
                node = plan['blueprint']['nodes'][task['node']]
                for slot, qty in node['input_quantities'].items():
                    key = node['recipe'][slot]
                    remaining[key] = remaining.get(key, 0) - qty * task['repetitions']
                key = task['item']
                remaining[key] = remaining.get(key, 0) + task['qty_produced']
            for stage in plan['stages'].values():
                if stage['fuel']: remaining['minecraft:coal'] -= stage['fuel']['need']
            for key, count in remaining.items():
                self.assertGreaterEqual(count, 0, key)
                name, damage = generator.split_item(key)
                self.lua.globals().STOCK[key] = self.lua.table_from({
                    'item': self.lua.table_from({'name': name, 'damage': damage}),
                    'count': count, 'maxSize': 64})
        self.assertEqual(generator.ROBOT_PARTS_FINAL, {k: v for k, v in remaining.items() if v})


if __name__ == '__main__':
    unittest.main()
