"""Drone survey module: native-shaped scan order, movement proof and bounds."""
from pathlib import Path
import unittest
from lupa.lua53 import LuaRuntime


class DroneSurveyTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.globals().SOURCE = Path('drone-logistics/usr/lib/logistics/drone/survey.lua').read_text()
        self.lua.execute('''
          P={x=0,y=65,z=0};ENERGY=5000;CALLS={};MOVES={};BLOCKS={};BLOCKED=false
          computer={energy=function() return ENERGY end}
          local geo={
            scan=function(...) assert(select('#',...)==6);local x,z,y,w,d,h=...
              CALLS[#CALLS+1]={x,z,y,w,d,h};ENERGY=ENERGY-10
              if w*d*h==1 then return {BLOCKS[(P.x+x)..','..(P.y+y)..','..(P.z+z)] and .04 or 0} end
              local out={};for i=1,w*d*h do out[i]=0 end;return out
            end,
            analyze=function(side) assert(side==5);return {name='minecraft:torch'} end}
          component={list=function(kind) return function() return kind end end,
            proxy=function(kind) if kind=='geolyzer' then return geo end
              return {getInventorySize=function() return nil end} end}
          function move(p)
            if BLOCKED and p.x==1 then error('blocked hop') end
            P={x=p.x,y=p.y,z=p.z};MOVES[#MOVES+1]=P
          end
          function position() return P end
          run=assert(load(SOURCE))()
        ''')

    def test_scan_before_each_hop_and_reverse(self):
        self.lua.execute('''
          local r=run({path={{x=1,y=65,z=0},{x=2,y=65,z=0}},
            scan={x=2,y=64,z=-1,w=4,d=4,h=4}},move,position)
          assert(r.scans==3 and r.hops==4 and r.energy==30 and #r.values==64)
          assert(P.x==0 and #MOVES==4 and #CALLS==3)
          assert(CALLS[3][1]==0 and CALLS[3][2]==-1 and CALLS[3][3]==-1)
        ''')

    def test_nonzero_path_refused_and_volume_range(self):
        self.lua.execute('''
          BLOCKS['1,65,0']=true
          assert(not pcall(run,{path={{x=1,y=65,z=0}}},move,position));assert(#MOVES==0)
          assert(not pcall(run,{scan={x=0,y=65,z=0,w=65,d=1,h=1}},move,position))
          assert(not pcall(run,{scan={x=32,y=65,z=0,w=2,d=1,h=1}},move,position))
        ''')

    def test_torch_exception_success_and_failure(self):
        self.lua.execute('''
          local r=run({side=5,torch={1,0,0}},move,position)
          assert(r.clear and r.hops==2 and P.x==0)
          BLOCKED=true;r=run({side=5,torch={1,0,0}},move,position)
          assert(not r.clear and r.reason:find('blocked') and P.x==0)
        ''')

    def test_survey_firmware_fits_boot_download(self):
        # logistics.lua sends the survey wrapper + agent in at most 16 x 2048-byte chunks.
        code=(b'local surveyStep=(function()\n'
              + Path('drone-logistics/usr/lib/logistics/drone/survey.lua').read_bytes() + b'\nend)()\n'
              + Path('drone-logistics/usr/lib/logistics/drone/agent.lua').read_bytes())
        self.assertLessEqual(len(code),16*2048)


if __name__ == '__main__':
    unittest.main()
