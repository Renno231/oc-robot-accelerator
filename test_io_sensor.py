from pathlib import Path
import unittest

from lupa.lua53 import LuaRuntime
import test_logistics_restart as restart


class SensorTests(unittest.TestCase):
    def start(self, sides=1):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.globals().SOURCE = Path('drone-logistics/drone/sensor.lua').read_text()
        lua.globals().SIDES = sides
        lua.execute('''
          TIME=0;N=4;SENT={}
          local tr={getInventorySize=function(side) if side<SIDES then return 27 end end,
            getAllStacks=function() return {getAll=function() return {
              {name='minecraft:coal',damage=0,label='Coal',size=N}} end} end}
          component={list=function() return function() return 'tr' end end,proxy=function() return tr end}
          computer={uptime=function() return TIME end,pullSignal=function(delay) return coroutine.yield(delay) end}
          local modem={send=function(...) SENT[#SENT+1]={...} end}
          local co=coroutine.create(function() return assert(load(SOURCE))(modem,'token','ctrl','sensor',27103) end)
          function step(dt,...)
            TIME=TIME+dt;local ok,value=coroutine.resume(co,...);assert(ok,value);assert(type(value)=='number')
          end
          function packet() return assert(load('return '..SENT[#SENT][5]))() end
          function incoming(kind,seq) step(0,'modem_message','local','ctrl',27103,0,'token',kind,seq) end
          step(0)
        ''')
        return lua

    def test_stable_two_polls_ack_and_status_resend(self):
        self.start().execute('''
          assert(#SENT==0);step(2);assert(#SENT==1 and packet().seq==1)
          assert(packet().size==27 and packet().listing[1].size==4)
          incoming('ack',1);step(10);assert(#SENT==1)
          incoming('status',7);assert(#SENT==1);step(2)
          assert(#SENT==2 and packet().seq==2 and packet().reply==7)
          incoming('ack',2);N=8;step(2);assert(#SENT==2);step(2)
          assert(#SENT==3 and packet().seq==3 and packet().listing[1].size==8 and not packet().reply)
        ''')

    def test_unacked_report_resends_after_ten_seconds(self):
        self.start().execute('''
          step(2);assert(#SENT==1);step(8);assert(#SENT==1)
          step(2);assert(#SENT==2 and packet().seq==1)
        ''')

    def test_setup_requires_exactly_one_inventory(self):
        for sides in (0, 2):
            with self.subTest(sides=sides):
                self.start(sides).execute("assert(packet().state=='setup' and packet().reason)")

    def test_firmware_byte_budget(self):
        self.assertLessEqual(Path('drone-logistics/drone/sensor.lua').stat().st_size, 1800)
        self.assertLessEqual(Path('drone-logistics/drone/loader.lua').stat().st_size, 2035)


class SensorTransportTests(unittest.TestCase):
    def test_legacy_hello_sensor_pair_download_and_scheduler_exclusion(self):
        lua = restart.LogisticsRestartTests().start('log')
        lua.execute('''
          files['/lib/logistics/sensor.lua']='return true'
          emit('modem_message','local','old',27103,0,'lgx_hello')
          emit('modem_message','local','sensoraddr',27103,0,'lgx_hello','sensor')
          assert(#lg.pending()==1 and lg.pending()[1]=='old')
          assert(#lg.pendingSensors()==1 and lg.pendingSensors()[1]=='sensoraddr')
          assert(lg.registerSensor('sensoraddr','sensor1'));assert(#lg.pendingSensors()==0)
          assert(#lg.drones()==1 and lg.drones()[1].name=='d1')
          local registry=require('serialization').unserialize(files['/etc/logistics.drones'])
          assert(registry.sensor1.kind=='sensor' and registry.sensor1.home==nil)
          local token=registry.sensor1.token;SENT={}
          emit('modem_message','local','sensoraddr',27103,0,token,'boot')
          assert(#SENT==2 and SENT[1].kind=='code' and SENT[2].kind=='start')
          local forwarded
          require('event').listen('logistics_sensor',function(_,name,kind,payload)
            forwarded={name,kind,payload}
          end)
          emit('modem_message','local','sensoraddr',27103,0,token,'report','payload');drain()
          assert(forwarded[1]=='sensor1' and forwarded[2]=='report' and forwarded[3]=='payload')
          lg.ackSensor('sensor1',7);assert(SENT[#SENT].kind=='ack' and SENT[#SENT].id==7)
          assert(lg.forget('sensor1')==false)
          assert(lg.found('sensor1')==nil)
          local id=fetch();assert(lg.status(id).state=='active')
          assert(#lg.drones()==1 and lg.drones()[1].name=='d1')
        ''')
