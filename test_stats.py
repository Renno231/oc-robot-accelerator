"""Catalogue-only stats, canonical CBOR log persistence, and stock identity."""
from pathlib import Path
import unittest
import tempfile
from lupa.lua53 import LuaRuntime
from test_store import install_store
import test_stations


class StatsTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute('''
          package.preload.serialization=function() return {
            serialize=function(a) return a[1]..'|'..a[2]..'|'..(a[3] or '') end,
            unserialize=function(s) DECODES=(DECODES or 0)+1;local n,d,l=s:match('^(.-)|(%d+)|(.*)$');return {n,tonumber(d),l~='' and l or nil} end} end
        ''')
        install_store(self.lua)
        self.lua.globals().STATS = Path('drone-logistics/lib/stats.lua').read_text()
        self.lua.execute('''
          TIME=0;LISTEN={};TIMERS={};ROWS={};RESERVED=0;READS=0;JOBS=0;PUTS=0;SIGNALS={};TCALLS=0;ENTRIES=0;DECODES=0;VERSION=0
          package.loaded.computer={uptime=function() return TIME end}
          package.loaded.event={listen=function(n,f) LISTEN[n]=f end,
            push=function(n) SIGNALS[#SIGNALS+1]=n end,
            cancel=function(id) TIMERS[id]=nil end,
            timer=function(seconds,f,times) assert(times==1);TCALLS=TCALLS+1;TIMERS[TCALLS]=f;return TCALLS end}
          local wh={}
          local function matches(a,b) return a.name==b.name and (a.damage or 0)==(b.damage or 0) and (not b.label or a.label==b.label) end
          function wh.entries() ENTRIES=ENTRIES+1;return ROWS end
          function wh.revision() return VERSION end
          function wh.totals()
            local t={};for _,fs in pairs(ROWS) do for _,v in pairs(fs[1].entry and fs[1].entry.items or {}) do
              if v.count>0 then local k=require('serialization').serialize({v.item.name,v.item.damage or 0,v.item.label})
                t[k]=t[k] or {item=v.item,count=0};t[k].count=t[k].count+v.count end
            end end;local out={};for _,v in pairs(t) do out[#out+1]=v end;return out
          end
          function wh.find(i)
            local out={};for _,fs in pairs(ROWS) do local n=0
              for _,v in pairs(fs[1].entry and fs[1].entry.items or {}) do if matches(v.item,i) then n=n+v.count end end
              if n>0 then out[#out+1]={storage=fs[1].storage,count=n} end
            end;return out
          end
          function wh.count(i) local n=0;for _,v in ipairs(wh.find(i)) do n=n+v.count end;return n end
          function wh.available(i) return wh.count(i)-RESERVED end
          wh.scan=function() READS=READS+1;error('unexpected read') end
          wh.fetch=function() JOBS=JOBS+1;error('unexpected job') end
          package.loaded.warehouse=wh
          package.loaded.logistics={job=wh.fetch};package.loaded.component={transposer={getAllStacks=wh.scan}}
          local open=require('store').open
          require('store').open=function(p,v)
            assert(p=='/etc/stats' and v=='log');local s=open(p,v);local put=s.put
            s.put=function(...) PUTS=PUTS+1;return put(...) end;return s
          end
          function storage(name,slots,used,count)
            local i={name='mod:seed',damage=0}
            ROWS[name]={{storage=name,entry=slots and {slots=slots,freeSlots=slots-used,time=0,
              items={seed={item=i,count=count}}} or nil}}
          end
          function reload() LISTEN={};TIMERS={};stats=assert(load(STATS))() end
          function warehouseChange()
            VERSION=VERSION+1;LISTEN.warehouse('warehouse','changed')
          end
          function change(used,count)
            ROWS.a[1].entry.freeSlots=100-used;ROWS.a[1].entry.items.seed.count=count
            warehouseChange()
          end
          function timerFire() for _,f in pairs(TIMERS) do f();return end;error('no hour timer') end
          function timerCount() local n=0;for _ in pairs(TIMERS) do n=n+1 end;return n end
          function closeHour() TIME=TIME+3600;timerFire() end
          function near(a,b) assert(math.abs(a-b)<1e-9,tostring(a)..' ~= '..tostring(b)) end
        ''')

    def test_summary_and_unknown(self):
        self.lua.execute('''
          for n=1,8 do storage('s'..n,27,1,n*64) end
          ROWS.s8[2]={storage='double-alias',entry=ROWS.s8[1].entry}
          storage('unread');reload();local r=stats.summary()
          assert(r.storages==9 and r.unknown==1 and r.slots==216 and r.freeSlots==208)
          assert(r.usedSlots==8 and r.items==2304 and r.kinds==1 and #r.perStorage==8)
          near(r.fill,8/216)
          TIME=17;assert(stats.summary().perStorage[1].age==17)
          RESERVED=12;local i=stats.item{name='mod:seed'}
          assert(i.count==2304 and i.free==2292 and i.reserved==12 and #i.where==8)
          assert(READS==0 and JOBS==0)
        ''')

    def test_growth_flat_shrinking_and_item_rates(self):
        self.lua.execute('''
          storage('a',100,0,0);reload()
          for h=1,8 do
            if h<=4 then TIME=(h-1)*3600+100;change(h*10,h*640) end
            TIME=h*3600;timerFire()
            local r=stats.summary()
            if h>=3 and h<=7 then assert(r.trend.state=='growing' and r.trend.fullInHours)
              near(r.trend.fullInHours,r.freeSlots/r.trend.usedPerHour6)
            elseif h==8 then assert(r.trend.state=='stable' and not r.trend.fullInHours) end
            if h==6 then local i=stats.item{name='mod:seed'};assert(i.perHour1==0);near(i.perHour6,2560/6) end
          end
          local i=stats.item{name='mod:seed'};near(i.perHour6,1280/6)
          assert(PUTS==8 and READS==0 and JOBS==0)
          for h=1,3 do change(40-h*10,2560-h*640);closeHour() end
          local r=stats.summary();assert(r.trend.state=='shrinking' and not r.trend.fullInHours)
          local i=stats.item{name='mod:seed'};assert(i.perHour1==-640);near(i.perHour6,-1920/6)
        ''')

    def test_top_three_and_known_empty_inventory(self):
        self.lua.execute('''
          storage('a',100,4,0);storage('empty',0,0,0)
          for n=1,4 do ROWS.a[1].entry.items['i'..n]={item={name='mod:i'..n},count=n} end
          reload();local r=stats.summary();assert(r.unknown==0 and r.kinds==4 and r.items==10)
          for _,v in ipairs(r.perStorage) do
            if v.name=='a' then assert(#v.top==3 and v.top[1].count==4 and v.top[3].count==2)
            else assert(v.fill==0 and #v.top==0) end
          end
        ''')

    def test_rollover_restart_retention_and_no_partial_save(self):
        self.lua.execute('''
          storage('a',100,0,0);reload();resetCalls()
          change(1,64);stats.summary();stats.item{name='mod:seed'}
          assert(PUTS==0 and not calls.write and not calls.read)
          closeHour();assert(PUTS==1 and calls.write==1)
          change(2,128);TIME=0;reload()
          local i=stats.item{name='mod:seed'};assert(i.perHour1==64)
          closeHour();assert(stats.item{name='mod:seed'}.perHour1==0)
          for n=1,25 do closeHour() end
          local s=require('store').open('/etc/stats','log');local h=s:load().hours
          assert(#h==24 and h.serial==27)
          for _,b in ipairs(h) do assert(not next(b.i)) end
          assert(stats.item{name='mod:seed'}.perHour6==0 and READS==0 and JOBS==0)
        ''')

    def test_settings_and_warnings(self):
        self.lua.execute('''
          storage('a',100,85,64);reload();assert(#stats.warnings()==2)
          assert(stats.settings().fillBad==.95)
          local copy=stats.settings();copy.fillWarn=1;assert(#stats.warnings()==2)
          for _,v in ipairs({'x',false,{},-1,1.01,0/0,math.huge}) do assert(not pcall(stats.set,'fillWarn',v)) end
          assert(not pcall(stats.set,'fullSoonHours',-1))
          assert(not pcall(stats.set,'nope',.5));assert(PUTS==0)
          stats.set('fillWarn',.9);assert(#stats.warnings()==0 and PUTS==1)
          stats.set('fillBad',.98);stats.set('fullSoonHours',4);reload()
          assert(stats.settings().fillWarn==.9 and stats.settings().fillBad==.98 and stats.settings().fullSoonHours==4)
          change(90,128);closeHour();change(95,192);closeHour();change(100,256);closeHour()
          local found=false;for _,v in ipairs(stats.warnings()) do if v.kind=='fullSoon' then found=v.hours==0 end end
          assert(found)
        ''')

    def test_label_rates_and_idle_gap(self):
        self.lua.execute('''
          storage('a',100,0,0);reload()
          local a=ROWS.a[1].entry
          a.items.x={item={name='mod:seed',damage=0,label='X'},count=6}
          a.items.y={item={name='mod:seed',damage=0,label='Y'},count=12}
          warehouseChange();closeHour()
          assert(stats.item{name='mod:seed'}.perHour1==18)
          assert(stats.item{name='mod:seed',label='X'}.perHour1==6)
          TIME=TIME+30*3600;timerFire();assert(stats.item{name='mod:seed'}.perHour6==0)
        ''')

    def test_hour_event_one_shot_and_no_change_suppression(self):
        self.lua.execute('''
          storage('a',100,0,0);reload();assert(timerCount()==1 and #SIGNALS==0)
          stats.summary();stats.summary();assert(TCALLS==1 and #SIGNALS==0)
          closeHour();assert(timerCount()==1 and TCALLS==2 and #SIGNALS==1 and SIGNALS[1]=='stats')
          stats.summary();assert(TCALLS==2 and #SIGNALS==1)
          stats.set('fillBad',.9);assert(#SIGNALS==2)
          stats.set('fillBad',.9);assert(#SIGNALS==2)
        ''')

    def test_summary_cache_invalidation_and_unread_names(self):
        self.lua.execute('''
          storage('a',100,1,64);storage('unread-a');storage('unread-b');reload()
          local r=stats.summary();local count=ENTRIES
          for n=1,10 do assert(stats.summary()==r);stats.warnings() end
          assert(ENTRIES==count and r.unknown==2 and #r.unread==2)
          local names={};for _,name in ipairs(r.unread) do names[name]=true end
          assert(names['unread-a'] and names['unread-b'])
          change(2,128);local changed=stats.summary();assert(changed~=r and changed.items==128)
          assert(ENTRIES==count+1);stats.warnings();assert(ENTRIES==count+1)
          closeHour();local rolled=stats.summary();assert(rolled~=changed and ENTRIES==count+2)
          stats.set('fillWarn',.7);assert(stats.summary()~=rolled and ENTRIES==count+3)
          assert(READS==0 and JOBS==0)
        ''')

    def test_item_rate_index_decodes_once_per_bucket_change(self):
        self.lua.execute('''
          storage('a',100,0,0);reload()
          local a=ROWS.a[1].entry
          a.items.x={item={name='mod:seed',damage=0,label='X'},count=6}
          a.items.y={item={name='mod:seed',damage=0,label='Y'},count=12}
          warehouseChange();closeHour()
          assert(stats.item{name='mod:seed'}.perHour1==18);local count=DECODES
          for n=1,10 do
            assert(stats.item{name='mod:seed',label='X'}.perHour1==6)
            assert(stats.item{name='mod:seed',label='Y'}.perHour1==12)
          end
          assert(DECODES==count and count==2)
          closeHour();assert(stats.item{name='mod:seed'}.perHour1==0 and DECODES==count+2)
        ''')

    def test_age_updates_but_pre_restart_observations_are_unknown(self):
        self.lua.execute('''
          storage('a',100,1,64);TIME=10
          local a=ROWS.a[1].entry;a.time=5;a.beforeRestart=true;reload()
          local r=stats.summary().perStorage[1];assert(r.age==nil and r.beforeRestart)
          a.time=10;a.beforeRestart=false;warehouseChange()
          r=stats.summary().perStorage[1];assert(r.age==0 and not r.beforeRestart)
          TIME=25;assert(stats.summary().perStorage[1].age==15)
        ''')

    def test_setting_errors_include_range_and_threshold_order(self):
        self.lua.execute('''
          reload()
          local function rejects(k,v,text)
            local ok,msg=pcall(stats.set,k,v);assert(not ok and msg:find(text,1,true),tostring(msg))
          end
          rejects('fillWarn',1.1,'0-1');rejects('fillBad',-1,'0-1')
          rejects('fullSoonHours',math.huge,'finite and >= 0')
          rejects('fillWarn',.95,'fillWarn < fillBad');rejects('fillBad',.8,'fillWarn < fillBad')
          rejects('fillWarn',.96,'fillWarn < fillBad');rejects('fillBad',.7,'fillWarn < fillBad')
          rejects('nope',.5,'unknown setting')
          assert(PUTS==0 and #SIGNALS==0 and stats.settings().fillWarn==.8)
          stats.set('fillWarn',0);stats.set('fillBad',1);stats.set('fullSoonHours',0)
          assert(stats.settings().fillWarn==0 and stats.settings().fillBad==1)
        ''')

    def test_cache_handles_reverse_subscriber_order_and_duplicate_events(self):
        self.lua.execute('''
          storage('a',100,1,64);reload();local original=stats.summary();local count=ENTRIES
          ROWS.a[1].entry.freeSlots=10;ROWS.a[1].entry.items.seed.count=640;VERSION=VERSION+1
          -- The alert/UI subscriber queries first, before the stats subscriber.
          local fresh=stats.summary();assert(fresh~=original and fresh.freeSlots==10 and fresh.items==640)
          assert(#stats.warnings()==2 and ENTRIES==count+1)
          LISTEN.warehouse('warehouse','changed');assert(stats.summary()==fresh and ENTRIES==count+1)
          LISTEN.warehouse('warehouse','changed');assert(stats.summary()==fresh and ENTRIES==count+1)
          closeHour();assert(stats.item{name='mod:seed'}.perHour1==576)
          assert(stats.summary().trend.usedPerHour1==89 and ENTRIES==count+2)
        ''')


class WarehouseStatsIntegrationTests(unittest.TestCase):
    def test_observation_boot_flag_is_runtime_only_and_alias_safe(self):
        f = test_stations.StationsTests();f.setUp();lua=f.lua
        lua.execute('''
          map.name('a','home1',0);map.name('alias','home2',0)
          wh.add('a',{inventory='shared'});wh.add('alias',{inventory='shared'})
          wh.scan();finishAll();local rows=wh.entries()
          for _,v in ipairs(rows.shared) do assert(v.entry.beforeRestart==false) end
          require('event').timer=function() return 1 end;require('event').cancel=function() end
          stats=assert(load(STATS))();local r=stats.summary().perStorage[1]
          assert(r.age==0 and r.beforeRestart==false)
          local data=require('store').open('/etc/warehouse.db','log'):load()
          assert(data.shared.beforeRestart==nil)
          package.loaded.warehouse=nil;wh=require('warehouse');rows=wh.entries()
          for _,v in ipairs(rows.shared) do assert(v.entry.beforeRestart==true) end
          stats=assert(load(STATS))();r=stats.summary().perStorage[1]
          assert(r.age==nil and r.beforeRestart==true)
          wh.scan();finishAll();rows=wh.entries()
          for _,v in ipairs(rows.shared) do assert(v.entry.beforeRestart==false) end
          r=stats.summary().perStorage[1];assert(r.age==0 and r.beforeRestart==false)
          data=require('store').open('/etc/warehouse.db','log'):load()
          assert(data.shared.beforeRestart==nil)
        ''')

    def test_generated_mes_fixture_includes_stats(self):
        from test_mes_fixtures import generator
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'case'
            generator.build(root, 'torches16')
            self.assertEqual((root / 'program/lib/stats.lua').read_bytes(),
                             Path('drone-logistics/lib/stats.lua').read_bytes())

    def test_accessor_stock_identity_group_exclusion_copy_and_zero_trips(self):
        f = test_stations.StationsTests();f.setUp();lua=f.lua
        lua.globals().STATS=Path('drone-logistics/lib/stats.lua').read_text()
        lua.execute('''
          for n=1,9 do local s='s'..n;map.name(s,'home'..math.ceil(n/5),(n-1)%5);wh.add(s,{inventory=n==9 and 's8' or s}) end
          wh.group('machine','test',{buffer='s7'})
          wh.scan();finishAll()
          require('event').timer=function() return 1 end
          require('event').cancel=function() end
          stats=assert(load(STATS))();local before=#HISTORY
          local rows=wh.entries();local n=0;for _ in pairs(rows) do n=n+1 end;assert(n==7)
          rows.s1[1].entry.slots=999;assert(wh.contents('s1').slots==27)
          local r=stats.summary();assert(r.storages==7 and r.slots==189 and r.items==14 and r.unknown==0)
          stats.item{name='mod:seed'};assert(#HISTORY==before)
          lg.job=function() error('stats submitted a job') end
          require('component').transposer={getAllStacks=function() error('stats read') end}
          TIME=3600;stats.summary();stats.item{name='mod:seed'};assert(#HISTORY==before)
        ''')


if __name__ == '__main__':
    unittest.main()
