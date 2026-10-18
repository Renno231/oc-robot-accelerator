"""Event-only incidents over catalogue/state facts, with canonical CBOR storage."""
from pathlib import Path
import unittest
from lupa.lua53 import LuaRuntime
from test_store import install_store


class AlertTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.globals().SERIAL=Path('.cache/oc-source/src/main/resources/assets/opencomputers/loot/openos/lib/serialization.lua').read_text()
        self.lua.execute('''
          function checkArg(n,v,...) for _,t in ipairs({...}) do if type(v)==t then return end end;error('bad argument '..n) end
          package.preload.serialization=function() return assert(load(SERIAL))() end
        ''')
        install_store(self.lua)
        for name in ('alerts','alert_sources'):
            self.lua.globals()['MES_'+name.upper()]=Path('craftsystem/usr/lib/mes/'+name+'.lua').read_text()
        self.lua.execute('''
          TIME=0;D={};IO={};world={groups={}};FILL=0;SOON=false;EVENTS={};LISTEN={};TIMERS={};TCALLS=0;CANCELS=0
          CFG={fillWarn=.8,fillBad=.95,fullSoonHours=2}
          package.loaded.computer={uptime=function() return TIME end}
          local event={}
          function event.push(...) EVENTS[#EVENTS+1]={...} end
          function event.listen(n,f) LISTEN[n]=LISTEN[n] or {};table.insert(LISTEN[n],f) end
          function event.timer(seconds,f,times)
            assert(times==1,'repeating timer');TCALLS=TCALLS+1
            TIMERS[TCALLS]={at=TIME+seconds,fn=f};return TCALLS
          end
          function event.cancel(id) if TIMERS[id] then TIMERS[id]=nil;CANCELS=CANCELS+1 end end
          package.loaded.event=event
          function emit(n,...) for _,f in ipairs(LISTEN[n] or {}) do f(n,...) end end
          function tick(time)
            TIME=time;local ids={};for id,t in pairs(TIMERS) do if t.at<=TIME then ids[#ids+1]=id end end
            table.sort(ids);for _,id in ipairs(ids) do local t=TIMERS[id];if t then TIMERS[id]=nil;t.fn() end end
          end
          function timerCount() local n=0;for _ in pairs(TIMERS) do n=n+1 end;return n end
          package.loaded.logistics={drones=function() return D end,job=function() error('unexpected job') end}
          package.loaded["logistics.iochest"]={list=function() return IO end}
          local stats={settings=function() local c={};for k,v in pairs(CFG) do c[k]=v end;return c end,
            summary=function() return {fill=FILL} end,
            warnings=function() local w={};if FILL>=CFG.fillWarn then w[#w+1]={kind='fill',fill=FILL} end
              if SOON then w[#w+1]={kind='fullSoon',hours=1} end;return w end}
          function stats.set(k,v)
            assert(CFG[k] and type(v)=='number' and v>=0 and v<math.huge and (k=='fullSoonHours' or v<=1),'invalid setting')
            CFG[k]=v;event.push('stats')
          end
          package.loaded["logistics.stats"]=stats
          package.loaded.component={transposer={getAllStacks=function() error('unexpected read') end}}
          package.loaded["logistics.warehouse"]={scan=function() error('unexpected read') end}
          package.preload["mes.alerts"]=function() return assert(load(MES_ALERTS))() end
          package.preload["mes.alert_sources"]=function() return assert(load(MES_ALERT_SOURCES))() end
          function reload()
            LISTEN={};TIMERS={};package.loaded["mes.alerts"]=nil;package.loaded["mes.alert_sources"]=nil
            alerts=require('mes.alerts');alerts.start(world)
          end
          function active(kind)
            local r=alerts.list{state='active',kind=kind};return r[1],#r
          end
          function lastEvent() return EVENTS[#EVENTS] end
          reload();resetCalls()
        ''')

    def test_all_untimed_causes_and_stock_margin(self):
        self.lua.execute('''
          emit('mes','done',8,'failed');local r=active('runFailed');assert(r and r.key==8)
          local e=lastEvent();assert(e[1]=='alert' and e[2]==r.id and e[3]=='runFailed' and e[4]=='active')
          emit('mes','done',8,'done');assert(active('runFailed'))
          assert(alerts.dismiss(r.id));assert(alerts.list('dismissed')[1].id==r.id)
          D={{name='d1',state='lost',lost=true}};emit('logistics_drone');assert(active('droneLost'))
          D[1].state='idle';D[1].lost=false;emit('logistics_drone');assert(not active('droneLost'))
          FILL=.95;emit('warehouse','changed');local r=active('stockFull');assert(r)
          for _,f in ipairs({.94,.93,.945,.95}) do FILL=f;emit('stats');assert(active('stockFull').id==r.id) end
          FILL=.929;emit('stats');assert(not active('stockFull'))
          FILL=.94;emit('stats');assert(not active('stockFull'))
          SOON=true;FILL=.1;emit('stats');assert(active('stockFull').id~=r.id)
          SOON=false;emit('stats');assert(not active('stockFull'))
          IO={{name='in',role='import',reason='stock full: 64 coal left'}};emit('io');assert(active('importBlocked'))
          IO[1].reason=nil;emit('io');assert(not active('importBlocked'))
          IO={{name='out',role='export',reason='export chest full: take items'}};emit('io');assert(active('exportFull'))
          IO[1].reason=nil;emit('io');assert(not active('exportFull'))
          assert(timerCount()==1 and not calls.read)
        ''')

    def test_dismiss_suppresses_until_clear_and_recurrence(self):
        self.lua.execute('''
          D={{name='d',state='lost'}};emit('logistics_drone');local r=active('droneLost');alerts.dismiss(r.id)
          local writes=calls.write;local events=#EVENTS
          for n=1,5 do emit('logistics_drone') end
          assert(#EVENTS==events and calls.write==writes and not active('droneLost'))
          assert(not alerts.dismiss(r.id))
          D[1].state='idle';emit('logistics_drone');assert(alerts.list('cleared')[1].id==r.id)
          D[1].state='lost';emit('logistics_drone');assert(active('droneLost').id>r.id)
          local copy=alerts.list();copy[1].state='active';assert(alerts.list()[1].state=='cleared')
        ''')

    def test_held_timer_exactly_once_and_cancelled(self):
        self.lua.execute('''
          D={{name='d',state='held'}};emit('logistics_held');assert(timerCount()==1 and TCALLS==1)
          emit('logistics');emit('logistics_work');assert(TCALLS==1)
          tick(599);assert(not active('droneHeld'));tick(600);assert(active('droneHeld') and timerCount()==0)
          emit('logistics');assert(TCALLS==1)
          D[1].state='idle';emit('logistics_released');assert(not active('droneHeld'))
          D[1].state='held';emit('logistics_held');assert(TCALLS==3 and timerCount()==2)
          tick(650);D[1].state='idle';emit('logistics_drone');assert(timerCount()==1 and CANCELS>=1)
          tick(2000);assert(not active('droneHeld'))
        ''')

    def test_machine_timer_due_change_collection_and_quarantine(self):
        self.lua.execute('''
          local load={sequence=1,due=100,duration=20,remaining={brick=1}}
          world.groups.furnace={loads={load}};emit('mes_machine');assert(timerCount()==1 and TCALLS==1)
          emit('mes_machine');assert(TCALLS==1)
          load.due=110;emit('mes_machine');assert(timerCount()==1 and TCALLS==2)
          tick(130);assert(not active('machineStuck'));tick(130.001);local r=active('machineStuck');assert(r and r.key=='furnace:1')
          load.remaining.brick=0;emit('mes_machine');assert(not active('machineStuck'))
          load.sequence=2;load.due=200;load.remaining.brick=1;emit('mes_machine');assert(timerCount()==2)
          load.quarantined=true;emit('mes_machine');assert(timerCount()==1)
          load.quarantined=nil;emit('mes_machine');tick(220.001);assert(active('machineStuck'))
          load.quarantined=true;emit('mes_machine');assert(not active('machineStuck'))
        ''')

    def test_restart_rechecks_and_dismiss_survives(self):
        self.lua.execute('''
          D={{name='gone',state='lost'},{name='persist',state='lost'},{name='hidden',state='lost'}}
          emit('logistics_drone');local ids={};for _,r in ipairs(alerts.list()) do ids[r.key]=r.id end
          alerts.dismiss(ids.hidden);D[1].state='idle';TIME=0;reload()
          assert(#alerts.list('active')==1 and active('droneLost').id==ids.persist)
          assert(alerts.list('cleared')[1].id==ids.gone and alerts.list('dismissed')[1].id==ids.hidden)
          emit('logistics_drone');assert(#alerts.list('active')==1)
          D[2].state='idle';emit('logistics_drone');assert(not active('droneLost'))
        ''')

    def test_settings_validate_persist_rearm_and_proxy(self):
        self.lua.execute('''
          for _,key in ipairs({'heldMinutes','stuckFactor','fillBad'}) do
            for _,v in ipairs({'x',false,{},-1,0/0,math.huge}) do assert(not pcall(alerts.set,key,v)) end
          end
          assert(not pcall(alerts.set,'unknown',1))
          D={{name='d',state='held'}};emit('logistics_held');alerts.set('heldMinutes',1)
          assert(timerCount()==1 and TCALLS==2);tick(60);assert(active('droneHeld'))
          alerts.set('stuckFactor',2);alerts.set('fillBad',.7)
          assert(alerts.settings().fillBad==.7);FILL=.8;emit('stats');assert(active('stockFull'))
          local copy=alerts.settings();copy.heldMinutes=100;assert(alerts.settings().heldMinutes==1)
          TIME=0;reload();assert(alerts.settings().heldMinutes==1 and alerts.settings().stuckFactor==2)
          assert(active('droneHeld') and timerCount()==0)
        ''')

    def test_retention_cap_and_active_exemption(self):
        self.lua.execute('''
          for n=1,205 do D[n]={name='d'..n,state='lost'} end;emit('logistics_drone')
          assert(#alerts.list('active')==205)
          for n=1,5 do alerts.dismiss(n) end
          assert(#alerts.list()==200 and #alerts.list('active')==200)
          emit('logistics_drone');assert(#alerts.list()==200)
          reload();emit('logistics_drone');assert(#alerts.list()==200)
          local saved=require('logistics.store').open('/etc/mes.alerts','log'):load().state
          local suppressed=0;for _ in pairs(saved.quiet) do suppressed=suppressed+1 end;assert(suppressed==5)
          for n=1,5 do D[n].state='idle' end;emit('logistics_drone')
          saved=require('logistics.store').open('/etc/mes.alerts','log'):load().state;assert(not next(saved.quiet))
          D[206]={name='new',state='lost'};emit('logistics_drone');assert(#alerts.list('active')==201)
          D[206].state='idle';emit('logistics_drone');assert(#alerts.list()==200)
          assert(timerCount()==0)
        ''')

    def test_five_hundred_failed_runs_keep_history_bounded(self):
        self.lua.execute('''
          for n=1,500 do
            emit('mes','done',n,'failed');local r=active('runFailed');assert(r.key==n)
            assert(alerts.dismiss(r.id));assert(#alerts.list()<=200)
          end
          local saved=require('logistics.store').open('/etc/mes.alerts','log'):load().state
          assert(#saved.rows==200 and not next(saved.quiet) and saved.serial==500)
          local count=0
          for n=1,100 do local name,value=debug.getupvalue(alerts.start,n);if not name then break end
            if name=='index' then for _ in pairs(value) do count=count+1 end end
          end
          assert(count==200 and #alerts.list('dismissed')==200)
          reload();assert(#alerts.list()==200 and not active('runFailed'))
          emit('mes','done',501,'failed');assert(active('runFailed').key==501 and #alerts.list()==200)
          assert(timerCount()==0)
        ''')

    def test_pruning_old_clear_keeps_recurring_incident_indexed(self):
        self.lua.execute('''
          D={{name='d',state='lost'}};emit('logistics_drone')
          D[1].state='idle';emit('logistics_drone');D[1].state='lost';emit('logistics_drone')
          local id=active('droneLost').id
          for n=1,200 do emit('mes','done',n,'failed') end
          emit('logistics_drone');local r,count=active('droneLost')
          assert(r.id==id and count==1 and #alerts.list('cleared')==0)
        ''')

    def test_cleared_records_pruned_after_one_day(self):
        self.lua.execute('''
          D={{name='d',state='lost'}};emit('logistics_drone');D[1].state='idle';emit('logistics_drone')
          TIME=86399;assert(#alerts.list()==1);TIME=86400;assert(#alerts.list()==0)
          assert(timerCount()==0)
        ''')

    def test_dismissal_history_survives_clear_and_rebased_restart(self):
        self.lua.execute('''
          TIME=20;D={{name='d',state='lost'}};emit('logistics_drone');local id=active('droneLost').id
          TIME=30;alerts.dismiss(id);D[1].state='idle';TIME=40;emit('logistics_drone')
          local r=alerts.list('cleared')[1];assert(r.dismissed==true and r.raised==20 and r.cleared==40)
          TIME=5;reload();r=alerts.list('cleared')[1]
          assert(r.id==id and r.dismissed==true and r.raised==-15 and r.cleared==5)
        ''')

    def test_failed_run_subject_is_persisted_without_reads(self):
        self.lua.execute('''
          TIME=20;emit('mes','done','0123456789abcdef0123456789abcdef','failed','minecraft:torch:0')
          local r=active('runFailed');assert(r.text=='Run failed: minecraft:torch:0' and r.item=='minecraft:torch:0')
          TIME=30;alerts.dismiss(r.id);TIME=5;reload();r=alerts.list('dismissed')[1]
          assert(r.text=='Run failed: minecraft:torch:0' and r.item=='minecraft:torch:0' and r.raised==-5)
        ''')

    def test_machine_fields_are_separate_and_restart_preserves_identity(self):
        self.lua.execute('''
          TIME=50;world.groups['furnace:west']={loads={{sequence=7,due=30,duration=10,remaining={brick=1}}}}
          emit('mes_machine');local r=active('machineStuck')
          assert(r.key=='furnace:west:7' and r.machine=='furnace:west' and r.load==7)
          TIME=60;alerts.dismiss(r.id);TIME=5;reload();r=alerts.list('dismissed')[1]
          assert(r.machine=='furnace:west' and r.load==7 and r.key=='furnace:west:7' and r.raised==-5)
        ''')

    def test_one_shot_expiry_uses_earliest_clear_and_rearms_on_restart(self):
        self.lua.execute('''
          assert(timerCount()==0)
          D={{name='a',state='lost'},{name='b',state='lost'}};emit('logistics_drone')
          TIME=10;D[1].state='idle';emit('logistics_drone');assert(timerCount()==1 and TCALLS==1)
          TIME=20;D[2].state='idle';emit('logistics_drone');assert(timerCount()==1 and TCALLS==1)
          alerts.list();emit('logistics_drone');assert(TCALLS==1)
          tick(86409);assert(#EVENTS==4 and timerCount()==1)
          tick(86410);assert(lastEvent()[4]=='removed' and timerCount()==1 and TCALLS==2)
          local saved=require('logistics.store').open('/etc/mes.alerts','log'):load().state
          assert(#saved.rows==1 and saved.rows[1].key=='b')
          TIME=5;reload();assert(timerCount()==1 and TCALLS==3)
          local t=TIMERS[next(TIMERS)];assert(t.at==15)
          tick(14);assert(timerCount()==1);tick(15)
          assert(lastEvent()[4]=='removed' and timerCount()==0)
          saved=require('logistics.store').open('/etc/mes.alerts','log'):load().state;assert(#saved.rows==0)
          assert(#alerts.list()==0 and timerCount()==0)
          reload();assert(timerCount()==0)
        ''')

    def test_alert_ranges_name_key_units_and_survive_restart(self):
        self.lua.execute('''
          for _,v in ipairs({0,.5,1.5}) do local ok,why=pcall(alerts.set,'heldMinutes',v)
            assert(not ok and why:find('heldMinutes must be a whole number of minutes >= 1',1,true)) end
          for _,v in ipairs({0,-1,math.huge,0/0}) do local ok,why=pcall(alerts.set,'stuckFactor',v)
            assert(not ok and why:find('stuckFactor must be a finite multiplier > 0',1,true)) end
          alerts.set('heldMinutes',2);alerts.set('stuckFactor',.5)
          TIME=20;D={{name='d',state='lost'}};emit('logistics_drone');TIME=5;reload()
          assert(alerts.settings().heldMinutes==2 and alerts.settings().stuckFactor==.5)
          assert(active('droneLost').raised==5)
        ''')

    def test_setting_owners_are_detached_and_survive_restart(self):
        self.lua.execute('''
          local o=alerts.owners();assert(o.heldMinutes=='alerts' and o.stuckFactor=='alerts')
          assert(o.fillWarn=='stats' and o.fillBad=='stats' and o.fullSoonHours=='stats')
          o.heldMinutes='bad';assert(alerts.owners().heldMinutes=='alerts')
          TIME=20;D={{name='d',state='lost'}};emit('logistics_drone');TIME=5;reload()
          assert(alerts.owners().fillBad=='stats' and active('droneLost').raised==5)
        ''')

    def test_removed_signals_for_expiry_and_evicted_quiet_clear_after_restart(self):
        self.lua.execute('''
          TIME=20;D={{name='d',state='lost'}};emit('logistics_drone');local id=active('droneLost').id
          TIME=30;D[1].state='idle';emit('logistics_drone');TIME=5;reload()
          assert(alerts.list('cleared')[1].raised==-5)
          TIME=86405;assert(#alerts.list()==0);local e=lastEvent();assert(e[2]==id and e[4]=='removed')
          D={};for n=1,201 do D[n]={name='d'..n,state='lost'} end;emit('logistics_drone')
          local old=alerts.list()[1];assert(alerts.dismiss(old.id));e=lastEvent();assert(e[2]==old.id and e[4]=='removed')
          TIME=5;reload();EVENTS={};D[1].state='idle';emit('logistics_drone')
          local found=false;for _,v in ipairs(EVENTS) do if v[2]==old.id then assert(v[4]=='removed');found=true end end
          assert(found and #alerts.list{ id=old.id }==0)
        ''')


class AlertSignalTests(unittest.TestCase):
    def test_machine_callback_only_on_membership_due_or_quarantine_change(self):
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.globals().STATE=Path('craftsystem/usr/lib/mes/state.lua').read_text()
        lua.execute('''
          package.preload.item_identity=function() return {} end
          package.preload["mes.timing"]=function() return {} end
          local M=assert(load(STATE))();local visited={}
          local function search(f)
            if visited[f] then return end;visited[f]=true
            for n=1,100 do local k,v=debug.getupvalue(f,n);if not k then break end
              if k=='publish' then return v end
              if type(v)=='function' then local found=search(v);if found then return found end end
            end
          end
          local publish;for _,f in pairs(M) do if type(f)=='function' then publish=publish or search(f) end end
          assert(publish);local signals=0
          local w={machines={m={state='idle'}},onMachine=function(n) assert(n=='m');signals=signals+1 end}
          local g={name='m',loads={},quarantined={}}
          publish(w,g);assert(signals==0)
          local l={sequence=1,record={}};g.loads={l};publish(w,g);assert(signals==1)
          publish(w,g);assert(signals==1)
          l.due=10;publish(w,g);assert(signals==2)
          publish(w,g);assert(signals==2)
          g.loads[2]={sequence=2,due=20,record={}};publish(w,g);assert(signals==3)
          l.quarantined=true;publish(w,g);assert(signals==4)
          table.remove(g.loads,1);publish(w,g);assert(signals==5)
          g.loads={};publish(w,g);assert(signals==6)
          publish(w,g);assert(signals==6 and package.loaded.event==nil)
        ''')

    def test_logistics_lost_ready_found_release_emit_only_on_transition(self):
        import test_logistics_restart
        lua=test_logistics_restart.LogisticsRestartTests().start('log')
        lua.execute('''
          local n=0;LISTEN.logistics_drone={function(_,name,state) assert(name=='d1');n=n+1 end}
          report(0,{state='ready',held=0});drain();assert(n==0)
          report(0,{state='ready',notAtHome=true});drain();assert(n==1)
          report(0,{state='ready',notAtHome=true});drain();assert(n==1)
          assert(lg.found('d1'));drain();assert(n==2)
          report(0,{state='ready',held=0});drain();assert(n==3)
          report(0,{state='ready',held=0});drain();assert(n==3)
          LISTEN.logistics_held={}
          report(0,{state='ready',held=1,cargo={{name='mod:stock',damage=0,size=1,maxSize=64}}});drain();assert(n==4)
          assert(lg.release('d1'));drain();assert(n==5)
          report(0,{state='ready',held=0});drain();assert(n==5)
        ''')


if __name__=='__main__':
    unittest.main()
