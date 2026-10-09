"""Coordinator's two-computer API harness, extended for exact-topic pubsub.

Original harness: scratchpad/apitest.py from the T13 pubsub addendum.
Runs installed, byte-identical QuickOS libraries through real tnet/API dispatch.
"""
from pathlib import Path
import unittest
from lupa.lua53 import LuaRuntime

LIB = str(Path(__file__).resolve().parents[1] / 'usr/lib').replace('\\', '/')
SETUP = r'''
local py, libdir = ...
package.path = libdir.."/?.lua;"..package.path
local handlers={}
package.preload.computer=function() return {uptime=function() return py.uptime() end, address=function() return py.addr end} end
package.preload.component=function() return {modem={open=function() return true end, close=function() return true end,
  send=function(...) py.send(py.addr, ...) return true end}} end
package.preload.event=function() return {listen=function(n,f) handlers[n]=f return 1 end, timer=function() return 1 end,
  cancel=function() end, ignore=function() end} end
local function ser(v) local t=type(v)
  if t=="table" then local p={} for k,x in pairs(v) do p[#p+1]="["..ser(k).."]="..ser(x) end return "{"..table.concat(p,",").."}"
  elseif t=="string" then return string.format("%q",v) elseif t=="number" or t=="boolean" then return tostring(v) else return "nil" end end
package.preload.serialization=function() return {serialize=ser, unserialize=function(s) return load("return "..s)() end} end
os.sleep=function() py.sleep() end
deliver=function(...) handlers.modem_message("modem_message", ...) end
'''


class Context:
    pass


class PubsubTests(unittest.TestCase):
    server_address = 'aaaaaaaa-1111-2222-3333-444444444444'

    def setUp(self):
        self.queue, self.clock, self.nodes = [], 0.0, {}
        self.server = self.node(self.server_address)
        self.server.execute('''
            api=require('api');ps=require('pubsub')
            endpoint=api.expose('calc',{
                add=function(a,b) return a+b end,
                emit=function(topic,value) return publisher:publish(topic,value) end
            },100)
            publisher=ps.attach(endpoint)
        ''')
        self.client = self.connect('bbbbbbbb-5555-6666-7777-888888888888')

    def node(self, address):
        lua = LuaRuntime(unpack_returned_tuples=True)
        context = Context()
        context.addr, context.uptime = address, lambda: self.clock
        context.send = lambda frm, to, port, *args: self.queue.append((to, frm, port, args))
        context.sleep = self.pump
        lua.execute(SETUP, context, LIB)
        self.nodes[address] = lua
        return lua

    def connect(self, address):
        node = self.node(address)
        node.execute('''
            proxy=require('api').connect('calc',100,...)
            subscriber=require('pubsub').client(proxy:getConnection())
            events={}
        ''', self.server_address)
        return node

    def pump(self):
        self.clock += 0.05
        while self.queue:
            to, sender, port, args = self.queue.pop(0)
            if to in self.nodes:
                self.nodes[to].globals().deliver(to, sender, port, 0, *args)

    def subscribe(self, node, topic='job:1'):
        node.execute('subscriber:subscribe(...,function(...) events[#events+1]=table.pack(...) end)', topic)
        self.pump()

    def test_subscribe_publish_preserves_data_and_nil_arguments(self):
        self.subscribe(self.client)
        self.assertEqual(self.server.execute("return publisher:publish('job:1',{'value'},nil,3,nil)"), 1)
        self.pump()
        self.assertEqual(self.client.execute('return events[1].n,events[1][1][1],events[1][3]'), (4, 'value', 3))

    def test_api_caller_is_scoped_to_each_client_and_cleared_after_error(self):
        self.server.execute('''
            endpoint.lib.owner=function() return api.caller().address end
            endpoint:exposeFunction('owner')
            endpoint.lib.fail=function() error('caller test error') end
            endpoint:exposeFunction('fail')
            assert(api.caller()==nil)
        ''')
        second_address = 'cccccccc-5555-6666-7777-999999999999'
        second = self.connect(second_address)
        self.assertEqual(self.client.execute('return proxy.owner()'),
                         (True, 'bbbbbbbb-5555-6666-7777-888888888888'))
        self.assertEqual(second.execute('return proxy.owner()'), (True, second_address))
        self.assertEqual(self.client.execute('return proxy.owner()'),
                         (True, 'bbbbbbbb-5555-6666-7777-888888888888'))
        self.assertFalse(self.client.execute('return proxy.fail()')[0])
        self.assertTrue(self.server.execute('return api.caller()==nil'))

    def test_close_then_immediate_api_reconnect_does_not_reuse_id(self):
        old_id = self.client.execute('return proxy:getConnection().id')
        result = self.client.execute('''
            proxy:close()
            proxy=require('api').connect('calc',100,...,nil,0.3)
            return proxy:getConnection().id,proxy.add(11,12)
        ''', self.server_address)
        self.assertNotEqual(result[0], old_id)
        self.assertEqual(result[1:], (True, 23))

    def test_two_subscribers_receive_same_topic(self):
        second = self.connect('cccccccc-5555-6666-7777-999999999999')
        self.subscribe(self.client)
        self.subscribe(second)
        self.assertEqual(self.server.execute("return publisher:publish('job:1','done')"), 2)
        self.pump()
        self.assertEqual(self.client.execute('return #events,events[1][1]'), (1, 'done'))
        self.assertEqual(second.execute('return #events,events[1][1]'), (1, 'done'))

    def test_exact_topic_isolation(self):
        self.subscribe(self.client)
        self.assertEqual(self.server.execute("return publisher:publish('job:10','wrong')"), 0)
        self.pump()
        self.assertEqual(self.client.execute('return #events'), 0)

    def test_unsubscribe_removes_remote_and_local_delivery(self):
        self.subscribe(self.client)
        self.client.execute("subscriber:unsubscribe('job:1')")
        self.pump()
        self.assertEqual(self.server.execute("return publisher:publish('job:1','wrong')"), 0)
        self.pump()
        self.assertEqual(self.client.execute('return #events'), 0)

    def test_closed_connections_are_dropped_lazily(self):
        self.subscribe(self.client)
        self.client.execute('proxy:close()')
        self.pump()
        self.assertEqual(self.server.execute("return publisher:publish('job:1','wrong')"), 0)
        self.assertTrue(self.server.execute('return next(publisher.connections)==nil'))

    def test_api_calls_and_events_interleave_on_one_connection(self):
        self.subscribe(self.client)
        self.assertEqual(self.client.execute('return proxy.add(1,2)'), (True, 3))
        self.server.execute("publisher:publish('job:1','progress')")
        self.assertEqual(self.client.execute('return proxy.add(3,4)'), (True, 7))
        self.server.execute("publisher:publish('job:1','complete')")
        self.pump()
        self.assertEqual(self.client.execute('return #events,events[1][1],events[2][1]'), (2, 'progress', 'complete'))
        self.assertTrue(self.client.execute("local c=proxy:getConnection();return c.expectations.rpc.persistent and c.expectations.ps.persistent"))

    def test_subscribe_before_call_is_delivered_before_call(self):
        result = self.client.execute('''
            subscriber:subscribe('job:1',function(value) events[#events+1]=value end)
            return proxy.emit('job:1','accepted')
        ''')
        self.assertEqual(result, (True, 1))
        self.assertEqual(self.client.execute('return #events,events[1]'), (1, 'accepted'))

    def test_attach_already_open_connection_and_multiple_hook_callbacks(self):
        self.server.execute('''
            later=require('pubsub').attach(endpoint)
            endpoint:onConnect(function(conn)
                assert(conn.expectations.rpc.persistent)
                error('isolated hook error')
            end)
            endpoint:onConnect(function(conn) HOOK_READY=conn.expectations.rpc.persistent end)
        ''')
        self.subscribe(self.client)
        self.assertEqual(self.server.execute("return later:publish('job:1','late')"), 1)
        self.pump()
        second = self.connect('dddddddd-5555-6666-7777-123412341234')
        self.assertTrue(self.server.globals().HOOK_READY)
        self.assertEqual(second.execute('return proxy.add(7,8)'), (True, 15))

    def test_bare_connection_server_uses_same_persistent_dispatcher(self):
        self.server.execute('''
            require('tnet').listen(101,function(conn)
                conn.serial={lib='serialization',encode='serialize',decode='unserialize'}
                bare=require('pubsub').server(conn)
            end)
        ''')
        self.client.execute('''
            local c=require('tnet').connect(...,101)
            c.serial={lib='serialization',encode='serialize',decode='unserialize'}
            assert(c:init(1));bareSub=require('pubsub').client(c)
            bareSub:subscribe('bare',function(v) BARE_EVENT=v end)
        ''', self.server_address)
        self.pump()
        self.assertEqual(self.server.execute("return bare:publish('bare','event')"), 1)
        self.pump()
        self.assertEqual(self.client.globals().BARE_EVENT, 'event')


if __name__ == '__main__':
    unittest.main()
