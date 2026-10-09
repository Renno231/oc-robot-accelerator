"""Fixture structure plus real recipe compiler/planner probes, not native evidence."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from lupa.lua53 import LuaRuntime
import runner_scenario

ROOT = Path(__file__).resolve().parent


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


generator = module('mes_fixture_builder', ROOT / 'examples/mes/build_fixtures.py')


class MesFixtureTests(unittest.TestCase):
    def test_shortfall_counts_input_clay_and_output_bricks_once(self):
        main = (ROOT / 'examples/mes/main.lua').read_text()
        proof = main[main.index("if case=='shortfall' then\n  scan()"):main.index('result.afterScan=')]
        lua = LuaRuntime()
        lua.execute('''
          case='shortfall';result={};scan=function() end
          count=function(id) return id=='minecraft:brick' and 32 or 0 end
          local listings={['furnA.in']={},['furnA.out']={{name='minecraft:brick',size=16}},
            ['furnB.in']={},['furnB.out']={{name='minecraft:coal',size=4}},['cpu1.buf']={}}
          read=function(id) return assert(listings[id]) end
          amount=function(listing,id) local n=0;for _,s in pairs(listing) do
            if s.name==id then n=n+s.size end end;return n end
        ''')
        lua.execute(proof)
        self.assertEqual(48, lua.globals().result['conservation']['total'])
        self.assertEqual(16, lua.globals().result['conservation']['machines']['A']['brick'])
        self.assertEqual(0, lua.globals().result['conservation']['machines']['B']['brick'])

    def test_destination_filters_merge_shared_stock_targets(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute('''
          FILTERS={};local nodes={}
          package.preload.map=function() return {
            node=function(n) return nodes[n] end,
            add=function(n,x,y,z) nodes[n]={x=x,y=y,z=z} end,
            name=function() end,group=function() end,link=function() end,
            nodes=function() return nodes end,save=function() end} end
          package.preload.warehouse=function() return {
            add=function(n,opts) FILTERS[n]=opts end,group=function() end} end
          package.preload.logistics=function() return {} end
        ''')
        lua.execute((ROOT / 'examples/mes/setup.lua').read_text())
        filters = lua.globals().FILTERS
        for storage, expected in [('s5_0_N', {'minecraft:torch', 'minecraft:brick_block'}),
                                  ('s6_0_N', {'minecraft:coal', 'minecraft:brick'})]:
            self.assertEqual(expected, {v['name'] for _, v in filters[storage]['filter'].items()})

    def test_regeneration_removes_stale_ui(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for program in ('program', 'robot-program'):
                ui = root / program / 'usr/lib/mes_ui'
                ui.mkdir(parents=True)
                (ui / 'core.lua').write_text('stale')
                binary = root / program / 'usr/bin'
                binary.mkdir(parents=True)
                (binary / 'mesui.lua').write_text('stale')
            generator.build(root)
            for program in ('program', 'robot-program'):
                self.assertFalse((root / program / 'usr/lib/mes_ui').exists())
                self.assertFalse((root / program / 'usr/bin/mesui.lua').exists())

    def test_done_waits_for_warehouse_catalogue_completion(self):
        main = (ROOT / 'examples/mes/main.lua').read_text()
        start = main.index('local function done(id)')
        stop = main.index("event.listen('logistics'", start)
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute('''
          polls=0
          lg={status=function() return {state='done'} end}
          wh={settled=function(id) assert(id=='job');return polls>=2 end}
          wait=function(fn)
            while not fn() do polls=polls+1;assert(polls<5) end
          end
        ''')
        done = lua.execute(main[start:stop] + '\nreturn done')
        self.assertEqual('done', done('job')['state'])
        self.assertEqual(2, lua.globals().polls)
        lua.execute('wh.settled=nil;polls=0')
        self.assertEqual('done', done('job')['state'])
        self.assertEqual(0, lua.globals().polls)

    def test_archive_writer_with_native_openos_buffer_close_contract(self):
        # Exercise real liblz16 AND the runner's OpenOS buffer, not the database
        # suite's archive mock (whose close incorrectly promises a true result).
        buffer = ROOT / '.cache/oc-source/src/main/resources/assets/opencomputers/loot/openos/lib/buffer.lua'
        if not buffer.is_file():
            self.skipTest('native OpenOS sources not installed')
        lua = LuaRuntime(unpack_returned_tuples=True)
        lib = (ROOT / 'craftsystem/usr/lib').as_posix()
        lua.execute(f'package.path="{lib}/?.lua;{lib}/?/init.lua;"..package.path')
        lua.globals().BUFFER_SOURCE = buffer.read_text()
        lua.globals().FULL_BUFFER_SOURCE = (buffer.parent / 'core/full_buffer.lua').read_text()
        lua.globals().SOURCE_TEXT = (ROOT / 'examples/mes/recipes.tsv').read_text()
        lua.execute('''
          checkArg=function(_,v,t) assert(type(v)==t) end
          os.sleep=function() end
          package.preload.computer=function() return {freeMemory=function() return 65536 end,uptime=function() return 0 end} end
          package.preload.unicode=function() return {len=string.len,sub=string.sub} end
          package.delay=function(b)
            package.loaded.buffer=b
            assert(load(FULL_BUFFER_SOURCE))()
          end
          package.preload.buffer=function() return assert(load(BUFFER_SOURCE))() end
          local bytes=''
          io.open=function(_,mode)
            assert(mode=='wb')
            return {mode={w=true,b=true},write=function(_,data) bytes=bytes..data;return true end,
              close=function() end}
          end
          local archive=assert(require('liblz16').open('fixture.dblz','wb'))
          assert(archive:write(SOURCE_TEXT)==archive) -- OpenOS write is truthy.
          assert(select('#',archive:close())==0) -- Native close has no return values.
          assert(archive.closed)
          local reader=require('liblz16').buffer({mode={r=true},read=function(_,n)
            if bytes=='' then return nil end
            local chunk=bytes:sub(1,n);bytes=bytes:sub(n+1);return chunk
          end,close=function() end})
          assert(reader:read('*a')==SOURCE_TEXT) -- Close flushed the compressed archive.
          -- Real eager ore-dictionary initialization must accept the same empty
          -- native archive emitted by fixture install before either planner boots.
          bytes=''
          local empty=assert(require('liblz16').open('/usr/lib/oredict/oredict.dblz','wb'))
          empty:close()
          assert(bytes=='lz16')
          io.open=function(path,mode)
            assert(path=='/usr/lib/oredict/oredict.dblz' and mode==nil)
            return {mode={r=true,b=true},read=function(_,n)
              if bytes=='' then return nil end
              local chunk=bytes:sub(1,n);bytes=bytes:sub(n+1);return chunk
            end,close=function() end}
          end
          package.preload.serialization=function() return {unserialize=function() error('empty archive has no entries') end} end
          package.preload.filesystem=function() return {concat=function(a,b) return a..b end} end
          local ores=require('oredict') -- unchanged init.lua, liblz16, lzss and cbor
          assert(next(ores.cache)==nil and next(ores.reverseCache)==nil)
          assert(ores.get('plankWood')==nil and ores.getByItemName('minecraft:log')==nil)
        ''')
        main = (ROOT / 'examples/mes/main.lua').read_text()
        self.assertIn('assert(archive:write(text));archive:close()', main)
        self.assertNotIn('assert(archive:close())', main)
        install = (ROOT / 'examples/mes/install.lua').read_text()
        self.assertIn("require('liblz16').open('/usr/lib/oredict/oredict.dblz','wb')", install)
        self.assertIn('ores:close()', install)

    def test_generated_worlds_and_native_baseline_validate(self):
        for case in generator.CASES:
            for mode in ('coordinated', 'baseline'):
                with self.subTest(case=case, mode=mode), tempfile.TemporaryDirectory() as tmp:
                    path = generator.build(Path(tmp), case, mode)
                    value = runner_scenario.load(path).normalized
                    self.assertEqual(67, len(value['containers']))
                    self.assertEqual(6, len(value['drones']))
                    self.assertEqual(1, len(value['robots']))
                    self.assertTrue(value['execution']['infiniteEnergy'])
                    self.assertEqual(mode, value['execution']['mode'])
                    self.assertEqual('robot-program-0', value['robots'][0]['program']['directory'])
                    self.assertEqual([8, 65, 0], value['robots'][0]['position'])
                    self.assertEqual('south', value['robots'][0]['facing'])
                    self.assertIn('craftingupgrade', value['robots'][0]['hardware']['upgrades'])
                    self.assertEqual(2, sum(b['block'] == 'minecraft:furnace' for b in value['blocks']))
                    self.assertEqual(case == 'shortfall', bool(value['containerEdits']))
                    self.assertEqual([{'index': 0, 'inventory': [{'slot': n, 'count': 0} for n in range(1, 17)]}], value['expect']['robots'])
                    self.assertEqual(27, len(value['expect']['containers'][0]['slots']))
                    self.assertTrue(all(s['count'] == 0 for s in value['expect']['containers'][0]['slots']))
                    for drone in value['expect']['drones']:
                        self.assertEqual([{'slot': n, 'count': 0} for n in range(1, 5)], drone['inventory'])
                    furnaces = [c for c in value['expect']['containers'] if c['position'] in ([10, 64, 7], [10, 64, 9])]
                    self.assertEqual(2 if case in ('torches16', 'bricks16', 'specific-group') else 0, len(furnaces))
                    for furnace in furnaces:
                        self.assertEqual([{'slot': 1, 'count': 0}, {'slot': 3, 'count': 0}], furnace['slots'])

    def test_canonical_sources_are_not_patched(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = generator.build(Path(tmp)).parent
            for src in (ROOT / 'craftsystem/usr').rglob('*'):
                if src.is_file() and 'mes_ui' not in src.parts and src.name != 'mesui.lua':
                    for program in ('program', 'robot-program'):
                        self.assertEqual(src.read_bytes(), (target / program / 'usr' / src.relative_to(ROOT / 'craftsystem/usr')).read_bytes())
            for program in ('program', 'robot-program'):
                self.assertFalse((target / program / 'usr/lib/mes_ui').exists())
                self.assertFalse((target / program / 'usr/bin/mesui.lua').exists())
            for name in ('map', 'warehouse', 'logistics'):
                self.assertEqual((ROOT / f'drone-logistics/lib/{name}.lua').read_bytes(),
                                 (target / f'program/lib/{name}.lua').read_bytes())

    def test_shipped_fixtures_are_generated(self):
        for case in generator.CASES:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                fresh = generator.build(Path(tmp), case).parent
                shipped = ROOT / 'examples/mes' / case
                files = {p.relative_to(fresh) for p in fresh.rglob('*') if p.is_file()}
                self.assertEqual(files, {p.relative_to(shipped) for p in shipped.rglob('*') if p.is_file()})
                for relative in files:
                    self.assertEqual((fresh / relative).read_bytes(), (shipped / relative).read_bytes(), str(relative))

    def test_recipe_compiler_and_users_planner_arithmetic(self):
        support = module('mes_database_support', ROOT / 'craftsystem/tests/test_database.py')
        lua = LuaRuntime(unpack_returned_tuples=True)
        lib = (ROOT / 'craftsystem/usr/lib').as_posix()
        lua.execute(f'package.path="{lib}/?.lua;{lib}/?/init.lua;"..package.path')
        lua.execute(support.MOCKS)
        lua.globals().SOURCE_TEXT = (ROOT / 'examples/mes/recipes.tsv').read_text()
        lua.execute('''
          listing['/usr/lib/recipes']={'minecraft.dblz'}
          files['/usr/lib/recipes/minecraft.dblz']=SOURCE_TEXT
          local builder=require('recipes.build');local built=builder.build();assert(builder.save(built))
          local db=require('recipes');db.install(built)
          assert(db.registerProcessingRecipe('minecraft:coal:1','furnace',{recipe={'minecraft:log'},qty=1}))
          assert(db.registerProcessingRecipe('minecraft:brick','furnace',{recipe={'minecraft:clay_ball'},qty=1}))
          package.preload.oredict=function() return {get=function() end,getByItemName=function() end} end
          package.preload.craft_tools=function() return {list=function() return {} end} end
          function plan(id,stacks)
            local p=require('craftingv4_4').calculateCraftingPlan(id,16,
              {getAllStacks=function() return {getAll=function() return stacks end} end},0,true)
            for i=1,100 do if not p.yield_data then assert(p.craftable,p.error);return p end
              require('craftingv4_4').resumeCalculation(p) end
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

    def test_fixture_lua_syntax_and_boot_contract(self):
        lua = LuaRuntime()
        compile_lua = lua.eval('function(s) local f,e=load(s);assert(f,e);return true end')
        for name in ('main.lua', 'setup.lua', 'robot.lua', 'install.lua'):
            self.assertTrue(compile_lua((ROOT / 'examples/mes' / name).read_text()))
        main = (ROOT / 'examples/mes/main.lua').read_text()
        self.assertIn("'/home/warehouse-results.lua'", main)
        self.assertIn('stage.receipt.status', main)
        self.assertIn("loads['furnA.in']==each", main)
        self.assertIn("assert(conservation.total==48", main)
        self.assertIn('result.conservation=conservation', main)
        self.assertIn('stockClay+stockBrick', main)
        self.assertIn("assert(loadfile('/usr/bin/cproc.lua'))('--side=3')", (ROOT / 'examples/mes/robot.lua').read_text())


if __name__ == '__main__':
    unittest.main()
