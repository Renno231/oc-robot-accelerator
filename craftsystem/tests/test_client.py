from test_transport import TransportFixture


class ClientLifecycleTests(TransportFixture):
    def test_foreground_wrong_owner_lost_rpc_never_accepts_job_publication(self):
        self.lua.execute('''
            A.duration=0.4;job(C,'robot-a')
            untilDone(function() return A.executions==1 end)
            local id
            for _,m in ipairs(commands('client')) do if m.msg=='rpc' and m.args[2]=='craft' then id=m.args[4][2] end end
            local other=peer('other');pairHost(other,A)
            local send=A.modem.send
            A.modem.send=function(to,port,wake,info,msg,...)
                if to=='other' and msg=='rpc' then return true end
                return send(to,port,wake,info,msg,...)
            end
            job(other,'robot-a',{jobId=id,jobTimeout=1})
            untilDone(function() return C.result end)
            assert(C.result.success and not other.result)
            untilDone(function() return other.result end)
            assert(not other.result.success and other.result.status=='unknown')
            A.modem.send=send
            query(other,'robot-a',id);untilDone(function() return other.queryResult end)
            assert(other.queryResult.status=='unknown' and other.queryResult.message:find('different sender'))
            assert(A.executions==1)
        ''')

    def test_foreground_lost_admission_uses_owner_scoped_status_without_replay(self):
        self.lua.execute('''
            local send=A.modem.send
            A.modem.send=function(to,port,wake,info,msg,data)
                if msg=='rpc' then
                    local packet=A.require('serialization').unserialize(data)
                    if packet.args[3] and packet.args[3][2]=='accepted' then return true end
                end
                return send(to,port,wake,info,msg,data)
            end
            job(C,'robot-a');untilDone(function() return C.result end)
            assert(C.result.success and A.executions==1)
            local crafts,statuses=0,0
            for _,m in ipairs(commands('client')) do if m.msg=='rpc' then
                if m.args[2]=='craft' then crafts=crafts+1 end
                if m.args[2]=='status' then statuses=statuses+1 end
            end end
            assert(crafts==1 and statuses>=1)
        ''')

    def test_unrelated_job_event_and_failed_send_are_ambiguous(self):
        self.lua.execute('''
            A.duration=1;job(C,'robot-a');untilDone(function() return A.executions==1 end)
            local endpoint=A.require('api').endpoints.craftServer
            A.require('pubsub').attach(endpoint):publish('job:wrong',{jobId='wrong',status='COMPLETE'})
            advance(0.1);assert(not C.result)
            untilDone(function() return C.result end);assert(C.result.success)
            C.result=nil;local send=C.modem.send
            C.modem.send=function(to,port,wake,info,msg,...)
                if msg=='rpc' then error('rpc send failed') end
                return send(to,port,wake,info,msg,...)
            end
            job(C,'robot-a',{jobTimeout=0.4})
            untilDone(function() return C.result end)
            assert(C.result.status=='unknown' and C.result.mayHaveExecuted and A.executions==1)
        ''')

    def test_renewable_idle_identity_blueprint_and_subscribe_order(self):
        self.lua.execute('''
            A.duration=2;A.progressEvery=0.2
            job(C,'robot-a',{idleTimeout=0.4},{requestItem='t:target',blueprint={huge='client only'}})
            untilDone(function() return C.result end)
            local sent=commands('client')
            assert(sent[1].msg=='ps' and sent[1].args[1]=='sub')
            assert(sent[2].msg=='rpc' and sent[2].args[2]=='craft')
            local args=sent[2].args[4]
            assert(args[1].blueprint==nil and args[3]==false)
            assert(C.result.success and C.result.jobId==args[2] and C.result.serverAddress=='robot-a')
            assert(sent[#sent].msg=='ps' and sent[#sent].args[1]=='unsub')
            assert(countListeners(C,'modem_message')==1 and C.open[5990])
        ''')

    def test_idle_timeout_quarantines_late_output_without_closing_pool(self):
        self.lua.execute('''
            A.duration=2;A.progressEvery=1
            local net=C.require('tnet');local base=net.connect
            net.connect=function(...) C.conn=base(...);return C.conn end
            job(C,'robot-a',{idleTimeout=0.2})
            untilDone(function() return C.result end)
            assert(C.result.status=='unknown' and C.result.mayHaveExecuted and C.conn.connected)
            assert(C.result.message:find('idle timeout'))
            advance(3);assert(C.result.status=='unknown' and A.executions==1 and A.cleanups==0)
            query(C,'robot-a',C.result.jobId);untilDone(function() return C.queryResult end)
            assert(C.queryResult.success)
        ''')

    def test_absolute_deadline_not_renewed_by_progress(self):
        self.lua.execute('''
            A.duration=5;A.progressEvery=0.1;job(C,'robot-a',{idleTimeout=1,jobTimeout=0.4})
            untilDone(function() return C.result end)
            assert(C.result.status=='unknown' and C.result.message:find('total timeout') and NOW<1)
        ''')

    def test_cancellation_and_exception_unsubscribe_without_canceling_execution(self):
        for throws in (False, True):
            with self.subTest(throws=throws):
                self.setUp()
                self.lua.globals().THROWS = throws
                self.lua.execute('''
                    A.duration=1
                    local net=C.require('tnet');local base=net.connect
                    net.connect=function(...) C.conn=base(...);return C.conn end
                    job(C,'robot-a',{shouldContinue=function()
                        if NOW>0.4 then if THROWS then error('continuation boom') else return false end end
                        return true
                    end})
                    untilDone(function() return C.result end)
                    assert(C.result.status=='unknown' and C.result.mayHaveExecuted and C.conn.connected)
                    assert(C.result.message:find(THROWS and 'continuation boom' or 'cancelled'))
                    local sent=commands('client');assert(sent[#sent].args[1]=='unsub')
                    advance(2);assert(A.executions==1 and A.cleanups==0 and C.result.status=='unknown')
                ''')

    def test_completion_survives_unsubscribe_exception_and_run_reports_it(self):
        self.lua.execute('''
            local ps=C.require('pubsub');local base=ps.client
            ps.client=function(conn)
                local sub=base(conn);local unsub=sub.unsubscribe
                sub.unsubscribe=function(self,topic) unsub(self,topic);error('unsub boom') end
                return sub
            end
            job(C,'robot-a');untilDone(function() return C.result end)
            assert(C.result.success and C.result.cleanupError:find('unsub boom'))
            spawn(function() C.ok,C.message=C.require('craft_client').run({requestItem='t:target'},
                {serverAddress='robot-a'});C.done=true end,C)
            untilDone(function() return C.done end);assert(not C.ok and C.message:find('unsub boom'))
        ''')

    def test_unpaired_and_handshake_failure_before_submission(self):
        self.lua.execute('''
            job(C,nil,{service='absent'})
            untilDone(function() return C.result end)
            assert(C.result.status=='failed' and not C.result.mayHaveExecuted)
            assert(countListeners(C,'modem_message')==0)
            local h=C.require('hosts');h.addHost('missing','missing-cid','missing','secret',{service='craftServer'},true)
            C.result=nil;job(C,'missing',{connectTimeout=0.2})
            untilDone(function() return C.result end)
            assert(C.result.status=='failed' and not C.result.mayHaveExecuted and C.result.message:find('no response'))
        ''')

    def test_default_selection_uses_paired_robot_without_broadcast(self):
        self.lua.execute('''
            job(C,nil);untilDone(function() return C.result end)
            assert(C.result.success and (C.result.serverAddress=='robot-a' or C.result.serverAddress=='robot-b'))
            assert(countListeners(C,'modem_message')==1)
        ''')

    def test_explicit_retry_never_executes_missing_receipt(self):
        self.lua.execute('''
            query(C,'robot-a','gone');untilDone(function() return C.queryResult end)
            assert(C.queryResult.status=='not_found' and C.queryResult.mayHaveExecuted and C.queryResult.queried)
            job(C,'robot-a',{jobId='gone'});untilDone(function() return C.result end)
            assert(C.result.status=='unknown' and C.result.receiptStatus=='not_found' and A.executions==0)
            local sent=commands('client');local args=sent[3].args[4]
            assert(args[2]=='gone' and args[3]==true)
            local before=#TRACE;local r=C.require('craft_client').runDetailed({},{jobId='prior'})
            assert(r.status=='unknown' and r.mayHaveExecuted and #TRACE==before)
        ''')

    def test_query_timeout_and_owner_denial_are_unknown(self):
        self.lua.execute('''
            job(C,'robot-a');untilDone(function() return C.result end)
            local other=peer('other');query(other,'robot-a',C.result.jobId)
            untilDone(function() return other.queryResult end)
            assert(other.queryResult.status=='unknown' and not other.queryResult.success)
            pairHost(other,A);other.queryResult=nil;query(other,'robot-a',C.result.jobId)
            untilDone(function() return other.queryResult end)
            assert(other.queryResult.status=='unknown' and other.queryResult.message:find('different sender'))
            query(C,'missing',C.result.jobId,{connectTimeout=0.2});untilDone(function() return C.queryResult end)
            assert(C.queryResult.status=='unknown' and C.queryResult.mayHaveExecuted)
        ''')

    def test_admission_failure_and_exception_safe_message_callback(self):
        self.lua.execute('''
            job(C,'robot-a',nil,{invalid=true});untilDone(function() return C.result end)
            assert(C.result.status=='failed' and A.executions==0)
            C.result=nil;job(C,'robot-a',{onMessage=function() error('observer boom') end})
            untilDone(function() return C.result end)
            assert(C.result.status=='unknown' and C.result.message:find('observer boom'))
            advance(2);assert(A.executions==1)
        ''')

    def test_plan_success_hook_runs_with_subscription_cleaned_and_pool_live(self):
        self.lua.globals().CRAFT_PLANS_SOURCE = (self.root_path() / 'usr/lib/craft_plans.lua').read_text()
        self.lua.execute('''
            local net=C.require('tnet');local base=net.connect
            net.connect=function(...) C.conn=base(...);return C.conn end
            spawn(function()
                C.result=C.require('craft_plans').run({requestItem='t:target',requestQuantity=1,
                    inventory_needed={['t:raw']=1},tasks={{item='t:target',recipe={'t:raw'},recipeOutput=1,qty_produced=1}}},
                    {serverAddress='robot-a',onSuccess=function()
                        local sent=commands('client');assert(sent[#sent].args[1]=='unsub' and C.conn.connected);C.hooked=true
                    end})
            end,C)
            untilDone(function() return C.result end);assert(C.result.success and C.hooked)
        ''')

    @staticmethod
    def root_path():
        from test_support import ROOT
        return ROOT
