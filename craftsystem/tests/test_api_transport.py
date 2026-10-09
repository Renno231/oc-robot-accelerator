from test_transport import TransportFixture


class ApiTransportTests(TransportFixture):
    def test_same_controller_two_robot_pools_and_terminal_reconnect_catchup(self):
        self.lua.execute('''
            A.duration=0.5;B.duration=2
            local client=C.require('craft_client')
            spawn(function() C.first=client.runDetailed({requestItem='t:target'},{serverAddress='robot-a'}) end,C)
            spawn(function() C.second=client.runDetailed({requestItem='t:target'},{serverAddress='robot-b'}) end,C)
            untilDone(function() return C.first end)
            assert(C.first.success and not C.second and B.started<A.ended)
            untilDone(function() return C.second end);assert(C.second.success)
            local net=C.require('tnet');local base=net.connect
            net.connect=function(...) C.conn=base(...);return C.conn end
            -- A new robot/address gets its own pool. Drop its terminal event and
            -- close client after server completion; reconnect must use status only.
            local r=peer('catchup');server(r);pairHost(C,r);advance(0.1)
            local send=r.modem.send
            r.modem.send=function(to,port,wake,info,msg,data)
                if msg=='ps' and r.require('serialization').unserialize(data).args[3].status=='COMPLETE' then
                    C.conn:close();return true
                end
                return send(to,port,wake,info,msg,data)
            end
            job(C,'catchup');untilDone(function() return C.result end)
            assert(C.result.success and r.executions==1)
            local crafts,statuses=0,0
            for _,m in ipairs(commands('client')) do if m.msg=='rpc' then
                if m.args[2]=='craft' and m.args[4][2]==C.result.jobId then crafts=crafts+1 end
                if m.args[2]=='status' and m.args[4][1]==C.result.jobId then statuses=statuses+1 end
            end end
            assert(crafts==1 and statuses==1)
        ''')

    def test_immediate_query_reconnect_default_id(self):
        self.lua.execute('''
            local net=C.require('tnet');local base=net.connect
            net.connect=function(...) C.conn=base(...);return C.conn end
            job(C,'robot-a');untilDone(function() return C.result end)
            C.conn:close()
            query(C,'robot-a',C.result.jobId,{connectTimeout=0.3})
            untilDone(function() return C.queryResult end)
            local trace={}
            for _,m in ipairs(TRACE) do if m.args[2]:match(',[cda]$') then
                trace[#trace+1]=m.from..'->'..tostring(m.to)..':'..m.args[2]
            end end
            IMMEDIATE_TRACE=table.concat(trace,'\\n')
            IMMEDIATE_RESULT=C.queryResult.message
            IMMEDIATE_SUCCESS=C.queryResult.success
        ''')
        print('IMMEDIATE TRACE:', self.lua.globals().IMMEDIATE_TRACE)
        print('IMMEDIATE RESULT:', self.lua.globals().IMMEDIATE_RESULT)
        self.assertTrue(self.lua.globals().IMMEDIATE_SUCCESS)

    def test_pooled_jobs_and_live_status(self):
        self.lua.execute('''
            A.duration=0.5;B.duration=2
            local net=C.require('tnet');local base=net.connect
            net.connect=function(address,...) local c=base(address,...);C[address]=c;return c end
            job(C,'robot-a');local second=peer('second');pairHost(second,B);job(second,'robot-b')
            untilDone(function() return A.executions==1 and B.executions==1 end)
            local id
            for _,m in ipairs(commands('client')) do
                if m.msg=='rpc' and m.args[1]=='rpc_call' and m.args[2]=='craft' then id=m.args[4][2] end
            end
            query(C,'robot-a',id);untilDone(function() return C.queryResult end)
            assert(C.queryResult.status=='running')
            untilDone(function() return C.result end)
            assert(C.result.success and not second.result and C['robot-a'].connected)
            C.queryResult=nil;query(C,'robot-a',id)
            untilDone(function() return C.queryResult end)
            assert(C.queryResult.success and C['robot-a'].connected)
            C.result=nil;job(C,'robot-a');untilDone(function() return C.result end)
            assert(C.result.success and A.executions==2)
            untilDone(function() return second.result end);assert(second.result.success)
            local connects=0
            for _,m in ipairs(TRACE) do if m.from=='client' and m.args[2]:match(',c$') then connects=connects+1 end end
            assert(connects==1,'long-lived proxy must be reused')
        ''')

    def test_reconnect_default_id_trace(self):
        self.lua.execute('''
            A.duration=2
            local net=C.require('tnet');local base=net.connect
            net.connect=function(...) C.conn=base(...);return C.conn end
            job(C,'robot-a',{connectTimeout=0.3,jobTimeout=5})
            untilDone(function() return A.executions==1 end)
            C.conn:close()
            untilDone(function() return C.result end)
            RECONNECT_TRACE={}
            for _,m in ipairs(TRACE) do if m.args[2]:match(',[cda]$') then
                RECONNECT_TRACE[#RECONNECT_TRACE+1]=m.from..'->'..tostring(m.to)..':'..m.args[2]
            end end
            RECONNECT_RESULT=C.result.message
            RECONNECT_SUCCESS=C.result.success
            advance(3)
            assert(A.executions==1 and A.cleanups==0)
        ''')
        print('RECONNECT TRACE:', list(self.lua.globals().RECONNECT_TRACE.values()))
        print('RECONNECT RESULT:', self.lua.globals().RECONNECT_RESULT)
        self.assertTrue(self.lua.globals().RECONNECT_SUCCESS)
