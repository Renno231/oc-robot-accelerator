from pathlib import Path
import unittest
import test_stations as stations


class IOChestTests(unittest.TestCase):
    def setUp(self):
        f = stations.StationsTests(); f.setUp(); self.lua = f.lua
        self.lua.globals().IOCHEST = Path('drone-logistics/usr/lib/logistics/iochest.lua').read_text()
        self.lua.execute('''
          IO_SAVES=0;IO_FLUSHES=0;IO_EVENTS=0
          local store=require('logistics.store');local open=store.open
          store.open=function(path,...)
            local disk=open(path,...)
            if path=='/etc/io' then
              local put,flush=disk.put,disk.flush
              disk.put=function(self,...) IO_SAVES=IO_SAVES+1;return put(self,...) end
              disk.flush=function(self,...) IO_FLUSHES=IO_FLUSHES+1;return flush(self,...) end
            end
            return disk
          end
          require('event').listen('io',function() IO_EVENTS=IO_EVENTS+1 end)
          ic=require('logistics.iochest');item={name='mod:seed',damage=0}
          function chest(n,role,x,count,size)
            local key='h'..x..'_65_2:0';INV[key]={count=count or 0,size=size or 27}
            local spec=single(n,x,2);spec.role=role;assert(st.add('storage',spec));finishAll()
            return INV[key]
          end
          REFRESH={};SEQ={};SENSOR_STATIONS={};AUTO=true
          local send=require('component').modem.send
          require('component').modem.send=function(addr,port,token,kind,id,...)
            if kind=='status' and SENSOR_STATIONS[addr] then REFRESH[addr]=id end
            return send(addr,port,token,kind,id,...)
          end
          function sensor(n,station,seq,count,size,reply)
            if not SENSOR_NAMES then SENSOR_NAMES={} end
            if not SENSOR_NAMES[n] then
              emit('modem_message','local',n,27103,0,'lgx_hello','sensor');assert(lg.registerSensor(n,n))
              SENSOR_NAMES[n]=true
            end
            SEQ[n]=math.max(SEQ[n] or 0,seq)
            local p={seq=seq,reply=reply,size=size or 27,listing=count>0 and {{name=item.name,damage=0,size=count}} or {}}
            emit('logistics_sensor',n,'report',require('serialization').serialize(p));drain()
            if station then local ok,err=ic.attach(n,station);if ok then SENSOR_STATIONS[n]=station end;return ok,err end
          end
          function record(n)
            for _,r in ipairs(ic.list()) do if r.name==n then return r end end
          end
          function count(n) local r=record(n);local v=r.listing['mod:seed:0'];return v and v.count or 0 end
          function bootSensor(n,token)
            disk['/usr/lib/logistics/drone/sensor.lua']='return true'
            token=token or require('serialization').unserialize(files['/etc/logistics.drones'])[n].token
            emit('modem_message','local',n,27103,0,token,'boot');drain()
          end
          function jobs() return #lg.jobs() end
          function fresh(n)
            local id=REFRESH[n];assert(id~=nil);REFRESH[n]=nil
            local e=map.storage(SENSOR_STATIONS[n]);local c=INV[e.node..':'..e.side]
            sensor(n,nil,(SEQ[n] or 0)+1,c.count,c.size,id)
          end
          finishHardware=finishAll
          finishAll=function()
            local rounds=0
            repeat finishHardware();if not AUTO then return end
              local names={};for n in pairs(REFRESH) do names[#names+1]=n end
              for _,n in ipairs(names) do fresh(n) end
              rounds=rounds+1;assert(rounds<20)
            until not next(REFRESH)
          end
        ''')

    def test_sensor_names_sorted_private_and_without_reads(self):
        self.lua.execute('''
          sensor('zeta',nil,1,32);sensor('alpha',nil,1,16)
          local before=jobs();local sends=0
          local modem=require('component').modem;local send=modem.send
          modem.send=function(...) sends=sends+1;return send(...) end
          local names=lg.sensors()
          assert(#names==2 and names[1]=='alpha' and names[2]=='zeta')
          names[1]='private';names[3]='not-registered'
          names=lg.sensors();assert(#names==2 and names[1]=='alpha')
          assert(#lg.drones()==6 and jobs()==before and sends==0)
        ''')

    def test_identical_sensor_reports_have_no_saves_flushes_or_events(self):
        self.lua.execute('''
          chest('out1','export',10,32);assert(sensor('s1','out1',1,32));drain()
          IO_SAVES=0;IO_FLUSHES=0;IO_EVENTS=0
          sensor('s1',nil,1,32)
          assert(IO_SAVES==0 and IO_FLUSHES==0 and IO_EVENTS==0)
          local packet=require('serialization').serialize({state='setup',seq=2,reason='no adjacent inventory'})
          emit('logistics_sensor','s1','report',packet);drain()
          assert(IO_SAVES==1 and IO_FLUSHES==1 and IO_EVENTS==1)
          assert(record('out1').reason=='no adjacent inventory')
          IO_SAVES=0;IO_FLUSHES=0;IO_EVENTS=0
          local acks=0;local ack=lg.ackSensor
          lg.ackSensor=function(...) acks=acks+1;return ack(...) end
          emit('logistics_sensor','s1','report',packet);drain()
          assert(IO_SAVES==0 and IO_FLUSHES==0 and IO_EVENTS==0 and acks==1)
        ''')

    def test_new_items_during_collection_only_collect_unreserved_amount(self):
        self.lua.execute('''
          local stock=chest('stock','stock',5,0)
          local input=chest('in1','import',10,64)
          assert(sensor('s1','in1',1,64));drain()
          input.count=96;sensor('s1',nil,2,96)
          local requests={};for id in pairs(record('in1').pending) do requests[#requests+1]=lg.status(id).requested end
          table.sort(requests);assert(#requests==2 and requests[1]==32 and requests[2]==64)
          finishAll();assert(input.count==0 and stock.count==96 and count('in1')==0)
          assert(not record('in1').reason and not wh.members().in1)
        ''')

    def test_stock_full_partial_names_left_items_without_a_retry_loop(self):
        self.lua.execute('''
          local stock=chest('stock','stock',5,60,1)
          local input=chest('in1','import',10,44)
          assert(sensor('s1','in1',1,44));drain();finishAll()
          assert(input.count==40 and stock.count==64 and count('in1')==40)
          assert(record('in1').reason:find('40',1,true) and record('in1').reason:find('in1',1,true))
          local n=jobs();for i=1,20 do drain() end;assert(jobs()==n)
          resetCalls();for i=1,20 do ic.list() end;assert(not calls.write)
        ''')

    def test_unacked_report_after_controller_reload_is_deduped(self):
        self.lua.execute('''
          chest('stock','stock',5,0);local input=chest('in1','import',10,64)
          assert(sensor('s1','in1',1,64));drain();local n=jobs()
          package.loaded["logistics.iochest"]=nil;reload();ic=require('logistics.iochest')
          local bytes=disk['/etc/io'];sensor('s1',nil,1,64)
          assert(jobs()==n and disk['/etc/io']==bytes)
          finishAll();assert(input.count==0 and count('in1')==0)
        ''')

    def test_authenticated_sensor_reboot_accepts_new_sequence_and_keeps_deduplication(self):
        self.lua.execute('''
          chest('out1','export',10,32);assert(sensor('s1','out1',5,32))
          bootSensor('s1','wrong-token');assert(record('out1').seq==5)
          bootSensor('s1');sensor('s1',nil,1,0)
          assert(record('out1').seq==1 and count('out1')==0)
          package.loaded["logistics.iochest"]=nil;reload();ic=require('logistics.iochest')
          sensor('s1',nil,1,32);assert(count('out1')==0)
          sensor('s1',nil,2,16);assert(count('out1')==16)
        ''')

    def test_sensor_reboot_reissues_outstanding_refresh_and_requires_matching_reply(self):
        self.lua.execute('''
          AUTO=false;chest('stock','stock',5,128);chest('out1','export',15,0)
          assert(sensor('s1','out1',5,0));assert(ic.fetch(item,64,'out1'));finishHardware()
          local refresh=assert(record('out1').refresh);REFRESH.s1=nil
          bootSensor('s1');assert(REFRESH.s1==refresh)
          sensor('s1',nil,1,64);assert(record('out1').refresh==refresh and count('out1')==0)
          sensor('s1',nil,2,64,27,refresh)
          assert(not record('out1').refresh and count('out1')==64)
          sensor('s1',nil,2,0,27,refresh);assert(count('out1')==64)
        ''')

    def test_sensor_reboot_preserves_inflight_import_reservations(self):
        self.lua.execute('''
          chest('stock','stock',5,0);chest('in1','import',10,64)
          assert(sensor('s1','in1',5,64));drain();local before=jobs()
          bootSensor('s1');sensor('s1',nil,1,64)
          assert(jobs()==before and record('in1').seq==1)
          finishAll();assert(count('in1')==0)
        ''')

    def test_full_export_stays_in_stock_and_reports_player_action(self):
        self.lua.execute('''
          local stock=chest('stock','stock',5,128)
          local output=chest('out1','export',15,64,1)
          assert(sensor('s1','out1',1,64,1))
          local n=jobs();local id,reason=ic.fetch(item,64,'out1')
          assert(not id and reason=='export chest full: take items from out1')
          assert(jobs()==n and stock.count==128 and output.count==64)
        ''')

    def test_player_empty_report_frees_export(self):
        self.lua.execute('''
          local stock=chest('stock','stock',5,128)
          local output=chest('out1','export',15,64,1)
          assert(sensor('s1','out1',1,64,1));output.count=0;sensor('s1',nil,2,0,1)
          assert(count('out1')==0 and not record('out1').reason)
          assert(ic.fetch(item,64,'out1'));finishAll()
          assert(stock.count==64 and output.count==64 and count('out1')==64)
        ''')

    def test_wrong_sensor_size_refused_without_an_extra_read(self):
        self.lua.execute('''
          chest('in1','import',10,0,54);local n=jobs()
          local ok,reason=sensor('s1','in1',1,0,27)
          assert(not ok and reason=='sensor sees 27 slots, expected 54')
          assert(jobs()==n and not record('in1').sensor)
        ''')

    def test_manual_import_one_read_and_manual_export_empty(self):
        self.lua.execute('''
          local stock=chest('stock','stock',5,0)
          local input=chest('in1','import',10,64)
          local output=chest('out1','export',15,0,1)
          HISTORY={};local id=ic.importNow('in1');assert(lg.status(id).steps[1].read)
          finishAll();assert(input.count==0 and stock.count==64 and count('in1')==0)
          local _,reads=counts();assert(reads==1)
          assert(ic.fetch(item,64,'out1'));finishAll()
          assert(count('out1')==64 and output.count==64)
          output.count=0;assert(ic.markEmptied('out1'));assert(count('out1')==0)
          local _,again=counts();assert(again==1)
        ''')

    def test_six_drones_two_imports_one_export_active_and_reservations(self):
        self.lua.execute('''
          local stock=chest('stock','stock',5,128)
          local a=chest('in1','import',10,640);local b=chest('in2','import',20,384)
          local output=chest('out1','export',15,0,2)
          HISTORY={};assert(sensor('s1','in1',1,640));assert(sensor('s2','in2',1,384))
          assert(sensor('s3','out1',1,0,2));assert(ic.fetch(item,128,'out1'));drain()
          local active=0;for _,d in ipairs(lg.drones()) do if d.state=='working' then active=active+1 end end
          assert(active==6,'active '..active)
          local before=jobs();local id,reason=ic.fetch(item,64,'out1')
          assert(not id and reason and jobs()==before)
          finishAll();assert(a.count==0 and b.count==0 and output.count==128 and stock.count==1024)
          local _,reads=counts();assert(reads==0)
          assert(#lg.drones()==6 and #ic.list()==3)
        ''')

    def test_double_chest_has_one_record_and_refuses_second_sensor(self):
        self.lua.execute('''
          local spec=row('double',2,1);spec.role='import';spec.pair=2
          INV['h5_65_2:0']={size=54,count=0};INV['h6_65_2:0']={size=54,count=0}
          assert(st.add('row',spec));finishAll()
          assert(#ic.list()==1 and record('double1'))
          assert(sensor('s1','double1',1,0,54))
          local ok,reason=sensor('s2','double2',1,0,54)
          assert(not ok and reason:find('already has sensor',1,true))
          assert(#ic.list()==1 and record('double1').sensor=='s1')
          assert(not wh.members().double1 and not wh.members().double2)
        ''')

    def test_report_before_receipt_needs_matching_fresh_reply(self):
        self.lua.execute('''
          AUTO=false;chest('stock','stock',5,128);local output=chest('out1','export',15,0)
          assert(sensor('s1','out1',1,0));assert(ic.fetch(item,64,'out1'))
          sensor('s1',nil,2,64);finishHardware()
          assert(count('out1')==64 and record('out1').refresh)
          fresh('s1');assert(count('out1')==64 and not record('out1').refresh)
          sensor('s1',nil,2,0);assert(count('out1')==64)
        ''')

    def test_receipt_before_report_waits_and_ignores_unmatched_reply(self):
        self.lua.execute('''
          AUTO=false;chest('stock','stock',5,128);chest('out1','export',15,0)
          assert(sensor('s1','out1',1,0));assert(ic.fetch(item,64,'out1'));finishHardware()
          assert(count('out1')==0 and record('out1').refresh)
          sensor('s1',nil,2,64,27,999);assert(record('out1').refresh)
          fresh('s1');assert(count('out1')==64 and not record('out1').refresh)
        ''')

    def test_items_added_after_take_are_replanned_from_fresh_post_job_report(self):
        self.lua.execute('''
          AUTO=false;local stock=chest('stock','stock',5,0);local input=chest('in1','import',10,64)
          assert(sensor('s1','in1',1,64));finishHardware()
          input.count=32;sensor('s1',nil,2,32)
          local before=jobs();assert(record('in1').refresh);assert(jobs()==before)
          fresh('s1');assert(jobs()==before+1);finishHardware();fresh('s1')
          assert(input.count==0 and stock.count==96 and count('in1')==0)
        ''')
