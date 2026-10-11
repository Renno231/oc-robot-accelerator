"""Graph scheduler tests with asynchronous transfers, catalogue and hardware.

The clock advances to the next service timer/event. No execution threads or
coroutines are provided by this hardware fake.
"""
from test_support import LuaCase


class MesGraphTests(LuaCase):
    def setUp(self):
        super().setUp()
        for name in ('inventory', 'craft_plans', 'craftingv4_4', 'mes_state', 'mes_service', 'mes'):
            self.module(name, 'lib/' + name + '.lua')
        self.lua.execute(r'''
            TIME=0; EVENTS={}; JOBS={}; NEXT=0; ACTIONS={};TIMERS={};LISTENERS={}
            package.preload.stations=function() return {} end
            package.preload.stats=function() return {} end
            package.preload.iochest=function() return {} end
            package.preload.mes_alerts=function() return {start=function() end} end
            package.preload.mes_config=function() return {installRobots=function() end,
                config=function(opts) return opts and opts.config or CFG end} end
            MOVES={}; SCANS={}; CLIENTS={}; MAX_CLIENTS=0; ACTIVE_CLIENTS=0
            OUTCOMES={}; DB={}; INSTALLS=0; CONSUME_DELAY=3; OUTPUT_DELAY=8
            GROUPS={cpu1={type='crafter',roles={buffer='buf1'}},
                    cpu2={type='crafter',roles={buffer='buf2'}},
                    kiln={type='furnace',roles={input='in1',output='out1'}},
                    alloy={type='alloy',roles={a='aa',b='ab',output='ao'}}}
            MEMBERS={stock={},buf1={},buf2={},in1={},out1={},aa={},ab={},ao={}}
            CONTENTS={}; RESERVED={}; CAPACITY={}; MAXSTACK={}; FUEL_INPUTS={}; FUEL_BURNED={}
            CFG={crafters={cpu1={robot='robot1'},cpu2={robot='robot2'}},machineTypes={
                furnace={inputs={'input'},output='output',batch=2,seconds=4,blocking=false,
                    roles={'input','output'},roleSlots={input={1},output={1,2,3,4}}},
                alloy={inputs={'a','b'},output='output',batch=2,seconds=4,blocking=true,
                    roles={'a','b','output'},roleSlots={a={1},b={1},output={1,2,3,4}}}}}
            MACHINE_RECIPES={kiln={},alloy={}}
            function put(s,id,n)
                assert(n>=0,'negative physical inventory '..s..' '..id)
                CONTENTS[s]=CONTENTS[s] or {}
                CONTENTS[s][id]=n
            end
            function held(s,id) return (CONTENTS[s] or {})[id] or 0 end
            function listing(s)
                local out={items={},slots=CAPACITY[s] or 4,freeSlots=CAPACITY[s] or 4}
                for id,n in pairs(CONTENTS[s] or {}) do if n>0 then
                    local name,damage=id:match('^(.*):(%d+)$')
                    local maximum=MAXSTACK[id] or 64
                    local stacks=math.ceil(n/maximum)
                    out.freeSlots=out.freeSlots-stacks
                    out.items[id]={item={name=name or id,damage=tonumber(damage) or 0},count=n,
                        maxSize=maximum,room=stacks*maximum-n,stacks=stacks}
                end end
                return out
            end
            local function push(...)
                EVENTS[#EVENTS+1]={...};local f=LISTENERS[select(1,...)];if f then f(...) end
            end
            local ev={push=push,listen=function(name,f) LISTENERS[name]=f;return true end,
                timer=function(n,f) TIMERS[#TIMERS+1]={period=n,due=TIME+n,fn=f};return #TIMERS end}
            package.preload.event=function() return ev end
            package.preload.computer=function() return {uptime=function() return TIME end} end
            function at(when,fn) ACTIONS[#ACTIONS+1]={when=when,fn=fn} end
            ev.pull=function(n)
                    assert(not require('mes_service').guarded(),'blocking pull inside MES pump')
                    PULLS=(PULLS or 0)+1;assert(PULLS<20000,'service deadlock at '..TIME)
                    local earliest=math.huge
                    for _,t in ipairs(TIMERS) do earliest=math.min(earliest,t.due) end
                    for _,a in ipairs(ACTIONS) do earliest=math.min(earliest,a.when) end
                    for _,j in pairs(JOBS) do
                        if not j.terminal then earliest=math.min(earliest,j.finish) end
                        if not j.settled then earliest=math.min(earliest,j.settle) end
                    end
                    assert(earliest<math.huge,'no scheduler wakeup');TIME=math.max(TIME,earliest)
                    for i=#ACTIONS,1,-1 do local a=ACTIONS[i];if a.when<=TIME then table.remove(ACTIONS,i);a.fn() end end
                    for id,j in pairs(JOBS) do
                        if not j.terminal and j.finish<=TIME then j.terminal=true;j.state=j.outcome or 'done';push('logistics','job',id,j.state) end
                        if not j.settled and j.settle<=TIME then j.settled=true;if j.apply then j.apply() end;push('warehouse','settled',id) end
                    end
                    for _,t in ipairs(TIMERS) do if t.due<=TIME then t.due=TIME+t.period;t.fn() end end
            end
            package.preload.thread=function() error('MES must not import thread') end
            function job(apply,outcome)
                NEXT=NEXT+1;JOBS[NEXT]={state='active',finish=TIME+0.1,settle=TIME+0.3,
                    apply=apply,outcome=outcome,moved=1,trips=1};return NEXT
            end
            function process(storage)
                for name,g in pairs(GROUPS) do if g.type~='crafter' then
                    for _,recipe in ipairs(MACHINE_RECIPES[name] or {}) do
                        local ops=math.huge
                        for role,inputs in pairs(recipe.inputs) do
                            local s=g.roles[role];RESERVED[s]=RESERVED[s] or {}
                            for id,n in pairs(inputs) do ops=math.min(ops,math.floor((held(s,id)-(RESERVED[s][id] or 0))/n)) end
                        end
                        if ops>0 and ops<math.huge then
                            local mt=CFG.machineTypes[g.type]
                            if mt and mt.fuel then
                                local inputs=0
                                for _,items in pairs(recipe.inputs) do for _,n in pairs(items) do inputs=inputs+ops*n end end
                                local total=(FUEL_INPUTS[name] or 0)+inputs
                                local needed=math.ceil(total/mt.fuel.per)
                                local additional=needed-(FUEL_BURNED[name] or 0)
                                local storage=g.roles[mt.fuel.role]
                                assert(held(storage,mt.fuel.item)>=additional,'physical machine lacks fuel')
                                put(storage,mt.fuel.item,held(storage,mt.fuel.item)-additional)
                                FUEL_INPUTS[name]=total;FUEL_BURNED[name]=needed
                            end
                            for role,inputs in pairs(recipe.inputs) do for id,n in pairs(inputs) do
                                local s=g.roles[role];RESERVED[s][id]=(RESERVED[s][id] or 0)+ops*n
                            end end
                            at(TIME+(recipe.consumeDelay or CONSUME_DELAY),function()
                                for role,inputs in pairs(recipe.inputs) do for id,n in pairs(inputs) do
                                    local s=g.roles[role];put(s,id,held(s,id)-ops*n);RESERVED[s][id]=RESERVED[s][id]-ops*n
                                end end
                            end)
                            at(TIME+(recipe.outputDelay or OUTPUT_DELAY),function()
                                local output=g.roles.output
                                for id,n in pairs(recipe.outputs) do put(output,id,held(output,id)+ops*n) end
                            end)
                        end
                    end
                end end
            end
            package.preload.logistics=function() return {status=function(id) return JOBS[id] end} end
            package.preload.warehouse=function() return {
                members=function() return MEMBERS end,
                groups=function(kind) local out={};for n,g in pairs(GROUPS) do if not kind or kind==g.type then out[n]=g end end;return out end,
                -- Fake machines use up their own inputs.
                consumed=function() end,observed=function(s,counts) local id=require('item_identity').stackName;for _,v in pairs((listing(s) or {}).items or {}) do put(s,id(v.item),0) end;for _,c in ipairs(counts) do put(s,id(c.item),c.count) end end,count=function(i) return held('stock',require('item_identity').stackName(i)) end,available=function(i) return held('stock',require('item_identity').stackName(i)) end,
                contents=listing,stackSize=function(i) return MAXSTACK[require('item_identity').stackName(i)] or 64 end,
                settled=function(id) return JOBS[id].settled==true end,
                scan=function(s) SCANS[#SCANS+1]={storage=s,time=TIME};return {job()} end,
                fetch=function(i,n,s)
                    s=type(s)=='table' and s.storage or s
                    local id=require('item_identity').stackName(i)
                    if FAIL_STORAGE==s then return nil,'injected fetch failure' end
                    STOCK_OUT=STOCK_OUT or {};assert(held('stock',id)-(STOCK_OUT[id] or 0)>=n,'fetch before settled stock '..id)
                    -- A storage with a set CAPACITY refuses what doesn't fit; the
                    -- drone brings the rest back to stock.
                    local accept=n
                    if CAPACITY[s] then
                        local maximum=MAXSTACK[id] or 64;local used=0
                        for other,c in pairs(CONTENTS[s] or {}) do if other~=id then used=used+math.ceil(c/(MAXSTACK[other] or 64)) end end
                        accept=math.max(0,math.min(n,(CAPACITY[s]-used)*maximum-held(s,id)))
                    end
                    -- Stock leaves the catalogue when the job settles, as in the warehouse.
                    STOCK_OUT[id]=(STOCK_OUT[id] or 0)+accept;put(s,id,held(s,id)+accept)
                    MOVES[#MOVES+1]={kind='fetch',storage=s,item=id,count=accept,time=TIME,refused=n-accept}
                    process(s)
                    local settle=function() STOCK_OUT[id]=STOCK_OUT[id]-accept;put('stock',id,held('stock',id)-accept) end
                    if accept==n then return job(settle) end
                    local j=job(settle,accept>0 and 'partial' or 'failed')
                    JOBS[j].accepted=accept;JOBS[j].refused=n-accept;JOBS[j].held={};JOBS[j].reason='destination refused items'
                    return j
                end,
                store=function(i,n,s)
                    s=type(s)=='table' and s.storage or s
                    -- A drone takes what is there; a short take is reported, not assumed.
                    local id=require('item_identity').stackName(i);local take=math.min(n,held(s,id))
                    put(s,id,held(s,id)-take)
                    local j=job(function() put('stock',id,held('stock',id)+take) end,take<n and (take>0 and 'partial' or 'failed') or nil)
                    if take<n then JOBS[j].accepted=take;JOBS[j].short=true end
                    MOVES[#MOVES+1]={kind='store',storage=s,item=id,count=take,time=TIME,job=j}
                    return j
                end
            } end
            local wh=require('warehouse')
            -- Physical packing fake: four cargo stacks per job, including
            -- split requests and distinct destination faces/slot scopes.
            -- Call the public single-item methods so existing failure hooks
            -- remain effective, then pack compatible transfer receipts.
            local function many(requests,endpoint,storing)
                local ids={};local current;local used=0
                for index,r in ipairs(requests) do
                    local destination=r.to or endpoint
                    local name=require('item_identity').stackName(r.item)
                    local left=r.count
                    local maximum=MAXSTACK[name] or 64
                    while left>0 do
                        local n=math.min(left,maximum)
                        local firstMove=#MOVES+1
                        local id,err
                        if storing then id,err=wh.store(r.item,n,endpoint)
                        else id,err=wh.fetch(r.item,n,destination) end
                        if not id then return nil,err,ids end
                        local j=JOBS[id]
                        local compatible=current and used<4 and
                            current.finish==j.finish and current.settle==j.settle and
                            current.outcome==j.outcome and current.reason==j.reason
                        if not compatible then
                            current=j;current.perItem={};current.applies={};current.moved=0
                            current.id=id;ids[#ids+1]=id;used=0
                        else JOBS[id]=nil end
                        local apply=j.apply
                        if apply then current.applies[#current.applies+1]=apply end
                        local target=current
                        current.apply=function() for _,fn in ipairs(target.applies) do fn() end end
                        local moved=j.outcome and (j.accepted or 0) or n
                        if j.refused then current.refused=(current.refused or 0)+j.refused;current.held={} end
                        if j.short then current.steps={{short=true}};current.held={} end
                        current.perItem[#current.perItem+1]={item=r.item,requestIndex=index,
                            requested=n,moved=moved,shortfall=n-moved,taken=n,returned=n-moved,overflow=0}
                        current.moved=current.moved+moved
                        for k=firstMove,#MOVES do
                            MOVES[k].job=current.id;MOVES[k].requestIndex=index
                            MOVES[k].slots=type(destination)=='table' and destination.slots or nil
                        end
                        used=used+1;left=left-n
                    end
                end
                return ids
            end
            wh.fetchMany=function(requests,to) return many(requests,to,false) end
            wh.collect=function(from,requests) return many(requests,from,true) end
            package.preload.recipes=function() return {getAll=function(id) return DB[id] end} end
            package.preload.oredict=function() return {get=function() end,getByItemName=function() end} end
            package.preload.craft_tools=function() return {list=function() return {} end} end
            package.preload.serialization=function() return {} end
            package.preload.filesystem=function() return {} end
            package.preload.map=function() MAIN_REQUIRES_DONE=true;return {} end
            PREPARED={}
            local sink
            package.preload.craft_client=function() return {
              install=function(cb)
                INSTALLS=INSTALLS+1;sink=cb;local rows={}
                for _,c in pairs(CFG.crafters) do PREPARED[c.robot]=true;rows[#rows+1]={address=c.robot,connected=true};cb(nil,'robot_transport',{address=c.robot,state='ready'}) end
                return rows
              end,
              tick=function() end,
              inspect=function(token,address)
                PREPARED[address]=true
                local unknown=false
                for _,call in ipairs(CLIENTS) do if call.robot==address and (not call.finish or call.outcome=='unknown') then unknown=true end end
                local data={address=address,unknown=unknown or nil};if not unknown then data.busy=false end
                sink(token,'robot_status',data);return true
              end,
              status=function(address)
                assert(PREPARED[address])
                for _,call in ipairs(CLIENTS) do
                  if call.robot==address and (not call.finish or call.outcome=='unknown') then return nil end
                end
                return {busy=false}
              end,
              begin=function(token,address,p,jobId,o)
                o=o or {};o.serverAddress=address;o.existingOnly=true
                assert(PREPARED[o.serverAddress] and o.existingOnly==true and MAIN_REQUIRES_DONE)
                local buffer=o.serverAddress=='robot1' and 'buf1' or 'buf2'
                local record={robot=o.serverAddress,start=TIME,plan=p};CLIENTS[#CLIENTS+1]=record
                ACTIVE_CLIENTS=ACTIVE_CLIENTS+1;MAX_CLIENTS=math.max(MAX_CLIENTS,ACTIVE_CLIENTS)
                sink(token,'robot_admitted',{address=address,jobId=jobId,disposition='accepted'})
                sink(token,'robot_progress',{address=address,jobId=jobId,receipt={message='WORKING: '..p.tasks[1].item}})
                at(TIME,function() require('mes_service').pump();record.live=M.status();record.resources=M.resources{config=CFG} end)
                at(TIME+2,function()
                ACTIVE_CLIENTS=ACTIVE_CLIENTS-1;record.finish=TIME
                local outcome=OUTCOMES[o.serverAddress] or 'complete'
                record.outcome=outcome
                if outcome=='complete' then for _,t in ipairs(p.tasks) do
                    for slot,id in pairs(t.recipe) do if not (t.tool_slots or {})[slot] and id~='minecraft:air' then
                        put(buffer,id,held(buffer,id)-t.qty_produced/t.recipeOutput)
                    elseif (t.tool_slots or {})[slot] then
                        local family=t.tool_slots[slot];local exact
                        for candidate,n in pairs(CONTENTS[buffer] or {}) do
                            if n>0 and require('craft_tool_rules').family(candidate)==family then exact=candidate;break end
                        end
                        assert(exact,'missing physical tool')
                        local damage=tonumber(exact:match(':(%d+)$')) or 0
                        local profile=p.tools[family]
                        damage=damage+t.qty_produced/t.recipeOutput*profile.durabilityPerUse
                        put(buffer,exact,held(buffer,exact)-1)
                        if damage<profile.durability then local worn=family..':'..math.floor(damage);put(buffer,worn,held(buffer,worn)+1) end
                    end end
                    put(buffer,t.item,held(buffer,t.item)+t.qty_produced)
                end end
                local counts=nil
                if outcome=='complete' then counts={};for id,n in pairs(CONTENTS[buffer] or {}) do if n>0 then counts[id]=n end end end
                sink(token,'robot_terminal',{address=address,jobId=jobId,status=outcome,receipt={status=outcome,message='injected robot '..outcome,buffer=counts},at=TIME})
                end)
                return true
            end} end
            M=require('mes')
            function task(id,inputs,node,refs,kind,n)
                return {item=id,qty_produced=n or 1,recipeOutput=1,recipe=inputs,node=node,input_nodes=refs,
                    machineType=kind,isProcessing=kind and true or nil}
            end
            function run(tasks,opts)
                opts=opts or {};opts.config=CFG
                local id,err=M.run({tasks=tasks,requestItem=tasks[#tasks].item,requestQuantity=tasks[#tasks].qty_produced},opts)
                assert(id,err);return M.wait(id),id
            end
        ''')

    def test_packed_four_robot_inputs_one_physical_job_and_multiitem_buffer_store(self):
        self.assertEqual(self.lua.execute('''
            for _,id in ipairs({'t:a','t:b','t:c','t:d'}) do put('stock',id,1) end
            -- An unrelated stack appearing after crafting is also drained.
            at(1,function() put('buf1','t:extra',1) end)
            local r=run({task('t:final',{'t:a','t:b','t:c','t:d'})},{crafter='cpu1'})
            assert(r.status=='complete',r.reason)
            local s=r.stages[1];local fetches,stores=0,0
            for _,p in ipairs(s.physicalJobs) do
                if p.kind=='fetch' then fetches=fetches+1;assert(#p.perItem==4)
                else stores=stores+1;assert(#p.perItem==2) end
            end
            local jobs={};for _,m in ipairs(s.itemsMoved) do
                assert(m.status=='complete' and m.moved==1 and #m.allocations==1)
                jobs[m.job]=true
            end
            assert(s.assigned<=s.craftStarted and s.released>=s.craftFinished)
            return fetches,stores,#s.itemsMoved,held('stock','t:extra'),held('buf1','t:extra')
        '''), (1, 1, 6, 1, 0))

    def test_packed_machine_multiitem_output_one_store_job(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:ore',1)
            DB['t:metal']={{'t:ore',qty=1,isProcessing=true,machineType='furnace',byproducts={{item='t:slag',qty=1}}}}
            MACHINE_RECIPES.kiln={{inputs={input={['t:ore']=1}},outputs={['t:metal']=1,['t:slag']=1}}}
            local r=M.wait(assert(M.run(assert(M.plan('t:metal',1,{config=CFG})),{config=CFG})))
            assert(r.status=='complete',r.reason)
            local stores=0;local job
            for _,p in ipairs(r.stages[1].physicalJobs) do if p.kind=='collect' and (p.moved or 0)>0 then
                stores=stores+1;job=p.job;assert(#p.perItem==2 and p.trips==1)
            end end
            for _,a in ipairs(r.stages[1].loadLedger[1].storeJobs) do assert(a.job==job and a.count==1) end
            local trips=0;for _,j in pairs(JOBS) do trips=trips+j.trips end
            return stores,r.trips==trips,held('stock','t:slag'),held('stock','t:metal')
        '''), (1, True, 1, 1))

    def test_packed_machine_split_store_keeps_every_physical_link(self):
        self.assertEqual(self.lua.execute('''
            MAXSTACK['t:metal']=1;CFG.machineTypes.furnace.batch=5
            CFG.machineTypes.furnace.roleSlots.output={1,2,3,4,5};CAPACITY.out1=8
            put('stock','t:ore',5)
            MACHINE_RECIPES.kiln={{inputs={input={['t:ore']=1}},outputs={['t:metal']=1}}}
            local r=run({task('t:metal',{'t:ore'},'metal',{'ore'},'furnace',5)})
            assert(r.status=='complete',r.reason)
            local s=r.stages[1];local physical={};local linked={};local total=0
            for _,p in ipairs(s.physicalJobs) do if p.kind=='collect' then physical[p.job]=true end end
            for _,a in ipairs(s.loadLedger[1].storeJobs) do
                assert(physical[a.job] and a.count==a.moved and a.requested==a.moved and a.shortfall==0)
                linked[a.job]=true;total=total+a.moved
            end
            local count=0;for id in pairs(physical) do assert(linked[id]);count=count+1 end
            return count,total,#s.storeAllocations
        '''), (2, 5, 5))

    def test_packed_machine_partial_store_links_actual_not_requested(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:ore',2);CFG.machineTypes.furnace.batch=2
            MACHINE_RECIPES.kiln={{inputs={input={['t:ore']=1}},outputs={['t:metal']=1}}}
            local wh=require('warehouse');local original=wh.collect
            wh.collect=function(...)
                local ids=original(...);local j=JOBS[ids[1]]
                j.outcome='partial';j.reason='injected packed shortfall'
                j.perItem[1].moved=1;j.perItem[1].shortfall=1;j.perItem[1].returned=1
                return ids
            end
            local r=run({task('t:metal',{'t:ore'},'metal',{'ore'},'furnace',2)})
            local s=r.stages[1];local a=s.loadLedger[1].storeJobs[1];local b=s.storeAllocations[1]
            return r.status,a.requested,a.count,a.moved,a.shortfall,b.requested,b.count,b.shortfall
        '''), ('failed', 2, 1, 1, 1, 2, 1, 1))

    def _packed_furnace_faces(self, same_face):
        self.lua.globals().SAME_FACE = same_face
        return self.lua.execute('''
            GROUPS.kiln.roles.fuel=SAME_FACE and 'in1' or 'fuel1';MEMBERS.fuel1={}
            local mt=CFG.machineTypes.furnace
            mt.fuel={role='fuel',item='t:fuel',per=8};mt.roles={'input','fuel','output'}
            mt.roleSlots.fuel={SAME_FACE and 2 or 1}
            put('stock','t:ore',1);put('stock','t:fuel',1)
            MACHINE_RECIPES.kiln={{inputs={input={['t:ore']=1}},outputs={['t:metal']=1}}}
            local r=run({task('t:metal',{'t:ore'},'metal',{'ore'},'furnace')})
            assert(r.status=='complete',r.reason)
            local fetches={};for _,m in ipairs(MOVES) do if m.kind=='fetch' then fetches[#fetches+1]=m end end
            assert(#fetches==2 and fetches[1].job==fetches[2].job)
            local indices={}
            for _,m in ipairs(fetches) do
                indices[m.item]=m.requestIndex
                assert(#m.slots==1)
                if m.item=='t:ore' then assert(m.storage=='in1' and m.slots[1]==1)
                else assert(m.storage==GROUPS.kiln.roles.fuel and m.slots[1]==mt.roleSlots.fuel[1]) end
            end
            assert(indices['t:ore']~=indices['t:fuel'])
            local physical=r.stages[1].physicalJobs[1];assert(#physical.perItem==2)
            for _,m in ipairs(r.stages[1].itemsMoved) do if m.kind=='fetch' then
                assert(#m.allocations==1 and m.allocations[1].job==physical.job and m.moved==1)
            end end
            return physical.trips,held('stock','t:metal')
        ''')

    def test_packed_furnace_input_top_and_fuel_side_one_job(self):
        self.assertEqual(self._packed_furnace_faces(False), (1, 1))

    def test_packed_same_face_distinct_role_slots_and_request_indices(self):
        self.assertEqual(self._packed_furnace_faces(True), (1, 1))

    def test_packed_partial_item_receipt_keeps_other_item_complete(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:a',2);put('stock','t:b',2)
            local wh=require('warehouse');local original=wh.fetchMany
            wh.fetchMany=function(...)
                local ids=original(...);local j=JOBS[ids[1]]
                j.outcome='partial';j.reason='one packed item short'
                j.perItem[1].moved=1;j.perItem[1].shortfall=1;j.perItem[1].returned=1
                return ids
            end
            local r=run({task('t:final',{'t:a','t:b'},nil,nil,nil,2)})
            assert(r.status=='failed' and #CLIENTS==0)
            local a,b=r.stages[1].itemsMoved[1],r.stages[1].itemsMoved[2]
            assert(a.item=='t:a' and a.moved==1 and a.shortfall==1 and a.returned==1)
            assert(b.item=='t:b' and b.moved==2 and b.shortfall==0)
            assert(a.job==b.job and #r.stages[1].physicalJobs==1)
            assert(JOBS[a.job].settled and r.finished>=JOBS[a.job].settle)
            return a.status,b.status,b.shortfall
        '''), ('partial', 'complete', 0))

    def test_packed_partial_submission_drains_every_returned_job(self):
        self.assertEqual(self.lua.execute('''
            MAXSTACK['t:a']=1;put('stock','t:a',5);put('stock','t:b',5)
            local wh=require('warehouse');local original=wh.fetchMany
            wh.fetchMany=function(...)
                local ids=original(...);LATE=ids[#ids]
                JOBS[LATE].finish=TIME+7;JOBS[LATE].settle=TIME+7.2
                return nil,'submission stopped after packed jobs',ids
            end
            local r=run({task('t:final',{'t:a','t:b'},nil,nil,nil,5)})
            assert(r.status=='failed' and #CLIENTS==0 and r.reason:find('submission stopped'))
            for _,p in ipairs(r.stages[1].physicalJobs) do assert(JOBS[p.job].settled) end
            assert(r.finished>=JOBS[LATE].settle)
            local a,b=r.stages[1].itemsMoved[1],r.stages[1].itemsMoved[2]
            return #r.stages[1].physicalJobs,a.moved,b.moved,#a.allocations
        '''), (2, 5, 5, 5))

    def test_diamond_branches_overlap_and_join_after_catalogue_settlement(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',2)
            local tasks={task('t:left',{'t:raw'},'left',{[1]='raw'}),
                task('t:right',{'t:raw'},'right',{[1]='raw'}),
                task('t:final',{'t:left','t:right'},'final',{'left','right'})}
            local id=assert(M.run({tasks=tasks},{config=CFG}))
            assert(type(id)=='number' and #CLIENTS==0 and INSTALLS==1 and #TIMERS==1)
            local initial=M.status(id);assert(initial.status=='running' and #initial.stages==3)
            initial.stages[1].after[1]=99;assert(#M.status(id).stages[1].after==0)
            local r=M.wait(id)
            assert(r.status=='complete',r.reason)
            assert(r.stages[1].craftStarted<r.stages[2].craftFinished)
            assert(r.stages[2].craftStarted<r.stages[1].craftFinished)
            assert(r.stages[3].after[1]==1 and r.stages[3].after[2]==2)
            for _,v in ipairs(MOVES) do if v.kind=='store' and (v.item=='t:left' or v.item=='t:right') then
                assert(r.stages[3].started>=JOBS[v.job].settle)
            end end
            local history=M.runs();history[1].status='changed';assert(M.runs()[1].status=='complete')
            for _,e in ipairs(EVENTS) do if e[1]=='mes' and e[2]=='stage' then
                assert(e[3]==id and type(e[4])=='number' and type(e[5])=='string')
            end end
            local e=EVENTS[#EVENTS];assert(e[1]=='mes' and e[2]=='done' and e[3]==id and e[4]=='complete')
            return MAX_CLIENTS,held('stock','t:final'),r.stages[3].done,r.trips>0
        '''), (2, 1, 1, True))

    def test_robot_and_machine_overlap_and_progress_copies(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',1);put('stock','t:ore',1)
            MACHINE_RECIPES.kiln={{inputs={input={['t:ore']=1}},outputs={['t:metal']=1}}}
            local r=run({task('t:part',{'t:raw'},'part',{'raw'}),
                task('t:metal',{'t:ore'},'metal',{'ore'},'furnace'),
                task('t:final',{'t:part','t:metal'},'final',{'part','metal'})})
            assert(r.status=='complete',r.reason)
            local s=r.stages
            assert(s[1].started<s[2].finished and s[2].started<s[1].finished)
            local live=CLIENTS[1].live;local resource=CLIENTS[1].resources
            assert(live.stages[1].detail:find('WORKING') and #live.active==2)
            assert(resource.crafters.cpu1.state=='busy' and resource.crafters.cpu1.run==r.id)
            resource.crafters.cpu1.state='modified'
            assert(M.resources{config=CFG}.crafters.cpu1.state=='idle')
            local beforeDue=0
            for _,m in ipairs(MOVES) do if m.kind=='store' and m.storage=='out1' and m.time<s[2].loadLedger[1].delivered+4.5 then beforeDue=beforeDue+1 end end
            return held('stock','t:final'),beforeDue,M.status(999)==nil
        '''), (1, 1, True))

    def test_blocking_same_recipe_topup_and_different_recipe_input_gate(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:copper',2);put('stock','t:tin',2);put('stock','t:iron',1);put('stock','t:coal',1)
            MACHINE_RECIPES.alloy={
                {inputs={a={['t:copper']=1},b={['t:tin']=1}},outputs={['t:bronze']=1}},
                {inputs={a={['t:iron']=1},b={['t:coal']=1}},outputs={['t:steel']=1}}}
            local r=run({task('t:bronze',{'t:copper','t:tin'},'bronze',{'copper','tin'},'alloy',2),
                task('t:steel',{'t:iron','t:coal'},'steel',{'iron','coal'},'alloy')})
            assert(r.status=='complete',r.reason)
            local bronze=r.stages[1].loadLedger;local steel=r.stages[2].loadLedger[1]
            assert(#bronze==2 and bronze[2].delivered<bronze[1].collected) -- same recipe tops up
            assert(steel.delivered>=bronze[2].collected) -- another recipe waits until the machine is emptied
            local loads=M.resources{config=CFG}.machines.alloy.loads
            return held('stock','t:bronze'),held('stock','t:steel'),#loads
        '''), (2, 1, 0))

    def _sand_added_by_hand(self, slots):
        # Someone puts sand in the furnace before the load arrives.
        self.lua.globals().SLOTS = slots
        return self.lua.execute('''
            CFG.machineTypes.furnace.batch=4;CAPACITY.in1=SLOTS;MAXSTACK['t:ore']=2
            put('stock','t:ore',4)
            MACHINE_RECIPES.kiln={{inputs={input={['t:ore']=1}},outputs={['t:metal']=1}}}
            local wh=require('warehouse');local original=wh.fetchMany;local once=true
            wh.fetchMany=function(...) if once then once=false;put('in1','t:sand',1) end;return original(...) end
            local r=run({task('t:metal',{'t:ore'},'a',{'ore'},'furnace',4)})
            local refused=0;for _,m in ipairs(MOVES) do if m.kind=='fetch' then refused=refused+(m.refused or 0) end end
            local loads={};for _,l in ipairs(r.stages[1].loadLedger or {}) do loads[#loads+1]=l.items end
            return r.status,r.reason,refused,table.concat(loads,','),held('stock','t:metal'),held('stock','t:ore')
        ''')

    def test_partly_refused_load_counts_what_went_in_and_retries_the_rest(self):
        self.assertEqual(self._sand_added_by_hand(2), ('complete', None, 2, '2,2', 4, 0))

    def test_load_refused_with_nothing_to_collect_fails_at_the_input_deadline(self):
        self.assertEqual(self._sand_added_by_hand(1),
            ('failed', 'kiln: Machine input deadline exceeded', 4, '', 0, 4))

    def test_nonblocking_refused_load_returns_to_stock_and_retries_after_collection(self):
        self.assertEqual(self.lua.execute('''
            CFG.machineTypes.furnace.batch=2;CAPACITY.in1=1;MAXSTACK['t:ore']=2
            put('stock','t:ore',4)
            MACHINE_RECIPES.kiln={{inputs={input={['t:ore']=1}},outputs={['t:metal']=1}}}
            local r=run({task('t:metal',{'t:ore'},'a',{'ore'},'furnace',2),
                task('t:metal',{'t:ore'},'b',{'ore'},'furnace',2)})
            assert(r.status=='complete',r.reason)
            local a=r.stages[1].loadLedger[1];local b=r.stages[2].loadLedger[1]
            -- The slot was full: the second load came back, then went in after collection.
            local refused=0;for _,m in ipairs(MOVES) do if m.kind=='fetch' then refused=refused+(m.refused or 0) end end
            assert(b.delivered>=a.collected)
            assert(a.collectedItems['t:metal']==2 and b.collectedItems['t:metal']==2)
            return refused,#r.stages[2].loadLedger,held('stock','t:metal'),held('stock','t:ore')
        '''), (2, 1, 4, 0))

    def test_mid_graph_failure_settles_active_sibling_and_never_dispatches_join(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',2);OUTCOMES.robot1='failed'
            local r,id=run({task('t:left',{'t:raw'},'left',{'raw'}),
                task('t:right',{'t:raw'},'right',{'raw'}),
                task('t:final',{'t:left','t:right'},'final',{'left','right'})})
            assert(r.status=='failed' and r.reason=='injected robot failed')
            assert(r.stages[1].state=='failed' and r.stages[2].state=='done' and r.stages[3].state=='waiting')
            assert(r.where[1].item=='t:raw' and r.where[1].count==1 and r.where[1].storage=='buf1')
            for _,j in pairs(JOBS) do assert(j.settled) end
            local resources=M.resources{config=CFG}
            assert(resources.crafters.cpu1.state=='idle' and resources.crafters.cpu1.run==nil)
            assert(resources.crafters.cpu2.state=='idle' and resources.crafters.cpu2.step==nil)
            r.where[1].count=999;assert(M.status(id).where[1].count==1)
            local e=EVENTS[#EVENTS]
            return #CLIENTS,held('stock','t:right'),e[3],e[4]
        '''), (2, 1, 1, 'failed'))

    def test_unknown_robot_stays_unavailable_until_confirmed_idle(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',3);OUTCOMES.robot1='unknown'
            local r=run({task('t:left',{'t:raw'})},{crafter='cpu1'})
            assert(r.status=='unknown' and M.resources{config=CFG}.crafters.cpu1.state=='unknown')
            local second=run({task('t:left',{'t:raw'})},{crafter='cpu1'})
            assert(second.status=='failed' and #CLIENTS==1)
            -- The robot answers idle again and the buffer was recovered.
            put('buf1','t:raw',0);OUTCOMES.robot1='complete'
            for _,c in ipairs(CLIENTS) do c.finish=c.finish or TIME;c.outcome='complete' end
            local third=run({task('t:left',{'t:raw'})},{crafter='cpu1'})
            return third.status,#CLIENTS,M.resources{config=CFG}.crafters.cpu1.state
        '''), ('complete', 2, 'idle'))

    def test_processing_byproducts_are_expected_and_settled(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:ore',2)
            DB['t:metal']={{'t:ore',qty=1,isProcessing=true,machineType='furnace',byproducts={{item='t:slag',qty=2}}}}
            MACHINE_RECIPES.kiln={{inputs={input={['t:ore']=1}},outputs={['t:metal']=1,['t:slag']=2}}}
            local p=assert(M.plan('t:metal',2,{config=CFG}))
            assert(#p.stages[1].outputs==2 and p.stages[1].outputs[2].qty==4)
            local r=M.wait(assert(M.run(p,{config=CFG})))
            assert(r.status=='complete',r.reason)
            local ledger=r.stages[1].loadLedger[1]
            assert(ledger.collectedItems['t:metal']==2 and ledger.collectedItems['t:slag']==4 and ledger.collected)
            return r.stages[1].total,held('stock','t:slag'),held('out1','t:slag')
        '''), (6, 4, 0))

    def test_plan_shortfall_fuel_split_rounding_and_ancestor_have(self):
        self.assertEqual(self.lua.execute('''
            GROUPS.kiln2={type='furnace',roles={input='in2',output='out2',fuel='fuel2'}}
            GROUPS.kiln.roles.fuel='fuel1';MEMBERS.in2={};MEMBERS.out2={};MEMBERS.fuel1={};MEMBERS.fuel2={}
            CFG.machineTypes.furnace.fuel={role='fuel',item='t:fuel',per=8}
            CFG.machineTypes.furnace.roles={'input','output','fuel'};CFG.machineTypes.furnace.roleSlots.fuel={1}
            DB['t:part']={{'t:raw'}}
            DB['t:metal']={{'t:part',qty=1,isProcessing=true,machineType='furnace'}}
            DB['t:final']={{'t:metal'}}
            put('stock','t:raw',2);put('stock','t:fuel',1)
            local p=assert(M.plan('t:final',2,{config=CFG}))
            assert(#p.stages==3 and p.stages[2].fuel.need==2 and p.stages[2].loads==2)
            assert(p.stages[2].inputs[1].have==2 and p.stages[3].inputs[1].have==2)
            assert(p.missing[1].item=='t:fuel' and p.missing[1].need==2 and p.missing[1].have==1)
            local id,err=M.run(p,{config=CFG});assert(id==nil and err:find('Missing inputs'))
            return p.craftable,#MOVES,#CLIENTS
        '''), (False, 0, 0))

    def test_public_configuration_copy_and_idle_discovery_confirmation(self):
        self.assertEqual(self.lua.execute('''
            CFG.crafters.cpu1.buffer='configured-buffer'
            local c=M.crafters{config=CFG};assert(c.cpu1.buffer=='configured-buffer' and c.cpu1.status==nil)
            c.cpu1.robot='changed';assert(M.crafters{config=CFG}.cpu1.robot=='robot1')
            assert(M.resources{config=CFG}.crafters.cpu1.buffer=='buf1')
            put('stock','t:raw',2);OUTCOMES.robot1='unknown'
            run({task('t:left',{'t:raw'})},{crafter='cpu1'})
            package.loaded.mes_config=nil
            package.preload.mes_config=function() return {installRobots=function() end,robots=function() return DISCOVERED end} end
            DISCOVERED={{address='robot1',busy=true}}
            M.robots(0,{config=CFG});assert(M.resources{config=CFG}.crafters.cpu1.state=='unknown')
            DISCOVERED={{address='robot1',busy=false}}
            local discovered=M.robots(0,{config=CFG});discovered[1].busy=true
            assert(M.resources{config=CFG}.crafters.cpu1.state=='idle')
            local status=M.status(999);local result,problem=M.wait(999)
            return status==nil,result==nil,problem,M.runs()[1].status
        '''), (True, True, 'Unknown run', 'unknown'))

    def test_callbacks_cannot_abort_movement_and_foreground_pull_errors_are_not_run_failures(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',1)
            local r=run({task('t:left',{'t:raw'})},{onStage=function() error('observer only') end,
                client={onMessage=function() error('progress observer only') end}})
            assert(r.status=='complete' and r.callbackError:find('observer only'))
            assert(M.resources{config=CFG}.crafters.cpu1.state=='idle')
            local ev=require('event');local pull=ev.pull
            ev.pull=function() error('foreground watcher exits') end
            put('stock','t:raw',1)
            local id=assert(M.run({tasks={task('t:left',{'t:raw'})}},{config=CFG}))
            local good,err=pcall(M.wait,id)
            assert(not good and err:find('foreground watcher exits') and M.status(id).status=='running')
            ev.pull=pull
            while M.status(id).status=='running' do ev.pull() end
            return held('stock','t:left'),M.status(id).status,INSTALLS,#TIMERS
        '''), (2, 'complete', 1, 1))

    def test_collection_at_output_due_then_exponential_backoff(self):
        self.assertEqual(self.lua.execute('''
            OUTPUT_DELAY=18;CFG.machineTypes.furnace.seconds=1
            put('stock','t:ore',1)
            MACHINE_RECIPES.kiln={{inputs={input={['t:ore']=1}},outputs={['t:metal']=1}}}
            local r=run({task('t:metal',{'t:ore'},'metal',{'ore'},'furnace')})
            assert(r.status=='complete',r.reason)
            -- Each collection attempt takes what is there; early ones find nothing.
            local scans={};for _,m in ipairs(MOVES) do if m.kind=='store' and m.storage=='out1' then scans[#scans+1]=m.time end end
            assert(#scans<=8 and scans[2]>=r.stages[1].loadLedger[1].delivered+1)
            local first=scans[3]-scans[2];local last=scans[#scans]-scans[#scans-1]
            return #scans<10,last>first,held('stock','t:metal')
        '''), (True, True, 1))

    def test_fifo_batch_store_settlement_attributes_two_live_loads(self):
        self.assertEqual(self.lua.execute('''
            OUTPUT_DELAY=1;CONSUME_DELAY=0.2;CFG.machineTypes.furnace.batch=1
            put('stock','t:ore',2)
            MACHINE_RECIPES.kiln={{inputs={input={['t:ore']=1}},outputs={['t:metal']=1}}}
            at(1.6,function()
                LIVE_RESOURCE=M.resources{config=CFG}.machines.kiln
                assert(LIVE_RESOURCE.state=='busy' and #LIVE_RESOURCE.loads==2)
                LIVE_RESOURCE.loads[1].recipe='mutated'
                assert(M.resources{config=CFG}.machines.kiln.loads[1].recipe~='mutated')
            end)
            local r=run({task('t:metal',{'t:ore'},'a',{'ore'},'furnace'),
                task('t:metal',{'t:ore'},'b',{'ore'},'furnace')})
            assert(r.status=='complete',r.reason)
            local stores=0;for _,m in ipairs(MOVES) do if m.kind=='store' and m.item=='t:metal' then stores=stores+1;assert(m.count==2) end end
            local a=r.stages[1].loadLedger[1];local b=r.stages[2].loadLedger[1]
            assert(a.collected==b.collected and a.storeJobs[1].job==b.storeJobs[1].job)
            assert(a.collected>=JOBS[a.storeJobs[1].job].settle)
            assert(a.collectedItems['t:metal']==1 and b.collectedItems['t:metal']==1)
            return stores,held('stock','t:metal'),b.inputBefore==nil
        '''), (1, 2, True))

    def test_shared_buffer_cannot_be_double_dispatched(self):
        self.assertEqual(self.lua.execute('''
            GROUPS.cpu2.roles.buffer='buf1'
            put('stock','t:raw',2)
            -- Force both stations onto one chest; scheduler must serialize them,
            -- even though each robot resource individually appears idle.
            local r=run({task('t:left',{'t:raw'},'left',{'raw'}),
                task('t:right',{'t:raw'},'right',{'raw'})})
            assert(r.status=='complete',r.reason)
            return MAX_CLIENTS,#r.stages,held('stock','t:left'),held('stock','t:right')
        '''), (1, 2, 1, 1))

    def test_distinct_physical_tools_allow_concurrent_branches_with_exact_wear(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',2);put('stock','t:tool:7',2)
            local a=task('t:left',{'t:tool','t:raw'},'a',{'tool','raw'});a.tool_slots={[1]='t:tool'}
            local b=task('t:right',{'t:tool','t:raw'},'b',{'tool','raw'});b.tool_slots={[1]='t:tool'}
            local p={tasks={a,b},tools={['t:tool']={durability=20,durabilityPerUse=1}},tool_stock={['t:tool']={1,1}}}
            local r=M.wait(assert(M.run(p,{config=CFG})))
            assert(r.status=='complete',r.reason)
            return MAX_CLIENTS,held('stock','t:tool:8'),held('stock','t:left'),held('stock','t:right')
        '''), (2, 2, 1, 1))

    def test_one_physical_tool_serializes_without_shortfall_or_double_withdrawal(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',2);put('stock','t:tool:7',1)
            local a=task('t:left',{'t:tool','t:raw'},'a',{'tool','raw'});a.tool_slots={[1]='t:tool'}
            local b=task('t:right',{'t:tool','t:raw'},'b',{'tool','raw'});b.tool_slots={[1]='t:tool'}
            local p={tasks={a,b},tools={['t:tool']={durability=20,durabilityPerUse=1}},tool_stock={['t:tool']={1}}}
            local r=M.wait(assert(M.run(p,{config=CFG})))
            assert(r.status=='complete',r.reason)
            return MAX_CLIENTS,held('stock','t:tool:9'),held('stock','t:left'),held('stock','t:right')
        '''), (1, 1, 1, 1))

    def test_ingredients_that_cannot_share_one_slot_are_refused_and_reported(self):
        self.assertEqual(self.lua.execute('''
            CFG.machineTypes.alloy.inputs={'a'};CFG.machineTypes.alloy.roles={'a','output'}
            CFG.machineTypes.alloy.roleSlots={a={1},output={1,2,3,4}}
            GROUPS.alloy.roles.b=nil
            CAPACITY.aa=1;put('stock','t:copper',1);put('stock','t:tin',1)
            local r=run({task('t:bronze',{'t:copper','t:tin'},'bronze',{'copper','tin'},'alloy')})
            assert(r.status=='failed' and r.reason:find('input deadline'))
            -- The one slot takes copper and refuses tin; the failure reports where the copper is.
            local where={};for _,w in ipairs(r.where or {}) do where[#where+1]=w.storage..':'..w.item..'='..w.count end
            return held('aa','t:copper'),held('stock','t:tin'),table.concat(where,',')
        '''), (1, 1, 'aa:t:copper=1'))

    def _two_group_store_receipts(self, partial):
        self.lua.globals().PARTIAL_STORE = partial
        return self.lua.execute('''
            GROUPS.kiln2={type='furnace',roles={input='in2',output='out2'}}
            MEMBERS.in2={};MEMBERS.out2={};OUTPUT_DELAY=1
            MACHINE_RECIPES.kiln={{inputs={input={['t:ore']=1}},outputs={['t:metal']=1}}}
            MACHINE_RECIPES.kiln2=MACHINE_RECIPES.kiln
            put('stock','t:ore',4)
            local wh=require('warehouse');local store=wh.store
            wh.store=function(i,n,endpoint,...)
                local storage=type(endpoint)=='table' and endpoint.storage or endpoint
                local id=store(i,n,endpoint,...)
                if storage=='out1' then
                    -- The first collector's wait must yield while the other
                    -- group appends its store to the SAME stage movement list.
                    JOBS[id].finish=TIME+0.4;JOBS[id].settle=TIME+0.7
                elseif storage=='out2' and PARTIAL_STORE then
                    JOBS[id].outcome='partial';JOBS[id].reason='injected partial output store'
                end
                return id
            end
            local r=run({task('t:metal',{'t:ore'},'metal',{'ore'},'furnace',4)})
            local records={};local stores={}
            for _,v in ipairs(r.stages[1].loadLedger) do records[v.group]=v end
            for _,v in ipairs(r.stages[1].itemsMoved) do if v.kind=='collect' then stores[v.storage]=v end end
            local a=records.kiln.storeJobs[1];local b=records.kiln2.storeJobs[1]
            assert(a.job~=b.job and a.job==stores.out1.job and b.job==stores.out2.job)
            assert(a.storage=='out1' and b.storage=='out2')
            assert(a.status=='complete' and a.status==stores.out1.status)
            assert(b.status==(PARTIAL_STORE and 'partial' or 'complete') and b.status==stores.out2.status)
            assert(records.kiln.collected>=JOBS[a.job].settle)
            if PARTIAL_STORE then
                assert(r.status=='failed' and records.kiln2.state=='failed' and records.kiln2.collected==nil)
                assert(r.reason:find('injected partial output store'))
            else
                assert(r.status=='complete' and records.kiln2.collected>=JOBS[b.job].settle)
            end
            local trips=0;for _,j in pairs(JOBS) do assert(j.settled);trips=trips+j.trips end
            return r.status,r.trips==trips,#r.stages[1].storeAllocations
        ''')

    def test_same_stage_concurrent_group_stores_keep_exact_complete_receipts(self):
        self.assertEqual(self._two_group_store_receipts(False), ('complete', True, 2))

    def test_same_stage_concurrent_group_stores_keep_exact_partial_receipts(self):
        self.assertEqual(self._two_group_store_receipts(True), ('failed', True, 2))

    def test_timed_out_load_keeps_machine_out_until_its_output_is_explained(self):
        self.assertEqual(self.lua.execute('''
            CFG.machineTypes.furnace.seconds=0;OUTPUT_DELAY=200
            put('stock','t:ore',2)
            MACHINE_RECIPES.kiln={{inputs={input={['t:ore']=1}},outputs={['t:metal']=1}}}
            local first=run({task('t:metal',{'t:ore'},'a',{'ore'},'furnace')})
            local resource=M.resources{config=CFG}.machines.kiln
            assert(first.status=='failed' and resource.state=='unknown' and #SCANS==1)
            -- The metal is still inside: the next run reads again, loads nothing and says why.
            CFG.machineTypes.furnace.seconds=150;OUTPUT_DELAY=500
            local second=run({task('t:metal',{'t:ore'},'b',{'ore'},'furnace')})
            local fetches=0;for _,m in ipairs(MOVES) do if m.kind=='fetch' then fetches=fetches+1 end end
            assert(second.status=='failed' and fetches==1 and #SCANS==2 and held('stock','t:metal')==0)
            -- Once the late metal is out, a read explains it: it goes to stock and the machine is back.
            while TIME<300 do require('event').pull(1) end;OUTPUT_DELAY=100
            local third=run({task('t:metal',{'t:ore'},'c',{'ore'},'furnace')})
            return third.status,#SCANS,held('stock','t:metal'),held('stock','t:ore'),M.resources{config=CFG}.machines.kiln.state,second.reason
        '''), ('complete', 3, 2, 0, 'idle', 'kiln: May still hold work: 1 t:metal'))

    def test_robot_address_aliases_are_locked_and_unknown_propagates(self):
        self.assertEqual(self.lua.execute('''
            CFG.crafters.cpu2.robot='robot1'
            put('stock','t:raw',2)
            local r=run({task('t:left',{'t:raw'},'a',{'raw'}),task('t:right',{'t:raw'},'b',{'raw'})})
            assert(r.status=='complete' and MAX_CLIENTS==1 and #CLIENTS==2)
            put('stock','t:raw',2);OUTCOMES.robot1='unknown'
            local failed=run({task('t:left',{'t:raw'})},{crafter='cpu1'})
            local before=#CLIENTS
            local blocked=run({task('t:right',{'t:raw'})},{crafter='cpu2'})
            assert(failed.status=='unknown' and blocked.status=='failed' and #CLIENTS==before)
            local resource=M.resources{config=CFG}
            assert(resource.crafters.cpu1.state=='unknown' and resource.crafters.cpu2.state=='unknown')
            package.loaded.mes_config=nil
            package.preload.mes_config=function() return {installRobots=function() end,robots=function() return {{address='robot1',busy=false}} end} end
            M.robots(0,{config=CFG})
            return M.resources{config=CFG}.crafters.cpu1.state,M.resources{config=CFG}.crafters.cpu2.state
        '''), ('idle', 'idle'))

    def test_physical_buffer_inventory_aliases_are_serialized(self):
        self.assertEqual(self.lua.execute('''
            MEMBERS.buf1.inventory='same-chest';MEMBERS.buf2.inventory='same-chest'
            CONTENTS.buf1={};CONTENTS.buf2=CONTENTS.buf1
            put('stock','t:raw',2)
            local r=run({task('t:left',{'t:raw'},'a',{'raw'}),task('t:right',{'t:raw'},'b',{'raw'})})
            assert(r.status=='complete',r.reason)
            return MAX_CLIENTS,held('stock','t:left'),held('stock','t:right')
        '''), (1, 1, 1))

    def test_one_group_choice_does_not_escape_admission_boundary(self):
        self.assertEqual(self.lua.execute('''
            GROUPS.alloy2={type='alloy',roles={a='a2',b='b2',output='o2'}}
            MEMBERS.a2={};MEMBERS.b2={};MEMBERS.o2={}
            put('stock','t:copper',1);put('stock','t:tin',1)
            MACHINE_RECIPES.alloy2={{inputs={a={['t:copper']=1},b={['t:tin']=1}},outputs={['t:bronze']=1}}}
            local r=run({task('t:bronze',{'t:copper','t:tin'},'bronze',{'copper','tin'},'alloy')},
                {machines={alloy='alloy'}})
            for _,m in ipairs(MOVES) do assert(m.storage~='a2' and m.storage~='b2' and m.storage~='o2') end
            return r.status,held('stock','t:bronze')
        '''), ('failed', 0))

    def test_busy_recipe_group_does_not_pin_another_ready_step(self):
        self.assertEqual(self.lua.execute('''
            GROUPS.alloy2={type='alloy',roles={a='a2',b='b2',output='o2'}}
            MEMBERS.a2={};MEMBERS.b2={};MEMBERS.o2={}
            local recipes={
                {inputs={a={['t:copper']=1},b={['t:tin']=1}},outputs={['t:bronze']=1}},
                {inputs={a={['t:iron']=1},b={['t:coal']=1}},outputs={['t:steel']=1}}}
            MACHINE_RECIPES.alloy=recipes;MACHINE_RECIPES.alloy2=recipes
            put('stock','t:copper',1);put('stock','t:tin',1);put('stock','t:iron',1);put('stock','t:coal',1)
            local r=run({task('t:bronze',{'t:copper','t:tin'},'bronze',{'copper','tin'},'alloy'),
                task('t:steel',{'t:iron','t:coal'},'steel',{'iron','coal'},'alloy')})
            assert(r.status=='complete',r.reason)
            local first=r.stages[1].loadLedger[1];local second=r.stages[2].loadLedger[1]
            assert(first.group~=second.group and second.delivered<first.collected)
            return held('stock','t:bronze'),held('stock','t:steel')
        '''), (1, 1))

    def test_fuel_plan_uses_what_the_mes_delivered(self):
        self.assertEqual(self.lua.execute('''
            GROUPS.kiln.roles.fuel='fuel1';MEMBERS.fuel1={}
            local mt=CFG.machineTypes.furnace;mt.batch=4;mt.fuel={role='fuel',item='t:fuel',per=8}
            mt.roles={'input','fuel','output'};mt.roleSlots.fuel={1}
            -- Fuel the MES did not deliver is not credited.
            put('fuel1','t:fuel',5);put('stock','t:ore',30);put('stock','t:fuel',4)
            DB['t:metal']={{'t:ore',qty=1,isProcessing=true,machineType='furnace'}}
            local before=assert(M.plan('t:metal',1,{config=CFG})).stages[1].fuel.need
            MACHINE_RECIPES.kiln={{inputs={input={['t:ore']=1}},outputs={['t:metal']=1}}}
            local r=run({task('t:metal',{'t:ore'},'metal',{'ore'},'furnace',12)})
            assert(r.status=='complete',r.reason)
            -- 2 fuel delivered for 12 inputs covers 4 more; 8 more needs one.
            local four=assert(M.plan('t:metal',4,{config=CFG})).stages[1].fuel.need
            local eight=assert(M.plan('t:metal',8,{config=CFG})).stages[1].fuel.need
            return before,four,eight
        '''), (1, 0, 1))

    def test_load_redistribution_does_not_overspend_planned_fuel(self):
        self.assertEqual(self.lua.execute('''
            GROUPS.kiln.roles.fuel='fuel1';GROUPS.kiln2={type='furnace',roles={input='in2',output='out2',fuel='fuel2'}}
            MEMBERS.in2={};MEMBERS.out2={};MEMBERS.fuel1={};MEMBERS.fuel2={}
            local mt=CFG.machineTypes.furnace;mt.batch=4;mt.fuel={role='fuel',item='t:fuel',per=8}
            mt.roles={'input','fuel','output'};mt.roleSlots.fuel={1};MAXSTACK['t:ore']=4
            MACHINE_RECIPES.kiln={{inputs={input={['t:ore']=1}},outputs={['t:metal']=1},consumeDelay=20,outputDelay=25}}
            MACHINE_RECIPES.kiln2={{inputs={input={['t:ore']=1}},outputs={['t:metal']=1}}}
            put('stock','t:ore',16);put('stock','t:fuel',2)
            local r=run({task('t:metal',{'t:ore'},'metal',{'ore'},'furnace',16)})
            assert(r.status=='complete',r.reason)
            local fuel=0;local loads={}
            for _,m in ipairs(MOVES) do if m.kind=='fetch' and m.item=='t:fuel' then fuel=fuel+m.count end end
            for _,load in ipairs(r.stages[1].loadLedger) do loads[load.group]=(loads[load.group] or 0)+load.items end
            return fuel,loads.kiln,loads.kiln2,held('stock','t:metal')
        '''), (2, 8, 8, 16))

    def test_robot_inputs_enqueued_fairly_before_any_fetch_wait(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:a',1);put('stock','t:b',1);put('stock','t:c',1);put('stock','t:d',1)
            local r=run({task('t:left',{'t:a','t:b'},'left',{'a','b'}),
                task('t:right',{'t:c','t:d'},'right',{'c','d'})})
            assert(r.status=='complete',r.reason)
            local fetches={};for _,m in ipairs(MOVES) do if m.kind=='fetch' then fetches[#fetches+1]=m end end
            assert(#fetches==4 and fetches[1].storage~=fetches[3].storage)
            assert(fetches[1].job==fetches[2].job and fetches[3].job==fetches[4].job)
            assert(fetches[1].time==fetches[2].time and fetches[2].time==fetches[3].time and fetches[3].time==fetches[4].time)
            return MAX_CLIENTS,held('stock','t:left'),held('stock','t:right')
        '''), (2, 1, 1))

    def test_bulk_input_failure_settles_all_already_submitted_fetches(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:a',1);put('stock','t:b',1)
            local wh=require('warehouse');local fetch=wh.fetch
            wh.fetch=function(i,n,s,...)
                local id=fetch(i,n,s,...)
                if i.name=='t:a' then JOBS[id].outcome='partial';JOBS[id].reason='first bulk input partial'
                else JOBS[id].finish=TIME+5;JOBS[id].settle=TIME+5.2;LATE_FETCH=id end
                return id
            end
            local r=run({task('t:left',{'t:a','t:b'})})
            assert(r.status=='failed' and #CLIENTS==0 and #MOVES==2)
            assert(r.finished>=JOBS[LATE_FETCH].settle and JOBS[LATE_FETCH].settled)
            return r.stages[1].itemsMoved[1].status,r.stages[1].itemsMoved[2].status,r.reason
        '''), ('partial', 'complete', 'first bulk input partial'))

    def test_fuel_already_in_a_machine_is_not_counted(self):
        self.assertEqual(self.lua.execute('''
            GROUPS.kiln.roles.fuel='fuel1';MEMBERS.fuel1={}
            local mt=CFG.machineTypes.furnace;mt.batch=4;mt.fuel={role='fuel',item='t:fuel',per=8}
            mt.roles={'input','fuel','output'};mt.roleSlots.fuel={1}
            put('fuel1','t:fuel',2);put('stock','t:ore',12);put('stock','t:fuel',2)
            MACHINE_RECIPES.kiln={{inputs={input={['t:ore']=1}},outputs={['t:metal']=1}}}
            local r=run({task('t:metal',{'t:ore'},'metal',{'ore'},'furnace',12)})
            assert(r.status=='complete' and r.stages[1].fuel.need==2,r.reason)
            local fuel=0;for _,m in ipairs(MOVES) do if m.kind=='fetch' and m.item=='t:fuel' then fuel=fuel+m.count end end
            return fuel,held('stock','t:fuel'),held('fuel1','t:fuel'),held('stock','t:metal')
        '''), (2, 0, 2, 12))

    def test_fuel_added_outside_the_mes_is_not_counted(self):
        self.assertEqual(self.lua.execute('''
            GROUPS.kiln.roles.fuel='fuel1';MEMBERS.fuel1={}
            local mt=CFG.machineTypes.furnace;mt.batch=4;mt.fuel={role='fuel',item='t:fuel',per=8}
            mt.roles={'input','fuel','output'};mt.roleSlots.fuel={1};MAXSTACK['t:ore']=4
            put('stock','t:ore',12);put('stock','t:fuel',2)
            MACHINE_RECIPES.kiln={{inputs={input={['t:ore']=1}},outputs={['t:metal']=1}}}
            at(4,function() put('fuel1','t:fuel',held('fuel1','t:fuel')+1) end)
            local r=run({task('t:metal',{'t:ore'},'metal',{'ore'},'furnace',12)})
            assert(r.status=='complete',r.reason)
            local fuel=0;for _,m in ipairs(MOVES) do if m.kind=='fetch' and m.item=='t:fuel' then fuel=fuel+m.count end end
            return fuel,held('stock','t:fuel'),held('stock','t:metal')
        '''), (2, 0, 12))

    def test_bulk_wait_preserves_first_known_failure_while_other_jobs_settle(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:a',1);put('stock','t:b',1)
            local wh=require('warehouse');local fetch=wh.fetch
            wh.fetch=function(i,n,s,...)
                local id=fetch(i,n,s,...)
                if i.name=='t:a' then JOBS[id].outcome='partial';JOBS[id].reason='later a failure';JOBS[id].finish=TIME+5;JOBS[id].settle=TIME+5.2
                else JOBS[id].outcome='partial';JOBS[id].reason='first b failure' end
                return id
            end
            local r=run({task('t:left',{'t:a','t:b'})})
            for _,j in pairs(JOBS) do assert(j.settled) end
            return r.status,r.reason,#CLIENTS
        '''), ('failed', 'first b failure', 0))

    def test_unknown_buffer_owner_blocks_other_robot_alias_until_owner_idle(self):
        self.assertEqual(self.lua.execute('''
            MEMBERS.buf1.inventory='same-chest';MEMBERS.buf2.inventory='same-chest'
            CONTENTS.buf1={};CONTENTS.buf2=CONTENTS.buf1
            local original=require('craft_client').begin
            require('craft_client').begin=function(token,address,p,jobId,o)
                if address=='robot1' then
                    CLIENTS[#CLIENTS+1]={robot='robot1',start=TIME}
                    put('buf1','t:raw',0) -- empty does NOT prove the robot stopped
                    at(TIME+50,function() put('buf1','t:left',1) end)
                    require('mes_service').enqueue(nil,'robot_terminal',{token=token,address=address,jobId=jobId,status='unknown',reason='robot connection lost while crafting'})
                    return true
                end
                return original(token,address,p,jobId,o)
            end
            put('stock','t:raw',3)
            local first=run({task('t:left',{'t:raw'})},{crafter='cpu1'})
            assert(first.status=='unknown' and held('buf1','t:raw')==0)
            local resource=M.resources{config=CFG}
            assert(resource.crafters.cpu1.state=='unknown' and resource.crafters.cpu2.state=='unknown')
            assert(resource.crafters.cpu2.bufferOwner=='robot1')
            local second=run({task('t:right',{'t:raw'})},{crafter='cpu2'})
            assert(second.status=='failed' and #CLIENTS==1 and #ACTIONS==1)
            package.loaded.mes_config=nil
            package.preload.mes_config=function() return {installRobots=function() end,robots=function() return DISCOVERED end} end
            DISCOVERED={{address='robot2',busy=false}}
            M.robots(0,{config=CFG})
            assert(M.resources{config=CFG}.crafters.cpu2.state=='unknown')
            local third=run({task('t:right',{'t:raw'})},{crafter='cpu2',isCrafterIdle=function() return true end})
            assert(third.status=='failed' and #CLIENTS==1) -- wrong owner hook also cannot clear it
            -- The old operation physically completes, then its OWN robot is
            -- confirmed idle. Discovery does not pretend its output was stored.
            local ev=require('event');while #ACTIONS>0 do ev.pull(0.2) end
            DISCOVERED={{address='robot1',busy=false}}
            M.robots(0,{config=CFG})
            assert(M.resources{config=CFG}.crafters.cpu2.state=='idle')
            -- The leftover is not looked for; the robot's report after its next craft
            -- lists everything in the buffer and all of it goes back to stock.
            local fourth=run({task('t:right',{'t:raw'})},{crafter='cpu2'})
            assert(fourth.status=='complete',fourth.reason)
            return held('buf2','t:left'),held('stock','t:left'),held('stock','t:right'),held('stock','t:raw')
        '''), (0, 1, 1, 1))

    def test_failure_prevents_new_load_but_settles_old_load(self):
        self.assertEqual(self.lua.execute('''
            local mt=CFG.machineTypes.furnace;mt.batch=1;mt.blocking=true
            put('stock','t:ore',3);put('stock','t:raw',1);OUTCOMES.robot1='failed'
            MACHINE_RECIPES.kiln={{inputs={input={['t:ore']=1}},outputs={['t:metal']=1}}}
            local r=run({task('t:metal',{'t:ore'},'metal',{'ore'},'furnace',3),
                task('t:robot',{'t:raw'},'robot',{'raw'})},{crafter='cpu1'})
            assert(r.status=='failed' and r.reason=='injected robot failed')
            for _,l in ipairs(r.stages[1].loadLedger) do assert(l.state=='done') end
            local failureAt=r.stages[2].craftFinished
            for _,m in ipairs(MOVES) do if m.kind=='fetch' then assert(m.time<failureAt,'new input delivery after failure') end end
            local loads=#r.stages[1].loadLedger
            assert(held('stock','t:metal')==loads and held('stock','t:ore')==3-loads)
            local resource=M.resources{config=CFG}.machines.kiln
            return resource.state,#resource.loads
        '''), ('idle', 0))

