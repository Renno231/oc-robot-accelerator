"""Warehouse reservations across jobs and inventory aliases (Lua 5.3)."""
from pathlib import Path
import unittest
from lupa.lua53 import LuaRuntime
from test_store import install_store


class ReservationTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute('''
          cfg={members={stock={},alias={inventory='stock'}},groups={}}
          jobs={}; listener=nil; serial={}; seq=0
          package.preload.serialization=function() return {
            serialize=function(t) seq=seq+1;serial[tostring(seq)]=t;return tostring(seq) end,
            unserialize=function(s) return serial[s] end} end
          package.preload.computer=function() return {uptime=function() return 0 end} end
          package.preload.event=function() return {
            push=function() end,listen=function(name,fn) if name=='logistics' then listener=fn end end} end
          storages={stock={node='stock',side=0},alias={node='stock',side=1},buffer={node='buffer',side=0}}
          package.preload.map=function() return {
            storage=function(s) return storages[s] end,
            storages=function() return storages end,place=function(s) return storages[s].node end} end
          package.preload.logistics=function() return {
            plan=function() return {{x=0,y=0,z=0},{x=1,y=0,z=0}} end,
            status=function(id) return jobs[id] end,
            job=function(steps) local id=#jobs+1;jobs[id]={state='queued',submitted=steps};return id end} end
          io.open=function(path,mode)
            if mode=='r' then
              if path=='/etc/warehouse.cfg' then return {read=function() return require('serialization').serialize(cfg) end,close=function() end} end
              return nil
            end
            return {write=function() end,close=function() end}
          end
          os.rename=function() return true end
        ''')
        install_store(self.lua, preserve_io=True)
        self.lua.globals().SOURCE = Path('drone-logistics/lib/warehouse.lua').read_text()
        self.lua.execute('''wh=assert(load(SOURCE))();item={name='minecraft:clay_ball',damage=0}
          function scan(storage,n,size)
            local id=#jobs+1;jobs[id]={state='done',steps={{read=storages[storage],size=size or 27,
              listing=n>0 and {{name=item.name,damage=0,size=n,maxSize=64}} or {}}}}
            listener('logistics',id)
          end
          scan('stock',128)
        ''')

    def test_two_fetches_reserve_disjoint_128_stock(self):
        self.lua.execute('''
          a=assert(wh.fetch(item,64,'buffer'));b=assert(wh.fetch(item,64,'buffer'))
          local c,e=wh.fetch(item,1,'buffer');assert(c==nil and e:find('available 0'))
          assert(jobs[a].submitted[1].count==64 and jobs[b].submitted[1].count==64)
        ''')

    def test_catalogue_survives_reload_and_forces_log_variant(self):
        self.lua.execute('''
          variant('files')
          local before=wh.count(item)
          wh.observed('stock',{{item=item,count=37}})
          assert(wh.count(item)==37)
          wh=assert(load(SOURCE))()
          assert(wh.count(item)==37 and before==128)
          assert(disk['/etc/warehouse.db'] and not dirs['/etc/warehouse.db'])
        ''')

    def test_group_inventory_aliases_never_count_as_stock(self):
        self.lua.execute('''
          wh.group('cpu1','crafter',{buffer='alias'})
          assert(wh.count(item)==0)
          assert(wh.fetch(item,1,'buffer')==nil)
        ''')

    def test_completion_updates_stock_before_releasing(self):
        self.lua.execute('''
          a=assert(wh.fetch(item,64,'buffer'));assert(not wh.settled(a))
          jobs[a]={state='done',steps={{take=storages.stock,item=item,taken=64,maxSize=64}}}
          assert(not wh.settled(a))
          listener('logistics',a)
          assert(wh.settled(a))
          assert(wh.count(item)==64);assert(wh.fetch(item,64,'buffer'))
          assert(wh.fetch(item,1,'buffer')==nil)
        ''')

    def test_scan_has_catalogue_barrier_without_reserving_stock(self):
        self.lua.execute('''
          local ids=wh.scan({'stock'});local id=ids[1]
          assert(not wh.settled(id));jobs[id]={state='done',steps={}}
          listener('logistics',id);assert(wh.settled(id))
          assert(wh.fetch(item,128,'buffer'))
        ''')

    def test_store_destinations_count_incoming_items(self):
        self.lua.execute('''
          scan('stock',0,1)
          a=assert(wh.store(item,64,'buffer'))
          assert(wh.store(item,1,'buffer')==nil)
          jobs[a]={state='failed',steps={}};listener('logistics',a)
          assert(wh.store(item,64,'buffer'))
        ''')

    def test_other_item_reservations_use_whole_slots(self):
        self.lua.execute('''
          scan('stock',0,1)
          other={name='minecraft:brick',damage=0}
          jobs[#jobs+1]={state='done',item=other,maxSize=64,steps={}};listener('logistics',#jobs)
          assert(wh.store(other,1,'buffer'));assert(wh.store(item,1,'buffer')==nil)
        ''')


if __name__ == '__main__':
    unittest.main()
