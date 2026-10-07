from test_support import LuaCase, ROOT


class ServerTests(LuaCase):
    def setUp(self):
        super().setUp()
        self.lua.execute("""
            LISTENERS,SENT={},{};EXECUTIONS,CLEANUPS=0,0
            NET={INTERNAL_EVENT_NAMES={CONNECTION_REQUEST='request',DISCOVERY_ANNOUNCE='discovery'},
                HDR_KEYS={TYP='t'},PACKET_TYPES={DATA='DAT',DISC_QRY='DQY'},
                listen=function(self,n,cb) LISTENERS[n]=cb end,openPort=function() return true end,
                startListener=function() return true end,shutdown=function() end}
            package.preload.gatenet=function() return {new=function() return NET end} end
            package.preload.component=function() return {modem={address='server'}} end
            package.preload.sides=function() return {front=3} end
            package.preload.shell=function() return {parse=function() return {},{} end} end
            package.preload.serialization=function() return {serialize=function() return '' end} end
            package.preload.event=function() return {listen=function() end,ignore=function() end} end
            EX={validatePlan=function(p) return p~=nil and not INVALID,'invalid plan' end,
                executePlan=function(p,opts)
                    EXECUTIONS=EXECUTIONS+1
                    if DURING_EXECUTION then DURING_EXECUTION() end
                    if EXECUTION_THROW then error('execution exception') end
                    opts.onProgress('testing')
                    return EXECUTION_OK,'execution result'
                end,
                dumpInventory=function() CLEANUPS=CLEANUPS+1;return not CLEANUP_FAIL,'storage blocked' end}
            package.preload.craft_executor=function() return EX end
            os.sleep=function() error('test server initialized') end
        """)
        self.lua.globals().SERVER_SOURCE = (ROOT / 'usr/bin/cproc.lua').read_text()
        self.lua.execute("local ok,err=pcall(assert(load(SERVER_SOURCE)));assert(not ok and err:find('test server initialized'))")
        self.lua.execute("""
            P={getConnectionID=function() return 'cid' end,isActive=function() return true end,
                sendData=function(self,d) table.insert(SENT,d);return self end,
                next=function(self,cb) REQUEST=cb;return self end,catch=function(self) return self end,
                finally=function(self) return self end,disconnect=function(self) return self end,
                timeout=function(self) return self end,clearTimeout=function(self) return self end}
            function request(payload)
                LISTENERS.request('client',5990,{},function(accept) assert(accept);return P end)
                REQUEST(P,{hdr={t='DAT'},pld=payload or {command='craft',plan={requestItem='t:target'}}})
                local terminals=0;for _,s in ipairs(SENT) do if s.status=='COMPLETE' or s.status=='FAILED' then terminals=terminals+1 end end
                return SENT[#SENT].status,terminals
            end
        """)

    def test_startup_failure_still_closes_port_and_listener(self):
        self.assertEqual(self.lua.execute("""
            PORT_OPEN,INTERRUPTED_PRESENT,SHUTDOWNS=false,false,0
            require('event').listen=function() INTERRUPTED_PRESENT=true end
            require('event').ignore=function() INTERRUPTED_PRESENT=false end
            NET.openPort=function() PORT_OPEN=true;return true end
            NET.startListener=function() return false end
            NET.shutdown=function() PORT_OPEN=false;SHUTDOWNS=SHUTDOWNS+1 end
            local ok=pcall(assert(load(SERVER_SOURCE)))
            return ok,PORT_OPEN,INTERRUPTED_PRESENT,SHUTDOWNS
        """), (False, False, False, 1))

    def test_false_execution_result_is_failed_not_complete(self):
        self.lua.execute('EXECUTION_OK=false')
        self.assertEqual(self.lua.execute('return request()'), ('FAILED', 1))
        self.assertEqual(self.lua.execute('return CLEANUPS'), 1)

    def test_exception_is_failed(self):
        self.lua.execute('EXECUTION_THROW=true')
        self.assertEqual(self.lua.execute('return request()'), ('FAILED', 1))

    def test_verified_success_reports_complete_once(self):
        self.lua.execute('EXECUTION_OK=true')
        self.assertEqual(self.lua.execute('return request()'), ('COMPLETE', 1))
        self.assertEqual(self.lua.execute('return CLEANUPS'), 0)

    def test_invalid_plan_rejected_before_execution_or_dump(self):
        self.lua.execute('INVALID=true')
        self.assertEqual(self.lua.execute('return request()'), ('FAILED', 1))
        self.assertEqual(self.lua.execute('return EXECUTIONS,CLEANUPS'), (0, 0))

    def test_cleanup_error_does_not_turn_failure_into_success(self):
        self.lua.execute('EXECUTION_OK=false;CLEANUP_FAIL=true')
        self.assertEqual(self.lua.execute('return request()'), ('FAILED', 1))
        self.assertIn('cleanup failed', self.lua.execute('return SENT[#SENT].message'))

    def test_busy_robot_rejects_another_connection(self):
        self.lua.execute("""
            EXECUTION_OK=true
            DURING_EXECUTION=function()
                LISTENERS.request('second',5990,{},function(accept) SECOND_ACCEPTED=accept end)
            end
        """)
        self.assertEqual(self.lua.execute('request();return SECOND_ACCEPTED'), False)

    def test_duplicate_job_returns_receipt_without_second_execution(self):
        self.assertEqual(self.lua.execute("""
            EXECUTION_OK=true
            local payload={command='craft',jobId='job1',plan={requestItem='t:target'}}
            request(payload);request(payload)
            return SENT[#SENT].status,SENT[#SENT].jobId,EXECUTIONS,CLEANUPS
        """), ('COMPLETE', 'job1', 1, 0))

    def test_changed_request_same_id_is_rejected(self):
        self.assertEqual(self.lua.execute("""
            EXECUTION_OK=true
            request({command='craft',jobId='same',plan={requestItem='t:target'}})
            request({command='craft',jobId='same',plan={requestItem='t:other'}})
            return SENT[#SENT].status,SENT[#SENT].message:find('different')~=nil,EXECUTIONS
        """), ('FAILED', True, 1))

    def test_status_query_and_duplicate_are_available_while_busy(self):
        self.assertEqual(self.lua.execute("""
            EXECUTION_OK=true
            DURING_EXECUTION=function()
                LISTENERS.request('client',5990,{pld={receiptControl=true}},function(accept) assert(accept);return P end)
                REQUEST(P,{hdr={t='DAT'},pld={command='job_status',jobId='active'}})
                RUNNING_STATUS=SENT[#SENT].status
                REQUEST(P,{hdr={t='DAT'},pld={command='craft',jobId='active',plan={requestItem='t:target'},retryOnly=true}})
                DUPLICATE_STATUS=SENT[#SENT].status
            end
            request({command='craft',jobId='active',plan={requestItem='t:target'}})
            return RUNNING_STATUS,DUPLICATE_STATUS,EXECUTIONS,SENT[#SENT].status
        """), ('RUNNING', 'RUNNING', 1, 'COMPLETE'))

    def test_receipt_exists_before_final_reply_send_fault(self):
        self.assertEqual(self.lua.execute("""
            EXECUTION_OK=true
            local send=P.sendData
            P.sendData=function(self,data) if data.status=='COMPLETE' then error('reply lost') end;return send(self,data) end
            local ok=pcall(request,{command='craft',jobId='lost',plan={requestItem='t:target'}})
            P.sendData=send
            request({command='job_status',jobId='lost'})
            return ok,SENT[#SENT].status,EXECUTIONS
        """), (False, 'COMPLETE', 1))

    def test_missing_retry_is_not_new_work_and_control_cannot_submit_new_job(self):
        self.assertEqual(self.lua.execute("""
            request({command='craft',jobId='gone',plan={},retryOnly=true})
            local absent=SENT[#SENT].status
            LISTENERS.request('client',5990,{pld={receiptControl=true}},function(accept) assert(accept);return P end)
            REQUEST(P,{hdr={t='DAT'},pld={command='craft',jobId='new',plan={requestItem='t:target'}}})
            return absent,SENT[#SENT].status,EXECUTIONS,CLEANUPS
        """), ('NOT_FOUND', 'FAILED', 0, 0))
