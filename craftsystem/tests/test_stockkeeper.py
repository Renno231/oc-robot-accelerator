"""Native OpenOS timer rules; no private scheduler or timer-ID bookkeeping."""
import unittest
import test_kits


class StockkeeperTests(unittest.TestCase):
    def setUp(self):
        test_kits.KitTests.setUp(self)
        self.lua.execute('''
            TIMERS,HISTORY,TIMER_CALLS={}, {},0
            package.preload.event=function() return {
                timer=function(interval,fn,times)
                    if TIMER_FAIL then error('timer failed') end
                    TIMER_CALLS=TIMER_CALLS+1
                    local h={interval=interval,callback=fn,times=times}
                    TIMERS[TIMER_CALLS]=h;HISTORY[TIMER_CALLS]=h
                    return TIMER_CALLS
                end,
                cancel=function() error('Stockkeeper must use return-false cleanup') end
            } end
            function fire(id)
                local h=TIMERS[id];if not h then return end
                local result=h.callback()
                if result==false and TIMERS[id]==h then TIMERS[id]=nil end
                return result
            end
            KEEPER=require('stockkeeper');RDIR=KEEPER.directory
            RULE={item='t:gear:0',quantity=64,interval=10,trigger='replacement',
                source={kind='plan',name='Gears'}}
            CURRENT=0
            COUNT=function(item) assert(item=='t:gear');COUNT_CALLS=COUNT_CALLS+1;return CURRENT end
            function setupRule(name)
                assert(PLANS.save('Gears',PLAN));assert(KEEPER.save(name or 'Daily gears',RULE))
                OPEN_CALLS=0
            end
        ''')

    def test_require_list_are_headless_without_files_or_timers(self):
        self.assertEqual(self.lua.execute('''
            directories[RDIR]=true;listing[RDIR]={'Z.rule','A.rule','broken.rule','folder.rule/','other.plan'}
            io.open=function() error('must not open rule files') end
            return table.concat(KEEPER.list(),','),OPEN_CALLS,TIMER_CALLS,
                package.loaded.event==nil,package.loaded.component==nil,package.loaded.qmenu==nil
        '''), ('A,Z,broken', 0, 0, True, True, True))

    def test_one_file_per_rule_and_only_selected_load(self):
        self.assertEqual(self.lua.execute('''
            RULE.hook=function() end;setupRule();assert(KEEPER.save('Spare',RULE));OPEN_CALLS=0
            local r=assert(KEEPER.load('Daily gears'))
            return r.item,r.enabled,r.useExisting==nil,r.hook==nil,OPEN_CALLS,
                files[RDIR..'Spare.rule']~=nil,allClosed(),TIMER_CALLS
        '''), ('t:gear', False, True, True, 1, True, True, 0))

    def test_invalid_configs_do_not_open_or_start_timers(self):
        for change in ("RULE.item='ore:gear'", "RULE.item='t:gear:*'", "RULE.item='t:gear:'",
                       "RULE.item='minecraft:air:0'", 'RULE.quantity=-1', 'RULE.quantity=0/0',
                       'RULE.quantity=1.5', 'RULE.interval=0', 'RULE.interval=math.huge',
                       "RULE.trigger='all'", "RULE.source.kind='worker'", "RULE.source.name='../bad'",
                       'RULE.storageSide=6', 'RULE.useExisting=1', 'RULE.port=0', 'RULE.idleTimeout=0'):
            with self.subTest(change=change):
                self.setUp();self.lua.execute(change)
                self.assertEqual(self.lua.execute("local v,e=KEEPER.save('Bad',RULE);return v==nil,type(e),OPEN_CALLS,TIMER_CALLS"), (True, 'string', 0, 0))

    def test_replacement_waits_for_whole_increment_and_never_scales(self):
        self.assertEqual(self.lua.execute('''
            setupRule();CURRENT=61
            local a=KEEPER.check('Daily gears',{countStock=COUNT})
            CURRENT=60;local b=KEEPER.check('Daily gears',{countStock=COUNT})
            return a.status,a.increment,b.status,b.increment,RUN_CALLS,SENT.requestQuantity,SENT.tasks[1].qty_produced
        '''), ('skipped', 4, 'complete', 4, 1, 4, 4))

    def test_level_triggers_at_or_below_not_only_exact_equality(self):
        self.assertEqual(self.lua.execute('''
            RULE.trigger='level';RULE.quantity=8;setupRule();CURRENT=9
            local a=KEEPER.check('Daily gears',{countStock=COUNT})
            CURRENT=8;local b=KEEPER.check('Daily gears',{countStock=COUNT})
            CURRENT=3;local c=KEEPER.check('Daily gears',{countStock=COUNT})
            return a.status,b.status,c.status,RUN_CALLS
        '''), ('skipped', 'complete', 'complete', 2))

    def test_rounding_defines_increment_not_requested_minimum(self):
        self.assertEqual(self.lua.execute('''
            PLAN.requestQuantity=1;PLAN.tasks[1].qty_produced=2;PLAN.inventory_needed['t:raw']=2
            setupRule();CURRENT=63;local r=KEEPER.check('Daily gears',{countStock=COUNT})
            return r.status,r.increment,RUN_CALLS
        '''), ('skipped', 2, 0))

    def test_default_uses_saved_tasks_not_recipe_db_or_inventory_replanning(self):
        self.assertEqual(self.lua.execute('''
            setupRule();local r=KEEPER.check('Daily gears',{countStock=COUNT,accounting='refresh'})
            return r.status,SENT_OPTIONS.accounting,SENT.requestQuantity,SENT.tasks[1].recipe[9],package.loaded.recipes==nil
        '''), ('complete', 'saved', 4, 't:raw', True))

    def test_explicit_use_existing_refreshes_captured_choices_only(self):
        self.assertEqual(self.lua.execute('''
            local p=modern('t:gear');assert(PLANS.save('Gears',p))
            RULE.useExisting=true;assert(KEEPER.save('Reuse',RULE))
            STOCK={{name='t:part',size=8,damage=0,maxSize=64}}
            local r=KEEPER.check('Reuse',{inventory=inv()})
            return r.status,r.accounting,#SENT.tasks,SENT.inventory_needed['t:part'],
                SENT.requestQuantity,KEEPER.load('Reuse').useExisting,package.loaded.recipes==nil
        '''), ('complete', 'refresh', 1, 1, 1, True, True))

    def test_refreshed_merged_increment_accounts_for_shared_batch_rounding(self):
        self.assertEqual(self.lua.execute('''
            local b={roots={{node='root',quantity=1}},tools={},nodes={
                root={item='t:gear',useStock=true,recipeOutput=4,recipe={'t:raw'},deps={'raw'}},
                raw={item='t:raw',useStock=true}}}
            local p=assert(require('craft_blueprint').calculate(b,inv()))
            assert(KITS.save('Bundle',{executionMode='merged',entries={{binding='pinned',plan=p},{binding='pinned',plan=p}}}))
            RULE.source={kind='kit',name='Bundle'};RULE.useExisting=true;assert(KEEPER.save('Kit',RULE))
            CURRENT=60;local r=KEEPER.check('Kit',{countStock=COUNT,inventory=inv()})
            return r.status,r.increment,r.accounting,r.executionMode,r.completedEntries,
                SENT.requestOutputs['t:gear'],SENT.tasks[1].qty_produced,RUN_CALLS
        '''), ('complete', 4, 'refresh', 'merged', 2, 2, 4, 1))

    def test_reuse_small_deficit_waits_even_when_materials_are_missing(self):
        self.assertEqual(self.lua.execute('''
            local b={roots={{node='root',quantity=1}},tools={},nodes={
                root={item='t:gear',useStock=true,recipeOutput=4,recipe={'t:raw'},deps={'raw'}},
                raw={item='t:raw',useStock=true}}}
            local p=assert(require('craft_blueprint').calculate(b,inv()));assert(PLANS.save('Gears',p))
            RULE.useExisting=true;assert(KEEPER.save('Reuse',RULE));STOCK={};CURRENT=63
            local a=KEEPER.check('Reuse',{countStock=COUNT,inventory=inv()});CURRENT=60
            local c=KEEPER.check('Reuse',{countStock=COUNT,inventory=inv()})
            return a.status,a.increment,c.status,c.message:find('Missing allowed inputs')~=nil,RUN_CALLS
        '''), ('skipped', 4, 'failed', True, 0))

    def test_separate_reuse_root_only_kit_forecasts_and_refreshes_children_live(self):
        self.assertEqual(self.lua.execute('''
            local p=modern('t:gear');local k={entries={{binding='pinned',plan=p},{binding='pinned',plan=p}}}
            assert(KITS.save('Bundle',k));RULE.source={kind='kit',name='Bundle'};RULE.useExisting=true
            assert(KEEPER.save('Kit',RULE))
            local run=require('craft_client').runDetailed
            require('craft_client').runDetailed=function(p,o)
                local result=run(p,o);STOCK[#STOCK+1]={name='t:gear',damage=0,size=1,maxSize=64};return result
            end
            local tp={getAllStacks=function() return {getAll=function() return STOCK end} end}
            local r=KEEPER.check('Kit',{transposer=tp})
            return r.status,r.increment,r.accounting,r.executionMode,r.completedEntries,RUN_CALLS
        '''), ('complete', 2, 'refresh', 'separate', 2, 2))

    def test_separate_reuse_watched_dependency_requires_one_merged_forecast(self):
        self.assertEqual(self.lua.execute('''
            local b={roots={{node='root',quantity=1}},tools={},nodes={
                root={item='t:part',useStock=true,recipeOutput=4,recipe={'t:raw'},deps={'raw'}},
                raw={item='t:raw',useStock=true}}}
            local p=assert(require('craft_blueprint').calculate(b,inv()));local q=modern('t:case')
            assert(KITS.save('Bundle',{entries={{binding='pinned',plan=p},{binding='pinned',plan=q}}}))
            RULE.item='t:part';RULE.source={kind='kit',name='Bundle'};RULE.useExisting=true
            assert(KEEPER.save('Kit',RULE));local r=KEEPER.check('Kit',{inventory=inv()})
            return r.status,r.message:find('use merged mode')~=nil,RUN_CALLS
        '''), ('failed', True, 0))

    def test_fresh_inventory_read_each_tick_and_idle_high_stock_skips_source_read(self):
        self.assertEqual(self.lua.execute('''
            setupRule();local tp={getAllStacks=function(side)
                assert(side==2);COUNT_CALLS=COUNT_CALLS+1
                return {getAll=function() return {{name='t:gear',damage=0,size=CURRENT,maxSize=64}} end}
            end}
            CURRENT=64;local a=KEEPER.check('Daily gears',{transposer=tp,storageSide=2});OPEN_CALLS=0
            CURRENT=60;local b=KEEPER.check('Daily gears',{transposer=tp,storageSide=2})
            return a.status,b.status,b.stockCount,COUNT_CALLS,RUN_CALLS,OPEN_CALLS
        '''), ('skipped', 'complete', 60, 2, 1, 1))

    def test_native_repeating_timer_failure_keeps_listener_and_rechecks_stock(self):
        self.assertEqual(self.lua.execute('''
            setupRule();assert(KEEPER.enable('Daily gears',{countStock=COUNT}))
            EXECUTION={status='failed',success=false,message='missing material'}
            local a=fire(1);CURRENT=64;local b=fire(1)
            return TIMERS[1].interval,TIMERS[1].times==math.huge,a==nil,b==nil,
                KEEPER.status('Daily gears').enabled,COUNT_CALLS,RUN_CALLS,KEEPER.status('Daily gears').lastResult.status
        '''), (10, True, True, True, True, 2, 1, 'skipped'))

    def test_disable_updates_disk_memory_and_listener_returns_false_next_time(self):
        self.assertEqual(self.lua.execute('''
            setupRule();assert(KEEPER.enable('Daily gears',{countStock=COUNT}));assert(KEEPER.disable('Daily gears'))
            local before=TIMERS[1]~=nil;local returned=fire(1)
            return before,KEEPER.load('Daily gears').enabled,KEEPER.status('Daily gears').enabled,
                returned==false,TIMERS[1]==nil,RUN_CALLS
        '''), (True, False, False, True, True, 0))

    def test_interval_edit_and_disable_reenable_retire_stale_callbacks(self):
        self.assertEqual(self.lua.execute('''
            setupRule();assert(KEEPER.enable('Daily gears',{countStock=COUNT}))
            local r=assert(KEEPER.load('Daily gears'));r.interval=3;assert(KEEPER.save('Daily gears',r))
            local stale=fire(1);fire(2)
            assert(KEEPER.disable('Daily gears'));assert(KEEPER.enable('Daily gears'))
            local old=fire(2);fire(3)
            return stale==false,old==false,TIMERS[3].interval,TIMER_CALLS,RUN_CALLS
        '''), (True, True, 3, 3, 2))

    def test_delete_retires_listener_without_touching_source(self):
        self.assertEqual(self.lua.execute('''
            setupRule();assert(KEEPER.enable('Daily gears',{countStock=COUNT}));assert(KEEPER.remove('Daily gears'))
            return fire(1)==false,RUN_CALLS,PLANS.load('Gears')~=nil,files[RDIR..'Daily gears.rule']==nil
        '''), (True, 0, True, True))

    def test_unknown_persists_pause_and_only_explicit_resume_unblocks(self):
        self.assertEqual(self.lua.execute('''
            setupRule();assert(KEEPER.enable('Daily gears',{countStock=COUNT}))
            EXECUTION={status='unknown',success=false,message='lost reply',mayHaveExecuted=true}
            local retired=fire(1);local s=KEEPER.status('Daily gears');local enabled=KEEPER.enable('Daily gears')
            local checked=KEEPER.check('Daily gears');local restored=KEEPER.start()
            EXECUTION={status='complete',success=true};assert(KEEPER.resume('Daily gears'));fire(2)
            return retired==false,s.paused,s.enabled,enabled==nil,checked.status,restored.started,
                RUN_CALLS,KEEPER.load('Daily gears').paused==nil
        '''), (True, True, False, True, 'unknown', 0, 2, True))

    def test_unknown_hold_survives_module_reload_and_enable_cannot_bypass_it(self):
        self.assertEqual(self.lua.execute('''
            setupRule();EXECUTION={status='unknown',success=false,mayHaveExecuted=true}
            KEEPER.check('Daily gears',{countStock=COUNT})
            package.loaded.stockkeeper=nil;local reloaded=require('stockkeeper')
            local ok=reloaded.enable('Daily gears');local started=reloaded.start()
            return ok==nil,started.started,reloaded.status('Daily gears').paused,TIMER_CALLS,RUN_CALLS
        '''), (True, 0, True, 0, 1))

    def test_replacing_saved_config_after_restart_cannot_clear_unknown_hold(self):
        self.assertEqual(self.lua.execute('''
            setupRule();EXECUTION={status='unknown',success=false,mayHaveExecuted=true}
            KEEPER.check('Daily gears',{countStock=COUNT})
            package.loaded.stockkeeper=nil;local fresh=require('stockkeeper')
            RULE.enabled=true;assert(fresh.save('Daily gears',RULE))
            return fresh.load('Daily gears').paused,fresh.enable('Daily gears')==nil,TIMER_CALLS
        '''), (True, True, 0))

    def test_no_duplicate_enable_or_nested_crafts_while_events_are_pulled(self):
        self.assertEqual(self.lua.execute('''
            setupRule();assert(KEEPER.save('Other',RULE))
            assert(KEEPER.enable('Daily gears',{countStock=COUNT}));assert(KEEPER.enable('Daily gears'))
            assert(KEEPER.enable('Other',{countStock=COUNT}))
            require('craft_client').runDetailed=function()
                RUN_CALLS=RUN_CALLS+1;assert(KEEPER.status('Daily gears').busy)
                assert(fire(1)==nil);assert(fire(2)==nil)
                return {status='complete',success=true}
            end
            fire(1)
            return TIMER_CALLS,RUN_CALLS,COUNT_CALLS,TIMERS[1]~=nil,TIMERS[2]~=nil,KEEPER.status('Daily gears').busy
        '''), (2, 1, 1, True, True, False))

    def test_hooks_are_once_per_action_isolated_and_do_not_change_success(self):
        self.assertEqual(self.lua.execute('''
            setupRule();local hooks=0
            assert(KEEPER.enable('Daily gears',{countStock=COUNT,onSuccess=function(r)
                hooks=hooks+1;r.source.name='mutated';r.status='failed';error('hook broke')
            end}))
            fire(1);local r=KEEPER.status('Daily gears').lastResult;r.source.name='changed'
            return hooks,RUN_CALLS,KEEPER.status('Daily gears').lastResult.status,
                KEEPER.status('Daily gears').lastResult.source.name,r.hookError:find('hook broke')~=nil,TIMERS[1]~=nil
        '''), (1, 1, 'complete', 'Gears', True, True))

    def test_start_is_explicit_restores_only_enabled_rules_and_stop_persists_disable(self):
        self.assertEqual(self.lua.execute('''
            setupRule();RULE.enabled=true;assert(KEEPER.save('Enabled',RULE,{countStock=COUNT}))
            listing[RDIR]={'Daily gears.rule','Enabled.rule'}
            package.loaded.stockkeeper=nil;local fresh=require('stockkeeper')
            local s=fresh.status('Enabled');local started=fresh.start({countStock=COUNT});local again=fresh.start()
            assert(fresh.stop());fire(2)
            return s.enabled,s.configuredEnabled,started.started,again.alreadyRunning,TIMER_CALLS,
                fresh.load('Enabled').enabled,TIMERS[2]==nil,RUN_CALLS
        '''), (False, True, 1, 1, 2, False, True, 0))

    def test_kits_follow_execution_default_but_stock_reuse_requires_rule_opt_in(self):
        self.assertEqual(self.lua.execute('''
            setupRule();local k=sample();k.executionMode='merged';k.accounting='refresh'
            assert(KITS.save('Bundle',k));RULE.source={kind='kit',name='Bundle'}
            assert(KEEPER.save('Kit',RULE));CURRENT=57;local a=KEEPER.check('Kit',{countStock=COUNT})
            CURRENT=56;local b=KEEPER.check('Kit',{countStock=COUNT})
            return a.status,a.increment,b.status,b.executionMode,b.accounting,RUN_CALLS,SENT.requestOutputs['t:gear']
        '''), ('skipped', 8, 'complete', 'merged', 'saved', 1, 8))

    def test_net_increment_subtracts_watched_stock_consumed_by_another_component(self):
        self.assertEqual(self.lua.execute('''
            setupRule();local c={success=true,craftable=true,requestItem='t:case',requestQuantity=1,
                inventory_needed={['t:gear']=1},tasks={{item='t:case',recipeOutput=1,qty_produced=1,recipe={'t:gear'}}}}
            assert(KITS.save('Bundle',{executionMode='merged',entries={
                {binding='pinned',plan=PLAN},{binding='pinned',plan=c}}}))
            RULE.source={kind='kit',name='Bundle'};assert(KEEPER.save('Kit',RULE))
            CURRENT=61;local r=KEEPER.check('Kit',{countStock=COUNT})
            return r.status,r.increment,RUN_CALLS,SENT.requestOutputs['t:gear']
        '''), ('complete', 3, 1, 4))

    def test_zero_net_replenishment_rejected_before_submission(self):
        self.assertEqual(self.lua.execute('''
            PLAN.requestQuantity=1;PLAN.tasks[1].qty_produced=2
            setupRule();local c={success=true,craftable=true,requestItem='t:case',requestQuantity=1,
                inventory_needed={['t:gear']=2},tasks={{item='t:case',recipeOutput=1,qty_produced=1,
                    recipe={'t:gear','t:gear'}}}}
            assert(KITS.save('Bundle',{entries={{binding='pinned',plan=PLAN},{binding='pinned',plan=c}}}))
            RULE.source={kind='kit',name='Bundle'};assert(KEEPER.save('Kit',RULE))
            local r=KEEPER.check('Kit',{countStock=COUNT})
            return r.status,r.message:find('positive net')~=nil,RUN_CALLS
        '''), ('failed', True, 0))

    def test_watched_wearing_tool_is_rejected_but_zero_wear_can_replenish(self):
        self.assertEqual(self.lua.execute('''
            setupRule();local c={success=true,craftable=true,requestItem='t:case',requestQuantity=1,
                inventory_needed={['t:gear']=1},tools={['t:gear']={durability=10,durabilityPerUse=1}},
                tool_stock={['t:gear']={1}},tasks={{item='t:case',recipeOutput=1,qty_produced=1,
                    recipe={'t:gear'},tool_slots={[1]='t:gear'}}}}
            local k={entries={{binding='pinned',plan=PLAN},{binding='pinned',plan=c}}}
            assert(KITS.save('Bundle',k));RULE.source={kind='kit',name='Bundle'};assert(KEEPER.save('Kit',RULE))
            local a=KEEPER.check('Kit',{countStock=COUNT})
            c.tools['t:gear'].durabilityPerUse=0;assert(KITS.save('Bundle',k))
            local b=KEEPER.check('Kit',{countStock=COUNT})
            return a.status,a.message:find('wearing tool')~=nil,b.status,b.increment,RUN_CALLS
        '''), ('failed', True, 'complete', 4, 2))

    def test_selected_kit_resolves_only_its_references_once_and_freezes_them(self):
        self.assertEqual(self.lua.execute('''
            setupRule();assert(KITS.save('Bundle',{entries={{binding='live',planName='Gears'},
                {binding='live',planName='Gears'}}}))
            RULE.source={kind='kit',name='Bundle'};assert(KEEPER.save('Kit',RULE));OPEN_CALLS=0
            local run=KITS.run
            KITS.run=function(k,o)
                assert(type(k)=='table' and k.entries[1].binding=='pinned')
                local p=PLANS.prepare(PLAN);p.requestQuantity=2;assert(PLANS.save('Gears',p))
                return run(k,o)
            end
            local r=KEEPER.check('Kit',{countStock=COUNT})
            return r.status,r.increment,RUN_CALLS,SENT.requestQuantity,OPEN_CALLS
        '''), ('complete', 8, 2, 4, 3))

    def test_unknown_partial_kit_has_one_failure_hook_and_retires_whole_rule(self):
        self.assertEqual(self.lua.execute('''
            setupRule();assert(KITS.save('Bundle',sample()));RULE.source={kind='kit',name='Bundle'}
            assert(KEEPER.save('Kit',RULE));local hooks=0
            assert(KEEPER.enable('Kit',{countStock=COUNT,onFailure=function(r)
                hooks=hooks+1;assert(r.partial and r.completedEntries==1)
            end}))
            require('craft_client').runDetailed=function()
                RUN_CALLS=RUN_CALLS+1
                return {status=RUN_CALLS==1 and 'complete' or 'unknown',success=RUN_CALLS==1,mayHaveExecuted=true}
            end
            return fire(1)==false,KEEPER.status('Kit').paused,RUN_CALLS,hooks,KEEPER.load('Kit').paused
        '''), (True, True, 2, 1, True))

    def test_disable_while_stock_is_read_prevents_a_not_yet_submitted_job(self):
        self.assertEqual(self.lua.execute('''
            setupRule();assert(KEEPER.enable('Daily gears',{countStock=function()
                assert(KEEPER.disable('Daily gears'));return 0
            end}))
            return fire(1)==false,RUN_CALLS,KEEPER.status('Daily gears').lastResult.status
        '''), (True, 0, 'skipped'))

    def test_missing_source_bad_stock_count_and_timer_failure_are_reported(self):
        self.assertEqual(self.lua.execute('''
            setupRule();local a=KEEPER.check('Daily gears',{countStock=function() return -1 end})
            assert(PLANS.remove('Gears'));local b=KEEPER.check('Daily gears',{countStock=COUNT})
            TIMER_FAIL=true;local ok,err=KEEPER.enable('Daily gears',{countStock=COUNT})
            return a.status,b.status,ok==nil,err:find('timer failed')~=nil,
                KEEPER.status('Daily gears').enabled,KEEPER.load('Daily gears').enabled,RUN_CALLS
        '''), ('failed', 'failed', True, True, False, False, 0))

    def test_edit_write_failure_preserves_active_callback(self):
        self.assertEqual(self.lua.execute('''
            setupRule();assert(KEEPER.enable('Daily gears',{countStock=COUNT}))
            local r=KEEPER.load('Daily gears');r.interval=1;failOpen[RDIR..'Daily gears.rule']=true
            local saved=KEEPER.save('Daily gears',r);fire(1)
            return saved==nil,KEEPER.status('Daily gears').rule.interval,TIMER_CALLS,RUN_CALLS
        '''), (True, 10, 1, 1))

    def test_disable_write_failure_still_stops_checks_and_restore_does_not_restart_them(self):
        self.assertEqual(self.lua.execute('''
            setupRule();assert(KEEPER.enable('Daily gears',{countStock=COUNT}))
            failWrite[RDIR..'Daily gears.rule']=true
            local ok,err=KEEPER.disable('Daily gears')
            failWrite[RDIR..'Daily gears.rule']=nil
            files[RDIR..'Daily gears.rule']=require('serialization').serialize({item=RULE.item,quantity=64,
                interval=10,trigger='replacement',source=RULE.source,enabled=true})
            listing[RDIR]={'Daily gears.rule'};local restarted=KEEPER.start()
            return ok==nil,err:find('disabled in memory')~=nil,KEEPER.status('Daily gears').enabled,
                fire(1)==false,restarted.started,restarted.errors['Daily gears']~=nil,RUN_CALLS
        '''), (True, True, False, True, 0, True, 0))

    def test_unknown_during_disable_still_persists_hold(self):
        self.assertEqual(self.lua.execute('''
            setupRule();assert(KEEPER.enable('Daily gears',{countStock=COUNT}))
            require('craft_client').runDetailed=function()
                RUN_CALLS=RUN_CALLS+1;assert(KEEPER.disable('Daily gears'))
                return {status='unknown',success=false,mayHaveExecuted=true}
            end
            fire(1);return KEEPER.status('Daily gears').paused,KEEPER.load('Daily gears').paused,
                KEEPER.load('Daily gears').enabled,TIMERS[1]==nil,RUN_CALLS
        '''), (True, True, False, True, 1))

    def test_unknown_pause_write_failure_still_blocks_memory_and_reports_error(self):
        self.assertEqual(self.lua.execute('''
            setupRule();assert(KEEPER.enable('Daily gears',{countStock=COUNT}))
            failOpen[RDIR..'Daily gears.rule']=true
            EXECUTION={status='unknown',success=false,mayHaveExecuted=true};fire(1)
            local s=KEEPER.status('Daily gears');failOpen[RDIR..'Daily gears.rule']=nil
            listing[RDIR]={'Daily gears.rule'};local restarted=KEEPER.start()
            return s.paused,s.lastResult.persistenceError~=nil,TIMERS[1]==nil,RUN_CALLS,restarted.started,TIMER_CALLS
        '''), (True, True, True, 1, 0, 1))
