-- Acceptance-only observer. Runs the unchanged native entry and exports final state.
local event=require('event')
local computer=require('computer')
local serialization=require('serialization')
local boots={}
local archivedJobs={}
local tripMetrics={}
event.listen('modem_message',function(_,_,sender,port,_,_,kind,id,text)
  if port==27103 and kind=='report' and type(text)=='string' then
    local result=serialization.unserialize(text)
    if type(result)=='table' and result.metrics then tripMetrics[#tripMetrics+1]=result.metrics end
  end
end)
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
local function json(out,v)
  if v==nil then out:write('null');return end
  if type(v)=='string' then out:write(quote(v));return end
  if type(v)=='number' or type(v)=='boolean' then out:write(tostring(v));return end
  assert(type(v)=='table','unsupported evidence value '..type(v))
  local n,array=0,true
  for k in pairs(v) do n=n+1;if type(k)~='number' or k<1 or k%1~=0 then array=false end end
  array=array and n==#v
  if array then
    out:write('[');for i=1,n do if i>1 then out:write(',') end;json(out,v[i]) end;out:write(']');return
  end
  local keys={};for k in pairs(v) do keys[#keys+1]=k end
  table.sort(keys,function(a,b) return tostring(a)<tostring(b) end)
  out:write('{')
  for i,k in ipairs(keys) do if i>1 then out:write(',') end;out:write(quote(tostring(k)),':');json(out,v[k]) end
  out:write('}')
end
local ok,err=xpcall(assert(loadfile('/home/program/native-main.lua')),debug.traceback)
local data={jobs=archivedJobs,fleet={},files={},boots=boots,returned=ok,programStarts=count+1,reloadPending=reloadPending}
data.flightMetrics=tripMetrics
local planning=io.open('/home/planning-metrics.lua','r')
if planning then data.planning=serialization.unserialize(planning:read('*a'));planning:close() end
local lg=package.loaded.logistics
local warehouse=io.open('/home/warehouse-results.lua','r')
if warehouse then data.warehouse=assert(serialization.unserialize(warehouse:read('*a')));warehouse:close() end
local memory=io.open('/home/warehouse-memory.lua','r')
if memory then data.warehouseMemory=assert(serialization.unserialize(memory:read('*a')));memory:close() end
local performance=io.open('/home/warehouse-performance.lua','r')
if performance then data.warehousePerformance=assert(serialization.unserialize(performance:read('*a')));performance:close() end
if lg then
  for id=1,1000 do local s=lg.status(id);if s then data.jobs[tostring(id)]=s end end
  for _,d in ipairs(lg.drones()) do
    data.fleet[#data.fleet+1]={name=d.name,address=d.address,state=d.state,node=d.node,cargo=d.cargo,releasePending=d.releasePending,boots=d.boots}
  end
end
for _,path in ipairs({'/etc/map.cfg','/etc/logistics.cfg','/etc/logistics.drones','/etc/logistics.routes','/etc/warehouse.cfg'}) do
  local f=io.open(path,'r')
  if f then local s=f:read('*a');f:close();data.files[path]=assert(serialization.unserialize(s)) end
end
local journal=io.open('/etc/warehouse.db','r')
if journal then
  local catalogue={};for line in journal:lines() do local r=assert(serialization.unserialize(line));catalogue[r.key]=r.value end
  journal:close();data.files['/etc/warehouse.db']=catalogue
end
-- Stream through OpenOS's bounded file buffer, not one large recursively
-- concatenated JSON string competing with the loaded controller libraries.
local out=assert(io.open('/home/equivalence.json','w'));json(out,data);out:close()
if not ok then error(err,0) end
