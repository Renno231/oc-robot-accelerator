local logistics=require("logistics")
local serialization=require("serialization")
local args={...};local command=table.remove(args,1)
local function endpoint(s)
  if s and not s:find(":",1,true) then return s end
  local node,side,slot=assert(s,"endpoint node:side[:slot] required"):match("^([^:]+):(%d+):?(%d*)$")
  assert(node,"endpoint node:side[:slot] required")
  return {node=node,side=tonumber(side),slots=slot~="" and {tonumber(slot)} or nil}
end
local value,err
if command=="pending" then value=logistics.pending()
elseif command=="register" then value,err=logistics.register(args[1],args[2],args[3])
elseif command=="forget" then value,err=logistics.forget(args[1])
elseif command=="release" then
  value,err=logistics.release(args[1])
  if value then
    local event=require("event");local _,name,status
    repeat _,name,status=event.pull("logistics_released") until name==args[1]
    if status=="ok" then
      for _,d in ipairs(logistics.drones()) do if d.name==name then value=d.cargo;break end end
    else value=nil;err="cargo report timeout" end
  end
elseif command=="found" then value,err=logistics.found(args[1])
elseif command=="drones" then value=logistics.drones()
elseif command=="routes" then value=logistics.routes()
elseif command=="run" then value=logistics.run(args[1])
elseif command=="status" then value=logistics.status(tonumber(args[1]))
elseif command=="transfer" then
  -- transfer ITEM COUNT FROM TO [DAMAGE [RETRIES [DRONES]]]
  value=logistics.transfer({name=args[1],damage=tonumber(args[5]) or 0},tonumber(args[2]),endpoint(args[3]),endpoint(args[4]),{retries=tonumber(args[6]),drones=tonumber(args[7])})
else error("logistics pending|register addr name home|forget name|release name|found name|drones|routes|run route|status id|transfer item count endpoint endpoint [damage [retries [drones]]]") end
if err then io.stderr:write(err,"\n") else print(serialization.serialize(value)) end
