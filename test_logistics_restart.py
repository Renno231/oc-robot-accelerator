"""Controller reloads on the same disk while physical fake drones keep running."""
from pathlib import Path
import unittest

from lupa.lua53 import LuaRuntime
import test_stock_api
from test_store import install_store


class LogisticsRestartTests(unittest.TestCase):
    def start(self, mode, item_name='mod:stock'):
        fixture = test_stock_api.LibraryApiTests()
        fixture.setUp()
        fixture.load('map', 'map')
        lua = fixture.lua
        install_store(lua, preserve_io=True)
        lua.globals().MODE = mode
        lua.globals().ITEM_NAME = item_name
        lua.globals().LOGISTICS = Path('drone-logistics/usr/lib/logistics/init.lua').read_text()
        lua.globals().WAREHOUSE = Path('drone-logistics/usr/lib/logistics/warehouse.lua').read_text()
        lua.execute('''
          variant(MODE);TIME=10;LISTEN={};EVENTS={};SENT={};TIMERS={}
          FAKE={cargo={},stock=10,dest=0,working=false}
          item={name=ITEM_NAME,damage=0,label='Stock'}
          package.loaded["logistics.map"]=map
          map.add('home',0,0,0);map.add('source',2,0,0);map.add('dest',4,0,0)
          map.link('home','source');map.link('source','dest') -- Straight-line fixture graph.
          map.name('stock','source',0);map.name('out','dest',0)
          map.theta=function(a,b) return {a,b} end
          files['/usr/lib/logistics/drone/agent.lua']='return true'
          files['/etc/logistics.drones']=require('serialization').serialize({
            d1={address='remote',token='secret',home='home'}})
          files['/etc/warehouse.cfg']=require('serialization').serialize({members={stock={}},groups={}})
          package.loaded.computer={uptime=function() return TIME end}
          package.loaded.event={
            timer=function(seconds,fn) TIMERS[#TIMERS+1]={at=TIME+seconds,fn=fn};return #TIMERS end,
            listen=function(name,fn) LISTEN[name]=LISTEN[name] or {};table.insert(LISTEN[name],fn) end,
            push=function(...) EVENTS[#EVENTS+1]={...} end}
          function emit(name,...)
            for _,fn in ipairs(LISTEN[name] or {}) do fn(name,...) end
          end
          function drain()
            while #EVENTS>0 do local e=table.remove(EVENTS,1);emit(table.unpack(e)) end
          end
          function advance(seconds)
            TIME=TIME+seconds
            for _,t in ipairs(TIMERS) do if not t.fired and TIME>=t.at then t.fired=true;t.fn() end end
          end
          package.loaded.event.pull=function(filter)
            assert(filter=='logistics_released','release must not pull events')
            while true do
              for i,e in ipairs(EVENTS) do if e[1]==filter then table.remove(EVENTS,i);return table.unpack(e) end end
              advance(5)
            end
          end
          function report(id,result)
            result.energy=5000;result.position={x=0,y=0,z=0};result.cargoSlots=4
            emit('modem_message','local','remote',27103,0,'secret','report',id,
              require('serialization').serialize(result))
          end
          require('component').modem.send=function(address,port,token,kind,id,payload)
            SENT[#SENT+1]={kind=kind,id=id,payload=payload}
            if kind=='trip' then
              assert(not FAKE.working);FAKE.working=true;FAKE.trip=id
              FAKE.task=require('serialization').unserialize(payload);FAKE.last=nil
            elseif kind=='release' then
              FAKE.last=nil
              if not FAKE.releaseSilent then
                emit('modem_message','local','remote',port,0,token,'cargo',id,
                  require('serialization').serialize(FAKE.cargo))
              end
            end
          end
          package.preload.logistics=function() return assert(load(LOGISTICS))() end
          package.preload["logistics.warehouse"]=function() return assert(load(WAREHOUSE))() end
          function reload()
            LISTEN={};EVENTS={};SENT={};TIMERS={}
            package.loaded.logistics=nil;package.loaded["logistics.warehouse"]=nil
            lg=require('logistics');wh=require('logistics.warehouse')
            assert(#SENT==1 and SENT[1].kind=='status')
          end
          function ready()
            report(0,{state='ready',freeMemory=32000,held=FAKE.held or 0,
              cargo=next(FAKE.cargo) and FAKE.cargo or nil})
          end
          function answerStatus()
            if FAKE.working then return end
            if FAKE.last then report(FAKE.last.id,clone(FAKE.last.result)) end
            ready()
          end
          function finishPhysical(deliver)
            assert(FAKE.working);local rows={};local carried=FAKE.held or 0
            for i,s in ipairs(FAKE.task.steps or {}) do
              local n=s.count or (s.rest and carried) or 0;rows[i]={moved=n,maxSize=64}
              if s.take then rows[i].taken=n;FAKE.stock=FAKE.stock-n;carried=carried+n end
              if s.put then
                if s.put.node=='source' then FAKE.stock=FAKE.stock+n else FAKE.dest=FAKE.dest+n end
                carried=carried-n
              end
            end
            FAKE.working=false;FAKE.held=0;FAKE.cargo={}
            FAKE.last={id=FAKE.trip,result={state='idle',steps=rows,held=0}}
            if deliver then report(FAKE.last.id,clone(FAKE.last.result));drain() end
          end
          local catalogue=require('logistics.store').open('/etc/warehouse.db','log');catalogue:load()
          catalogue:put('stock',{items={seed={item=item,count=10,maxSize=64,stacks=1,room=54}},
            slots=27,freeSlots=26,verified=true,time=TIME});catalogue:flush();catalogue:close()
          reload();ready();drain();SENT={}
          function fetch()
            local id=assert(wh.fetch(item,4,'out',{split=false}));drain()
            assert(lg.status(id).state=='active' and FAKE.working);return id
          end
        ''')
        return lua

    def test_lost_final_report_replayed_after_restart_catalogue_once(self):
        for mode in ('log', 'files'):
            with self.subTest(mode=mode):
                self.start(mode).execute('''
                  local id=fetch();LISTEN={};EVENTS={}
                  finishPhysical(true) -- Drone finishes with no controller listening.
                  assert(FAKE.stock==6 and FAKE.dest==4)
                  TIME=1;reload();assert(not wh.settled(id))
                  answerStatus();drain()
                  local s=lg.status(id)
                  assert(s.state=='done' and s.moved==4 and s.trips==1)
                  assert(s.steps[1].taken==4 and s.tripTimings[1].startedAt==nil)
                  assert(s.tripTimings[1].finishedAt==1)
                  assert(wh.count(item)==FAKE.stock and wh.settled(id))
                  answerStatus();drain();assert(wh.count(item)==6 and lg.status(id).trips==1)
                  reload();answerStatus();drain();assert(wh.count(item)==6)
                ''')

    def test_drone_still_working_at_restart_reports_normally(self):
        for mode in ('log', 'files'):
            with self.subTest(mode=mode):
                self.start(mode).execute('''
                  local id=fetch();TIME=1;reload();answerStatus();drain()
                  assert(FAKE.working and lg.drones()[1].state=='working' and #SENT==1)
                  assert(lg.status(id).tripTimings[1].startedAt==nil)
                  finishPhysical(true)
                  assert(lg.status(id).state=='done' and lg.status(id).moved==4)
                  assert(wh.count(item)==6 and wh.settled(id))
                ''')

    def test_orphan_held_status_creates_one_delivery_to_stock(self):
        for mode in ('log', 'files'):
            with self.subTest(mode=mode):
                self.start(mode).execute('''
                  FAKE.held=3;FAKE.cargo={[2]={name=item.name,damage=0,label='Stock',size=3,maxSize=64}}
                  reload();answerStatus();drain()
                  local jobs=lg.jobs();assert(#jobs==1 and FAKE.working)
                  local id=jobs[1].id
                  assert(FAKE.task.cargo and #FAKE.task.steps==1 and FAKE.task.steps[1].put.node=='source')
                  assert(FAKE.task.steps[1].count==3)
                  ready();drain();assert(#lg.jobs()==1) -- Reserved holder must not be submitted twice.
                  finishPhysical(true)
                  assert(lg.status(id).state=='done' and wh.count(item)==13 and FAKE.stock==13)
                ''')

    def test_boot_ready_lists_current_inventory(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.globals().AGENT = Path('drone-logistics/usr/lib/logistics/drone/agent.lua').read_text()
        lua.execute('''
          local drone={inventorySize=function() return 4 end,count=function(i) return i==1 and 3 or 0 end,
            getAcceleration=function() return 2 end,getMaxVelocity=function() return 8 end,
            getOffset=function() return 0 end}
          local inv={getStackInInternalSlot=function(i)
            if i==1 then return {name='minecraft:coal',damage=0,size=3,maxSize=64} end
          end}
          component={list=function(kind) return function() return kind end end,
            proxy=function(kind) return kind=='drone' and drone or inv end}
          computer={energy=function() return 5000 end,freeMemory=function() return 32000 end,
            pullSignal=function(timeout) assert(timeout==nil,'idle drone must wait for a signal');return coroutine.yield() end}
          local ready
          local modem={send=function(_,_,_,kind,id,payload)
            if kind=='report' then ready=assert(load('return '..payload))() end
          end}
          local agent=coroutine.create(assert(load(AGENT)))
          local ok,err=coroutine.resume(agent,modem,'token','controller','d1',27103,0,0,0)
          assert(ok,err);assert(ready.state=='ready' and ready.held==3 and ready.cargo[1].size==3)
        ''')

    def test_lingering_read_hands_its_drone_the_next_job(self):
        self.start('log').execute('''
          local function lingeringRead()
            local id=lg.job({{read='out'}},{drones=1,retries=0,linger=true});drain()
            assert(FAKE.working and FAKE.task.linger==8);FAKE.working=false
            report(FAKE.trip,{state='idle',steps={{moved=0,listing={},size=27}},held=0,lingering='dest'});drain()
            assert(lg.status(id).state=='done');return id
          end
          lingeringRead()
          local d=lg.drones()[1];assert(d.state=='idle' and d.node=='dest')
          -- The next job starts where the drone waits, not at its charger.
          assert(wh.fetch(item,4,'out',{split=false}));drain()
          assert(FAKE.working and FAKE.task.routes.take[1].name=='dest' and not FAKE.task.linger)
          finishPhysical(true);assert(lg.drones()[1].node=='home')
          -- Past the window the drone is flying home: no work until it is back.
          lingeringRead();advance(6)
          assert(wh.fetch(item,2,'out',{split=false}));drain()
          assert(not FAKE.working and lg.drones()[1].state=='returning')
          ready();drain()
          assert(FAKE.working and FAKE.task.routes.take[1].name=='home')
          finishPhysical(true)
          -- A scan of several storages lingers between reads; one storage does not.
          assert(#wh.scan({'stock','out'})==2);drain()
          assert(FAKE.working and FAKE.task.linger==8)
        ''')

    def test_single_storage_scan_goes_home(self):
        self.start('log').execute('''
          wh.scan('out');drain()
          assert(FAKE.working and not FAKE.task.linger)
        ''')

    def test_agent_lingers_then_continues_or_retraces_home(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.globals().AGENT = Path('drone-logistics/usr/lib/logistics/drone/agent.lua').read_text()
        lua.execute('''
          local T,WAITS,REPORTS,NAV=0,{},{},nil
          local drone={inventorySize=function() return 4 end,count=function() return 0 end,
            getAcceleration=function() return 2 end,getMaxVelocity=function() return 8 end,
            getOffset=function() return 0 end,getVelocity=function() return 0 end,move=function() end}
          local inv={getStackInInternalSlot=function() end,getInventorySize=function() return 27 end,
            getStackInSlot=function() end}
          component={list=function(kind) return function() return kind end end,
            proxy=function(kind) return kind=='drone' and drone or inv end}
          computer={energy=function() return 5000 end,freeMemory=function() return 32000 end,uptime=function() return T end,
            pullSignal=function(timeout) WAITS[#WAITS+1]=timeout or 'none';return coroutine.yield() end}
          local modem={send=function(_,_,_,kind,id,payload)
            if kind=='report' then REPORTS[#REPORTS+1]=assert(load('return '..payload))() end
            if kind=='navigate' then NAV=assert(load('return '..payload))() end
          end}
          local points={home={name='home',x=0,y=0,z=0},chest={name='chest',x=2,y=0,z=0}}
          local agent=coroutine.create(assert(load(AGENT)))
          local function resume(...)
            assert(coroutine.resume(agent,...))
            while NAV do local n=NAV;NAV=nil
              local route='{route={{name="'..n.from..'",x='..points[n.from].x..',y=0,z=0},{name="'..n.to..'",x='..points[n.to].x..',y=0,z=0}}}'
              assert(coroutine.resume(agent,'modem_message','local','controller',27103,0,'token','navigation',ACTIVE,route))
            end
          end
          local function trip(id,linger)
            ACTIVE=id
            resume('modem_message','local','controller',27103,0,'token','trip',id,
              '{steps={{read={node="chest",side=0}}},home="home",reserve=100,'..(linger and 'linger=8,' or '')..
              'routes={take={{name="home",x=0,y=0,z=0}}}}')
            return REPORTS[#REPORTS]
          end
          resume(modem,'token','controller','d1',27103,0,0,0)
          local r=trip(1,true);assert(r.lingering=='chest' and WAITS[#WAITS]==8)
          -- A trip while lingering starts at the chest and ends at home.
          r=trip(2);assert(not r.lingering and r.position.x==0 and WAITS[#WAITS]=='none')
          r=trip(3,true);assert(r.lingering=='chest' and r.position.x==2)
          -- No trip in time: retrace the flown path home and report ready there.
          T=9;resume()
          r=REPORTS[#REPORTS];assert(r.state=='ready' and not r.notAtHome and r.position.x==0 and WAITS[#WAITS]=='none')
        ''')

    def test_boot_offset_mismatch_stays_lost_until_found(self):
        for offset in (0.02, 0.2):
            with self.subTest(offset=offset):
                lua = self.start('log')
                lua.globals().OFFSET = offset
                lua.execute('''
                  report(0,{state='ready',notAtHome=true,offset=OFFSET})
                  local d=lg.drones()[1];assert(d.state=='lost')
                  assert(lg.found('d1'));ready();assert(lg.drones()[1].state=='idle')
                ''')
                agent = LuaRuntime(unpack_returned_tuples=True)
                agent.globals().AGENT = Path('drone-logistics/usr/lib/logistics/drone/agent.lua').read_text()
                agent.globals().OFFSET = offset
                agent.execute('''
                  local drone={inventorySize=function() return 4 end,count=function() return 0 end,
                    getAcceleration=function() return 2 end,getMaxVelocity=function() return 8 end,
                    getOffset=function() return OFFSET end,getLightColor=function() return 0 end,
                    setLightColor=function() end,setStatusText=function() end}
                  component={list=function(kind) return function() return kind end end,
                    proxy=function(kind) return kind=='drone' and drone or
                      {getStackInInternalSlot=function() end} end}
                  computer={energy=function() return 5000 end,pullSignal=function() return coroutine.yield() end}
                  local report
                  local modem={send=function(_,_,_,kind,id,payload)
                    if kind=='report' then report=assert(load('return '..payload))() end
                  end}
                  local thread=coroutine.create(assert(load(AGENT)))
                  assert(coroutine.resume(thread,modem,'token','controller','d1',27103,0,0,0))
                  assert(report.state=='ready' and report.notAtHome==true and report.offset==OFFSET)
                  assert(coroutine.status(thread)=='suspended')
                ''')

    def test_lost_found_fresh_ready_returns_only_remaining_cargo(self):
        for mode in ('log', 'files'):
            with self.subTest(mode=mode):
                self.start(mode, 'minecraft:coal').execute('''
                  local id=fetch();FAKE.stock=6;FAKE.held=4
                  FAKE.cargo={{name=item.name,damage=0,size=4,maxSize=64}}
                  report(FAKE.trip,{state='progress',steps={{taken=4,moved=4}},held=4,
                    cargo={{item=item,count=4}}})
                  emit('modem_message','local','remote',27103,0,'secret','boot')
                  FAKE.working=false;report(0,{state='lost',cargo=FAKE.cargo});drain()
                  assert(lg.status(id).state=='failed' and wh.count(item)==6)
                  FAKE.held=3;FAKE.cargo[1].size=3 -- Player removed one while carrying it.
                  assert(lg.found('d1'));report(0,{state='ready',held=3,cargo=FAKE.cargo});drain()
                  assert(lg.drones()[1].held[1].count==3)
                  assert(FAKE.working and FAKE.task.cargo)
                  finishPhysical(true)
                  assert(FAKE.stock==9 and wh.count(item)==9 and FAKE.held==0)
                ''')

    def test_release_returns_before_report_and_signals_listing(self):
        self.start('log').execute('''
          FAKE.held=3;FAKE.cargo={{name=item.name,damage=0,size=3,maxSize=64}}
          ready();EVENTS={};FAKE.releaseSilent=true
          local before=TIME;assert(lg.release('d1')==true and TIME==before)
          assert(lg.drones()[1].releasePending and lg.drones()[1].cargo==nil)
          local id=SENT[#SENT].id
          emit('modem_message','local','remote',27103,0,'secret','cargo',id,
            require('serialization').serialize(FAKE.cargo))
          local _,name,state=require('event').pull('logistics_released')
          assert(name=='d1' and state=='ok' and lg.drones()[1].cargo[1].size==3)
          assert(not lg.drones()[1].releasePending)
          EVENTS={};advance(5);assert(#EVENTS==0)
        ''')

    def test_release_timeout_late_report_and_second_release(self):
        self.start('log').execute('''
          FAKE.held=1;FAKE.cargo={{name=item.name,damage=0,size=1,maxSize=64}}
          ready();EVENTS={};FAKE.releaseSilent=true
          assert(lg.release('d1'));local old=SENT[#SENT].id
          local ok,err=lg.release('d1');assert(not ok and err=='release already pending')
          advance(4.9);assert(lg.drones()[1].releasePending and #EVENTS==0)
          advance(.1);assert(not lg.drones()[1].releasePending)
          local _,name,state=require('event').pull('logistics_released');assert(name=='d1' and state=='timeout')
          emit('modem_message','local','remote',27103,0,'secret','cargo',old,
            require('serialization').serialize(FAKE.cargo))
          assert(lg.drones()[1].cargo==nil and #EVENTS==0)
          assert(lg.release('d1'));assert(SENT[#SENT].id==old+1)
          emit('modem_message','local','remote',27103,0,'secret','cargo',old,
            require('serialization').serialize(FAKE.cargo))
          assert(lg.drones()[1].releasePending and lg.drones()[1].cargo==nil and #EVENTS==0)
        ''')

    def test_release_cli_prints_listing_and_timeout(self):
        lua=self.start('log')
        lua.globals().CLI=Path('drone-logistics/usr/bin/logistics.lua').read_text()
        lua.execute(r'''
          FAKE.held=3;FAKE.cargo={{name=item.name,damage=0,size=3,maxSize=64}}
          ready();EVENTS={};PRINTED={};print=function(s) PRINTED[#PRINTED+1]=s end
          EVENTS[1]={'logistics_released','other','timeout'}
          assert(load(CLI))('release','d1')
          assert(require('serialization').unserialize(PRINTED[1])[1].size==3)
          assert(TIME==10)
          EVENTS={};FAKE.releaseSilent=true;local err
          io.stderr={write=function(_,...) err=table.concat({...}) end}
          assert(load(CLI))('release','d1')
          assert(err=='cargo report timeout\n' and #PRINTED==1 and TIME==15)
        ''')

    def test_pending_release_restart_uses_fresh_boot_cargo_without_reusing_id(self):
        for mode in ('log','files'):
            with self.subTest(mode=mode):
                self.start(mode).execute('''
                  FAKE.held=3;FAKE.cargo={{name=item.name,damage=0,size=3,maxSize=64}}
                  ready();EVENTS={};FAKE.releaseSilent=true
                  assert(lg.release('d1'));local old=SENT[#SENT].id
                  reload();assert(not lg.drones()[1].releasePending and lg.drones()[1].state=='booting')
                  FAKE.held=2;FAKE.cargo[1].size=2;answerStatus()
                  assert(lg.drones()[1].state=='held' and lg.drones()[1].held[1].count==2)
                  EVENTS={};assert(lg.release('d1'));assert(SENT[#SENT].id==old+1)
                ''')

    def test_job_and_trip_ids_continue_without_reuse(self):
        for mode in ('log', 'files'):
            with self.subTest(mode=mode):
                self.start(mode).execute('''
                  local a=fetch();local first=FAKE.trip;finishPhysical(true)
                  reload();answerStatus();drain();local b=fetch()
                  assert(b==a+1 and FAKE.trip==first+1);finishPhysical(true)
                  FAKE.held=1;FAKE.cargo={{name=item.name,damage=0,size=1,maxSize=64}}
                  ready() -- Don't drain the held notification; exercise the explicit release path.
                  assert(lg.release('d1')==true)
                  local _,name,state=require('event').pull('logistics_released');assert(name=='d1' and state=='ok')
                  local listing=lg.drones()[1].cargo;assert(listing[1].size==1)
                  local released=SENT[#SENT].id;FAKE.held=0;FAKE.cargo={}
                  reload();answerStatus();drain()
                  local c=lg.scan('home');drain();assert(c==b+1 and FAKE.trip==released+1)
                ''')

    def test_saved_reports_queue_eviction_and_reservation_reconciliation(self):
        for mode in ('log', 'files'):
            with self.subTest(mode=mode):
                self.start(mode).execute('''
                  local id=fetch()
                  report(FAKE.trip,{state='blocked',link={a='home',b='source'},to='dest'})
                  report(FAKE.trip,{state='progress',steps={{taken=2,moved=2}},held=2})
                  local s=require('logistics.store').open('/etc/logistics.state');local r=s:load();s:close()
                  assert(r['job_'..id].active[FAKE.trip].progress.held==2)
                  assert(r['job_'..id].avoid==nil and r.ids.job==id and r.ids.trip==FAKE.trip)
                  assert(#r['job_'..id].blockedReports==1)
                  finishPhysical(false);report(FAKE.last.id,clone(FAKE.last.result))
                  -- The terminal job is saved, but its warehouse event has not run.
                  reload();assert(wh.count(item)==6 and wh.settled(id));answerStatus();drain()
                  local f=require('logistics.store').open('/etc/warehouse.flight');f:load()
                  f:put('job_999',{});f:flush();f:close();reload()
                  f=require('logistics.store').open('/etc/warehouse.flight');assert(not next(f:load()));f:close()
                  local first
                  for i=1,34 do local n=lg.scan('home');first=first or n;assert(lg.cancel(n)) end
                  reload();assert(lg.status(first)==nil and #lg.jobs()==32)
                  s=require('logistics.store').open('/etc/logistics.state');r=s:load();s:close()
                  assert(r['job_'..first]==nil)
                  local x=lg.transfer(item,1,'stock','out');local y=lg.scan('home')
                  reload();answerStatus();drain();assert(FAKE.working and FAKE.task.steps[1].take)
                  assert(lg.status(x).state=='active' and lg.status(y).state=='queued')
                ''')

    def test_replayed_transfer_uses_report_cargo_slots_before_ready(self):
        for mode in ('log', 'files'):
            with self.subTest(mode=mode):
                self.start(mode).execute('''
                  local id=lg.transfer(item,4,'stock','out',{split=false});drain()
                  assert(FAKE.working and FAKE.task.steps[1].count==4)
                  finishPhysical(false)
                  reload();answerStatus();drain()
                  local s=lg.status(id);assert(s.state=='done' and s.moved==4 and s.taken==4)
                  assert(wh.count(item)==6)
                ''')

    def test_unknown_navigation_trip_answers_known_token_only(self):
        for mode in ('log', 'files'):
            with self.subTest(mode=mode):
                self.start(mode).execute('''
                  emit('modem_message','local','remote',27103,0,'wrong','navigate',999,'{}')
                  assert(#SENT==0)
                  emit('modem_message','local','remote',27103,0,'secret','navigate',999,'{}')
                  assert(#SENT==1 and SENT[1].kind=='navigation' and SENT[1].id==999)
                  assert(require('serialization').unserialize(SENT[1].payload).reason=='unknown trip 999')
                ''')


class AgentRestartTests(unittest.TestCase):
    def route_fixture(self, blocked=False):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.globals().AGENT = Path('drone-logistics/usr/lib/logistics/drone/agent.lua').read_text()
        lua.globals().BLOCKED = blocked
        lua.execute('''
          TIME=0;SENT={};POSITION=0;TARGET=0
          local drone={inventorySize=function() return 4 end,count=function() return 0 end,
            getAcceleration=function() return 2 end,getMaxVelocity=function() return 8 end,
            move=function(dx) TARGET=TARGET+dx;if not BLOCKED then POSITION=TARGET end end,
            getOffset=function() return math.abs(TARGET-POSITION) end,getVelocity=function() return 0 end}
          local inv={getStackInInternalSlot=function() end}
          component={list=function(kind) return function() return kind end end,
            proxy=function(kind) return kind=='drone' and drone or inv end}
          computer={energy=function() return 5000 end,freeMemory=function() return 32000 end,
            uptime=function() return TIME end,pullSignal=function(seconds) return coroutine.yield(seconds) end}
          local modem={send=function(_,_,_,kind,id,payload)
            SENT[#SENT+1]={kind=kind,id=id,payload=payload}
          end}
          AGENT_THREAD=coroutine.create(assert(load(AGENT)))
          assert(coroutine.resume(AGENT_THREAD,modem,'token','controller','d1',27103,0,0,0))
          function resume(...)
            SENT={};local ok,err=coroutine.resume(AGENT_THREAD,...)
            assert(ok,err);assert(coroutine.status(AGENT_THREAD)=='suspended')
          end
          function command(kind,id,payload)
            resume('modem_message','local','controller',27103,0,'token',kind,id,payload)
          end
          function decoded(n) return assert(load('return '..SENT[n].payload))() end
          ROUTE="{route={{name='home',x=0,y=0,z=0},{name='dest',x=1,y=0,z=0}}}"
          command('trip',11,"{reserve=1000,home='dest',steps={{go='dest'}},routes={take={{name='home',x=0,y=0,z=0}}}}")
          assert(#SENT==1 and SENT[1].kind=='navigate' and SENT[1].id==11)
        ''')
        return lua

    def test_goto_waits_past_ten_seconds_and_resends_on_restart_status(self):
        self.route_fixture().execute('''
          local original=SENT[1].payload
          TIME=25;resume();assert(#SENT==0)
          command('status');assert(#SENT==1 and SENT[1].kind=='navigate' and SENT[1].payload==original)
          command('navigation',99,ROUTE);assert(#SENT==0)
          command('navigation',11,ROUTE)
          assert(SENT[#SENT].id==11 and decoded(#SENT).state=='idle' and POSITION==1)
        ''')

    def test_blocked_reroute_waits_past_ten_seconds_and_resends_on_status(self):
        self.route_fixture(True).execute('''
          command('navigation',11,ROUTE)
          TIME=0.1;resume() -- establish the unchanged offset
          TIME=4.1;resume() -- stall, undo movement target, and retrace physically
          TIME=4.2;resume()
          assert(#SENT==1 and SENT[1].kind=='report' and decoded(1).state=='blocked')
          local original=SENT[1].payload
          TIME=30;resume();assert(#SENT==0)
          command('status');assert(#SENT==1 and SENT[1].kind=='report' and SENT[1].payload==original)
          BLOCKED=false;command('navigation',11,ROUTE)
          assert(SENT[#SENT].id==11 and decoded(#SENT).state=='idle' and POSITION==1)
        ''')

    def test_arrival_during_yield_is_not_misreported_as_a_stall(self):
        self.route_fixture(True).execute('''
          command('navigation',11,ROUTE)
          TIME=.1;POSITION=.91;resume()
          -- The last .09 block settles during the yield, after the stall time.
          TIME=4.1;POSITION=TARGET;resume()
          assert(TARGET==1,'an arrived drone must not undo its movement')
          assert(SENT[#SENT].id==11 and decoded(#SENT).state=='idle')
        ''')

    def test_unknown_trip_route_response_fails_loudly(self):
        self.route_fixture().execute('''
          command('navigation',11,"{reason='unknown trip 11'}")
          assert(#SENT==1 and SENT[1].id==11)
          local result=decoded(1)
          assert(result.state=='held' and result.reason:find('unknown trip 11',1,true))
        ''')

    def test_last_cleared_by_trip_release_and_empty_status_only_ready(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.globals().AGENT = Path('drone-logistics/usr/lib/logistics/drone/agent.lua').read_text()
        lua.execute('''
          SENT={};HELD=0
          local drone={inventorySize=function() return 4 end,count=function(i) return i==1 and HELD or 0 end,
            getAcceleration=function() return 2 end,getMaxVelocity=function() return 8 end,
            getOffset=function() return 0 end}
          local inv={getInventorySize=function() return nil end,getStackInInternalSlot=function(i)
            if HELD>0 and i==1 then return {name='mod:stock',damage=0,size=HELD,maxSize=64} end
          end}
          component={list=function(kind) return function() return kind end end,
            proxy=function(kind) return kind=='drone' and drone or inv end}
          computer={energy=function() return 5000 end,freeMemory=function() return 32000 end,
            pullSignal=function() return coroutine.yield() end}
          local modem={send=function(_,_,_,kind,id,payload)
            SENT[#SENT+1]={kind=kind,id=id,payload=payload}
          end}
          local agent=coroutine.create(assert(load(AGENT)))
          assert(coroutine.resume(agent,modem,'token','controller','d1',27103,0,0,0))
          function command(kind,id,payload)
            SENT={};local ok,err=coroutine.resume(agent,'modem_message','local','controller',27103,0,'token',kind,id,payload)
            assert(ok,err);assert(coroutine.status(agent)=='suspended')
          end
          function decoded(n) return assert(load('return '..SENT[n].payload))() end
          local trip="{reserve=1000,action={kind='scan'},routes={take={{name='home',x=0,y=0,z=0}},home={{name='home',x=0,y=0,z=0}}}}"
          command('status');assert(#SENT==1 and SENT[1].id==0 and decoded(1).state=='ready')
          command('trip',11,trip);assert(#SENT==1 and SENT[1].id==11)
          local payload=SENT[1].payload
          command('status');assert(#SENT==2 and SENT[1].id==11 and SENT[1].payload==payload and SENT[2].id==0)
          command('trip',12,'invalid');assert(#SENT==0)
          command('status');assert(#SENT==1 and SENT[1].id==0)
          command('trip',13,trip);assert(SENT[1].id==13)
          command('release',14);assert(#SENT==1 and SENT[1].kind=='cargo')
          command('status');assert(#SENT==1 and SENT[1].id==0)
          HELD=3;command('status');local ready=decoded(1)
          assert(#SENT==1 and ready.freeMemory==32000 and ready.held==3 and ready.cargo[1].size==3)
        ''')
