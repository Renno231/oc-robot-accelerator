"""Real recipe compiler/planner to MES graph integration; no native substitute."""
import unittest

from lupa.lua53 import LuaRuntime
from test_mes_fixtures import ROOT, generator, module


class OcpartsMesPlanTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        lib = (ROOT / 'craftsystem/usr/lib').as_posix()
        self.lua.execute(f'package.path="{lib}/?.lua;{lib}/?/init.lua;"..package.path')
        support = module('ocparts_mes_database_support', ROOT / 'craftsystem/tests/test_database.py')
        self.lua.execute(support.MOCKS)
        self.lua.globals().SOURCE_TEXT = generator.OCPARTS_RECIPES
        self.lua.globals().REQUEST_QTY = generator.OCPARTS_QTY
        self.lua.globals().BATCH = generator.OCPARTS_BATCH
        stock = self.lua.table()
        for identity, qty in generator.OCPARTS_STOCK.items():
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

    def plan(self):
        result = self.lua.execute("return MES.plan('opencomputers:component:6',REQUEST_QTY,{config=CFG})")
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


if __name__ == '__main__':
    unittest.main()
