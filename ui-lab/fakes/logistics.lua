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
function M.fake(kind,ep,i,n)
  local id=#D.jobs+1;local j={id=id,state="running",requested=n or 0,moved=0,item=i,from=kind~="store" and (kind=="read" and ep or {storage="s2_1_N"}) or ep,to=kind~="read" and ep or nil}
  if kind=="read" then j.requested=0 end
  D.jobs[id]=j;event.push("logistics_work")
  event.timer(1.5,function() j.state="done";j.moved=j.requested
    if kind=="read" then j.listing={[1]={name="minecraft:clay_ball",damage=0,size=1,maxSize=64,label="Clay"},[24]={name="minecraft:brick",damage=0,size=1,maxSize=64,label="Brick"}};j.size=27 end
    event.push("logistics",id,"done") end)
  return id
end
return M
