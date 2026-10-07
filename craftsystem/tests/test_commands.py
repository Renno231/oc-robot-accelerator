import unittest
import test_kits
from test_database import ROOT


class CommandTests(unittest.TestCase):
    def setUp(self):
        test_kits.KitTests.setUp(self)
        self.lua.execute('''
            MESSAGES={};print=function(s) MESSAGES[#MESSAGES+1]=tostring(s) end
            package.preload.shell=function() return {parse=function(...)
                local args,opts={},{};local done=false
                for _,v in ipairs({...}) do
                    if not done and v=='--' then done=true
                    elseif not done and type(v)=='string' and v:sub(1,2)=='--' then
                        local k,val=v:match('^%-%-(.-)=(.*)$');opts[k or v:sub(3)]=val or true
                    else args[#args+1]=v end
                end
                return args,opts
            end} end
            COMMANDS=require('craft_commands')
        ''')

    def binary(self, name, args):
        self.lua.globals().BINARY_SOURCE = (ROOT / 'usr/bin' / (name + '.lua')).read_text(encoding='utf-8')
        self.lua.globals().BIN_ARGS = self.lua.table_from(args)
        result = self.lua.execute('return assert(load(BINARY_SOURCE))(table.unpack(BIN_ARGS))')
        return result[0] if isinstance(result, tuple) and result[1] is None else result

    def test_purpose_binaries_are_headless_and_independently_callable(self):
        self.assertEqual(self.binary('craftplan', ['list']), 0)
        self.assertEqual(self.binary('craftkit', ['list']), 0)
        self.assertEqual(self.binary('crafttools', ['list']), 0)
        self.assertEqual(self.lua.execute('return OPEN_CALLS,package.loaded.qmenu==nil,package.loaded.component==nil'), (0, True, True))

    def test_tool_binary_registers_and_removes_profile(self):
        self.assertEqual(self.binary('crafttools', ['set', 't:hammer', '--durability=10', '--wear=2']), 0)
        self.assertEqual(self.lua.execute("return require('craft_tools').get('t:hammer').durabilityPerUse"), 2)
        self.assertEqual(self.binary('crafttools', ['remove', 't:hammer']), 0)
        self.assertTrue(self.lua.execute("return require('craft_tools').get('t:hammer')==nil"))

    def test_preview_command_is_headless_and_never_runs(self):
        self.lua.execute("assert(PLANS.save('Gears',PLAN));OPEN_CALLS=0")
        self.assertEqual(self.binary('craftplan', ['preview', 'Gears']), 0)
        self.assertEqual(self.lua.execute("return OPEN_CALLS,RUN_CALLS,package.loaded.qmenu==nil"), (1, 0, True))

    def test_edit_command_requires_explicit_save_flag(self):
        self.lua.execute('''
            INV={countItemByName=function() return 64,{} end}
            local b={roots={{node='root',quantity=2}},tools={},nodes={
                root={item='t:gear',useStock=true,recipeOutput=1,recipe={[1]='t:raw'},deps={[1]='raw'}},
                raw={item='t:raw',useStock=true}}}
            PLAN=assert(PLANS.prepare(assert(require('craft_blueprint').calculate(b,INV))))
            assert(PLANS.save('Gears',PLAN));BEFORE=files['/usr/craftplans/Gears.plan']
            PLANS.inventory=function() return INV end
        ''')
        self.assertEqual(self.binary('craftplan', ['edit', 'Gears', '--node=root', '--stock=false']), 0)
        self.assertTrue(self.lua.execute("return files['/usr/craftplans/Gears.plan']==BEFORE"))
        self.assertEqual(self.binary('craftplan', ['edit', 'Gears', '--node=root', '--stock=false', '--save=false']), 0)
        self.assertTrue(self.lua.execute("return files['/usr/craftplans/Gears.plan']==BEFORE"))
        self.assertEqual(self.binary('craftplan', ['edit', 'Gears', '--node=root', '--stock=false', '--save', '--to=Draft']), 0)
        self.assertEqual(self.lua.execute("return assert(PLANS.load('Draft')).blueprint.nodes.root.useStock,files['/usr/craftplans/Gears.plan']==BEFORE,RUN_CALLS"), (False, True, 0))

    def test_receipt_command_uses_original_address_and_reports_uncertainty_code(self):
        self.lua.execute("""
            require('craft_client').query=function(a,id) QUERY_ADDRESS=a;QUERY_ID=id;return {status='not_found',success=false,message='no receipt'} end
        """)
        self.assertEqual(self.binary('craftplan', ['status', 'robot', 'job']), (3, 'no receipt'))
        self.assertEqual(self.lua.execute('return QUERY_ADDRESS,QUERY_ID,RUN_CALLS'), ('robot', 'job', 0))

    def test_conflicting_edit_kinds_are_rejected_before_file_access(self):
        self.assertEqual(self.binary('craftplan', ['edit', 'Gears', '--node=root', '--stock=false', '--recipe=1'])[0], 2)
        self.assertEqual(self.lua.execute('return OPEN_CALLS,RUN_CALLS'), (0, 0))

    def test_plan_binary_uses_numeric_domain_codes_not_just_process_success(self):
        self.lua.execute("assert(PLANS.save('Gears',PLAN))")
        for status, code in (('complete', 0), ('failed', 1), ('unknown', 3)):
            with self.subTest(status=status):
                self.lua.execute(f"EXECUTION={{status='{status}',success={'true' if code == 0 else 'false'},message='domain result'}}")
                result = self.binary('craftplan', ['run', 'Gears'])
                self.assertEqual(result[0] if isinstance(result, tuple) else result, code)

    def test_kit_commands_manage_individual_bindings_and_defaults(self):
        self.lua.execute('sample()')
        self.assertEqual(self.binary('craftkit', ['create', 'Computer', 'Gears', '--mode=merged']), 0)
        self.assertEqual(self.binary('craftkit', ['add', 'Computer', 'Spare', '--binding=pinned']), 0)
        self.assertEqual(self.lua.execute("local k=assert(KITS.load('Computer'));return k.executionMode,k.entries[1].binding,k.entries[2].binding"), ('merged', 'live', 'pinned'))
        self.assertEqual(self.binary('craftkit', ['bind', 'Computer', '1', 'pinned']), 0)
        self.assertEqual(self.binary('craftkit', ['set', 'Computer', '--mode=separate']), 0)
        self.assertEqual(self.binary('craftkit', ['remove-entry', 'Computer', '2']), 0)
        self.assertEqual(self.lua.execute("local k=assert(KITS.load('Computer'));return #k.entries,k.executionMode,k.entries[1].binding"), (1, 'separate', 'pinned'))

    def test_invalid_flags_paths_and_commands_fail_before_submission(self):
        for args in (['run', 'Gears', '--accounting=auto'], ['run', 'Gears', '--storage-side=10'],
                     ['create', '../bad', 'Gears'], ['bind', 'missing', '0', 'pinned']):
            with self.subTest(args=args):
                result = self.binary('craftkit', args)
                self.assertEqual(result[0], 2)
        self.assertEqual(self.lua.execute('return RUN_CALLS'), 0)

    def test_headless_creation_captures_choices_without_qmenu(self):
        self.lua.execute('''
            package.preload.craftingv4_4=nil
            package.preload.recipes=function() return {getAll=function(name)
                if name=='t:target' then return {{'t:raw',qty=4}} end
                if name=='t:raw' then return {{'t:target'}} end
            end} end
            package.preload.oredict=function() return {get=function() return {} end} end
            TP={getAllStacks=function() return {getAll=function() return STOCK end} end}
        ''')
        self.assertEqual(self.lua.execute('''
            local p,e=COMMANDS.createPlan('Headless','t:target',5,{transposer=TP,toolProfiles={},leaf='t:raw'})
            assert(p,e);return p.requestQuantity,p.tasks[1].qty_produced,p.blueprint.nodes['t:raw'].recipe==nil,
                PLANS.load('Headless')~=nil,package.loaded.qmenu==nil
        '''), (5, 8, True, True, True))

    def test_creation_selection_cancellation_does_not_write_or_run(self):
        self.lua.execute('''
            package.preload.craftingv4_4=nil
            package.preload.recipes=function() return {getAll=function(name) if name=='t:target' then return {{'t:raw'}} end end} end
            package.preload.oredict=function() return {get=function() return {} end} end
            TP={getAllStacks=function() return {getAll=function() return STOCK end} end}
        ''')
        self.assertEqual(self.lua.execute('''
            local p,e=COMMANDS.createPlan('Cancelled','t:target',1,{transposer=TP,toolProfiles={}},
                function() error('cancelled choice') end)
            return p==nil,e:find('cancelled')~=nil,files['/usr/craftplans/Cancelled.plan']==nil,RUN_CALLS
        '''), (True, True, True, 0))
