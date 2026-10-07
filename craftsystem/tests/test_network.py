from test_support import LuaCase


class NetworkFixture(LuaCase):
    def setUp(self):
        super().setUp()
        self.module('cbor', 'lib/cbor.lua')
        self.lua.execute("""
            WIRE,TIMERS,OPEN,SIGNALS={}, {}, {}, {}
            local n=0
            package.preload.uuid=function() return {next=function() n=n+1;return 'id'..n end} end
            MODEM={address='local',isOpen=function(p) return OPEN[p] end,open=function(p) OPEN[p]=true;return true end,
                close=function(p) OPEN[p]=nil end,send=function(to,port,tag,msg)
                    if SEND_FAIL then return false,'send failure' end
                    table.insert(WIRE,{to=to,port=port,packet=require('cbor').decode(msg)});return true
                end,
                broadcast=function(port,tag,msg) table.insert(WIRE,{port=port,packet=require('cbor').decode(msg)});return true end}
            package.preload.component=function() return {modem=MODEM} end
            package.preload.event=function() return {
                listen=function(_,cb) RECEIVE=cb;return true end,ignore=function() RECEIVE=nil;return true end,
                timer=function(_,cb) local id=#TIMERS+1;TIMERS[id]=cb;return id end,
                cancel=function(id) TIMERS[id]=false;return true end
            } end
            package.preload.computer=function() return {uptime=function() return 1 end,pushSignal=function(...) table.insert(SIGNALS,{...}) end} end
        """)
        self.module('gatenet', 'lib/gatenet.lua')
        self.lua.execute("""
            NET=require('gatenet').new();NET:startListener()
            function deliver(typ,cid,payload,pid,src)
                RECEIVE('modem_message','local','remote',5990,1,'gnt',require('cbor').encode({
                    hdr={v=1,s=src or 'remote',c=cid,p=pid or 'packet',t=typ},pld=payload}))
            end
            function connected()
                local p=NET:connect('remote',5990,{})
                p:next(function() end):next(function(self) self:looping(true) end)
                deliver('CAC','cid',{ackPID=WIRE[1].packet.hdr.p},'ack')
                return p
            end
        """)


class NetworkTests(NetworkFixture):
    def test_shutdown_does_not_reopen_ports(self):
        self.assertEqual(self.lua.execute("local p=connected();NET:shutdown();return OPEN[5990]==nil,next(NET._openPorts)==nil,p:isActive(),RECEIVE==nil"), (True, True, False, True))

    def test_reentrant_catch_finalizes_exactly_once(self):
        self.assertEqual(self.lua.execute("""
            local p=connected();local n=0
            p:catch(function(self) self:disconnect() end):finally(function() n=n+1 end)
            deliver('DIS','cid',{},'bye');return n,p:isActive()
        """), (1, False))

    def test_finalizer_can_disconnect_without_recursing(self):
        self.assertEqual(self.lua.execute("local p=connected();local n=0;p:finally(function(self) n=n+1;self:disconnect() end);p:disconnect();return n,p:isActive()"), (1, False))

    def test_rejection_without_connection_id_reaches_client(self):
        self.assertEqual(self.lua.execute("""
            local caught=false;local p=NET:connect('remote',5990,{})
            p:catch(function() caught=true end)
            deliver('CRJ',nil,{ackPID=WIRE[1].packet.hdr.p},'reject')
            return caught,p:isActive()
        """), (True, False))

    def test_callback_exception_rejects_and_finalizes(self):
        self.assertEqual(self.lua.execute("""
            local caught,done=false,false;local p=NET:connect('remote',5990,{})
            p:next(function() error('broken callback') end):catch(function() caught=true end):finally(function() done=true end)
            deliver('CAC','cid',{ackPID=WIRE[1].packet.hdr.p},'ack')
            return caught,done,p:isActive()
        """), (True, True, False))

    def test_local_callback_failure_notifies_peer_to_stop(self):
        self.assertEqual(self.lua.execute("""
            local p=NET:connect('remote',5990,{})
            p:next(function() end):next(function() error('failed update handling') end)
            deliver('CAC','cid',{ackPID=WIRE[1].packet.hdr.p},'ack')
            deliver('DAT','cid',{status='WORKING'},'work')
            return p:isActive(),WIRE[#WIRE].packet.hdr.t
        """), (False, 'DIS'))

    def test_clear_timeout_cancels_handshake_timer(self):
        self.assertEqual(self.lua.execute("local p=connected();p:timeout(10);p:clearTimeout();return TIMERS[1]==false,p:isActive()"), (True, True))

    def test_failed_send_rejects_promise(self):
        self.assertEqual(self.lua.execute("local p=connected();SEND_FAIL=true;p:sendData({command='craft'});return p:isActive()"), False)

    def test_spoofed_header_sender_not_accepted(self):
        self.assertEqual(self.lua.execute("""
            local called=false;NET:listen(NET.INTERNAL_EVENT_NAMES.CONNECTION_REQUEST,function() called=true end)
            deliver('CRQ',nil,{},'request','different-address');return called
        """), False)

    def test_duplicate_data_is_ignored(self):
        self.assertEqual(self.lua.execute("""
            local count=0;local p=NET:connect('remote',5990,{})
            p:next(function() end):next(function(self) self:looping(true);count=count+1 end)
            deliver('CAC','cid',{ackPID=WIRE[1].packet.hdr.p},'ack')
            deliver('DAT','cid',{},'same');deliver('DAT','cid',{},'same');return count
        """), 1)
