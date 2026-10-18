local component=require("component")
local event=require("event")
local computer=require("computer")
local serialization=require("serialization")
local M={port=27104}
local sequence=0
function M.config()
  local f=io.open("/etc/mapclient.cfg","r");if not f then return {} end
  local text=f:read("*a");f:close()
  local chunk,err=load(text:match("^%s*return[%s{]") and text or "return "..text,"=mapclient.cfg","t",_G)
  assert(chunk,err);local value=chunk();assert(type(value)=="table","invalid mapclient config");return value
end
local function block(x,y,z)
  for _,n in ipairs({x,y,z}) do assert(type(n)=="number" and n==n and math.abs(n)<math.huge,"finite coordinates required") end
  assert(type(x)=="number" and type(y)=="number" and type(z)=="number","three coordinates required")
  return {x=math.floor(x),y=math.floor(y),z=math.floor(z)}
end
M.block=block
function M.nudge(p,axis,delta)
  assert((axis=="x" or axis=="y" or axis=="z") and (delta==1 or delta==-1),"axis and +/-1 required")
  local out=block(p.x,p.y,p.z);out[axis]=out[axis]+delta;return out
end
function M.search(nodes,query)
  query=(query or ""):lower();local out={}
  for name,node in pairs(nodes) do
    name=type(name)=="string" and name or node.name
    if name:lower():find(query,1,true) then
      local copy={};for k,v in pairs(node) do copy[k]=v end;copy.name=name;out[#out+1]=copy
    end
  end
  table.sort(out,function(a,b) if (a.created or 0)==(b.created or 0) then return a.name<b.name end;return (a.created or 0)>(b.created or 0) end)
  return out
end
function M.new(cfg)
  cfg=cfg or M.config();assert(type(cfg.key)=="string" and #cfg.key>0 and #cfg.key<=64,"mapclient key must be 1..64 bytes")
  local modem=assert(component.modem,"modem required");assert(modem.isWireless(),"wireless modem required");modem.open(M.port)
  local client={address=cfg.address}
  function client:position()
    if type(cfg.position)~="function" then return nil,"GPS unavailable; enter coordinates manually" end
    local ok,p=pcall(function() return block(cfg.position()) end)
    if not ok then return nil,"GPS failed; enter coordinates manually: "..tostring(p) end
    return p
  end
  function client:request(op,args,timeout)
    sequence=sequence+1;local id=computer.address()..":"..sequence
    local data=serialization.serialize(args or {},false);assert(#data<=6000,"request exceeds packet bound")
    if self.address then modem.send(self.address,M.port,"mapreq",cfg.key,id,op,data)
    else modem.broadcast(M.port,"mapreq",cfg.key,id,op,data) end
    local deadline=computer.uptime()+(timeout or ((op=="scan" or op=="test") and 120 or 5))
    while computer.uptime()<deadline do
      local e={event.pull(math.max(0,deadline-computer.uptime()),"modem_message")}
      if e[4]==M.port and e[6]=="mapreply" and e[7]==cfg.key and e[8]==id and (not self.address or e[3]==self.address) and type(e[11])=="string" and #e[11]<=6000 then
        local body=serialization.unserialize(e[11])
        if type(body)=="table" then
          self.address=self.address or e[3]
          if e[9]=="done" then if e[10] then return body.value,nil,true else return nil,body.value,false end end
        end
      end
    end
    return nil,"map request timed out",false
  end
  function client:list(op)
    local out,cursor={},nil
    repeat
      local result,err,ok=self:request(op,{cursor});if not ok then return nil,err end
      for name,value in pairs(result.entries) do out[name]=value end
      assert(not result.next or (not cursor or result.next>cursor),"invalid page cursor")
      cursor=result.next
    until not cursor
    return out
  end
  function client:nodes(query)
    local nodes,err=self:list("nodes");if not nodes then return nil,err end
    return M.search(nodes,query)
  end
  return client
end
return M
