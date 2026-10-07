"""User tool profiles: real CBOR and mocked OpenOS file transport."""
import unittest
from lupa.lua53 import LuaRuntime, LuaError
from test_database import MOCKS, ROOT


class ToolProfileTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        lib = (ROOT / 'usr/lib').as_posix()
        self.lua.execute(f'package.path="{lib}/?.lua;{lib}/?/init.lua;"..package.path')
        self.lua.execute(MOCKS)
        self.lua.execute("TOOLS=require('craft_tools');PATH=TOOLS.path")

    def test_require_is_lazy_and_profiles_roundtrip_with_copy_isolation(self):
        self.assertEqual(self.lua.execute("""
            assert(#handles==0);assert(TOOLS.set('t:hammer:12',100,2))
            local p=TOOLS.get('t:hammer:*');p.durability=1
            package.loaded.craft_tools=nil;local reloaded=require('craft_tools')
            local actual=reloaded.get({name='t:hammer',damage=40})
            return actual.durability,actual.durabilityPerUse,TOOLS.get('t:hammer').durability
        """), (100, 2, 100))

    def test_wear_is_per_operation_and_zero_wear_is_unlimited(self):
        self.assertEqual(self.lua.execute("""
            return TOOLS.usesLeft({damage=91},{durability=100,durabilityPerUse=3}),
                TOOLS.usesLeft({damage=100},{durability=100,durabilityPerUse=3}),
                TOOLS.usesLeft({damage=99},{durability=100,durabilityPerUse=0})==math.huge
        """), (3, 0, True))

    def test_invalid_profiles_are_rejected_without_writes(self):
        for durability, wear in ((0, 1), (-1, 1), (10, -1), (10, 11), (10, 0.5)):
            with self.subTest(durability=durability, wear=wear):
                self.assertEqual(self.lua.execute(f"local ok=TOOLS.set('t:hammer',{durability},{wear});return ok==nil,#handles"), (True, 0))

    def test_failed_save_preserves_active_profile_and_closes_handle(self):
        self.assertEqual(self.lua.execute("""
            assert(TOOLS.set('t:hammer',100,1));failWrite[PATH]=true
            local ok=TOOLS.set('t:hammer',200,2)
            return ok==nil,TOOLS.get('t:hammer').durability,handles[#handles].closed
        """), (True, 100, True))

    def test_remove_is_persisted(self):
        self.assertEqual(self.lua.execute("""
            assert(TOOLS.set('t:hammer',100,1));assert(TOOLS.remove('t:hammer'))
            TOOLS.reload();return TOOLS.get('t:hammer')==nil,next(TOOLS.list())==nil
        """), (True, True))

    def test_corrupt_profile_file_is_explicit_and_closed(self):
        self.lua.execute("files[PATH]='broken'")
        with self.assertRaisesRegex(LuaError, 'Cannot load tool profiles'):
            self.lua.execute("TOOLS.get('t:hammer')")
        self.assertTrue(self.lua.execute('return handles[#handles].closed'))
