local map=require('logistics.map');local wh=require('logistics.warehouse');local lg=require('logistics')
local function node(x,y,z,faces,charger)
  local name=x..':'..y..':'..z
  if not map.node(name) then map.add(name,x,y,z,{faces=faces,charger=charger}) end
  return name
end
local H=node(-2,65,2,nil,true);local H2=node(-2,65,5,nil,true)
node(-2,65,3);node(-2,65,4);node(-1,65,2)
for x=0,7 do for y=0,3 do
  local n=node(x,65+y,2,{[2]=true,[3]=true})
  for _,w in ipairs({'N','S'}) do local s='s'..x..'_'..y..'_'..w;map.name(s,n,w=='N' and 2 or 3);wh.add(s) end
end end
for x=8,10 do node(x,65,2) end
for z=3,9 do node(9,65,z) end
for z=7,9 do node(9,64,z);node(9,63,z) end
for _,v in ipairs({{'A',7},{'B',9}}) do
  local n,z=v[1],v[2]
  map.name('furn'..n..'.in',node(10,65,z,{[0]=true}),0)
  map.name('furn'..n..'.fuel',node(9,64,z,{[5]=true}),5)
  map.name('furn'..n..'.out',node(10,63,z,{[1]=true}),1)
  wh.group('furnace'..n,'furnace',{input='furn'..n..'.in',fuel='furn'..n..'.fuel',output='furn'..n..'.out'})
end
map.name('cpu1.buf','8:65:2',2)
wh.group('cpu1','crafter',{buffer='cpu1.buf'})
-- Drones have no hitboxes for each other: all six share one charger.
map.add('-2:65:2',-2,65,2,{charger=true})
local homes={}
for i=1,6 do homes[i]='-2:65:2' end
local nodes=map.nodes()
for a,p in pairs(nodes) do for b,q in pairs(nodes) do
  if a<b and math.abs(p.x-q.x)+math.abs(p.y-q.y)+math.abs(p.z-q.z)==1 then map.link(a,b) end
end end
map.save()
-- Dedicated destinations make native chest expectations deterministic.
for _,v in ipairs({{'minecraft:planks','s3_0_N'},{'minecraft:stick','s4_0_N'},
                   {'minecraft:coal','s6_0_N',1},{'minecraft:brick','s6_0_N'},
                   {'minecraft:torch','s5_0_N'},{'minecraft:brick_block','s5_0_N'}}) do
  local filter={{name=v[1],damage=v[3] or 0}}
  if v[2]=='s6_0_N' then filter={{name='minecraft:coal',damage=1},{name='minecraft:brick',damage=0}} end
  if v[2]=='s5_0_N' then filter={{name='minecraft:torch',damage=0},{name='minecraft:brick_block',damage=0}} end
  wh.add(v[2],{filter=filter,priority=10})
end
return {homes=homes}
