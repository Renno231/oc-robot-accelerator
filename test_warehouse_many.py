"""Packed multi-item warehouse tours; existing stock fixtures stay unchanged."""
import unittest
import test_stock_api


class WarehouseManyTests(unittest.TestCase):
    def test_collect_wait_for_splits_across_pieces_and_stack_limits(self):
        self.lua.execute('''
          observe('stock',{stack('mod:out',44)},1)
          addStorage('other',{stack('mod:out',44)},1)
          local ids=assert(wh.collect('buffer',{{item={name='mod:out'},count=40,waitFor=10}},{wait={timeout=5}}))
          local takes={};for _,id in ipairs(ids) do for _,s in ipairs(jobs[id].submitted) do
            if s.take then takes[#takes+1]=s end
          end end
          assert(#takes==2 and takes[1].waitFor==10 and takes[2].waitFor==0)
          local packed
          for i=1,100 do local name,value=debug.getupvalue(wh.collect,i)
            if name=='packedJobs' then packed=value;break end
          end
          assert(packed)
          local item={name='mod:out',damage=0}
          local tours=packed({{item=item,count=40}},{{item=item,requestIndex=1,count=32,maximum=64,from='buffer',to='stock',waitFor=10},
            {item=item,requestIndex=1,count=8,maximum=16,from='buffer',to='other',waitFor=0}},{},4,{})
          takes={};local sum=0
          for _,tour in ipairs(tours) do for _,s in ipairs(tour.steps) do if s.take then
            takes[#takes+1]=s;sum=sum+(s.waitFor or 0);assert(s.count<=16)
          end end end
          assert(#takes==3 and sum==10 and takes[1].waitFor==10 and takes[2].waitFor==0 and takes[3].waitFor==0)
        ''')

    def test_collection_wait_reaches_logistics_job(self):
        self.lua.execute('''
          observe('stock',{},3)
          local opts={wait={timeout=5}}
          local ids=assert(wh.collect('buffer',{{item={name='mod:output'},count=4}},opts))
          assert(jobs[ids[1]].opts.wait.timeout==5 and opts.retries==nil)
        ''')

    def setUp(self):
        fixture = test_stock_api.WarehouseApiTests()
        fixture.setUp()
        self.lua = fixture.lua
        self.lua.execute('''
          function clone(t)
            if type(t)~='table' then return t end
            local out={};for k,v in pairs(t) do out[k]=clone(v) end;return out
          end
          require('serialization').unserialize=function(key) return clone(serial[key]) end
          FLEET={{name='a',cargoSlots=4},{name='b',cargoSlots=6}}
          local lg=require('logistics');lg.drones=function() return clone(FLEET) end
          lg.job=function(steps,opts)
            local id=#jobs+1;jobs[id]={state='queued',submitted=clone(steps),opts=clone(opts)};return id
          end
          function stack(name,count,maximum)
            return {name=name,damage=0,size=count,maxSize=maximum or 64}
          end
          function observe(storage,listing,size)
            local id=#jobs+1;jobs[id]={state='done',steps={{read=storages[storage],
              listing=listing,size=size or 27}}};listener('logistics',id)
          end
          function addStorage(name,listing,size,settings)
            storages[name]={node=name,side=0};wh.add(name,settings);observe(name,listing,size)
          end
          function setupFour()
            observe('stock',{stack('mod:a',16),stack('mod:b',16),stack('mod:c',16),stack('mod:d',16)})
            return {{item={name='mod:a'},count=16},{item={name='mod:b'},count=16},
              {item={name='mod:c'},count=16},{item={name='mod:d'},count=16}}
          end
          function ep(value)
            if type(value)=='string' then return clone(storages[value]) end
            if value.storage then local out=clone(storages[value.storage]);out.slots=clone(value.slots);return out end
            return clone(value)
          end
          function deliver(id,shortItem,shortCount)
            local job=jobs[id];local result,held,perItem={},{},{}
            for k,r in ipairs(job.opts.expectedItems) do
              perItem[k]={item=clone(r.item),requestIndex=r.requestIndex,requested=r.count,moved=0,taken=0,returned=0,overflow=0}
            end
            local delivered=0
            for _,s in ipairs(job.submitted) do
              local r={item=clone(s.item),maxSize=s.maxSize,expectedIndex=s.expectedIndex}
              local key=s.item.name..':'..s.item.damage
              if s.take then
                local n=s.item.name==shortItem and math.min(s.count,shortCount or 0) or s.count
                r.take=ep(s.take);r.taken=n;r.moved=n;held[key]=(held[key] or 0)+n
                perItem[s.expectedIndex].taken=perItem[s.expectedIndex].taken+n
                if n<s.count then r.short=true;r.found=0 end
              else
                local n=math.min(s.count,held[key] or 0);held[key]=(held[key] or 0)-n
                r.put=ep(s.put);r.moved=n;delivered=delivered+n
                perItem[s.expectedIndex].moved=perItem[s.expectedIndex].moved+n
                LANDINGS=LANDINGS or {};local face=r.put.node..':'..r.put.side
                LANDINGS[face]=LANDINGS[face] or {}
                if n>0 then LANDINGS[face][r.put.slots and r.put.slots[1] or 1]=s.item.name end
              end
              result[#result+1]=r
            end
            local partial=false
            for _,r in ipairs(perItem) do r.shortfall=r.requested-r.moved;partial=partial or r.shortfall>0 end
            jobs[id]={state=partial and 'partial' or 'done',steps=result,perItem=perItem,trips=1,moved=delivered}
            listener('logistics',id)
          end
        ''')

    def test_four_types_one_tour_reservations_settlement_and_copies(self):
        self.lua.execute('''
          local requests=setupFour();local ids=assert(wh.fetchMany(requests,'buffer'))
          assert(#ids==1 and not wh.settled(ids[1]))
          local job=jobs[ids[1]];assert(#job.submitted==8 and #job.opts.expectedItems==4)
          assert(job.opts.drones==1 and job.opts.split==false)
          for k,s in ipairs(job.submitted) do
            assert(s.maxSize==64 and s.expectedIndex>=1 and s.expectedIndex<=4)
            assert(k<=4 and s.take or k>4 and s.put)
          end
          requests[1].count=999;requests[1].item.name='changed'
          assert(job.opts.expectedItems[1].count==16 and job.opts.expectedItems[1].item.name=='mod:a')
          assert(#wh.inflight()==4)
          local more,err=wh.fetchMany({{item={name='mod:a'},count=1}},'buffer')
          assert(more==nil and err:find('unavailable'))
          deliver(ids[1]);assert(wh.settled(ids[1]) and #wh.inflight()==0)
          assert(jobs[ids[1]].trips==1 and #jobs[ids[1]].perItem==4)
          for _,r in ipairs(jobs[ids[1]].perItem) do assert(r.moved==16 and r.shortfall==0) end
          assert(wh.count({name='mod:a'})==0)
        ''')

    def test_five_stacks_split_and_non64_limits(self):
        self.lua.execute('''
          local listing,requests={},{}
          for k=1,5 do listing[k]=stack('mod:'..k,16,16);requests[k]={item={name='mod:'..k},count=16} end
          observe('stock',listing)
          local ids=assert(wh.fetchMany(requests,'buffer'));assert(#ids==2)
          assert(#jobs[ids[1]].submitted==8 and #jobs[ids[2]].submitted==2)
          for _,id in ipairs(ids) do for _,s in ipairs(jobs[id].submitted) do assert(s.maxSize==16) end;deliver(id) end
          assert(jobs[ids[1]].trips+jobs[ids[2]].trips==2)
          observe('stock',{stack('mod:tiny',16,16),stack('mod:tiny',16,16),stack('mod:tiny',16,16),
            stack('mod:tiny',16,16),stack('mod:tiny',16,16)})
          ids=assert(wh.fetchMany({{item={name='mod:tiny'},count=80}},'buffer'))
          assert(#ids==2 and jobs[ids[1]].opts.expectedItems[1].count==64
            and jobs[ids[2]].opts.expectedItems[1].count==16)
        ''')

    def test_multiple_sources_alias_reservations_and_observed_fragmentation(self):
        self.lua.execute('''
          observe('stock',{stack('mod:a',2)})
          addStorage('second',{stack('mod:b',2)})
          local ids=assert(wh.fetchMany({{item={name='mod:a'},count=2},{item={name='mod:b'},count=2}},'buffer'))
          assert(#ids==1)
          local sources={};for _,s in ipairs(jobs[ids[1]].submitted) do if s.take then
            sources[type(s.take)=='table' and s.take.storage or s.take]=true end end
          assert((sources.alias or sources.stock) and sources.second)
          local fail=wh.fetchMany({{item={name='mod:a'},count=1}},'buffer');assert(fail==nil)
          jobs[ids[1]]={state='failed',steps={}};listener('logistics',ids[1])
          assert(#wh.inflight()==0 and wh.fetchMany({{item={name='mod:a'},count=2}},'buffer'))
          -- Known separate stacks are not collapsed into one assumed NBT stack.
          observe('second',{stack('mod:fragment',1),stack('mod:fragment',1),stack('mod:fragment',1),
            stack('mod:fragment',1),stack('mod:fragment',1)})
          ids=assert(wh.fetchMany({{item={name='mod:fragment'},count=5}},'buffer'));assert(#ids==2)
        ''')

    def test_known_and_runtime_shortfalls_deliver_other_items(self):
        self.lua.execute('''
          observe('stock',{stack('mod:a',2),stack('mod:b',5)})
          local requests={{item={name='mod:a'},count=4},{item={name='mod:b'},count=5}}
          local ids=assert(wh.fetchMany(requests,'buffer'));assert(#ids==1)
          deliver(ids[1],'mod:a',1)
          local s=jobs[ids[1]];assert(s.state=='partial' and s.trips==1 and wh.settled(ids[1]))
          local byName={};for _,r in ipairs(s.perItem) do byName[r.item.name]=r end
          assert(byName['mod:a'].requested==4 and byName['mod:a'].moved==1 and byName['mod:a'].shortfall==3)
          assert(byName['mod:b'].moved==5 and byName['mod:b'].shortfall==0 and #wh.inflight()==0)
          -- Item known from a prior read but now entirely unavailable gets an expected row, no take leg.
          observe('stock',{stack('mod:b',1)})
          ids=assert(wh.fetchMany({{item={name='mod:a'},count=1},{item={name='mod:b'},count=1}},'buffer'))
          assert(#jobs[ids[1]].opts.expectedItems==2)
          deliver(ids[1]);assert(jobs[ids[1]].state=='partial')
        ''')

    def test_collect_takes_expected_items_without_looking_and_counts_what_was_there(self):
        self.lua.execute('''
          observe('stock',{},3)
          local before=#jobs
          local ids=assert(wh.collect({storage='buffer',slots={7}},{{item={name='mod:output'},count=4}}))
          assert(#ids==1 and #jobs==before+1) -- one trip: no read job first
          local job=jobs[ids[1]];assert(job.opts.retries==0)
          for _,s in ipairs(job.submitted) do
            assert(not s.read and s.item.name=='mod:output')
            if s.take then assert(s.take.storage=='buffer' and s.take.slots[1]==7 and s.count==4) end
          end
          deliver(ids[1],'mod:output',2)
          assert(wh.count({name='mod:output'})==2)
        ''')

    def test_validation_unknown_limits_fleet_and_later_failure_ids(self):
        self.lua.execute('''
          local requests=setupFour();local before=#jobs
          local invalid={false,{false},{[2]={item={name='mod:a'},count=1}},
            {{item={name='mod:a'},count=1},{item={name='mod:b'},count=0}},
            {{item={name='mod:a'},count=math.huge}}}
          for _,r in ipairs(invalid) do assert(wh.fetchMany(r,'buffer')==nil and #jobs==before) end
          assert(wh.fetchMany({{item={name='mod:unknown'},count=1}},'buffer')==nil)
          FLEET={{name='cold'}};assert(wh.fetchMany(requests,'buffer')==nil and #jobs==before)
          FLEET={{cargoSlots=2},{cargoSlots=4}}
          local lg=require('logistics');local submit=lg.job;local calls=0
          lg.job=function(steps,opts)
            calls=calls+1;if calls==2 then return nil,'second tour refused' end
            return submit(steps,opts)
          end
          local ids,err,submitted=wh.fetchMany(requests,'buffer')
          assert(ids==nil and err=='second tour refused' and #submitted==1)
          assert(not wh.settled(submitted[1]) and #wh.inflight()==2)
          jobs[submitted[1]]={state='failed',steps={}};listener('logistics',submitted[1])
          assert(wh.settled(submitted[1]) and #wh.inflight()==0)
        ''')

    def test_one_machine_load_across_two_faces_one_tour(self):
        self.lua.execute('''
          observe('stock',{stack('mod:input',2),stack('mod:fuel',3)})
          storages.top={node='above',side=0};storages.side={node='beside',side=4}
          local requests={{item={name='mod:input'},count=2,to={storage='top',slots={1}}},
            {item={name='mod:fuel'},count=3,to={storage='side',slots={2}}}}
          local ids=assert(wh.fetchMany(requests));assert(#ids==1)
          requests[1].to.slots[1]=99
          deliver(ids[1]);local s=jobs[ids[1]]
          assert(s.trips==1 and s.perItem[1].requestIndex==1 and s.perItem[2].requestIndex==2)
          assert(LANDINGS['above:0'][1]=='mod:input' and LANDINGS['above:0'][2]==nil)
          assert(LANDINGS['beside:4'][2]=='mod:fuel' and LANDINGS['beside:4'][1]==nil)
        ''')

    def test_same_face_distinct_role_slots_and_same_item_request_indices(self):
        self.lua.execute('''
          observe('stock',{stack('mod:input',2),stack('mod:fuel',3)})
          local ids=assert(wh.fetchMany({{item={name='mod:input'},count=2,to={storage='buffer',slots={7}}},
            {item={name='mod:fuel'},count=3,to={storage='buffer',slots={9}}}},'buffer'))
          assert(#ids==1);deliver(ids[1])
          assert(LANDINGS['buffer:0'][7]=='mod:input' and LANDINGS['buffer:0'][9]=='mod:fuel')
          assert(LANDINGS['buffer:0'][1]==nil and jobs[ids[1]].trips==1)
          observe('stock',{stack('mod:same',2)})
          FLEET={{cargoSlots=1}}
          ids=assert(wh.fetchMany({{item={name='mod:same'},count=1,to={storage='buffer',slots={3}}},
            {item={name='mod:same'},count=1,to={storage='buffer',slots={5}}}}))
          assert(#ids==1 and #jobs[ids[1]].opts.expectedItems==2)
          deliver(ids[1]);local rows=jobs[ids[1]].perItem
          assert(rows[1].requestIndex==1 and rows[2].requestIndex==2 and rows[1].moved==1 and rows[2].moved==1)
          assert(LANDINGS['buffer:0'][3]=='mod:same' and LANDINGS['buffer:0'][5]=='mod:same')
        ''')

    def test_all_effective_destinations_validated_before_submission(self):
        self.lua.execute('''
          observe('stock',{stack('mod:a',2),stack('mod:b',3)});local before=#jobs
          for _,bad in ipairs({false,'absent',{storage='buffer',slots={1,1}},
            {storage='buffer',slots={[1]=1,[3]=2}}}) do
            local ids=wh.fetchMany({{item={name='mod:a'},count=2,to='buffer'},
              {item={name='mod:b'},count=3,to=bad}})
            assert(ids==nil and #jobs==before and #wh.inflight()==0)
          end
          local ids=assert(wh.fetchMany({{item={name='mod:a'},count=2},
            {item={name='mod:unknown'},count=3}},'buffer'))
          assert(#ids==1 and #jobs[ids[1]].opts.expectedItems==2)
          deliver(ids[1]);local missing
          for _,r in ipairs(jobs[ids[1]].perItem) do if r.requestIndex==2 then missing=r end end
          assert(missing.shortfall==3 and jobs[ids[1]].state=='partial')
        ''')

    def test_packed_metadata_survives_real_router_normalization(self):
        fixture = test_stock_api.LibraryApiTests()
        fixture.setUp()
        fixture.load_logistics()
        lua = fixture.lua
        lua.execute('''
          local serialization=require('serialization');local serialize=serialization.serialize
          serialization.serialize=function(t,...)
            if type(t)=='table' and type(t[1])=='string' and type(t[2])=='number' then
              local key=t[1]..'/'..t[2]..'/'..tostring(t[3]);serial[key]=clone(t);return key
            end
            return serialize(t,...)
          end
          local map=require('map');local storages={stock={node='stock',side=0},buffer={node='buffer',side=0},
            top={node='top',side=0},side={node='side',side=4}}
          map.storage=function(s) return storages[s] end
          map.storages=function() return storages end
          map.place=function(s) return storages[s] and storages[s].node or s end
          map.node=function(s) return {x=s=='stock' and 0 or 10,y=0,z=0,
            faces={[0]=true,[4]=true}} end
          package.loaded.logistics=lg
          lg.drones=function() return {{cargoSlots=4}} end
          lg.plan=function() return {{x=0,y=0,z=0},{x=1,y=0,z=0}} end
          package.preload.computer=function() return {uptime=function() return 0 end} end
          package.loaded.event={push=function() end,listen=function(_,fn) listener=fn end}
          os.rename=function() return true end
        ''')
        fixture.load('warehouse', 'wh')
        lua.execute('''
          wh.add('stock')
          local status=lg.status
          -- A real full read must populate the ordinary catalogue first.
          local full=lg.job({{read='stock'}})
          lg.status=function(id)
            if id==full then return {state='done',steps={{read={node='stock',side=0},size=2,
              listing={{name='mod:input',size=2,maxSize=16},{name='mod:fuel',size=3,maxSize=64}}}}} end
            return status(id)
          end
          listener('logistics',full)
          local ids,err=wh.fetchMany({{item={name='mod:input'},count=2,to={storage='top',slots={1}}},
            {item={name='mod:fuel'},count=3,to={storage='side',slots={2}}}})
          assert(ids,err);assert(#ids==1 and not wh.settled(ids[1]))
          local s=lg.status(ids[1]);assert(s.state=='queued' and #s.perItem==2)
          assert(s.perItem[1].requestIndex==1 and s.perItem[2].requestIndex==2)
          assert(s.steps[1].maxSize==16 and s.steps[2].maxSize==64)
          assert(s.steps[3].put.node=='top' and s.steps[3].put.side==0 and s.steps[3].put.slots[1]==1)
          assert(s.steps[4].put.node=='side' and s.steps[4].put.side==4 and s.steps[4].put.slots[1]==2)
        ''')


if __name__ == '__main__':
    unittest.main()
