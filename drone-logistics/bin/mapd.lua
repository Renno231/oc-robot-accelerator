-- Install once; callbacks run in the caller's ordinary OpenOS event pulls.
if package.loaded.mapd then return package.loaded.mapd end
local component=require("component")
local event=require("event")
local serialization=require("serialization")
local map=require("map")
local f=assert(io.open("/etc/mapd.cfg","r"));local cfg=serialization.unserialize(f:read("*a"));f:close()
assert(type(cfg)=="table" and type(cfg.key)=="string" and #cfg.key>0 and #cfg.key<=64,"mapd key must be 1..64 bytes")
local modem=assert(component.modem,"modem required");assert(modem.isWireless(),"wireless modem required")
local port,bound=27104,6000
modem.open(port)
local edits={add=true,remove=true,link=true,unlink=true,name=true,unname=true,save=true}
local reads={node=true,storage=true}
local pending={}
local function reply(address,id,phase,ok,value)
  local data=serialization.serialize({value=value},false)
  if #data>bound then ok=false;data=serialization.serialize({value="reply entry exceeds packet bound"},false) end
  modem.send(address,port,"mapreply",cfg.key,id,phase,ok,data)
end
local function page(values,after)
  assert(after==nil or type(after)=="string","invalid page cursor")
  local names={};for name in pairs(values) do if not after or name>after then names[#names+1]=name end end;table.sort(names)
  local out={entries={}}
  for i,name in ipairs(names) do
    out.entries[name]=values[name];out.next=i<#names and name or nil
    if #serialization.serialize({value=out},false)>bound then
      out.entries[name]=nil;assert(i>1,"reply entry exceeds packet bound")
      out.next=names[i-1];break
    end
  end
  return out
end
local function receive(_,_,sender,received,_,tag,key,id,op,data)
  if received~=port or tag~="mapreq" or key~=cfg.key then return end
  if type(id)~="string" or #id>96 or type(op)~="string" or type(data)~="string" or #data>bound then return end
  local args=serialization.unserialize(data)
  if type(args)~="table" then reply(sender,id,"done",false,"invalid arguments");return end
  local ok,value=pcall(function()
    if edits[op] or reads[op] then
      local result=map[op](table.unpack(args));if edits[op] and op~="save" then map.save() end
      return result
    elseif op=="nodes" or op=="storages" then return page(map[op](),args[1])
    elseif op=="scan" or op=="test" then
      local logistics=package.loaded.logistics;assert(type(logistics)=="table","logistics not loaded")
      local job=logistics[op](table.unpack(args));pending[job]={address=sender,id=id}
      return {job=job}
    else error("unknown map operation") end
  end)
  reply(sender,id,ok and (op=="scan" or op=="test") and "pending" or "done",ok,value)
end
local function completed(_,id)
  local request=pending[id];if not request then return end;pending[id]=nil
  local result=package.loaded.logistics.status(id)
  reply(request.address,request.id,"done",result.state=="done" or result.test=="blocked",result)
end
event.listen("modem_message",receive);event.listen("logistics",completed)
local service={port=port}
package.loaded.mapd=service
return service
