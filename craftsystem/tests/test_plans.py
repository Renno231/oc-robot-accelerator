"""Labelled fixed-plan storage and headless automation regressions."""
import unittest
from lupa.lua53 import LuaRuntime
from test_database import MOCKS, ROOT


class SavedPlanTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        lib = (ROOT / 'usr/lib').as_posix()
        self.lua.execute(f'package.path="{lib}/?.lua;{lib}/?/init.lua;"..package.path')
        self.lua.execute(MOCKS)
        self.lua.execute(r'''
            local ser=require('serialization')
            local function encode(v)
                if type(v)=='string' then return string.format('%q',v) end
                if type(v)=='number' or type(v)=='boolean' then return tostring(v) end
                assert(type(v)=='table','unserializable value')
                local entries={}
                for k,val in pairs(v) do entries[#entries+1]='['..encode(k)..']='..encode(val) end
                return '{'..table.concat(entries,',')..'}'
            end
            ser.serialize=encode
            LIST_CALLS,OPEN_CALLS,RUN_CALLS,COUNT_CALLS=0,0,0,0
            local fs=require('filesystem');local list=fs.list
            fs.list=function(...) LIST_CALLS=LIST_CALLS+1;return list(...) end
            local open=io.open
            io.open=function(...) OPEN_CALLS=OPEN_CALLS+1;return open(...) end
            package.preload.component=function() error('unexpected component dependency') end
            package.preload.qmenu=function() error('unexpected UI dependency') end
            package.preload.robinv=function() error('unexpected robot dependency') end
            package.preload.craftingv4_4=function() error('unexpected planner dependency') end
            EXECUTION={status='complete',success=true,message='done',mayHaveExecuted=true}
            package.preload.craft_client=function() return {runDetailed=function(p,o)
                RUN_CALLS=RUN_CALLS+1;SENT=p;SENT_OPTIONS=o
                if RUN_THROW then error('network creation failed') end
                return EXECUTION
            end} end
            PLANS=require('craft_plans');DIR=PLANS.directory
            PLAN={success=true,craftable=true,requestItem='t:gear:0',requestQuantity=4,
                inventory_needed={['t:raw']=2},tasks={{item='t:gear:0',recipeOutput=2,qty_produced=4,
                recipe={[1]='t:raw',[9]='t:raw'}}}}
            function seed(name)
                assert(PLANS.save(name or 'Gears',PLAN))
                OPEN_CALLS=0
            end
            function allClosed() for _,h in ipairs(handles) do if not h.closed then return false end end;return true end
        ''')

    def test_require_and_listing_are_headless_and_never_open_plan_files(self):
        self.assertEqual(self.lua.execute('return OPEN_CALLS,RUN_CALLS,package.loaded.component==nil,package.loaded.craft_client==nil'), (0, 0, True, True))
        self.assertEqual(self.lua.execute('return #PLANS.list(),LIST_CALLS,OPEN_CALLS'), (0, 0, 0))
        self.assertEqual(self.lua.execute("""
            directories[DIR]=true
            listing[DIR]={'Z gears.plan','A gears.plan','corrupt.plan','readme.txt','directory.plan/','.plan'}
            io.open=function() error('listing must not open any plan') end
            local names=assert(PLANS.list())
            return table.concat(names,','),LIST_CALLS,RUN_CALLS
        """), ('A gears,Z gears,corrupt', 1, 0))

    def test_listing_failure_is_explicit(self):
        self.assertEqual(self.lua.execute("""
            directories[DIR]=true;require('filesystem').list=function() return nil,'list failure' end
            local names,err=PLANS.list();return names==nil,err:find('list failure')~=nil,OPEN_CALLS
        """), (True, True, 0))

    def test_each_label_has_its_own_file_and_selected_load_opens_only_one(self):
        self.assertEqual(self.lua.execute("""
            assert(PLANS.save('Daily gears',PLAN));PLAN.requestQuantity=2
            assert(PLANS.save('Spare gears',PLAN));OPEN_CALLS=0
            local p=assert(PLANS.load('Daily gears'))
            return p.requestQuantity,p.tasks[1].recipe[9],files['/usr/craftplans/Daily gears.plan']~=nil,
                files['/usr/craftplans/Spare gears.plan']~=nil,OPEN_CALLS,allClosed()
        """), (4, 't:raw', True, True, 1, True))

    def test_saving_to_existing_directory_does_not_attempt_to_recreate_it(self):
        self.assertEqual(self.lua.execute("""
            seed();require('filesystem').makeDirectory=function() error('already exists') end
            local saved=PLANS.save('Another batch',PLAN);return saved,allClosed()
        """), (True, True))

    def test_runtime_fields_and_callbacks_are_not_persisted_and_input_is_not_mutated(self):
        self.assertEqual(self.lua.execute("""
            PLAN.onSuccess=function() end;PLAN.extra={self=PLAN}
            PLAN.coroutine=coroutine.create(function() end);coroutine.resume(PLAN.coroutine)
            seed();local p=assert(PLANS.load('Gears'))
            return p.onSuccess==nil,p.extra==nil,p.coroutine==nil,p.yield_data==nil,
                PLAN.onSuccess~=nil,PLAN.extra.self==PLAN,allClosed()
        """), (True, True, True, True, True, True, True))

    def test_legacy_bare_plan_file_loads_without_recalculation(self):
        self.assertEqual(self.lua.execute("""
            files['/usr/craftplans/legacy.plan']=require('serialization').serialize(PLAN)
            local p=assert(PLANS.load('legacy'));return p.requestQuantity,p.success,p.craftable,OPEN_CALLS
        """), (4, True, True, 1))

    def test_path_traversal_blank_and_control_labels_are_rejected_before_open(self):
        for name in ('../bad', 'a/b', 'a\\b', '', '  ', '.', '..', 'a\nb', 'x' * 121):
            with self.subTest(name=name):
                self.lua.globals().NAME = name
                self.assertEqual(self.lua.execute('local saved=PLANS.save(NAME,PLAN);local p=PLANS.load(NAME);return saved==nil,p==nil,OPEN_CALLS'), (True, True, 0))

    def test_incomplete_or_invalid_batches_are_rejected_before_save_or_network(self):
        changes = ('PLAN.success=false', 'PLAN.craftable=false', 'PLAN.yield_data={}',
                   'PLAN.coroutine=coroutine.create(function() coroutine.yield() end)',
                   'PLAN.tasks[1].machineType="furnace"', 'PLAN.tasks[1].recipeOutput=0',
                   'PLAN.tasks={}', 'PLAN.requestQuantity=0', 'PLAN.tasks[1].recipe[1]=function() end')
        for change in changes:
            with self.subTest(change=change):
                self.setUp()
                self.lua.execute(change)
                self.assertEqual(self.lua.execute("""
                    local saved=PLANS.save('Bad',PLAN);local r=PLANS.run(PLAN)
                    return saved==nil,r.status,OPEN_CALLS,RUN_CALLS
                """), (True, 'failed', 0, 0))

    def test_load_and_save_failures_close_handles(self):
        for operation in ('load', 'save'):
            for failure in ('open', 'read', 'write', 'close'):
                if operation == 'load' and failure == 'write' or operation == 'save' and failure == 'read':
                    continue
                with self.subTest(operation=operation, failure=failure):
                    self.setUp()
                    self.lua.execute('seed();PATH="/usr/craftplans/Gears.plan"')
                    if failure == 'read':
                        self.lua.execute("local open=io.open;io.open=function(...) local h,e=open(...);if h then h.read=function() return nil,'read failure' end end;return h,e end")
                    else:
                        self.lua.execute({'open': 'failOpen', 'write': 'failWrite', 'close': 'failClose'}[failure] + '[PATH]=true')
                    self.assertEqual(self.lua.execute(f"local value,err=PLANS.{operation}('Gears'{',PLAN' if operation == 'save' else ''});return value==nil,type(err),allClosed()"), (True, 'string', True))

    def test_directory_and_serialization_failure_do_not_open_or_truncate_files(self):
        for failure in ('directory', 'serialization'):
            with self.subTest(failure=failure):
                self.setUp()
                if failure == 'directory':
                    self.lua.execute("require('filesystem').makeDirectory=function() return nil,'directory failure' end")
                else:
                    self.lua.execute("require('serialization').serialize=function() error('serialization failure') end")
                self.assertEqual(self.lua.execute("local saved,err=PLANS.save('Gears',PLAN);return saved==nil,err:find('failure')~=nil,OPEN_CALLS"), (True, True, 0))

    def test_corrupt_or_missing_file_fails_without_network_and_calls_failure_once(self):
        for data in (None, 'broken', '42', '{requestItem="t:gear",requestQuantity=4}'):
            with self.subTest(data=data):
                self.setUp()
                self.lua.globals().files['/usr/craftplans/Bad.plan'] = data
                self.assertEqual(self.lua.execute("""
                    local calls=0;local r=PLANS.run('Bad',{onFailure=function(v) calls=calls+1;assert(v.status=='failed') end})
                    return r.status,calls,RUN_CALLS,OPEN_CALLS,allClosed()
                """), ('failed', 1, 0, 1, True))

    def test_run_saved_batch_does_not_replan_scale_export_or_check_stock_by_default(self):
        self.assertEqual(self.lua.execute("""
            seed();local calls=0
            local r=PLANS.run('Gears',{countStock=function() error('unexpected stock check') end,
                onSuccess=function(v) calls=calls+1;assert(v.name=='Gears' and v.quantity==4) end})
            return r.status,r.success,calls,RUN_CALLS,OPEN_CALLS,SENT.requestQuantity,SENT.tasks[1].qty_produced,SENT.recipe==nil
        """), ('complete', True, 1, 1, 1, 4, 4, True))

    def test_threshold_skip_invokes_only_skip_hook_without_network(self):
        for stock in (64, 100):
            with self.subTest(stock=stock):
                self.lua.globals().STOCK = stock
                self.assertEqual(self.lua.execute("""
                    local skipped=0;local r=PLANS.run(PLAN,{stockAtLeast=64,
                        countStock=function(item) assert(item=='t:gear:0');return STOCK end,
                        onSkip=function(v) skipped=skipped+1;assert(v.stockCount==STOCK) end,
                        onSuccess=function() error('wrong hook') end,onFailure=function() error('wrong hook') end})
                    return r.status,r.success,skipped,RUN_CALLS,r.hookError==nil
                """), ('skipped', False, 1, 0, True))

    def test_below_threshold_executes_entire_saved_batch_and_passes_client_options(self):
        self.assertEqual(self.lua.execute("""
            local r=PLANS.run(PLAN,{stockAtLeast=64,countStock=function() return 63 end,
                jobTimeout=90,idleTimeout=10,onMessage=function() end})
            return r.status,r.stockCount,SENT.requestQuantity,SENT.tasks[1].qty_produced,
                SENT_OPTIONS.jobTimeout,SENT_OPTIONS.idleTimeout,type(SENT_OPTIONS.onMessage),OPEN_CALLS
        """), ('complete', 63, 4, 4, 90, 10, 'function', 0))

    def test_default_stock_check_uses_fresh_inventory_and_zero_metadata_identity(self):
        self.assertEqual(self.lua.execute("""
            local proxy={getAllStacks=function(side)
                assert(side==2);COUNT_CALLS=COUNT_CALLS+1
                return {getAll=function() return {{name='t:gear',damage=0,size=64,maxSize=64}} end}
            end}
            local r=PLANS.run(PLAN,{stockAtLeast=64,transposer=proxy,storageSide=2})
            return r.status,r.stockCount,COUNT_CALLS,RUN_CALLS,package.loaded.component==nil
        """), ('skipped', 64, 1, 0, True))

    def test_bad_threshold_count_side_or_stock_reader_fails_before_network(self):
        for options in ('{stockAtLeast=-1}', '{stockAtLeast=0/0}', '{stockAtLeast=math.huge}',
                        '{stockAtLeast=1.5}', '{stockAtLeast=10,countStock=function() return -1 end}',
                        '{stockAtLeast=10,countStock=function() error("stock read failed") end}',
                        '{stockAtLeast=10,storageSide=8}', '{onSuccess="bad"}'):
            with self.subTest(options=options):
                self.assertEqual(self.lua.execute(f'local r=PLANS.run(PLAN,{options});return r.status,RUN_CALLS'), ('failed', 0))

    def test_unknown_and_failed_outcomes_invoke_only_failure_hook_once(self):
        for status in ('unknown', 'failed'):
            with self.subTest(status=status):
                self.lua.globals().STATUS = status
                self.assertEqual(self.lua.execute("""
                    EXECUTION={status=STATUS,success=false,message='execution error',mayHaveExecuted=true}
                    local calls=0;local r=PLANS.run(PLAN,{onFailure=function(v) calls=calls+1;assert(v.status==STATUS) end,
                        onSuccess=function() error('wrong hook') end})
                    return r.status,r.success,calls,r.mayHaveExecuted,r.hookError==nil
                """), (status, False, 1, True, True))

    def test_hook_error_or_mutation_does_not_change_verified_outcome_or_retry(self):
        self.assertEqual(self.lua.execute("""
            EXECUTION.cleanupError='cleanup failed'
            local r=PLANS.run(PLAN,{onSuccess=function(v) v.status='failed';v.success=false;error('hook failed') end,
                onFailure=function() error('wrong hook') end})
            return r.status,r.success,r.hookError:find('hook failed')~=nil,r.cleanupError,RUN_CALLS
        """), ('complete', True, True, 'cleanup failed', 1))

    def test_client_creation_exception_reports_failure_and_invokes_hook(self):
        self.assertEqual(self.lua.execute("""
            RUN_THROW=true;local calls=0
            local r=PLANS.run(PLAN,{onFailure=function() calls=calls+1 end})
            return r.status,r.message:find('network creation failed')~=nil,calls,RUN_CALLS
        """), ('failed', True, 1, 1))

    def test_runtime_reservations_are_canonicalized_not_saved_and_hooks_get_output_copy(self):
        self.assertEqual(self.lua.execute('''
            PLAN.external_reserved={['t:part']=5};seed()
            local r=PLANS.run('Gears',{externalReserved={['t:part:0']=2,['t:part']=1},
                onSuccess=function(v) v.outputs['t:gear']=99 end})
            return r.status,SENT.external_reserved['t:part'],PLANS.load('Gears').external_reserved==nil,
                r.outputs['t:gear']
        '''), ('complete', 3, True, 4))

    def test_invalid_runtime_reservations_fail_before_network(self):
        self.assertEqual(self.lua.execute('''
            local r=PLANS.run(PLAN,{externalReserved={['t:part']=0/0}})
            return r.status,RUN_CALLS
        '''), ('failed', 0))
