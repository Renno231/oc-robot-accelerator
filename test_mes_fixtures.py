"""Current fixture setup and real recipe/archive contracts, not native evidence."""
import unittest
import json
from pathlib import Path
import re
import tempfile

from lupa.lua53 import LuaRuntime
from examples.mes.build_fixtures import ROOT, SOURCE, build_native
from craftsystem.tests.test_database import MOCKS


class MesFixtureTests(unittest.TestCase):
    def test_robot_disks_contain_execution_dependencies_not_server_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'case'
            scenario = json.loads(build_native(target, 'concurrent').read_text())
            for robot in scenario['robots']:
                disk = target / robot['program']['directory']
                self.assertEqual(['cproc.lua'], [p.name for p in (disk / 'usr/bin').iterdir()])
                for unwanted in ('mes.lua', 'craft_plans.lua', 'dataio.lua', 'csv.lua', 'oredict'):
                    self.assertFalse((disk / 'usr/lib' / unwanted).exists(), unwanted)
                for path in (disk / 'usr').rglob('*.lua'):
                    canonical = ROOT / 'craftsystem/usr' / path.relative_to(disk / 'usr')
                    self.assertEqual(canonical.read_bytes(), path.read_bytes())
                    for name in re.findall(r'require\s*\(?\s*[\'"]([^\'"]+)[\'"]', path.read_text()):
                        dependency = Path('lib') / (name.replace('.', '/') + '.lua')
                        if (ROOT / 'craftsystem/usr' / dependency).is_file():
                            self.assertTrue((disk / 'usr' / dependency).is_file(), f'{path.name}: {name}')
                self.assertTrue((disk / 'etc/rc.d/cproc.lua').is_file())
                self.assertIn('"cproc"', (disk / 'etc/rc.cfg').read_text())
            self.assertTrue((target / 'program/usr/lib/recipes/build.lua').is_file())

    def test_destination_filters_merge_shared_stock_targets(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute('''
          FILTERS={};local nodes={}
          package.preload["logistics.map"]=function() return {
            node=function(n) return nodes[n] end,
            add=function(n,x,y,z) nodes[n]={x=x,y=y,z=z} end,
            name=function() end,group=function() end,link=function() end,
            nodes=function() return nodes end,save=function() end} end
          package.preload["logistics.warehouse"]=function() return {
            add=function(n,opts) FILTERS[n]=opts end,group=function() end} end
          package.preload.logistics=function() return {} end
        ''')
        lua.execute((SOURCE / 'setup.lua').read_text())
        for storage, expected in [('s5_0_N', {'minecraft:torch', 'minecraft:brick_block'}),
                                  ('s6_0_N', {'minecraft:coal', 'minecraft:brick'})]:
            self.assertEqual(expected, {v['name'] for _, v in lua.globals().FILTERS[storage]['filter'].items()})

    def test_archive_writer_with_native_openos_buffer_close_contract(self):
        # Real OpenOS close returns no values; the database mock returns true.
        buffer = ROOT / '.cache/oc-source/src/main/resources/assets/opencomputers/loot/openos/lib/buffer.lua'
        if not buffer.is_file(): self.skipTest('native OpenOS sources not installed')
        lua = LuaRuntime(unpack_returned_tuples=True)
        lib = (ROOT / 'craftsystem/usr/lib').as_posix()
        lua.execute(f'package.path="{lib}/?.lua;{lib}/?/init.lua;"..package.path')
        lua.globals().BUFFER_SOURCE = buffer.read_text()
        lua.globals().FULL_BUFFER_SOURCE = (buffer.parent / 'core/full_buffer.lua').read_text()
        lua.globals().SOURCE_TEXT = (SOURCE / 'recipes.tsv').read_text()
        lua.execute('''
          checkArg=function(_,v,t) assert(type(v)==t) end
          os.sleep=function() end
          package.preload.computer=function() return {freeMemory=function() return 65536 end,uptime=function() return 0 end} end
          package.preload.unicode=function() return {len=string.len,sub=string.sub} end
          package.delay=function(b) package.loaded.buffer=b;assert(load(FULL_BUFFER_SOURCE))() end
          package.preload.buffer=function() return assert(load(BUFFER_SOURCE))() end
          local bytes=''
          io.open=function(_,mode)
            assert(mode=='wb')
            return {mode={w=true,b=true},write=function(_,data) bytes=bytes..data;return true end,
              close=function() end}
          end
          local archive=assert(require('liblz16').open('fixture.dblz','wb'))
          assert(archive:write(SOURCE_TEXT)==archive)
          assert(select('#',archive:close())==0)
          assert(archive.closed)
          local reader=require('liblz16').buffer({mode={r=true},read=function(_,n)
            if bytes=='' then return nil end
            local chunk=bytes:sub(1,n);bytes=bytes:sub(n+1);return chunk
          end,close=function() end})
          assert(reader:read('*a')==SOURCE_TEXT)
          bytes=''
          local empty=assert(require('liblz16').open('/usr/lib/oredict/oredict.dblz','wb'))
          empty:close();assert(bytes=='lz16')
          io.open=function(path,mode)
            assert(path=='/usr/lib/oredict/oredict.dblz' and mode==nil)
            return {mode={r=true,b=true},read=function(_,n)
              if bytes=='' then return nil end
              local chunk=bytes:sub(1,n);bytes=bytes:sub(n+1);return chunk
            end,close=function() end}
          end
          package.preload.serialization=function() return {unserialize=function() error('empty archive has no entries') end} end
          package.preload.filesystem=function() return {concat=function(a,b) return a..b end} end
          local ores=require('oredict')
          assert(next(ores.cache)==nil and next(ores.reverseCache)==nil)
          assert(ores.get('plankWood')==nil and ores.getByItemName('minecraft:log')==nil)
        ''')

    def test_recipe_compiler_and_users_planner_arithmetic(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lib = (ROOT / 'craftsystem/usr/lib').as_posix()
        lua.execute(f'package.path="{lib}/?.lua;{lib}/?/init.lua;"..package.path')
        lua.execute(MOCKS)
        lua.globals().SOURCE_TEXT = (SOURCE / 'recipes.tsv').read_text()
        lua.execute('''
          listing['/usr/lib/recipes']={'minecraft.dblz'}
          files['/usr/lib/recipes/minecraft.dblz']=SOURCE_TEXT
          local builder=require('recipes.build');local built=builder.build();assert(builder.save(built))
          local db=require('recipes');db.install(built)
          assert(db.registerProcessingRecipe('minecraft:coal:1','furnace',{recipe={'minecraft:log'},qty=1}))
          assert(db.registerProcessingRecipe('minecraft:brick','furnace',{recipe={'minecraft:clay_ball'},qty=1}))
          package.preload.oredict=function() return {get=function() end,getByItemName=function() end} end
          package.preload["craft.tools"]=function() return {list=function() return {} end} end
          function plan(id,stacks)
            local p=require('craft.demand').calculateCraftingPlan(id,16,
              {getAllStacks=function() return {getAll=function() return stacks end} end},0,true)
            for i=1,100 do if not p.yield_data then assert(p.craftable,p.error);return p end
              require('craft.demand').resumeCalculation(p) end
            error('planner did not terminate')
          end
          TORCH=plan('minecraft:torch',{{name='minecraft:log',damage=0,size=8,maxSize=64},
            {name='minecraft:coal',damage=0,size=16,maxSize=64}})
          BRICKS=plan('minecraft:brick_block',{{name='minecraft:clay_ball',damage=0,size=64,maxSize=64}})
        ''')
        torch = lua.globals().TORCH
        self.assertEqual(5, torch['inventory_needed']['minecraft:log'])
        self.assertEqual(['minecraft:coal:1', 'minecraft:planks', 'minecraft:stick', 'minecraft:torch'],
                         [t['item'] for _, t in torch['tasks'].items()])
        self.assertEqual([4, 4, 4, 16], [t['qty_produced'] for _, t in torch['tasks'].items()])
        bricks = lua.globals().BRICKS
        self.assertEqual(64, bricks['inventory_needed']['minecraft:clay_ball'])
        self.assertEqual([64, 16], [t['qty_produced'] for _, t in bricks['tasks'].items()])

    def test_current_fixture_lua_syntax(self):
        compile_lua = LuaRuntime().eval('function(s) local f,e=load(s);assert(f,e);return true end')
        for name in ('native.lua', 'setup.lua', 'robot.lua', 'install.lua'):
            self.assertTrue(compile_lua((SOURCE / name).read_text()))


if __name__ == '__main__':
    unittest.main()
