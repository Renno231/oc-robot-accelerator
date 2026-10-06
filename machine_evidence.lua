-- Acceptance-only observer. Runs the unchanged native entry and exports final state.
local event=require('event')
local computer=require('computer')
local serialization=require('serialization')
local boots={}
local archivedJobs={}
local originalRequire=require
local instrumented=false
require=function(name)
  local value=originalRequire(name)
  if name=='logistics' and not instrumented then
    instrumented=true
    local cancel=value.cancel
    value.cancel=function(id,...)
      local ok,err=cancel(id,...)
      local status=value.status(id)
      if status then archivedJobs[tostring(id)]=serialization.unserialize(serialization.serialize(status)) end
      return ok,err
    end
  end
  return value
end
local starts=io.open('/home/program-starts','r')
local count=starts and tonumber(starts:read('*a')) or 0
if starts then starts:close() end
starts=assert(io.open('/home/program-starts','w'));starts:write(tostring(count+1));starts:close()
local reloadPending=0
event.listen('runner_reload_pending',function(_,value)
  assert(value=='persisted');reloadPending=reloadPending+1
  local f=assert(io.open('/home/reload-ack','w'));f:write(tostring(reloadPending));f:close()
end)
event.listen('modem_message',function(_,_,sender,port,_,_,kind)
  if port==27103 and kind=='boot' then
    boots[#boots+1]={sender=sender,time=computer.uptime()}
  end
end)
local function quote(s)
  return '"'..s:gsub('[%z\1-\31\\"]',function(c)
    if c=='"' or c=='\\' then return '\\'..c end
    return string.format('\\u%04x',string.byte(c))
  end)..'"'
end
local function json(v)
  if v==nil then return 'null' end
  if type(v)=='string' then return quote(v) end
  if type(v)=='number' or type(v)=='boolean' then return tostring(v) end
  assert(type(v)=='table','unsupported evidence value '..type(v))
  local n,array=0,true
  for k in pairs(v) do n=n+1;if type(k)~='number' or k<1 or k%1~=0 then array=false end end
  array=array and n==#v
  local out={}
  if array then for i=1,n do out[#out+1]=json(v[i]) end;return '['..table.concat(out,',')..']' end
  local keys={};for k in pairs(v) do keys[#keys+1]=k end
  table.sort(keys,function(a,b) return tostring(a)<tostring(b) end)
  for _,k in ipairs(keys) do out[#out+1]=quote(tostring(k))..':'..json(v[k]) end
  return '{'..table.concat(out,',')..'}'
end
local ok,err=xpcall(assert(loadfile('/home/program/native-main.lua')),debug.traceback)
local data={jobs=archivedJobs,fleet={},files={},boots=boots,returned=ok,programStarts=count+1,reloadPending=reloadPending}
local lg=package.loaded.logistics
if lg then
  for id=1,1000 do local s=lg.status(id);if s then data.jobs[tostring(id)]=s end end
  for _,d in ipairs(lg.drones()) do
    data.fleet[#data.fleet+1]={name=d.name,address=d.address,state=d.state,node=d.node,cargo=d.cargo,releasePending=d.releasePending,boots=d.boots}
  end
end
for _,path in ipairs({'/etc/map.cfg','/etc/logistics.cfg','/etc/logistics.drones','/etc/logistics.routes'}) do
  local f=io.open(path,'r')
  if f then local s=f:read('*a');f:close();data.files[path]=assert(serialization.unserialize(s)) end
end
local out=assert(io.open('/home/equivalence.json','w'));out:write(json(data));out:close()
if not ok then error(err,0) end
