-- Known-stock housekeeping: one bounded tour, interrupted between tours.
local w=require('warehouse')
local lg=require('logistics')
local stats=require('stats')
local mes=require('mes_service')
local event=require('event')
local clock=require('computer')
local ser=require('serialization')
local db=require('store').open('/etc/housekeeping','log')
local D=db:load()
local C=D.settings or {enabled=true,idleSeconds=30,minFill=stats.settings().fillWarn,minSlotsPerTrip=1}
if not D.settings then db:put('settings',C);db:flush() end
local S={phase='waiting',moved=0,trips=0,job=D.job}
local timer,last
local M={}
local function copy(t) return ser.unserialize(ser.serialize(t)) end
local function publish()
  local text=ser.serialize(S)
  if text~=last then last=text;event.push('housekeeping',S.phase,S.job,S.reason) end
end
local function stopTimer() if timer then event.cancel(timer);timer=nil end end
local function busy(state) return state=='queued' or state=='active' or state=='running' end
local function realWork()
  for _,r in ipairs(mes.runs()) do if busy(r.status) then return true end end
  for _,j in ipairs(lg.jobs(true)) do if j.id~=S.job and busy(j.state) then return true end end
  return false
end
local function idle()
  local ds=lg.drones();if #ds==0 then return false end
  for _,d in ipairs(ds) do if d.state~='idle' then return false end end
  return #w.inflight()==0
end
local function matches(a,b)
  return a.name==b.name and (a.damage or 0)==(b.damage or 0) and (not b.label or a.label==b.label)
end
local function accepts(settings,item)
  if not settings.filter then return nil end
  for _,i in ipairs(settings.filter) do if matches(item,i) then return true end end
  return false
end
local function candidate()
  local rows=w.entries();local fill={};local slots=4
  for _,s in ipairs(stats.summary().perStorage) do fill[s.name]=s.fill end
  for _,d in ipairs(lg.drones()) do slots=math.min(slots,d.cargoSlots or 0) end
  local choices={}
  for key,faces in pairs(rows) do
    table.sort(faces,function(a,b) return a.storage<b.storage end)
    local source=faces[1];local entry=source.entry
    if entry and not entry.capacityUnknown and (fill[source.storage] or 0)>=C.minFill then
      for _,v in pairs(entry.items) do
        local maximum=v.maxSize or w.stackSize(v.item)
        local units=v.stacks or 0
        if maximum and v.count>0 and units>0 and units<=slots then
          local filtered=false
          for _,f in ipairs(faces) do filtered=filtered or accepts(f.settings,v.item)==true end
          local best
          for targetKey,targets in pairs(rows) do if targetKey~=key then
            for _,target in ipairs(targets) do
              local e=target.entry;local accept=accepts(target.settings,v.item)
              if e and not e.capacityUnknown and accept~=false and (not filtered or accept) then
                local room=0
                for _,i in pairs(e.items) do if matches(i.item,v.item) then room=room+i.room end end
                local gain=(entry.estimated and math.ceil(v.count/maximum) or units)
                  -math.ceil(math.max(0,v.count-room)/maximum)
                local sort=not filtered and accept==true
                if e.freeSlots*maximum+room>=v.count and not (e.full and e.full[ser.serialize({v.item.name,v.item.damage or 0,v.item.label},false)])
                  and (sort or gain>=C.minSlotsPerTrip) then
                  local c={from=source.storage,to=target.storage,item=v.item,count=v.count,
                    units=units,gain=gain,kind=sort and 'sort' or 'merge',key=key,room=room}
                  if not best or room>best.room or room==best.room and c.to<best.to then best=c end
                end
              end
            end
          end end
          if best then choices[#choices+1]=best end
        end
      end
    end
  end
  table.sort(choices,function(a,b)
    if a.count~=b.count then return a.count<b.count end
    if a.from~=b.from then return a.from<b.from end
    return ser.serialize(a.item)<ser.serialize(b.item)
  end)
  for _,first in ipairs(choices) do
    local requests,used,gain={},0,0
    for _,c in ipairs(choices) do
      if c.key==first.key and used+c.units<=slots and pcall(lg.plan,c.from,c.to) then
        requests[#requests+1]={item=c.item,count=c.count,to=c.to}
        used=used+c.units;gain=gain+c.gain
      end
    end
    if #requests>0 then return first,requests,gain end
  end
end
local update
update=function()
  local own=S.job and lg.status(S.job)
  if S.job and (not own or not busy(own.state) and w.settled(S.job)) then
    S.moved=S.moved+(own and own.moved or 0);S.trips=S.trips+(own and own.trips or 0)
    S.lastReason=own and own.reason;S.job=nil;db:delete('job');db:flush()
  end
  local real=realWork()
  if not C.enabled or real then
    stopTimer();S.idleSince=nil
    if S.job and own and own.state=='queued' then lg.cancel(S.job) end
    S.phase=S.job and 'paused' or C.enabled and 'waiting' or 'off'
    S.reason=not C.enabled and 'disabled' or 'real work'
  elseif S.job then
    stopTimer();S.phase='running';S.reason='finishing tour'
  elseif not idle() then
    stopTimer();S.idleSince=nil;S.phase='waiting';S.reason='fleet or catalogue busy'
  else
    S.idleSince=S.idleSince or clock.uptime()
    local remaining=C.idleSeconds-(clock.uptime()-S.idleSince)
    S.phase='waiting';S.reason='idle delay'
    if remaining>0 then
      if not timer then timer=event.timer(remaining,function() timer=nil;update() end,1) end
    else
      stopTimer()
      local first,requests,gain=candidate()
      if first and not realWork() and idle() then
        local ids,err=w.collect(first.from,requests,{oneTour=true})
        if ids and ids[1] then
          S.job=ids[1];S.source=first.from;S.target=first.to;S.kind=first.kind;S.estimatedGain=gain
          db:put('job',S.job);db:flush();S.phase='running';S.reason='finishing tour'
        else S.reason=err or 'no worthwhile move' end
      else S.reason='no worthwhile move' end
    end
  end
  publish()
end
function M.status() return copy(S) end
function M.settings() return copy(C) end
function M.set(k,v)
  assert(C[k]~=nil and (k=='enabled' and type(v)=='boolean' or k~='enabled' and type(v)=='number'
    and v>=0 and v<math.huge and (k~='minFill' or v<=1)
    and (k~='minSlotsPerTrip' or v%1==0)),'invalid housekeeping setting')
  if C[k]==v then return end
  C[k]=v;db:put('settings',C);db:flush();stopTimer()
  event.push('housekeeping','settings',k,v);update()
end
-- A restored queued tour is replaceable; an active one finishes, never replays.
if S.job then local j=lg.status(S.job);if j and j.state=='queued' then lg.cancel(S.job) end end
for _,name in ipairs({'warehouse','logistics','logistics_work','mes'}) do event.listen(name,update) end
update()
return M
