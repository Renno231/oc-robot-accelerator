from pathlib import Path
import unittest
from lupa.lua53 import LuaRuntime

ROOT = Path(__file__).resolve().parent


class MesServiceCliTests(unittest.TestCase):
    def run_cli(self, args, setup=None):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.globals().ARGS = lua.table_from(args)
        lua.execute('''
            OUTPUT={};print=function(...) local line={...};for i,v in ipairs(line) do line[i]=tostring(v) end
              OUTPUT[#OUTPUT+1]=table.concat(line,' ') end
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
        if setup:
            lua.execute(setup)
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

    def test_status_is_read_only_and_stop_targets_mes_order_not_robot(self):
        setup='''
            MES.status=function(id) STATUS_ID=id;return {status='running',stages={{kind='machine',state='processing'}}} end
            MES.cancel=function(id,reason) STOP_ID=id;STOP_REASON=reason;return true end
        '''
        code,lua=self.run_cli(['status','7'],setup)
        self.assertEqual((code,lua.globals().STATUS_ID,lua.globals().STOP_ID,lua.globals().RUN),(0,7,None,None))
        code,lua=self.run_cli(['stop','7'],setup)
        self.assertEqual((code,lua.globals().STOP_ID,lua.globals().STOP_REASON,lua.globals().RUN),(0,7,'Stopped by player',None))

    def test_runs_lists_orders_without_submitting_work(self):
        code,lua=self.run_cli(['runs'],"MES.runs=function() LISTED=true;return {{id=7,status='complete',item='t:gear'}} end")
        self.assertEqual((code,lua.globals().LISTED,lua.globals().RUN),(0,True,None))

    def test_terminal_order_reports_leftover_material_without_another_stop(self):
        code,lua=self.run_cli(['stop','7'],'''MES.status=function() return {
          status='failed',reason='Stopped by player',stages={},
          where={{item='t:raw',count=3,storage='cpu1.buf'}}} end
          MES.cancel=function() error('terminal order must not be cancelled again') end''')
        self.assertEqual(code,0)
        self.assertIn('Outside stock: 3 t:raw in cpu1.buf',lua.eval("table.concat(OUTPUT,'\\n')"))

    def test_invalid_order_id_never_starts_service(self):
        for value in ('0','-1','1.5','inf','missing'):
            with self.subTest(value=value):
                code,lua=self.run_cli(['stop',value])
                self.assertNotEqual(code,0)
                self.assertIsNone(lua.globals().STARTS)
