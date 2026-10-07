import unittest
import test_plans


class KitTests(unittest.TestCase):
    def setUp(self):
        test_plans.SavedPlanTests.setUp(self)
        self.lua.execute('''
            PLAN.inventory_needed['t:raw']=4
            KITS=require('craft_kits');KDIR=KITS.directory
            require('filesystem').remove=function(path)
                if files[path] then files[path]=nil;return true end;return nil,'missing file'
            end
            STOCK={{name='t:raw',size=10,damage=0,maxSize=64}}
            function inv() return assert(require('inventory').new({getAllStacks=function()
                return {getAll=function() return STOCK end} end},0)) end
            function modern(item)
                local b={roots={{node='root',quantity=1}},tools={},nodes={
                    root={item=item or 't:a',useStock=true,recipeOutput=1,recipe={'t:part'},deps={'part'}},
                    part={item='t:part',useStock=true,recipeOutput=4,recipe={'t:raw'},deps={'raw'}},
                    raw={item='t:raw',useStock=true}}}
                return assert(require('craft_blueprint').calculate(b,inv()))
            end
            function sample()
                assert(PLANS.save('Gears',PLAN));assert(PLANS.save('Spare',PLAN))
                return {executionMode='separate',accounting='saved',entries={
                    {binding='live',planName='Gears'},assert(KITS.pin('Spare'))}}
            end
        ''')

    def test_require_and_listing_are_headless_directory_only(self):
        self.assertEqual(self.lua.execute('''
            directories[KDIR]=true;listing[KDIR]={'Computer.kit','Robot.kit','corrupt.kit','ignore.plan','nested.kit/'}
            io.open=function() error('unexpected file open') end
            return table.concat(assert(KITS.list()),','),OPEN_CALLS,LIST_CALLS,package.loaded.component==nil
        '''), ('Computer,Robot,corrupt', 0, 1, True))

    def test_one_kit_file_contains_defaults_pins_and_live_names(self):
        self.assertEqual(self.lua.execute('''
            local kit=sample();kit.extra=function() end
            assert(KITS.save('T3 Computer',kit));OPEN_CALLS=0
            local loaded=assert(KITS.load('T3 Computer'))
            return files['/usr/craftkits/T3 Computer.kit']~=nil,OPEN_CALLS,loaded.executionMode,
                loaded.accounting,loaded.entries[1].planName,loaded.entries[2].plan.requestQuantity,
                loaded.extra==nil,allClosed()
        '''), (True, 1, 'separate', 'saved', 'Gears', 4, True, True))

    def test_selected_kit_loads_only_its_live_references(self):
        self.assertEqual(self.lua.execute('''
            local kit=sample();assert(KITS.save('Computer',kit));OPEN_CALLS=0
            local prepared=assert(KITS.prepare('Computer'))
            return OPEN_CALLS,#prepared.entries,prepared.entries[1].binding,prepared.entries[2].binding
        '''), (2, 2, 'live', 'pinned'))

    def test_pinned_survives_source_deletion_live_reflects_edit(self):
        self.assertEqual(self.lua.execute('''
            local kit=sample();assert(PLANS.remove('Spare'))
            PLAN.requestQuantity=2;assert(PLANS.save('Gears',PLAN))
            local p=assert(KITS.prepare(kit))
            return p.entries[1].plan.requestQuantity,p.entries[2].plan.requestQuantity
        '''), (2, 4))

    def test_missing_live_reference_fails_before_any_job_or_overall_success(self):
        self.assertEqual(self.lua.execute('''
            local kit=sample();assert(PLANS.remove('Gears'));local calls=0
            local r=KITS.run(kit,{onFailure=function() calls=calls+1 end})
            return r.status,calls,RUN_CALLS
        '''), ('failed', 1, 0))

    def test_one_run_mode_override_does_not_change_saved_default(self):
        self.assertEqual(self.lua.execute('''
            assert(KITS.save('Computer',sample()));local callbacks=0
            local r=KITS.run('Computer',{executionMode='merged',onSuccess=function() callbacks=callbacks+1 end})
            assert(r.success,r.message)
            return r.status,r.executionMode,callbacks,RUN_CALLS,SENT.requestOutputs['t:gear'],
                SENT.inventory_needed['t:raw'],KITS.load('Computer').executionMode
        '''), ('complete', 'merged', 1, 1, 8, 8, 'separate'))

    def test_separate_jobs_have_one_overall_hook_and_no_persisted_callbacks(self):
        self.assertEqual(self.lua.execute('''
            local calls=0;local r=KITS.run(sample(),{onSuccess=function() calls=calls+1 end})
            return r.status,calls,RUN_CALLS,#r.entries,r.completedEntries,r.partial
        '''), ('complete', 1, 2, 2, 2, False))

    def test_unknown_second_job_stops_without_retry_or_rollback(self):
        self.assertEqual(self.lua.execute('''
            local kit=sample();kit.entries[3]=kit.entries[1]
            require('craft_client').runDetailed=function()
                RUN_CALLS=RUN_CALLS+1
                return {status=RUN_CALLS==1 and 'complete' or 'unknown',success=RUN_CALLS==1,mayHaveExecuted=true}
            end
            local callbacks=0;local r=KITS.run(kit,{onFailure=function() callbacks=callbacks+1 end})
            return r.status,RUN_CALLS,r.completedEntries,r.partial,r.mayHaveExecuted,callbacks
        '''), ('unknown', 2, 1, True, True, 1))

    def test_callback_error_does_not_change_complete_result(self):
        self.assertEqual(self.lua.execute('''
            local r=KITS.run(sample(),{onSuccess=function(v) v.entries[1].status='failed';error('hook broke') end})
            return r.status,r.success,r.entries[1].status,r.hookError:find('hook broke')~=nil,RUN_CALLS
        '''), ('complete', True, 'complete', True, 2))

    def test_saved_merge_replays_while_refreshed_merge_shares_batch_cost(self):
        self.assertEqual(self.lua.execute('''
            local kit={executionMode='merged',entries={
                {binding='pinned',plan=modern('t:a')},{binding='pinned',plan=modern('t:b')}}}
            local saved=assert(KITS.prepare(kit));local fresh=assert(KITS.prepare(kit,{accounting='refresh',inventory=inv()}))
            return #saved.plan.tasks,saved.plan.inventory_needed['t:raw'],
                #fresh.plan.tasks,fresh.plan.inventory_needed['t:raw'],fresh.plan.requestOutputs['t:a'],fresh.plan.requestOutputs['t:b']
        '''), (4, 2, 3, 1, 1, 1))

    def test_refresh_keeps_concrete_material_choices_after_database_edits(self):
        self.assertEqual(self.lua.execute('''
            local p=modern();assert(PLANS.save('Locked',p));STOCK={}
            package.preload.recipes=function() error('must not consult recipes') end
            local r=PLANS.run('Locked',{accounting='refresh',inventory=inv()})
            return r.status,r.message:find('t:raw')~=nil,RUN_CALLS,package.loaded.recipes==nil
        '''), ('failed', True, 0, True))

    def test_blueprint_roundtrip_and_wire_payload_excludes_graph(self):
        self.assertEqual(self.lua.execute('''
            local p=modern();p.blueprint.extra=function() end;assert(PLANS.save('Modern',p))
            local restored=assert(PLANS.load('Modern'));local r=PLANS.run(restored,{accounting='refresh',inventory=inv()})
            return r.status,restored.blueprint.nodes.part.recipe[1],SENT.blueprint==nil,
                SENT.node_items~=nil,SENT.requestOutputs['t:a'],restored.blueprint.extra==nil
        '''), ('complete', 't:raw', True, True, 1, True))

    def test_legacy_refresh_and_bad_modes_fail_before_network(self):
        for options in ("{accounting='refresh'}", "{accounting='auto'}", "{executionMode='auto'}", "{onSuccess='bad'}"):
            with self.subTest(options=options):
                self.setUp()
                self.assertEqual(self.lua.execute('local r=KITS.run(sample(),'+options+');return r.status,RUN_CALLS'), ('failed', 0))

    def test_fixed_merge_rejects_insufficient_snapshots_before_submission(self):
        self.assertEqual(self.lua.execute('''
            PLAN.inventory_needed['t:raw']=1;local r=KITS.run(sample(),{executionMode='merged'})
            return r.status,r.message:find('Insufficient fixed prerequisite')~=nil,RUN_CALLS
        '''), ('failed', True, 0))

    def test_corrupt_data_sparse_entries_path_traversal_and_io_failures(self):
        self.assertEqual(self.lua.execute('''
            local kit=sample();kit.entries[4]=kit.entries[1]
            local saved,e=KITS.save('bad',kit);local traversed=KITS.save('../bad',sample())
            files[KDIR..'broken.kit']='42';local loaded=KITS.load('broken')
            return saved==nil,traversed==nil,loaded==nil,RUN_CALLS,allClosed()
        '''), (True, True, True, 0, True))

    def test_removing_one_kit_does_not_remove_source_plans(self):
        self.assertEqual(self.lua.execute('''
            assert(KITS.save('Computer',sample()));assert(KITS.remove('Computer'))
            return files[KDIR..'Computer.kit']==nil,PLANS.load('Gears')~=nil
        '''), (True, True))
