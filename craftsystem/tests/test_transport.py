"""Focused peer/event harness running the frozen tnet and OpenOS serialization."""
from test_support import LuaCase, ROOT


class TransportFixture(LuaCase):
    def setUp(self):
        super().setUp()
        for name in ('tnet', 'api', 'pubsub', 'hosts', 'craft_client', 'craft_receipts', 'mes_config',
                     'craft_plan', 'item_identity', 'craft_tool_rules', 'craft_tool_budget',
                     'craft_execution', 'craft_blueprint', 'craft_resources'):
            self.lua.globals()[name.upper() + '_SOURCE'] = (ROOT / 'usr/lib' / (name + '.lua')).read_text()
        self.lua.globals().CPROC_SOURCE = (ROOT / 'usr/bin/cproc.lua').read_text()
        serial_path = ROOT.parent / '.cache/oc-source/src/main/resources/assets/opencomputers/loot/openos/lib/serialization.lua'
        self.lua.globals().SERIALIZATION_SOURCE = serial_path.read_text()
        self.lua.execute(r'''
            NOW, TASKS, PACKETS, TRACE, PEERS, PEER_ID = 0, {}, {}, {}, {}, 0
            function spawn(fn, peer)
                local t={co=coroutine.create(fn),due=NOW,peer=peer}
                TASKS[#TASKS+1]=t;return t
            end
            function peer(address)
                local p={address=address,listeners={},timers={},open={},loaded={},seq=0,
                    executions=0,cleanups=0,duration=1,progressEvery=0.2,success=true,disk={}}
                PEER_ID=PEER_ID+1;p.cid=address..'-'..string.format('%04x0000',PEER_ID)
                PEERS[address]=p
                local env=setmetatable({package={loaded=p.loaded},print=function() end},{__index=_G})
                env._G=env
                env.os=setmetatable({sleep=function(n) coroutine.yield(n or 0.01) end},{__index=os})
                env.os.exit=function(code) p.exitCode=code;error('PAIR_EXIT',0) end
                local function send(to,port,...)
                    if p.sendThrow then error('modem send exception') end
                    local msg={from=address,to=to,port=port,args=table.pack(...)}
                    TRACE[#TRACE+1]=msg;PACKETS[#PACKETS+1]=msg;return true
                end
                p.modem={address=address,open=function(port)
                    if p.open[port] then return false end
                    p.open[port]=true;return true
                end,isOpen=function(port) return p.open[port]==true end,
                    close=function(port) p.open[port]=nil;return true end,
                    send=send,broadcast=function(port,...) return send(nil,port,...) end}
                p.event={listen=function(name,cb)
                    if p.listenFail then return false end
                    p.listeners[name]=p.listeners[name] or {};p.listeners[name][cb]=true;return true
                end,ignore=function(name,cb)
                    if p.ignoreThrow then error('ignore exception') end
                    if p.listeners[name] then p.listeners[name][cb]=nil end;return true
                end,pull=function(n) coroutine.yield(n or 0.01) end,
                push=function(name,...) emit(p,name,...) end,
                timer=function(n,cb,times)
                    p.seq=p.seq+1;p.timers[p.seq]={due=NOW+n,interval=n,cb=cb,left=times or 1};return p.seq
                end,cancel=function(id) p.timers[id]=nil;return true end}
                local function open(path,mode)
                    if mode=='r' then return {read=function() return p.disk[path] end,close=function() end} end
                    return {write=function(_,data) p.disk[path]=data end,close=function() end}
                end
                local fs={exists=function(path) return path=='/etc' or p.disk[path]~=nil end,
                    makeDirectory=function() return true end,open=open}
                local modules={event=p.event,component={modem=p.modem,computer={address=p.cid}},
                    computer={uptime=function() return NOW end,address=function() return p.cid end},
                    sides={front=3},shell={parse=function() return p.args or {},p.options or {} end},filesystem=fs,io={open=open},
                    uuid={next=function() p.seq=p.seq+1;return address..'-job-'..p.seq end}}
                modules.craft_executor={validatePlan=function(plan) return type(plan)=='table' and not plan.invalid,'invalid plan' end,
                    dumpInventory=function()
                        if p.booting then p.bootCleanups=(p.bootCleanups or 0)+1;p.booting=false
                        else p.cleanups=p.cleanups+1 end
                        if p.dumpThrow then error('dump exception') end
                        return not p.dumpFail,'storage blocked'
                    end,
                    executePlan=function(plan,opts)
                        assert(coroutine.running()==p.main.co,'execution must be in cproc main loop')
                        p.executions=p.executions+1;p.started=NOW
                        local untilTime=NOW+p.duration
                        while NOW<untilTime do
                            if not opts.shouldContinue() then p.ended=NOW;return false,'cancelled execution' end
                            if p.executionThrow then error('execution exception') end
                            opts.onProgress('working '..address)
                            env.os.sleep(p.progressEvery)
                        end
                        p.ended=NOW;if p.success then return true end;return false,'execution failed'
                    end}
                function env.require(name)
                    if p.loaded[name] then return p.loaded[name] end
                    local m=modules[name]
                    if not m then
                        local src=_G[name:upper()..'_SOURCE'];assert(src,'missing module '..name)
                        m=assert(load(src,name,'t',env))()
                    end
                    p.loaded[name]=m;return m
                end
                p.env=env;p.require=env.require
                p.require('hosts').addHost(address,p.cid,address,'wake-'..address,{},true)
                return p
            end
            function server(p)
                p.booting=true
                p.main=spawn(function() assert(load(CPROC_SOURCE,'cproc','t',p.env))() end,p)
            end
            function job(p,robot,options,plan)
                options=options or {};options.serverAddress=robot
                local t=spawn(function() p.result=p.require('craft_client').runDetailed(plan or {requestItem='t:target'},options) end,p)
                return t
            end
            function query(p,robot,id,options)
                return spawn(function() p.queryResult=p.require('craft_client').query(robot,id,options) end,p)
            end
            function emit(p,name,...)
                local args=table.pack(...)
                for cb in pairs(p.listeners[name] or {}) do
                    spawn(function() cb(name,table.unpack(args,1,args.n)) end,p)
                end
            end
            function tick()
                local packets=PACKETS;PACKETS={}
                for _,msg in ipairs(packets) do
                    for address,p in pairs(PEERS) do
                        if address~=msg.from and (not msg.to or msg.to==address) and p.open[msg.port] then
                            emit(p,'modem_message',address,msg.from,msg.port,1,table.unpack(msg.args,1,msg.args.n))
                        end
                    end
                end
                for _,p in pairs(PEERS) do
                    for id,t in pairs(p.timers) do if NOW>=t.due then
                        t.left=t.left-1
                        if t.left<=0 then p.timers[id]=nil else t.due=NOW+t.interval end
                        spawn(t.cb,p)
                    end end
                end
                local current=TASKS;TASKS={}
                for _,t in ipairs(current) do
                    if NOW>=t.due then
                        local ok,delay=coroutine.resume(t.co)
                        assert(ok,delay)
                        if coroutine.status(t.co)~='dead' then t.due=NOW+(delay or 0.01);TASKS[#TASKS+1]=t end
                    else TASKS[#TASKS+1]=t end
                end
                NOW=NOW+0.01
            end
            function advance(seconds) local stop=NOW+seconds;while NOW<stop do tick() end end
            function untilDone(predicate,seconds)
                local stop=NOW+(seconds or 20)
                while not predicate() and NOW<stop do tick() end
                assert(predicate(),'test event deadline exhausted')
            end
            function countListeners(p,name) local n=0;for _ in pairs(p.listeners[name] or {}) do n=n+1 end;return n end
            function commands(from)
                local out={}
                for _,m in ipairs(TRACE) do
                    if m.from==from and m.args[2] and m.args[2]:match(',m$') then
                        out[#out+1]=PEERS[from].require('serialization').unserialize(m.args[4])
                    end
                end
                return out
            end
            function pairHost(controller,robot)
                controller.require('hosts').addHost(robot.address,robot.cid,robot.address,'wake-'..robot.address,{service='craftServer'},true)
            end
            A=peer('robot-a');B=peer('robot-b');C=peer('client');pairHost(C,A);pairHost(C,B)
            server(A);server(B);advance(0.1)
        ''')


class ConcurrentTransportTests(TransportFixture):
    def test_default_id_reconnect_uses_authorized_monotonic_allocator(self):
        self.lua.execute('''
            local net=C.require('tnet');local base=net.connect
            net.connect=function(...) C.conn=base(...);return C.conn end
            job(C,'robot-a');untilDone(function() return C.result end)
            C.conn:close()
            query(C,'robot-a',C.result.jobId,{connectTimeout=0.3})
            untilDone(function() return C.queryResult end)
            assert(C.queryResult.status=='complete' and A.executions==1)
            local ids={}
            for _,m in ipairs(TRACE) do if m.args[2]:match(',[cda]$') then
                if m.from=='client' and m.args[2]:match(',c$') then ids[#ids+1]=m.args[2] end
            end end
            assert(#ids==2 and ids[1]~=ids[2])
        ''')

    def test_two_jobs_first_close_keeps_second_and_live_query(self):
        self.lua.execute('''
            A.duration=0.5;B.duration=2
            job(C,'robot-a',{idleTimeout=0.4,jobTimeout=4})
            local c2=peer('second-client');pairHost(c2,B);job(c2,'robot-b',{idleTimeout=0.4,jobTimeout=4})
            untilDone(function() return A.executions==1 and B.executions==1 end)
            assert(B.ended==nil)
            local id
            for _,m in ipairs(commands('second-client')) do
                if m.msg=='rpc' and m.args[2]=='craft' then id=m.args[4][2] end
            end
            -- Direct status command on the very same busy connection, twice.
            local conn
            -- Connection is reachable by its original connect result through a test observer.
            local observer=peer('observer')
            local live=spawn(function()
                local proxy=observer.require('api').connect('craftServer',5990,'robot-b','wake-robot-b',1)
                conn=proxy:getConnection()
                local ok,r=proxy.status(id);assert(ok);observer.status=r
            end,observer)
            untilDone(function() return observer.status end)
            assert(observer.status.status=='FAILED','different owner must be rejected')
            conn:close()
            untilDone(function() return C.result end)
            assert(C.result.success and not c2.result and B.ended==nil)
            assert(countListeners(c2,'modem_message')==1)
            untilDone(function() return c2.result end)
            assert(c2.result.success and A.started<B.ended and B.started<A.ended)
            assert(A.executions==1 and B.executions==1)
        ''')

    def test_live_connection_status_and_duplicate_receipts_are_persistent(self):
        self.lua.execute('''
            local net=C.require('tnet');local base=net.connect
            net.connect=function(...) C.conn=base(...);return C.conn end
            A.duration=2;job(C,'robot-a')
            untilDone(function() return A.executions==1 end)
            local id
            for _,m in ipairs(commands('client')) do if m.msg=='rpc' and m.args[2]=='craft' then id=m.args[4][2] end end
            query(C,'robot-a',id);untilDone(function() return C.queryResult end)
            assert(C.queryResult.status=='running');C.queryResult=nil
            query(C,'robot-a',id);untilDone(function() return C.queryResult end)
            assert(C.queryResult.status=='running' and A.executions==1)
            local duplicate=spawn(function()
                C.duplicate=C.require('craft_client').runDetailed({requestItem='t:target'}, {serverAddress='robot-a',jobId=id})
            end,C)
            untilDone(function() return C.result end);assert(C.result.success)
            untilDone(function() return C.duplicate end);assert(C.duplicate.success and A.executions==1)
        ''')

    def test_repeated_status_listing_coexists_with_live_job_and_listener(self):
        self.lua.execute('''
            A.duration=2;job(C,'robot-a');untilDone(function() return A.executions==1 end)
            assert(C.require('tnet').listen(6000,function() end))
            spawn(function()
                for _=1,3 do local robots=C.require('mes_config').robots(0.1)
                    assert(#robots==2 and robots[1].address=='robot-a' and robots[2].address=='robot-b')
                    assert(type(robots[1].busy)=='boolean' and robots[2].busy==false)
                end
                C.listed=true
            end,C)
            untilDone(function() return C.listed end)
            assert(countListeners(C,'modem_message')==1 and C.open[5990])
            untilDone(function() return C.result end);assert(C.result.success)
            local another=peer('another');spawn(function()
                local conn=another.require('tnet').connect('client',6000)
                assert(conn:init(1));conn:close();another.finished=true
            end,another)
            untilDone(function() return another.finished end)
        ''')
