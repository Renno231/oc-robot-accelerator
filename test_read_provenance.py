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
          function finishRead(id,storage,slots,n)
            jobs[id]={state='done',steps={{read={node=storages[storage].node,
              side=storages[storage].side,slots=slots},size=27,
              listing=n>0 and {[slots and slots[1] or 1]=stack(n)} or {}}}}
            listener('logistics',id)
          end
        ''')

    def test_unsolicited_read_does_not_replace_stock(self):
        self.lua.execute('''
          assert(wh.count(item)==128)
          finishRead(99,'stock',nil,9)
          assert(wh.count(item)==128 and wh.settled(99))
        ''')

    def test_read_overlapping_a_mutation_does_not_restore_stale_stock(self):
        self.lua.execute('''
          local lg=require('logistics')
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
