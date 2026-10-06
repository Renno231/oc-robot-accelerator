local component=require("component")
local event=require("event")
local serialization=require("serialization")
local map=require("map")
local M={}
local function read(path,default)
  local f=io.open(path,"r");if not f then return default end
  local data=serialization.unserialize(f:read("*a"));f:close();assert(type(data)=="table","invalid "..path);return data
end
local config=read("/etc/logistics.cfg",{})
local port,reserve,retries=27103,config.reserve or 1000,config.retries or 2
assert(port>=1 and port<=65535 and port%1==0 and reserve>0 and reserve<=5000 and retries>=0 and retries%1==0,"invalid logistics config")
local modem=component.modem
assert(modem and modem.isWireless(),"wireless modem required")
modem.open(port)
local file=assert(io.open("/lib/logistics/agent.lua","r"));local source=file:read("*a");file:close()
local chunks=math.ceil(#source/2048);assert(chunks>=1 and chunks<=16,"agent download bound")
local registry=read("/etc/logistics.drones",{})
local savedRoutes=read("/etc/logistics.routes",{})
local fleet,addresses,announcing,jobs,queue,finished={},{},{},{},{},{}
local nextJob,nextTrip=0,0
local function persist()
  local f=assert(io.open("/etc/logistics.drones","w"));f:write(serialization.serialize(registry));f:close()
end
local function attach(name,record)
  local d={name=name,address=record.address,token=record.token,home=record.home,node=record.home,state="booting"}
  fleet[name]=d;addresses[d.address]=d
end
for name,r in pairs(registry) do attach(name,r) end
local function send(d,...)
  d.sent=(d.sent or 0)+1;modem.send(d.address,port,d.token,...)
end
local function wakeScheduler() event.push("logistics_work") end
local function finish(job,state,reason)
  if job.finished then return end
  job.state=state;job.reason=reason or job.reason;job.finished=true
  finished[#finished+1]=job.id
  if #finished>32 then jobs[table.remove(finished,1)]=nil end
  for i,id in ipairs(queue) do if id==job.id then table.remove(queue,i);break end end
  event.push("logistics",job.id,state);wakeScheduler()
end
local function endpoint(e)
  if type(e)=="string" then e=assert(map.storage(e),"unknown storage "..e)
  elseif type(e)=="table" and e.storage then
    local named=assert(map.storage(e.storage),"unknown storage "..e.storage)
    e={node=named.node,side=named.side,slots=e.slots}
  end
  assert(type(e)=="table" and type(e.node)=="string","endpoint required")
  local node=assert(map.node(e.node),"unknown endpoint node "..e.node)
  assert(type(e.side)=="number" and e.side%1==0 and e.side>=0 and e.side<=5 and node.faces[e.side],"unmapped storage face")
  if e.slots then
    assert(type(e.slots)=="table" and #e.slots>0,"empty slots")
    local seen={};for _,slot in ipairs(e.slots) do assert(type(slot)=="number" and slot%1==0 and slot>0 and not seen[slot],"invalid/duplicate slot");seen[slot]=true end
  end
  return serialization.unserialize(serialization.serialize(e))
end
local function path(a,b,avoid)
  local names=assert(map.route(a,b,avoid),"no route "..a.." -> "..b)
  local out={};for _,name in ipairs(names) do local p=map.node(name);p.name=name;out[#out+1]=p end;return out
end
local function points(names)
  local out={};for _,name in ipairs(names or {}) do local p=map.node(name);out[#out+1]={name=name,x=p.x,y=p.y,z=p.z} end;return out
end
local function activeCount(job)
  local n,amount=0,0;for _,a in pairs(job.active) do n=n+1;amount=amount+a.amount end;return n,amount
end
local function scheduleJob(job)
  if not job or job.finished then return end
  local n,reserved=activeCount(job)
  -- An open-ended take cannot be partitioned before its first local read.
  if job.openEnded and n>0 then return end
  if job.blocked then
    if n==0 and not next(job.lostPending or {}) then finish(job,job.moved>0 and "partial" or "failed") end
    return
  end
  if job.remaining==0 and not job.openEnded and not job.steps then if n==0 then finish(job,"done") end;return end
  for _,d in pairs(fleet) do
    if job.openEnded and n>0 then break end
    if n>=(job.opts.drones or math.huge) then break end
    local available=(job.openEnded or job.steps) and math.huge or job.remaining-reserved
    if available>0 and d.state=="idle" then
      local capacity=64*d.cargoSlots
      if job.opts.split==false and not job.steps and job.remaining>capacity then
        job.blocked=true;job.reason="requested "..job.remaining.." exceeds one trip "..capacity.." ("..d.cargoSlots.." slots x 64)"
        if n==0 then finish(job,"failed") end;return
      end
      local amount=math.min(available,capacity)
      local ok,task=pcall(function()
        if job.action then
          local a=job.action.node or job.action.a
          local routes={take=path(d.home,a,job.avoid),home=path(a,d.home,job.avoid)}
          if job.action.kind=="test" then routes.candidate=points({a,job.action.b});routes.back=points({job.action.b,a}) end
          return {action=job.action,reserve=reserve,routes=routes}
        end
        if job.steps then
          local steps={};local carried,total={},0;local reservations={}
          for _,assigned in pairs(job.active) do
            for i,count in pairs(assigned.steps or {}) do reservations[i]=(reservations[i] or 0)+count end
          end
          for i,s in ipairs(job.steps) do
            local step=serialization.unserialize(serialization.serialize(s))
            if step.take then
              step.count=step.all and (step.complete and 0 or capacity) or math.max(0,step.count-step.moved-(reservations[i] or 0))
              local key=serialization.serialize(step.item,false);carried[key]=(carried[key] or 0)+step.count
            elseif step.put and not step.rest then step.count=math.max(0,step.count-step.moved-(reservations[i] or 0)) end
            if step.put then
              local key=serialization.serialize(step.item,false);carried[key]=math.max(0,(carried[key] or 0)-(step.rest and math.huge or step.count))
            end
            local occupied=0;for _,count in pairs(carried) do occupied=occupied+math.ceil(count/64) end
            total=math.max(total,occupied*64)
            steps[i]=step
          end
          if job.opts.split==false and total>capacity then error("requested "..total.." exceeds one trip "..capacity) end
          carried={};local allocation={};local useful=false
          for i,s in ipairs(steps) do
            if s.take then
              local key=serialization.serialize(s.item,false);local used=0
              for _,count in pairs(carried) do used=used+math.ceil(count/64) end
              local held=carried[key] or 0
              local room=(d.cargoSlots-used)*64+(math.ceil(held/64)*64-held)
              s.count=math.min(s.count,room);carried[key]=held+s.count;allocation[i]=s.count
              useful=useful or s.count>0
            elseif s.put then
              local key=serialization.serialize(s.item,false);local held=carried[key] or 0
              local count=math.min(held,s.rest and math.huge or s.count)
              if not s.rest then s.count=count;allocation[i]=count end
              carried[key]=held-count;useful=useful or count>0
            end
          end
          if not useful and (job.requested>0 or n>0) then
            if n==0 then error("step counts unmet") end
            return nil
          end
          return {steps=steps,allocation=allocation,home=d.home,reserve=reserve,wait=job.opts.wait,overflow=job.opts.overflow,split=job.opts.split,routes={take=points({d.home})}}
        end
        local routes={take=path(d.home,job.from.node,job.avoid),put=path(job.from.node,job.to.node,job.avoid),back=path(job.to.node,job.from.node,job.avoid),homeSource=path(job.from.node,d.home,job.avoid),homeDest=path(job.to.node,d.home,job.avoid)}
        if job.opts.overflow then routes.overflow=path(job.to.node,job.opts.overflow.node,job.avoid);routes.homeOverflow=path(job.opts.overflow.node,d.home,job.avoid) end
        return {item=job.item,count=amount,from=job.from,to=job.to,overflow=job.opts.overflow,wait=job.opts.wait,reserve=reserve,routes=routes}
      end)
      if not ok then job.blocked=true;job.reason=tostring(task);if n==0 then finish(job,job.moved>0 and "partial" or "failed") end;return end
      if not task then return end
      local allocation=task.allocation;task.allocation=nil
      local encoded,data=pcall(function() local s=serialization.serialize(task,false);assert(#s<7000,"trip packet too large");return s end)
      if not encoded then job.blocked=true;job.reason=tostring(data);if n==0 then finish(job,job.moved>0 and "partial" or "failed") end;return end
      nextTrip=nextTrip+1;job.active[nextTrip]={drone=d.name,amount=amount,steps=allocation};d.trip=nextTrip;d.job=job.id;d.state="working";job.state="active"
      send(d,"trip",nextTrip,data);n=n+1;reserved=reserved+amount
    end
  end
end
local function schedule()
  local ordered={};for i,id in ipairs(queue) do ordered[i]=id end
  for _,id in ipairs(ordered) do scheduleJob(jobs[id]) end
end
local function receive(_,_,sender,received,_,token,kind,id,payload)
  if received~=port then return end
  if token=="lgx_hello" then announcing[sender]=true;return end
  local d=addresses[sender];if not d or token~=d.token then return end
  d.received=(d.received or 0)+1
  if kind=="boot" then
    if d.trip or d.lost or not d.node then
      local job=jobs[d.job];local a=job and job.active[d.trip]
      if a then
        local progress=a.progress or {};job.active[d.trip]=nil
        job.trips=job.trips+1
        if job.steps then
          job.moved=0
          for i,s in ipairs(job.steps) do
            local r=(progress.steps or {})[i] or {};s.moved=s.moved+(r.moved or 0);s.maxSize=r.maxSize or s.maxSize
            for _,key in ipairs({"taken","returned","overflow"}) do if r[key] then s[key]=(s[key] or 0)+r[key] end end
            if s.put then job.moved=job.moved+s.moved end
          end
          job.remaining=math.max(0,job.requested-job.moved)
          for _,cargo in ipairs(progress.cargo or {}) do job.held[#job.held+1]={drone=d.name,item=cargo.item,count=cargo.count} end
        else
          job.moved=job.moved+(progress.moved or 0);job.remaining=job.requested-job.moved
          job.taken=job.taken+(progress.taken or 0)
          if (progress.held or 0)>0 then job.held[#job.held+1]={drone=d.name,item=job.item,count=progress.held} end
        end
        job.blocked=true;job.reason="drone lost: "..d.name
        d.lostJob=job.id;job.lostPending=job.lostPending or {};job.lostPending[d.name]=true
      end
      d.trip=nil;d.job=nil;d.lost=true;d.position=nil;d.node=nil
    end
    d.state=d.lost and "lost" or "booting"
    for i=1,chunks do send(d,"code",i,chunks,source:sub((i-1)*2048+1,i*2048)) end
    if d.lost then send(d,"start") else
      local p=assert(map.node(d.home),"missing drone home");send(d,"start",p.x,p.y,p.z)
    end
  elseif kind=="cargo" and id==d.release and type(payload)=="string" and #payload<7000 then
    local listing=serialization.unserialize(payload)
    if type(listing)~="table" then return end
    d.cargo=listing;d.release=nil;d.state=next(listing) and "held" or "idle";wakeScheduler()
  elseif kind=="navigate" and d.trip==id and d.job and type(payload)=="string" and #payload<7000 then
    local request=serialization.unserialize(payload);local job=jobs[d.job]
    if type(request)~="table" or not map.node(request.from) or not map.node(request.to) then return end
    local names=map.route(request.from,request.to,job.avoid)
    send(d,"navigation",id,serialization.serialize({route=names and points(names),reason="no route "..request.from.." -> "..request.to},false))
  elseif kind=="report" and type(payload)=="string" and #payload<7000 then
    local result=serialization.unserialize(payload);if type(result)~="table" then return end
    d.energy=result.energy;d.position=result.position
    if id==0 and result.state=="lost" and d.lost then
      d.cargo=result.cargo
      local job=jobs[d.lostJob]
      if job then
        for i=#job.held,1,-1 do if job.held[i].drone==d.name then table.remove(job.held,i) end end
        for _,cargo in pairs(result.cargo or {}) do
          job.held[#job.held+1]={drone=d.name,item={name=cargo.name,damage=cargo.damage,label=cargo.label},count=cargo.size}
        end
        job.lostPending[d.name]=nil
        if not next(job.active) and not next(job.lostPending) then finish(job,job.moved>0 and "partial" or "failed") end
      end
    elseif id==0 and result.state=="ready" then
      if d.lost then return end
      d.state=(result.held or 0)>0 and "held" or "idle";d.node=d.home;d.cargoSlots=result.cargoSlots;d.freeMemory=result.freeMemory;d.boots=(d.boots or 0)+1;wakeScheduler()
    elseif d.trip==id and d.job then
      if result.state=="charging" then d.state="charging";return end
      local job=jobs[d.job];local assigned=job and job.active[id];if not assigned then return end
      if result.state=="progress" then assigned.progress=result;return end
      if result.state=="blocked" then
        local link=result.link
        if type(link)~="table" or not map.node(link.a) or not map.node(link.b) or not map.node(result.to) then return end
        job.avoid=job.avoid or {};job.avoid[link.a..":"..link.b]=true
        job.reason="blocked link "..link.a.." -> "..link.b
        job.blockedReports=job.blockedReports or {};job.blockedReports[#job.blockedReports+1]={link=link,offset=result.offset,stalledSeconds=result.stalledSeconds}
        if job.action and job.action.kind=="test" and result.candidate then
          job.test="blocked";send(d,"navigation",id,serialization.serialize({reason=job.reason},false));return
        end
        local alternative=map.route(link.a,result.to,job.avoid)
        send(d,"navigation",id,serialization.serialize({route=alternative and points(alternative),reason=job.reason},false))
        return
      end
      job.active[id]=nil
      if job.action then
        job.trips=job.trips+1;job.scan=result.scan;job.test=job.test or result.test
        job.remaining=0;d.state=(result.away or (result.held or 0)>0) and "held" or "idle"
        d.node=not result.away and d.home or nil;d.trip=nil;d.job=nil
        if (result.held or 0)>0 then
          for _,cargo in pairs(result.cargo or {}) do job.held[#job.held+1]={drone=d.name,item=cargo.item,count=cargo.count} end
        end
        finish(job,result.reason and "failed" or "done",result.reason);return
      end
      if job.steps then
        job.trips=job.trips+1;job.openEnded=false;local complete=true
        for i,s in ipairs(job.steps) do
          local r=(result.steps or {})[i] or {}
          s.moved=s.moved+(r.moved or 0);if r.listing then s.listing=r.listing;s.size=r.size end
          s.maxSize=r.maxSize or s.maxSize
          for _,key in ipairs({"taken","returned","overflow"}) do if r[key] then s[key]=(s[key] or 0)+r[key] end end
          if s.all then s.complete=s.complete or r.complete;if not s.complete then complete=false;job.openEnded=true end
          elseif s.count and s.moved<s.count then complete=false end
        end
        job.moved=0
        for _,s in ipairs(job.steps) do if s.put then job.moved=job.moved+s.moved end end
        job.remaining=math.max(0,job.requested-job.moved)
        for _,held in ipairs(result.cargo or {}) do job.held[#job.held+1]={drone=d.name,item=held.item,count=held.count} end
        d.state=(result.held or 0)>0 and "held" or "idle";d.node=not result.away and d.home or nil;d.trip=nil;d.job=nil
        local advanced=false;for _,r in pairs(result.steps or {}) do if (r.moved or 0)>0 then advanced=true end end
        if not complete and not advanced and not result.reason then result.reason="step counts unmet" end
        if result.reason and not result.recharge then
          job.shortfalls=job.shortfalls+1
          if result.refused or result.state=="held" or job.shortfalls>(job.opts.retries or retries) then job.blocked=true;job.reason=result.reason end
        end
        if complete and not job.blocked and not next(job.active) then finish(job,"done") else wakeScheduler() end
        return
      end
      job.moved=job.moved+(result.moved or 0);job.remaining=job.requested-job.moved;job.trips=job.trips+1
      job.maxSize=result.maxSize or job.maxSize;job.taken=job.taken+(result.taken or 0);job.returned=job.returned+(result.returned or 0);job.overflow=job.overflow+(result.overflow or 0)
      if (result.held or 0)>0 then job.held[#job.held+1]={drone=d.name,item=job.item,count=result.held};d.state="held" else d.state="idle" end
      d.node=not result.away and d.home or nil;d.trip=nil;d.job=nil
      if result.recharge then
        -- The wait was interrupted to charge; no source retry was consumed.
      elseif job.opts.split==false and result.maxSize and job.requested>d.cargoSlots*result.maxSize then
        job.blocked=true;job.reason="requested "..job.requested.." exceeds actual one trip "..d.cargoSlots*result.maxSize.." ("..d.cargoSlots.." slots x "..result.maxSize..")"
      elseif (result.moved or 0)<(result.taken or 0) or (result.held or 0)>0 then
        job.blocked=true;job.reason=result.reason or "destination refused items"
      elseif (result.taken or 0)<assigned.amount and (not result.maxSize or (result.taken or 0)<d.cargoSlots*result.maxSize) then
        job.shortfalls=job.shortfalls+1
        if job.shortfalls>(job.opts.retries or retries) then job.blocked=true;job.reason=result.reason or "source shortfall" end
      end
      wakeScheduler()
    end
  end
end
function M.release(name)
  local d=fleet[name];if not d then return nil,"unknown drone" end
  if d.state~="held" then return nil,"drone is not held" end
  if d.release then return nil,"release already pending" end
  nextTrip=nextTrip+1;d.release=nextTrip;d.cargo=nil;send(d,"release",d.release)
  local computer=require("computer");local deadline=computer.uptime()+5
  while d.release and computer.uptime()<deadline do event.pull(0.1) end
  if d.release then d.release=nil;return nil,"cargo report timeout" end
  return serialization.unserialize(serialization.serialize(d.cargo))
end
function M.found(name)
  local d=fleet[name];if not d then return nil,"unknown drone" end
  if not d.lost then return nil,"drone is not lost" end
  local p=assert(map.node(d.home),"missing drone home")
  d.lost=nil;d.state="booting";send(d,"found",p.x,p.y,p.z);return true
end
event.listen("modem_message",receive)
event.listen("logistics_work",schedule)
function M.pending()
  local out={};for address in pairs(announcing) do if not addresses[address] then out[#out+1]=address end end;table.sort(out);return out
end
function M.register(address,name,home)
  if not announcing[address] or addresses[address] then return nil,"address is not an announcing unpaired drone" end
  if type(name)~="string" or not name:match("^[%w_-]+$") or #name>48 or fleet[name] then return nil,"invalid/duplicate name" end
  local node=map.node(home);if not node or not node.charger then return nil,"home must be a mapped charger" end
  local record={address=address,token=string.format("%06x",math.random(0,0xffffff)),home=home}
  registry[name]=record;attach(name,record);persist();announcing[address]=nil
  modem.send(address,port,"lgx_pair",record.token,name)
  return true
end
function M.forget(name)
  local d=fleet[name];if not d then return false end
  if d.job then return nil,"drone is active" end
  registry[name]=nil;fleet[name]=nil;addresses[d.address]=nil;persist();return true
end
function M.drones()
  local out={};for _,d in pairs(fleet) do
    out[#out+1]={name=d.name,address=d.address,state=d.state,node=d.node,energy=d.energy,cargoSlots=d.cargoSlots,freeMemory=d.freeMemory,boots=d.boots,agentBytes=#source,chunks=chunks,sent=d.sent or 0,received=d.received or 0,cargo=d.cargo,releasePending=d.release~=nil}
  end
  table.sort(out,function(a,b) return a.name<b.name end);return out
end
local function options(opts)
  opts=opts or {}
  for k in pairs(opts) do assert(k=="retries" or k=="drones" or k=="split" or k=="overflow" or k=="wait","unsupported option "..k) end
  for _,k in ipairs({"retries","drones"}) do if opts[k]~=nil then assert(type(opts[k])=="number" and opts[k]%1==0 and opts[k]>=(k=="drones" and 1 or 0),"invalid "..k) end end
  assert(opts.split==nil or type(opts.split)=="boolean","invalid split")
  if opts.wait then assert(type(opts.wait)=="table" and type(opts.wait.timeout)=="number" and opts.wait.timeout>=0 and opts.wait.timeout<math.huge,"invalid wait timeout") end
  return serialization.unserialize(serialization.serialize(opts))
end
function M.transfer(item,count,from,to,opts)
  assert(type(item)=="table" and type(item.name)=="string" and (item.damage==nil or (type(item.damage)=="number" and item.damage>=0 and item.damage%1==0)) and (item.label==nil or type(item.label)=="string"),"item required")
  assert(type(count)=="number" and count>0 and count<math.huge and count%1==0,"positive count required")
  opts=options(opts)
  local job={item=serialization.unserialize(serialization.serialize(item)),requested=count,moved=0,remaining=count,state="queued",held={},opts=serialization.unserialize(serialization.serialize(opts)),active={},trips=0,shortfalls=0,taken=0,returned=0,overflow=0}
  nextJob=nextJob+1;job.id=nextJob;jobs[nextJob]=job
  local ok,err=pcall(function() job.from=endpoint(from);job.to=endpoint(to);if opts.overflow then job.opts.overflow=endpoint(opts.overflow) end end)
  if not ok then finish(job,"failed",tostring(err)) else queue[#queue+1]=job.id;wakeScheduler() end
  return job.id
end
function M.status(id)
  local job=jobs[id];if not job then return nil end
  local out={};for _,key in ipairs({"state","requested","moved","remaining","reason","held","trips","shortfalls","maxSize","taken","returned","overflow","steps","blockedReports","scan","test"}) do out[key]=job[key] end
  return serialization.unserialize(serialization.serialize(out))
end
local function action(kind,a,b)
  nextJob=nextJob+1;local id=nextJob
  local job={id=id,state="queued",requested=0,moved=0,remaining=1,held={},active={},trips=0,shortfalls=0,taken=0,returned=0,overflow=0,opts={drones=1}}
  jobs[id]=job
  if not map.node(a) or (kind=="test" and (a==b or not map.node(b))) then finish(job,"failed","unknown/same action node")
  else
    job.action=kind=="scan" and {kind=kind,node=a} or {kind=kind,a=a,b=b}
    queue[#queue+1]=id;wakeScheduler()
  end
  return id
end
function M.scan(node) return action("scan",node) end
function M.test(a,b) return action("test",a,b) end
function M.job(steps,opts)
  assert(type(steps)=="table" and #steps>0,"steps required")
  nextJob=nextJob+1;local id=nextJob
  local job={id=id,state="queued",requested=0,moved=0,remaining=0,steps={},held={},active={},trips=0,shortfalls=0,opts=options(opts)}
  jobs[id]=job
  local ok,err=pcall(function()
    if job.opts.overflow then job.opts.overflow=endpoint(job.opts.overflow) end
    for i,s in ipairs(steps) do
      local step=serialization.unserialize(serialization.serialize(s));local kinds=0
      for _,k in ipairs({"take","put","go","read"}) do if step[k] then kinds=kinds+1 end end
      assert(kinds==1,"one operation per step")
      step.moved=0
      if step.take or step.put then
        assert(type(step.item)=="table" and type(step.item.name)=="string","step item required")
        step.item.damage=step.item.damage or 0
        assert(type(step.item.damage)=="number" and step.item.damage>=0 and step.item.damage%1==0 and (step.item.label==nil or type(step.item.label)=="string"),"invalid step item")
        step[step.take and "take" or "put"]=endpoint(step.take or step.put)
        if step.count=="all" then step.count=nil;step.all=true end
        assert((step.all==nil or step.all==true) and (step.rest==nil or step.rest==true),"invalid all/rest")
        assert(not (step.all and (step.put or step.count)) and not (step.rest and (step.take or step.count)),"conflicting step count")
        assert((step.take and step.all) or (step.put and step.rest) or (type(step.count)=="number" and step.count>0 and step.count%1==0),"step count/all/rest required")
        step.requested=step.count or (step.all and "all" or "rest")
        if step.count and step.take then job.requested=job.requested+step.count;job.remaining=job.remaining+step.count end
        if step.all then job.openEnded=true end
      elseif step.read then step.read=endpoint(step.read)
      else assert(map.node(step.go),"unknown go node") end
      job.steps[i]=step
    end
    job.openEnded=job.openEnded or job.requested==0
  end)
  if not ok then finish(job,"failed",tostring(err)) else queue[#queue+1]=id;wakeScheduler() end
  return id
end
function M.route(name,steps)
  assert(type(name)=="string" and name~="" and type(steps)=="table","route name and steps required")
  savedRoutes[name]=serialization.unserialize(serialization.serialize(steps))
  local f=assert(io.open("/etc/logistics.routes","w"));f:write(serialization.serialize(savedRoutes));f:close();return true
end
function M.routes() local out={};for name in pairs(savedRoutes) do out[#out+1]=name end;table.sort(out);return out end
function M.run(name,opts) return M.job(assert(savedRoutes[name],"unknown route"),opts) end
function M.cancel(id)
  local job=jobs[id];if not job or job.state~="queued" then return false,"only queued jobs can be cancelled" end
  finish(job,"failed","cancelled");return true
end
return M
