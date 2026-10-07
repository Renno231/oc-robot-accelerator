-- Opt-in acceptance observer for bounded, public-state failure diagnostics.
return function(lg,wh,save)
  local computer=require('computer');local event=require('event')
  local current
  local function snapshot(id,message)
    return {id=id,message=message,time=computer.uptime(),free=computer.freeMemory(),
      status=id and lg.status(id),jobs=lg.jobs(true),drones=lg.drones(),
      stock={brick=wh.count({name='minecraft:brick',damage=0}),clay=wh.count({name='minecraft:clay_ball',damage=0}),coal=wh.count({name='minecraft:coal',damage=0})}}
  end
  local onError=event.onError
  event.onError=function(message)
    pcall(save,'/home/cycle-event-error.lua',snapshot(current,tostring(message)))
    onError(message)
  end
  event.listen('logistics',function(_,id,state)
    save('/home/cycle-last-finished.lua',{id=id,state=state,time=computer.uptime()})
  end)
  return function(id,predicate,wait)
    current=id
    save('/home/cycle-progress.lua',{waiting=id,time=computer.uptime(),status=lg.status(id)})
    local ok,err=pcall(wait,predicate,600)
    if not ok then save('/home/cycle-failure.lua',snapshot(id,tostring(err)));error(err,0) end
    return lg.status(id)
  end
end
