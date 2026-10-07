import unittest
import test_stockkeeper


class StockkeeperUITests(unittest.TestCase):
    def setUp(self):
        test_stockkeeper.StockkeeperTests.setUp(self)
        self.lua.execute('''
            KEYS,READ_VALUES,VIEWPORTS={}, {},{}
            LISTENED,IGNORED=false,false
            package.preload.component=function() return {
                gpu={getResolution=function() return 80,25 end,set=function() end},
                transposer={getAllStacks=function() return {getAll=function() return STOCK end} end}
            } end
            package.preload.keyboard=function() return {keys={q=16,up=200,down=208}} end
            package.preload.term=function() return {clear=function() end} end
            package.preload.tty=function() return {
                getViewport=function() return 80,25,0,0 end,
                setViewport=function(...) VIEWPORTS[#VIEWPORTS+1]={...} end
            } end
            local e=require('event')
            e.listen=function(_,fn) LISTENED=true;INTERRUPT=fn end
            e.ignore=function() IGNORED=true end
            e.pull=function()
                local k=table.remove(KEYS,1);assert(k,'UI test exhausted keys');return 'key_down','keyboard',0,k
            end
            package.preload.qmenu=function() return {create=function()
                local m={options={}}
                function m:addOption(name,x,y,text)
                    local o={name=name}
                    function o:bind() return self end
                    function o:onActivate(fn) self.activate=fn;return self end
                    self.options[name]=o;self.selected=self.selected or name;return o
                end
                function m:setSelected(name) self.selected=name end
                function m:draw() end
                function m:handleEvent(key)
                    local o=self.options[key] or self.options[self.selected];if o then o.activate() end
                end
                function m:read() return table.remove(READ_VALUES,1) end
                return m
            end} end
            function seedUI()
                setupRule();listing[RDIR]={'Daily gears.rule'};listing[DIR]={'Gears.plan'}
            end
            function showUI() return require('craft_management_ui').show('stockkeeper',{storageSide=2,jobTimeout=90}) end
        ''')

    def test_listing_then_exit_does_not_open_rules_and_restores_ui(self):
        self.assertEqual(self.lua.execute('''
            directories[RDIR]=true;listing[RDIR]={'A.rule','B.rule'};KEYS={16}
            local code=showUI();return code,OPEN_CALLS,RUN_CALLS,LISTENED,IGNORED,#KEYS
        '''), (0, 0, 0, True, True, 0))
        self.assertEqual(self.lua.execute('return table.unpack(VIEWPORTS[#VIEWPORTS])'), (80, 25, 0, 0))

    def test_qmenu_create_saves_disabled_without_gui_callbacks(self):
        self.assertEqual(self.lua.execute('''
            assert(PLANS.save('Gears',PLAN));listing[DIR]={'Gears.plan'}
            READ_VALUES={'Daily gears','t:gear','64','10'}
            KEYS={'new','plan','item1','replacement','saved','ok',16}
            local code=showUI();local r=assert(KEEPER.load('Daily gears'))
            return code,r.quantity,r.interval,r.trigger,r.source.name,r.enabled,r.useExisting==nil,
                r.storageSide,r.jobTimeout,TIMER_CALLS,RUN_CALLS,#KEYS
        '''), (0, 64, 10, 'replacement', 'Gears', False, True, 2, 90, 0, 0, 0))

    def test_enabled_timer_survives_menu_exit_without_gui_cancellation_predicate(self):
        self.assertEqual(self.lua.execute('''
            seedUI();KEYS={'rule1','enable','ok',16,16};local code=showUI();fire(1)
            return code,KEEPER.status('Daily gears').enabled,RUN_CALLS,
                SENT_OPTIONS.shouldContinue==nil,SENT_OPTIONS.onMessage==nil,TIMERS[1]~=nil,IGNORED,#KEYS
        '''), (0, True, 1, True, True, True, True, 0))

    def test_menu_disable_retires_callback_next_tick(self):
        self.assertEqual(self.lua.execute('''
            seedUI();assert(KEEPER.enable('Daily gears',{countStock=COUNT}))
            KEYS={'rule1','disable','ok',16,16};local code=showUI()
            return code,KEEPER.load('Daily gears').enabled,fire(1)==false,RUN_CALLS,#KEYS
        '''), (0, False, True, 0, 0))

    def test_menu_resume_requires_acknowledgement_and_restores_timer(self):
        self.assertEqual(self.lua.execute('''
            seedUI();EXECUTION={status='unknown',success=false,mayHaveExecuted=true}
            KEEPER.check('Daily gears',{countStock=COUNT})
            KEYS={'rule1','enable','no',16,16};assert(showUI()==0)
            local paused=KEEPER.status('Daily gears').paused
            KEYS={'rule1','enable','yes','ok',16,16};local code=showUI()
            return paused,code,KEEPER.status('Daily gears').paused,TIMER_CALLS,RUN_CALLS,#KEYS
        '''), (True, 0, False, 1, 1, 0))

    def test_edit_interval_replaces_callback_and_deletion_retires_new_one(self):
        self.assertEqual(self.lua.execute('''
            seedUI();assert(KEEPER.enable('Daily gears',{countStock=COUNT}))
            READ_VALUES={'t:gear','48','2'}
            KEYS={'rule1','edit','plan','item1','replacement','saved','ok',16,16};assert(showUI()==0)
            local old=fire(1);local interval=TIMERS[2].interval
            KEYS={'rule1','delete','yes','ok',16};local code=showUI()
            return old==false,interval,code,fire(2)==false,files[RDIR..'Daily gears.rule']==nil,RUN_CALLS,#KEYS
        '''), (True, 2, 0, True, True, 0, 0))

    def test_manual_check_does_not_store_ui_lifetime_options(self):
        self.assertEqual(self.lua.execute('''
            seedUI();KEYS={'rule1','check','yes','ok','enable','ok',16,16}
            local code=showUI();fire(1)
            return code,RUN_CALLS,SENT_OPTIONS.shouldContinue==nil,SENT_OPTIONS.onMessage==nil,#KEYS
        '''), (0, 2, True, True, 0))
