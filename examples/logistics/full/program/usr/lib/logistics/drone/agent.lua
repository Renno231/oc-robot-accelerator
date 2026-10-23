local modem,token,controller,name,port,x,y,z=...
local drone=component.proxy(component.list("drone")())
local inv=component.proxy(component.list("inventory_controller")())
local slots=drone.inventorySize()
local function encode(v)
  if type(v)=="table" then
    local out={"{"}
    for k,a in pairs(v) do out[#out+1]="["..encode(k).."]="..encode(a).."," end
    out[#out+1]="}";return table.concat(out)
  elseif type(v)=="string" then return string.format("%q",v)
  else return tostring(v) end
end
local function decode(s)
  if type(s)~="string" then return nil end
  local f=load("return "..s,"=d","t",{});if not f then return nil end
  local ok,v=pcall(f);if ok and type(v)=="table" then return v end
end
local function report(id,data)
  data.energy=computer.energy();data.position={x=x,y=y,z=z};data.cargoSlots=slots
  local payload=encode(data)
  if #payload>=7000 and data.task then data.task=nil;payload=encode(data) end
  if #payload>=7000 then
    for _,step in ipairs(data.steps or {}) do step.listing=nil end
    data.reason="inventory listing exceeds result packet bound";data.state="held";data.refused=true
    payload=encode(data)
  end
  assert(#payload<7000,"result packet too large")
  modem.send(controller,port,token,"report",id,payload)
  return payload
end
-- Reports of the last two trips, newest first, resent when the controller asks.
local done={}
-- The trip as the controller planned it, kept with its report so a controller
-- that lost the job can rebuild it from this drone's account.
local function account(task)
  if not task.steps then return nil end
  local steps={}
  for i,s in ipairs(task.steps) do steps[i]={take=s.take,put=s.put,read=s.read,go=s.go,item=s.item,count=s.count,all=s.all,rest=s.rest,expectedIndex=s.expectedIndex} end
  return {steps=steps,expected=task.expected}
end
local function final(id,task,result)
  result.job=task.job;result.task=account(task)
  table.insert(done,1,{id,report(id,result)});done[3]=nil
end
local activeTrip,history,currentPoint,rerouted,testingCandidate
local function askRoute(from,to,blocked)
  local function sendRequest()
    if blocked then report(activeTrip,blocked)
    else modem.send(controller,port,token,"navigate",activeTrip,encode({from=from,to=to})) end
  end
  sendRequest()
  while true do
    local e={computer.pullSignal(60)}
    -- No answer: wake the controller in case it stopped. Once started, it asks for status.
    if not e[1] and WAKE~="" then modem.send(controller,port,WAKE) end
    if e[1]=="modem_message" and e[3]==controller and e[4]==port and e[6]==token then
      if e[7]=="status" then sendRequest()
      elseif e[7]=="navigation" and e[8]==activeTrip then
        local answer=decode(e[9]);assert(answer and answer.route,answer and answer.reason or "invalid route")
        return answer.route
      end
    end
  end
end
-- OC 8ca336fb entity/Drone.scala:74-78,430-457: .1 acceleration per
-- tick, .4 axis cap, .8 drag. component/Drone.scala: getMaxVelocity=8,
-- getAcceleration=2; convert the latter back to 40 blocks/s^2.
local acceleration=drone.getAcceleration()*20
-- From a confirmed hover, ||v_next|| <= .8*(||v||+.1): the scalar
-- terminal bound is .4 blocks/tick (8 blocks/s); axis clipping only lowers it.
local speed=math.max(.02,math.min(drone.getMaxVelocity()*math.sqrt(3),acceleration/20*.8/(1-.8)))
local function flightSleep(offset)
  -- Reserve braking/settling distance; use the source's upper speed bound,
  -- not an optimistic ETA. Never weaken either arrival or stall predicate.
  local near=math.max(1,speed*speed/(2*math.max(acceleration,0.001)))
  return math.max(0.1,math.min(1,(offset-near)/speed))
end
local function fly(path)
  for _,p in ipairs(path) do
    if math.abs(p.x-x)+math.abs(p.y-y)+math.abs(p.z-z)>0.01 then
      local previous=currentPoint or path[1]
      local offset=math.sqrt((p.x-x)^2+(p.y-y)^2+(p.z-z)^2)
      drone.move(p.x-x,p.y-y,p.z-z)
      local best,progress=math.huge,computer.uptime()
      while drone.getOffset()>=0.02 or drone.getVelocity()>=0.02 do
        computer.pullSignal(flightSleep(offset))
        offset=drone.getOffset()
        if offset<0.02 and drone.getVelocity()<0.02 then break end
        if offset<best-0.1 then best=offset;progress=computer.uptime() end
        if computer.uptime()-progress>=3 then
          local stalled=computer.uptime()-progress
          -- move() changes the target, not the current position. Undo the target
          -- increment and retrace this clear portion to the last confirmed node.
          drone.move(x-p.x,y-p.y,z-p.z)
          local deadline=computer.uptime()+10
          repeat computer.pullSignal(0.1) until (drone.getOffset()<0.02 and drone.getVelocity()<0.02) or computer.uptime()>deadline
          assert(drone.getOffset()<0.02,"blocked link retrace failed")
          local route=askRoute(previous.name,path[#path].name,{state="blocked",link={a=previous.name,b=p.name},to=path[#path].name,offset=offset,stalledSeconds=stalled,candidate=testingCandidate})
          rerouted=true
          return fly(route)
        end
      end
      x,y,z=p.x,p.y,p.z
      if history then history[#history+1]=p end
    end
    currentPoint=p
  end
end
local function goTo(node)
  if currentPoint.name==node then return end
  return fly(askRoute(currentPoint.name,node))
end
local function travel(path)
  if rerouted then return goTo(path[#path].name) end
  return fly(path)
end
-- Probe stalls return to the last confirmed hover, without named-map rerouting.
local function probeMove(p)
  drone.move(p.x-x,p.y-y,p.z-z)
  local best,progress=math.huge,computer.uptime()
  while drone.getOffset()>=.02 or drone.getVelocity()>=.02 do
    computer.pullSignal(.1)
    local offset=drone.getOffset()
    if offset<.02 and drone.getVelocity()<.02 then break end
    if offset<best-.1 then best=offset;progress=computer.uptime() end
    if computer.uptime()-progress>=3 then
      drone.move(x-p.x,y-p.y,z-p.z)
      repeat computer.pullSignal(.1) until drone.getOffset()<.02 and drone.getVelocity()<.02
      error('blocked probe hop')
    end
  end
  x,y,z=p.x,p.y,p.z
end
local function match(stack,item)
  return stack and stack.name==item.name and stack.damage==(item.damage or 0) and (not item.label or stack.label==item.label)
end
local function indexes(endpoint,size)
  if endpoint.slots then return endpoint.slots end
  local result={};for i=1,size do result[i]=i end;return result
end
local function take(endpoint,item,wanted)
  local size=inv.getInventorySize(endpoint.side);if not size then return 0,nil,"source has no inventory",0 end
  local taken,maxSize,left,emptied=0,nil,0,0
  for _,source in ipairs(indexes(endpoint,size)) do
    local remaining,had=0,false
    if source<=size then
      for cargo=1,slots do
        local stack=inv.getStackInSlot(endpoint.side,source)
        remaining=match(stack,item) and stack.size or 0
        had=had or remaining>0
        if not match(stack,item) or taken>=wanted then break end
        maxSize=stack.maxSize
        local held=inv.getStackInInternalSlot(cargo)
        if not held or match(held,item) then
          local room=stack.maxSize-(held and held.size or 0)
          if room>0 then
            drone.select(cargo)
            local got=inv.suckFromSlot(endpoint.side,source,math.min(room,wanted-taken,stack.size))
            if type(got)=="number" then taken=taken+got;remaining=remaining-got end
          end
        end
      end
    end
    left=left+remaining
    if had and remaining==0 then emptied=emptied+1 end
    if taken>=wanted then break end
  end
  return taken,maxSize,nil,left,emptied
end
local function put(endpoint,item,wanted)
  local size=inv.getInventorySize(endpoint.side);if not size then return 0,"destination has no inventory" end
  local inserted,maxSize=0,nil
  for cargo=1,slots do
    local held=inv.getStackInInternalSlot(cargo)
    if match(held,item) then
      maxSize=held.maxSize
      drone.select(cargo)
      for _,target in ipairs(indexes(endpoint,size)) do
        if target<=size and inserted<wanted and drone.count(cargo)>0 then
          local stack=inv.getStackInSlot(endpoint.side,target)
          if not stack or (match(stack,item) and stack.size<stack.maxSize) then
            local before=drone.count(cargo)
            -- Never use drop(): only a verified adjacent inventory's explicit slot.
            if inv.getInventorySize(endpoint.side) then inv.dropIntoSlot(endpoint.side,target,math.min(before,wanted-inserted)) end
            inserted=inserted+before-drone.count(cargo)
          end
        end
      end
    end
  end
  return inserted,inserted<wanted and "destination refused items" or nil,maxSize
end
local function cargoCount()
  local count=0;for i=1,slots do count=count+drone.count(i) end;return count
end
local function cargoListing()
  local listing={}
  for i=1,slots do local s=inv.getStackInInternalSlot(i);if s then listing[i]={name=s.name,damage=s.damage,label=s.label,size=s.size,maxSize=s.maxSize} end end
  return listing
end
local function cargoRoom(item)
  for i=1,slots do
    local held=inv.getStackInInternalSlot(i)
    if not held or (match(held,item) and held.size<held.maxSize) then return true end
  end
  return false
end
local function waitingTake(endpoint,item,wanted,wait,reserve,minimum)
  local total,maxSize,reason,left,emptied=take(endpoint,item,wanted)
  if not wait then return total,maxSize,reason,false,left,emptied end
  local deadline=computer.uptime()+wait.timeout;local delay=0.05
  while total<(minimum or wanted) and computer.uptime()<deadline do
    if computer.energy()<reserve then return total,maxSize,"wait interrupted to charge",true,left end
    if not cargoRoom(item) then break end
    computer.pullSignal(math.min(delay,math.max(0,deadline-computer.uptime())))
    delay=math.min(0.5,delay*2)
    local got,maximum,why,remaining=take(endpoint,item,wanted-total);left=remaining
    emptied=nil
    total=total+got;maxSize=maximum or maxSize;reason=why
  end
  return total,maxSize,reason,false,left,emptied
end
local function runSteps(task,id,result)
  local ledger={};result.steps={};result.cargo={}
  -- A held drone sent to deliver what it carries starts with that cargo.
  if task.cargo then for i=1,slots do local s=inv.getStackInInternalSlot(i);if s then ledger[#ledger+1]={item={name=s.name,damage=s.damage,label=s.label},count=s.size} end end end
  local function consume(item,count,delivered)
    for _,entry in ipairs(ledger) do
      if match(entry.item,item) then
        local n=math.min(count,entry.count);entry.count=entry.count-n;count=count-n
        if not delivered and entry.step then result.steps[entry.step].moved=result.steps[entry.step].moved-n end
      end
    end
  end
  local function progress()
    local cargo={}
    for _,entry in ipairs(ledger) do if entry.count>0 then cargo[#cargo+1]={item=entry.item,count=entry.count} end end
    result.cargo=cargo;result.held=cargoCount()
    local steps={}
    for i,r in ipairs(result.steps) do local copy={};for k,v in pairs(r) do if k~="listing" then copy[k]=v end end;steps[i]=copy end
    report(id,{state="progress",steps=steps,cargo=cargo,held=result.held})
  end
  for i,step in ipairs(task.steps) do
    local r={moved=0};result.steps[i]=r
    if step.go then goTo(step.go)
    elseif step.read then
      goTo(step.read.node);r.listing={};r.size=inv.getInventorySize(step.read.side)
      assert(r.size,"read has no inventory")
      for _,slot in ipairs(indexes(step.read,r.size)) do
        local s=inv.getStackInSlot(step.read.side,slot)
        if s then r.listing[slot]={name=s.name,damage=s.damage,label=s.label,size=s.size,maxSize=s.maxSize} end
      end
    elseif step.take and step.count>0 then
      goTo(step.take.node)
      local got,maximum,why,recharge,left,empty=waitingTake(step.take,step.item,step.count,task.wait,task.reserve,step.waitFor)
      r.moved=got;r.taken=got;r.maxSize=maximum
      r.emptied=empty;r.knownTaken=empty and got or 0
      ledger[#ledger+1]={step=i,source=step.take,item=step.item,count=got}
      if step.all then r.complete=got<step.count and cargoRoom(step.item);r.short=r.complete or nil
      elseif got<step.count and cargoRoom(step.item) then r.short=not recharge or nil;result.reason=why or "source shortfall" end
      r.left=r.short and left or nil
      if task.split==false and maximum and step.count>slots*maximum then result.refused=true;result.reason="requested "..step.count.." exceeds actual one trip "..slots*maximum.." ("..slots.." slots x "..maximum..")" end
      if recharge then result.recharge=true end
      progress()
      if recharge then break end
    elseif step.put then
      local amount=0;for _,entry in ipairs(ledger) do if match(entry.item,step.item) then amount=amount+entry.count end end
      amount=math.min(amount,step.rest and math.huge or step.count)
      if amount>0 then
        goTo(step.put.node);local got,why,maximum=put(step.put,step.item,amount);r.moved=got;r.maxSize=maximum;consume(step.item,got,true)
        if got<amount then r.refused=amount-got;result.refused=true;result.reason=why end
        progress()
        if result.refused then break end
      end
    end
  end
  -- Every residual quantity retains its own take/source attribution.
  for _,entry in ipairs(ledger) do
    local target=task.overflow or entry.source
    if entry.count>0 and target and entry.step then
      goTo(target.node)
      local got=put(target,entry.item,entry.count)
      entry.count=entry.count-got;result.steps[entry.step].moved=result.steps[entry.step].moved-got
      local r=result.steps[entry.step];local key=task.overflow and "overflow" or "returned";r[key]=(r[key] or 0)+got
      if got>0 and not result.reason then result.reason="undelivered cargo returned";result.refused=true end
    end
  end
  progress()
  if result.recharge and result.held>0 then
    result.recharge=nil;result.refused=true;result.reason="source refused cargo on charging interruption"
  end
  -- A lingering trip that went cleanly waits where it ended for a follow-up
  -- trip (an import's collect after its read) instead of flying home first.
  if task.linger and not result.reason and result.held==0 and computer.energy()>=task.reserve then
    result.lingering=currentPoint.name;return
  end
  -- Delivered in full: the trip ends here, so the job closes while the drone
  -- flies home; it says ready when it lands.
  if not result.reason and result.held==0 then result.homing=true;final(id,task,result) end
  goTo(task.home)
  if computer.energy()<task.reserve then
    report(id,{state="charging"});repeat computer.pullSignal(0.5) until computer.energy()>=task.reserve
  end
end
if not x or drone.getOffset()>=.02 then
  local light=drone.getLightColor()
  drone.setLightColor(0xFF0000);drone.setStatusText("LOST\nsee base")
  report(0,{state=x and"ready"or"lost",notAtHome=x~=nil,offset=drone.getOffset(),cargo=cargoListing()})
  while true do
    local e={computer.pullSignal(60)}
    if e[1]=="modem_message" and e[3]==controller and e[4]==port and e[6]==token and e[7]=="found" and type(e[8])=="number" and type(e[9])=="number" and type(e[10])=="number" then
      x,y,z=e[8],e[9],e[10];drone.setLightColor(light);drone.setStatusText("");break
    end
  end
end
local function ready() report(0,{state="ready",survey=component.list('geolyzer')()~=nil,freeMemory=computer.freeMemory(),held=cargoCount(),cargo=cargoCount()>0 and cargoListing()or nil}) end
ready()
-- While lingering, the flown path back home is kept; with no trip in time the
-- drone retraces it (it was clear on the way out) and reports ready at home.
local lingerUntil
local function returnHome()
  local reverse={};for i=#history,1,-1 do reverse[#reverse+1]=history[i] end
  history=nil;lingerUntil=nil
  local ok=pcall(fly,reverse)
  if ok then ready() else report(0,{state="ready",notAtHome=true,offset=drone.getOffset(),cargo=cargoListing()}) end
end
while true do
  if lingerUntil and computer.uptime()>=lingerUntil then returnHome() end
  local e={computer.pullSignal(lingerUntil and math.max(0,lingerUntil-computer.uptime()) or nil)}
  if e[1]=="modem_message" and e[3]==controller and e[4]==port and e[6]==token and e[7]=="release" then
    done={}
    local listing=cargoListing()
    modem.send(controller,port,token,"cargo",e[8],encode(listing))
  elseif e[1]=="modem_message" and e[3]==controller and e[4]==port and e[6]==token and e[7]=="trip" then
    local task=decode(e[9]);local id=e[8]
    if task and (cargoCount()==0 or task.cargo and task.steps) then
      -- A trip taken while lingering continues the path from home.
      if not lingerUntil then history={task.routes.take[1]};currentPoint=history[1] end
      activeTrip=id;lingerUntil=nil;rerouted=false;testingCandidate=false
      local result={state="idle",held=0}
      local ok,err=pcall(function()
        -- Every trip starts/ends at home. Charge before accepting actual work.
        if computer.energy()<task.reserve then
          report(id,{state="charging"})
          repeat computer.pullSignal(0.5) until computer.energy()>=task.reserve
        end
        if task.steps then return runSteps(task,id,result) end
        if task.action then
          local before=computer.energy()
          travel(task.routes.take)
          if task.action.kind=="survey" then
            result.survey=surveyStep(task.action.command,probeMove,function() return {x=x,y=y,z=z} end)
          elseif task.action.kind=="scan" then
            result.scan={};for side=0,5 do result.scan[side]=inv.getInventorySize(side) end
          else
            testingCandidate=true;fly(task.routes.candidate);fly(task.routes.back);testingCandidate=false;result.test="ok"
          end
          travel(task.routes.home)
          if result.survey then result.survey.tripEnergy=before-computer.energy() end
          if computer.energy()<task.reserve then report(id,{state="charging"});repeat computer.pullSignal(0.5) until computer.energy()>=task.reserve end
          return
        end
      end)
      if not ok then
        result.reason=tostring(err);result.state="held"
        local reverse={};for i=#history,1,-1 do reverse[#reverse+1]=history[i] end
        history=nil
        local returned,why=pcall(fly,reverse)
        if not returned then result.reason=result.reason.."; home retrace: "..tostring(why);result.away=true end
        result.held=cargoCount()
      end
      if not result.homing then final(id,task,result)
      elseif not result.away then ready()
      else report(0,{state="ready",notAtHome=true,offset=drone.getOffset(),cargo=cargoListing()}) end
      if result.lingering then lingerUntil=computer.uptime()+task.linger else history=nil end
    end
  elseif e[1]=="modem_message" and e[3]==controller and e[4]==port and e[6]==token and e[7]=="status" then
    for i=#done,1,-1 do modem.send(controller,port,token,"report",done[i][1],done[i][2]) end
    -- Away from home, ready waits until the drone is back there.
    if not lingerUntil then ready() end
  end
end
