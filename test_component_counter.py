"""Transparent, bounded controller component-call acceptance instrumentation."""
from pathlib import Path
import tempfile
import unittest

from lupa.lua53 import LuaRuntime
from build_machine_comparisons import prepare
from examples.mes.build_fixtures import build_native

ROOT = Path(__file__).resolve().parent


class ComponentCounterTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute('''
            local proxies={}
            component={type=function(address) return address=='a' and 'modem' or 'gpu' end}
            component.invoke=function(address,method,...)
                if method=='fail' then error('original failure',0) end
                return 'ok',nil,77
            end
            component.methods=function() return {send=true,fail=true,nested=true} end
            function component.proxy(address)
                if not proxies[address] then proxies[address]={address=address,
                  send=function(...) return component.invoke(address,'send',...) end,
                  fail=function() return component.invoke(address,'fail') end,
                  nested=function() return component.invoke('b','send') end} end
                return proxies[address]
            end
            component.list=function() local ids={'a','b'};local n=0;return function() n=n+1;return ids[n] end end
            EXISTING=component.proxy('a')
            require=function(name) assert(name=='component');return component end
        ''')
        self.lua.globals().COUNTER = self.lua.execute((ROOT / 'machine_component_counter.lua').read_text())

    def test_cached_proxy_identity_and_nil_returns_preserved_no_double_count(self):
        actual = self.lua.execute('''
            local same=EXISTING==component.proxy('a')
            local result=table.pack(EXISTING.send('x'))
            local s=COUNTER.snapshot()
            return same,result.n,result[1],result[2],result[3],s.total,s.byMethod['modem.send']
        ''')
        self.assertEqual(actual, (True, 3, 'ok', None, 77, 1, 1))

    def test_errors_restore_accounting_context_and_direct_invokes_count(self):
        actual = self.lua.execute('''
            local ok,err=pcall(EXISTING.fail)
            component.invoke('b','send')
            local s=COUNTER.snapshot()
            return ok,err,s.total,s.byType.modem,s.byType.gpu
        ''')
        self.assertEqual(actual, (False, 'original failure', 2, 1, 1))

    def test_native_style_callable_table_uses_public_invoke(self):
        actual = self.lua.execute('''
            local method=setmetatable({},{__call=function(_,...) return component.invoke('a','send',...) end})
            local result=table.pack(method('message'))
            local s=COUNTER.snapshot()
            return result.n,result[1],result[2],result[3],s.total,s.byMethod['modem.send']
        ''')
        self.assertEqual(actual, (3, 'ok', None, 77, 1, 1))

    def test_nested_distinct_method_and_snapshot_delta_are_counted(self):
        actual = self.lua.execute('''
            local before=COUNTER.snapshot()
            EXISTING.nested()
            local after=COUNTER.snapshot();local d=COUNTER.delta(before,after)
            before.byType.modem=100
            return d.scope,d.total,d.byType.modem,d.byType.gpu,d.byMethod['modem.nested'],d.byMethod['gpu.send']
        ''')
        self.assertEqual(actual, ('controller', 2, 1, 1, 1, 1))

    def test_comparison_preparation_installs_counter(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'observed'
            source = build_native(Path(directory) / 'source', 'torches16').parent
            prepare(source, destination, 'coordinated')
            self.assertEqual((destination / 'program/component-counter.lua').read_bytes(),
                             (ROOT / 'machine_component_counter.lua').read_bytes())
