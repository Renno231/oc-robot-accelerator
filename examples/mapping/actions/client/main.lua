local fs=require("filesystem")
local function install(a,b) fs.makeDirectory(b);for n in fs.list(a) do local s,d=fs.concat(a,n),fs.concat(b,n);if fs.isDirectory(s) then install(s,d) else assert(fs.copy(s,d)) end end end;install('/home/program/usr','/usr')
local key="mapping-native-key"
local f=assert(io.open("/etc/mapclient.cfg","w"));f:write('return {key="'..key..'",position=function() return 1.9,65.7,-0.1 end}');f:close()
local api=require("logistics.mapclient");local client=api.new()
local event=require("event");local computer=require("computer");local component=require("component");local serialization=require("serialization")
local deadline=computer.uptime()+20
local ready=false
repeat local e={event.pull(0.5,"modem_message")};ready=e[4]==27104 and e[6]=="mapping_ready" and e[7]==key until ready or computer.uptime()>deadline
assert(ready,"map service readiness missing")
local replies,maxPacket=0,0
event.listen("modem_message",function(_,_,_,port,_,tag,_,_,_,_,data)
  if port==27104 and tag=="mapreply" then replies=replies+1;maxPacket=math.max(maxPacket,type(data)=="string" and #data or 0) end
end)
local function call(op,args)
  local result,err,ok=client:request(op,args);assert(ok,type(err)=="table" and err.reason or err);return result
end
if require("case")=="service" then
  local p=assert(client:position());assert(p.x==1 and p.y==65 and p.z==-1)
  p=api.nudge(p,"x",-1);assert(p.x==0)
  local manual=api.new({key=key});assert(not manual:position())
  local failing=api.new({key=key,position=function() error("GPS unavailable") end});assert(not failing:position())
  for i,name in ipairs({"Alpha","Bravo","Charlie"}) do call("add",{name,i,65,i,{}}) end
  local nodes=assert(client:nodes());assert(nodes[1].name=="Charlie" and nodes[2].name=="Bravo" and nodes[3].name=="Alpha")
  assert(client:nodes("ALP")[1].name=="Alpha" and #client:nodes("nothere")==0)
  call("link",{"Alpha","Bravo"});call("name",{"stock","Alpha",0});call("name",{"temp","Bravo",1})
  assert(call("storage",{"stock"}).node=="Alpha" and assert(client:list("storages")).temp.side==1)
  assert(call("unname",{"temp"}));assert(call("storage",{"temp"})==nil)
  call("unlink",{"Alpha","Bravo"});call("link",{"Alpha","Bravo"});call("save",{})
  local wrong=api.new({key="wrong-key",address=client.address});local _,err,ok=wrong:request("remove",{"Alpha"},1)
  assert(not ok and err=="map request timed out");assert(call("node",{"Alpha"}))
  local _,missing,loaded=client:request("scan",{"Alpha"});assert(not loaded and tostring(missing):find("logistics not loaded",1,true))
  for i=1,70 do call("add",{string.format("bulk%02d",i),i,65,0,{faces={[0]=true,[1]=true,[2]=true,[3]=true,[4]=true}}}) end
  local before=replies;nodes=assert(client:nodes());assert(#nodes==73 and replies-before>=2,"nodes not paged")
  call("remove",{"bulk01"})
  -- Native OpenOS stdin is a file handle; execute the actual tablet script.
  local input=assert(io.open("/home/ui-input.txt","w"))
  input:write("here\n\n\n\nadd\nUI\nn\nfaces\ny\nn\nn\nn\nn\nn\nname\nui-storage\n0\nunname\nui-storage\nquit\n");input:close()
  local old=io.input();io.input("/home/ui-input.txt")
  assert(loadfile("/usr/bin/mapclient.lua"))();io.input(old)
  assert(call("node",{"UI"}).x==1 and call("node",{"UI"}).faces[0])
  assert(call("storage",{"ui-storage"})==nil)
  print("M1 standalone/paging/wrong-key/GPS/manual/UI passed")
else
  local scan=call("scan",{"A"});assert(scan.state=="done" and scan.scan[0]==27)
  for side=1,5 do assert(scan.scan[side]==nil,"unexpected inventory side "..side) end
  assert(not next(call("node",{"A"}).faces));print("scan",serialization.serialize(scan))
  local clear=call("test",{"A","B"});assert(clear.test=="ok" and clear.state=="done");print("clear",serialization.serialize(clear))
  local blocked=call("test",{"A","C"});assert(blocked.test=="blocked" and blocked.state=="failed")
  assert(blocked.blockedReports[1].stalledSeconds>=3 and blocked.blockedReports[1].stalledSeconds<4);print("blocked",serialization.serialize(blocked))
end
assert(maxPacket<=6000);print("map replies",replies,"largest serialized reply",maxPacket)
component.modem.send(client.address,27104,"mapping_done",key)
