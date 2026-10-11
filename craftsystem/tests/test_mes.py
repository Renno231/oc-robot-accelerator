from test_support import LuaCase


class MesTests(LuaCase):
    def setUp(self):
        super().setUp()
        self.module('inventory', 'lib/inventory.lua')
        self.module('craftingv4_4', 'lib/craftingv4_4.lua')
        self.module('mes_state', 'lib/mes_state.lua')
        self.module('mes_service', 'lib/mes_service.lua')
        self.lua.execute('''
            DB, STOCK, ORES = {}, {}, {}
            package.preload.stations=function() return {} end
            package.preload.stats=function() return {} end
            package.preload.iochest=function() return {} end
            package.preload.housekeeping=function() return {} end
            package.preload.mes_alerts=function() return {start=function() end} end
            package.preload.recipes=function() return {getAll=function(id) return DB[id] end} end
            package.preload.oredict=function() return {get=function() end,getByItemName=function() end} end
            package.preload.craft_tools=function() return {list=function() return {} end} end
            package.preload.serialization=function() return {} end
            package.preload.filesystem=function() return {} end
            TIME=0; EVENTS={}; JOBS={}; MOVES={}; NEXT=0; FAIL=false; TIMEOUT=false
            package.preload.computer=function() return {uptime=function() return TIME end} end
            LISTENERS={};TIMERS={}
            package.preload.event=function() return {
                listen=function(name,f) LISTENERS[name]=f;return true end,
                timer=function(n,f) TIMERS[#TIMERS+1]=f;return #TIMERS end,
                push=function(...) EVENTS[#EVENTS+1]={...};local f=LISTENERS[select(1,...)];if f then f(...) end end,
                pull=function(n) TIME=TIME+(n or 0.2);for _,f in ipairs(TIMERS) do f() end end
            } end
            GROUPS={cpu1={type='crafter',roles={buffer='buf'}},
                A={type='furnace',roles={input='ai',output='ao',fuel='af'}},
                B={type='furnace',roles={input='bi',output='bo',fuel='bf'}}}
            MEMBERS={stock={},buf={},ai={},ao={},af={},bi={},bo={},bf={}}
            CONTENTS={}
            function put(s,id,n)
                CONTENTS[s]=CONTENTS[s] or {items={},slots=27,freeSlots=27}
                local name,damage=id:match('^(.*):(%d+)$')
                CONTENTS[s].items[id]={item={name=name or id,damage=tonumber(damage) or 0},count=n,maxSize=64,
                    room=n>0 and (64-n%64)%64 or 0}
            end
            function held(s,id) return CONTENTS[s] and CONTENTS[s].items[id] and CONTENTS[s].items[id].count or 0 end
            function job() NEXT=NEXT+1;JOBS[NEXT]={state='queued',moved=1};return NEXT end
            package.preload.logistics=function() return {status=function(id)
                local j=JOBS[id]; if j.state=='queued' then j.state='waiting';return j end
                if j.state=='waiting' then
                    j.state=j.failWhenWait and 'failed' or 'done'
                    if j.failWhenWait then
                        j.reason=j.failWhenWait;j.moved=0
                        for _,r in ipairs(j.perItem or {}) do r.moved=0;r.taken=0;r.shortfall=r.requested;r.reason=j.reason end
                    end
                end; return j
            end} end
            package.preload.warehouse=function() return {
                -- This fixture applies catalogue changes synchronously during
                -- submission; terminal jobs therefore have a settled catalogue.
                -- Delayed-settlement tests override this independent seam.
                settled=function(id) local s=JOBS[id].state;return s=='done' or s=='partial' or s=='failed' end,
                groups=function(kind) local out={};for n,g in pairs(GROUPS) do if not kind or g.type==kind then out[n]=g end end;return out end,
                members=function() return MEMBERS end,
                contents=function(s) return CONTENTS[s] or {items={},slots=27,freeSlots=27} end,
                -- The fake furnace already moves its input to output.
                consumed=function() end,
                -- A robot's read of its buffer replaces what the buffer holds.
                observed=function(s,counts) local id=require('item_identity').stackName;for _,v in pairs((package.loaded.warehouse.contents(s) or {}).items or {}) do put(s,id(v.item),0) end;for _,c in ipairs(counts) do put(s,id(c.item),c.count) end end,
                count=function(i) return held('stock',require('item_identity').stackName(i)) end,
                available=function(i) return held('stock',require('item_identity').stackName(i)) end,
                stackSize=function() return 64 end,
                scan=function(s) return {job()} end,
                fetch=function(item,n,s)
                    s=type(s)=='table' and s.storage or s
                    local id=require('item_identity').stackName(item)
                    if FAIL or held('stock',id)<n then return nil,'shortfall' end
                    put('stock',id,held('stock',id)-n);put(s,id,held(s,id)+n)
                    MOVES[#MOVES+1]={kind='fetch',item=id,n=n,s=s}
                    if (s=='ai' or s=='bi') and not TIMEOUT then
                        local output=s=='ai' and 'ao' or 'bo'
                        put(s,id,0);put(output,'t:processed',held(output,'t:processed')+n)
                        local fuel=s=='ai' and 'af' or 'bf'
                        put(fuel,'t:fuel',math.max(0,held(fuel,'t:fuel')-math.ceil(n/8)))
                    end
                    return job()
                end,
                store=function(item,n,s)
                    s=type(s)=='table' and s.storage or s
                    local id=require('item_identity').stackName(item);local take=math.min(n,held(s,id))
                    put(s,id,held(s,id)-take);put('stock',id,held('stock',id)+take)
                    MOVES[#MOVES+1]={kind='store',item=id,n=take,s=s};local j=job()
                    if take<n then local r=JOBS[j];r.state='partial';r.moved=take;r.taken=take;r.returned=0;r.held={};r.steps={{short=true}} end
                    return j
                end
            } end
            -- Compatibility adapter for this legacy functional fixture. Packed
            -- physical-trip assertions live in the dedicated graph/warehouse tests.
            local wh=require('warehouse')
            local function many(requests,default,store)
                local ids={};local order={}
                for i,r in ipairs(requests) do order[#order+1]={index=i,request=r} end
                if not store then table.sort(order,function(a,b)
                    local x=type(a.request.to)=='table' and a.request.to.storage or a.request.to or default
                    local y=type(b.request.to)=='table' and b.request.to.storage or b.request.to or default
                    return (x=='af' or x=='bf') and not (y=='af' or y=='bf')
                end) end
                for _,entry in ipairs(order) do
                    local r=entry.request;local id,err
                    if store then id,err=wh.store(r.item,r.count,default)
                    else id,err=wh.fetch(r.item,r.count,r.to or default) end
                    if not id then return nil,err,ids end
                    local j=JOBS[id];local terminal=j.state=='partial' or j.state=='failed'
                    local moved=terminal and (j.moved or 0) or r.count
                    j.perItem={{item=r.item,requestIndex=entry.index,requested=r.count,
                        moved=moved,shortfall=r.count-moved,taken=terminal and j.taken or r.count,
                        returned=terminal and j.returned or 0,overflow=0,reason=j.reason}}
                    ids[#ids+1]=id
                end
                return ids
            end
            wh.fetchMany=function(requests,to) return many(requests,to,false) end
            wh.collect=function(from,requests) return many(requests,from,true) end
            CLIENT_STATUS='complete'; CLIENT_CALLS=0
            package.preload.map=function() return {} end
            PREPARED={}
            package.preload.craft_client=function() return {
              prepare=function(address) PREPARED[address]=true end,
              status=function(address)
                assert(PREPARED[address])
                if CLIENT_CALLS>0 and CLIENT_STATUS=='unknown' then return nil end
                return {busy=false}
              end,
              runDetailed=function(p,o)
                assert(PREPARED[o.serverAddress] and o.existingOnly==true)
                CLIENT_CALLS=CLIENT_CALLS+1; PAYLOAD=p; ADDRESS=o.serverAddress
                local valid,err=require('craft_plan').validateFlow(p);assert(valid,err)
                if BUSY_PROBE then BUSY_RESULT,BUSY_ERROR=M.run(p,{config=CFG}) end
                if CLIENT_STATUS=='complete' then
                    for _,t in ipairs(p.tasks) do
                        for slot,id in pairs(t.recipe) do
                            if not (t.tool_slots or {})[slot] then put('buf',id,held('buf',id)-t.qty_produced/t.recipeOutput)
                            else
                                local family=t.tool_slots[slot]
                                for exact,v in pairs(CONTENTS.buf.items) do
                                    if v.count>0 and require('craft_tool_rules').family(exact)==family then
                                        local damage=(v.item.damage or 0)+(t.qty_produced/t.recipeOutput)*p.tools[family].durabilityPerUse
                                        put('buf',exact,v.count-1)
                                        if damage<p.tools[family].durability then
                                            local result=family..(damage>0 and ':'..math.floor(damage) or '')
                                            put('buf',result,held('buf',result)+1)
                                        end
                                        break
                                    end
                                end
                            end
                        end
                        put('buf',t.item,held('buf',t.item)+t.qty_produced)
                    end
                end
                return {status=CLIENT_STATUS,message='robot outcome'}
            end} end
            package.preload.thread=function() error('MES must not import thread') end
            CFG={crafters={cpu1={robot='robot-address'}},machineTypes={furnace={
                inputs={'input'},output='output',fuel={role='fuel',item='t:fuel',per=8},batch=64,seconds=0,blocking=false,
                roles={'input','fuel','output'},roleSlots={input={1},fuel={1},output={1}}}}}
            function task(id,recipe,n,out,kind)
                return {item=id,recipe=recipe,qty_produced=n or 1,recipeOutput=out or 1,
                    machineType=kind,isProcessing=kind and true or nil}
            end
            function awaitRun(plan,opts)
                local id,err=M.run(plan,opts)
                if not id then return {status='failed',error=err,reason=err,stages={}} end
                return M.wait(id)
            end
            function run(tasks,opts) opts=opts or {};opts.config=CFG;return awaitRun({tasks=tasks},opts) end
            local client=require('craft_client');local sink
            client.install=function(cb)
                sink=cb;local rows={}
                for _,c in pairs(CFG.crafters) do PREPARED[c.robot]=true;rows[#rows+1]={address=c.robot,connected=true};cb(nil,'robot_transport',{address=c.robot,state='ready'}) end
                return rows
            end
            client.inspect=function(token,address)
                PREPARED[address]=true
                local r=client.status(address)
                sink(token,'robot_status',{address=address,busy=r and r.busy,unknown=not r or nil});return true
            end
            client.begin=function(token,address,p,jobId,o)
                o=o or {};o.serverAddress=address;o.existingOnly=true
                local r=client.runDetailed(p,o)
                sink(token,'robot_admitted',{address=address,jobId=jobId,disposition='accepted'})
                if r.status=='complete' then
                    r.buffer={};for id,v in pairs((CONTENTS.buf or {}).items or {}) do if v.count>0 then r.buffer[id]=v.count end end
                end
                sink(token,'robot_terminal',{address=address,jobId=jobId,status=r.status,receipt=r});return true
            end
            client.tick=function() end
        ''')
        self.module('craft_plans', 'lib/craft_plans.lua')
        self.module('mes_config', 'lib/mes_config.lua')
        self.module('mes', 'lib/mes.lua')
        self.lua.execute("require('mes_config').installRobots=function() end;M=require('mes')")

    def test_terminal_jobs_wait_for_catalogue_settlement(self):
        self.assertEqual(self.lua.execute('''
            local wh=require('warehouse');local ev=require('event')
            local pull=ev.pull;local settled={};local pulls=0;local delayed=0
            wh.settled=function(id)
                if not settled[id] then delayed=delayed+1 end
                return settled[id]==true
            end
            ev.pull=function(n)
                pulls=pulls+1
                for id,j in pairs(JOBS) do
                    if j.state=='done' then settled[id]=true end
                end
                return pull(n)
            end
            put('stock','t:raw',1)
            local r=run({task('t:result',{'t:raw'})})
            local all=true
            for id in pairs(JOBS) do if not settled[id] then all=false end end
            return r.status,delayed>0,pulls>0,all,held('stock','t:result')
        '''), ('complete', True, True, True, 1))

    def test_failed_jobs_wait_for_catalogue_settlement(self):
        self.assertEqual(self.lua.execute('''
            local wh=require('warehouse');local ev=require('event')
            local pull=ev.pull;local settled={};local failedSettled=false
            local fetch=wh.fetch
            wh.fetch=function(...)
                local id=fetch(...)
                JOBS[id].state='partial';JOBS[id].reason='partial transfer';JOBS[id].moved=0
                return id
            end
            wh.settled=function(id) return settled[id]==true end
            ev.pull=function(n)
                for id,j in pairs(JOBS) do
                    if j.state=='done' or j.state=='partial' then
                        settled[id]=true
                        if j.state=='partial' then failedSettled=true end
                    end
                end
                return pull(n)
            end
            put('stock','t:raw',1)
            local r=run({task('t:result',{'t:raw'})})
            return r.status,failedSettled,CLIENT_CALLS,r.stages[1].itemsMoved[1].status
        '''), ('failed', True, 0, 'partial'))

    def test_plan_stock_only_and_metadata(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw:2',2);put('buf','t:raw:2',50)
            DB['t:final']={{'t:raw:2'}}
            local p=M.plan('t:final:0',2,{config=CFG})
            return p.craftable,p.inventory_needed['t:raw:2'],p.requestItem
        '''), (True, 2, 't:final'))

    def test_plan_shortfall_excludes_group_stock(self):
        self.assertEqual(self.lua.execute('''
            put('buf','t:raw',50);DB['t:final']={{'t:raw'}}
            local p,err=M.plan('t:final',1,{config=CFG})
            return p~=nil,#p.missing,p.missing[1].item,p.missing[1].need,p.missing[1].have
        '''), (True, 1, 't:raw', 1, 0))

    def test_robot_stage_net_inputs_and_surplus(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',2)
            local r=run({task('t:part',{'t:raw'},8,4),task('t:final',{'t:part'},3)})
            return r.status,#r.stages,CLIENT_CALLS,PAYLOAD.inventory_needed['t:raw'],
                PAYLOAD.requestOutputs['t:part'],held('stock','t:part'),held('stock','t:final'),ADDRESS
        '''), ('complete', 1, 1, 2, 5, 5, 3, 'robot-address'))

    def test_robot_machine_robot_stage_barrier(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',1);put('stock','t:fuel',2)
            local r=run({task('t:part',{'t:raw'}),task('t:processed',{'t:part'},1,1,'furnace'),
                task('t:final',{'t:processed'})})
            return r.status,#r.stages,CLIENT_CALLS,held('stock','t:final'),held('buf','t:final')
        '''), ('complete', 3, 2, 1, 0))

    def test_split_parallel_groups_and_fuel(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',64);put('stock','t:fuel',8)
            local r=run({task('t:processed',{'t:raw'},64,1,'furnace')})
            local a,b=0,0
            for _,v in ipairs(MOVES) do if v.kind=='fetch' and v.item=='t:raw' then
                if v.s=='ai' then a=a+v.n else b=b+v.n end
            end end
            return r.status,a,b,held('stock','t:processed'),held('stock','t:fuel'),#r.stages[1].groups
        '''), ('complete', 32, 32, 64, 0, 2))

    def test_specific_group_multiple_loads_existing_fuel(self):
        self.assertEqual(self.lua.execute('''
            -- Fuel already in the machine is not ours to count: the MES delivers all it needs.
            put('stock','t:raw',130);put('stock','t:fuel',17);put('af','t:fuel',1)
            local r=run({task('t:processed',{'t:raw'},130,1,'furnace')},{machines={furnace='A'}})
            local loads=0;for _,v in ipairs(MOVES) do if v.kind=='fetch' and v.item=='t:raw' then
                assert(v.n<=64 and v.s=='ai');loads=loads+1
            end end
            return r.status,loads,held('stock','t:processed'),held('stock','t:fuel'),held('bi','t:raw')
        '''), ('complete', 3, 130, 0, 0))

    def test_shortfall_reports_locations_stops_without_retry(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',0);FAIL=true
            local r=run({task('t:processed',{'t:raw'},1,1,'furnace'),task('t:final',{'t:processed'})},
                {machines={furnace='A'}})
            local located=false;for _,storage in ipairs(r.stages[1].locations) do if storage=='ai' then located=true end end
            local fetches=0;for _,v in ipairs(MOVES) do if v.kind=='fetch' then fetches=fetches+1 end end
            return r.status,#r.stages,CLIENT_CALLS,located,r.error,fetches,r.stages[2].state
        '''), ('failed', 2, 0, True, 'A: Not enough t:raw in stock', 0, 'waiting'))

    def test_unknown_robot_outcome_does_not_store_or_continue(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',1);CLIENT_STATUS='unknown'
            local r=run({task('t:final',{'t:raw'})})
            return r.status,CLIENT_CALLS,held('buf','t:raw'),#MOVES,
                r.where[1].storage=='buf' and r.where[1].item=='t:raw' and r.where[1].count==1
        '''), ('unknown', 1, 1, 1, True))

    def test_failed_done_signal_carries_existing_run_subject(self):
        self.lua.execute('''
            FAIL=true
            local r=awaitRun({requestItem='t:final',tasks={task('t:final',{'t:raw'})}}, {config=CFG})
            assert(r.status=='failed')
            local seen=false;for _,e in ipairs(EVENTS) do if e[1]=='mes' and e[2]=='done' then
                assert(e[3]==r.id and e[4]=='failed' and e[5]=='t:final');seen=true
            end end
            assert(seen)
        ''')

    def test_request_submitted_mid_run_is_accepted_and_completes(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',2);BUSY_PROBE=true
            local r=run({task('t:final',{'t:raw'})});BUSY_PROBE=false
            local second=M.wait(BUSY_RESULT)
            return r.status,type(BUSY_RESULT),BUSY_ERROR,second.status,held('stock','t:final')
        '''), ('complete', 'number', None, 'complete', 2))

    def test_stock_a_run_may_take_excludes_other_runs_claims(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',3)
            local st=require('mes_state');local P={}
            local new,adv,upd=st.new,st.advance,st.update
            st.new=function(id,plan,cfg,opts,world,ports) P[id]=ports
              return {id=id,status='running',claims=id==1 and {['t:raw']=2} or {},inflight=id==1 and {['t:raw']=1} or {},stages={}} end
            st.advance=function() end;st.update=function() end
            local S=require('mes_service');S.start({})
            S.submit({},CFG,{});S.submit({},CFG,{})
            local second,first=P[2].stock('t:raw'),P[1].stock('t:raw')
            st.new,st.advance,st.update=new,adv,upd
            return second,first
        '''), (2, 3))  # one claimed unit is already on a drone: the warehouse withholds it

    def test_machine_timeout_reports_output(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',1);put('stock','t:fuel',1);TIMEOUT=true
            local r=run({task('t:processed',{'t:raw'},1,1,'furnace')},{machines={furnace='A'}})
            -- The furnace never started: its raw goes back to stock and it is back in service.
            return r.status,r.error:find('deadline')~=nil,held('ai','t:raw'),held('stock','t:raw'),M.resources{config=CFG}.machines.A.state
        '''), ('failed', True, 0, 1, 'idle'))

    def test_tool_fields_retained_without_branch_bindings(self):
        self.assertEqual(self.lua.execute('''
            local t=task('t:final',{'t:tool','t:raw'});t.tool_slots={[1]='t:tool'};t.node='out';t.input_nodes={}
            local p=assert(M.robotPlan({tasks={t},tools={['t:tool']={durability=100,durabilityPerUse=1}},
                tool_stock={['t:tool']={10}}},1,1))
            return p.tasks[1].tool_slots[1],p.tool_stock['t:tool'][1],p.tasks[1].node==nil,
                p.inventory_needed['t:raw'],p.inventory_needed['t:tool']==nil
        '''), ('t:tool', 10, True, 1, True))

    def test_machine_blueprint_input_quantity(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',64);put('stock','t:fuel',8)
            local t=task('t:processed',{'t:raw'},64,64,'furnace');t.node='n'
            local r=awaitRun({tasks={t},blueprint={nodes={n={input_quantities={64}}}}},
                {config=CFG,machines={furnace='A'}})
            return r.status,held('stock','t:processed'),held('stock','t:raw')
        '''), ('complete', 64, 0))

    def test_events_and_read_only_status_copy(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',1);run({task('t:final',{'t:raw'})})
            local s=M.status();s.status='changed'
            return EVENTS[1][1],EVENTS[1][2],EVENTS[#EVENTS][2],EVENTS[#EVENTS][4],M.status().status
        '''), ('mes', 'stage', 'done', 'complete', 'complete'))

    def test_processing_plan_is_returned_without_robot_validator(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',64)
            DB['t:processed']={{'t:raw,64',qty=64,isProcessing=true,machineType='furnace'}}
            local p=assert(M.plan('t:processed',64,{config=CFG}))
            return p.tasks[1].isProcessing,p.tasks[1].machineType,p.inventory_needed['t:raw'],
                p.blueprint.nodes[p.tasks[1].node].input_quantities[1]
        '''), (True, 'furnace', 64, 64))

    def test_direct_task_processing_input_quantity(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',64);put('stock','t:fuel',8)
            local t=task('t:processed',{'t:raw'},64,64,'furnace');t.input_quantities={64}
            local r=run({t},{machines={furnace={'A'}}})
            return r.status,held('stock','t:raw'),held('stock','t:processed')
        '''), ('complete', 0, 64))

    def test_saved_processing_path_decoded_without_craft_plans_load(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',1);put('stock','t:fuel',1)
            local saved={tasks={task('t:processed',{'t:raw'},1,1,'furnace')}}
            require('serialization').unserialize=function(text) assert(text=='saved data');return saved end
            local original=io.open
            io.open=function(path) assert(path=='/tmp/process.plan');return {
                read=function() return 'saved data' end,close=function() end} end
            local r=awaitRun('/tmp/process.plan',{config=CFG,machines={furnace='A'}})
            io.open=original
            return r.status,held('stock','t:processed')
        '''), ('complete', 1))

    def test_existing_craftplan_cannot_save_processing_contract(self):
        self.assertEqual(self.lua.execute('''
            local p,err=require('craft_plans').prepare({inventory_needed={['t:raw']=1},
                requestItem='t:processed',requestQuantity=1,
                tasks={task('t:processed',{'t:raw'},1,1,'furnace')}})
            return p==nil,err
        '''), (True, 'Machine processing is not supported by this robot executor.'))

    def test_concurrent_failure_settles_other_worker_and_stops_next_stage(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',128);put('stock','t:fuel',16)
            local wh=require('warehouse');local original=wh.fetch
            wh.fetch=function(i,n,s,o)
                local storage=type(s)=='table' and s.storage or s
                if storage=='ai' then local id=job();JOBS[id].failWhenWait='A input shortfall';return id end
                return original(i,n,s,o)
            end
            local r=run({task('t:processed',{'t:raw'},128,1,'furnace'),task('t:final',{'t:processed'})})
            local settled=true;for _,j in pairs(JOBS) do if j.state~='done' and j.state~='failed' and j.state~='partial' then settled=false end end
            return r.status,#r.stages,CLIENT_CALLS,settled,held('stock','t:processed'),r.stages[2].state
        '''), ('failed', 2, 0, True, 64, 'waiting'))

    def test_partial_ledger_retains_actual_movement(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',3)
            local wh=require('warehouse');local fetch=wh.fetch
            wh.fetch=function(...) local id=fetch(...);JOBS[id]={state='partial',moved=1,taken=2,returned=1,
                held={},reason='late removal'};return id end
            local r=run({task('t:final',{'t:raw'},3)})
            local m=r.stages[1].itemsMoved[1]
            return r.status,m.status,m.moved,m.taken,m.returned,m.reason,CLIENT_CALLS
        '''), ('failed', 'partial', 1, 2, 1, 'late removal', 0))

    def test_per_crafter_occupancy(self):
        self.assertEqual(self.lua.execute('''
            CFG.crafters.cpu2={robot='second-robot'}
            GROUPS.cpu2={type='crafter',roles={buffer='buf'}}
            put('stock','t:raw',1)
            local client=require('craft_client');local original=client.runDetailed
            local first,second
            client.runDetailed=function(...) local c=M.resources{config=CFG}.crafters;first=c.cpu1.state;second=c.cpu2.state;return original(...) end
            local r=run({task('t:final',{'t:raw'})},{crafter='cpu2'})
            return r.status,ADDRESS,first,second,M.resources{config=CFG}.crafters.cpu2.state
        '''), ('complete', 'second-robot', 'busy', 'busy', 'idle'))

    def test_unknown_crafter_not_selected_again_without_idle_confirmation(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',2);CLIENT_STATUS='unknown'
            run({task('t:final',{'t:raw'})})
            local second=run({task('t:final',{'t:raw'})})
            return second.status,second.error:find('No idle resources')~=nil,CLIENT_CALLS,
                M.resources{config=CFG}.crafters.cpu1.state
        '''), ('failed', True, 1, 'unknown'))

    def test_malformed_later_task_rejected_before_any_submission(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',1)
            local bad=task('ore:thing',{'t:raw'},1,1,'furnace')
            local r=run({task('t:final',{'t:raw'}),bad})
            return r.status,#MOVES,CLIENT_CALLS,#r.stages
        '''), ('failed', 0, 0, 0))

    def test_cli_craft_progress_and_status(self):
        self.module('mes_cli', 'bin/mes.lua')
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',1);DB['t:final']={{'t:raw'}}
            local lib=M;lib.plan=function() return {tasks={task('t:final',{'t:raw'})}} end
            local original=lib.run;lib.run=function(p,o) o.config=CFG;return original(p,o) end
            package.preload.shell=function() return {parse=function() return {'craft','t:final','1'},{} end} end
            local lines={};print=function(s) lines[#lines+1]=s end
            local code=require('mes_cli')
            return code,lines[1],lines[#lines]
        '''), (0, 'Stage 1: robot', 'complete'))

    def test_machine_role_mapping_non_air_order_and_last_role_fallback(self):
        self.assertEqual(self.lua.execute('''
            CFG.machineTypes.furnace.inputs={'input','extra'};CFG.machineTypes.furnace.roleSlots.extra={1,2}
            GROUPS.A.roles.extra='ax'
            put('stock','t:raw',1);put('stock','t:aux',1);put('stock','t:aux2',1);put('stock','t:fuel',1)
            local r=run({task('t:processed',{[1]='minecraft:air',[3]='t:raw',[8]='t:aux',[10]='t:aux2'},1,1,'furnace')},
                {machines={furnace='A'}})
            local locations={};for _,v in ipairs(MOVES) do if v.kind=='fetch' then locations[v.item]=v.s end end
            return r.status,locations['t:raw'],locations['t:aux'],locations['t:aux2']
        '''), ('complete', 'ai', 'ax', 'ax'))

    def test_tool_manufactured_before_machine_rebudgeted_after_barrier(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',1);put('stock','t:clay',1);put('stock','t:fuel',1)
            local finish=task('t:final',{'t:tool','t:processed'});finish.tool_slots={[1]='t:tool'}
            local p={tools={['t:tool']={durability=20,durabilityPerUse=1}},tasks={
                task('t:tool',{'t:raw'}),task('t:processed',{'t:clay'},1,1,'furnace'),finish}}
            local r=awaitRun(p,{config=CFG,machines={furnace='A'}})
            return r.status,#r.stages,CLIENT_CALLS,held('stock','t:final'),held('stock','t:tool:1'),
                PAYLOAD.tool_stock['t:tool'][1],PAYLOAD.inventory_needed['t:tool']==nil
        '''), ('complete', 3, 2, 1, 1, 1, True))

    def test_exact_damaged_tool_metadata_fetched_and_wear_preserved(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',1);put('stock','t:tool:7',1)
            local t=task('t:final',{'t:tool','t:raw'});t.tool_slots={[1]='t:tool'}
            local r=awaitRun({tools={['t:tool']={durability=20,durabilityPerUse=1}},tool_stock={['t:tool']={1}},tasks={t}},
                {config=CFG})
            local fetched
            for _,v in ipairs(MOVES) do if v.kind=='fetch' and v.item:find('t:tool',1,true) then fetched=v.item end end
            return r.status,fetched,held('stock','t:tool:8'),held('stock','t:final')
        '''), ('complete', 't:tool:7', 1, 1))

    def test_manufactured_and_reused_tool_split_into_safe_jobs(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',2)
            local t=task('t:final',{'t:tool','t:raw'});t.tool_slots={[1]='t:tool'}
            local r=awaitRun({tools={['t:tool']={durability=20,durabilityPerUse=1}},
                tasks={task('t:tool',{'t:raw'}),t}},{config=CFG})
            return r.status,#r.stages,CLIENT_CALLS,held('stock','t:final'),held('stock','t:tool:1')
        '''), ('complete', 2, 2, 1, 1))

    def test_insufficient_tool_budget_fails_before_input_movement(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',3);put('stock','t:tool:18',1)
            local t=task('t:final',{'t:tool','t:raw'},3);t.tool_slots={[1]='t:tool'}
            local r=awaitRun({tools={['t:tool']={durability=20,durabilityPerUse=1}},tasks={t}},{config=CFG})
            return r.status,#MOVES,CLIENT_CALLS,r.error:find('stage tool wear budget',1,true)~=nil
        '''), ('failed', 0, 0, True))
