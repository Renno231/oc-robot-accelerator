"""HK facts, one-shot idle clock and between-tour pre-emption."""
from pathlib import Path
import unittest
from lupa.lua53 import LuaRuntime
from test_store import install_store


class HousekeepingTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        install_store(self.lua)
        self.lua.globals().HK = Path('drone-logistics/usr/lib/logistics/housekeeping.lua').read_text()
        self.lua.execute('''
          local serial={};local seq=0
          local function clone(v) if type(v)~='table' then return v end;local t={};for k,x in pairs(v) do t[k]=clone(x) end;return t end
          package.loaded.serialization={serialize=function(t) seq=seq+1;local s=tostring(seq);serial[s]=clone(t);return s end,
            unserialize=function(s) return clone(serial[s]) end}
          -- A structural serializer makes unchanged snapshots compare equal.
          local ser=package.loaded.serialization
          local function key(t) if type(t)~='table' then return tostring(t) end
            local ks={};for k in pairs(t) do ks[#ks+1]=k end;table.sort(ks,function(a,b) return tostring(a)<tostring(b) end)
            local s='{';for _,k in ipairs(ks) do s=s..tostring(k)..'='..key(t[k])..';' end;return s..'}' end
          ser.serialize=function(t) local s=key(t);serial[s]=clone(t);return s end
          TIME=0;TIMERS={};NEXT=0;EVENTS={};LISTEN={};JOBS={};RUNS={};ROWS={};COLLECTS={};SETTLED=true
          FLEET={{state='idle',cargoSlots=4},{state='idle',cargoSlots=4}}
          package.loaded.computer={uptime=function() return TIME end}
          package.loaded.event={listen=function(n,f) LISTEN[n]=f end,push=function(...) EVENTS[#EVENTS+1]={...} end,
            timer=function(delay,f,n) assert(n==1);NEXT=NEXT+1;TIMERS[NEXT]={at=TIME+delay,f=f};return NEXT end,
            cancel=function(id) TIMERS[id]=nil end}
          function emit(n) LISTEN[n]() end
          function advance(n) TIME=TIME+n;local due={};for id,t in pairs(TIMERS) do if t.at<=TIME then due[#due+1]=id end end
            for _,id in ipairs(due) do local t=TIMERS[id];TIMERS[id]=nil;t.f() end end
          function timers() local n=0;for _ in pairs(TIMERS) do n=n+1 end;return n end
          local lg={drones=function() return FLEET end,jobs=function() local t={};for id,j in pairs(JOBS) do j.id=id;t[#t+1]=j end;return t end,
            status=function(id) return JOBS[id] end,plan=function() return {} end,
            cancel=function(id) JOBS[id].state='failed';return true end}
          package.loaded.logistics=lg
          package.loaded["mes.service"]={runs=function() return RUNS end}
          package.loaded["logistics.stats"]={settings=function() return {fillWarn=.8} end,summary=function()
            local t={};for _,fs in pairs(ROWS) do t[#t+1]={name=fs[1].storage,fill=1-fs[1].entry.freeSlots/fs[1].entry.slots} end;return {perStorage=t} end}
          package.loaded["logistics.warehouse"]={entries=function() return clone(ROWS) end,inflight=function() return {} end,
            settled=function() return SETTLED end,stackSize=function() return 64 end,
            collect=function(from,rs,opts) assert(opts.oneTour);COLLECTS[#COLLECTS+1]={from=from,rs=clone(rs)}
              local id=#COLLECTS;JOBS[id]={state='queued',moved=0,trips=0};return {id} end}
          function row(n,count,stacks,room,filter,max)
            return {{storage=n,key=n,settings={filter=filter},entry={slots=4,freeSlots=4-stacks,
              items={coal={item={name='coal',damage=0},count=count,stacks=stacks,room=room,maxSize=max or 64}}}}} end
          function boot() hk=assert(load(HK))() end
        ''')

    def test_continuous_idle_and_one_timer(self):
        self.lua.execute('''boot();assert(timers()==1)
          for i=1,20 do emit('warehouse') end;assert(timers()==1)
          advance(20);RUNS={{status='running'}};emit('mes');assert(timers()==0)
          RUNS={};emit('mes');advance(29);assert(#COLLECTS==0 and timers()==1)
          advance(1);assert(timers()==0 and hk.status().reason=='no worthwhile move')
        ''')

    def test_gain_and_packed_items_no_read(self):
        self.lua.execute('''ROWS={a=row('a',32,2,96),b=row('b',32,1,32)}
          ROWS.a[1].entry.items.iron={item={name='iron',damage=0},count=16,stacks=2,room=112,maxSize=64}
          ROWS.b[1].entry.items.iron={item={name='iron',damage=0},count=48,stacks=1,room=16,maxSize=64}
          boot();hk.set('minFill',0);advance(30)
          assert(#COLLECTS==1 and COLLECTS[1].from=='a' and #COLLECTS[1].rs==2)
          assert(hk.status().estimatedGain==4 and timers()==0)
        ''')

    def test_low_fill_and_filtered_zero_gain(self):
        self.lua.execute('''ROWS={a=row('a',64,1,0),b=row('b',0,0,0,{{name='coal',damage=0}})}
          boot();advance(30);assert(#COLLECTS==0)
          hk.set('minFill',0);assert(#COLLECTS==1 and hk.status().kind=='sort' and hk.status().estimatedGain==0)
        ''')

    def test_real_work_preempts_queued_then_active_boundary(self):
        self.lua.execute('''ROWS={a=row('a',32,2,96),b=row('b',32,1,32)}
          boot();hk.set('minFill',0);advance(30);RUNS={{status='running'}};emit('mes')
          assert(JOBS[1].state=='failed' and hk.status().phase=='paused')
          emit('logistics');assert(hk.status().job==nil and #COLLECTS==1)
          RUNS={};emit('mes');advance(30);assert(#COLLECTS==2)
          JOBS[2].state='active';RUNS={{status='running'}};emit('mes')
          assert(JOBS[2].state=='active');JOBS[2]={state='done',moved=32,trips=1}
          SETTLED=false;emit('logistics');assert(hk.status().job==2)
          SETTLED=true;emit('warehouse');assert(hk.status().job==nil and hk.status().moved==32 and #COLLECTS==2)
        ''')

    def test_noop_settings_zero_writes_events_and_private_copy(self):
        self.lua.execute('''boot();local n=#EVENTS;resetCalls();hk.set('enabled',true)
          assert(#EVENTS==n and not calls.write);local c=hk.settings();c.enabled=false;assert(hk.settings().enabled)
          local ok=pcall(hk.set,'minFill',2);assert(not ok)
          hk.set('enabled',false);assert(hk.status().phase=='off' and timers()==0)
        ''')

    def test_restart_does_not_replay_queued_tour(self):
        self.lua.execute('''ROWS={a=row('a',32,2,96),b=row('b',32,1,32)}
          boot();hk.set('minFill',0);advance(30);assert(#COLLECTS==1)
          RUNS={{status='running'}};boot();assert(JOBS[1].state=='failed' and #COLLECTS==1)
          assert(hk.settings().minFill==0)
        ''')

    def test_delay_setting_rearms_and_default_seed_is_independent(self):
        self.lua.execute('''boot();hk.set('idleSeconds',10);advance(10)
          assert(timers()==0 and hk.status().reason=='no worthwhile move')
          package.loaded["logistics.stats"].settings=function() return {fillWarn=.1} end
          boot();assert(hk.settings().minFill==.8)
        ''')

    def test_sixteen_stack_alias_and_matching_filter_protection(self):
        self.lua.execute('''ROWS={a=row('a',8,2,24,nil,16),b=row('b',8,1,8,nil,16)}
          ROWS.a[2]=ROWS.a[1];boot();hk.set('minFill',0);advance(30)
          assert(#COLLECTS==1 and #COLLECTS[1].rs==1 and hk.status().estimatedGain==2)
        ''')
        self.setUp()
        self.lua.execute('''ROWS={a=row('a',8,2,24,{{name='coal',damage=0}},16),b=row('b',64,4,0,nil,16)}
          boot();hk.set('minFill',0);advance(30);assert(#COLLECTS==0)
        ''')


if __name__ == '__main__':
    unittest.main()
