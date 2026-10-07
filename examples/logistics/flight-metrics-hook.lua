-- Acceptance-only native instrumentation; no substitute for movement/access.
do
  local modem,token,controller,name,port,px,py,pz=...
  local proxy=component.proxy
  local drone=proxy(component.list('drone')())
  local inv=proxy(component.list('inventory_controller')())
  local trip,started,energy,legs,accesses,leg
  local function encode(v)
    if type(v)=='table' then local out={'{'};for k,a in pairs(v) do out[#out+1]='['..encode(k)..']='..encode(a)..',' end;out[#out+1]='}';return table.concat(out)
    elseif type(v)=='string' then return string.format('%q',v) else return tostring(v) end
  end
  local move,send,pull=drone.move,modem.send,computer.pullSignal
  local getOffset,getVelocity=drone.getOffset,drone.getVelocity
  local lastOffset,lastVelocity
  -- Observe the production checks without adding synchronized OC callbacks.
  drone.getOffset=function() lastOffset=getOffset();return lastOffset end
  drone.getVelocity=function() lastVelocity=getVelocity();return lastVelocity end
  local function arrival()
    if leg and lastOffset and lastVelocity and lastOffset<.02 and lastVelocity<.02 then
      leg.seconds=computer.uptime()-leg.start;leg.energy=leg.energy-computer.energy()
      leg.offset=lastOffset;leg.velocity=lastVelocity;legs[#legs+1]=leg;leg=nil
    end
  end
  drone.move=function(dx,dy,dz)
    arrival()
    if leg then
      leg.interrupted=true;leg.distance=math.max(0,leg.distance-(lastOffset or 0));leg.seconds=computer.uptime()-leg.start
      leg.energy=leg.energy-computer.energy();legs[#legs+1]=leg;leg=nil
    end
    px,py,pz=px+dx,py+dy,pz+dz
    local result=move(dx,dy,dz)
    if trip then leg={dx=dx,dy=dy,dz=dz,distance=math.sqrt(dx*dx+dy*dy+dz*dz),start=computer.uptime(),energy=computer.energy()} end
    return result
  end
  for _,method in ipairs({'getInventorySize','suckFromSlot','dropIntoSlot'}) do
    local original=inv[method]
    inv[method]=function(...)
      arrival()
      if trip then
        local key=px..','..py..','..pz
        local access=accesses[key] or {point={x=px,y=py,z=pz},count=0,offset=0,velocity=0};accesses[key]=access
        assert(lastOffset and lastVelocity,'access without arrival checks')
        access.count=access.count+1;access.offset=math.max(access.offset,lastOffset);access.velocity=math.max(access.velocity,lastVelocity)
      end
      return original(...)
    end
  end
  component.proxy=function(address)
    if address==drone.address then return drone elseif address==inv.address then return inv end
    return proxy(address)
  end
  computer.pullSignal=function(timeout)
    local e={pull(timeout)};arrival()
    if e[1]=='modem_message' and e[3]==controller and e[4]==port and e[6]==token and e[7]=='trip' then
      trip=e[8];started=computer.uptime();energy=computer.energy();legs={};accesses={}
    end
    return table.unpack(e)
  end
  modem.send=function(address,p,t,kind,id,data,...)
    if trip and kind=='report' and id==trip and type(data)=='string' then
      local result=assert(load('return '..data,'=metrics','t',{}))()
      if result.state=='idle' or result.state=='held' then
        arrival()
        local distance,stops,blockedStops=0,0,0
        for _,flight in ipairs(legs) do distance=distance+flight.distance;if flight.interrupted then blockedStops=blockedStops+1 else stops=stops+1 end end
        local compact={}
        for _,a in pairs(accesses) do compact[#compact+1]={a.point.x,a.point.y,a.point.z,a.count,a.offset,a.velocity} end
        result.metrics={drone=name,trip=trip,start=started,finish=computer.uptime(),seconds=computer.uptime()-started,netBufferUsed=energy-computer.energy(),stops=stops,blockedStops=blockedStops,distance=distance,accesses=compact}
        -- Reuse the existing final report: observation adds no radio sends or
        -- wireless energy debits. Native radio cost is strength, not byte size.
        data=encode(result);assert(#data<7000,'instrumented result packet bound')
        trip=nil
      end
    end
    return send(address,p,t,kind,id,data,...)
  end
end
