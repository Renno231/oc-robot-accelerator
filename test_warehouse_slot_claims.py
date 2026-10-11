"""Selected-slot claims through real logistics callbacks and physical receipts."""
import unittest
import test_stations


class WarehouseSlotClaimTests(unittest.TestCase):
    def setUp(self):
        fixture = test_stations.StationsTests()
        fixture.setUp()
        self.lua = fixture.lua
        self.lua.execute('''
          map.add('output',6,65,0);map.link('home6','output')
          map.add('destination',7,65,0);map.link('output','destination')
          map.name('machineOutput','output',0);map.name('stock','destination',0)
          wh.add('machineOutput');wh.add('stock')
          ITEM={name='mod:seed',damage=0}
          PHYSICAL={output={16,48},destination={}}
          function executeJob()
            drain()
            for addr,f in pairs(FAKES) do if f.task then
              local r={state='idle',steps={}};local carried=0
              for index,s in ipairs(f.task.steps) do
                local e=s.read or s.take or s.put;local contents=PHYSICAL[e.node]
                local v={moved=0,maxSize=64};r.steps[index]=v
                if s.read then
                  v.size=27;v.listing={}
                  for slot,n in pairs(contents) do if n>0 then
                    v.listing[slot]={name=ITEM.name,damage=0,size=n,maxSize=64}
                  end end
                elseif s.take then
                  v.taken=0;v.left=0
                  for _,slot in ipairs(e.slots) do
                    local n=math.min(contents[slot] or 0,s.count-v.taken)
                    contents[slot]=(contents[slot] or 0)-n;v.taken=v.taken+n
                    v.left=v.left+contents[slot]
                  end
                  v.moved=v.taken;v.short=v.taken<s.count;carried=carried+v.taken
                else
                  v.moved=math.min(s.count or carried,carried)
                  contents[1]=(contents[1] or 0)+v.moved;carried=carried-v.moved
                end
              end
              local id=f.id;f.task=nil;TIME=TIME+1;report(addr,id,r);drain();return id
            end end
            error('no dispatched job')
          end
          function scanBoth()
            local id=lg.job({{read='machineOutput'},{read='stock'}})
            assert(executeJob()==id and wh.settled(id))
          end
          function takeOutput(waitFor)
            local id=lg.job({{take={storage='machineOutput',slots={1}},item=ITEM,count=32,waitFor=waitFor},
              {put='stock',item=ITEM,rest=true}},{wait={timeout=1},retries=0})
            return id
          end
          function physicalTotal()
            local n=0;for _,slots in pairs(PHYSICAL) do for _,count in pairs(slots) do n=n+count end end
            return n
          end
        ''')

    def test_machine_output_over_request_preserves_unvisited_stock(self):
        self.lua.execute('''
          scanBoth();assert(wh.count(ITEM)==64)
          local id=takeOutput(32)
          assert(lg.status(id).steps[1].claimed==16)
          assert(executeJob()==id and wh.settled(id))
          local s=lg.status(id);assert(s.state=='partial' and s.steps[1].taken==16)
          assert(s.steps[1].claimed==16 and s.steps[1].found==0)
          assert(wh.count(ITEM)==physicalTotal() and physicalTotal()==64)
          local byStorage={};for _,v in ipairs(wh.find(ITEM)) do byStorage[v.storage]=v.count end
          assert(byStorage.machineOutput==48 and byStorage.stock==16)
        ''')

    def test_real_shortfall_removes_only_the_claimed_missing_items(self):
        self.lua.execute('''
          PHYSICAL.output[1]=32;scanBoth();assert(wh.count(ITEM)==80)
          -- Sixteen observed items disappear before the physical take.
          PHYSICAL.output[1]=16
          local id=takeOutput()
          assert(lg.status(id).steps[1].claimed==32)
          assert(executeJob()==id and wh.settled(id))
          local s=lg.status(id);assert(s.state=='partial' and s.steps[1].taken==16)
          assert(s.steps[1].claimed==32 and s.steps[1].found==0)
          assert(wh.count(ITEM)==physicalTotal() and physicalTotal()==64)
          local byStorage={};for _,v in ipairs(wh.find(ITEM)) do byStorage[v.storage]=v.count end
          assert(byStorage.machineOutput==48 and byStorage.stock==16)
        ''')
