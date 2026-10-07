from test_network import NetworkFixture


class ClientLifecycleTests(NetworkFixture):
    def setUp(self):
        super().setUp()
        self.lua.execute("""
            NOW, CLOCK_ID, CLOCK, STEPS, CONTINUE = 0, 0, {}, {}, true
            require('computer').uptime=function() return NOW end
            require('event').timer=function(seconds,cb)
                CLOCK_ID=CLOCK_ID+1;CLOCK[CLOCK_ID]={due=NOW+seconds,cb=cb};return CLOCK_ID
            end
            require('event').cancel=function(id) CLOCK[id]=nil;return true end
            require('event').pull=function()
                local step=table.remove(STEPS,1)
                if not step then error('test exhausted event steps') end
                NOW=step[1]
                local due={}
                for id,timer in pairs(CLOCK) do if timer.due<=NOW then table.insert(due,id) end end
                table.sort(due)
                for _,id in ipairs(due) do local timer=CLOCK[id];if timer then CLOCK[id]=nil;timer.cb() end end
                if step[2]=='announce' then deliver('DAN',nil,{serviceName='craftServer',status='Ready'},'discovery')
                elseif step[2]=='ack' then
                    local pid
                    for _,msg in ipairs(WIRE) do if msg.packet.hdr.t=='CRQ' then pid=msg.packet.hdr.p end end
                    deliver('CAC','cid',{ackPID=pid},'ack')
                elseif step[2]=='working' then deliver('DAT','cid',{status='WORKING',message='progress'},'work'..NOW)
                elseif step[2]=='complete' then deliver('DAT','cid',{status='COMPLETE'},'complete')
                elseif step[2]=='failed' then deliver('DAT','cid',{status='FAILED',message='missing ingredient'},'failed')
                elseif step[2]=='interrupt' then CONTINUE=false end
            end
        """)
        self.module('craft_client', 'lib/craft_client.lua')
        self.lua.execute("CLIENT=require('craft_client');PLAN={requestItem='t:target',requestQuantity=1}")

    def run_client(self, steps, options=''):
        return self.lua.execute("STEPS="+steps+";return CLIENT.run(PLAN,{network=NET,shouldContinue=function() return CONTINUE end,"+options+"})")

    def test_long_job_renews_idle_timeout_and_cleans_up(self):
        self.assertEqual(self.run_client("{{0,'announce'},{1,'ack'},{30,'working'},{65,'working'},{95,'complete'}}"), (True, 'Crafting complete.'))
        self.assertEqual(self.lua.execute("return OPEN[5990]==nil,next(CLOCK)==nil,next(NET._activePromises)==nil"), (True, True, True))

    def test_idle_timeout_disconnects_job(self):
        ok, message = self.run_client("{{0,'announce'},{1,'ack'},{80,'noop'}}")
        self.assertFalse(ok)
        self.assertIn('idle timeout', message)
        self.assertEqual(self.lua.execute("return WIRE[#WIRE].packet.hdr.t"), 'DIS')

    def test_total_deadline_is_separate_from_progress(self):
        ok, message = self.run_client("{{0,'announce'},{1,'ack'},{30,'working'},{65,'working'}}", 'jobTimeout=45')
        self.assertFalse(ok)
        self.assertIn('total timeout', message)

    def test_interruption_disconnects_and_cleans_up(self):
        ok, message = self.run_client("{{0,'announce'},{1,'ack'},{2,'interrupt'}}")
        self.assertFalse(ok)
        self.assertIn('cancelled', message)
        self.assertEqual(self.lua.execute("return OPEN[5990]==nil,next(CLOCK)==nil"), (True, True))

    def test_server_failure_is_not_success(self):
        self.assertEqual(self.run_client("{{0,'announce'},{1,'ack'},{2,'failed'}}"), (False, 'missing ingredient'))

    def test_detailed_result_distinguishes_verified_failure_from_unknown_timeout(self):
        for outcome, expected in (('failed', 'failed'), ('noop', 'unknown')):
            with self.subTest(outcome=outcome):
                self.setUp()
                time = 2 if outcome == 'failed' else 80
                self.assertEqual(self.lua.execute("STEPS={{0,'announce'},{1,'ack'},{" + str(time) + ",'" + outcome + "'}};local r=CLIENT.runDetailed(PLAN,{network=NET});return r.status,r.success,r.mayHaveExecuted,OPEN[5990]==nil,next(CLOCK)==nil"), (expected, False, True, True, True))

    def test_recovery_disconnect_exception_retains_unknown_and_reaches_cleanup(self):
        self.assertEqual(self.lua.execute("""
            local connect=NET.connect
            NET.connect=function(self,...) local p=connect(self,...);p.disconnect=function() error('disconnect boom') end;return p end
            STEPS={{0,'announce'},{1,'ack'}};local checks=0
            local ok,r=pcall(CLIENT.runDetailed,PLAN,{network=NET,shouldContinue=function()
                checks=checks+1;if checks==3 then error('continuation boom') end;return true
            end})
            return ok,r.status,r.mayHaveExecuted,r.cleanupError:find('disconnect boom')~=nil,
                OPEN[5990]==nil,next(CLOCK)==nil,next(NET._activePromises)==nil
        """), (True, 'unknown', True, True, True, True, True))

    def test_compound_disconnect_or_active_check_fault_calls_failure_hook_after_cleanup(self):
        for method in ('disconnect', 'isActive'):
            with self.subTest(method=method):
                self.setUp()
                self.module('craft_plans', 'lib/craft_plans.lua')
                self.lua.execute("package.preload.filesystem=function() return {} end;package.preload.serialization=function() return {} end")
                self.lua.globals().METHOD = method
                self.assertEqual(self.lua.execute("""
                    PLAN={requestItem='t:target',requestQuantity=1,inventory_needed={['t:raw']=1},
                        tasks={{item='t:target',recipe={'t:raw'},recipeOutput=1,qty_produced=1}}}
                    local connect=NET.connect
                    NET.connect=function(self,...) ACTIVE=connect(self,...);return ACTIVE end
                    STEPS={{0,'announce'},{1,'ack'}};local checks,hooks=0,0
                    local r=require('craft_plans').run(PLAN,{network=NET,shouldContinue=function()
                        checks=checks+1
                        if checks==3 then ACTIVE[METHOD]=function() error(METHOD..' boom') end;error('continuation boom') end
                        return true
                    end,onFailure=function(v)
                        hooks=hooks+1;assert(v.status=='unknown' and v.mayHaveExecuted)
                        assert(OPEN[5990]==nil and next(CLOCK)==nil and next(NET._activePromises)==nil)
                    end})
                    return r.status,r.success,r.mayHaveExecuted,hooks,r.hookError==nil,r.cleanupError:find('boom')~=nil
                """), ('unknown', False, True, 1, True, True))

    def test_pre_submission_timeout_is_not_an_unknown_execution(self):
        self.assertEqual(self.lua.execute("STEPS={{20,'noop'}};local r=CLIENT.runDetailed(PLAN,{network=NET});return r.status,r.success,r.mayHaveExecuted,OPEN[5990]==nil"), ('failed', False, False, True))

    def test_verified_completion_survives_cleanup_exception_in_detailed_result(self):
        self.assertEqual(self.lua.execute("""
            local shutdown=NET.shutdown;NET.shutdown=function(self) shutdown(self);error('cleanup boom') end
            STEPS={{0,'announce'},{1,'ack'},{2,'complete'}}
            local r=CLIENT.runDetailed(PLAN,{network=NET})
            return r.status,r.success,r.cleanupError:find('cleanup boom')~=nil,OPEN[5990]==nil
        """), ('complete', True, True, True))

    def test_plan_api_real_network_hook_runs_after_cleanup_with_fixed_wire_batch(self):
        self.module('craft_plans', 'lib/craft_plans.lua')
        self.lua.execute("package.preload.filesystem=function() return {} end;package.preload.serialization=function() return {} end")
        self.assertEqual(self.lua.execute("""
            PLAN={requestItem='t:target',requestQuantity=4,inventory_needed={['t:raw']=4},
                tasks={{item='t:target',recipe={'t:raw'},recipeOutput=1,qty_produced=4}}}
            STEPS={{0,'announce'},{1,'ack'},{2,'complete'}}
            local hooks=0
            local r=require('craft_plans').run(PLAN,{network=NET,onSuccess=function(result)
                hooks=hooks+1;assert(result.status=='complete' and OPEN[5990]==nil and next(CLOCK)==nil)
            end})
            local sent
            for _,msg in ipairs(WIRE) do if msg.packet.hdr.t=='DAT' then sent=msg.packet.pld.plan end end
            return r.status,hooks,sent.requestQuantity,sent.tasks[1].qty_produced,package.loaded.qmenu==nil
        """), ('complete', 1, 4, 4, True))

    def test_failed_initial_send_terminates(self):
        self.lua.execute('SEND_FAIL=true')
        ok, message = self.run_client("{{0,'announce'}}")
        self.assertFalse(ok)
        self.assertIn('initiate', message)

    def test_execution_returns_job_identity_and_robot_address(self):
        self.assertEqual(self.lua.execute("""
            STEPS={{0,'announce'},{1,'ack'},{2,'complete'}}
            local r=CLIENT.runDetailed(PLAN,{network=NET});local packet
            for _,m in ipairs(WIRE) do if m.packet.hdr.t=='DAT' then packet=m.packet.pld end end
            return r.status,r.serverAddress,r.jobId==packet.jobId,type(r.jobId)=='string',packet.retryOnly
        """), ('complete', 'remote', True, True, False))

    def query_fixture(self, status):
        self.lua.globals().RECEIPT_STATUS = status
        self.lua.execute("""
            local pull=require('event').pull
            require('event').pull=function()
                if STEPS[1] and STEPS[1][2]=='receipt' then
                    NOW=table.remove(STEPS,1)[1]
                    deliver('DAT','cid',{status=RECEIPT_STATUS,jobId='prior',receipt=true,message='receipt'},'receipt')
                else return pull() end
            end
            STEPS={{1,'ack'},{2,'receipt'}}
        """)

    def test_query_contacts_original_robot_without_discovery_and_cleans_up(self):
        for status, expected in (('COMPLETE', 'complete'), ('FAILED', 'failed'), ('RUNNING', 'running'), ('NOT_FOUND', 'not_found')):
            with self.subTest(status=status):
                self.setUp()
                self.query_fixture(status)
                self.assertEqual(self.lua.execute("""
                    local r=CLIENT.query('remote','prior',{network=NET});local packet
                    for _,m in ipairs(WIRE) do
                        assert(m.packet.hdr.t~='DQY','query must not broadcast')
                        if m.packet.hdr.t=='DAT' then packet=m.packet.pld end
                    end
                    return r.status,r.jobId,r.serverAddress,packet.command,packet.plan==nil,
                        r.mayHaveExecuted,OPEN[5990]==nil,next(CLOCK)==nil
                """), (expected, 'prior', 'remote', 'job_status', True, True, True, True))

    def test_explicit_duplicate_submission_is_retry_only(self):
        self.query_fixture('NOT_FOUND')
        self.assertEqual(self.lua.execute("""
            local r=CLIENT.runDetailed(PLAN,{network=NET,serverAddress='remote',jobId='prior'})
            local request
            for _,m in ipairs(WIRE) do if m.packet.hdr.t=='DAT' then request=m.packet.pld end end
            return r.status,r.receiptStatus,request.retryOnly,WIRE[1].packet.pld.receiptControl
        """), ('unknown', 'not_found', True, True))

    def test_query_transport_timeout_is_unknown_not_proof_of_no_execution(self):
        self.assertEqual(self.lua.execute("""
            STEPS={{20,'noop'}}
            local r=CLIENT.query('remote','prior',{network=NET})
            return r.status,r.mayHaveExecuted,OPEN[5990]==nil,next(CLOCK)==nil
        """), ('unknown', True, True, True))

    def test_old_job_id_without_original_address_does_not_discover_another_robot(self):
        self.assertEqual(self.lua.execute("""
            local r=CLIENT.runDetailed(PLAN,{network=NET,jobId='prior'})
            return r.status,r.mayHaveExecuted,#WIRE
        """), ('unknown', True, 0))

    def test_query_authorization_error_is_not_a_verified_job_failure(self):
        self.query_fixture('FAILED')
        self.lua.execute("""
            require('event').pull=function()
                local step=table.remove(STEPS,1);NOW=step[1]
                if step[2]=='ack' then
                    deliver('CAC','cid',{ackPID=WIRE[1].packet.hdr.p},'ack')
                else deliver('DAT','cid',{status='FAILED',jobId='prior',message='different sender'},'denied') end
            end
        """)
        self.assertEqual(self.lua.execute("local r=CLIENT.query('remote','prior',{network=NET});return r.status,r.success,OPEN[5990]==nil"), ('unknown', False, True))
