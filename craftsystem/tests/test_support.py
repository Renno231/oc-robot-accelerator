"""Hardware-free Lua 5.3 regression helpers. Requires Python package lupa."""
from pathlib import Path
import unittest
from lupa.lua53 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]


class LuaCase(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.module('item_identity', 'lib/item_identity.lua')
        self.module('craft_tool_rules', 'lib/craft_tool_rules.lua')
        self.module('craft_tool_budget', 'lib/craft_tool_budget.lua')
        self.module('craft_blueprint', 'lib/craft_blueprint.lua')
        self.module('craft_resources', 'lib/craft_resources.lua')
        self.module('craft_plan', 'lib/craft_plan.lua')
        self.module('cbor', 'lib/cbor.lua')
        self.module('mes_timing', 'lib/mes_timing.lua')
        self.module('mes_persist', 'lib/mes_persist.lua')
        # Legacy hardware fixtures use an in-memory store seam. Restart tests
        # replace this with the canonical store and its counted filesystem.
        self.lua.execute('''
          package.preload.store=function()
            local cbor=require('cbor');local files={}
            return {open=function(path)
              files[path]=files[path] or {};local rows=files[path]
              return {
                load=function() local out={};for k,v in pairs(rows) do out[k]=cbor.decode(v) end;return out end,
                put=function(_,k,v) rows[k]=cbor.encode(v) end,
                delete=function(_,k) rows[k]=nil end,
                flush=function() end,close=function() end}
            end}
          end
        ''')
        for name in ('craft_handoff', 'craft_preview', 'craft_edit', 'craft_receipts'):
            self.module(name, 'lib/' + name + '.lua')
        self.lua.execute("""
            print = function() end
            os.sleep = function() end
            function checkArg(n, value, ...)
                for _, expected in ipairs({...}) do
                    if type(value) == expected then return end
                end
                error('bad argument #' .. n)
            end
        """)

    def module(self, name, relative_path):
        source = (ROOT / "usr" / relative_path).read_text(encoding="utf-8")
        self.lua.globals().MODULE_SOURCE = source
        self.lua.execute("package.preload[MODULE_NAME] = assert(load(MODULE_SOURCE))".replace(
            "MODULE_NAME", repr(name)))

    def script(self, relative_path):
        self.lua.execute((ROOT / "usr" / relative_path).read_text(encoding="utf-8"))


class SyntaxTests(LuaCase):
    def test_project_compiles_on_lua53(self):
        compile_lua = self.lua.eval("function(s,n) local f,e=load(s,n); return f~=nil,e end")
        for path in sorted((ROOT / "usr").rglob("*.lua")) + [ROOT.parent / 'inv.lua']:
            with self.subTest(path=str(path)):
                ok, error = compile_lua(path.read_text(encoding="utf-8"), str(path))
                self.assertTrue(ok, error)
