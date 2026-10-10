"""Pure update/advance proofs: no OpenOS, clocks, networking or hardware imports.

Action submissions, terminal receipts, scoped observations and catalogue
settlement are independent facts supplied explicitly by each test.
"""
from test_support import LuaCase


class MesStateTests(LuaCase):
    def setUp(self):
        super().setUp()
        self.module('mes_state', 'lib/mes_state.lua')
        self.lua.execute(r'''
          for _,name in ipairs({'event','computer','warehouse','logistics','craft_client','thread'}) do
            package.preload[name]=function() error('state imported hardware: '..name) end
          end
          os.sleep=function() error('state slept') end
          S=require('mes_state');WORLD=S.world();ACTIONS={};EMITTED={};VIEWS={};TIME=0;NEXT=0
          CF={a={robot='r1',buffer='b1'},b={robot='r2',buffer='b2'}}
          WORLD.robots.r1={state='idle'};WORLD.robots.r2={state='idle'}
          GROUPS={kiln={type='furnace',roles={input='mi',output='mo',fuel='mf'}},
            alloy={type='alloy',roles={a='ma',b='mb',output='mx'}}}
          CFG={crafters=CF,machineTypes={
            furnace={inputs={'input'},output='output',batch=2,seconds=1,blocking=false,roleSlots={input={1},output={1,2},fuel={1}}},
            alloy={inputs={'a','b'},output='output',batch=2,seconds=1,blocking=true,roleSlots={a={1},b={1},output={1,2}}}}}
          function view(storage)
            VIEWS[storage]=VIEWS[storage] or {items={},freeSlots=2,slots=2};return VIEWS[storage]
          end
          function put(storage,id,n,maximum)
            local v=view(storage);local m=maximum or 64
            v.items[id]={item={name=id,damage=0},count=n,maxSize=m,room=n>0 and (m-n%m)%m or 0,stacks=math.ceil(n/m)}
            v.freeSlots=v.slots;for _,r in pairs(v.items) do v.freeSlots=v.freeSlots-r.stacks end
          end
          function total(storage,id) return (view(storage).items[id] or {}).count or 0 end
          PORTS={
            dispatch=function(a) ACTIONS[#ACTIONS+1]=a end,
            emit=function(...) EMITTED[#EMITTED+1]={...} end,
            contents=function(storage) return view(storage) end,
            roleContents=function(storage,slots,listing,size) return S.copy(listing) end,
            stackSize=function() return 64 end,
            roleFits=function(v,quantities)
              local free=v.freeSlots
              for id,n in pairs(quantities) do local r=v.items[id] or {};free=free-math.ceil(math.max(0,n-(r.room or 0))/(r.maxSize or 64)) end
              return free>=0
            end,
            crafters=function() return CF end,
            groups=function(kind) local o={};for n,g in pairs(GROUPS) do if not kind or g.type==kind then o[n]=g end end;return o end,
            bufferIdentity=function(storage) return ALIAS or storage end,
            prepareRobot=function(run,stage,reserved)
              if stage.tool and (reserved['t:tool:7'] or 0)>=TOOL_COUNT then return nil,'Insufficient stage tool wear budget' end
              return {tasks={},inventory_needed={['t:raw']=1},requestOutputs={[stage.outputs[1].item]=1},tools={}},nil,stage.tool and {['t:tool:7']=1} or {}
            end
          }
          function robot(output,after,crafter)
            return {kind='robot',taskIndices={1},inputs={{item='t:raw',need=1}},outputs={{item=output,qty=1}},after=after or {},crafter=crafter}
          end
          function machine(output,ingredients,kind,n)
            kind=kind or 'furnace';n=n or 1
            return {kind='machine',machineType=kind,groups={kind=='furnace' and 'kiln' or 'alloy'},
              taskIndices={1},inputs={},outputs={{item=output,qty=n}},after={},testRecipe=ingredients,testQty=n}
          end
          function new(stages,opts)
            local tasks={}
            for i,s in ipairs(stages) do
              s.taskIndices={i};tasks[i]={item=s.outputs[1].item,recipe=s.testRecipe or {'t:raw'},qty_produced=s.testQty or 1,recipeOutput=1,machineType=s.machineType}
            end
            RUN=S.new(1,{tasks=tasks,stages=stages},CFG,opts or {},WORLD,PORTS,TIME);S.advance(RUN);return RUN
          end
          function fact(what,data) S.update(RUN,what,data) end
          function advance() S.advance(RUN) end
          function tick(now) TIME=now;fact('tick',{now=now});advance() end
          function actions(kind)
            local o={};for _,a in ipairs(ACTIONS) do if a.kind==kind and not a.testDone then o[#o+1]=a end end;return o
          end
          function submit(a,ids,err) fact('action_submitted',{token=a.token,ids=ids,error=err}) end
          function receipt(a,id,state,why,moved)
            local l={state=state or 'done',reason=why,trips=1,tripTimings={{queuedAt=TIME,finishedAt=TIME}},steps={},perItem={}}
            if a.kind=='scanRoles' then for _,r in ipairs(a.requests) do l.steps[#l.steps+1]={roleKey=r.key,listing=S.copy(view(r.storage)),size=2} end
            elseif a.kind=='scanRole' then l.steps={{listing=S.copy(view(a.storage)),size=2}}
            else for i,r in ipairs(a.requests or {}) do
              local n=moved and moved[i] or r.count
              -- A collection takes what is there.
              if a.kind=='collectMany' then
                n=math.min(n,total(type(a.endpoint)=='table' and a.endpoint.storage or a.endpoint,r.item.name..((r.item.damage or 0)>0 and ':'..r.item.damage or '')))
                if n<r.count then l.steps[#l.steps+1]={short=true};l.held={} end
              end
              l.perItem[#l.perItem+1]={item=r.item,requestIndex=i,requested=r.count,moved=n,shortfall=r.count-n,taken=r.count,returned=r.count-n}
            end end
            fact('job',{id=id,receipt=l});return l
          end
          function finish(a,state,why,moved)
            NEXT=NEXT+1;local id=NEXT;a.testDone=true;submit(a,{id});receipt(a,id,state,why,moved);fact('settled',{id=id});advance();return id
          end
          function drain(kind)
            local list=actions(kind);for _,a in ipairs(list) do finish(a) end
          end
          function readyRobots()
            drain('scan');drain('fetchMany');return actions('robot_begin')
          end
          -- A finished robot reports what it read in its buffer.
          function terminal(a,status,at)
            local buffer
            if (status or 'complete')=='complete' then
              buffer={};for _,c in pairs(CF) do if c.robot==a.address then
                for id,v in pairs(view(c.buffer).items) do if v.count>0 then buffer[id]=v.count end end
              end end
            end
            a.testDone=true;fact('robot_terminal',{token=a.token,address=a.address,jobId=a.jobId,status=status or 'complete',at=at or TIME,
              receipt={status=status or 'complete',message='robot '..(status or 'complete'),buffer=buffer}});advance()
          end
          function loaded(stages,opts)
            new(stages,opts);drain('scanRoles');drain('fetchMany')
          end
        ''')

    def test_update_records_only_and_advance_dispatches_both_branches(self):
        self.lua.execute('''
          new({robot('t:left'),robot('t:right'),robot('t:join',{1,2})})
          assert(#actions('fetchMany')==2 and RUN.stages[3].state=='waiting')
          local before=#ACTIONS;local a=actions('fetchMany')[1]
          a.testDone=true;submit(a,{10});receipt(a,10);fact('settled',{id=10})
          assert(#ACTIONS==before and RUN.stages[1].state=='fetching')
          advance();assert(#actions('robot_begin')==1)
          assert(package.loaded.event==nil and package.loaded.warehouse==nil)
        ''')

    def test_terminal_without_settlement_never_starts_robot(self):
        self.lua.execute('''
          new({robot('t:final')});drain('scan');local a=actions('fetchMany')[1]
          submit(a,{20});receipt(a,20);advance()
          assert(#actions('robot_begin')==0 and RUN.stages[1].physicalJobs[1].status=='pending')
          fact('settled',{id=20});advance();assert(#actions('robot_begin')==1)
        ''')

    def test_robot_and_buffer_aliases_lock_before_any_action(self):
        self.lua.execute('''
          CF.b.robot='r1';new({robot('t:left'),robot('t:right')})
          assert(#actions('fetchMany')==1 and WORLD.robots.r1.state=='busy')
        ''')
        self.setUp()
        self.lua.execute('''
          ALIAS='physical-chest';new({robot('t:left'),robot('t:right')})
          assert(#actions('fetchMany')==1 and WORLD.buffers[ALIAS].owner=='r1')
        ''')

    def test_partial_submission_retains_all_ids_and_first_failure_until_settled(self):
        self.lua.execute('''
          new({robot('t:final')});drain('scan');local a=actions('fetchMany')[1]
          a.testDone=true;submit(a,{21,22},'submission stopped');receipt(a,21,'partial','later failure',{0});advance()
          assert(RUN.status=='running' and RUN.reason=='submission stopped' and #RUN.stages[1].physicalJobs==2)
          fact('settled',{id=21});receipt(a,22);advance();assert(RUN.status=='running')
          fact('settled',{id=22});advance();drain('scan')
          assert(RUN.status=='failed' and #actions('robot_begin')==0)
        ''')

    def test_first_received_failure_not_hash_order(self):
        self.lua.execute('''
          new({robot('t:left'),robot('t:right')});drain('scan')
          local a,b=actions('fetchMany')[1],actions('fetchMany')[2];submit(a,{31});submit(b,{32})
          receipt(b,32,'partial','first b');receipt(a,31,'partial','second a');advance()
          assert(RUN.reason=='first b');fact('settled',{id=31});fact('settled',{id=32});advance();drain('scan')
          assert(RUN.status=='failed' and #actions('robot_begin')==0)
        ''')

    def test_cancel_drains_active_robot_and_store_without_dispatching_join(self):
        self.lua.execute('''
          new({robot('t:left'),robot('t:right'),robot('t:join',{1,2})});local running=readyRobots()
          fact('cancel',{});advance();assert(RUN.status=='running')
          put('b1','t:left',1);put('b2','t:right',1)
          terminal(running[1]);terminal(running[2]);drain('collectMany')
          assert(RUN.status=='failed' and RUN.reason=='Cancelled' and RUN.stages[3].state=='waiting')
          assert(RUN.stages[1].state=='done' and RUN.stages[2].state=='done')
        ''')

    def test_later_index_robot_failure_stops_ready_earlier_robot_before_dispatch(self):
        self.lua.execute('''
          new({robot('t:left'),robot('t:right')});drain('scan')
          local a,b=actions('fetchMany')[1],actions('fetchMany')[2]
          finish(b);local running=actions('robot_begin')[1]
          a.testDone=true;submit(a,{90});receipt(a,90);fact('settled',{id=90})
          fact('robot_terminal',{token=running.token,address=running.address,jobId=running.jobId,
            status='failed',receipt={status='failed',message='known robot failure'}})
          local before=#ACTIONS;assert(RUN.reason==nil)
          advance();assert(#actions('robot_begin')==1 and RUN.reason=='known robot failure')
          assert(RUN.stages[1].craftStarted==nil and #ACTIONS>before)
          drain('scan');assert(RUN.status=='failed' and RUN.stages[2].receipt.message=='known robot failure')
          assert(RUN.stages[1].physicalJobs[1].status=='complete')
        ''')

    def test_two_robot_failures_keep_first_received_not_first_stage(self):
        self.lua.execute('''
          new({robot('t:left'),robot('t:right')});local running=readyRobots()
          for _,i in ipairs({2,1}) do local a=running[i]
            fact('robot_terminal',{token=a.token,address=a.address,jobId=a.jobId,status='failed',
              receipt={status='failed',message=i==2 and 'first received b' or 'later a'}})
          end
          advance();assert(RUN.reason=='first received b');drain('scan')
          assert(RUN.status=='failed' and RUN.stages[1].error=='later a' and RUN.stages[2].error=='first received b')
        ''')

    def test_robot_logistics_and_cancel_failures_share_arrival_order(self):
        for first in ('robot', 'logistics', 'cancel'):
            with self.subTest(first=first):
                self.setUp()
                self.lua.execute('FIRST=%r' % first)
                self.lua.execute('''
                  new({robot('t:left'),robot('t:right')});drain('scan')
                  local a,b=actions('fetchMany')[1],actions('fetchMany')[2]
                  finish(b);local running=actions('robot_begin')[1];submit(a,{90})
                  local facts={
                    robot=function() fact('robot_terminal',{token=running.token,address=running.address,jobId=running.jobId,
                      status='failed',receipt={status='failed',message='robot first'}}) end,
                    logistics=function() receipt(a,90,'failed','logistics first',{0}) end,
                    cancel=function() fact('cancel',{reason='cancel first'}) end}
                  facts[FIRST]()
                  for _,kind in ipairs({'robot','logistics','cancel'}) do if kind~=FIRST then facts[kind]() end end
                  advance();assert(RUN.reason==FIRST..' first' and #actions('robot_begin')==1)
                  assert(RUN.status=='running');fact('settled',{id=90});advance();drain('scan')
                  assert(RUN.status=='failed' and RUN.reason==FIRST..' first')
                ''')

    def test_stray_and_stale_robot_failures_do_not_stop_actual_jobs(self):
        self.lua.execute('''
          new({robot('t:left'),robot('t:right')});local running=readyRobots();local a=running[1]
          fact('robot_terminal',{token=a.token,address='other',jobId=a.jobId,status='failed',reason='wrong address'})
          fact('robot_terminal',{token=a.token,address=a.address,jobId='other-job',status='failed',reason='wrong job'})
          fact('robot_terminal',{token='other-token',address=a.address,status='failed',reason='wrong token'})
          advance();assert(RUN.reason==nil and RUN.stages[1].state=='crafting')
          put('b1','t:left',1);terminal(a);drain('collectMany')
          fact('robot_terminal',{token=a.token,address=a.address,jobId=a.jobId,status='failed',reason='stale failure'})
          advance();assert(RUN.reason==nil and RUN.stages[1].receipt.status=='complete')
          put('b2','t:right',1);terminal(running[2]);drain('collectMany')
          assert(RUN.status=='complete')
        ''')

    def test_first_terminal_is_authoritative_when_duplicates_queue_together(self):
        self.lua.execute('''
          new({robot('t:final')});local a=readyRobots()[1]
          fact('robot_terminal',{token=a.token,address=a.address,jobId=a.jobId,status='complete',at=3,
            receipt={status='COMPLETE',message='SUCCESS',receipt=true}})
          fact('robot_terminal',{token=a.token,address=a.address,jobId=a.jobId,status='failed',at=4,reason='duplicate'})
          advance();assert(RUN.reason==nil and RUN.stages[1].craftFinished==3)
          drain('scan');assert(RUN.status=='complete' and RUN.stages[1].receipt.message=='SUCCESS')
        ''')

    def test_unknown_owner_quarantines_alias_and_only_own_idle_fact_clears(self):
        self.lua.execute('''
          ALIAS='shared';new({robot('t:left',{},'a')});terminal(readyRobots()[1],'unknown');drain('scan')
          assert(RUN.status=='unknown' and WORLD.buffers.shared.state=='unknown' and RUN.stages[1].released==nil)
          S.confirmIdle(WORLD,'r2');assert(WORLD.buffers.shared.state=='unknown')
          S.confirmIdle(WORLD,'r1');assert(WORLD.buffers.shared.state=='idle')
        ''')

    def test_terminal_arrival_timestamp_survives_delayed_advance(self):
        self.lua.execute('''
          new({robot('t:final')});local a=readyRobots()[1]
          fact('robot_terminal',{token=a.token,address=a.address,jobId=a.jobId,status='complete',at=3,receipt={status='COMPLETE',receipt=true}})
          fact('tick',{now=17});advance()
          assert(RUN.stages[1].craftFinished==3 and RUN.stages[1].receipt.status=='complete')
        ''')

    def test_success_receipt_and_settled_release_remain_in_finished_history(self):
        self.lua.execute('''
          new({robot('t:final')});local a=readyRobots()[1]
          tick(2)
          local original={status='COMPLETE',message='SUCCESS',jobId=a.jobId,receipt=true,finishedAt=3,buffer={['t:final']=1}}
          fact('robot_admitted',{token=a.token,address=a.address,jobId=a.jobId,disposition='started',receipt={status='RUNNING'}})
          fact('robot_terminal',{token=a.token,address=a.address,jobId=a.jobId,status='complete',at=3,receipt=original})
          put('b1','t:final',1);tick(4)
          local store=actions('collectMany')[1];submit(store,{51});receipt(store,51);advance()
          local stage=RUN.stages[1]
          assert(stage.assigned==0 and stage.craftStarted==0 and stage.craftFinished==3)
          assert(stage.released==nil and stage.receipt.message=='SUCCESS' and stage.receipt.receipt==true)
          assert(original.status=='COMPLETE' and original.message=='SUCCESS')
          tick(8);fact('settled',{id=51});advance()
          assert(RUN.status=='complete' and stage.released==8 and stage.receipt.finishedAt==3)
          assert(stage.admission.disposition=='started' and stage.physicalJobs[2].tripTimings[1].finishedAt==4)
          assert(RUN.plan==nil and RUN.ports==nil and RUN.world==nil and stage.prepared==nil)
          assert(#stage.itemsMoved==2 and stage.itemsMoved[2].allocations[1].job==51)
        ''')

    def test_world_reconciliation_requires_real_idle_and_ignores_busy_owner(self):
        self.lua.execute('''
          WORLD.robots.r1={state='unknown'}
          WORLD.buffers.shared={state='unknown',owner='r1'}
          S.updateWorld(WORLD,'robot_transport',{address='r1',state='ready'})
          assert(#ACTIONS==0 and WORLD.robots.r1.state=='unknown')
          S.advanceWorld(WORLD,PORTS.dispatch,{})
          assert(#actions('robot_inspect')==1 and WORLD.robots.r1.pending)
          S.updateWorld(WORLD,'robot_status',{address='r1',unknown=true})
          S.advanceWorld(WORLD,PORTS.dispatch,{})
          assert(WORLD.robots.r1.state=='unknown' and WORLD.buffers.shared.state=='unknown')
          S.updateWorld(WORLD,'robot_status',{address='r1',busy=false})
          S.advanceWorld(WORLD,PORTS.dispatch,{})
          assert(WORLD.robots.r1.state=='idle' and WORLD.buffers.shared.state=='idle')
          WORLD.robots.r1={state='busy',run=9,step=1}
          S.updateWorld(WORLD,'robot_status',{address='r1',busy=false})
          S.advanceWorld(WORLD,PORTS.dispatch,{})
          assert(WORLD.robots.r1.run==9 and WORLD.robots.r1.state=='busy')
        ''')

    def test_blocking_same_recipe_topup_and_different_recipe_waits_for_its_loads_to_be_collected(self):
        self.lua.execute('''
          loaded({machine('t:bronze',{'t:copper','t:tin'},'alloy',4),machine('t:steel',{'t:iron','t:coal'},'alloy')})
          while #actions('fetchMany')>0 do drain('fetchMany') end
          -- Same recipe tops up; the other recipe waits. Nothing is looked at.
          assert(#RUN.stages[1].loadLedger==4 and RUN.stages[2].loadLedger==nil)
          assert(#actions('scanRole')==0 and #actions('scanRoles')==0 and #actions('fetchMany')==0)
          put('mx','t:bronze',4);tick(5);drain('collectMany')
          assert(RUN.stages[1].state=='done' and #RUN.stages[2].loadLedger==1)
          assert(#actions('scanRole')==0 and #actions('scanRoles')==0)
        ''')

    def test_machine_fifo_packed_store_allocates_real_split_ids_and_byproducts(self):
        self.lua.execute('''
          local a=machine('t:metal',{'t:ore'});a.outputs[2]={item='t:slag',qty=1}
          loaded({a,machine('t:metal',{'t:ore'})});drain('fetchMany')
          assert(#RUN.stages[1].loadLedger==1 and #RUN.stages[2].loadLedger==1)
          put('mo','t:metal',2);put('mo','t:slag',1);tick(2)
          local store=actions('collectMany')[1];assert(#store.requests==2)
          store.testDone=true;submit(store,{41,42})
          fact('job',{id=41,receipt={state='done',trips=1,perItem={{item={name='t:metal'},requestIndex=1,requested=1,moved=1}}}})
          fact('job',{id=42,receipt={state='done',trips=1,perItem={{item={name='t:metal'},requestIndex=1,requested=1,moved=1},{item={name='t:slag'},requestIndex=2,requested=1,moved=1}}}})
          fact('settled',{id=41});advance();assert(RUN.status=='running')
          fact('settled',{id=42});advance()
          local x,y=RUN.stages[1].loadLedger[1],RUN.stages[2].loadLedger[1]
          assert(x.storeJobs[1].job==41 and y.storeJobs[1].job==42)
          assert(x.collectedItems['t:slag']==1 and x.collectedItems['t:metal']==1 and y.collectedItems['t:metal']==1)
          assert(RUN.status=='complete' and #RUN.stages[1].physicalJobs==3 and #RUN.stages[2].physicalJobs==1)
        ''')

    def test_tool_exact_physical_reservations_serialize_when_only_one_unit(self):
        self.lua.execute('''
          TOOL_COUNT=1;local a,b=robot('t:left'),robot('t:right');a.tool=true;b.tool=true
          new({a,b});assert(#actions('fetchMany')==1 and WORLD.toolReservations['t:tool:7']==1)
          local running=readyRobots()[1];put('b1','t:tool:8',1);put('b1','t:left',1)
          terminal(running);drain('collectMany')
          assert(RUN.stages[1].state=='done' and RUN.stages[2].state=='fetching' and #actions('fetchMany')==1)
          assert(WORLD.toolReservations['t:tool:7']==1)
        ''')

    def test_fuel_counts_only_what_the_mes_delivered(self):
        self.lua.execute('''
          CFG.machineTypes.furnace.fuel={role='fuel',item='t:fuel',per=2}
          local stage=machine('t:metal',{'t:ore'},nil,4);stage.fuel={item='t:fuel',need=2}
          put('mf','t:fuel',1);loaded({stage});drain('fetchMany')
          -- A unit added by hand is not ours to count; the machine is never looked at.
          local fuel=0;for _,a in ipairs(ACTIONS) do if a.kind=='fetchMany' then for _,v in ipairs(a.requests) do if v.item.name=='t:fuel' then fuel=fuel+v.count end end end end
          local f=WORLD.machines.kiln.fuel
          assert(#RUN.stages[1].loadLedger==2 and fuel==2 and f.credit==2 and f.admitted==4,fuel..' '..f.credit..' '..f.admitted)
          assert(#actions('scanRoles')==0 and #actions('scanRole')==0)
        ''')
