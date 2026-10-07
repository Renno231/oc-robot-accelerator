"""Compiled-db paths with real CBOR/LZSS and mocked OpenOS file transport."""
import unittest
from lupa.lua53 import LuaRuntime, LuaError
from test_database import MOCKS, ROOT


class CompiledDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        lib = (ROOT / 'usr/lib').as_posix()
        self.lua.execute(f'package.path = "{lib}/?.lua;{lib}/?/init.lua;"..package.path')
        self.lua.execute(MOCKS)
        self.lua.execute("""
            RAW_OPENS, COMPILED_READS, COMPRESS_CALLS = 0,0,0
            local baseOpen=io.open
            io.open=function(path,mode)
                if path=='/usr/lib/recipes/compiled.cb' and mode=='rb' then COMPILED_READS=COMPILED_READS+1 end
                return baseOpen(path,mode)
            end
            package.preload.liblz16=function() return {open=function(...)
                RAW_OPENS=RAW_OPENS+1;return mockOpen(...)
            end} end
            local lz=require('lzss');local compress=lz.compress
            lz.compress=function(...) COMPRESS_CALLS=COMPRESS_CALLS+1;return compress(...) end
            package.preload.shell=function() return {parse=function(...) return {...},SCRIPT_OPTIONS or {} end} end
            SOURCE='/usr/lib/recipes/alpha.dblz'
            COMPILED='/usr/lib/recipes/compiled.cb'
            listing['/usr/lib/recipes']={'alpha.dblz'}
            files[SOURCE]='alpha:one\\t{[1]="t:old",qty=2}\\nalpha:two:3\\t{[2]="t:raw"}\\n'
            BUILD=require('recipes.build')
            function resetCounts() RAW_OPENS,COMPILED_READS,COMPRESS_CALLS=0,0,0 end
            function seedCompiled() local db=BUILD.build();assert(BUILD.save(db));resetCounts();return db end
            function allClosed() for _,h in ipairs(handles) do if not h.closed then return false end end;return true end
        """)

    def script(self, *args):
        return self.lua.execute((ROOT / 'usr/bin/build_db.lua').read_text(), *args)

    def test_require_is_lightweight_and_existing_compiled_file_is_loaded_once(self):
        self.assertEqual(self.lua.execute("""
            seedCompiled();DB=require('recipes')
            assert(RAW_OPENS==0 and COMPILED_READS==0 and next(DB.__recipes)==nil)
            local a=DB.getAll('alpha:one');local b=DB.getAll('alpha:two:3');DB.getAll('alpha:one')
            return a[1][1],b[1][2],RAW_OPENS,COMPILED_READS,COMPRESS_CALLS,allClosed()
        """), ('t:old', 't:raw', 0, 1, 0, True))

    def test_missing_compiled_file_builds_saves_and_uses_table_without_reread(self):
        self.assertEqual(self.lua.execute("""
            DB=require('recipes');local a=DB.getAll('alpha:one');DB.getAll('alpha:two:3')
            return a[1].qty,files[COMPILED]~=nil,RAW_OPENS,COMPILED_READS,COMPRESS_CALLS>0,allClosed()
        """), (2, True, 1, 0, True, True))

    def test_second_library_load_uses_compiled_even_if_sources_are_unavailable(self):
        self.assertEqual(self.lua.execute("""
            require('recipes').getAll('alpha:one');package.loaded.recipes=nil
            files[SOURCE]=nil;listing['/usr/lib/recipes']={};resetCounts()
            local db=require('recipes');return db.getAll('alpha:one')[1][1],RAW_OPENS,COMPILED_READS,COMPRESS_CALLS
        """), ('t:old', 0, 1, 0))

    def test_install_adopts_same_table_and_clears_decoded_cache(self):
        self.assertEqual(self.lua.execute("""
            DB=require('recipes');DB.getAll('alpha:one')
            files[SOURCE]='alpha:one\\t{[1]="t:new"}\\n'
            local built=BUILD.build();resetCounts();DB.install(built)
            assert(DB.__recipes==built and #DB._recipeCache==0)
            return DB.getAll('alpha:one')[1][1],RAW_OPENS,COMPILED_READS,COMPRESS_CALLS
        """), ('t:new', 0, 0, 0))

    def test_build_db_default_rebuilds_file_without_loading_library(self):
        self.assertTrue(self.script())
        self.assertEqual(self.lua.execute("return files[COMPILED]~=nil,package.loaded.recipes==nil,RAW_OPENS,COMPILED_READS"), (True, True, 1, 0))
        self.assertTrue(self.lua.execute('return allClosed()'))

    def test_build_db_load_populates_new_library_using_exact_built_table(self):
        self.lua.execute("""
            SCRIPT_OPTIONS={load=true}
            local build=BUILD.build;BUILD.build=function(...) BUILT=build(...);return BUILT end
        """)
        self.assertTrue(self.script())
        self.assertEqual(self.lua.execute("""
            local db=require('recipes');assert(db.__recipes==BUILT)
            return db.getAll('alpha:one')[1][1],RAW_OPENS,COMPILED_READS
        """), ('t:old', 1, 0))

    def test_build_db_load_replaces_existing_library_and_cache(self):
        self.lua.execute("""
            DB=require('recipes');DB.getAll('alpha:one')
            files[SOURCE]='alpha:one\\t{[1]="t:new"}\\n';resetCounts();SCRIPT_OPTIONS={load=true}
        """)
        self.script()
        self.assertEqual(self.lua.execute("return DB.getAll('alpha:one')[1][1],RAW_OPENS,COMPILED_READS"), ('t:new', 1, 0))

    def test_default_build_leaves_live_database_until_explicit_reload(self):
        self.lua.execute("""
            DB=require('recipes');DB.getAll('alpha:one')
            files[SOURCE]='alpha:one\\t{[1]="t:new"}\\n';resetCounts()
        """)
        self.script()
        self.assertEqual(self.lua.execute("""
            local old=DB.getAll('alpha:one')[1][1];DB.reload()
            return old,DB.getAll('alpha:one')[1][1],RAW_OPENS,COMPILED_READS
        """), ('t:old', 't:new', 1, 1))

    def test_install_preserves_processing_recipes_and_registration_overrides_cache(self):
        self.assertEqual(self.lua.execute("""
            DB=require('recipes');DB.getAll('alpha:one')
            assert(DB.registerProcessingRecipe('alpha:one','furnace',{qty=4,recipe={'t:input,2'}}))
            local process=DB.__processRecipes;local built=BUILD.build();DB.install(built)
            return DB.__processRecipes==process,DB.getAll('alpha:one')[1].machineType,files['/usr/lib/recipes/process.cb']~=nil
        """), (True, 'furnace', True))

    def test_processing_only_lookup_does_not_force_crafting_build(self):
        self.assertEqual(self.lua.execute("""
            files['/usr/lib/recipes/process.cb']=require('cbor').encode({['t:processed']={{isProcessing=true,machineType='furnace',qty=1,[1]='t:raw'}}})
            local db=require('recipes');local r=db.getAll('t:processed')
            return r[1].machineType,RAW_OPENS,COMPILED_READS,files[COMPILED]==nil
        """), ('furnace', 0, 0, True))

    def test_corrupt_existing_compiled_file_is_reported_without_implicit_rebuild(self):
        self.lua.execute("files[COMPILED]='broken';DB=require('recipes')")
        with self.assertRaisesRegex(LuaError, 'run build_db'):
            self.lua.execute("DB.getAll('alpha:one')")
        self.assertEqual(self.lua.execute('return RAW_OPENS,COMPILED_READS,allClosed()'), (0, 1, True))

    def test_corrupt_inner_dictionaries_report_item_path_and_rebuild_without_source_reads(self):
        cases = {
            'lzss': "'broken'",
            'cbor': "lz.compress('broken')",
            'dictionary': 'lz.compress(cbor.encode(42))',
            'category': 'lz.compress(cbor.encode({base=42}))',
            'category_key': 'lz.compress(cbor.encode({[1]={}}))',
            'encoded_recipe': 'lz.compress(cbor.encode({base={42}}))',
            'decoded_recipe': 'lz.compress(cbor.encode({base={cbor.encode(42)}}))',
            'list_key': 'lz.compress(cbor.encode({base={bad=cbor.encode({})}}))',
            'list_gap': 'lz.compress(cbor.encode({base={[2]=cbor.encode({})}}))',
        }
        for corruption, dictionary in cases.items():
            with self.subTest(corruption=corruption):
                self.setUp()
                self.lua.execute(f"""
                    local cbor=require('cbor');local lz=require('lzss')
                    files[COMPILED]=cbor.encode({{alpha={{one={dictionary}}}}})
                    DB=require('recipes')
                """)
                with self.assertRaisesRegex(LuaError, r'compiled\.cb recipe alpha:one:.*run build_db'):
                    self.lua.execute("DB.getAll('alpha:one')")
                self.assertEqual(self.lua.execute('return RAW_OPENS,COMPILED_READS,allClosed(),#DB._recipeCache'), (0, 1, True, 0))

    def test_missing_metadata_is_a_normal_lookup_miss(self):
        self.assertEqual(self.lua.execute("""
            seedCompiled();local db=require('recipes')
            return db.getAll('alpha:one:9')==nil,db.getAll('alpha:one')[1][1],RAW_OPENS,COMPILED_READS
        """), (True, 't:old', 0, 1))

    def test_malformed_source_namespace_and_empty_item_fail_before_save(self):
        for item, message in (('beta:one', 'invalid recipe namespace'), ('alpha:', 'empty recipe item'), ('alpha::0', 'empty recipe item')):
            with self.subTest(item=item):
                self.setUp()
                self.lua.globals().files['/usr/lib/recipes/alpha.dblz'] = item + '\t{[1]="t:raw"}\n'
                with self.assertRaisesRegex(LuaError, message):
                    self.script()
                self.assertEqual(self.lua.execute('return files[COMPILED]==nil,RAW_OPENS,allClosed()'), (True, 1, True))

    def test_invalid_compiled_structure_and_invalid_install_are_rejected(self):
        self.lua.execute("files[COMPILED]=require('cbor').encode({alpha={one={}}});DB=require('recipes')")
        with self.assertRaisesRegex(LuaError, 'invalid compressed recipe dictionary'):
            self.lua.execute("DB.getAll('alpha:one')")
        with self.assertRaisesRegex(LuaError, 'expected compiled recipe table'):
            self.lua.execute('DB.install(42)')
        self.assertTrue(self.lua.execute('return allClosed()'))

    def test_load_open_read_and_close_failures_close_returned_handles(self):
        for failure in ('open', 'read', 'close'):
            with self.subTest(failure=failure):
                self.setUp()
                self.lua.execute('seedCompiled();DB=require("recipes")')
                if failure == 'open':
                    self.lua.execute('failOpen[COMPILED]=true')
                elif failure == 'close':
                    self.lua.execute('failClose[COMPILED]=true')
                else:
                    self.lua.execute("local open=io.open;io.open=function(path,mode) local h,e=open(path,mode);if path==COMPILED and h then h.read=function() error('read failure') end end;return h,e end")
                with self.assertRaises(LuaError):
                    self.lua.execute("DB.getAll('alpha:one')")
                self.assertTrue(self.lua.execute('return allClosed()'))

    def test_missing_cache_save_failure_keeps_runtime_table_without_rebuilding(self):
        self.assertEqual(self.lua.execute("""
            failWrite[COMPILED]=true;local db=require('recipes')
            local a=db.getAll('alpha:one');db.getAll('alpha:two:3')
            return a[1][1],RAW_OPENS,COMPILED_READS,allClosed(),table.concat(messages,' '):find('not saved')~=nil
        """), ('t:old', 1, 0, True, True))

    def test_explicit_build_save_failure_is_reported_and_not_installed(self):
        self.lua.execute('failWrite[COMPILED]=true;SCRIPT_OPTIONS={load=true}')
        with self.assertRaisesRegex(LuaError, 'cannot save'):
            self.script()
        self.assertEqual(self.lua.execute('return package.loaded.recipes==nil,allClosed()'), (True, True))

    def test_sparse_recipes_and_multiple_metadata_categories_roundtrip(self):
        self.assertEqual(self.lua.execute("""
            files[SOURCE]='alpha:one\\t{[1]="t:a",[9]="t:b",qty=3}\\nalpha:one:0\\t{[2]="t:zero"}\\nalpha:one:4\\t{[7]="t:four"}\\n'
            seedCompiled();local db=require('recipes')
            return db.getAll('alpha:one')[1][9],db.getAll('alpha:one:0')[1][2],db.getAll('alpha:one:4')[1][7]
        """), ('t:b', 't:zero', 't:four'))
