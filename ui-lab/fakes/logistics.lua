-- UI-lab fake of logistics: windowed job summaries, drones, timed progress.
local D=require("lab_data");local event=require("event");local M={}
local function copy(t) if type(t)~="table" then return t end;local o={};for k,v in pairs(t) do o[k]=copy(v) end;return o end
function M.drones() return copy(D.drones) end
function M.jobs(summary,first,count)
  local n=#D.jobs;first=first or 1;count=count or n;local out={}
  for k=first,math.min(n,first+count-1) do local j=D.jobs[n-k+1];out[#out+1]=copy(j) end
  return out,n
end
function M.status(id) local j=D.jobs[id];if not j then return nil end
  local s=copy(j);s.trips=math.max(1,j.requested//32);if j.listing then s.steps={{read=j.from,listing=copy(j.listing),size=j.size}} else s.steps={{take=j.from,item=j.item,taken=j.moved},{put=j.to,item=j.item,moved=j.moved}} end;return s end
function M.fake(kind,ep,i,n,delay)
  local id=#D.jobs+1;local j={id=id,state="running",requested=n or 0,moved=0,item=i,from=kind~="store" and (kind=="read" and ep or {storage="s2_1_N"}) or ep,to=kind~="read" and ep or nil}
  if kind=="read" then j.requested=0 end
  D.jobs[id]=j;event.push("logistics_work")
  event.timer(delay or 1.5,function() j.state="done";j.moved=j.requested
    if kind=="read" then j.listing={[1]={name="minecraft:clay_ball",damage=0,size=1,maxSize=64,label="Clay"},[24]={name="minecraft:brick",damage=0,size=1,maxSize=64,label="Brick"}};j.size=27 end
    event.push("logistics",id,"done") end)
  return id
end
-- Fleet board: announcing drones, registration, held cargo, lost drones.
local function drone(name) for _,d in ipairs(D.drones) do if d.name==name then return d end end end
-- As the real one: pending(kind) by announced kind (default drone); sensors
-- register with no home and are not in drones() (D.sensors keeps their names).
D.sensorAnnouncing={"6a7b8c9d-cccc-4ddd-8eee-ffffffffff05"};D.sensors={"sensor1","sensor2","sensor3"}
function M.pending(kind) kind=kind or "drone";return copy(kind=="sensor" and D.sensorAnnouncing or kind=="drone" and D.announcing or {}) end
function M.pendingSensors() return M.pending("sensor") end
function M.register(address,name,home)
  local k,list;for _,l in ipairs({D.announcing,D.sensorAnnouncing}) do for i,a in ipairs(l) do if a==address then k,list=i,l end end end
  if not k then return nil,"address is not an announcing unpaired drone" end
  local taken=drone(name);for _,n in ipairs(D.sensors) do if n==name then taken=true end end
  if type(name)~="string" or not name:match("^[%w_-]+$") or #name>48 or taken then return nil,"invalid/duplicate name" end
  if list==D.sensorAnnouncing then table.remove(list,k);D.sensors[#D.sensors+1]=name;return true end
  local node=D.nodes[home];if not node or not node.charger then return nil,"home must be a mapped charger" end
  table.remove(D.announcing,k)
  D.drones[#D.drones+1]={name=name,address=address,state="booting",node=home,home=home,cargoSlots=8}
  table.sort(D.drones,function(a,b) return a.name<b.name end)
  return true
end
-- Returns at once; logistics_released follows: "ok" after 3 s (listing in
-- drones() cargo; empty when M.labReleaseEmpty), or "timeout" after 5 s
-- when M.labReleaseTimeout is set.
function M.release(name)
  local d=drone(name);if not d then return nil,"unknown drone" end
  if d.state~="held" then return nil,"drone is not held" end
  if d.releasePending then return nil,"release already pending" end
  local got=d.cargo or {};d.releasePending=true;d.cargo=nil
  local function done()
    d.releasePending=nil
    if M.labReleaseTimeout then d.cargo=got;event.push("logistics_released",name,"timeout");return end
    -- As the real one: the listing is what it still holds; empty means idle.
    if M.labReleaseEmpty then got={} end
    d.cargo=got;if not next(got) then d.held=nil;d.state="idle" end;event.push("logistics_released",name,"ok")
  end
  event.timer(M.labReleaseTimeout and 5 or 3,done);return true
end
function M.found(name)
  local d=drone(name);if not d then return nil,"unknown drone" end
  if not d.lost then return nil,"drone is not lost" end
  d.lost=nil;d.state="booting";d.job=nil;d.trip=nil;d.node=d.home;return true
end
-- Lab: a drone announces (sync.py's "announce" launcher argument).
function M.labAnnounce() local a="2f3e4d5c-bbbb-4ccc-8ddd-eeeeeeeeee03";D.announcing[#D.announcing+1]=a;event.push("logistics_announce",a,"drone") end
function M.labAnnounceSensor() local a="1a2b3c4d-dddd-4eee-8fff-000000000006";D.sensorAnnouncing[#D.sensorAnnouncing+1]=a;event.push("logistics_announce",a,"sensor") end
-- Not in the real API (proposed): registered sensor names. On only with the
-- launcher's "sensorlist" argument.
function M.labSensorList() M.sensors=function() local o=copy(D.sensors);table.sort(o);return o end end
return M
