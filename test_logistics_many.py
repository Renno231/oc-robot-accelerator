"""Real mixed-route allocator, expected-item receipts and controller timing."""
import unittest
import test_stock_api


class LogisticsManyTests(unittest.TestCase):
    def test_empty_sources_block_without_retry_but_nonempty_sources_retry(self):
        for packed in (True, False):
            for left in (0, 1):
                with self.subTest(packed=packed, left=left):
                    self.setUp()
                    self.lua.globals().PACKED = packed
                    self.lua.globals().LEFT = left
                    self.lua.execute('''
                      local id
                      if PACKED then
                        id=lg.job({leg('take','mod:a',4,nil,64),leg('put','mod:a',4,nil,64,'dest')},{retries=2})
                      else id=lg.transfer({name='mod:a'},4,'source','dest',{retries=2}) end
                      local packet=assert(dispatch())
                      local result={state='idle',taken=0,moved=0,short=true,left=LEFT,held=0}
                      if PACKED then result.steps={{short=true,left=LEFT,taken=0,moved=0},{moved=0}} end
                      report(packet.id,result)
                      local s=lg.status(id)
                      assert(s.trips==1)
                      if LEFT==0 then
                        assert(s.reason=='source empty' and s.shortfalls==0)
                        local before=#SENT;dispatch();assert(#SENT==before)
                      else
                        assert(s.shortfalls==1);local before=#SENT;dispatch();assert(#SENT==before+1)
                      end
                    ''')

    def setUp(self):
        fixture = test_stock_api.LibraryApiTests()
        fixture.setUp()
        fixture.load_logistics()
        self.lua = fixture.lua
        self.lua.execute('''
          TIME=10;LISTEN={};SENT={}
          local function fingerprint(t)
            if type(t)~='table' then return type(t)..':'..tostring(t) end
            local keys={};for k in pairs(t) do keys[#keys+1]=k end
            table.sort(keys,function(a,b) return type(a)..tostring(a)<type(b)..tostring(b) end)
            local out={'{'};for _,k in ipairs(keys) do out[#out+1]=fingerprint(k)..'='..fingerprint(t[k])..';' end
            out[#out+1]='}';return table.concat(out)
          end
          require('serialization').serialize=function(t) local key=fingerprint(t);serial[key]=clone(t);return key end

          package.loaded.computer={uptime=function() return TIME end}
          package.loaded.event={push=function() end,listen=function(name,fn) LISTEN[name]=fn end}
          require('component').modem.send=function(address,port,token,kind,id,payload)
            SENT[#SENT+1]={kind=kind,id=id,payload=payload}
          end
          local m=require('map');m.node=function(name) return {x=0,y=0,z=0,charger=true,faces={[0]=true}} end
          m.theta=function(a,b) return {a,b} end
          files['/etc/logistics.drones']=require('serialization').serialize({
            d1={address='remote',token='secret',home='home'}})
          lg=assert(load(SOURCE))()
          function report(id,result)
            LISTEN.modem_message('modem_message','local','remote',27103,0,'secret','report',id,
              require('serialization').serialize(result))
          end
          report(0,{state='ready',cargoSlots=4})
          function dispatch()
            TIME=20;LISTEN.logistics_work()
            if #SENT==0 then return nil end
            local packet=SENT[#SENT]
            return packet,require('serialization').unserialize(packet.payload)
          end
          function complete(packet,task)
            local rows={}
            for i,s in ipairs(task.steps) do
              rows[i]={moved=s.count or 0,maxSize=s.maxSize}
              if s.take then rows[i].taken=s.count end
            end
            TIME=30;report(packet.id,{state='idle',steps=rows,held=0})
          end
          function leg(kind,name,n,index,limit,dest)
            return {[kind]=dest or 'source',item={name=name},count=n,expectedIndex=index,maxSize=limit}
          end
        ''')

    def test_mixed_four_stacks_one_trip_and_private_timed_receipts(self):
        self.lua.execute('''
          local expected,steps={},{}
          for i=1,4 do
            local item='mod:item'..i;expected[i]={item={name=item},count=16,requestIndex=i+10}
            steps[#steps+1]=leg('take',item,16,i,16)
          end
          for i=1,4 do steps[#steps+1]=leg('put','mod:item'..i,16,i,16,'dest'..i) end
          local id=lg.job(steps,{expectedItems=expected,split=false,drones=1,retries=0})
          expected[1].count=999;steps[1].maxSize=1
          local packet,task=dispatch();assert(packet.kind=='trip')
          for i=1,4 do assert(task.steps[i].count==16) end
          complete(packet,task)
          local s=lg.status(id);assert(s.state=='done' and s.trips==1 and s.requested==64 and s.moved==64)
          assert(s.queuedAt==10 and s.dispatchedAt==20 and s.finishedAt==30)
          assert(#s.tripTimings==1 and s.tripTimings[1].drone=='d1' and s.tripTimings[1].startedAt==20 and s.tripTimings[1].finishedAt==30)
          for i,r in ipairs(s.perItem) do assert(r.requestIndex==i+10 and r.requested==16 and r.moved==16 and r.shortfall==0 and r.taken==16) end
          s.perItem[1].item.name='changed';s.tripTimings[1].drone='changed'
          assert(lg.status(id).perItem[1].item.name=='mod:item1' and lg.status(id).tripTimings[1].drone=='d1')
        ''')

    def test_known_non64_fifth_stack_rejected_before_trip(self):
        self.lua.execute('''
          local id=lg.job({leg('take','mod:a',64,1,16),leg('take','mod:b',1,2,64),
            leg('put','mod:a',64,1,16,'dest'),leg('put','mod:b',1,2,64,'dest')},
            {expectedItems={{item={name='mod:a'},count=64},{item={name='mod:b'},count=1}},split=false})
          dispatch();local s=lg.status(id)
          assert(s.state=='failed' and s.trips==0 and #SENT==0 and s.reason:find('exceeds one trip'))
        ''')

    def test_missing_item_metadata_does_not_block_available_delivery(self):
        self.lua.execute('''
          local id=lg.job({leg('take','mod:a',2,1,64),leg('put','mod:a',2,1,64,'dest')},
            {expectedItems={{item={name='mod:a'},count=3,requestIndex=7},
              {item={name='mod:missing'},count=1,requestIndex=8}},split=false})
          local packet,task=dispatch();complete(packet,task)
          local s=lg.status(id)
          assert(s.state=='partial' and s.trips==1 and s.requested==4 and s.moved==2 and s.remaining==2)
          assert(s.perItem[1].moved==2 and s.perItem[1].shortfall==1 and s.perItem[2].shortfall==1)
          assert(s.perItem[2].requestIndex==8 and s.perItem[2].taken==0)
        ''')

    def test_same_item_distinct_destinations_preserve_request_index(self):
        self.lua.execute('''
          local id=lg.job({leg('take','mod:a',1,1,64),leg('take','mod:a',2,2,64),
            leg('put','mod:a',1,1,64,{storage='top',slots={1}}),
            leg('put','mod:a',2,2,64,{storage='side',slots={2}})},
            {expectedItems={{item={name='mod:a'},count=1,requestIndex=3},
              {item={name='mod:a'},count=2,requestIndex=4}},split=false})
          local packet,task=dispatch()
          assert(task.steps[3].put.node=='top' and task.steps[3].put.slots[1]==1)
          assert(task.steps[4].put.node=='side' and task.steps[4].put.slots[1]==2)
          complete(packet,task);local s=lg.status(id)
          assert(s.state=='done' and s.trips==1 and s.perItem[1].moved==1 and s.perItem[2].moved==2)
        ''')

    def test_invalid_metadata_and_index_rejected(self):
        self.lua.execute('''
          assert(not pcall(lg.job,{leg('take','mod:a',1,1,64)},
            {expectedItems={{item={name='mod:a'},count=0}}}))
          local id=lg.job({leg('take','mod:a',1,2,64)},
            {expectedItems={{item={name='mod:a'},count=1}}})
          assert(lg.status(id).state=='failed' and #SENT==0)
          id=lg.job({leg('take','mod:a',1,1,0)},
            {expectedItems={{item={name='mod:a'},count=1}}})
          assert(lg.status(id).state=='failed' and #SENT==0)
        ''')

    def test_item_identity_independent_of_serialization_order(self):
        self.lua.execute('''
          local serialization=require('serialization');local original=serialization.serialize;local n=0
          serialization.serialize=function(t,...)
            if type(t)=='table' and t.name then
              n=n+1;local token='distinct-item-encoding-'..n;serial[token]=clone(t);return token
            end
            return original(t,...)
          end
          local id=lg.job({leg('take','mod:a',3,1,16),leg('put','mod:a',3,1,16)},
            {split=false,expectedItems={{item={name='mod:a',damage=0},count=3}}})
          local packet,task=dispatch();assert(packet,lg.status(id).reason)
          complete(packet,task)
          local s=lg.status(id);assert(s.state=='done' and s.perItem[1].moved==3)
        ''')


if __name__ == '__main__':
    unittest.main()
