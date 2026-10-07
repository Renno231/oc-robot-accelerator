from test_support import LuaCase


class MesTests(LuaCase):
    def setUp(self):
        super().setUp()
        self.module('inventory', 'lib/inventory.lua')
        self.module('craftingv4_4', 'lib/craftingv4_4.lua')
        self.lua.execute('''
            DB, STOCK, ORES = {}, {}, {}
            package.preload.recipes=function() return {getAll=function(id) return DB[id] end} end
            package.preload.oredict=function() return {get=function() end,getByItemName=function() end} end
            package.preload.craft_tools=function() return {list=function() return {} end} end
            package.preload.serialization=function() return {} end
            package.preload.filesystem=function() return {} end
            TIME=0; EVENTS={}; JOBS={}; MOVES={}; NEXT=0; FAIL=false; TIMEOUT=false
            package.preload.computer=function() return {uptime=function() return TIME end} end
            package.preload.event=function() return {
                push=function(...) EVENTS[#EVENTS+1]={...} end,
                pull=function(n) TIME=TIME+(n or 0); if coroutine.isyieldable() then coroutine.yield() end end
            } end
            GROUPS={cpu1={type='crafter',roles={buffer='buf'}},
                A={type='furnace',roles={input='ai',output='ao',fuel='af'}},
                B={type='furnace',roles={input='bi',output='bo',fuel='bf'}}}
            MEMBERS={stock={},buf={},ai={},ao={},af={},bi={},bo={},bf={}}
            CONTENTS={}
            function put(s,id,n)
                CONTENTS[s]=CONTENTS[s] or {items={}}
                local name,damage=id:match('^(.*):(%d+)$')
                CONTENTS[s].items[id]={item={name=name or id,damage=tonumber(damage) or 0},count=n,maxSize=64}
            end
            function held(s,id) return CONTENTS[s] and CONTENTS[s].items[id] and CONTENTS[s].items[id].count or 0 end
            function job() NEXT=NEXT+1;JOBS[NEXT]={state='queued',moved=1};return NEXT end
            package.preload.logistics=function() return {status=function(id)
                local j=JOBS[id]; if j.state=='queued' then j.state='waiting';return j end
                if j.state=='waiting' then j.state='done' end; return j
            end} end
            package.preload.warehouse=function() return {
                groups=function(kind) local out={};for n,g in pairs(GROUPS) do if not kind or g.type==kind then out[n]=g end end;return out end,
                members=function() return MEMBERS end,
                contents=function(s) return CONTENTS[s] or {items={}} end,
                scan=function(s) return {job()} end,
                fetch=function(item,n,s)
                    local id=require('item_identity').stackName(item)
                    if FAIL or held('stock',id)<n then return nil,'shortfall' end
                    put('stock',id,held('stock',id)-n);put(s,id,held(s,id)+n)
                    MOVES[#MOVES+1]={kind='fetch',item=id,n=n,s=s}
                    if (s=='ai' or s=='bi') and not TIMEOUT then
                        put(s,id,0);put(s=='ai' and 'ao' or 'bo','t:processed',n)
                        local fuel=s=='ai' and 'af' or 'bf'
                        put(fuel,'t:fuel',math.max(0,held(fuel,'t:fuel')-math.ceil(n/8)))
                    end
                    return job()
                end,
                store=function(item,n,s)
                    local id=require('item_identity').stackName(item)
                    put(s,id,held(s,id)-n);put('stock',id,held('stock',id)+n)
                    MOVES[#MOVES+1]={kind='store',item=id,n=n,s=s};return job()
                end
            } end
            CLIENT_STATUS='complete'; CLIENT_CALLS=0
            package.preload.craft_client=function() return {runDetailed=function(p,o)
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
            package.preload.thread=function() return {create=function(f,...)
                local args={...}; local co=coroutine.create(function() f(table.unpack(args)) end)
                THREADS=THREADS or {};THREADS[#THREADS+1]=co
                return {join=function()
                    local running=true
                    while running do running=false
                        for _,c in ipairs(THREADS) do if coroutine.status(c)~='dead' then
                            running=true;local ok,err=coroutine.resume(c);assert(ok,err)
                        end end
                    end
                end}
            end} end
            CFG={crafters={cpu1={robot='robot-address'}},machineTypes={furnace={
                inputs={'input'},output='output',fuel={role='fuel',item='t:fuel',per=8},batch=64,seconds=0}}}
            function task(id,recipe,n,out,kind)
                return {item=id,recipe=recipe,qty_produced=n or 1,recipeOutput=out or 1,
                    machineType=kind,isProcessing=kind and true or nil}
            end
            function run(tasks,opts) opts=opts or {};opts.config=CFG;return M.run({tasks=tasks},opts) end
        ''')
        self.module('craft_plans', 'lib/craft_plans.lua')
        self.module('mes', 'lib/mes.lua')
        self.lua.execute("M=require('mes')")

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
                JOBS[id].state='partial';JOBS[id].reason='partial transfer'
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
            local p=M.plan('t:final:0',2)
            return p.craftable,p.inventory_needed['t:raw:2'],p.requestItem
        '''), (True, 2, 't:final'))

    def test_plan_shortfall_excludes_group_stock(self):
        self.assertEqual(self.lua.execute('''
            put('buf','t:raw',50);DB['t:final']={{'t:raw'}}
            local p,err=M.plan('t:final',1);return p==nil,err
        '''), (True, 'Missing inputs'))

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
            return r.status,a,b,held('stock','t:processed'),held('stock','t:fuel'),#THREADS
        '''), ('complete', 32, 32, 64, 0, 2))

    def test_specific_group_multiple_loads_existing_fuel(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',130);put('stock','t:fuel',17);put('af','t:fuel',1)
            local r=run({task('t:processed',{'t:raw'},130,1,'furnace')},{machines={furnace='A'}})
            local loads=0;for _,v in ipairs(MOVES) do if v.kind=='fetch' and v.item=='t:raw' then
                assert(v.n<=64 and v.s=='ai');loads=loads+1
            end end
            return r.status,loads,held('stock','t:processed'),held('stock','t:fuel'),held('bi','t:raw')
        '''), ('complete', 3, 130, 1, 0))

    def test_shortfall_reports_locations_stops_without_retry(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',0);FAIL=true
            local r=run({task('t:processed',{'t:raw'},1,1,'furnace'),task('t:final',{'t:processed'})},
                {machines={furnace='A'}})
            return r.status,#r.stages,CLIENT_CALLS,r.stages[1].remaining.ai~=nil,r.error:find('shortfall')~=nil
        '''), ('failed', 1, 0, True, True))

    def test_unknown_robot_outcome_does_not_store_or_continue(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',1);CLIENT_STATUS='unknown'
            local r=run({task('t:final',{'t:raw'})})
            return r.status,CLIENT_CALLS,held('buf','t:raw'),#MOVES,r.stages[1].remaining.buf.verified
        '''), ('unknown', 1, 1, 1, True))

    def test_busy_guard_and_release(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',2);BUSY_PROBE=true
            local r=run({task('t:final',{'t:raw'})});BUSY_PROBE=false
            local second=run({task('t:final',{'t:raw'})})
            return r.status,BUSY_RESULT==nil,BUSY_ERROR,second.status,M.status().status
        '''), ('complete', True, 'busy', 'complete', 'complete'))

    def test_machine_timeout_reports_output(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',1);put('stock','t:fuel',1);TIMEOUT=true
            local r=run({task('t:processed',{'t:raw'},1,1,'furnace')},{machines={furnace='A'}})
            return r.status,r.error:find('deadline')~=nil,held('ai','t:raw'),r.stages[1].remaining.ai.verified
        '''), ('failed', True, 1, True))

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
            local r=M.run({tasks={t},blueprint={nodes={n={input_quantities={64}}}}},
                {config=CFG,machines={furnace='A'}})
            return r.status,held('stock','t:processed'),held('stock','t:raw')
        '''), ('complete', 64, 0))

    def test_events_and_read_only_status_copy(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',1);run({task('t:final',{'t:raw'})})
            local s=M.status();s.status='changed'
            return EVENTS[1][1],EVENTS[1][2],EVENTS[#EVENTS][2],EVENTS[#EVENTS][3],M.status().status
        '''), ('mes', 'stage', 'done', 'complete', 'complete'))

    def test_processing_plan_is_returned_without_robot_validator(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',64)
            DB['t:processed']={{'t:raw,64',qty=64,isProcessing=true,machineType='furnace'}}
            local p=assert(M.plan('t:processed',64))
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
            local r=M.run('/tmp/process.plan',{config=CFG,machines={furnace='A'}})
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

    def test_failure_scan_unavailable_marks_locations_unknown(self):
        self.assertEqual(self.lua.execute('''
            require('warehouse').scan=function() error('scan unavailable') end
            local r=run({task('t:final',{'t:raw'})})
            return r.status,r.stages[1].remaining.buf.unknown,r.stages[1].remaining.buf.verified,
                r.stages[1].remaining.buf.error:find('scan unavailable')~=nil
        '''), ('failed', True, False, True))

    def test_concurrent_failure_settles_other_worker_and_stops_next_stage(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',128);put('stock','t:fuel',16)
            local wh=require('warehouse');local original=wh.fetch
            wh.fetch=function(i,n,s,o) if s=='ai' then return nil,'A input shortfall' end;return original(i,n,s,o) end
            local r=run({task('t:processed',{'t:raw'},128,1,'furnace'),task('t:final',{'t:processed'})})
            local settled=true;for _,j in pairs(JOBS) do if j.state~='done' then settled=false end end
            return r.status,#r.stages,CLIENT_CALLS,settled,held('stock','t:processed')
        '''), ('failed', 1, 0, True, 64))

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

    def test_first_idle_crafter_hook_and_per_crafter_occupancy(self):
        self.assertEqual(self.lua.execute('''
            CFG.crafters.cpu2={robot='second-robot'}
            GROUPS.cpu2={type='crafter',roles={buffer='buf'}}
            put('stock','t:raw',1)
            local client=require('craft_client');local original=client.runDetailed
            local first,second
            client.runDetailed=function(...) local c=M.crafters{config=CFG};first=c.cpu1.status;second=c.cpu2.status;return original(...) end
            local r=run({task('t:final',{'t:raw'})},{isCrafterIdle=function(name) return name=='cpu2' end})
            return r.status,ADDRESS,first,second,M.crafters{config=CFG}.cpu2.status
        '''), ('complete', 'second-robot', 'idle', 'busy', 'idle'))

    def test_unknown_crafter_not_selected_again_without_idle_confirmation(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',2);CLIENT_STATUS='unknown'
            run({task('t:final',{'t:raw'})})
            local second=run({task('t:final',{'t:raw'})})
            return second.status,second.error:find('No idle crafter')~=nil,CLIENT_CALLS,
                M.crafters{config=CFG}.cpu1.status
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
            return code,lines[1],lines[2]
        '''), (0, 'Stage 1: robot', 'complete'))

    def test_machine_role_mapping_non_air_order_and_last_role_fallback(self):
        self.assertEqual(self.lua.execute('''
            CFG.machineTypes.furnace.inputs={'input','extra'};GROUPS.A.roles.extra='ax'
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
            local r=M.run(p,{config=CFG,machines={furnace='A'}})
            return r.status,#r.stages,CLIENT_CALLS,held('stock','t:final'),held('stock','t:tool:1'),
                PAYLOAD.tool_stock['t:tool'][1],PAYLOAD.inventory_needed['t:tool']==nil
        '''), ('complete', 3, 2, 1, 1, 1, True))

    def test_exact_damaged_tool_metadata_fetched_and_wear_preserved(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',1);put('stock','t:tool:7',1)
            local t=task('t:final',{'t:tool','t:raw'});t.tool_slots={[1]='t:tool'}
            local r=M.run({tools={['t:tool']={durability=20,durabilityPerUse=1}},tool_stock={['t:tool']={1}},tasks={t}},
                {config=CFG})
            local fetched
            for _,v in ipairs(MOVES) do if v.kind=='fetch' and v.item:find('t:tool',1,true) then fetched=v.item end end
            return r.status,fetched,held('stock','t:tool:8'),held('stock','t:final')
        '''), ('complete', 't:tool:7', 1, 1))

    def test_same_stage_manufactured_and_reused_tool_fails_before_movement(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',2)
            local t=task('t:final',{'t:tool','t:raw'});t.tool_slots={[1]='t:tool'}
            local r=M.run({tools={['t:tool']={durability=20,durabilityPerUse=1}},
                tasks={task('t:tool',{'t:raw'}),t}},{config=CFG})
            return r.status,#MOVES,CLIENT_CALLS,r.error:find('Unsupported stage-tool contract',1,true)~=nil
        '''), ('failed', 0, 0, True))

    def test_insufficient_tool_budget_fails_before_input_movement(self):
        self.assertEqual(self.lua.execute('''
            put('stock','t:raw',3);put('stock','t:tool:18',1)
            local t=task('t:final',{'t:tool','t:raw'},3);t.tool_slots={[1]='t:tool'}
            local r=M.run({tools={['t:tool']={durability=20,durabilityPerUse=1}},tasks={t}},{config=CFG})
            return r.status,#MOVES,CLIENT_CALLS,r.error:find('stage tool wear budget',1,true)~=nil
        '''), ('failed', 0, 0, True))
