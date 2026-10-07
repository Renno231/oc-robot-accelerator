"""Hardware-free database regressions; requires the installed lupa.lua53."""
import pathlib
import unittest

from lupa.lua53 import LuaRuntime, LuaError

ROOT = pathlib.Path(__file__).resolve().parents[1]

MOCKS = r'''
os.sleep = function() end
checkArg = function(_, value, expected) assert(type(value) == expected) end
files, directories, listing, handles, messages = {}, {}, {}, {}, {}
failOpen, failWrite, failClose = {}, {}, {}
print = function(...)
    local args = {...}
    for i, v in ipairs(args) do args[i] = tostring(v) end
    messages[#messages+1] = table.concat(args, " ")
end
local filesystem = {}
function filesystem.concat(a, b) return a:gsub("/+$", "").."/"..b:gsub("^/+", "") end
function filesystem.exists(p) return files[p] ~= nil or directories[p] == true end
function filesystem.isDirectory(p) return directories[p] == true end
function filesystem.makeDirectory(p) directories[p] = true return true end
function filesystem.list(p)
    local i = 0
    return function() i = i + 1 return (listing[p] or {})[i] end
end
package.preload.filesystem = function() return filesystem end
package.preload.computer = function() return {uptime = function() return 0 end} end
package.preload.serialization = function()
    return {
        unserialize = function(s)
            local f, err = load("return "..s, "recipe", "t", {})
            if not f then return nil, err end
            local ok, value = pcall(f)
            if not ok then return nil, value end
            return value
        end,
        serialize = function(t)
            local entries = {}
            for k, v in pairs(t) do
                entries[#entries+1] = "["..string.format("%q", k).."]="..string.format("%q", v)
            end
            return "{"..table.concat(entries, ",").."}"
        end
    }
end
function mockOpen(path, mode)
    if failOpen[path] then return nil, "injected open failure" end
    local writing = mode and mode:match("w")
    if not writing and files[path] == nil then return nil, "missing file" end
    if writing then files[path] = "" end
    local h = {path = path, closed = false, pos = 1}
    handles[#handles+1] = h
    function h:read(n)
        if self.pos > #files[path] then return nil end
        local data = files[path]:sub(self.pos, n == math.huge and #files[path] or self.pos + n - 1)
        self.pos = self.pos + #data
        return data
    end
    function h:lines()
        return function()
            if self.pos > #files[path] then return nil end
            local last = files[path]:find("\n", self.pos, true)
            local line = files[path]:sub(self.pos, last and last-1 or -1)
            self.pos = last and last+1 or #files[path]+1
            return line
        end
    end
    function h:write(data)
        if failWrite[path] then return nil, "injected write failure" end
        files[path] = files[path]..data
        return self
    end
    function h:close()
        self.closed = true
        if failClose[path] then return nil, "injected close failure" end
        return true
    end
    return h
end
io.open = mockOpen
-- Only the OpenOS buffered archive transport is mocked. CBOR and LZSS are real.
package.preload.liblz16 = function() return {open = mockOpen} end
package.preload.shell = function()
    return {parse = function(...) return {...}, {} end}
end
'''


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        lib = (ROOT / "usr/lib").as_posix()
        self.lua.execute(f'package.path = "{lib}/?.lua;{lib}/?/init.lua;"..package.path')
        self.lua.execute(MOCKS)

    def run_script(self, name, *args):
        return self.lua.execute((ROOT / name).read_text(), *args)

    def assert_closed(self):
        self.assertTrue(self.lua.eval('(function() for _, h in ipairs(handles) do if not h.closed then return false end end return true end)()'))

    def seed_recipes(self, listing, contents):
        self.lua.globals().listing['/usr/lib/recipes'] = self.lua.table_from(listing)
        for name, data in contents.items():
            self.lua.globals().files['/usr/lib/recipes/' + name] = data

    def test_misc_two_namespaces_including_last(self):
        self.seed_recipes(['misc.dblz'], {'misc.dblz': 'alpha:one\t{[1]="minecraft:log:0",qty=2}\nbeta:two:3\t{[2]="alpha:one"}\n'})
        db = self.run_script('usr/lib/recipes/init.lua')
        self.assertEqual(db.getAll('alpha:one')[1]['qty'], 2)
        self.assertEqual(db.getAll('beta:two:3')[1][2], 'alpha:one')
        self.assertEqual(self.lua.eval('function(db) return type(db.__recipes.beta.two) end')(db), 'string')
        self.assert_closed()

    def test_interleaving_and_import_boundary_both_orders(self):
        for order in (['alpha.dblz', 'misc.dblz'], ['misc.dblz', 'alpha.dblz']):
            with self.subTest(order=order):
                self.setUp()
                self.seed_recipes(order, {
                    'alpha.dblz': 'alpha:one\t{[1]="a"}\n',
                    'misc.dblz': 'alpha:one\t{[1]="b"}\nbeta:two\t{[1]="c"}\nalpha:one\t{[1]="d"}\nbeta:empty\t{}\n'})
                db = self.run_script('usr/lib/recipes/init.lua')
                recipes = db.getAll('alpha:one')
                self.assertEqual(len(recipes), 3)
                self.assertEqual({recipes[i][1] for i in range(1, 4)}, {'a', 'b', 'd'})
                self.assertEqual(db.getAll('beta:two')[1][1], 'c')
                self.assert_closed()

    def test_recipe_load_errors_close_resources(self):
        for contents in ('bad line\n', 'alpha:one\t{bad=\n', 'alpha:one\tfalse\n'):
            with self.subTest(contents=contents):
                self.setUp()
                self.seed_recipes(['misc.dblz'], {'misc.dblz': contents})
                with self.assertRaisesRegex(LuaError, 'cannot import'):
                    self.run_script('usr/lib/recipes/init.lua').getAll('alpha:one')
                self.assert_closed()
        self.setUp()
        self.seed_recipes(['misc.dblz'], {})
        with self.assertRaisesRegex(LuaError, 'cannot open recipe database'):
            self.run_script('usr/lib/recipes/init.lua').getAll('alpha:one')

    def test_processing_roundtrip_and_decode_failure(self):
        db = self.run_script('usr/lib/recipes/init.lua')
        data = self.lua.eval('{qty=4, recipe={"minecraft:log:0"}}')
        self.assertTrue(db.registerProcessingRecipe('minecraft:coal:1', 'furnaceBulk', data))
        loaded = self.run_script('usr/lib/recipes/init.lua')
        recipe = loaded.getAll('minecraft:coal:1')[1]
        self.assertEqual(recipe['qty'], 4)
        self.assertEqual(recipe['machineType'], 'furnaceBulk')
        self.assertTrue(recipe['isProcessing'])
        self.assertEqual(recipe[1], 'minecraft:log:0')
        self.assert_closed()
        self.lua.execute(r'files["/usr/lib/recipes/process.cb"] = "\122"')
        with self.assertRaisesRegex(LuaError, 'cannot decode'):
            self.run_script('usr/lib/recipes/init.lua')
        self.assert_closed()

    def seed_builder(self):
        self.lua.globals().files['inputs/shaped.csv'] = 'id,shape,ingredients,output\n'
        self.lua.globals().files['/data/shapeless.csv'] = 'id,ingredients,output\n'
        self.lua.globals().files['ore.csv'] = ''

    def test_builder_omitted_optional_arguments_and_supplied_paths(self):
        self.seed_builder()
        self.run_script('usr/bin/build_database.lua', 'inputs/shaped.csv', '/data/shapeless.csv', 'ore.csv')
        self.assertIsNotNone(self.lua.globals().files['recipe_db/raw/misc.db'])
        self.assertIsNotNone(self.lua.globals().files['recipe_db/raw/oredict.db'])
        self.assertIsNone(self.lua.globals().files['recipe_db/raw/tool.db'])
        self.assert_closed()

    def test_builder_explicit_output_without_stacks(self):
        self.seed_builder()
        self.run_script('usr/bin/build_database.lua', 'inputs/shaped.csv', '/data/shapeless.csv', 'ore.csv', '', '/output')
        self.assertIsNotNone(self.lua.globals().files['/output/raw/misc.db'])
        self.assert_closed()

    def test_builder_optional_stacks_and_compression_paths(self):
        self.seed_builder()
        self.lua.globals().files['/data/shapeless.csv'] = 'id,ingredients,output\nalpha:tool,alpha:input,alpha:tool x2\n'
        self.lua.globals().files['stacks.csv'] = 'id,a,b,display,tooltip,c,class,d,e,stack,damage,f,enchant\nalpha:tool,,,Tool,tip,,ToolClass,,x,1,20,,3\n'
        self.lua.globals().listing['/target/raw'] = self.lua.table_from(['misc.db', 'oredict.db', 'tool.db'])
        self.run_script('usr/bin/build_database.lua', 'inputs/shaped.csv', '/data/shapeless.csv', 'ore.csv', 'stacks.csv', '/target')
        self.assertIn('alpha:tool', self.lua.globals().files['/target/raw/tool.db'])
        self.assertIn('alpha:tool', self.lua.globals().files['/target/compressed/misc.dblz'])
        self.assert_closed()

    def test_processing_open_and_write_failures(self):
        path = '/usr/lib/recipes/process.cb'
        self.lua.globals().files[path] = 'present'
        self.lua.globals().failOpen[path] = True
        with self.assertRaisesRegex(LuaError, 'cannot open'):
            self.run_script('usr/lib/recipes/init.lua')
        self.setUp()
        db = self.run_script('usr/lib/recipes/init.lua')
        self.lua.globals().failWrite[path] = True
        ok, error = db.registerProcessingRecipe('minecraft:coal:1', 'furnaceBulk', self.lua.eval('{qty=1, recipe={"log"}}'))
        self.assertFalse(ok)
        self.assertIn('write failure', error)
        self.assert_closed()

    def test_builder_missing_input_is_explicit(self):
        with self.assertRaisesRegex(LuaError, 'cannot open missing.csv'):
            self.run_script('usr/bin/build_database.lua', 'missing.csv', 'other.csv', 'ore.csv')
        self.assert_closed()

    def test_builder_write_failure_closes_all(self):
        self.seed_builder()
        self.lua.globals().failWrite['recipe_db/raw/oredict.db'] = True
        self.lua.globals().files['ore.csv'] = 'log,minecraft:log:0\n'
        with self.assertRaisesRegex(LuaError, 'cannot write'):
            self.run_script('usr/bin/build_database.lua', 'inputs/shaped.csv', '/data/shapeless.csv', 'ore.csv')
        self.assert_closed()

    def seed_compressor(self, source='in', target='out'):
        self.lua.globals().directories[source] = True
        self.lua.globals().directories[target] = True
        self.lua.globals().listing[source] = self.lua.table_from(['alpha.db', 'ignore.txt'])
        self.lua.globals().files['in/alpha.db'] = 'recipe data'

    def test_compressor_joins_with_or_without_trailing_slashes(self):
        for source, target in [('in', 'out'), ('in/', 'out/'), ('in/', 'out'), ('in', 'out/')]:
            with self.subTest(source=source, target=target):
                self.setUp()
                self.seed_compressor(source, target)
                self.run_script('usr/bin/compressdbs.lua', source, target)
                self.assertEqual(self.lua.globals().files['out/alpha.dblz'], 'recipe data')
                self.assert_closed()

    def test_compressor_open_write_and_close_failures(self):
        for failure, path in [('failOpen', 'in/alpha.db'), ('failOpen', 'out/alpha.dblz'), ('failWrite', 'out/alpha.dblz'), ('failClose', 'out/alpha.dblz')]:
            with self.subTest(failure=failure, path=path):
                self.setUp()
                self.seed_compressor()
                self.lua.globals()[failure][path] = True
                self.assertFalse(self.run_script('usr/bin/compressdbs.lua', 'in', 'out'))
                self.assertFalse(self.lua.eval('table.concat(messages, "\\n"):find("processed in", 1, true) ~= nil'))
                self.assert_closed()


if __name__ == '__main__':
    unittest.main()
