"""Authorized Renno netbase ports, loaded directly (not installed copies)."""
from pathlib import Path
import test_pubsub
from lupa.lua53 import LuaRuntime

RENNO = Path('C:/Users/Conner/Documents/GitHub/Renno-Programs/tnet/usr/lib')
SERIAL = Path(__file__).resolve().parents[2] / '.cache/oc-source/src/main/resources/assets/opencomputers/loot/openos/lib/serialization.lua'


class NetbaseTests(test_pubsub.PubsubTests):
    def node(self, address):
        lua = LuaRuntime(unpack_returned_tuples=True)
        context = test_pubsub.Context()
        context.addr, context.uptime = address, lambda: self.clock
        context.send = lambda frm, to, port, *args: self.send_packet(to, frm, port, args)
        context.sleep = self.pump
        lua.execute(test_pubsub.SETUP, context, str(RENNO).replace('\\', '/'))
        lua.globals().SERIAL_SOURCE = SERIAL.read_text()
        lua.execute('''
            function checkArg(n,value,...)
                for i=1,select('#',...) do if type(value)==select(i,...) then return end end
                error('bad argument '..n)
            end
            package.preload.serialization=function() return assert(load(SERIAL_SOURCE))() end
            local event=require('event')
            NET_TIMERS={};local seq=0
            event.timer=function(delay,fn,times)
                seq=seq+1
                NET_TIMERS[seq]={due=require('computer').uptime()+delay,fn=fn,delay=delay,left=times or 1}
                return seq
            end
            event.cancel=function(id) NET_TIMERS[id]=nil end
            function fireTimers()
                local now=require('computer').uptime()
                for id,t in pairs(NET_TIMERS) do if now>=t.due then
                    t.left=t.left-1
                    if t.left==0 then NET_TIMERS[id]=nil else t.due=now+t.delay end
                    t.fn()
                end end
            end
        ''')
        self.nodes[address] = lua
        return lua

    def send_packet(self, to, sender, port, args):
        # OC counts strings by byte length and primitive values as eight bytes.
        size = sum(len(x.encode()) if isinstance(x, str) else 8 for x in args)
        self.assertLessEqual(size, 8192, 'physical modem packet limit exceeded')
        self.packet_trace.append((sender, args, size))
        self.queue.append((to, sender, port, args))

    def setUp(self):
        self.packet_trace = []
        super().setUp()

    def pump(self):
        super().pump()
        for node in self.nodes.values():
            node.globals().fireTimers()

    def test_fragmented_craft_rpc_and_pubsub_are_intact(self):
        self.server.execute('''
            endpoint.lib.craft=function(plan,id,retryOnly)
                receivedPlan=plan
                publisher:publish('job:'..id,{status='WORKING',jobId=id,message=plan.large})
                return 'accepted',{status='ACCEPTED',jobId=id,receipt=true}
            end
            endpoint:exposeFunction('craft')
        ''')
        self.assertEqual(self.client.execute('''
            local payload=string.rep('0123456789',2500)
            subscriber:subscribe('job:large',function(r) eventReceipt=r end)
            local ok,kind,r=proxy.craft({large=payload,nested={value=42}},'large',false)
            assert(ok and kind=='accepted' and r.receipt and r.jobId=='large')
            assert(eventReceipt.status=='WORKING' and eventReceipt.message==payload)
            return #payload
        '''), 25000)
        self.assertEqual(self.server.execute('return #receivedPlan.large,receivedPlan.nested.value'), (25000, 42))
        fragments = [p for p in self.packet_trace if len(p[1][1].split(',')) == 6]
        self.assertGreaterEqual(len(fragments), 8)
        self.assertTrue(any(p[0] == self.server_address for p in fragments))
        self.assertTrue(any(p[0] != self.server_address for p in fragments))

    def test_pending_async_sync_docs_and_events_do_not_overwrite(self):
        self.client.execute('''
            results={}
            subscriber:subscribe('job:1',function(v) events[#events+1]=v end)
            for i=1,12 do
                assert(proxy:async(function(ok,n) assert(ok);results[i]=n end).add(i,100))
            end
            local ok,n=proxy.emit('job:1','during-calls');assert(ok and n==1)
            local docs=proxy:refreshDocumentation();assert(docs.add and docs.emit)
            for i=1,12 do assert(results[i]==i+100) end
            assert(events[1]=='during-calls' and next(proxy.pending)==nil)
            assert(proxy:getConnection().expectations.rpc.persistent)
        ''')

    def test_function_keys_async_and_nil_results(self):
        self.server.execute('''
            endpoint.lib.keyed=function(...) return select('#',...),... end
            endpoint:exposeFunction('keyed','key test',{'secret'})
        ''')
        denied = self.client.execute('return proxy.keyed(1)')
        self.assertFalse(denied[0])
        self.assertIn('Missing function key', denied[1])
        self.client.execute("proxy:setFnKeyTable({keyed='wrong'})")
        self.assertIn('Access denied', self.client.execute('return proxy.keyed(1)')[1])
        self.client.execute('''
            proxy:setFnKeyTable({keyed='secret'})
            local r=table.pack(proxy.keyed(1,nil,3,nil))
            assert(r.n==6 and r[1] and r[2]==4 and r[3]==1 and r[5]==3)
            proxy:async(function(...) asyncResult=table.pack(...) end).keyed(2,nil)
        ''')
        self.pump()
        self.assertTrue(self.client.execute('return asyncResult.n==4 and asyncResult[1] and asyncResult[2]==2 and asyncResult[3]==2'))

    def test_silent_deny_does_not_poison_router(self):
        self.server.execute('endpoint:setSilentDeny(true)')
        self.client.execute('proxy:async(function() unexpected=true end).missing()')
        self.pump()
        self.assertIsNone(self.client.globals().unexpected)
        self.assertEqual(self.client.execute('return proxy.add(9,10)'), (True, 19))
        self.server.execute('endpoint:setSilentDeny(false)')
        self.assertIn('Function not exposed', self.client.execute('return proxy.missing()')[1])

    def test_fragmented_reply_and_concurrent_pending_docs(self):
        self.server.execute('''
            endpoint.lib.large=function(v) return v,nil end
            endpoint:exposeFunction('large',string.rep('doc',5000))
        ''')
        self.client.execute('''
            for i=1,3 do
                proxy:async(function(ok,v,last)
                    assert(ok and #v==20000 and v==string.rep(tostring(i),20000) and last==nil)
                    completed=(completed or 0)+1
                end).large(string.rep(tostring(i),20000))
            end
            local docs=proxy:refreshDocumentation()
            assert(#docs.large.description==15000 and completed==3 and next(proxy.pending)==nil)
        ''')

    def test_async_timeout_and_close_release_pending_and_timers(self):
        self.server.execute('endpoint:setSilentDeny(true)')
        self.client.execute('proxy:async(function() unexpected=true end).missing()')
        self.pump()
        self.assertTrue(self.client.execute('return next(proxy.pending)~=nil'))
        self.clock += 10.1
        self.pump()
        self.assertTrue(self.client.execute('return next(proxy.pending)==nil and unexpected==nil'))
        self.client.execute('''
            proxy:async(function() unexpected=true end).missing()
            proxy:close()
            assert(next(proxy.pending)==nil)
            local count=0;for _ in pairs(NET_TIMERS) do count=count+1 end
            assert(count==1,'only tnet timeout checker remains')
        ''')
