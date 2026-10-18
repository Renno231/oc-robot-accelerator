-- Separate diagnostic run, not the uninstrumented deployment-memory sample.
-- Public API wrappers preserve returned values and only sample freeMemory.
local measure=assert(loadfile('/home/program/deployment-memory-base.lua'))()
return function(save)
  local preexisting={keyboard=package.loaded.keyboard~=nil,tty=package.loaded.tty~=nil,term=package.loaded.term~=nil}
  local computer=require('computer');local wh=require('logistics.warehouse');local lg=require('logistics');local map=require('logistics.map')
  local view=require('logistics.warehouse.view');local qmenu=require('qmenu')
  local phases={};local restores={}
  local function wrap(object,name,label)
    local original=object[name];local metric={calls=0,allocated=0,net=0,gcReturns=0,max=0};phases[label]=metric
    object[name]=function(...)
      local before=computer.freeMemory();local returns=table.pack(original(...));local used=before-computer.freeMemory()
      metric.calls=metric.calls+1;metric.net=metric.net+used
      if used>=0 then metric.allocated=metric.allocated+used;metric.max=math.max(metric.max,used) else metric.gcReturns=metric.gcReturns+1 end
      return table.unpack(returns,1,returns.n)
    end
    restores[#restores+1]=function() object[name]=original end
  end
  for _,name in ipairs({'members','groups','contents'}) do wrap(wh,name,'warehouse.'..name) end
  for _,name in ipairs({'jobs','status','drones'}) do wrap(lg,name,'logistics.'..name) end
  wrap(map,'storages','map.storages');wrap(view,'build','view.build')
  local create=qmenu.create
  qmenu.create=function(...)
    local menu=create(...);wrap(menu,'draw','qmenu.draw');return menu
  end
  local ok,err=pcall(measure,function(path,data)
    if path=='/home/warehouse-memory.lua' then data.allocationProfile=phases;data.profileOnly=true;data.preexistingOpenOS=preexisting end
    save(path,data)
  end)
  qmenu.create=create;for _,restore in ipairs(restores) do restore() end
  assert(ok,err)
end
