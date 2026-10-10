"""A scan that overlaps a queued take or put never restores stale stock."""
import unittest
import test_stock_api


class CachedRoleApiTests(unittest.TestCase):
    def setUp(self):
        fixture = test_stock_api.WarehouseApiTests()
        fixture.setUp()
        self.lua = fixture.lua
        self.lua.execute('''
          function stack(n,name,maximum)
            return {name=name or item.name,damage=0,label='Fuel',size=n,maxSize=maximum or 64}
          end
          function installHooks()
            local lg=require('logistics');local mutationHook,readHook
            lg.onMutation=function(_,fn) mutationHook=fn;return true end
            lg.onRead=function(_,fn) readHook=fn;return true end
            lg.job=function(steps)
              local id=#jobs+1;local mutations,reads={},{}
              for _,step in ipairs(steps) do
                local value=step.take or step.put or step.read
                if value then
                  local e=type(value)=='string' and storages[value]
                    or value.storage and storages[value.storage] or value
                  local ep={node=e.node,side=e.side,slots=type(value)=='table' and value.slots or nil}
                  local list=step.read and reads or mutations;list[#list+1]=ep
                end
              end
              jobs[id]={state='queued',submitted=steps}
              if #mutations>0 then mutationHook(id,mutations) end
              if #reads>0 then readHook(id,reads) end
              return id
            end
            wh=assert(load(SOURCE))();return lg
          end
          function finishRead(id,storage,slots,n)
            jobs[id]={state='done',steps={{read={node=storages[storage].node,
              side=storages[storage].side,slots=slots},size=27,
              listing=n>0 and {[slots and slots[1] or 1]=stack(n)} or {}}}}
            listener('logistics',id)
          end
        ''')

    def test_read_overlapping_a_mutation_does_not_restore_stale_stock(self):
        self.lua.execute('''
          local lg=installHooks()
          local initial=lg.job({{read='stock'}});finishRead(initial,'stock',nil,5)
          assert(wh.count(item)==5)
          local stale=lg.job({{read='stock'}})
          local mutation=lg.job({{take='alias',item=item,count=2}})
          jobs[mutation]={state='done',steps={{take=storages.alias,item=item,taken=2,maxSize=64}}}
          listener('logistics',mutation);assert(wh.count(item)==3)
          finishRead(stale,'stock',nil,5)
          assert(wh.count(item)==3 and wh.settled(stale))
        ''')


if __name__ == '__main__':
    unittest.main()
