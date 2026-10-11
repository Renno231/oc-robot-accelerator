"""S1 transitions through real map/logistics/warehouse, six physical fakes."""
from pathlib import Path
import unittest
import test_stock_api
from test_store import install_store


class StationsTests(unittest.TestCase):
    def setUp(self):
        f = test_stock_api.LibraryApiTests(); f.setUp(); self.lua = f.lua
        self.lua.execute('oldIO=io.open')
        install_store(self.lua)
        for name in ('map', 'logistics', 'warehouse', 'stations', 'iochest', 'stats'):
            self.lua.globals()[name.upper()] = Path(f'drone-logistics/lib/{name}.lua').read_text()
        for name in ('mes_alerts', 'mes_alert_sources'):
            self.lua.globals()[name.upper()] = Path(f'craftsystem/usr/lib/{name}.lua').read_text()
        self.lua.execute('''
          local countedIO=io.open
          io.open=function(p,m)
            if p=='/etc/map.cfg' or p=='/etc/warehouse.cfg' or p=='/etc/logistics.drones'
              or p=='/lib/logistics/agent.lua' then return oldIO(p,m) end
            return countedIO(p,m)
          end
          local ser=require('serialization');local encode=ser.serialize
          ser.serialize=function(t,...)
            if type(t)=='table' and type(t[1])=='string' and type(t[2])=='number' then
              local key=t[1]..'/'..tostring(t[2])..'/'..tostring(t[3]);serial[key]=clone(t);return key
            end
            return encode(t,...)
          end
          variant('log');TIME=0;LISTEN={};EVENTS={};FAKES={};HISTORY={};INV={};BLOCKED=false
          package.loaded.computer={uptime=function() return TIME end}
          package.loaded.event={listen=function(n,f) LISTEN[n]=LISTEN[n] or {};table.insert(LISTEN[n],f) end,
            push=function(...) EVENTS[#EVENTS+1]={...} end}
          function emit(n,...) for _,f in ipairs(LISTEN[n] or {}) do f(n,...) end end
          function drain() while #EVENTS>0 do local e=table.remove(EVENTS,1);emit(table.unpack(e)) end end
          package.preload.map=function() return assert(load(MAP))() end
          map=require('map')
          local fleet={}
          for i=1,6 do
            local home='home'..i;map.add(home,i-1,65,0)
            FAKES['remote'..i]={token='token'..i,home=home};fleet['d'..i]={address='remote'..i,token='token'..i,home=home}
            if i>1 then map.link('home'..(i-1),home) end
          end
          map.save();files['/lib/logistics/agent.lua']='return true'
          files['/etc/logistics.drones']=ser.serialize(fleet)
          require('component').modem.send=function(addr,port,token,kind,id,payload)
            local f=FAKES[addr]
            if kind=='trip' then assert(not f.task);f.task=ser.unserialize(payload);f.id=id
              HISTORY[#HISTORY+1]=clone(f.task)
            end
          end
          function report(addr,id,r)
            local f=FAKES[addr];r.energy=5000;r.cargoSlots=4;r.position=map.node(f.home);r.held=0
            emit('modem_message','local',addr,27103,0,f.token,'report',id,ser.serialize(r))
          end
          package.preload.logistics=function() return assert(load(LOGISTICS))() end
          package.preload.warehouse=function() return assert(load(WAREHOUSE))() end
          package.preload.stations=function() return assert(load(STATIONS))() end
          package.preload.stats=function() return assert(load(STATS))() end
          package.preload.iochest=function() return assert(load(IOCHEST))() end
          package.preload.mes_alerts=function() return assert(load(MES_ALERTS))() end
          package.preload.mes_alert_sources=function() return assert(load(MES_ALERT_SOURCES))() end
          local open=require('store').open;PUTS=0;FLUSHES=0
          require('store').open=function(p,...)
            local h=open(p,...)
            if p=='/etc/stations' then
              local put,flush=h.put,h.flush
              h.put=function(...) PUTS=PUTS+1;return put(...) end
              h.flush=function(...) FLUSHES=FLUSHES+1;return flush(...) end
            end
            return h
          end
          function reload()
            LISTEN={};EVENTS={}
            package.loaded.logistics=nil;package.loaded.warehouse=nil;package.loaded.stations=nil
            lg=require('logistics');wh=require('warehouse');st=require('stations')
            for addr,f in pairs(FAKES) do if not f.task then report(addr,0,{state='ready',freeMemory=32000}) end end
            drain();assert(#lg.drones()==6)
          end
          reload()
          function finishOne()
            for addr,f in pairs(FAKES) do if f.task then
              local task=f.task;local r={state='idle',steps={}};local carried=0
              if task.action then
                r.test=BLOCKED and 'blocked' or 'ok';r.reason=BLOCKED and 'blocked candidate' or nil
                if BLOCKED then report(addr,f.id,{state='blocked',candidate=true,
                  link={a=task.action.a,b=task.action.b},to=task.action.b,offset=1,stalledSeconds=1}) end
              else for i,s in ipairs(task.steps) do
                local e=s.read or s.take or s.put;local key=e.node..':'..e.side
                local c=INV[key] or {size=27,count=2};INV[key]=c
                local v={moved=0,maxSize=64};r.steps[i]=v
                if s.read then v.size=c.size;v.listing={}
                  if c.count>0 then v.listing[1]={name='mod:seed',damage=0,size=c.count,maxSize=64} end
                elseif s.take then v.taken=math.min(c.count,s.count);v.moved=v.taken;c.count=c.count-v.taken;carried=carried+v.taken
                elseif s.put then v.moved=math.min(carried,s.count or carried);c.count=c.count+v.moved;carried=carried-v.moved end
              end end
              f.task=nil;TIME=TIME+1;report(addr,f.id,r);drain();return true
            end end
          end
          function finishAll() drain();local n=0;while finishOne() do n=n+1;assert(n<200) end end
          function counts()
            local tests,reads=0,0
            for _,t in ipairs(HISTORY) do if t.action then tests=tests+1
              else for _,s in ipairs(t.steps) do if s.read then reads=reads+1 end end end end
            return tests,reads
          end
          function single(name,x,z) return {name=name,x=x or 5,y=64,z=z or 2,face='top',role='stock'} end
          function row(name,count,spacing) return {prefix=name,x=5,y=64,z=2,face='top',role='stock',rowDir='east',count=count,spacing=spacing} end
        ''')

    def test_boot_mes_service_resumes_station_without_setup_or_station_require(self):
        self.lua.execute('''
          assert(st.add('storage',single('boot_chest')));drain()
          assert(st.get('boot_chest').state=='checking')
          LISTEN={};EVENTS={};st=nil
          package.loaded.stations=nil;package.loaded.logistics=nil;package.loaded.warehouse=nil
          lg=require('logistics');wh=require('warehouse')
          assert(package.loaded.stations==nil)
          package.path='craftsystem/usr/lib/?.lua;'..package.path
          package.preload.craft_client=function() return {install=function() return {} end,tick=function() end} end
          package.preload.mes_config=function() return {installRobots=function() end,
            config=function() return {crafters={},machineTypes={}} end} end
          require('event').timer=function() return 1 end
          assert(require('mes_service').start())
          assert(package.loaded.stations and package.loaded.stats and package.loaded.mes_alerts and LISTEN.logistics)
          for addr,f in pairs(FAKES) do if not f.task then report(addr,0,{state='ready',freeMemory=32000}) end end
          finishAll()
          st=package.loaded.stations
          assert(st.get('boot_chest').state=='ready' and wh.members().boot_chest)
        ''')

    def test_phase_events_and_list_member_count(self):
        self.lua.execute('''
          local seen={}
          LISTEN.station={function(_,name,state,phase)
            seen[#seen+1]={name=name,state=state,phase=phase}
          end}
          assert(st.add('row',row('counted',3,2)))
          assert(st.list()[1].count==3)
          finishAll()
          assert(seen[1].name=='counted' and seen[1].state=='checking' and seen[1].phase=='row')
          assert(seen[2].state=='checking' and seen[2].phase=='read')
          assert(seen[3].state=='ready' and seen[3].phase==nil)
          assert(st.add('storage',single('single',12,5)));finishAll()
          local counts={};for _,r in ipairs(st.list()) do counts[r.name]=r.count end
          assert(counts.counted==3 and counts.single==1)
        ''')

    def test_name_error_identifies_taken_member_and_empty_name(self):
        self.lua.execute('''
          local ok,err=st.add('storage',single(''));assert(not ok and err:find('name empty',1,true))
          ok,err=st.add('storage',single('home1'));assert(not ok and err:find('name home1 already used',1,true))
          map.name('occupied2','home1',1)
          ok,err=st.add('row',row('occupied',3,2))
          assert(not ok and err:find('name occupied2 already used',1,true))
          assert(#st.list()==0 and not map.storage('occupied1'))
        ''')

    def test_storage_ready_T1_T2_T3_T5_T6_T7(self):
        self.lua.execute('''
          assert(st.add('storage',single('chest'))=='chest')
          assert(st.get('chest').phase=='link' and PUTS==2 and FLUSHES==2)
          local n=PUTS;drain();drain();assert(PUTS==n)
          local d=lg.drones();assert(d[1].lost==false)
          finishAll();local r=st.get('chest');assert(r.state=='ready' and #r.created.nodes==1)
          assert(r.members[1].node=='h5_65_2' and r.members[1].side==0)
          assert(r.created.links[1][1]=='home6' and #r.created.links==1)
          local t,b=counts();assert(t==1 and b==1 and wh.members().chest)
          assert(PUTS==4 and FLUSHES==4)
          r.members[1].node='corrupt';assert(st.get('chest').members[1].node=='h5_65_2')
        ''')

    def test_reused_hover_node_T1_T5_T6_T7(self):
        self.lua.execute('''
          map.add('existing',5.0,65.0,2.0);map.link('home6','existing');map.save()
          assert(st.add('storage',single('chest')));finishAll()
          local r=st.get('chest');local t,b=counts()
          assert(r.state=='ready' and r.members[1].node=='existing' and #r.created.nodes==0)
          assert(t==0 and b==1 and PUTS==3)
          local links=map.links('existing');assert(#links==1 and links[1]=='home6')
          links[1]='bad';assert(map.links('existing')[1]=='home6' and map.links('unknown')==nil)
        ''')

    def test_link_candidates_then_retry_T2x3_T8_T9(self):
        self.lua.execute('''
          BLOCKED=true;assert(st.add('storage',single('chest')));finishAll()
          local r=st.get('chest');assert(r.state=='failed' and #r.tried==3)
          assert(r.reason=='no clear path from the network to (5,65,2): tried home6, home5, home4; clear the path or add a node nearer')
          local t=counts();assert(t==3);BLOCKED=false;assert(st.retry('chest'));finishAll()
          assert(st.get('chest').state=='ready');t=counts();assert(t==4)
        ''')

    def test_row_of_five_double_chests_T1_T2_T3_T4_T5_T6_T7(self):
        self.lua.execute('''
          for i=0,4 do INV['h'..(5+2*i)..'_65_2:0']={size=54,count=2} end
          assert(st.add('row',row('row',5,2)));finishAll()
          local r=st.get('row');local t,b=counts();assert(r.state=='ready' and t==2 and b==5)
          assert(#r.created.nodes==5 and #r.created.links==5)
          for i=2,5 do local v=r.created.links[i];assert(v[1]==r.members[i-1].node and v[2]==r.members[i].node) end
          assert(map.node(r.members[5].node).x==13 and PUTS==5 and FLUSHES==5)
          for _,size in pairs(r.sizes) do assert(size==54) end;assert(not r.note)
        ''')

    def test_row_read_one_bad_T6_T8_T9(self):
        self.lua.execute('''
          INV['h7_65_2:0']={size=0,count=0}
          assert(st.add('row',row('row',3,1)));finishAll()
          local r=st.get('row');assert(r.state=='failed' and #r.bad==1 and r.bad[1]=='row3')
          assert(r.reason=='no inventory on the top face at (7,64,2)')
          local t,b=counts();assert(t==2 and b==3)
          INV['h7_65_2:0']={size=27,count=3};assert(st.retry('row'));finishAll()
          t,b=counts();assert(t==2 and b==4 and st.get('row').state=='ready')
        ''')

    def test_remove_rules_T10(self):
        self.lua.execute('''
          assert(st.add('storage',single('chest')));finishAll()
          wh.group('machine','furnace',{input='chest'})
          local ok,err=st.remove('chest');assert(not ok and err=='chest is machine.input; reassign it first')
          wh.ungroup('machine');ok,err=st.remove('chest');assert(not ok and err=='holds 2 items: remove with move or forget')
          assert(st.remove('chest',{items='forget'}));assert(not st.get('chest') and not map.node('h5_65_2'))
          INV['h4_65_2:0']={size=27,count=0}
          assert(st.add('storage',single('dest',4,2)));finishAll()
          assert(st.add('storage',single('source',6,2)));finishAll()
          local id=assert(wh.fetch({name='mod:seed',damage=0},1,'dest'));drain()
          ok,err=st.remove('source');assert(not ok and err=='source has items reserved by a running job')
          finishAll()
          assert(st.remove('source',{items='move'}));assert(st.get('source').state=='removing')
          finishAll();assert(not st.get('source') and not map.node('h6_65_2') and map.storage('dest'))
          assert(INV['h6_65_2:0'].count==0 and INV['h4_65_2:0'].count==2)
          assert(wh.count({name='mod:seed',damage=0})==2)
          assert(st.add('storage',single('shared',5,3)));finishAll()
          local s=single('other',6,4);s.face='west';s.role='other'
          -- A second face of the same hover node (5,64,4), not the first block.
          s.x=6;s.y=65;s.z=3
          assert(st.add('storage',s));finishAll()
          assert(st.remove('shared',{items='forget'}));assert(map.node('h5_65_3') and st.get('other'))
        ''')

    def test_restart_mid_check_R(self):
        self.lua.execute('''
          assert(st.add('storage',single('chest')));drain();local id=st.get('chest').jobs[1]
          reload();assert(st.get('chest').jobs[1]==id);assert(finishOne())
          assert(st.get('chest').phase=='read');id=st.get('chest').jobs[1]
          reload();assert(st.get('chest').jobs[1]==id);finishAll();assert(st.get('chest').state=='ready')
          assert(st.add('storage',single('evicted',9,2)))
          -- Recorded queued job is deliberately evicted from the same canonical store.
          local job=st.get('evicted').jobs[1];local h=require('store').open('/etc/logistics.state','log');h:load()
          h:delete('job_'..job);h:flush();reload();finishAll()
          assert(st.get('evicted').state=='ready' and st.get('evicted').jobs[1]==nil)
        ''')

    def test_validation_changes_nothing_T1(self):
        self.lua.execute('''
          local function rejects(kind,s)
            local before=require('serialization').serialize(map.nodes());local n=PUTS
            local cfg=files['/etc/map.cfg'];assert(not st.add(kind,s))
            assert(PUTS==n and files['/etc/map.cfg']==cfg)
            local a=require('serialization').unserialize(before);local b=map.nodes()
            for k,v in pairs(a) do assert(b[k] and b[k].x==v.x and b[k].y==v.y and b[k].z==v.z);b[k]=nil end
            assert(not next(b) and #st.list()==0)
          end
          local s=single('x');s.x=0.1;rejects('storage',s)
          s=single('x');s.face='bad';rejects('storage',s)
          s=single('x');s.role='machine';rejects('storage',s)
          for _,count in ipairs({0,65,1.5}) do s=row('x',count,1);rejects('row',s) end
          s=row('x',2,3);rejects('row',s)
          for _,d in ipairs({'bad','top','bottom'}) do s=row('x',2,1);s.rowDir=d;rejects('row',s) end
          s=single('home1');rejects('storage',s)
          map.add('occupied',5,65,2);map.name('used','occupied',0);map.save()
          rejects('storage',single('x'))
          s=row('used',2,1);rejects('row',s)
          map.unname('used');map.add('x2',7,65,2);map.save();rejects('row',row('x',2,2))
          s=row('pair',2,1);s.pair=3;rejects('row',s)
        ''')

    def test_pair_two_shared_catalogue_and_second_face_transfer(self):
        self.lua.execute('''
          for i=0,3 do INV['h'..(5+i)..'_65_2:0']={size=54,count=2} end
          INV['h6_65_2:0']=INV['h5_65_2:0'];INV['h8_65_2:0']=INV['h7_65_2:0']
          local s=row('row',4,1);s.pair=2;assert(st.add('row',s));finishAll()
          local t,b=counts();local r=st.get('row');assert(t==2 and b==2 and r.state=='ready')
          assert(r.sizes.row1==54 and r.sizes.row3==54 and not r.sizes.row2)
          local m=wh.members();assert(m.row1.inventory=='row1' and m.row2.inventory=='row1')
          local item={name='mod:seed',damage=0};assert(wh.count(item)==4)
          INV['h1_65_2:0']={size=27,count=10};assert(st.add('storage',single('source',1,2)));finishAll()
          local id=assert(wh.fetch(item,1,'row2'));finishAll();assert(lg.status(id).state=='done')
          assert(INV['h5_65_2:0'].count==3 and wh.contents('row1').items[next(wh.contents('row1').items)].count==3)
          assert(wh.count(item)==14)
          assert(st.remove('row',{items='move'}));finishAll();assert(not st.get('row'))
          assert(INV['h5_65_2:0'].count==0 and INV['h7_65_2:0'].count==0 and INV['h1_65_2:0'].count==14)
          assert(wh.count(item)==14)
        ''')

    def test_pair_one_note_not_failure(self):
        self.lua.execute('''
          INV['h5_65_2:0']={size=54,count=2};INV['h6_65_2:0']={size=54,count=2}
          assert(st.add('row',row('row',2,1)));finishAll()
          local r=st.get('row');assert(r.state=='ready')
          assert(r.note=='these may be double chests; remove and re-add with pair 2')
          assert(st.list()[1].note==r.note);local t,b=counts();assert(t==2 and b==2)
        ''')

    def test_unpaired_announce_once_and_fleet_work_fields(self):
        self.lua.execute('''
          local n=0;require('event').listen('logistics_announce',function(_,a) assert(a=='new');n=n+1 end)
          emit('modem_message','local','new',27103,0,'lgx_hello')
          emit('modem_message','local','new',27103,0,'lgx_hello')
          emit('modem_message','local','remote1',27103,0,'lgx_hello');drain();assert(n==1)
          assert(st.add('storage',single('chest')));drain()
          local job=st.get('chest').jobs[1];local found=false
          for _,d in ipairs(lg.drones()) do if d.job==job then assert(d.trip and not d.lost);found=true end end
          assert(found);finishAll()
          for _,d in ipairs(lg.drones()) do assert(d.job==nil and d.trip==nil and d.lost==false) end
        ''')

    def test_mapd_immediate_station_operations(self):
        self.lua.globals().MAPD = Path('drone-logistics/bin/mapd.lua').read_text()
        self.lua.execute('''
          local ser=require('serialization');disk['/etc/mapd.cfg']=ser.serialize({key='key'})
          local modem=require('component').modem;local send=modem.send;local replies={}
          modem.send=function(a,p,...)
            local v={...};if p==27104 then replies[#replies+1]=v else return send(a,p,...) end
          end
          assert(load(MAPD))()
          local function request(op,args)
            emit('modem_message','local','tablet',27104,0,'mapreq','key','id',op,ser.serialize(args))
            local r=replies[#replies];assert(r[4]=='done');return r[5],ser.unserialize(r[6]).value
          end
          local ok,n=request('station_add',{'storage',single('chest')});assert(ok and n=='chest')
          ok,n=request('station',{'chest'});assert(ok and n.state=='checking')
          ok,n=request('stations',{});assert(ok and #n==1)
          ok,n=request('station_retry',{'chest'});assert(not ok and n=='station is not retryable')
          finishAll();ok,n=request('station_remove',{'chest',{items='forget'}});assert(ok and n==true)
          assert(not st.get('chest'))
        ''')

    def test_blocked_row_T4_T8_T9(self):
        self.lua.execute('''
          assert(st.add('row',row('row',3,2)));drain();assert(finishOne())
          BLOCKED=true;assert(finishOne());assert(st.get('row').state=='failed')
          assert(st.get('row').reason=="blocked between (5,65,2) and (9,65,2): clear the row's hover line")
          BLOCKED=false;assert(st.retry('row'));finishAll();assert(st.get('row').state=='ready')
          local t,b=counts();assert(t==3 and b==3)
        ''')

    def test_pair_size_mismatch_only_owned_reads(self):
        self.lua.execute('''
          INV['h5_65_2:0']={size=54,count=2};INV['h6_65_2:0']={size=27,count=2}
          local s=row('row',2,1);s.pair=2;assert(st.add('row',s));drain()
          assert(finishOne());assert(finishOne());assert(st.get('row').phase=='read')
          -- Restore a checking record which owns reads of both access faces.
          local r=st.get('row');local ids=wh.scan('row2');r.jobs[#r.jobs+1]=ids[1]
          local h=require('store').open('/etc/stations','log');h:load();h:put('st_row',r);h:flush()
          reload();finishAll();assert(st.get('row').state=='failed')
          assert(st.get('row').reason:find('inventory size mismatch',1,true))
          local before=PUTS;wh.scan('row2');finishAll();assert(PUTS==before)
        ''')

    def test_restart_removing_R_evicted_completed_move(self):
        self.lua.execute('''
          INV['h1_65_2:0']={size=27,count=0}
          assert(st.add('storage',single('dest',1,2)));finishAll()
          assert(st.add('storage',single('source')));finishAll()
          assert(st.remove('source',{items='move'}));local id=st.get('source').jobs[1]
          table.remove(LISTEN.logistics) -- Warehouse settles, station misses completion.
          finishAll();assert(INV['h5_65_2:0'].count==0 and INV['h1_65_2:0'].count==2)
          local h=require('store').open('/etc/logistics.state','log');h:load();h:delete('job_'..id);h:flush()
          reload();assert(not st.get('source') and not map.node('h5_65_2'))
          assert(wh.count({name='mod:seed',damage=0})==2)
        ''')


if __name__ == '__main__':
    unittest.main()
