-- Downloaded only to geolyzer carriers; controller owns the transient grid.
return function(command, move, position)
  local geo=component.proxy(component.list('geolyzer')())
  local inv=component.proxy(component.list('inventory_controller')())
  local before=computer.energy()
  local result={hops=0,scans=0,analyzes=0}
  local visited={position()}
  local function hop(p)
    local from=position()
    assert(math.abs(p.x-from.x)+math.abs(p.y-from.y)+math.abs(p.z-from.z)==1,'non-unit probe hop')
    move(p);visited[#visited+1]=p;result.hops=result.hops+1
  end
  local ok,reason=pcall(function()
    for _,p in ipairs(command.path or {}) do
      local from=position()
      local values=geo.scan(p.x-from.x,p.z-from.z,p.y-from.y,1,1,1)
      result.scans=result.scans+1
      assert(values[1]==0 or p.torch,'probe path no longer air')
      hop(p)
    end
    if command.scan then
      local s,p=command.scan,position()
      assert(s.w*s.d*s.h<=64,'scan volume')
      for _,v in ipairs({s.x-p.x,s.x+s.w-1-p.x,s.y-p.y,s.y+s.h-1-p.y,s.z-p.z,s.z+s.d-1-p.z}) do
        assert(math.abs(v)<=32,'scan range')
      end
      result.values=geo.scan(s.x-p.x,s.z-p.z,s.y-p.y,s.w,s.d,s.h)
      result.scans=result.scans+1
    elseif command.side then
      result.block=geo.analyze(command.side)
      result.size=inv.getInventorySize(command.side)
      result.analyzes=result.analyzes+1
      if result.block.name=='minecraft:torch' then
        local directions={{0,-1,0},{0,1,0},{0,0,-1},{0,0,1},{-1,0,0},{1,0,0}}
        local p=position();local d=directions[command.side+1]
        local passed,why=pcall(hop,{x=p.x+d[1],y=p.y+d[2],z=p.z+d[3]})
        result.clear=passed;result.reason=not passed and tostring(why) or nil
      end
    end
  end)
  for i=#visited-1,1,-1 do move(visited[i]);result.hops=result.hops+1 end
  result.energy=before-computer.energy()
  assert(ok,reason)
  return result
end
