-- Measured on the native OC controller. os.clock is Machine.cpuTime at
-- pinned OC 8ca336fb server/machine/luac/OSAPI.scala:15-20.
return function(map)
  if not map.smooth then return end
  local serialization=require('serialization')
  local computer=require('computer')
  local half={x=.375,y=.1875,z=.375,offsetY=.1875}
  local before=computer.freeMemory();local t=os.clock();local clear=map.buildClear(half)
  local count=0;for _ in pairs(clear) do count=count+1 end
  local data={clearBlocks=count,clearBytes=before-computer.freeMemory(),buildSeconds=os.clock()-t,routes={}}
  local nodes=map.nodes();local names={};for n in pairs(nodes) do names[#names+1]=n end;table.sort(names)
  if #names>16 then
    names={}
    for _,n in ipairs({'H','H2','N0_0','N0_3','N7_0','N7_3','N0_6','N6_0','N6_6'}) do if nodes[n] then names[#names+1]=n end end
    table.sort(names)
  end
  local function describe(path)
    if not path then return nil end
    local distance=0;for i=2,#path do local a,b=nodes[path[i-1]],nodes[path[i]];local dx,dy,dz=a.x-b.x,a.y-b.y,a.z-b.z;distance=distance+math.sqrt(dx*dx+dy*dy+dz*dz) end
    return {path=path,stops=#path-1,distance=distance}
  end
  local logistics=require('logistics')
  for _,a in ipairs(names) do for _,b in ipairs(names) do if a<b then
    local row={from=a,to=b}
    local start=os.clock();local path=map.smooth(map.route(a,b),half);row.smoothSeconds=os.clock()-start;row.smooth=describe(path)
    start=os.clock();path=map.theta(a,b,half);row.thetaSeconds=os.clock()-start;row.theta=describe(path)
    -- Cache lookup uses the same nested [from][to] layout as logistics.
    local cache={[a]={[b]=path}};start=os.clock()
    for i=1,100 do path=cache[a][b] end
    row.cachedSeconds=(os.clock()-start)/100
    start=os.clock();local live=logistics.plan(a,b);row.liveColdSeconds=os.clock()-start
    start=os.clock();for i=1,10 do live=logistics.plan(a,b) end;row.liveCachedSeconds=(os.clock()-start)/10
    data.routes[#data.routes+1]=row
  end end end
  local f=assert(io.open('/home/planning-metrics.lua','w'));f:write(serialization.serialize(data));f:close()
end
