"""WH2 physical takes and conservative catalogue capacity, using real Lua."""
from pathlib import Path
import unittest
import test_warehouse_many


class WarehouseTakeSlotsTests(unittest.TestCase):
    def setUp(self):
        fixture = test_warehouse_many.WarehouseManyTests()
        fixture.setUp()
        self.lua = fixture.lua
        agent = Path('drone-logistics/usr/lib/logistics/drone/agent.lua').read_text()
        self.lua.globals().TAKE = agent[agent.index('local function match('):agent.index('local function runSteps(')]
        self.lua.execute('''
          physical={};slots=4
          drone={select=function() end}
          inv={getInventorySize=function() return #physical end,
            getStackInSlot=function(_,s) return physical[s].size>0 and physical[s] or nil end,
            getStackInInternalSlot=function() return nil end,
            suckFromSlot=function(_,s,n) physical[s].size=physical[s].size-n;return n end}
          realTake,realWaitingTake=assert(load(TAKE..'\\nreturn take,waitingTake'))()
          function check(counts,n,selected,expected,stacks,free)
            physical={};for k,c in ipairs(counts) do physical[k]=stack('mod:coal',c) end
            observe('stock',clone(physical),#physical)
            local i={name='mod:coal',damage=0}
            local got,maximum,why,left,empty=realTake({side=0,slots=selected},i,n)
            assert(got==n and not why)
            for k,c in ipairs(expected) do assert(physical[k].size==c) end
            local id=#jobs+1;jobs[id]={state='done',steps={{take={node='stock',side=0,slots=selected},
              item=i,taken=got,maxSize=maximum,emptied=empty,knownTaken=got}}}
            listener('logistics',id)
            local e=wh.contents('stock');local v
            for _,value in pairs(e.items) do if value.item.name=='mod:coal' then v=value end end
            assert(v.count==n*-1+(function() local t=0;for _,c in ipairs(counts) do t=t+c end;return t end)())
            assert(v.stacks==stacks and e.freeSlots==free,'wrong occupied/free slots')
            assert(v.room==stacks*64-v.count)
          end
        ''')

    def test_partial_slot_and_drained_slot(self):
        self.lua.execute("check({64,64},32,{2},{64,32},2,0);check({64,64},64,{2},{64,0},1,1)")

    def test_partial_item_take(self):
        self.lua.execute("check({64,64},64,nil,{0,64},1,1)")

    def test_three_stacks_leaving_one_partial(self):
        self.lua.execute("check({64,64,64},160,nil,{0,0,32},1,2)")

    def test_full_take(self):
        self.lua.execute("check({64,64},128,nil,{0,0},0,2)")

    def test_repeated_waiting_pass_does_not_double_count_refilled_slot(self):
        self.lua.execute('''
          physical={stack('mod:coal',2)};local t=0
          computer={uptime=function() return t end,energy=function() return 5000 end,
            pullSignal=function(dt) t=t+dt;physical[1]=stack('mod:coal',2) end}
          local got,_,why,recharge,_,empty=realWaitingTake({side=0},
            {name='mod:coal'},4,{timeout=1},1000)
          assert(got==4 and not why and not recharge and empty==nil)
        ''')

    def test_unknown_receipt_keeps_upper_bound(self):
        self.lua.execute('''
          observe('stock',{stack('mod:coal',64),stack('mod:coal',64)},2)
          local id=#jobs+1;jobs[id]={state='done',steps={{take=storages.stock,
            item={name='mod:coal'},taken=64,maxSize=64}}};listener('logistics',id)
          local e=wh.contents('stock');assert(e.freeSlots==0)
          for _,v in pairs(e.items) do if v.item.name=='mod:coal' then assert(v.count==64 and v.stacks==2 and v.room==64) end end
          id=#jobs+1;jobs[id]={state='done',steps={{take=storages.stock,
            item={name='mod:coal'},taken=63,maxSize=64}}};listener('logistics',id)
          e=wh.contents('stock');assert(e.freeSlots==1)
          for _,v in pairs(e.items) do if v.item.name=='mod:coal' then assert(v.count==1 and v.stacks==1) end end
        ''')

    def test_mixed_known_unknown_and_returns_are_conservative(self):
        for known, returned in [(64, 0), (128, 32)]:
            self.lua.execute('''
              observe('stock',{stack('mod:coal',64),stack('mod:coal',64),stack('mod:coal',64)},3)
              local id=#jobs+1;jobs[id]={state='done',steps={{take=storages.stock,
                item={name='mod:coal'},taken=128,returned=%d,maxSize=64,
                emptied=2,knownTaken=%d}}};listener('logistics',id)
              assert(wh.contents('stock').freeSlots==0)
            ''' % (returned, known))

    def test_full_take_clears_an_earlier_conservative_stack_bound(self):
        self.lua.execute('''
          observe('stock',{stack('mod:coal',64),stack('mod:coal',64)},2)
          local id=#jobs+1;jobs[id]={state='done',steps={{take=storages.stock,
            item={name='mod:coal'},taken=64,maxSize=64}}};listener('logistics',id)
          assert(wh.contents('stock').freeSlots==0)
          id=#jobs+1;jobs[id]={state='done',steps={{take=storages.stock,
            item={name='mod:coal'},taken=64,maxSize=64,emptied=1,knownTaken=64}}};listener('logistics',id)
          assert(wh.contents('stock').freeSlots==2)
          for _,v in pairs(wh.contents('stock').items) do if v.item.name=='mod:coal' then
            assert(v.count==0 and v.stacks==0 and v.room==0)
          end end
        ''')

    def test_label_optional_take_does_not_reuse_one_empty_delta_twice(self):
        self.lua.execute('''
          local a=stack('mod:coal',64);a.label='A'
          local b=stack('mod:coal',64);b.label='B'
          observe('stock',{a,b},2)
          local id=#jobs+1;jobs[id]={state='done',steps={{take=storages.stock,
            item={name='mod:coal'},taken=96,maxSize=64,emptied=1,knownTaken=96}}}
          listener('logistics',id)
          assert(wh.contents('stock').freeSlots==1,'one physical empty slot counted twice')
        ''')


class WarehouseMixedTargetsTests(unittest.TestCase):
    def setUp(self):
        fixture = test_warehouse_many.WarehouseManyTests()
        fixture.setUp()
        self.lua = fixture.lua

    def test_new_kind_prefers_most_free_then_name_for_store_and_collect(self):
        self.lua.execute('''
          wh.remove('stock');wh.remove('alias')
          addStorage('z',{stack('mod:other',64)},5,{priority=99})
          addStorage('b',{stack('mod:other',64)},7,{priority=100})
          addStorage('a',{stack('mod:other',64)},7)
          observe('buffer',{stack('mod:new',8)},1)
          local id=assert(wh.store({name='mod:new'},8,'buffer'))
          assert(ep(jobs[id].submitted[2].put).node=='a')
          jobs[id]={state='done',steps={{take=storages.buffer,item={name='mod:new'},taken=8,maxSize=64},
            {put=storages.a,item={name='mod:new'},moved=8,maxSize=64}}};listener('logistics',id)
          assert(wh.count({name='mod:new'})==8)
          observe('a',{stack('mod:other',64)},7);observe('buffer',{stack('mod:new',8)},1)
          local ids=assert(wh.collect('buffer',{{item={name='mod:new'},count=8}}))
          assert(ep(jobs[ids[1]].submitted[2].put).node=='a')
          jobs[ids[1]]={state='done',steps={{take=storages.buffer,item={name='mod:new'},taken=8,maxSize=64},
            {put=storages.a,item={name='mod:new'},moved=8,maxSize=64}}};listener('logistics',ids[1])
          assert(wh.count({name='mod:new'})==8)
        ''')

    def test_tiers_one_to_three_precede_mixed_capacity(self):
        for tier in (1, 2, 3):
            self.setUp()
            self.lua.execute(f'''
              wh.remove('stock');wh.remove('alias')
              addStorage('mixed',{{stack('mod:other',64)}},27,{{priority=99}})
              addStorage('preferred',{ '{stack("mod:new",1)}' if tier==2 else '{}' },1,
                { '{filter={{name="mod:new"}}}' if tier==1 else '{}' })
              observe('buffer',{{stack('mod:new',8)}},1)
              local id=assert(wh.store({{name='mod:new'}},8,'buffer'))
              assert(ep(jobs[id].submitted[2].put).node=='preferred')
            ''')


class LogisticsTakeReceiptTests(unittest.TestCase):
    def setUp(self):
        import test_stations
        fixture = test_stations.StationsTests()
        fixture.setUp()
        self.lua = fixture.lua

    def test_step_receipt_and_unknown_transfer_trip_are_retained(self):
        self.lua.execute('''
          map.name('from','home1',0);map.name('to','home6',0)
          local a={node='home1',side=0};local b={node='home6',side=0};local i={name='mod:coal'}
          local id=assert(lg.job({{take=a,item=i,count=16},{put=b,item=i,count=16}},{drones=1}));drain()
          for addr,f in pairs(FAKES) do if f.task then
            f.task=nil;report(addr,f.id,{state='idle',steps={{taken=16,moved=16,maxSize=64,emptied=1,knownTaken=16},{moved=16,maxSize=64}}})
          end end
          drain();local s=lg.status(id);assert(s.state=='done' and s.steps[1].emptied==1 and s.steps[1].knownTaken==16)
          id=assert(lg.transfer(i,512,a,b,{drones=1}));drain()
          for _,known in ipairs({true,false}) do
            local found=false
            for addr,f in pairs(FAKES) do if f.task then
              local r={state='idle',steps={{taken=256,moved=256,maxSize=64},{moved=256}}}
              if known then r.steps[1].emptied=4;r.steps[1].knownTaken=256 end
              f.task=nil;report(addr,f.id,r);found=true;break
            end end
            assert(found);drain()
          end
          s=lg.status(id);assert(s.state=='done' and s.taken==512 and s.emptied==4 and s.knownTaken==256)
        ''')


if __name__ == '__main__':
    unittest.main()
