"""Real mixed-route allocator, expected-item receipts and controller timing."""
import unittest
from pathlib import Path
import test_stock_api


class LogisticsManyTests(unittest.TestCase):
    def test_transfer_receipts_keep_returns_overflow_and_actual_stack_limit(self):
        for overflow in (False, True):
            with self.subTest(overflow=overflow):
                self.setUp()
                self.lua.globals().OVERFLOW = overflow
                self.lua.execute('''
          local id=lg.transfer({name='mod:a'},300,'source','dest',{drones=1,overflow=OVERFLOW and 'overflow' or nil})
          local packet,task=dispatch()
          assert(task.steps[1].count==256 and task.steps[2].count==256)
          report(packet.id,{state='idle',held=0,steps={{taken=64,moved=64,maxSize=16},{moved=64}}})
          packet,task=dispatch()
          assert(task.steps[1].count==64 and task.steps[2].count==64)
          report(packet.id,{state='idle',held=0,refused=true,reason='destination refused items',steps={
            {taken=64,moved=10,maxSize=16,returned=not OVERFLOW and 54 or 0,overflow=OVERFLOW and 54 or 0,emptied=4,knownTaken=64},
            {moved=10,refused=54}}})
          dispatch()
          local s=lg.status(id)
          assert(s.state=='partial' and s.moved==74 and s.remaining==226 and s.trips==2)
          assert(s.taken==128 and s.returned==(OVERFLOW and 0 or 54) and s.overflow==(OVERFLOW and 54 or 0) and s.maxSize==16)
          assert(s.refused==54 and s.emptied==4 and s.knownTaken==64 and s.steps==nil)
          assert(s.from.node=='source' and s.to.node=='dest' and s.item.name=='mod:a')
        ''')

    def test_transfer_rejects_unreachable_delivery_before_dispatch(self):
        self.lua.execute('''
          local map=require('logistics.map')
          local theta=map.theta
          map.theta=function(a,b,...) if a=='source' and b=='dest' then return nil end;return theta(a,b,...) end
          local id=lg.transfer({name='mod:a'},4,'source','dest')
          local before=#SENT;dispatch()
          assert(#SENT==before and lg.status(id).state=='failed' and lg.status(id).trips==0)
          assert(lg.status(id).reason:find('no route source'))
        ''')

    def test_agent_waiting_take_stops_at_minimum_or_waits_for_it(self):
        source = Path('drone-logistics/usr/lib/logistics/drone/agent.lua').read_text()
        function = source[source.index('local function waitingTake('):source.index('local function runSteps(')]
        self.lua.execute('''
          STOCK=1;PULLS=0;CLOCK=0
          computer={uptime=function() return CLOCK end,energy=function() return 100 end,
            pullSignal=function(seconds) PULLS=PULLS+1;CLOCK=CLOCK+seconds;STOCK=2 end}
          function cargoRoom() return true end
          function take(endpoint,item,wanted)
            local got=math.min(STOCK,wanted);STOCK=STOCK-got;return got,64,nil,STOCK
          end
        ''')
        waiting_take = self.lua.execute(function + '\nreturn waitingTake')
        self.assertEqual(waiting_take(None, None, 3, self.lua.table(timeout=5), 0, 1)[0], 1)
        self.assertEqual(self.lua.globals().PULLS, 0)
        self.lua.execute('STOCK=1;PULLS=0;CLOCK=0')
        self.assertEqual(waiting_take(None, None, 3, self.lua.table(timeout=5), 0, 3)[0], 3)
        self.assertEqual(self.lua.globals().PULLS, 1)

    def test_wait_for_survives_dispatch_and_decreases_on_later_trip(self):
        self.lua.execute('''
          local take=leg('take','mod:a',6,nil,64);take.waitFor=4
          local id=lg.job({take,leg('put','mod:a',6,nil,64,'dest')},{wait={timeout=5}})
          local packet,task=dispatch();assert(task.steps[1].waitFor==4)
          report(packet.id,{state='idle',held=0,reason='source shortfall',steps={
            {taken=2,moved=2,short=true,left=4},{moved=2}}})
          packet,task=dispatch();assert(task.steps[1].count==4 and task.steps[1].waitFor==2)
        ''')

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
                      local result={state='idle',held=0,steps={{short=true,left=LEFT,taken=0,moved=0},{moved=0}}}
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

    def test_take_all_that_empties_its_source_is_done_not_source_empty(self):
        self.lua.execute('''
          local id=lg.job({{take='source',item={name='mod:a'},count='all'},{put='dest',item={name='mod:a'},rest=true}})
          local packet=dispatch()
          report(packet.id,{state='idle',held=0,steps={{taken=64,moved=64,short=true,complete=true},{moved=64}}})
          local s=lg.status(id);assert(s.state=='done' and s.reason==nil)
        ''')

    def test_held_drone_delivers_its_cargo_only_on_its_own_job(self):
        self.lua.execute('''
          lg.job({leg('take','mod:a',3,nil,64),leg('put','mod:a',3,nil,64,'dest')})
          local packet=dispatch()
          report(packet.id,{state='idle',held=3,reason='destination refused items',refused=true,
            steps={{taken=3,moved=3},{moved=0,refused=3}},cargo={{item={name='mod:a',damage=0},count=3}}})
          local d=lg.drones()[1];assert(d.state=='held' and d.held[1].count==3 and d.home=='home')
          -- Other work does not use a held drone.
          local before=#SENT;lg.job({leg('take','mod:b',1,nil,64),leg('put','mod:b',1,nil,64,'dest')});dispatch()
          assert(#SENT==before)
          lg.job({leg('put','mod:a',3,nil,64,'other')},{drone='d1',cargo=true,drones=1,retries=0})
          local _,task=dispatch()
          assert(task.cargo==true and #task.steps==1 and task.steps[1].put and task.steps[1].count==3)
        ''')

    def test_mixed_trip_reports_numeric_destination_refusal_to_mes(self):
        self.lua.execute('''
          local id=lg.job({leg('take','mod:a',3,nil,64),leg('put','mod:a',3,nil,64,'dest')})
          local packet=dispatch()
          report(packet.id,{state='idle',held=0,reason='destination refused items',refused=true,
            steps={{taken=3,moved=3,returned=2},{moved=1,refused=2}},cargo={}})
          dispatch() -- Consume the scheduler wake that settles a blocked job.
          local s=lg.status(id)
          assert(s.state=='partial' and s.moved==1 and s.refused==2)
          assert(not next(s.held))
        ''')

    def test_agent_delivers_cargo_it_already_holds(self):
        source = Path('drone-logistics/usr/lib/logistics/drone/agent.lua').read_text()
        function = source[source.index('local function runSteps('):source.index('if not x or drone.getOffset()>=.02 then')]
        self.lua.execute('''
          slots=2;CARGO={{name='mod:a',damage=0,size=3,maxSize=64}};PUT={};REPORTS={}
          inv={getStackInInternalSlot=function(i) local c=CARGO[i];return c and c.size>0 and c or nil end}
          function match(a,b) return a and b and a.name==b.name end
          function goTo() end
          function report(id,r) REPORTS[#REPORTS+1]=r end
          function final(id,task,r) report(id,r) end -- the agent's trip report, without its history
          function cargoCount() local n=0;for _,c in pairs(CARGO) do n=n+c.size end;return n end
          function put(endpoint,item,n) CARGO[1].size=CARGO[1].size-n;PUT[#PUT+1]={endpoint.node,n};return n end
          computer={energy=function() return 100 end}
        ''')
        run_steps = self.lua.execute(function + '\nreturn runSteps')
        self.lua.globals().RUN = run_steps
        self.assertEqual(self.lua.execute('''
          local result={}
          RUN({cargo=true,reserve=0,home='home',steps={{put={node='stock'},item={name='mod:a'},count=3}}},1,result)
          return PUT[1][1],PUT[1][2],result.steps[1].moved,result.held,#result.cargo
        '''), ('stock', 3, 3, 0, 0))

    def test_charging_interruption_returns_cargo_or_blocks_with_it_held(self):
        source = Path('drone-logistics/usr/lib/logistics/drone/agent.lua').read_text()
        function = source[source.index('local function runSteps('):source.index('if not x or drone.getOffset()>=.02 then')]
        self.lua.execute('''
          HELD=0;slots=4;VISITS={}
          function match(a,b) return a.name==b.name end
          function goTo(node) VISITS[#VISITS+1]=node end
          function report() end
          function cargoCount() return HELD end
          function cargoRoom() return true end
          function waitingTake() HELD=1;return 1,64,'wait interrupted to charge',true,0 end
          function put() local n=REFUSE and 0 or HELD;HELD=HELD-n;return n end
          computer={energy=function() return 100 end}
        ''')
        self.lua.globals().RUN = self.lua.execute(function + '\nreturn runSteps')
        self.lua.execute('''
          for _,refuse in ipairs({false,true}) do
            REFUSE=refuse;VISITS={};local result={}
            RUN({reserve=10,home='home',steps={
              {take={node='source'},item={name='mod:a'},count=2},
              {put={node='dest'},item={name='mod:a'},count=2}}},1,result)
            assert(table.concat(VISITS,',')=='source,source,home')
            assert(result.held==(refuse and 1 or 0))
            if refuse then
              assert(not result.recharge and result.refused and result.cargo[1].count==1)
              assert(result.reason=='source refused cargo on charging interruption')
            else assert(result.recharge and result.steps[1].returned==1 and result.steps[1].moved==0) end
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
          package.loaded.event={push=function() end,listen=function(name,fn) LISTEN[name]=fn end,timer=function() return 1 end,cancel=function() end}
          require('component').modem.send=function(address,port,token,kind,id,payload)
            SENT[#SENT+1]={kind=kind,id=id,payload=payload}
          end
          local m=require('logistics.map');m.node=function(name) return {x=0,y=0,z=0,charger=true,faces={[0]=true}} end
          m.theta=function(a,b) return {a,b} end
          files['/etc/logistics.drones']=require('serialization').serialize({
            d1={address='remote',token='secret',home='home'}})
          lg=assert(load(SOURCE))()
          assert(#SENT==1 and SENT[1].kind=='status');SENT={}
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
