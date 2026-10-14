"""Service ownership regression with frozen network and actual OpenOS event.lua.

Expands .taskreports/T13-thread-owner-repro.py: callers exit, while one installed
service owns listeners, API async timers and reconnects. No OpenOS threads load.
Physical MES state-machine regressions belong to the core/service lane.
"""
from test_transport import TransportFixture
from test_support import ROOT


class MesTransportOwnerTests(TransportFixture):
    def test_robot_pushes_busy_and_idle_and_finished_client_has_no_deadline(self):
        self.lua.execute('''
            wave('push');untilDone(function() return C.terminals.pusha and C.terminals.pushb end)
            advance(0.1)
            local busy,idle,statuses=false,false,0
            for _,f in ipairs(C.facts) do if f.what=='robot_status' and not f.token and f.data.address=='robot-a' then
                busy=busy or f.data.busy==true;idle=idle or f.data.busy==false
            end end
            for _,m in ipairs(commands('client')) do if m.msg=='rpc' and m.args[2]=='status' then statuses=statuses+1 end end
            assert(busy and idle and statuses==0 and C.client.nextDue()==nil)
        ''')

    def test_adopt_running_job_sends_no_second_craft(self):
        self.lua.execute('''
            A.duration=2
            C.command=function(client) assert(client.begin('original','robot-a',{},'adopt-live')) end
            untilDone(function() return A.executions==1 end)
            C.command=function(client) assert(client.adopt('restored','robot-a','adopt-live')) end
            untilDone(function() return C.terminals.restored end)
            assert(C.terminals.restored.success and A.executions==1)
            local crafts,statuses,progress=0,0,false
            for _,m in ipairs(commands('client')) do if m.msg=='rpc' then
                if m.args[2]=='craft' then crafts=crafts+1 end
                if m.args[2]=='status' then statuses=statuses+1 end
            end end
            for _,f in ipairs(C.facts) do if f.token=='restored' and f.what=='robot_progress' then progress=true end end
            assert(crafts==1 and statuses>=1 and progress and #C.errors==0)
        ''')

    def test_adopt_complete_and_failed_cached_receipts(self):
        for success in (True, False):
            with self.subTest(success=success):
                self.setUp()
                self.lua.globals().SUCCESS = success
                self.lua.execute('''
                    A.success=SUCCESS;A.duration=0.2
                    C.command=function(client) assert(client.begin('original','robot-a',{},'adopt-cached')) end
                    untilDone(function() return C.terminals.original end)
                    C.command=function(client) assert(client.adopt('restored','robot-a','adopt-cached')) end
                    untilDone(function() return C.terminals.restored end)
                    assert(C.terminals.restored.success==SUCCESS and A.executions==1)
                    local crafts=0;for _,m in ipairs(commands('client')) do
                        if m.msg=='rpc' and m.args[2]=='craft' then crafts=crafts+1 end
                    end
                    assert(crafts==1 and #C.errors==0)
                ''')

    def test_adopt_disconnected_not_found_without_craft(self):
        self.lua.execute('''
            untilDone(function() return C['robot-a']~=nil end)
            C['robot-a']:close()
            C.client.announce('robot-a')
            C.command=function(client) assert(client.adopt('restored','robot-a','missing-at-boot')) end
            untilDone(function() return C.terminals.restored end)
            local d=C.terminals.restored
            assert(d.unknown and d.receipt.status=='NOT_FOUND' and A.executions==0)
            local crafts=0;for _,m in ipairs(commands('client')) do
                if m.msg=='rpc' and m.args[2]=='craft' then crafts=crafts+1 end
            end
            assert(crafts==0 and #C.errors==0)
        ''')

    def setUp(self):
        super().setUp()
        oc = ROOT.parent / '.cache/oc-source/src/main/resources/assets/opencomputers/loot/openos/lib'
        self.lua.globals().OC_EVENT = (oc / 'event.lua').read_text()
        self.lua.globals().EMPTY_HOSTS = self._testMethodName == 'test_install_zero_hosts_then_pair_two_and_answer_four_jobs'
        self.lua.execute(r'''
            C.signals={};C.created={};C.facts={};C.errors={};C.terminals={};C.responses={}
            C.tickConnections={}
            if EMPTY_HOSTS then
                C.require('hosts').removeHost('robot-a');C.require('hosts').removeHost('robot-b')
            end
            local oldEmit=emit
            emit=function(p,name,...)
                if p~=C then return oldEmit(p,name,...) end
                C.signals[#C.signals+1]=table.pack(name,...)
            end
            C.main=spawn(function()
                local computer=C.require('computer')
                computer.pushSignal=function(...) emit(C,...);return true end
                computer.pullSignal=function(n)
                    if #C.signals>0 then local s=table.remove(C.signals,1);return table.unpack(s,1,s.n) end
                    coroutine.yield(n or 0.01)
                    if #C.signals>0 then local s=table.remove(C.signals,1);return table.unpack(s,1,s.n) end
                end
                C.loaded.package={delay=function() end}
                C.loaded.keyboard={isControlDown=function() return false end,keys={c=46}}
                C.loaded.event=assert(load(OC_EVENT,'OpenOS/event','t',C.env))()
                C.event=C.loaded.event
                C.event.timer=function(n,cb,times) return C.event.register(false,cb,n,times) end
                C.event.cancel=function(id) C.event.handlers[id]=nil end
                C.event.onError=function(err) C.errors[#C.errors+1]=err end
                local pull=C.event.pull
                C.event.pull=function(...)
                    assert(not C.advancing and not C.inFact,debug.traceback('action/fact callback blocked'))
                    return pull(...)
                end
                C.env.os.sleep=function(n) return C.event.pull(n or 0.01) end
                local net=C.require('tnet');local connect=net.connect
                net.connect=function(address,...)
                    assert(coroutine.running()==C.main.co,'transport created outside service')
                    assert(not C.advancing,'action opened transport')
                    C.created[#C.created+1]=address
                    local conn=connect(address,...);C[address]=conn;return conn
                end
                local client=C.require('craft_client');C.client=client
                C.sink=function(token,what,data)
                    assert(not C.inFact,'reentrant fact sink')
                    C.inFact=true
                    assert(data.at==NOW,'fact did not retain arrival timestamp')
                    C.facts[#C.facts+1]={token=token,what=what,data=data}
                    if what=='robot_terminal' then C.terminals[token]=data end
                    if what=='robot_status' and token then C.responses[token]=data end
                    C.inFact=false
                end
                C.rows=client.install(C.sink,{connectTimeout=0.2})
                C.installs=#C.created
                assert(client.install(C.sink)==C.rows and #C.created==C.installs)
                local pumping=false
                C.event.timer(0.02,function()
                    if pumping then return end
                    pumping=true
                    local before=#C.created
                    client.tick(NOW)
                    C.tickConnections[#C.tickConnections+1]=#C.created-before
                    if C.command then
                        local command=C.command;C.command=nil
                        C.advancing=true;command(client);C.advancing=false
                    end
                    pumping=false
                end,math.huge)
                C.ready=true
                while not C.stop do C.event.pull(0.01) end
            end,C)
            untilDone(function() return C.ready end)
            function wave(prefix)
                C.frontend=spawn(function()
                    C.command=function(client)
                        assert(client.begin(prefix..'a','robot-a',{requestItem='t:target'},prefix..'job-a'))
                        assert(client.begin(prefix..'b','robot-b',{requestItem='t:target'},prefix..'job-b'))
                    end
                end,C)
            end
        ''')

    def test_first_two_then_next_two_jobs_survive_frontend_exit(self):
        self.lua.execute('''
            wave('first');untilDone(function() return A.executions==1 and B.executions==1 end)
            assert(coroutine.status(C.frontend.co)=='dead')
            assert(not C.terminals.firsta and not C.terminals.firstb)
            untilDone(function() return C.terminals.firsta and C.terminals.firstb end)
            assert(C.terminals.firsta.success and C.terminals.firstb.success)
            wave('next');untilDone(function() return C.terminals.nexta and C.terminals.nextb end)
            assert(C.terminals.nexta.success and C.terminals.nextb.success)
            assert(A.executions==2 and B.executions==2 and #C.created==2)
            assert(A.started<B.ended and B.started<A.ended)
            assert(#C.errors==0,table.concat(C.errors,'; '))
            assert(C.loaded.thread==nil and C.loaded.process==nil)
            local count=0
            for _,h in pairs(C.event.handlers) do if h.key=='modem_message' then count=count+1 end end
            assert(count==1)
            local sent=commands('client')
            for i,m in ipairs(sent) do if m.msg=='rpc' and m.args[2]=='craft' then
                assert(sent[i-1].msg=='ps' and sent[i-1].args[1]=='sub')
            end end
        ''')

    def test_announce_after_drop_connects_once_and_status_only_catches_up(self):
        self.lua.execute('''
            A.duration=1;B.duration=2
            wave('drop');untilDone(function() return A.executions==1 and B.executions==1 end)
            C['robot-a']:close()
            C.client.announce('robot-a')
            untilDone(function() return C.terminals.dropa and C.terminals.dropb end)
            assert(C.terminals.dropa.success and C.terminals.dropb.success and #C.created==3)
            assert(A.executions==1 and B.executions==1 and #C.errors==0)
            local crafts,statuses=0,0
            for _,m in ipairs(commands('client')) do if m.msg=='rpc' then
                if m.args[2]=='craft' and m.args[4][2]=='dropjob-a' then crafts=crafts+1 end
                if m.args[2]=='status' and m.args[4][1]=='dropjob-a' then statuses=statuses+1 end
            end end
            assert(crafts==1 and statuses>=1)
        ''')

    def test_close_reports_once_without_connecting_until_announce(self):
        self.lua.execute('''
            local before=#C.facts;local connections=#C.created
            C['robot-a']:close();C['robot-a']:close()
            local closed=0
            for i=before+1,#C.facts do local f=C.facts[i]
                if f.what=='robot_transport' and f.data.address=='robot-a' and f.data.state=='disconnected' then closed=closed+1 end
            end
            assert(closed==1 and not C.rows[1].connected)
            advance(1)
            assert(#C.created==connections and C.client.nextDue()==nil)
            C.client.announce('robot-a')
            untilDone(function() return C.rows[1].connected end)
            assert(#C.created==connections+1 and #C.errors==0)
        ''')

    def test_close_during_status_finishes_unknown_without_a_stale_deadline(self):
        self.lua.execute('''
            A.duration=10
            C.command=function(client) assert(client.begin('closing','robot-a',{},'closing-job')) end
            untilDone(function() return A.executions==1 end)
            C.command=function(client)
                assert(client.inspect('closing','robot-a','closing-job'))
                C['robot-a']:close()
            end
            untilDone(function() return C.terminals.closing end,1)
            assert(C.terminals.closing.unknown and C.responses.closing.unknown)
            assert(C.client.nextDue()==nil and #C.created==C.installs and A.executions==1)
        ''')

    def test_actions_never_connect_uninstalled_robot(self):
        self.lua.execute('''
            local third=peer('robot-c');server(third);pairHost(C,third)
            local ok,err=C.client.begin('unprepared','robot-c',{},'unprepared-job')
            local inspected,why=C.client.inspect('unprepared','robot-c')
            assert(not ok and err:find('installation'))
            assert(not inspected and why:find('installation'))
            assert(#C.created==2 and third.executions==0 and #C.errors==0)
        ''')

    def test_install_zero_hosts_then_pair_two_and_answer_four_jobs(self):
        self.lua.execute('''
            assert(#C.rows==0 and #C.created==0)
            pairHost(C,A);pairHost(C,B)
            C.client.announce(A.address);C.client.announce(B.address)
            untilDone(function() return #C.rows==2 and C.rows[1].connected and C.rows[2].connected end)
            assert(#C.rows==2 and C.rows[1].connected and C.rows[2].connected)
            wave('late1');untilDone(function() return C.terminals.late1a and C.terminals.late1b end)
            wave('late2');untilDone(function() return C.terminals.late2a and C.terminals.late2b end)
            assert(C.terminals.late1a.success and C.terminals.late1b.success)
            assert(C.terminals.late2a.success and C.terminals.late2b.success)
            assert(A.executions==2 and B.executions==2 and #C.created==2 and #C.errors==0)
        ''')

    def test_dynamic_eight_robot_fleet_is_not_size_capped(self):
        self.lua.execute('''
            local robots={A,B}
            for i=3,8 do local robot=peer('robot-'..i);server(robot);pairHost(C,robot);C.client.announce(robot.address);robots[#robots+1]=robot end
            untilDone(function() return #C.rows==8 and #C.created==8 and C['robot-8'].connected end)
            C.command=function(client)
                for i,robot in ipairs(robots) do
                    assert(client.begin('fleet-'..i,robot.address,{},'fleet-job-'..i))
                end
            end
            untilDone(function()
                for i=1,8 do if not C.terminals['fleet-'..i] then return false end end;return true
            end)
            for i,robot in ipairs(robots) do assert(C.terminals['fleet-'..i].success and robot.executions==1) end
            for _,count in ipairs(C.tickConnections) do assert(count<=1,'unbounded connect work in tick') end
            assert(#C.created==8 and #C.errors==0)
        ''')

    def test_offline_announces_attempt_once_without_retry_timer(self):
        self.lua.execute('''
            for i=1,8 do
                C.require('hosts').addHost('offline-'..i,'offline-cid-'..i,'offline-'..i,'wake-offline-'..i,{service='craftServer'},true)
                C.client.announce('offline-'..i)
            end
            wave('live')
            untilDone(function() return C.terminals.livea and C.terminals.liveb and #C.created>=10 end,8)
            assert(C.terminals.livea.success and C.terminals.liveb.success)
            local attempted={}
            for _,address in ipairs(C.created) do attempted[address]=true end
            for i=1,8 do assert(attempted['offline-'..i],'offline peer starved') end
            for _,count in ipairs(C.tickConnections) do assert(count<=1,'offline fleet blocked one tick N times') end
            local attempts=#C.created;advance(3);assert(#C.created==attempts)
            assert(#C.errors==0)
        ''')

    def test_busy_idle_and_unanswered_status_unknown_never_idle(self):
        self.lua.execute('''
            wave('busy');untilDone(function() return A.executions==1 and B.executions==1 end)
            C.command=function(client) assert(client.inspect('busy-inspection','robot-a')) end
            untilDone(function() return C.responses['busy-inspection'] end)
            local busy=C.responses['busy-inspection']
            assert(busy.busy==true and type(busy.currentJobId)=='string')
            untilDone(function() return C.terminals.busya and C.terminals.busyb end)
            C.command=function(client) assert(client.inspect('idle-inspection','robot-a')) end
            untilDone(function() return C.responses['idle-inspection'] end)
            local idle=C.responses['idle-inspection']
            assert(idle.busy==false and idle.currentJobId==nil)
            local send=A.modem.send
            A.modem.send=function(to,port,wake,info,msg,...)
                if msg=='rpc' then return true end
                return send(to,port,wake,info,msg,...)
            end
            C.command=function(client) assert(client.inspect('lost-inspection','robot-a',nil,{rpcTimeout=0.1})) end
            untilDone(function() return C.responses['lost-inspection'] end)
            assert(C.responses['lost-inspection'].unknown and C.responses['lost-inspection'].busy==nil)
            assert(#C.errors==0)
        ''')

    def test_rpc_deadline_reconciles_status_without_replaying_craft(self):
        self.lua.execute('''
            local send=A.modem.send
            A.modem.send=function(to,port,wake,info,msg,data)
                if msg=='rpc' then
                    local packet=A.require('serialization').unserialize(data)
                    if packet.args[3] and packet.args[3][2]=='accepted' then return true end
                end
                return send(to,port,wake,info,msg,data)
            end
            C.command=function(client)
                assert(client.begin('deadline','robot-a',{},'deadline-job',{rpcTimeout=0.15}))
            end
            untilDone(function() return C.terminals.deadline end)
            assert(C.terminals.deadline.success and A.executions==1)
            local crafts,statuses,unknowns=0,0,0
            for _,m in ipairs(commands('client')) do if m.msg=='rpc' then
                if m.args[2]=='craft' then crafts=crafts+1 end
                if m.args[2]=='status' then statuses=statuses+1 end
            end end
            for _,f in ipairs(C.facts) do if f.token=='deadline' and f.data.unknown then unknowns=unknowns+1 end end
            assert(crafts==1 and statuses>=1 and unknowns>=1 and #C.errors==0)
        ''')

    def test_idle_reads_once_then_fails_without_new_progress(self):
        self.lua.execute('''
            A.duration=2;A.progressEvery=1
            C.command=function(client)
                assert(client.begin('silent-running','robot-a',{},'silent-job',{idleTimeout=0.2,rpcTimeout=0.1}))
            end
            untilDone(function() return C.terminals['silent-running'] end,4)
            assert(C.terminals['silent-running'].unknown and A.executions==1)
            local statuses=0
            for _,m in ipairs(commands('client')) do
                if m.msg=='rpc' and m.args[2]=='status' then statuses=statuses+1 end
            end
            assert(statuses==1 and #C.created==C.installs and #C.errors==0)
        ''')

    def test_idle_unanswered_inspect_fails_without_reconnect(self):
        self.lua.execute('''
            A.duration=10;A.progressEvery=10
            C.command=function(client)
                assert(client.begin('silent','robot-a',{},'silent-job',{idleTimeout=0.2,rpcTimeout=0.1}))
            end
            untilDone(function() return A.executions==1 end)
            local send=A.modem.send
            A.modem.send=function(to,port,wake,info,msg,...)
                if msg=='rpc' then return true end
                return send(to,port,wake,info,msg,...)
            end
            untilDone(function() return C.terminals.silent end,3)
            assert(C.terminals.silent.reason:find('idle timeout',1,true))
            assert(#C.created==C.installs and A.executions==1 and #C.errors==0)
            local statuses=0
            for _,m in ipairs(commands('client')) do
                if m.msg=='rpc' and m.args[2]=='status' then statuses=statuses+1 end
            end
            assert(statuses==1,statuses)
        ''')

    def test_async_timeouts_are_service_owned_after_frontend_exit(self):
        self.lua.execute('''
            local send=A.modem.send
            A.modem.send=function(to,port,wake,info,msg,...)
                if msg=='rpc' then return true end
                return send(to,port,wake,info,msg,...)
            end
            C.frontend=spawn(function()
                C.command=function(client) assert(client.inspect('silent','robot-a',nil,{rpcTimeout=10.1})) end
            end,C)
            untilDone(function() return C.responses.silent end,12)
            assert(coroutine.status(C.frontend.co)=='dead')
            assert(C.responses.silent.unknown and C.responses.silent.busy==nil)
            assert(C.loaded.thread==nil and #C.errors==0)
        ''')

    def test_status_catchup_and_receipts_remain_owner_scoped(self):
        self.lua.execute('''
            wave('owner');untilDone(function() return C.terminals.ownera end)
            local other=peer('other');pairHost(other,A)
            query(other,'robot-a','ownerjob-a');untilDone(function() return other.queryResult end)
            assert(other.queryResult.status=='unknown' and other.queryResult.message:find('different sender'))
            C.command=function(client) assert(client.inspect('owner-query','robot-a','ownerjob-a')) end
            untilDone(function() return C.responses['owner-query'] end)
            assert(C.responses['owner-query'].receipt.status=='COMPLETE')
        ''')

    def test_wrong_owner_lost_rpc_cannot_accept_shared_topic_complete(self):
        self.lua.execute('''
            A.duration=1
            C.command=function(client) assert(client.begin('original','robot-a',{},'shared-id')) end
            untilDone(function() return A.executions==1 end)
            local other=peer('other');pairHost(other,A)
            local send=A.modem.send
            A.modem.send=function(to,port,wake,info,msg,...)
                if to=='other' and msg=='rpc' then return true end
                return send(to,port,wake,info,msg,...)
            end
            spawn(function()
                local client=other.require('craft_client');other.facts={}
                client.install(function(token,what,data)
                    other.facts[#other.facts+1]={token=token,what=what,data=data}
                    if what=='robot_terminal' then other.terminal=data end
                end,{connectTimeout=0.2})
                assert(client.begin('not-owner','robot-a',{},'shared-id',{rpcTimeout=0.2}))
                while not other.stop do client.tick(NOW);other.event.pull(0.02) end
            end,other)
            untilDone(function() return C.terminals.original end)
            advance(0.4)
            assert(C.terminals.original.success and other.terminal.unknown and not other.terminal.success and A.executions==1)
            local unknowns=0
            for _,f in ipairs(other.facts) do
                assert(not (f.token=='not-owner' and f.what=='robot_progress'))
                assert(not (f.token=='not-owner' and f.what=='robot_terminal' and f.data.success))
                if f.token=='not-owner' and f.data.unknown then unknowns=unknowns+1 end
            end
            assert(unknowns>=1,'unverified complete cancelled our RPC deadlines')
            A.modem.send=send
            other.terminal=nil
            assert(other.require('craft_client').adopt('verify-owner','robot-a','shared-id',{rpcTimeout=0.2}))
            untilDone(function() return other.terminal end)
            assert(not other.terminal.success and other.terminal.unknown)
            assert(other.terminal.receipt.status=='FAILED' and other.terminal.reason:find('different sender'))
            local crafts,statuses=0,0
            for _,m in ipairs(commands('other')) do if m.msg=='rpc' then
                if m.args[2]=='craft' then crafts=crafts+1 end
                if m.args[2]=='status' then statuses=statuses+1 end
            end end
            assert(crafts==1 and statuses>=1 and A.executions==1 and #C.errors==0)
            other.stop=true
        ''')

    def test_unanswered_owner_proof_fails_unknown_then_explicit_adoption_recovers(self):
        self.lua.execute('''
            A.duration=0.2
            local send=A.modem.send
            A.modem.send=function(to,port,wake,info,msg,...)
                if to=='client' and msg=='rpc' then return true end
                return send(to,port,wake,info,msg,...)
            end
            C.command=function(client)
                assert(client.begin('rightful','robot-a',{},'rightful-id',{rpcTimeout=0.2}))
            end
            untilDone(function() return A.ended end)
            advance(0.4)
            assert(C.terminals.rightful.unknown and not C.terminals.rightful.success and A.executions==1)
            A.modem.send=send
            C.command=function(client) assert(client.adopt('recovered','robot-a','rightful-id',{rpcTimeout=0.2})) end
            untilDone(function() return C.terminals.recovered end)
            assert(C.terminals.recovered.success and C.terminals.recovered.receipt.receipt==true)
            local crafts,statuses=0,0
            for _,m in ipairs(commands('client')) do if m.msg=='rpc' then
                if m.args[2]=='craft' then crafts=crafts+1 end
                if m.args[2]=='status' then statuses=statuses+1 end
            end end
            assert(crafts==1 and statuses>=1 and A.executions==1 and #C.errors==0)
        ''')

    def test_same_job_status_observer_does_not_replace_live_subscription(self):
        self.lua.execute('''
            A.duration=2;wave('isolation')
            untilDone(function() return A.executions==1 end)
            C.command=function(client) assert(client.inspect('separate-probe','robot-a','isolationjob-a')) end
            untilDone(function() return C.responses['separate-probe'] end)
            assert(C.responses['separate-probe'].receipt.status=='RUNNING')
            untilDone(function() return C.terminals.isolationa and C.terminals.isolationb end)
            assert(C.terminals.isolationa.success and C.terminals.isolationb.success and A.executions==1)
            assert(#C.created==2 and #C.errors==0)
        ''')

    def test_complete_receipt_cancels_silent_admission_deadline(self):
        self.lua.execute('''
            local send=A.modem.send
            A.modem.send=function(to,port,wake,info,msg,data)
                if msg=='rpc' then
                    local packet=A.require('serialization').unserialize(data)
                    if packet.args[3] and packet.args[3][2]=='accepted' then return true end
                elseif msg=='ps' then
                    local packet=A.require('serialization').unserialize(data)
                    if packet.args[3] and packet.args[3].status=='WORKING' then return true end
                end
                return send(to,port,wake,info,msg,data)
            end
            C.command=function(client) assert(client.begin('proven','robot-a',{},'proven-job',{rpcTimeout=3})) end
            untilDone(function() return C.terminals.proven end)
            assert(C.terminals.proven.success)
            local statuses=0
            for _,m in ipairs(commands('client')) do
                if m.msg=='rpc' and m.args[2]=='status' then statuses=statuses+1 end
            end
            assert(statuses>=1,'unconfirmed terminal was accepted without owner-scoped status')
            advance(4)
            for _,f in ipairs(C.facts) do assert(not (f.token=='proven' and f.data.unknown)) end
            assert(A.executions==1 and #C.errors==0)
        ''')
