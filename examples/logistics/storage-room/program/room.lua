-- Shared native entry for the dense hallway and open pillar layout.
return function(obstacle)
  local fs=require('filesystem')
  local function install(a,b) fs.makeDirectory(b);for n in fs.list(a) do local s,d=fs.concat(a,n),fs.concat(b,n);if fs.isDirectory(s) then install(s,d) else assert(fs.copy(s,d)) end end end;install('/home/program/usr','/usr')
  local event,computer=require('event'),require('computer')
  local serialization=require('serialization')
  local map=require('logistics.map')
  require('map-geometry-tests')(map)
  local function name(x,y) return 'N'..x..'_'..y end
  map.add('H',-2,65,2,{charger=true});map.add('H2',-2,65,5,{charger=true});map.link('H','H2')
  local w,h=obstacle and 7 or 8,obstacle and 7 or 4
  local function allowed(x,y) return not obstacle or not (x==3 and y>=2 and y<=4) end
  for x=0,w-1 do for y=0,h-1 do if allowed(x,y) then
    map.add(name(x,y),x,obstacle and 65 or 65+y,obstacle and 2+y or 2,{faces=obstacle and {[0]=true} or {[2]=true,[3]=true}})
    if x>0 and allowed(x-1,y) then map.link(name(x-1,y),name(x,y)) end
    if y>0 and allowed(x,y-1) then map.link(name(x,y-1),name(x,y)) end
  end end end
  map.link('H',name(0,0));map.save()
  local distances={}
  event.listen('modem_message',function(_,_,sender,port,distance,token) if port==27103 and token=='lgx_hello' then distances[sender]=distance end end)
  local half={x=.375,y=.1875,z=.375,offsetY=.1875}
  if map.smooth then
    local before=computer.freeMemory();local t=os.clock();local clear=map.buildClear(half)
    local count=0;for k in pairs(clear) do assert(type(k)=='number');count=count+1 end
    print('clear',count,'bytes',before-computer.freeMemory(),'cpuSeconds',os.clock()-t)
    assert(map.clearLine(name(0,0),name(0,h-1),half))
    assert(not map.clearLine({x=-20,y=65,z=2},{x=-19,y=65,z=2},half),'outside keys alias')
    if not obstacle then
      assert(#map.smooth(map.route(name(0,0),name(w-1,h-1)),half)==2,'hallway diagonal not collapsed')
      assert(#map.theta(name(0,0),name(w-1,h-1),half)==2)
    else assert(not map.clearLine(name(0,0),name(w-1,h-1),half),'pillar bypassed') end
  end
  local lg=require('logistics')
  local function wait(predicate,seconds)
    local deadline=computer.uptime()+seconds
    repeat if predicate() then return end;event.pull(math.max(0.1,deadline-computer.uptime())) until computer.uptime()>deadline
    error('room timeout')
  end
  wait(function() return #lg.pending()==2 end,20)
  local pending=lg.pending();table.sort(pending,function(a,b) return distances[a]<distances[b] end)
  for i=1,2 do assert(lg.register(pending[i],'d'..i,i==1 and 'H' or 'H2')) end
  wait(function() local d=lg.drones();return #d==2 and d[1].state=='idle' and d[2].state=='idle' end,30)
  local item={name='minecraft:iron_ingot',damage=0}
  local side=obstacle and 0 or 2
  local from={node=name(0,0),side=side}
  local to={node=name(w-1,h-1),side=obstacle and 0 or 3}
  local function done(id)
    wait(function() local s=lg.status(id);return s.state=='done' or s.state=='failed' or s.state=='partial' end,240)
    local s=lg.status(id);print('room job',id,serialization.serialize(s));return s
  end
  local s=done(lg.transfer(item,64,from,to,{drones=1,retries=0}));assert(s.state=='done' and s.moved==64)
  -- Reverse distant transfer also measures charger-to-far-corner entry, where
  -- A*'s chosen graph chain can anchor its forward pass later than Theta*.
  s=done(lg.transfer(item,64,to,from,{drones=1,retries=0}));assert(s.state=='done' and s.moved==64)
  s=done(lg.transfer(item,64,{node=name(0,h-1),side=side},{node=name(w-1,0),side=obstacle and 0 or 3},{drones=1,retries=0}));assert(s.state=='done' and s.moved==64)
  local parallel=false
  local function watch() local ds=lg.drones();if ds[1].state=='working' and ds[2].state=='working' then parallel=true end end
  event.listen('modem_message',watch)
  s=done(lg.transfer(item,512,from,to,{drones=2,retries=0}))
  event.ignore('modem_message',watch);assert(s.state=='done' and s.moved==512 and parallel,'parallel room delivery')
  -- Access every mapped face, not just the sampled transfer endpoints.
  local reads={}
  for x=0,w-1 do for y=0,h-1 do if allowed(x,y) then
    reads[#reads+1]={read={node=name(x,y),side=side,slots={27}}}
    if not obstacle then reads[#reads+1]={read={node=name(x,y),side=3,slots={27}}} end
  end end end
  -- Explicit slot 27 keeps listings empty and the complete sweep bounded.
  s=done(lg.job(reads,{drones=1}));assert(s.state=='done')
  for _,r in ipairs(s.steps) do assert(r.size and r.size>0,'inventory access failed') end
  if not obstacle then
    local f=assert(io.open('/home/storage-room-place-chest','w'));f:write('after mapping and access checks');f:close()
    assert(event.pull(10,'storage_room_chest_placed'),'native chest placement missing')
    -- A horizontal row leg forces a real stop at the inserted chest. The
    -- earlier corner flights cover diagonals separately; native collisions
    -- can slide an ascending trajectory around a chest without stalling.
    s=done(lg.transfer(item,64,{node=name(0,2),side=2},{node=name(w-1,2),side=3},{drones=1,retries=0}))
    assert(s.blockedReports and #s.blockedReports>=1,'smoothed blockage not detected')
    assert(s.state=='done' and s.moved==64,'room reroute failed')
    if map.smooth then assert(s.blockedReports[1].links and #s.blockedReports[1].links>0,'original link attribution missing') end
  end
end
