"""Graph-distance ranking: reuse one search, never preview candidate flights."""
from pathlib import Path
import unittest

import test_warehouse_many as fixtures


class RankingTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.WarehouseManyTests();fixture.setUp();self.lua=fixture.lua
        self.lua.globals().MAP=Path('drone-logistics/lib/map.lua').read_text()
        self.lua.execute('''
          realmap=assert(load(MAP))()
          local stub=require('map');for k,v in pairs(realmap) do stub[k]=v end
          realmap.add('stockNode',0,0,0);realmap.add('bufferNode',10,0,0)
          realmap.add('otherNode',20,0,0);realmap.add('lostNode',10,0,10)
          realmap.name('stock','stockNode',0);realmap.name('alias','stockNode',1)
          realmap.name('buffer','bufferNode',0);realmap.name('other','otherNode',0)
          realmap.name('lost','lostNode',0)
          realmap.link('stockNode','bufferNode');realmap.link('otherNode','bufferNode')
          for _,n in ipairs({'stock','alias','buffer','other','lost'}) do storages[n]=realmap.storage(n) end
          function addStorage(n,listing,size)
            storages[n]=realmap.storage(n);wh.add(n);observe(n,listing,size)
          end
          SEARCHES=0;local route=realmap.route
          realmap.route=function(a,b,...) if not b then SEARCHES=SEARCHES+1 end;return route(a,b,...) end
          require('logistics').plan=function() error('ranking must not preview flights') end
        ''')

    def test_many_candidates_and_requests_share_target_search(self):
        self.lua.execute('''
          observe('stock',{stack('mod:a',64),stack('mod:b',64)})
          for k=1,50 do
            local n='s'..k;realmap.add('node'..k,k,0,2);realmap.name(n,'node'..k,0);realmap.link('node'..k,'bufferNode')
            addStorage(n,{stack('mod:a',64),stack('mod:b',64)})
          end
          local ids=assert(wh.fetchMany({{item={name='mod:a'},count=1},{item={name='mod:b'},count=1}},'buffer'))
          assert(#ids>0 and SEARCHES==1,'one target search serves all candidates and requests')
        ''')

    def test_edit_invalidates_cached_distances(self):
        self.lua.execute('''
          local a=realmap.distances('bufferNode');assert(a.stockNode==10 and not a.lostNode and SEARCHES==1)
          assert(realmap.distances('bufferNode')==a and SEARCHES==1)
          local revision=realmap.revision();realmap.link('lostNode','bufferNode')
          local b=realmap.distances('bufferNode');assert(b~=a and b.lostNode==10 and SEARCHES==2)
          assert(realmap.revision()>revision and not a.lostNode)
        ''')

    def test_four_origin_cache_bound(self):
        self.lua.execute('''
          realmap.add('fifth',0,0,2)
          for _,n in ipairs({'stockNode','bufferNode','otherNode','lostNode','fifth'}) do realmap.distances(n) end
          assert(SEARCHES==5);realmap.distances('bufferNode');assert(SEARCHES==5)
          realmap.distances('stockNode');assert(SEARCHES==6,'oldest of five origins was evicted')
        ''')

    def test_unreachable_stock_excluded_and_tie_unchanged(self):
        self.lua.execute('''
          observe('stock',{stack('mod:a',64)})
          addStorage('other',{stack('mod:a',64)})
          addStorage('lost',{stack('mod:a',64)})
          local ids=assert(wh.fetchMany({{item={name='mod:a'},count=1}},'buffer'))
          local first
          for _,s in ipairs(jobs[ids[1]].submitted) do if s.take then first=s.take;break end end
          assert(first=='alias','equal distance keeps storage-name/face tie ordering')
          assert(not realmap.distances('bufferNode').lostNode)
        ''')

    def test_single_fetch_store_and_collect_use_shared_origin(self):
        self.lua.execute('''
          observe('stock',{stack('mod:a',64)})
          assert(wh.fetch({name='mod:a'},1,'buffer'));assert(SEARCHES==1)
          observe('stock',{},4);addStorage('other',{},4)
          assert(wh.store({name='mod:a'},1,'buffer'));assert(SEARCHES==1)
          assert(wh.collect('buffer',{{item={name='mod:a'},count=1}}));assert(SEARCHES==1)
        ''')

    def test_graph_and_smoothed_order_can_differ_explicitly(self):
        self.lua.execute('''
          realmap.add('target',0,0,20);realmap.add('bend',2,0,23)
          realmap.add('near',2,0,20);realmap.add('far',4,0,20)
          realmap.link('target','bend');realmap.link('bend','near');realmap.link('target','far')
          local d=realmap.distances('target');assert(d.far<d.near)
          local function flight(to)
            local p=assert(realmap.theta('target',to,.1));local n=0
            for k=2,#p do local a,b=realmap.node(p[k-1]),realmap.node(p[k]);n=n+math.sqrt((a.x-b.x)^2+(a.z-b.z)^2) end
            return n
          end
          assert(flight('near')<flight('far'),'documented graph/any-angle ordering disagreement')
        ''')


if __name__=='__main__': unittest.main()
