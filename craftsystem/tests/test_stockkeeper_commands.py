import unittest
import test_commands
import test_stockkeeper


class StockkeeperCommandTests(unittest.TestCase):
    binary = test_commands.CommandTests.binary

    def setUp(self):
        test_stockkeeper.StockkeeperTests.setUp(self)
        self.lua.execute('''
            MESSAGES={};print=function(s) MESSAGES[#MESSAGES+1]=tostring(s) end
            package.preload.shell=function() return {parse=function(...)
                local args,flags={},{}
                for _,v in ipairs({...}) do
                    if v:sub(1,2)=='--' then
                        local k,val=v:match('^%-%-(.-)=(.*)$');flags[k or v:sub(3)]=val or true
                    else args[#args+1]=v end
                end
                return args,flags
            end} end
        ''')

    def create(self):
        return self.binary('stockkeeper', ['create', 'Daily gears', '--plan=Gears', '--item=t:gear',
                                         '--quantity=64', '--interval=10'])

    def test_standalone_list_is_directory_only_headless(self):
        self.lua.execute("directories[RDIR]=true;listing[RDIR]={'A.rule','B.rule'}")
        self.assertEqual(self.binary('stockkeeper', ['list']), 0)
        self.assertEqual(self.lua.execute('return table.concat(MESSAGES,","),OPEN_CALLS,TIMER_CALLS,package.loaded.component==nil,package.loaded.qmenu==nil'), ('A,B', 0, 0, True, True))

    def test_create_set_enable_disable_use_same_library(self):
        self.assertEqual(self.create(), 0)
        self.assertEqual(self.lua.execute("return KEEPER.load('Daily gears').enabled,TIMER_CALLS"), (False, 0))
        self.assertEqual(self.binary('stockkeeper', ['set', 'Daily gears', '--trigger=level', '--quantity=8', '--use-existing=true']), 0)
        self.assertEqual(self.binary('stockkeeper', ['set', 'Daily gears', '--use-existing=false']), 0)
        self.assertEqual(self.binary('stockkeeper', ['enable', 'Daily gears']), 0)
        self.assertEqual(self.binary('stockkeeper', ['disable', 'Daily gears']), 0)
        self.assertEqual(self.lua.execute("local r=KEEPER.load('Daily gears');return r.trigger,r.quantity,r.useExisting==nil,r.enabled,fire(1)==false"), ('level', 8, True, False, True))

    def test_start_is_idempotent_even_with_options_and_does_not_open_sources(self):
        self.create()
        self.lua.execute("local r=KEEPER.load('Daily gears');r.enabled=true;files[RDIR..'Daily gears.rule']=require('serialization').serialize(r);listing[RDIR]={'Daily gears.rule'};OPEN_CALLS=0")
        self.assertEqual(self.binary('stockkeeper', ['start', '--storage-side=2']), 0)
        self.assertEqual(self.binary('stockkeeper', ['start', '--storage-side=2']), 0)
        self.assertEqual(self.lua.execute('return TIMER_CALLS,RUN_CALLS,package.loaded.craft_client==nil'), (1, 0, True))
        self.assertEqual(self.binary('stockkeeper', ['stop']), 0)
        self.assertTrue(self.lua.execute("return KEEPER.load('Daily gears').enabled==false and fire(1)==false"))

    def test_headless_check_returns_domain_codes_and_resume_is_explicit(self):
        self.lua.execute('''
            setupRule();package.preload.component=function() return {transposer={getAllStacks=function()
                return {getAll=function() return STOCK end} end}} end
        ''')
        self.assertEqual(self.binary('stockkeeper', ['check', 'Daily gears']), 0)
        for status, code in (('failed', 1), ('unknown', 3)):
            self.lua.execute(f"EXECUTION={{status='{status}',success=false,message='job result'}}")
            result = self.binary('stockkeeper', ['check', 'Daily gears'])
            self.assertEqual(result[0], code)
        self.assertEqual(self.binary('stockkeeper', ['enable', 'Daily gears'])[0], 2)
        self.assertEqual(self.binary('stockkeeper', ['resume', 'Daily gears']), 0)
        self.assertEqual(self.lua.execute("return KEEPER.status('Daily gears').paused,TIMER_CALLS"), (False, 1))

    def test_bad_flags_sources_and_labels_fail_without_timers_or_network(self):
        for args in (['create', '../bad', '--plan=Gears', '--item=t:gear', '--quantity=64'],
                     ['create', 'Bad', '--plan=Gears', '--kit=Bundle', '--item=t:gear', '--quantity=64'],
                     ['create', 'Bad', '--plan=Gears', '--item=t:gear', '--quantity=64', '--interval=0'],
                     ['create', 'Bad', '--plan=Gears', '--item=t:gear', '--quantity=64', '--trigger=any'],
                     ['create', 'Bad', '--plan=Gears', '--item=t:gear', '--quantity=64', '--use-existing=auto'],
                     ['create', 'Bad', '--plan=Gears', '--item=t:gear', '--quantity=64', '--accounting=refresh']):
            with self.subTest(args=args):
                self.assertEqual(self.binary('stockkeeper', args)[0], 2)
        self.assertEqual(self.lua.execute('return TIMER_CALLS,RUN_CALLS'), (0, 0))
