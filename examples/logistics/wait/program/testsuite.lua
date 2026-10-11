-- Native acceptance entry, copied with the canonical libraries into each program tree.
return function(case)
  local fs=require("filesystem")
  fs.makeDirectory("/lib/logistics")
  for _,name in ipairs({"cbor","store","map","logistics"}) do assert(fs.copy("/home/program/lib/"..name..".lua","/lib/"..name..".lua")) end
  assert(fs.copy("/home/program/drone/agent.lua","/lib/logistics/agent.lua"))
  assert(fs.copy("/home/program/bin/logistics.lua","/bin/logistics.lua"))
  local file=assert(io.open("/etc/logistics.cfg","w"))
  file:write("{reserve="..(case=="power" and 4990 or 1000)..",retries=2}");file:close()
  local event=require("event")
  local computer=require("computer")
  local map=require("map")
  local serialization=require("serialization")
  local component=require("component")
  local function check(ok,message) assert(ok,message or "acceptance assertion") end
  map.add("H",0,65,0,{charger=true})
  map.add("H2",0,65,-3,{charger=true})
  map.add("A",0,65,2,{faces={[0]=true}})
  map.add("M",3,65,2)
  map.add("B",6,65,2,{faces={[0]=true}})
  map.add("O",6,65,4,{faces={[0]=true}})
  map.add("B2",6,65,6,{faces={[0]=true}})
  map.link("H","A");map.link("H2","H");map.link("A","M");map.link("M","B");map.link("B","O")
  map.link("B","B2")
  if case=="steps" then
    map.add("E",3,65,6,{faces={[0]=true}});map.link("B2","E")
  elseif case=="blocked" then
    map.add("detour1",3,65,4);map.add("detour2",6,65,4)
    map.link("M","detour1");map.link("detour1","detour2");map.link("detour2","B")
  elseif case=="furnace" then
    map.add("FS",5,64,2,{faces={[5]=true}})
    map.add("FB",6,63,2,{faces={[1]=true}})
    map.add("FS-air",5,65,2);map.add("FB-air",5,63,2)
    map.link("M","FS-air");map.link("FS-air","FS");map.link("FS","FB-air");map.link("FB-air","FB")
  end
  check(#map.route("A","B")==3,"two-link route")
  check((map.route("A","B",{["M:B"]=true})~=nil)==(case=="blocked"),"avoid link")
  map.unlink("M","B");check((map.route("A","B")~=nil)==(case=="blocked"));map.link("M","B")
  local independent=map.node("A");independent.x=999;check(map.node("A").x==0)
  map.add("temporary",1,65,1);map.link("H","temporary");map.remove("temporary");check(not map.node("temporary"))
  map.save();check(map.load());check(#map.route("A","B")==3)
  if case=="names" then
    check(map.node("H").created<map.node("A").created and map.node("A").created<map.node("B").created,"creation order")
    map.name("iron-source","A",0);map.name("iron-destination","B",0)
    map.name("temporary-name","O",0);check(map.unname("temporary-name"));check(not map.storage("temporary-name"))
    map.save();check(map.load());check(map.storage("iron-source").node=="A" and map.storages()["iron-destination"].side==0)
    check(not pcall(map.name,"duplicate-face","A",0),"duplicate face accepted")
    check(not pcall(map.name,"B","A",1),"storage named like a node accepted")
    check(not pcall(map.add,"iron-source",0,65,0),"node named like a storage accepted")
    check(map.place("iron-source")=="A" and map.place("B")=="B" and map.place("missing")==nil,"place")
  end
  -- Commissioning fixture knows both physical charger positions. Distinct native
  -- radio distances identify their announcements, not an agent position sensor.
  local distances={}
  event.listen("modem_message",function(_,_,sender,port,distance,first)
    if port==27103 and first=="lgx_hello" then distances[sender]=distance end
  end)
  local logistics=require("logistics")
  if case=="names" then
    local byStorage,byNode=logistics.plan("iron-source","iron-destination"),logistics.plan("A","B")
    check(#byStorage==#byNode and byStorage[1].name=="A" and byStorage[#byStorage].name=="B","plan by storage name")
  end
  local function untilTrue(predicate,seconds,message)
    local deadline=computer.uptime()+seconds
    repeat if predicate() then return end;event.pull(math.max(0.1,deadline-computer.uptime())) until computer.uptime()>deadline
    error(message or "timeout")
  end
  local count=(case=="split" or case=="wait" or case=="fixes" or case=="steps") and 2 or 1
  untilTrue(function() return #logistics.pending()>=count end,15,"announcements missing")
  local pending=logistics.pending()
  if count==2 then table.sort(pending,function(a,b) return distances[a]<distances[b] end) end
  local bootTimes,dropUntil={},nil
  if case=="fixes" then
    local send=component.modem.send
    component.modem.send=function(address,port,token,kind,...)
      if address==pending[1] and (kind=="code" or kind=="start") then
        dropUntil=dropUntil or computer.uptime()+4
        if computer.uptime()<dropUntil then return true end
        component.modem.send=send
      end
      return send(address,port,token,kind,...)
    end
    event.listen("modem_message",function(_,_,sender,port,_,_,kind)
      if sender==pending[1] and port==27103 and kind=="boot" then bootTimes[#bootTimes+1]=computer.uptime() end
    end)
  end
  local pairedCount=case=="split" and 1 or count
  for i=1,pairedCount do check(logistics.register(pending[i],"d"..i,i==1 and "H" or "H2")) end
  check(not logistics.register("unknown-address","unknown","H"),"unknown register accepted")
  -- These are ordinary caller sleeps/pulls: the library's event.listen callbacks
  -- must pair, download and report ready without a foreground controller loop.
  os.sleep(1)
  untilTrue(function()
    local ds=logistics.drones();if #ds~=pairedCount then return false end
    for _,d in ipairs(ds) do if d.state~="idle" then return false end end
    return true
  end,25,"ready missing")
  for _,d in ipairs(logistics.drones()) do print("ready",serialization.serialize(d)) end
  if case=="fixes" then
    check(dropUntil and #bootTimes>=2 and bootTimes[2]-bootTimes[1]>=5,"boot resend missing")
    print("boot resend interval",bootTimes[2]-bootTimes[1])
  end
  if case=="pair" then
    local d=logistics.drones()[1]
    check(d.boots==1 and d.chunks>=2 and d.freeMemory>0,"boot/download metrics")
    check(require("shell").execute("/bin/logistics.lua drones"),"native CLI failed")
    local queued=logistics.transfer({name="minecraft:iron_ingot"},1,{node="A",side=0},{node="B",side=0})
    check(logistics.cancel(queued));check(logistics.status(queued).reason=="cancelled")
    local oldest,last
    for i=1,33 do
      last=logistics.transfer({name="minecraft:iron_ingot"},1,{node="A",side=0},{node="B",side=0})
      oldest=oldest or last;check(logistics.cancel(last))
    end
    check(not logistics.status(oldest) and logistics.status(last),"last-32 history bound")
    check(logistics.forget("d1"));check(#logistics.drones()==0);return
  end
  local from,to={node="A",side=0},{node="B",side=0}
  local item={name="minecraft:iron_ingot",damage=0}
  local function completed(id,seconds)
    untilTrue(function() local s=logistics.status(id);return s and (s.state=="done" or s.state=="partial" or s.state=="failed") end,seconds or 180,"job completion missing")
    local s=logistics.status(id);print("job",id,serialization.serialize(s));return s
  end
  local function transfer(name,amount,opts,source,destination)
    local id=logistics.transfer({name=name,damage=0},amount,source or from,destination or to,opts)
    local notified=false
    local listener=function(_,finished,state) if finished==id then notified=state end end
    event.listen("logistics",listener)
    local deadline=computer.uptime()+180
    while not notified and computer.uptime()<deadline do event.pull(math.max(0,deadline-computer.uptime()),"logistics") end
    event.ignore("logistics",listener)
    check(notified,"completion event missing")
    local result=logistics.status(id);print("job",id,serialization.serialize(result))
    check(result.state==notified);return result,id
  end
  if case=="steps" then
    local steps={{take=from,item=item,count=10},{take=to,item=item,count=10},{take={node="O",side=0},item=item,count=10},
      {put={node="B2",side=0},item=item,count=10},{put={node="E",side=0},item=item,rest=true}}
    local result=completed(logistics.job(steps));check(result.state=="done" and result.steps[4].moved==10 and result.steps[5].moved==20)
    check(logistics.route("milk-run",steps));check(logistics.routes()[1]=="milk-run")
    result=completed(logistics.run("milk-run"));check(result.state=="done" and result.steps[5].moved==20)
    local sawParallel=false
    local watch=function()
      local working=0;for _,d in ipairs(logistics.drones()) do if d.state=="working" then working=working+1 end end
      if working==2 then sawParallel=true end
    end
    event.listen("modem_message",watch)
    result=completed(logistics.job({{take=from,item=item,count=600},{put={node="E",side=0},item=item,rest=true}},{drones=2}))
    event.ignore("modem_message",watch);check(sawParallel,"step parallel option ignored")
    check(result.state=="done" and result.steps[1].moved==600 and result.steps[2].moved==600 and result.trips==3)
    result=completed(logistics.job({{take={node="E",side=0,slots={1}},item=item,count="all"},{put={node="A",side=0,slots={1}},item=item,rest=true},{read={node="E",side=0,slots={1}}},{go="M"}}))
    check(result.state=="done" and result.steps[1].moved==64 and result.steps[2].moved==64 and not next(result.steps[3].listing),"all/slots/read/go")
  elseif case=="wait" then
    local waiting=logistics.transfer(item,64,from,to,{wait={timeout=30},retries=0,drones=1})
    local filling=logistics.transfer(item,64,{node="O",side=0},from,{drones=1})
    local filled=completed(filling);check(filled.state=="done" and filled.moved==64,"newer job starved")
    local result=completed(waiting);check(result.state=="done" and result.moved==64)
    result=completed(logistics.transfer(item,1,from,to,{wait={timeout=2},retries=0}))
    check(result.state=="failed" and result.moved==0)
  elseif case=="blocked" or case=="blocked-held" then
    local result=transfer("minecraft:iron_ingot",64,{retries=0})
    check(result.blockedReports and #result.blockedReports>=1,"blocked not reported")
    check(result.blockedReports[1].stalledSeconds>=3 and result.blockedReports[1].stalledSeconds<4,"blocked deadline")
    check(map.route("M","B")[2]=="B","saved link modified")
    if case=="blocked" then check(result.state=="done" and result.moved==64)
    else check(result.state=="failed" and result.held[1].count==64 and logistics.drones()[1].state=="held");return end
  elseif case=="furnace" then
    local ore={name="minecraft:iron_ore",damage=0};local coal={name="minecraft:coal",damage=0}
    local result=completed(logistics.job({{take=from,item=ore,count=1},{put=to,item=ore,count=1},{read=to}}))
    check(result.state=="done" and result.steps[3].size==1 and result.steps[3].listing[1].name==ore.name,"top slot")
    print("furnace top",serialization.serialize(result.steps[3]))
    result=completed(logistics.job({{take={node="O",side=0},item=coal,count=2},{put={node="FS",side=5},item=coal,count=2},{read={node="FS",side=5}}}))
    check(result.state=="done" and result.steps[3].size==1 and result.steps[3].listing[1].name==coal.name);print("furnace side",serialization.serialize(result.steps[3]))
    os.sleep(12)
    result=completed(logistics.job({{read={node="FB",side=1}},{go="H"}}))
    check(result.state=="done" and result.steps[1].size==2 and result.steps[1].listing[1].name=="minecraft:iron_ingot" and result.steps[1].listing[2].name==coal.name,"bottom output/fuel slots")
    print("furnace bottom",serialization.serialize(result.steps[1]))
  elseif case=="fixes" then
    local placed,emptied=false,false
    local ds=logistics.drones();local d1=ds[1]
    event.listen("modem_message",function(_,_,sender,port,_,token,kind)
      if sender==d1.address and port==27103 and kind=="fixture_placed" then placed=true
      elseif sender==d1.address and kind=="fixture_emptied" then emptied=true end
    end)
    -- d1 is selected by keeping d2 occupied waiting at O (already stocked
    -- cobble, but the deliberately absent iron wait has a bounded timeout).
    local occupying=logistics.transfer(item,1,{node="O",side=0},to,{wait={timeout=20},retries=0,drones=1})
    untilTrue(function() for _,d in ipairs(logistics.drones()) do if d.state=="working" then return true end end end,5,"waiting job not assigned")
    local active=logistics.drones();local occupied
    for _,d in ipairs(active) do if d.state=="working" then occupied=d.name end end
    -- The native adversary triggers only on d1. If d1 got the waiting job,
    -- let it end, then use an iron take as the sole job (fleet iteration is
    -- stable and the now-idle d1 is first as observed).
    if occupied=="d1" then completed(occupying,40) end
    local id=logistics.transfer(item,64,from,to,{drones=1,retries=0})
    local result=completed(id,60)
    check(result.state=="failed" and result.held[1] and result.held[1].count==64,"lost cargo accounting")
    check(result.trips==1 and result.taken==64,"lost trip statistics")
    untilTrue(function() return logistics.drones()[1].state=="lost" end,10,"lost state missing")
    check(logistics.drones()[1].node==nil,"guessed lost position")
    check(not logistics.release("d1"),"lost release accepted")
    local token=serialization.unserialize(assert(io.open("/etc/logistics.drones")):read("*a")).d1.token
    component.modem.send(d1.address,27103,token,"trip",999,"{}")
    os.sleep(1);check(logistics.drones()[1].state=="lost","lost accepted trip")
    component.modem.send(d1.address,27103,token,"fixture_home")
    untilTrue(function() return placed end,15,"player relocation missing")
    check(require("shell").execute("/bin/logistics.lua found d1"),"found CLI failed")
    untilTrue(function() return logistics.drones()[1].state=="held" end,10,"found ready missing")
    local cargo=assert(logistics.release("d1"));check(cargo[1].size==64 and logistics.drones()[1].state=="held")
    component.modem.send(d1.address,27103,token,"fixture_empty")
    untilTrue(function() return emptied end,10,"player empty missing")
    check(not next(assert(logistics.release("d1"))) and logistics.drones()[1].state=="idle","release empty failed")
    completed(occupying,40)
  elseif case=="stack-capacity" then
    local result=transfer("minecraft:ender_pearl",200,{split=false})
    check(result.state=="partial" and result.moved==64 and result.remaining==136 and result.maxSize==16 and result.trips==1)
    check(result.reason:find("200",1,true) and result.reason:find("64",1,true))
  elseif case=="split" then
    local result=transfer("minecraft:cobblestone",600,{drones=1}, {node="A",side=0,slots={1,2,3,4,5,6,7,8,9,10}})
    check(result.state=="done" and result.moved==600 and result.trips>=3)
    check(#logistics.drones()==1,"first split used more than one registered drone")
    check(logistics.register(pending[2],"d2","H2"))
    untilTrue(function()
      local ds=logistics.drones();return #ds==2 and ds[1].state=="idle" and ds[2].state=="idle"
    end,25,"second drone ready missing")
    print("second drone ready",serialization.serialize(logistics.drones()[2]))
    result=transfer("minecraft:cobblestone",600,{drones=2},{node="A",side=0,slots={11,12,13,14,15,16,17,18,19,20}})
    check(result.state=="done" and result.moved==600 and result.trips>=3)
    result=transfer("minecraft:ender_pearl",40,{drones=1},{node="A",side=0,slots={21,22,23}})
    check(result.state=="done" and result.moved==40 and result.maxSize==16)
    result=transfer("minecraft:cobblestone",600,{split=false})
    check(result.state=="failed" and result.reason:find("600",1,true) and result.reason:find("256",1,true))
  elseif case=="shortfall" then
    local result=transfer("minecraft:iron_ingot",64,{retries=2})
    check(result.state=="partial" and result.moved==48 and result.remaining==16 and result.shortfalls==3 and result.trips==3)
  elseif case=="held" then
    local result=transfer("minecraft:iron_ingot",64,{overflow={node="O",side=0,slots={1}}},{node="A",side=0,slots={1}},{node="B",side=0,slots={3}})
    check(result.state=="failed" and result.moved==0 and #result.held==1 and result.held[1].count==64)
    check(logistics.drones()[1].state=="held" and logistics.drones()[1].node=="H");return
  elseif case=="full" then
    local result=transfer("minecraft:iron_ingot",64,{retries=0},{node="A",side=0,slots={1}},{node="B",side=0,slots={3}})
    check(result.state=="partial" and result.moved==20 and result.returned==44 and #result.held==0 and result.reason)
    result=transfer("minecraft:iron_ingot",64,{overflow={node="O",side=0},retries=0},{node="A",side=0,slots={2}},{node="B2",side=0,slots={3}})
    check(result.state=="partial" and result.moved==20 and result.overflow==44 and #result.held==0)
  else
    local d=logistics.drones()[1];local before=(d.sent or 0)+(d.received or 0)
    if case=="security" then
      -- The fixture's agent prepends one native wrong-token report, then runs
      -- the unchanged agent. The controller must have ignored that report.
      check(d.cargoSlots==4 and d.received==2,"wrong-token report was counted")
      event.timer(1,function() component.modem.send(d.address,27103,"WRONG!","trip",999,"{}") end,1)
    end
    local source,destination={node="A",side=0,slots={1}},{node="B",side=0,slots={3}}
    if case=="names" then source="iron-source";destination={storage="iron-destination",slots={3}} end
    local result=transfer("minecraft:iron_ingot",64,nil,source,destination)
    check(result.state=="done" and result.moved==64 and result.remaining==0)
    d=logistics.drones()[1];check(d.node=="H" and d.state=="idle")
    print("transfer packets",(d.sent or 0)+(d.received or 0)-before,"energy",d.energy)
    if case=="names" then
      local id=logistics.job({{go="iron-destination"}})
      local status;repeat os.sleep(0.5);status=logistics.status(id) until status.state~="queued" and status.state~="active"
      check(status.state=="done" and status.steps[1].go=="B","go by storage name")
    end
    if case=="power" then check(d.energy>=4990,"not charged to reserve");os.sleep(0.6) end
  end
  for _,d in ipairs(logistics.drones()) do check(d.state=="idle" and d.node==(d.name=="d1" and "H" or "H2")) end
end
