from pathlib import Path
import unittest
from lupa.lua53 import LuaRuntime

ROOT = Path(__file__).resolve().parent


class MesServiceCliTests(unittest.TestCase):
    def run_cli(self, args):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.globals().ARGS = lua.table_from(args)
        lua.execute('''
            print=function() end
            MES={start=function() STARTS=(STARTS or 0)+1;return true end,
              plan=function(item,qty) ITEM=item;QTY=qty;return {item=item} end,
              run=function(plan) RUN=plan;return 7 end,
              wait=function(id) WAIT=id;return {status='complete'} end}
            require=function(name)
              if name=='mes' then return MES end
              if name=='shell' then return {parse=function() return ARGS,{} end} end
              error(name)
            end
        ''')
        result = lua.execute((ROOT / 'craftsystem/usr/bin/mes.lua').read_text())
        return result, lua

    def test_start_installs_service_without_submitting_run(self):
        result, lua = self.run_cli(['start'])
        self.assertEqual(result, 0)
        self.assertEqual(lua.globals().STARTS, 1)
        self.assertIsNone(lua.globals().RUN)

    def test_item_shorthand_submits_and_waits(self):
        result, lua = self.run_cli(['opencomputers:component:6', '64'])
        self.assertEqual(result, 0)
        self.assertEqual((lua.globals().ITEM, lua.globals().QTY, lua.globals().WAIT),
                         ('opencomputers:component:6', 64, 7))

    def test_item_shorthand_defaults_to_one(self):
        result, lua = self.run_cli(['minecraft:torch'])
        self.assertEqual(result, 0)
        self.assertEqual(lua.globals().QTY, 1)
