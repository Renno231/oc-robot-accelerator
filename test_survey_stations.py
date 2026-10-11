"""Supplied survey geometry commissions through the real S1 job lifecycle."""
import unittest
import test_stations


class SuppliedStationsTests(unittest.TestCase):
    def setUp(self):
        fixture = test_stations.StationsTests(); fixture.setUp(); self.lua = fixture.lua
        self.lua.execute('''
          function supplied()
            return {x=5,y=64,z=2,face='top',role='stock',prefix='wall',spacing=2,pair=2,
              members={{x=5,y=64,z=2,alias=1},{x=6,y=64,z=2,alias=1},
                {x=5,y=65,z=2,alias=3},{x=6,y=65,z=2,alias=3}},
              paths={
                {{x=0,y=65,z=0},{x=0,y=65,z=2},{x=5,y=65,z=2}},
                {{x=0,y=65,z=0},{x=0,y=65,z=2},{x=5,y=65,z=2},{x=6,y=65,z=2}},
                {{x=0,y=65,z=0},{x=0,y=65,z=2},{x=0,y=66,z=2},{x=5,y=66,z=2}},
                {{x=0,y=65,z=0},{x=0,y=65,z=2},{x=0,y=66,z=2},{x=5,y=66,z=2},{x=6,y=66,z=2}}}}
          end
        ''')

    def test_every_supplied_edge_proved_before_registering_wall(self):
        self.lua.execute('''
          local spec=supplied();assert(st.add('wall',spec))
          assert(st.get('wall').phase=='path' and not wh.members().wall1)
          finishAll();local r=st.get('wall');assert(r.state=='ready',r.reason)
          local tests,reads=counts();assert(tests==6 and reads==2,tests..'/'..reads)
          assert(#r.created.links==6 and #r.members==4)
          assert(wh.members().wall2.inventory=='wall1' and wh.members().wall4.inventory=='wall3')
          assert(wh.count({name='mod:seed',damage=0})==4)
          assert(not st.remove('wall')) -- one removal unit, asks about all stock
          assert(st.remove('wall',{items='forget'}));assert(not st.get('wall'))
          assert(not map.node('h0_65_2') and not map.storage('wall4'))
        ''')

    def test_supplied_path_failure_and_restart(self):
        self.lua.execute('''
          assert(st.add('wall',supplied()));drain();assert(finishOne());drain()
          assert(st.get('wall').nextLink==2)
          reload();finishAll();assert(st.get('wall').state=='ready')
        ''')

    def test_bad_path_rejected_without_mutation(self):
        self.lua.execute('''
          local s=supplied();s.paths[1][1]={x=99,y=65,z=0}
          assert(not st.add('wall',s));assert(not map.storage('wall1') and #st.list()==0)
          s=supplied();s.paths[1][3]={x=7,y=65,z=2}
          assert(not st.add('wall',s));assert(not map.node('h7_65_2'))
        ''')

    def test_capability_preference_and_ephemeral_result_transport(self):
        self.lua.execute('''
          report('remote1',0,{state='ready',survey=true,freeMemory=32000});drain()
          assert(lg.drones()[1].survey)
          local id=assert(st.add('storage',single('ordinary')));drain()
          assert(not FAKES.remote1.task,'ordinary work stole the survey carrier');finishAll()
          local got
          require('event').listen('survey_result',function(_,job,payload)
            assert(type(payload)=='string');got=require('serialization').unserialize(payload)
          end)
          local job=lg.probe('home1',{path={},scan={x=1,y=65,z=0,w=2,h=1,d=1}});drain()
          assert(FAKES.remote1.task and FAKES.remote1.task.action.kind=='survey')
          for addr,f in pairs(FAKES) do if addr~='remote1' then assert(not f.task) end end
          FAKES.remote1.task=nil
          report('remote1',FAKES.remote1.id,{state='idle',survey={values={0,2.5},scans=1,hops=0,analyzes=0,energy=10}});drain()
          assert(got and got.values[2]==2.5 and lg.status(job).state=='done')
          assert(lg.drones()[1].survey==true,'scan payload replaced capability mark')
          assert(not disk['/etc/logistics.state']:find('values',1,true),'raw grid persisted in logistics')
        ''')

    def test_removing_one_group_does_not_break_shared_approach(self):
        self.lua.execute('''
          assert(st.add('wall',supplied()));finishAll()
          local s={x=7,y=64,z=2,face='top',role='other',name='another',
            members={{x=7,y=64,z=2}},paths={{{x=0,y=65,z=0},{x=0,y=65,z=2},
              {x=5,y=65,z=2},{x=6,y=65,z=2},{x=7,y=65,z=2}}}}
          assert(st.add('storage',s));finishAll()
          assert(st.remove('wall',{items='forget'}))
          assert(st.get('another').state=='ready' and map.node('h0_65_2'))
          assert(map.route('home1','h7_65_2'),'removing wall broke other supplied path')
        ''')

    def test_parallel_units_wait_for_catalogue_before_membership_edits(self):
        self.lua.execute('''
          -- Native OpenOS handler order is not the fake's insertion order.
          local callbacks=LISTEN.logistics;assert(#callbacks==2)
          LISTEN.logistics={callbacks[2],callbacks[1]}
          assert(st.add('wall',supplied()))
          local s=single('second',10,4);assert(st.add('storage',s))
          finishAll()
          assert(st.get('wall').state=='ready' and st.get('second').state=='ready')
          assert(wh.count({name='mod:seed',damage=0})==6,'membership edits invalidated commissioning reads')
          local _,reads=counts();assert(reads==3,'commissioning re-read inventories')
        ''')


if __name__ == '__main__':
    unittest.main()
