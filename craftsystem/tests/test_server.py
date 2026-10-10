from test_transport import TransportFixture


class ServerTests(TransportFixture):
    def test_startup_dumps_inventory_before_serving(self):
        self.lua.execute('''
            assert(A.bootCleanups==1 and B.bootCleanups==1 and A.cleanups==0 and B.cleanups==0)
            local restarted=peer('restarted');restarted.dumpThrow=true
            server(restarted);pairHost(C,restarted);advance(0.1)
            job(C,'restarted');untilDone(function() return C.result end)
            assert(restarted.bootCleanups==1 and restarted.executions==1 and C.result.success)
        ''')

    def test_malformed_and_unknown_rpc_do_not_execute(self):
        self.lua.execute('''
            spawn(function()
                local p=C.require('api').connect('craftServer',5990,'robot-a','wake-robot-a',1)
                local ok,kind,r=p.craft('invalid','bad',false)
                assert(ok and kind=='failed' and r.status=='FAILED')
                local known=p.nonsense();assert(not known)
                C.finished=true
            end,C)
            untilDone(function() return C.finished end);assert(A.executions==0 and A.cleanups==0)
        ''')

    def test_success_immediate_accept_progress_terminal_receipts(self):
        self.lua.execute('''
            job(C,'robot-a');untilDone(function() return C.result end)
            local msgs=commands('robot-a');local accepted,working,terminal
            for _,m in ipairs(msgs) do
                if m.msg=='rpc' then accepted=m.args[3]
                elseif m.msg=='ps' and m.args[3].status=='WORKING' then working=m.args[3]
                elseif m.msg=='ps' and m.args[3].status=='COMPLETE' then terminal=m.args[3] end
            end
            assert(accepted[1] and accepted[2]=='accepted' and accepted[3].receipt)
            assert(working and terminal.receipt and terminal.jobId==C.result.jobId)
            assert(A.executions==1 and A.cleanups==0)
            query(C,'robot-a',C.result.jobId);untilDone(function() return C.queryResult end)
            assert(C.queryResult.status=='complete')
        ''')

    def test_failed_execution_cleanup_exceptions_terminal(self):
        for flag in ('success=false', 'executionThrow=true', 'success=false;A.dumpFail=true', 'success=false;A.dumpThrow=true'):
            with self.subTest(flag=flag):
                self.setUp()
                self.lua.execute('A.' + flag)
                self.lua.execute('''
                    job(C,'robot-a');untilDone(function() return C.result end)
                    assert(C.result.status=='failed' and A.cleanups==1)
                    query(C,'robot-a',C.result.jobId);untilDone(function() return C.queryResult end)
                    assert(C.queryResult.status=='failed')
                ''')

    def test_busy_admission_and_live_query_without_stealing_subscription(self):
        self.lua.execute('''
            A.duration=2;job(C,'robot-a');untilDone(function() return A.executions==1 end)
            local second=peer('second');pairHost(second,A);job(second,'robot-a')
            untilDone(function() return second.result end)
            assert(second.result.status=='failed' and second.result.message:find('busy') and A.executions==1)
            local id
            for _,m in ipairs(commands('client')) do if m.msg=='rpc' and m.args[2]=='craft' then id=m.args[4][2] end end
            query(C,'robot-a',id);untilDone(function() return C.queryResult end)
            assert(C.queryResult.status=='running')
            untilDone(function() return C.result end);assert(C.result.success)
        ''')

    def test_duplicate_changed_request_missing_retry(self):
        self.lua.execute('''
            job(C,'robot-a');untilDone(function() return C.result end)
            local id=C.result.jobId;C.result=nil
            job(C,'robot-a',{jobId=id});untilDone(function() return C.result end)
            assert(C.result.success and A.executions==1)
            C.result=nil;job(C,'robot-a',{jobId=id},{requestItem='other'})
            untilDone(function() return C.result end)
            assert(C.result.status=='failed' and C.result.message:find('different') and A.executions==1)
            C.result=nil;job(C,'robot-a',{jobId='lost'});untilDone(function() return C.result end)
            assert(C.result.status=='unknown' and C.result.receiptStatus=='not_found' and A.executions==1)
        ''')

    def test_terminal_receipt_precedes_lost_pubsub_event(self):
        self.lua.execute('''
            local send=A.modem.send
            A.modem.send=function(to,port,wake,info,msg,data)
                if msg=='ps' and A.require('serialization').unserialize(data).args[3].status=='COMPLETE' then
                    error('terminal event lost')
                end
                return send(to,port,wake,info,msg,data)
            end
            job(C,'robot-a',{idleTimeout=0.4});untilDone(function() return C.result end)
            assert(C.result.status=='unknown')
            query(C,'robot-a',C.result.jobId);untilDone(function() return C.queryResult end)
            assert(C.queryResult.status=='complete' and A.executions==1)
        ''')

    def test_server_startup_failure_cleans_owned_network(self):
        self.lua.execute('''
            local p=peer('bad');local net=p.require('tnet')
            net.listen=function() return false,'listen failed' end
            local ok,err=pcall(assert(load(CPROC_SOURCE,'cproc','t',p.env)))
            assert(not ok and err:find('listen failed'))
            assert(countListeners(p,'interrupted')==0 and countListeners(p,'modem_message')==0)
        ''')

    def test_midjob_peer_close_reconnects_without_canceling_or_reexecution(self):
        self.lua.execute('''
            local net=C.require('tnet');local base=net.connect
            net.connect=function(...) C.conn=base(...);return C.conn end
            A.duration=2;job(C,'robot-a');untilDone(function() return A.executions==1 end)
            C.conn:close();untilDone(function() return C.result end)
            assert(C.result.success and A.executions==1 and A.cleanups==0)
            query(C,'robot-a',C.result.jobId);untilDone(function() return C.queryResult end)
            assert(C.queryResult.success)
        ''')
