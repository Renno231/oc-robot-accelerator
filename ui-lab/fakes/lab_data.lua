-- Fixture world for the UI lab: a storage room, two furnaces, a crafter.
local D={nodes={},storages={},members={},groups={},items={},jobs={},drones={},revision=1}
local function node(name,x,y,z) D.nodes[name]={x=x,y=y,z=z,faces={},charger=false,created=#D.nodes+1} end
for x=0,7 do for y=0,3 do
  local n=x..":"..(65+y)..":2";node(n,x,65+y,2)
  for _,w in ipairs({"N","S"}) do
    local s="s"..x.."_"..y.."_"..w;D.storages[s]={node=n,side=w=="N" and 2 or 3};D.nodes[n].faces[w=="N" and 2 or 3]=true
    D.members[s]={}
  end
end end
node("-2:65:2",-2,65,2);D.nodes["-2:65:2"].charger=true
node("10:66:4",10,66,4);node("9:65:4",9,65,4);node("10:64:4",10,64,4)
node("13:66:4",13,66,4);node("12:65:4",12,65,4);node("13:64:4",13,64,4)
node("4:65:7",4,65,7)
D.storages["furnA.in"]={node="10:66:4",side=0};D.storages["furnA.fuel"]={node="9:65:4",side=5};D.storages["furnA.out"]={node="10:64:4",side=1}
D.storages["furnB.in"]={node="13:66:4",side=0};D.storages["furnB.fuel"]={node="12:65:4",side=5};D.storages["furnB.out"]={node="13:64:4",side=1}
D.storages["cpu1.buf"]={node="4:65:7",side=3}
D.members.s0_0_N={filter={{name="minecraft:brick",damage=0}},priority=5};D.members.s1_0_N={priority=1}
D.groups.furnaceA={type="furnace",roles={input="furnA.in",fuel="furnA.fuel",output="furnA.out"}}
D.groups.furnaceB={type="furnace",roles={input="furnB.in",fuel="furnB.fuel",output="furnB.out"}}
D.groups.cpu1={type="crafter",roles={buffer="cpu1.buf"}}
node("6:65:7",6,65,7);D.storages["cpu2.buf"]={node="6:65:7",side=3};D.groups.cpu2={type="crafter",roles={buffer="cpu2.buf"}}
-- Free non-stock chests: buffers for a robot being registered.
node("8:65:7",8,65,7);D.storages["chest8"]={node="8:65:7",side=3};D.storages["chest9"]={node="8:65:7",side=2}
local stock={
  {"minecraft:log",0,"Oak Wood",192},{"minecraft:log",1,"Spruce Wood",64},{"minecraft:planks",0,"Oak Wood Planks",37},
  {"minecraft:stick",0,"Stick",12},{"minecraft:coal",0,"Coal",20},{"minecraft:coal",1,"Charcoal",0},
  {"minecraft:clay_ball",0,"Clay",128},{"minecraft:brick",0,"Brick",9},{"minecraft:cobblestone",0,"Cobblestone",2311},
  {"minecraft:iron_ingot",0,"Iron Ingot",141},{"minecraft:iron_ore",0,"Iron Ore",58},{"minecraft:gold_ingot",0,"Gold Ingot",17},
  {"minecraft:redstone",0,"Redstone",880},{"minecraft:glass",0,"Glass",96},{"minecraft:sand",0,"Sand",412},
  {"minecraft:torch",0,"Torch",3},{"minecraft:string",0,"String",44},{"minecraft:paper",0,"Paper",61},
  {"opencomputers:material",0,"Cutting Wire",4},{"opencomputers:material",4,"Printed Circuit Board",22},
  {"opencomputers:material",7,"Microchip (Tier 1)",30},{"opencomputers:material",8,"Microchip (Tier 2)",12},
  {"opencomputers:material",10,"Arithmetic Logic Unit",6},{"opencomputers:material",11,"Control Unit",2},
  {"minecraft:diamond",0,"Diamond",7},{"minecraft:emerald",0,"Emerald",3},{"minecraft:obsidian",0,"Obsidian",14},
  {"minecraft:quartz",0,"Nether Quartz",75},{"minecraft:slime_ball",0,"Slimeball",9},{"minecraft:leather",0,"Leather",28},
  {"minecraft:wool",0,"White Wool",19},{"minecraft:wool",14,"Red Wool",5},{"minecraft:dye",4,"Lapis Lazuli",63},
  {"minecraft:gravel",0,"Gravel",120},{"minecraft:flint",0,"Flint",33},{"minecraft:stone",0,"Stone",640},
  {"minecraft:stonebrick",0,"Stone Bricks",128},{"minecraft:chest",0,"Chest",11},{"minecraft:hopper",0,"Hopper",2},
}
for k,s in ipairs(stock) do D.items[k]={item={name=s[1],damage=s[2],label=s[3]},count=s[4],storages=1+(s[4]//200)} end
local states={"done","done","done","partial","failed","running","queued"}
local names={"s0_0_N","s3_1_S","s7_3_N","furnA.in","furnB.out","cpu1.buf","s5_2_S"}
for id=1,60 do
  local i=D.items[(id%#D.items)+1].item;local st=id>57 and (id==60 and "running" or "queued") or states[(id%5)+1]
  local req=(id*7)%64+1
  D.jobs[id]={id=id,state=st,requested=req,moved=st=="done" and req or st=="partial" and req//2 or 0,item=i,
    from={storage=names[(id%7)+1]},to={storage=names[((id+3)%7)+1]},reason=st=="failed" and "drone d2: route blocked at 5:66:2" or nil}
end
-- Fleet: 6 registered drones in every state (one lost: as logistics marks it,
-- job and trip cleared; one held), 2 announcing,
-- 8 chargers of which 2 are free.
for k=2,8 do local n="-2:65:"..(2*k);node(n,-2,65,2*k);D.nodes[n].charger=true end
local function st(name,d,n,label) return {name=name,damage=d,label=label,size=n,maxSize=64} end
D.drones={
  {name="drone1",address="a1b2c3d4-0001-4e00-8000-000000000001",state="idle",node="-2:65:2",home="-2:65:2",energy=4800,cargoSlots=8,cargo={}},
  {name="drone2",address="b2c3d4e5-0002-4e00-8000-000000000002",state="working",node="3:66:2",home="-2:65:4",energy=3100,cargoSlots=8,job=58,trip=112,
    cargo={st("minecraft:iron_ingot",0,64,"Iron Ingot"),st("minecraft:iron_ingot",0,64,"Iron Ingot"),st("minecraft:coal",0,20,"Coal")}},
  {name="drone3",address="c3d4e5f6-0003-4e00-8000-000000000003",state="held",node="-2:65:6",home="-2:65:6",energy=4100,cargoSlots=8,
    cargo={st("minecraft:brick",0,64,"Brick"),st("minecraft:clay_ball",0,9,"Clay")},
    held={{item={name="minecraft:brick",damage=0,label="Brick"},count=64},{item={name="minecraft:clay_ball",damage=0,label="Clay"},count=9}}},
  {name="drone4",address="d4e5f6a7-0004-4e00-8000-000000000004",state="charging",node="-2:65:8",home="-2:65:8",energy=900,cargoSlots=8},
  {name="drone5",address="e5f6a7b8-0005-4e00-8000-000000000005",state="lost",home="-2:65:10",energy=150,cargoSlots=8,lost=true,
    cargo={st("minecraft:sand",0,64,"Sand")}},
  {name="drone6",address="f6a7b8c9-0006-4e00-8000-000000000006",state="booting",node="-2:65:12",home="-2:65:12",cargoSlots=8},
}
D.announcing={"9c1d2e3f-aaaa-4bbb-8ccc-dddddddddd01","7b8a9f0e-1111-4222-8333-444444444402"}
return D
