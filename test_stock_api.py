"""T13 canonical stock/map/job API shapes and bounded redraw allocations."""
from pathlib import Path
import unittest

from lupa.lua53 import LuaRuntime
import test_warehouse_reservations as reservations


class WarehouseApiTests(unittest.TestCase):
    def setUp(self):
        fixture = reservations.ReservationTests()
        fixture.setUp()
        self.lua = fixture.lua
        self.lua.execute('''
          -- Item aggregation needs repeatable keys, as real serialization has.
          local serialization=require('serialization');local serialize=serialization.serialize
          serialization.serialize=function(t,...)
            if type(t)=='table' and type(t[1])=='string' and type(t[2])=='number' then
              local key=t[1]..'/'..tostring(t[2])..'/'..tostring(t[3]);serial[key]=t;return key
            end
            return serialize(t,...)
          end
          function scan(storage,n,size)
            local id=#jobs+1;jobs[id]={state='done',steps={{read=storages[storage],size=size or 27,
              listing=n>0 and {{name=item.name,damage=item.damage,label=item.label,size=n,maxSize=64}} or {}}}}
            listener('logistics',id)
          end
        ''')

    def test_totals_shape_aliases_sorting_and_lazy_cache(self):
        self.lua.execute('''
          assert(type(wh.revision())=='number' and wh.revision()%1==0)
          local rev=wh.revision();local before=seq
          local a=wh.totals();assert(#a==1 and a[1].count==128 and a[1].storages==1)
          assert(a[1].item.name==item.name and a[1].item.damage==0)
          local allocated=seq
          collectgarbage('collect');collectgarbage('stop');local memory=collectgarbage('count')
          for k=1,1000 do assert(wh.totals()==a and wh.revision()==rev) end
          assert(collectgarbage('count')-memory<2);collectgarbage('restart')
          assert(seq==allocated)
          storages.second={node='second',side=0};wh.add('second')
          scan('second',3)
          assert(wh.revision()>rev)
          local b=wh.totals();assert(b~=a and b[1].count==131 and b[1].storages==2)
          assert(a[1].count==128)
          item={name='aaa:x',damage=2,label='X'};scan('second',4)
          local c=wh.totals();assert(#c==2 and c[1].item.name=='aaa:x')
          assert(c[1].item.label=='X' and c[1].count==4 and c[1].storages==1)
          item={name='aaa:x',damage=0};scan('stock',1)
          c=wh.totals();assert(#c==2 and c[1].item.damage==0 and c[2].item.damage==2)
          wh.group('cpu','crafter',{buffer='alias'})
          c=wh.totals();assert(#c==1 and c[1].count==4)
          wh.ungroup('cpu');assert(#wh.totals()==2)
          wh.remove('second');assert(#wh.totals()==1)
        ''')

    def test_totals_terminal_ledger_and_empty_stock(self):
        self.lua.execute('''
          local a=wh.totals();local rev=wh.revision()
          local id=assert(wh.fetch(item,128,'buffer'))
          assert(wh.totals()==a) -- reservations are not physical stock changes
          jobs[id]={state='done',steps={{take=storages.stock,item=item,taken=128,maxSize=64}}}
          listener('logistics',id)
          assert(wh.revision()==rev+1 and #wh.totals()==0)
        ''')

    def test_role_scan_barrier_partial_read_preserves_catalogue(self):
        self.lua.execute('''
          local before=wh.contents('stock');local total=wh.totals()
          local declared={3,7};local id=assert(wh.scanRole('alias',declared))
          assert(not wh.settled(id) and #wh.inflight()==0)
          local read=jobs[id].submitted[1].read
          assert(read.storage=='alias' and read.slots[1]==3 and read.slots[2]==7)
          declared[1]=99;assert(read.slots[1]==3)
          local scoped={node=storages.alias.node,side=storages.alias.side,slots=read.slots}
          jobs[id]={state='done',steps={{read=scoped,size=27,listing={
            [7]={name='mod:small',damage=0,size=2,maxSize=16}}}}}
          listener('logistics',id)
          assert(wh.settled(id) and wh.stackSize({name='mod:small'})==16)
          assert(wh.count(item)==128 and wh.contents('stock').freeSlots==before.freeSlots)
          assert(wh.totals()[1].count==total[1].count)
          local failed=assert(wh.scanRole('stock',{1}))
          assert(not wh.settled(failed))
          jobs[failed]={state='failed',steps={}};listener('logistics',failed)
          assert(wh.settled(failed) and wh.count(item)==128)
          local partial=assert(wh.scanRole('alias',{7}));assert(not wh.settled(partial))
          jobs[partial]={state='partial',steps={{read=scoped,size=27,listing={
            [7]={name='mod:tiny',size=1,maxSize=8}}}}}
          listener('logistics',partial)
          assert(wh.settled(partial) and wh.stackSize({name='mod:tiny'})==8)
          assert(wh.count(item)==128 and wh.contents('stock').slots==27)
        ''')

    def test_role_views_capacity_real_indices_and_bounded_copy(self):
        self.lua.execute('''
          local listing={
            [2]={name='mod:wrong',damage=0,size=1,maxSize=64},
            [5]={name=item.name,damage=0,size=10,maxSize=64},
            [9]={name=item.name,damage=0,size=20,maxSize=64}}
          local view=wh.roleContents('alias',{2},listing,27)
          assert(view.slots==1 and view.freeSlots==0 and wh.roleCapacity(view,item)==0)
          assert(view.listing[2].name=='mod:wrong' and view.listing[5]==nil)
          view=wh.roleContents('alias',{5,9,12},listing,27)
          assert(view.slots==3 and view.freeSlots==1 and wh.roleCapacity(view,item)==162)
          local row;for _,v in pairs(view.items) do row=v end
          assert(row.count==30 and row.stacks==2 and row.maxSize==64 and row.room==98)
          view.listing[5].size=99;row.item.name='changed'
          assert(listing[5].size==10 and listing[5].name==item.name)
          assert(wh.roleContents('alias',{5},listing,27).listing[5].size==10)
          view=wh.roleContents('alias',{12},listing,27)
          local capacity,err=wh.roleCapacity(view,{name='mod:unknown'})
          assert(capacity==nil and err:find('unknown stack limit'))
          assert(wh.roleCapacity(view,item)==64) -- full catalogue capacity is irrelevant
          view=wh.roleContents('alias',{2},listing,27)
          assert(wh.roleCapacity(view,{name='mod:wrong'})==63) -- row limit suffices
          -- Large unselected stacks must not be traversed or copied.
          for k=30,20000 do listing[k]={name='mod:unselected',size=64,maxSize=64} end
          collectgarbage('collect');collectgarbage('stop');local memory=collectgarbage('count')
          view=wh.roleContents('alias',{5,12},listing,20000)
          assert(collectgarbage('count')-memory<16);collectgarbage('restart')
          assert(view.listing[30]==nil and view.freeSlots==1)
        ''')

    def test_role_declarations_reject_malformed_and_out_of_bounds(self):
        self.lua.execute('''
          local invalid={{},{0},{-1},{1.5},{1,1},{[1]=1,[3]=2},{[0]=1},{x=1},{math.huge}}
          for _,slots in ipairs(invalid) do
            local id,err=wh.scanRole('stock',slots);assert(id==nil and type(err)=='string')
            assert(not pcall(wh.roleContents,'stock',slots,{},27))
          end
          assert(not pcall(wh.roleContents,'stock',{28},{},27))
          assert(not pcall(wh.roleContents,'stock',{1},{},nil))
          assert(not pcall(wh.roleContents,'stock',{1},{},-1))
          assert(not pcall(wh.roleContents,'stock',{1},{},2.5))
          assert(not pcall(wh.roleContents,'absent',{1},{},27))
          local id,err=wh.scanRole('absent',{1});assert(id==nil and err)
          -- Scan declarations cannot check a remote face size until its read returns.
          assert(wh.scanRole('stock',{28}))
        ''')

    def test_role_batch_slot_bound_copies_keys_and_settlement(self):
        self.lua.execute('''
          local requests={{storage='stock',slots={2,5,7,9},key='input'},
            {storage='alias',slots={4},key='output'}}
          local ids=assert(wh.scanRoles(requests));assert(#ids==2)
          requests[1].slots[1]=99;requests[1].key='changed'
          local seen={};local before=wh.contents('stock')
          for _,id in ipairs(ids) do
            assert(not wh.settled(id));local n=0;local result={}
            for _,step in ipairs(jobs[id].submitted) do
              local read=step.read;n=n+#read.slots
              assert(read.storage=='stock' or read.storage=='alias')
              assert(step.roleKey==(read.storage=='stock' and 'input' or 'output'))
              local endpoint={node=storages[read.storage].node,side=storages[read.storage].side,slots=read.slots}
              local listing={};for _,slot in ipairs(read.slots) do
                assert(slot~=99);seen[slot]=true
                listing[slot]={name='mod:role',size=1,maxSize=16}
              end
              result[#result+1]={read=endpoint,roleKey=step.roleKey,size=27,listing=listing}
            end
            assert(n<=3 and n>0)
            jobs[id]={state='done',steps=result};listener('logistics',id)
            assert(wh.settled(id))
          end
          assert(seen[2] and seen[5] and seen[7] and seen[9] and seen[4])
          assert(wh.count(item)==128 and wh.contents('stock').freeSlots==before.freeSlots)
          assert(wh.stackSize({name='mod:role'})==16 and #wh.inflight()==0)
          -- Three single-slot faces are distinct legs of exactly one read job.
          ids=assert(wh.scanRoles({{storage='stock',slots={1},key='input'},
            {storage='alias',slots={1},key='fuel'},{storage='buffer',slots={3}}}))
          assert(#ids==1 and #jobs[ids[1]].submitted==3)
          assert(jobs[ids[1]].submitted[3].roleKey=='buffer')
          jobs[ids[1]]={state='partial',steps={}};listener('logistics',ids[1])
          assert(wh.settled(ids[1]) and wh.count(item)==128)
        ''')

    def test_role_batch_validation_precedes_any_submission(self):
        self.lua.execute('''
          local before=#jobs
          local invalid={false, {false}, {[2]={storage='stock',slots={1}}},
            {{storage='stock',slots={1}},{storage='absent',slots={1}}},
            {{storage='stock',slots={1,1}}},{{storage='stock',slots={1},key=12}}}
          for _,requests in ipairs(invalid) do
            local ids,err=wh.scanRoles(requests);assert(ids==nil and type(err)=='string')
            assert(#jobs==before)
          end
          assert(#wh.scanRoles({})==0 and #jobs==before)
        ''')

    def test_role_fits_joint_empty_slots_merge_room_and_unknown_limits(self):
        self.lua.execute('''
          local id=assert(wh.scanRole('alias',{3}))
          jobs[id]={state='done',steps={{read={node=storages.alias.node,side=1,slots={3}},size=27,
            listing={[3]={name='mod:small',damage=3,size=2,maxSize=16}}}}}
          listener('logistics',id)
          local one=wh.roleContents('alias',{1},{},27)
          local two=wh.roleContents('alias',{1,2},{},27)
          local needs={[item.name]=1,['mod:small:3']=1}
          assert(wh.roleCapacity(one,item)==64)
          assert(wh.roleCapacity(one,{name='mod:small',damage=3})==16)
          assert(wh.roleFits(one,needs)==false and wh.roleFits(two,needs)==true)
          local listing={[5]={name=item.name,damage=0,size=60,maxSize=64}}
          local view=wh.roleContents('alias',{5,9},listing,27)
          assert(wh.roleFits(view,{[item.name]=4,['mod:small:3']=16})==true)
          assert(wh.roleFits(view,{[item.name]=5,['mod:small:3']=16})==false)
          assert(wh.roleFits(view,{[item.name]=4,['mod:small:3']=17})==false)
          -- Full physical alias capacity is irrelevant: declared role has no room.
          view=wh.roleContents('alias',{5},{[5]={name='mod:wrong',size=64,maxSize=64}},27)
          assert(wh.roleFits(view,{[item.name]=1})==false)
          local fits,err=wh.roleFits(two,{['mod:unknown']=1})
          assert(fits==nil and err:find('unknown stack limit'))
          fits,err=wh.roleFits(two,{['mod:small']=1}) -- metadata zero not learned
          assert(fits==nil and err)
          assert(wh.roleFits(two,{})==true)
          for _,n in ipairs({0,-1,0.5,math.huge}) do
            assert(not pcall(wh.roleFits,two,{[item.name]=n}))
          end
        ''')

    def test_inflight_shape_copies_alias_face_and_release(self):
        self.lua.execute('''
          assert(#wh.inflight()==0)
          local id=assert(wh.fetch(item,64,'buffer'))
          local a=wh.inflight();assert(#a==1)
          local r=a[1];assert(r.job==id and r.count==64 and r.kind=='fetch')
          assert(r.storage=='alias' and r.item.name==item.name and r.item.damage==0)
          r.item.name='bad';r.count=999;r.storage='bad'
          assert(wh.inflight()[1].count==64 and wh.inflight()[1].item.name==item.name)
          jobs[id]={state='failed',steps={}};listener('logistics',id)
          assert(#wh.inflight()==0)
          scan('stock',0,1)
          id=assert(wh.store(item,32,'buffer'));r=wh.inflight()[1]
          assert(r.job==id and r.kind=='store' and r.storage=='alias' and r.count==32)
          jobs[id]={state='partial',steps={}};listener('logistics',id)
          assert(#wh.inflight()==0)
          local ids=wh.scan('stock');assert(#wh.inflight()==0 and not wh.settled(ids[1]))
        ''')


class LibraryApiTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute('''
          serial={};seq=0;copies=0
          function clone(t)
            if type(t)~='table' then return t end
            local out={};for k,v in pairs(t) do out[k]=clone(v) end;return out
          end
          package.preload.serialization=function() return {
            serialize=function(t) copies=copies+1;seq=seq+1;serial[tostring(seq)]=clone(t);return tostring(seq) end,
            unserialize=function(s) return clone(serial[s]) end} end
          files={};io.open=function(path,mode)
            if mode=='r' and not files[path] then return nil end
            return {read=function() return files[path] end,
              write=function(_,s) files[path]=s end,close=function() end}
          end
          package.preload.event=function() return {push=function() end,listen=function() end} end
          package.preload.component=function() return {modem={
            isWireless=function() return true end,open=function() end}} end
        ''')

    def load(self, library, variable):
        self.lua.globals().SOURCE = Path(f'drone-logistics/lib/{library}.lua').read_text()
        self.lua.execute(f'{variable}=assert(load(SOURCE))()')

    def test_map_shared_indexes_every_edit_and_load(self):
        self.load('map', 'map')
        self.lua.execute('''
          assert(#map.names()==0 and #map.storageNames()==0)
          map.add('z',0,0,0);map.add('a',1,0,0)
          local names=map.names();assert(names[1]=='a' and names[2]=='z')
          local sn=map.storageNames();local rev=map.revision();local n=copies
          collectgarbage('collect');collectgarbage('stop');local memory=collectgarbage('count')
          for k=1,1000 do assert(map.names()==names and map.storageNames()==sn) end
          assert(collectgarbage('count')-memory<2);collectgarbage('restart')
          assert(copies==n and map.revision()==rev)
          map.name('zz','z',0);assert(map.revision()==rev+1)
          assert(map.names()~=names and map.storageNames()[1]=='zz')
          map.name('aa','a',0);assert(map.storageNames()[1]=='aa')
          rev=map.revision();map.unname('zz');assert(map.revision()==rev+1)
          assert(#map.storageNames()==1)
          names=map.names();map.link('a','z');assert(map.names()~=names)
          names=map.names();map.unlink('a','z');assert(map.names()~=names)
          map.save();map.remove('a');assert(#map.names()==1 and #map.storageNames()==0)
          map.load();assert(#map.names()==2 and map.storageNames()[1]=='aa')
          names=map.names();map.add('a',2,0,0);assert(map.names()~=names)
        ''')

    def load_logistics(self):
        self.lua.execute('''
          files['/lib/logistics/agent.lua']='return true'
          package.preload.map=function() return {
            buildClear=function() end,
            storage=function(s) return {node=s,side=0} end,
            node=function(s) return {x=0,y=0,z=0,faces={[0]=true}} end,
            place=function(s) return s end} end
        ''')
        self.load('logistics', 'lg')

    def test_warehouse_real_map_edits_invalidate_stock_cache(self):
        self.load('map', 'map')
        self.lua.execute('''
          package.loaded.map=map
          package.preload.computer=function() return {uptime=function() return 0 end} end
          jobs={}
          package.preload.logistics=function() return {
            status=function(id) return jobs[id] end} end
          package.loaded.event={push=function() end,listen=function(_,fn) listener=fn end}
          os.rename=function() return true end
          map.add('rack',0,0,0);map.add('other',1,0,0)
          map.name('stock','rack',0);map.name('alias','rack',1)
          files['/etc/warehouse.cfg']=require('serialization').serialize({
            members={stock={},alias={inventory='stock'}},groups={}})
        ''')
        self.load('warehouse', 'wh')
        self.lua.execute('''
          item={name='mod:stock',damage=0}
          jobs[1]={state='done',steps={{read=map.storage('stock'),size=27,
            listing={{name=item.name,damage=0,size=128,maxSize=64}}}}}
          listener('logistics',1)
          local cached=wh.totals();local rev=wh.revision()
          local function verify(count,revisionFirst)
            if revisionFirst then assert(wh.revision()>rev) end
            local totals=wh.totals()
            assert(totals~=cached and wh.revision()>rev)
            assert(wh.count(item)==count)
            assert(#totals==(count>0 and 1 or 0))
            if count>0 then assert(totals[1].count==count and totals[1].storages==1) end
            cached=totals;rev=wh.revision()
          end
          assert(cached[1].count==128 and cached[1].storages==1)
          map.unname('stock');verify(128,true) -- alias still exposes physical stock
          map.name('alias','other',0);verify(128,false) -- remapped alias
          map.unname('alias');verify(0,true) -- no remaining eligible faces
          map.name('stock','rack',0);verify(128,false) -- observation survives restoration
          map.name('alias','rack',1);verify(128,true) -- aliases never double count
          map.save();map.remove('rack');verify(0,false)
          map.load();verify(128,true)
          -- Checking both revision and totals on unchanged redraws is allocation-free.
          collectgarbage('collect');collectgarbage('stop');local memory=collectgarbage('count')
          local before=copies
          for k=1,1000 do assert(wh.revision()==rev and wh.totals()==cached) end
          assert(collectgarbage('count')-memory<2 and copies==before)
          collectgarbage('restart')
        ''')

    def test_jobs_window_shape_serialization_bound_and_legacy(self):
        self.load_logistics()
        self.lua.execute('''
          local empty,total=lg.jobs(true,1,5);assert(#empty==0 and total==0)
          for k=1,100 do lg.transfer({name='mod:x',damage=k},k,'from','to') end
          local before=copies;local rows,total=lg.jobs(true,3,4)
          assert(total==100 and #rows==4 and copies-before==4)
          for k,j in ipairs(rows) do
            assert(j.id==99-k and j.state=='queued' and j.moved==0)
            assert(j.requested==j.id and j.item.damage==j.id and j.item.name=='mod:x')
            assert(j.from.node=='from' and j.to.node=='to' and j.steps==nil)
          end
          rows[1].item.name='changed';assert(lg.jobs(true,3,1)[1].item.name=='mod:x')
          before=copies;rows,total=lg.jobs(true,101,20);assert(#rows==0 and total==100 and copies==before)
          rows,total=lg.jobs(true,1,0);assert(#rows==0 and total==100 and copies==before)
          rows,total=lg.jobs(true,99,20);assert(#rows==2 and total==100)
          rows,total=lg.jobs(true,99);assert(#rows==2 and total==100)
          rows,total=lg.jobs(true);assert(#rows==100 and rows[1].id==100 and total==100)
          rows,total=lg.jobs();assert(#rows==100 and rows[1].remaining==100 and total==100)
          rows,total=lg.jobs(false,4,2);assert(#rows==2 and rows[1].id==97 and rows[1].trips==0)
          for _,args in ipairs({{true,0,1},{true,1,-1},{true,1.5,1},{true,1,0.5},{'bad'}}) do
            assert(not pcall(lg.jobs,table.unpack(args)))
          end
        ''')

    def test_role_batch_metadata_survives_real_logistics_normalization(self):
        self.load_logistics()
        self.lua.execute('''
          package.loaded.logistics=lg
          package.preload.computer=function() return {uptime=function() return 0 end} end
        ''')
        self.load('warehouse', 'wh')
        self.lua.execute('''
          local ids=assert(wh.scanRoles({{storage='face-a',slots={2},key='input'},
            {storage='face-b',slots={4},key='fuel'},{storage='face-c',slots={1},key='output'}}))
          assert(#ids==1 and not wh.settled(ids[1]))
          local job=lg.status(ids[1]);assert(job.state=='queued' and #job.steps==3)
          assert(job.steps[1].roleKey=='input' and job.steps[1].read.node=='face-a')
          assert(job.steps[2].roleKey=='fuel' and job.steps[2].read.slots[1]==4)
          assert(job.steps[3].roleKey=='output' and job.steps[3].read.node=='face-c')
        ''')

    def test_job_steps_summary_does_not_copy_read_packet_and_retention_gaps(self):
        self.load_logistics()
        self.lua.execute('''
          local listing={};for k=1,20000 do listing[k]={name='mod:x',size=64} end
          local id=lg.job({{read='source',listing=listing},{take='source',item={name='mod:x'},count=8},
            {put='sink',item={name='mod:x'},rest=true}})
          collectgarbage('collect');collectgarbage('stop');local memory=collectgarbage('count')
          local before=copies;local rows,total=lg.jobs(true,1,1)
          assert(collectgarbage('count')-memory<16);collectgarbage('restart')
          assert(total==1 and copies-before==1)
          local j=rows[1];assert(j.id==id and j.item.name=='mod:x' and j.requested==8)
          assert(j.from.node=='source' and j.to.node=='sink' and j.steps==nil)
          assert(#lg.jobs(false)[1].steps==3)
          -- Invalid steps finish synchronously, exercising the retained 32-job cap.
          for k=1,40 do lg.job({{bogus=true}}) end
          rows,total=lg.jobs(true,31,5)
          assert(total==33 and #rows==3 and rows[1].id==11 and rows[3].id==1)
          assert(rows[1].state=='failed' and type(rows[1].reason)=='string')
        ''')


if __name__ == '__main__':
    unittest.main()
