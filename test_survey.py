"""Survey grouping and transitions using real CBOR persistence, no Minecraft."""
from pathlib import Path
import unittest
from lupa.lua53 import LuaRuntime
from test_store import install_store


class SurveyTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute('''
          local function encode(v)
            if type(v)=='table' then local out={'{'}
              for k,a in pairs(v) do out[#out+1]='['..encode(k)..']='..encode(a)..',' end
              out[#out+1]='}';return table.concat(out)
            elseif type(v)=='string' then return string.format('%q',v) else return tostring(v) end
          end
          package.preload.serialization=function() return {serialize=encode,
            unserialize=function(s) return assert(load('return '..s))() end} end
        ''')
        install_store(self.lua)
        self.lua.globals().SOURCE = Path('drone-logistics/usr/lib/logistics/survey.lua').read_text()
        self.lua.execute('''
          LISTEN={};EVENTS={};JOBS={};REQUESTS={};KNOWN={};ANALYZED={};HOPS={};GRID={};BLOCKS={}
          local nodes={origin={x=0,y=65,z=0},home={x=-1,y=65,z=0}}
          package.preload["logistics.map"]=function() return {nodes=function() return nodes end,
            node=function(n) return nodes[n] end,links=function() return {'home'} end,
            storages=function() return {} end} end
          package.preload["logistics.stations"]=function() return {
            list=function() return KNOWN end,get=function(n) return KNOWN[n] end,
            add=function(kind,spec) REQUESTS[#REQUESTS+1]={kind=kind,spec=spec};return spec.prefix end} end
          package.preload.logistics=function() return {
            drones=function() return {{survey=true}} end,
            probe=function(n,c) local id=#JOBS+1;JOBS[id]={node=n,command=c,state='queued'};return id end,
            status=function(id) return JOBS[id] end} end
          package.preload.event=function() return {
            listen=function(n,f) LISTEN[n]=LISTEN[n] or {};table.insert(LISTEN[n],f) end,
            push=function(...) EVENTS[#EVENTS+1]={...} end} end
          function emit(n,...) for _,f in ipairs(LISTEN[n] or {}) do f(n,...) end end
          function k(p) return p.x..','..p.y..','..p.z end
          local directions={{0,-1,0},{0,1,0},{0,0,-1},{0,0,1},{-1,0,0},{1,0,0}}
          function complete()
            for id,j in ipairs(JOBS) do if j.state=='queued' then
              local c=j.command;local r={hops=0,scans=0,analyzes=0,energy=10};local p={x=0,y=65,z=0}
              for _,q in ipairs(c.path) do
                assert(math.abs(p.x-q.x)+math.abs(p.y-q.y)+math.abs(p.z-q.z)==1)
                assert((GRID[k(q)] or 0)==0 or q.torch,'hop crossed unproved non-air')
                assert(SCANNED[k(q)],'hop not scanned');p=q;r.hops=r.hops+2;HOPS[#HOPS+1]=q
              end
              if c.scan then
                local t=c.scan;r.values={};assert(t.w*t.d*t.h<=64)
                for y=t.y,t.y+t.h-1 do for z=t.z,t.z+t.d-1 do for x=t.x,t.x+t.w-1 do
                  assert(math.abs(x-p.x)<=32 and math.abs(y-p.y)<=32 and math.abs(z-p.z)<=32)
                  local q={x=x,y=y,z=z};r.values[#r.values+1]=GRID[k(q)] or 0;SCANNED[k(q)]=true
                end end end;r.scans=1
              else
                local d=directions[c.side+1];local q={x=p.x+d[1],y=p.y+d[2],z=p.z+d[3]}
                r.block=BLOCKS[k(q)] or {name='minecraft:air'};r.size=r.block.size;r.analyzes=1
                ANALYZED[#ANALYZED+1]=k(q)
                if r.block.name=='minecraft:torch' then r.clear=true;r.hops=r.hops+2 end
              end
              j.state='done';emit('survey_result',id,require('serialization').serialize(r));emit('logistics',id);return true
            end end
          end
          function finish() local n=0;while complete() do n=n+1;assert(n<500) end end
          SCANNED={};sv=assert(load(SOURCE))()
          function chest(x,y,z,faces,size)
            return {x=x,y=y,z=z,faces=faces or {'north'},name='minecraft:chest',size=size or 27,
              paths={north={{x=x,y=y,z=z-1}},top={{x=x,y=y+1,z=z}}}}
          end
        ''')

    def test_wall_double_and_choose_groups(self):
        self.lua.execute('''
          local c={}
          for y=64,66 do for x=2,5 do c[#c+1]=chest(x,y,10) end end
          for x=8,13 do c[#c+1]=chest(x,64,10,nil,54) end
          c[#c+1]=chest(16,64,10,{'north','top'})
          local g=sv.group(c);assert(#g==3)
          local wall,double,choose
          for _,v in ipairs(g) do if v.kind=='wall' then wall=v
            elseif v.face=='choose' then choose=v else double=v end end
          assert(wall and #wall.inventories==12 and wall.levels==3 and wall.face=='north')
          assert(double and #double.inventories==3 and double.spacing==2 and double.pair==2)
          assert(double.inventories[1].parts[2].x==9)
          assert(choose and choose.role=='?' and #choose.faces==2)
          local st=require('logistics.store').open('/group','log');st:put('g',g);st:flush()
          assert(#st:load().g==3) -- double parts must not be a cyclic table
        ''')

    def test_tiles_cap_and_integer_validation(self):
        self.lua.execute('''
          local a={x1=-4,y1=64,z1=0,x2=27,y2=79,z2=31}
          local count=0
          for _,t in ipairs(sv.tiles(a)) do assert(t.w*t.h*t.d<=64);count=count+t.w*t.h*t.d end
          assert(count==32*16*32)
          a.x2=28;local id,reason=sv.request(a);assert(not id and reason:find('cap'))
          a.x2=27.5;assert(not sv.request(a))
        ''')

    def test_physical_proposal_mismatch_approval_restart(self):
        self.lua.execute('''
          GRID['2,65,0']=2.5;BLOCKS['2,65,0']={name='minecraft:chest',size=27}
          GRID['4,65,0']=3.5;BLOCKS['4,65,0']={name='minecraft:furnace',size=1}
          KNOWN[1]={name='old'};KNOWN.old={members={{x=3,y=65,z=0}}}
          local id=assert(sv.request({x1=1,y1=65,z1=0,x2=4,y2=65,z2=0}));finish()
          local r=sv.get(id);assert(r.state=='proposed',r.reason)
          assert(#r.groups==1 and r.groups[1].face=='choose' and r.groups[1].role=='?')
          assert(#r.mismatches==1 and r.mismatches[1].block.name=='minecraft:air')
          local oldReads=0;for _,p in ipairs(ANALYZED) do if p=='3,65,0' then oldReads=oldReads+1 end end
          assert(oldReads==1 and KNOWN.old.members[1].x==3)
          assert(#r.ignored==1 and r.ignored[1].kind:find('S2'))
          assert(r.trips==nil and r.metrics.scans>0 and r.metrics.analyzes>0)
          assert(not sv.approve(id,{[1]={prefix='stock'}}))
          assert(not sv.approve(id,{[1]={prefix='stock',role='stock'}}))
          -- Previously persisted diagnostics can be discarded without losing the proposal.
          local store=require('logistics.store').open('/etc/survey','log')
          r.trips={{job=1,command={path={{x=0,y=65,z=0}}}}}
          store:put('sv_'..id,r);store:flush()
          LISTEN={};sv=assert(load(SOURCE))();r=sv.get(id)
          assert(r.state=='proposed' and r.limitation:find('same density'))
          assert(r.trips==nil and require('logistics.store').open('/etc/survey','log'):load()['sv_'..id].trips==nil)
          assert(sv.approve(id,{[1]={prefix='stock',role='stock',face='top'}}))
          assert(#REQUESTS==1 and REQUESTS[1].spec.paths[1][1].x==0)
          assert(sv.get(id).state=='approved')
        ''')

    def test_known_solid_member_not_analyzed(self):
        self.lua.execute('''
          GRID['2,65,0']=2.5;BLOCKS['2,65,0']={name='minecraft:chest',size=27}
          KNOWN[1]={name='old'};KNOWN.old={members={{x=2,y=65,z=0}}}
          local id=assert(sv.request({x1=2,y1=65,z1=0,x2=2,y2=65,z2=0}));finish()
          assert(sv.get(id).state=='proposed' and #ANALYZED==0 and #sv.get(id).groups==0)
        ''')

    def test_torch_gets_explicit_proof(self):
        self.lua.execute('''
          GRID['1,65,0']=.04;BLOCKS['1,65,0']={name='minecraft:torch'}
          local id=assert(sv.request({x1=1,y1=65,z1=0,x2=1,y2=65,z2=0}));finish()
          assert(sv.get(id).state=='proposed' and #ANALYZED==1)
          assert(sv.get(id).metrics.analyzes==1 and sv.get(id).metrics.hops>=2)
        ''')

    def test_far_area_connects_by_scanned_air_not_remote_density_only(self):
        self.lua.execute('''
          GRID['40,65,0']=2.5;BLOCKS['40,65,0']={name='minecraft:chest',size=27}
          local id=assert(sv.request({x1=40,y1=65,z1=0,x2=40,y2=65,z2=0}));finish()
          local r=sv.get(id);assert(r.state=='proposed',r.reason)
          assert(#r.groups==1 and r.groups[1].inventories[1].x==40)
          assert(#HOPS>0 and #JOBS>10)
        ''')

    def test_final_faces_include_newly_proven_torch_air_without_reanalyzing(self):
        self.lua.execute('''
          GRID['1,65,0']=.04;BLOCKS['1,65,0']={name='minecraft:torch'}
          GRID['2,65,0']=2.5;BLOCKS['2,65,0']={name='minecraft:chest',size=27}
          local id=assert(sv.request({x1=1,y1=65,z1=0,x2=2,y2=65,z2=0}));finish()
          local r=sv.get(id);assert(r.state=='proposed' and #r.groups==1)
          assert(r.groups[1].face=='choose' and #r.groups[1].faces==6)
          assert(#ANALYZED==2,'known chest was re-analyzed after torch proof')
        ''')


if __name__ == '__main__':
    unittest.main()
