"""Thin service plumbing, guarded reconnect, and frontend-independent progress."""
from test_support import LuaCase
import test_mes_graph as graph


class MesServiceTests(LuaCase):
    def setUp(self):
        fixture = graph.MesGraphTests()
        fixture.setUp()
        self.lua = fixture.lua

    def test_failed_restore_does_not_report_started_or_leave_pump_guarded(self):
        self.lua.execute('''
          local p=require('mes_persist');local restore=p.restore
          p.restore=function() error('restore failed') end
          local ok,err=M.start{config=CFG}
          assert(not ok and err:find('restore failed',1,true))
          assert(not require('mes_service').guarded())
          p.restore=restore
          assert(M.start{config=CFG})
          put('stock','t:raw',1)
          assert(run({task('t:final',{'t:raw'})}).status=='complete')
        ''')

    def test_machine_capacity_exclusion_uses_completed_receipt(self):
        self.lua.execute('''
          CFG.machineTypes.furnace.roleSlots.output={1}
          CFG.machineTypes.furnace.batch=64
          put('stock','t:ore',64)
          MACHINE_RECIPES.kiln={{inputs={input={['t:ore']=1}},outputs={['t:metal']=1}}}
          local collect=require('warehouse').collect
          require('warehouse').collect=function(...)
            local ids=collect(...)
            for _,id in ipairs(ids) do JOBS[id].steps={{take={},taken=64,maxSize=64}} end
            return ids
          end
          local timing=require('mes_timing');local observe=timing.observe;local excluded
          timing.observe=function(w,g,c,e)
            observe(w,g,c,e);excluded=(g.timingExcluded or {}).capacity
          end
          assert(run({task('t:metal',{'t:ore'},'metal',{'ore'},'furnace',64)}).status=='complete')
          assert(excluded==1)
        ''')

    def test_job_notification_reads_only_that_job_and_idle_has_no_timer(self):
        self.lua.execute('''
          assert(M.start{config=CFG});assert(liveTimers()==0)
          put('stock','t:raw',2)
          local id=assert(M.run({tasks={task('t:left',{'t:raw'},'a',{'raw'}),
            task('t:right',{'t:raw'},'b',{'raw'})}},{config=CFG}))
          local lg=require('logistics');local status=lg.status;local reads={}
          lg.status=function(j) reads[#reads+1]=j;return status(j) end
          local job=next(JOBS)
          require('event').push('logistics',job,'active');require('mes_service').pump()
          assert(#reads==1 and reads[1]==job)
          assert(liveTimers()==0,'outstanding transfers must wait for notifications')
          assert(M.wait(id).status=='complete');assert(liveTimers()==0)
        ''')

    def test_known_idle_robots_are_not_read_before_each_run(self):
        self.lua.execute('''
          local c=require('craft_client');local inspect=c.inspect;local reads=0
          c.inspect=function(...) reads=reads+1;return inspect(...) end
          assert(M.start{config=CFG});local initial=reads;assert(initial==2)
          put('stock','t:raw',2)
          assert(run({task('t:left',{'t:raw'})}).status=='complete')
          assert(run({task('t:right',{'t:raw'})}).status=='complete')
          assert(reads==initial)
        ''')

    def test_install_once_and_every_connect_entry_is_guarded(self):
        self.lua.execute('''
          local c=require('craft_client');local install=c.install;local tick=c.tick
          local connects=0
          c.install=function(...) assert(require('mes_service').guarded());connects=connects+1;return install(...) end
          c.tick=function(...) assert(require('mes_service').guarded());return tick(...) end
          assert(M.start{config=CFG});assert(M.start{config=CFG})
          assert(INSTALLS==1 and connects==1 and liveTimers()==0)
          assert(LISTENERS.logistics and LISTENERS.warehouse and package.loaded.map)
        ''')

    def test_run_submission_never_calls_reconnect_tick(self):
        self.lua.execute('''
          local c=require('craft_client');local ticks=0;c.tick=function() ticks=ticks+1 end
          put('stock','t:raw',1)
          local id=assert(M.run({tasks={task('t:final',{'t:raw'})}},{config=CFG}))
          assert(M.status(id).status=='running' and ticks==0 and #CLIENTS==0)
          M.wait(id);assert(ticks>0)
        ''')

    def test_initial_status_pending_waits_and_busy_never_synthesizes_idle(self):
        self.lua.execute('''
          require('craft_client').inspect=function() return true end
          put('stock','t:raw',1)
          local id=assert(M.run({tasks={task('t:final',{'t:raw'})}},{config=CFG}))
          assert(M.status(id).status=='running' and #MOVES==0)
          local svc=require('mes_service')
          svc.enqueue(nil,'robot_status',{address='robot1',busy=true})
          svc.enqueue(nil,'robot_status',{address='robot2',unknown=true,reason='unanswered'})
          svc.pump()
          assert(M.status(id).status=='failed' and #MOVES==0)
          local r=M.resources{config=CFG};assert(r.crafters.cpu1.state=='busy' and r.crafters.cpu2.state=='unknown')
        ''')

    def test_unreachable_initial_status_is_unknown_not_idle(self):
        self.lua.execute('''
          require('craft_client').inspect=function() return nil,'unreachable' end
          put('stock','t:raw',1)
          local id=assert(M.run({tasks={task('t:final',{'t:raw'})}},{config=CFG}))
          assert(M.status(id).status=='failed' and M.status(id).reason=='No idle resources for ready steps')
          assert(M.resources{config=CFG}.crafters.cpu1.state=='unknown' and #MOVES==0)
        ''')

    def test_nested_connect_pull_queues_facts_without_advance_reentry(self):
        self.lua.execute('''
          put('stock','t:raw',1)
          local state=require('mes_state');local advance=state.advance;local advancing=false;local advances=0
          state.advance=function(run)
            assert(not advancing,'advance reentered');advancing=true;advances=advances+1
            local ok,e=pcall(advance,run);advancing=false;assert(ok,e)
          end
          local id=assert(M.run({tasks={task('t:final',{'t:raw'})}},{config=CFG,crafter='cpu1'}))
          local ev=require('event');while #CLIENTS==0 do ev.pull() end
          local svc=require('mes_service');local c=require('craft_client');local oldTick=c.tick
          local fired=false;local arrived
          c.tick=function(now)
            assert(svc.guarded() and not advancing)
            if not fired then
              fired=true;arrived=TIME;local before=advances
              -- Model api.connect's nested pull: bottom callbacks run while the
              -- guarded pump is suspended, but must not execute MES decisions.
              local pull=ev.pull
              ev.pull=function()
                put('buf1','t:raw',0);put('buf1','t:final',1)
                svc.enqueue(nil,'robot_progress',{address='robot1',jobId='mes-'..id..'-1',receipt={message='WORKING nested'}})
                svc.enqueue(nil,'robot_terminal',{address='robot1',jobId='mes-'..id..'-1',status='complete',at=arrived,receipt={status='COMPLETE',receipt=true}})
                svc.pump();assert(advances==before)
                TIME=TIME+5
              end
              ev.pull();ev.pull=pull
              assert(advances==before and M.status(id).stages[1].state=='crafting')
              -- The fake's old delayed hardware completion is superseded by
              -- the explicitly supplied authoritative terminal receipt above.
              ACTIONS={}
            end
            return oldTick(now)
          end
          ev.push('craft_client')
          while M.status(id).status=='running' do ev.pull() end
          assert(M.status(id).status=='complete' and M.status(id).stages[1].craftFinished==arrived)
          assert(M.status(id).stages[1].receipt.receipt==true and advances>0)
        ''')

    def test_handlers_and_advance_never_pull_or_sleep(self):
        self.lua.execute('''
          local ev=require('event');local pull=ev.pull
          local s=require('mes_state');local advance=s.advance
          s.advance=function(run)
            ev.pull=function() error('advance pulled') end
            os.sleep=function() error('advance slept') end
            local ok,e=pcall(advance,run);ev.pull=pull;assert(ok,e)
          end
          put('stock','t:raw',2);put('stock','t:ore',1)
          MACHINE_RECIPES.kiln={{inputs={input={['t:ore']=1}},outputs={['t:metal']=1}}}
          local r=run({task('t:left',{'t:raw'},'a',{'raw'}),task('t:right',{'t:raw'},'b',{'raw'}),
            task('t:metal',{'t:ore'},'c',{'ore'},'furnace')})
          assert(r.status=='complete' and MAX_CLIENTS==2)
        ''')

    def test_frontend_returns_then_unrelated_event_loop_finishes_run(self):
        self.lua.execute('''
          put('stock','t:raw',2)
          local function transientFrontend()
            return assert(M.run({tasks={task('t:left',{'t:raw'},'a',{'raw'}),task('t:right',{'t:raw'},'b',{'raw'})}},{config=CFG}))
          end
          local id=transientFrontend();transientFrontend=nil;collectgarbage()
          assert(M.status(id).status=='running')
          while M.status(id).status=='running' do require('event').pull() end
          assert(M.status(id).status=='complete' and MAX_CLIENTS==2 and held('stock','t:left')==1)
          assert(INSTALLS==1 and liveTimers()==0 and package.loaded.thread==nil)
        ''')

    def test_failure_fact_queued_during_reconnect_prevents_any_new_fetch(self):
        self.lua.execute('''
          put('stock','t:raw',2)
          local id=assert(M.run({tasks={task('t:left',{'t:raw'},'a',{'raw'}),task('t:right',{'t:raw'},'b',{'raw'})}},{config=CFG}))
          local svc=require('mes_service');local c=require('craft_client');local fired=false
          c.tick=function()
            assert(svc.guarded())
            if not fired then fired=true;BEFORE=#MOVES;svc.enqueue(id,'cancel',{reason='queued during connect'});svc.pump() end
          end
          local r=M.wait(id)
          -- Inputs already on their way finish; nothing new is fetched after the failure.
          assert(r.status=='failed' and r.reason=='queued during connect' and #MOVES==BEFORE and #CLIENTS==0)
          for _,job in pairs(JOBS) do assert(job.settled) end
        ''')
