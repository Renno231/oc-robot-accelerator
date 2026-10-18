local fs=require("filesystem")
local function install(a,b) fs.makeDirectory(b);for n in fs.list(a) do local s,d=fs.concat(a,n),fs.concat(b,n);if fs.isDirectory(s) then install(s,d) else assert(fs.copy(s,d)) end end end;install('/home/program/usr','/usr')
local key="mapping-native-key"
local f=assert(io.open("/etc/mapd.cfg","w"));f:write('{key="'..key..'"}');f:close()
local case=require("case")
local event=require("event");local computer=require("computer");local component=require("component")
local map=require("logistics.map")
if case=="actions" then
  map.add("H",0,65,0,{charger=true});map.add("A",0,65,2);map.add("B",6,65,4);map.add("C",6,65,2);map.link("H","A");map.save()
  local logistics=require("logistics");local deadline=computer.uptime()+15
  while #logistics.pending()==0 and computer.uptime()<deadline do event.pull(0.1) end
  assert(logistics.register(assert(logistics.pending()[1]),"d1","H"))
else assert(package.loaded.logistics==nil,"standalone map loaded logistics") end
assert(loadfile("/usr/bin/mapd.lua"))();assert(package.loaded.mapd.port==27104)
local done=false
event.listen("modem_message",function(_,_,_,port,_,tag,receivedKey)
  if port==27104 and tag=="mapping_done" and receivedKey==key then done=true end
end)
local timer=event.timer(1,function() component.modem.broadcast(27104,"mapping_ready",key) end,math.huge)
local deadline=computer.uptime()+240
while not done and computer.uptime()<deadline do event.pull(0.1) end
event.cancel(timer);assert(done,"mapping client did not finish")
if case=="service" then
  assert(not package.loaded.logistics);assert(map.node("Alpha") and map.storage("stock").node=="Alpha")
  assert(map.route("Alpha","Bravo"));assert(map.node("UI").faces[0]);assert(not map.node("bulk01"))
  local before=map.node("Charlie");assert(map.load());assert(map.node("Charlie").created==before.created)
  assert(map.storage("stock").side==0 and map.route("Alpha","Bravo"))
  print("M1 saved map reload confirmed")
else
  assert(not next(map.node("A").faces),"scan marked map faces")
  assert(not map.route("A","B") and not map.route("A","C"),"candidate link saved")
  local d=require("logistics").drones()[1];assert(d.node=="H" and d.state=="idle")
  assert(map.load());assert(not map.route("A","B") and not map.route("A","C"))
  print("M2 no candidate saved, drone home")
end
