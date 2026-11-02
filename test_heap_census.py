"""Host heap census: who holds a machine's live Lua memory, on a fake OC kernel."""
import json
from pathlib import Path
import unittest
from lupa.lua53 import LuaRuntime

CHUNK = Path(__file__).with_name('src') / 'main/resources/heap_census.lua'

# A suspended kernel coroutine whose frame holds machine.lua's `sandbox` local,
# with OpenOS's package.loaded inside it.
KERNEL = r'''
local function machine()
  local sandbox = {}
  sandbox._G = sandbox
  local loaded = {_G = sandbox}
  sandbox.package = {loaded = loaded}
  loaded.package = sandbox.package
  -- OC's computer table (whose event list OpenOS fills) sorts before the application that listens.
  loaded.computer = load('local handlers = {} local c = {} ' ..
                         'function c.listen(f) handlers[#handlers + 1] = f end return c', '=machine')()
  loaded.warehouse = load([[
    local computer = ...
    local catalogue = {}
    for i = 1, 100 do catalogue['item' .. i] = string.rep('x', 100) .. i end
    local big = {config = {name = 'big'}}
    function big.count() return #catalogue end
    local jobs = {}
    for i = 1, 3 do jobs[i] = {id = i, log = string.rep('l', 1099) .. i} end
    local pending = {}
    for i = 1, 5 do pending[i] = string.rep('p', 199) .. i end
    local function submit() return pending end
    function big.run() return submit(), jobs end
    computer.listen(function() return big.count() + #catalogue end)
    return big]], '=/usr/lib/warehouse.lua')(loaded.computer)
  loaded.small = {big = loaded.warehouse, list = {}}
  for i = 1, 3 do loaded.small.list[i] = i end
  -- Loaded from its own file, as require does.
  local code = load('local code = {} function code.make() return function() return 1 end end ' ..
                    'code.inner = code.make() return code', '=/usr/lib/code.lua')()
  loaded.code = code
  sandbox.SHARED = string.rep('g', 500)
  coroutine.yield()
end
local co = coroutine.create(machine)
assert(coroutine.resume(co))
local i, name, code = 1
repeat name, code = debug.getlocal(co, 1, i); i = i + 1 until name == 'code'
return co, #string.dump(code.make)
'''


def census(scale=1):
    lua = LuaRuntime(unpack_returned_tuples=True)
    kernel, make = lua.execute(KERNEL)
    run = lua.execute("return assert(load(..., '=heapcensus'))", CHUNK.read_text())
    return json.loads(run(kernel, scale)), make


def module(result, name):
    return next(m for m in result['modules'] if m['name'] == name)


def child(mod, name):
    return next((c for c in mod['children'] if c['name'] == name), None)


class HeapCensusTests(unittest.TestCase):
    def test_module_locals_are_found_through_function_upvalues(self):
        result, _ = census()
        catalogue = child(module(result, 'warehouse'), 'local catalogue')
        self.assertEqual(catalogue['entries'], 100)
        # 100 strings of 101-103 bytes plus their keys, each with a 25-byte string header.
        self.assertGreater(catalogue['bytes'], 100 * (24 + 102))
        self.assertEqual(len(catalogue['top']), 10)
        self.assertTrue(all(t['key'].startswith('item') for t in catalogue['top']))
        self.assertIsNotNone(child(module(result, 'warehouse'), 'config'))

    def test_entries_are_split_into_fields_and_function_locals_into_upvalues(self):
        result, _ = census()
        warehouse = module(result, 'warehouse')
        job = child(warehouse, 'local jobs')['top'][0]
        self.assertEqual(job['fields'][0]['key'], 'log')
        self.assertEqual(job['fields'][0]['bytes'], 25 + 1100 + 25 + 3)
        submit = child(warehouse, 'local submit')
        self.assertEqual(submit['top'][0]['key'], '^pending')
        self.assertEqual(len(submit['top'][0]['fields']), 5)

    def test_applications_claim_their_data_before_openos_modules(self):
        result, _ = census()
        self.assertEqual(result['modules'][0]['name'], 'warehouse')
        handlers = child(module(result, 'computer'), 'local handlers')
        self.assertLess(handlers['bytes'], 1000)

    def test_a_machine_before_openos_boots_reports_that(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        kernel = lua.execute('local co = coroutine.create(function() local sandbox = {} coroutine.yield() end) '
                             'coroutine.resume(co) return co')
        run = lua.execute("return assert(load(..., '=heapcensus'))", CHUNK.read_text())
        self.assertEqual(json.loads(run(kernel, 1)), {'booted': False})

    def test_a_module_does_not_absorb_another_module(self):
        result, _ = census()
        small = module(result, 'small')
        self.assertIsNone(child(small, 'big'))
        self.assertLess(small['bytes'], 1000)
        # Lua's rehash rule: three array keys take a four-slot array part.
        self.assertEqual(child(small, 'list')['bytes'], 56 + 4 * 16)

    def test_code_counts_a_nested_function_once_inside_its_parent(self):
        result, make = census()
        # make's dump already holds inner's prototype; each adds only its 32-byte closure.
        self.assertEqual(module(result, 'code')['codeBytes'], make + 2 * 32)

    def test_code_is_also_totalled_by_the_file_it_came_from(self):
        result, make = census()
        sources = {s['source']: s['bytes'] for s in result['codeBySource']}
        self.assertEqual(sources['=/usr/lib/code.lua'], make)
        # The warehouse's listener is first reached through computer's handlers, so
        # computer's code counts it; by file it is the warehouse's.
        self.assertGreater(module(result, 'computer')['codeBytes'], sources['=machine'] + 64)
        self.assertGreater(sources['=/usr/lib/warehouse.lua'], module(result, 'warehouse')['codeBytes'] - 4 * 40)

    def test_globals_kernel_and_scale(self):
        result, _ = census()
        self.assertGreaterEqual(result['globalsBytes'], 500)
        self.assertGreater(result['kernelBytes'], 0)
        self.assertEqual(result['lua'], 'Lua 5.3')
        total = result['globalsBytes'] + result['kernelBytes'] + sum(m['bytes'] for m in result['modules'])
        self.assertEqual(result['walkedBytes'], total)
        halved, _ = census(scale=2)
        self.assertAlmostEqual(halved['walkedBytes'], total / 2, delta=len(result['modules']) * 30 + 10)


if __name__ == '__main__':
    unittest.main()
