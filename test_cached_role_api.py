"""Exact-face authoritative warehouse role cache and submission barriers."""
import unittest
import test_stock_api


class CachedRoleApiTests(unittest.TestCase):
    def setUp(self):
        fixture = test_stock_api.WarehouseApiTests()
        fixture.setUp()
        self.lua = fixture.lua
        self.lua.execute('''
          function cold(storage,slots)
            local view,err=wh.cachedRoleContents(storage,slots)
            assert(view==nil and type(err)=='string',storage..' unexpectedly warm')
          end
          function readRole(storage,slots,listing,size,state)
            local id=assert(wh.scanRole(storage,slots))
            jobs[id]={state=state or 'done',steps={{read={node=storages[storage].node,
              side=storages[storage].side,slots=slots},listing=listing,size=size or 27}}}
            listener('logistics',id);return id
          end
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

    def test_cold_exact_face_declared_empty_and_pure_helper(self):
        self.lua.execute('''
          local before=#jobs;cold('alias',{1})
          wh.roleContents('alias',{1},{[1]=stack(5)},27)
          cold('alias',{1});assert(#jobs==before)
          readRole('alias',{3,7},{[7]=stack(2),[9]=stack(50)})
          local view=assert(wh.cachedRoleContents('alias',{3,7}))
          assert(view.slots==2 and view.freeSlots==1 and view.listing[7].size==2)
          assert(view.listing[9]==nil);cold('alias',{9});cold('alias',{1})
          -- The initial stock face read verified this slot empty, never alias fuel.
          assert(wh.cachedRoleContents('stock',{7}).freeSlots==1)
          local onlyEmpty=assert(wh.cachedRoleContents('alias',{3}))
          assert(next(onlyEmpty.items)==nil and onlyEmpty.freeSlots==1)
          storages.sameFace={node=storages.alias.node,side=storages.alias.side}
          assert(wh.cachedRoleContents('sameFace',{7}).listing[7].size==2)
          assert(wh.count(item)==128) -- no partial catalogue replacement
          assert(not wh.cachedRoleContents('alias',{28}))
        ''')

    def test_fresh_views_and_latest_size(self):
        self.lua.execute('''
          local listing={[7]=stack(2)};readRole('alias',{3,7},listing)
          listing[7].size=50
          local a=assert(wh.cachedRoleContents('alias',{3,7}))
          a.listing[7].size=60
          for _,v in pairs(a.items) do v.item.name='changed';v.count=999 end
          local b=assert(wh.cachedRoleContents('alias',{3,7}))
          assert(b~=a and b.listing~=a.listing and b.listing[7].size==2)
          for _,v in pairs(b.items) do assert(v.item.name==item.name and v.count==2) end
          readRole('alias',{2},{},4)
          assert(wh.cachedRoleContents('alias',{2}).freeSlots==1)
          cold('alias',{7}) -- latest reported face size is authoritative
        ''')

    def test_full_read_covers_face_without_cross_face_reuse(self):
        self.lua.execute('''
          scan('alias',5,27)
          assert(wh.cachedRoleContents('alias',{1}).listing[1].size==5)
          assert(wh.cachedRoleContents('alias',{2,27}).freeSlots==2)
          storages.other={node='other',side=1};wh.add('other',{inventory='stock'})
          -- Config alias edits conservatively invalidate volatile observations.
          scan('alias',5,27);cold('other',{1})
          assert(wh.cachedRoleContents('alias',{27}).freeSlots==1)
        ''')

    def test_missing_failed_and_partial_batch_read_results(self):
        self.lua.execute('''
          readRole('alias',{3,7},{[7]=stack(2)})
          local id=assert(wh.scanRole('alias',{7}))
          jobs[id]={state='failed',steps={}};listener('logistics',id)
          cold('alias',{7});assert(wh.cachedRoleContents('alias',{3}))
          readRole('alias',{7},{[7]=stack(2)})
          readRole('alias',{7},nil,27,'failed');cold('alias',{7})
          local ids=assert(wh.scanRoles({{storage='alias',slots={3,7}},
            {storage='buffer',slots={2}}}))
          id=ids[1];jobs[id]={state='partial',steps={{read={node='stock',side=1,slots={3,7}},
            size=27,listing={[7]=stack(4)}}}}
          listener('logistics',id)
          assert(wh.cachedRoleContents('alias',{3,7}).listing[7].size==4)
          cold('buffer',{2});assert(wh.settled(id))
          id=assert(wh.scanRole('alias',{3}));jobs[id]={state='done',steps={}}
          listener('logistics',id);cold('alias',{3})
          readRole('alias',{3},{})
          local lg=require('logistics');local submit=lg.job
          lg.job=function() return nil,'read refused' end
          local refused,err=wh.scanRole('alias',{3})
          assert(refused==nil and err=='read refused');cold('alias',{3})
          lg.job=submit
        ''')

    def test_fallback_pending_and_settled_alias_source_destination(self):
        self.lua.execute('''
          readRole('alias',{7},{[7]=stack(2)})
          readRole('buffer',{2},{})
          local id=assert(wh.fetch(item,1,'buffer'))
          cold('alias',{7});cold('stock',{2});cold('buffer',{2})
          -- A scan completed after submission cannot authorize pending stock.
          readRole('alias',{7},{[7]=stack(2)})
          readRole('buffer',{2},{})
          cold('alias',{7});cold('buffer',{2})
          jobs[id]={state='failed',steps={}};listener('logistics',id)
          cold('alias',{7});cold('buffer',{2})
          readRole('alias',{7},{[7]=stack(2)})
          assert(wh.cachedRoleContents('alias',{7}))
          scan('stock',0,1);readRole('buffer',{2},{[2]=stack(1)})
          id=assert(wh.store(item,1,'buffer'))
          cold('stock',{1});cold('buffer',{2})
          jobs[id]={state='partial',steps={}};listener('logistics',id)
          cold('stock',{1});cold('buffer',{2})
        ''')

    def test_physical_coordinates_other_face_and_alias_invalidation(self):
        self.lua.execute('''
          local map=require('map')
          local nodes={stock={x=0,y=1,z=0},opposite={x=0,y=-1,z=0},
            distant={x=99,y=0,z=0},buffer={x=1,y=1,z=0}}
          map.node=function(n) return nodes[n] end
          storages.opposite={node='opposite',side=1}
          storages.distant={node='distant',side=0}
          wh.add('distant',{inventory='stock'})
          readRole('stock',{2},{})
          cold('opposite',{2});cold('distant',{2})
          readRole('opposite',{2},{[2]=stack(1)})
          readRole('distant',{2},{[2]=stack(1)})
          readRole('buffer',{2},{})
          local id=assert(wh.fetch(item,1,'buffer'))
          cold('stock',{2});cold('opposite',{2});cold('distant',{2});cold('buffer',{2})
          readRole('opposite',{2},{})
          cold('opposite',{2})
          jobs[id]={state='done',steps={}};listener('logistics',id)
          cold('opposite',{2});cold('distant',{2})
        ''')

    def test_direct_router_hook_pending_overlap_and_missing_settlement_legs(self):
        self.lua.execute('''
          local lg=require('logistics');local hooks={}
          lg.onMutation=function(key,callback) hooks[key]=callback;return true end
          lg.job=function(steps)
            local endpoints={};local id=#jobs+1
            for _,step in ipairs(steps) do
              if step.take or step.put then
                local e=step.take or step.put
                if type(e)=='string' then e=storages[e] end
                endpoints[#endpoints+1]={node=e.node,side=e.side}
              end
            end
            for _,callback in pairs(hooks) do callback(id,endpoints) end
            jobs[id]={state='queued',submitted=steps};return id
          end
          wh=assert(load(SOURCE))() -- registration with router hook
          readRole('alias',{7},{[7]=stack(2)})
          readRole('buffer',{2},{})
          local a=lg.job({{take='stock'},{put='buffer'}})
          local b=lg.job({{take='stock'}})
          cold('alias',{7});cold('buffer',{2})
          readRole('alias',{7},{[7]=stack(2)});cold('alias',{7})
          jobs[a]={state='failed',steps={}};listener('logistics',a)
          cold('alias',{7});cold('buffer',{2})
          readRole('alias',{7},{[7]=stack(2)});cold('alias',{7})
          jobs[b]={state='done',steps={}};listener('logistics',b)
          cold('alias',{7})
          readRole('alias',{7},{[7]=stack(2)})
          assert(wh.cachedRoleContents('alias',{7}))
        ''')

    def test_map_revision_invalidates_all_slot_observations(self):
        self.lua.execute('''
          local revision=0;require('map').revision=function() return revision end
          readRole('alias',{3,7},{[7]=stack(2)})
          revision=revision+1;cold('alias',{3});cold('stock',{2})
          readRole('alias',{3},{})
          revision=revision+1;wh.totals();cold('alias',{3})
          readRole('alias',{3},{})
          revision=revision+1;wh.revision();cold('alias',{3})
        ''')

    def test_repeated_bounded_calls_over_large_listing(self):
        self.lua.execute('''
          local listing={};for k=1,20000 do listing[k]=stack(1) end
          readRole('alias',{3,7},listing,20000)
          cold('alias',{20000})
          -- Also stress a fully observed 20k-slot exact-face cache.
          local id=#jobs+1;jobs[id]={state='done',steps={{read=storages.alias,
            size=20000,listing=listing}}};listener('logistics',id)
          assert(wh.cachedRoleContents('alias',{20000}))
          local before=seq;local jobsBefore=#jobs
          collectgarbage('collect');collectgarbage('stop');local memory=collectgarbage('count')
          for k=1,100 do
            local m=collectgarbage('count')
            local view=assert(wh.cachedRoleContents('alias',{3,7}))
            assert(view.slots==2 and view.freeSlots==0 and view.listing[20000]==nil)
            assert(collectgarbage('count')-m<16)
          end
          assert(collectgarbage('count')-memory<1600);collectgarbage('restart')
          assert(seq==before and #jobs==jobsBefore)
        ''')

    def test_later_batch_submission_failure_preserves_ids_and_reason(self):
        self.lua.execute('''
          local lg=require('logistics');local submit=lg.job
          for _,throws in ipairs({false,true}) do
            local calls=0
            lg.job=function(steps,opts)
              calls=calls+1
              if calls==2 then
                if throws then error('batch refused') end
                return nil,'batch refused'
              end
              return submit(steps,opts)
            end
            local ids,err,submitted=wh.scanRoles({{storage='alias',slots={1,2,3,4}}})
            assert(ids==nil and err:find('batch refused') and #submitted==1)
            local id=submitted[1];assert(type(id)=='number' and not wh.settled(id))
            jobs[id]={state='done',steps={}};listener('logistics',id)
            assert(wh.settled(id))
          end
          lg.job=function() return nil,'first refused' end
          local ids,err,submitted=wh.scanRoles({{storage='alias',slots={1}}})
          assert(ids==nil and err=='first refused' and #submitted==0)
        ''')

    def test_mutation_metadata_index_rebuilds_once_not_per_endpoint(self):
        self.lua.execute('''
          local map=require('map');local lg=require('logistics');local callback
          local revision=0;map.revision=function() return revision end
          map.node=function(node)
            return {x=3*(tonumber(node:match('%d+')) or (node=='buffer' and -1 or 0)),y=1,z=0}
          end
          lg.onMutation=function(_,fn) callback=fn;return true end
          wh=assert(load(SOURCE))()
          for k=1,64 do
            local name='rack'..k;storages[name]={node=name,side=0};wh.add(name)
          end
          local storage=map.storage;local calls=0
          map.storage=function(name) calls=calls+1;return storage(name) end
          local endpoints={storages.stock,storages.buffer}
          callback(101,endpoints)
          assert(calls>=64 and calls<=68,'first rebuild '..calls)
          calls=0
          for id=102,111 do callback(id,endpoints) end
          assert(calls==0,'unchanged mutation copied '..calls..' descriptors')
          for id=101,111 do
            jobs[id]={state='failed',steps={}};listener('logistics',id)
          end
          assert(calls==0,'settlement copied '..calls..' descriptors')
          revision=revision+1;callback(112,endpoints)
          assert(calls>=64 and calls<=68,'map edit rebuild '..calls)
          calls=0;callback(113,endpoints);assert(calls==0)
          storages.newRack={node='rack99',side=0};wh.add('newRack',{inventory='stock'})
          calls=0;callback(114,endpoints)
          assert(calls>=65 and calls<=69,'alias edit rebuild '..calls)
          calls=0;callback(115,endpoints);assert(calls==0)
        ''')

    def test_late_read_and_read_during_mutation_never_restore_stale_fuel(self):
        self.lua.execute('''
          local lg=installHooks()
          local ids=assert(wh.scanRoles({{storage='alias',slots={7},key='fuel'},
            {storage='buffer',slots={2},key='other'}}))
          local delayed=ids[1]
          local mutation=lg.job({{take='alias',item=item,count=2}})
          jobs[mutation]={state='done',steps={{take=storages.alias,item=item,taken=2,maxSize=64}}}
          listener('logistics',mutation)
          jobs[delayed]={state='done',steps={
            {read={node='stock',side=1,slots={7}},size=27,listing={[7]=stack(2)}},
            {read={node='buffer',side=0,slots={2}},size=27,listing={}}}}
          listener('logistics',delayed);cold('alias',{7})
          assert(wh.cachedRoleContents('buffer',{2}).freeSlots==1)
          assert(wh.settled(mutation) and wh.settled(delayed))
          readRole('alias',{7},{})
          assert(wh.cachedRoleContents('alias',{7}).freeSlots==1)
          mutation=lg.job({{put='alias',item=item,count=2}})
          local during=lg.job({{read={storage='alias',slots={7}}}})
          assert(not wh.settled(during))
          jobs[mutation]={state='failed',steps={}};listener('logistics',mutation)
          finishRead(during,'alias',{7},2);cold('alias',{7})
          assert(wh.settled(during))
          readRole('alias',{7},{})
          assert(next(wh.cachedRoleContents('alias',{7}).items)==nil)
        ''')

    def test_full_catalogue_read_provenance_and_metadata_edits(self):
        self.lua.execute('''
          local lg=installHooks()
          local initial=lg.job({{read='stock'}});finishRead(initial,'stock',nil,5)
          assert(wh.count(item)==5)
          local stale=lg.job({{read='stock'}})
          local mutation=lg.job({{take='alias',item=item,count=2}})
          jobs[mutation]={state='done',steps={{take=storages.alias,item=item,taken=2,maxSize=64}}}
          listener('logistics',mutation);assert(wh.count(item)==3)
          finishRead(stale,'stock',nil,5)
          assert(wh.count(item)==3);cold('stock',{1})
          local unrelated=lg.job({{read={storage='alias',slots={7}}}})
          mutation=lg.job({{put='buffer',item=item,count=2}})
          jobs[mutation]={state='failed',steps={}};listener('logistics',mutation)
          finishRead(unrelated,'alias',{7},2)
          assert(wh.cachedRoleContents('alias',{7}).listing[7].size==2)
          local revision=0;require('map').revision=function() return revision end
          local edited=lg.job({{read={storage='alias',slots={7}}}})
          revision=revision+1;finishRead(edited,'alias',{7},2);cold('alias',{7})
          readRole('alias',{7},{})
          edited=lg.job({{read={storage='alias',slots={7}}}})
          wh.add('alias',{inventory='stock'})
          finishRead(edited,'alias',{7},2);cold('alias',{7})
          readRole('alias',{7},{})
          assert(wh.cachedRoleContents('alias',{7}).freeSlots==1)
        ''')


if __name__ == '__main__':
    unittest.main()
