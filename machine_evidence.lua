-- Acceptance-only observer. Runs the unchanged native entry and exports final state.
local event=require('event')
local computer=require('computer')
local serialization=require('serialization')
local boots={}
local archivedJobs={}
local tripMetrics={}
local craftPayloads={}
event.listen('modem_message',function(_,_,sender,port,_,_,kind,id,text)
  if port==27103 and kind=='report' and type(text)=='string' then
    local result=serialization.unserialize(text)
    if type(result)=='table' and result.metrics then tripMetrics[#tripMetrics+1]=result.metrics end
  end
end)
local originalRequire=require
local instrumented=false
local transportInstrumented=false
require=function(name)
  local value=originalRequire(name)
  if name=='tnet' and not transportInstrumented then
    transportInstrumented=true
    local connect=value.connect
    value.connect=function(...)
      local conn=connect(...)
      local send=conn.send
      local modem,observed=conn.modem,nil
      conn.modem=setmetatable({send=function(...)
        if observed then
          local wire=table.pack(...);local bytes=2*(wire.n-2)
          for i=3,wire.n do
            assert(type(wire[i])=='string','unexpected craft packet part')
            bytes=bytes+#wire[i]
          end
          observed.packetBytes=math.max(observed.packetBytes,bytes)
          observed.fragments=observed.fragments+1
          observed.physicalPackets[#observed.physicalPackets+1]={bytes=bytes,ninfo=wire[4]}
        end
        return modem.send(...)
      end},{__index=modem})
      conn.send=function(self,message,...)
        local args=table.pack(...)
        local previous=observed;observed=nil
        local request=message=='craft' and args[1] or nil
        if message=='rpc' and args[1]=='rpc_call' and args[2]=='craft' and type(args[4])=='table' then
          request={plan=args[4][1],jobId=args[4][2]}
        end
        if type(request)=='table' and type(request.plan)=='table' then
          local payload=serialization.serialize({msg=message,args=args})
          local info=computer.getDeviceInfo()[self.modem.address]
          local limit=assert(info and tonumber(info.capacity),'missing observed modem packet limit')
          -- Measure actual physical frames, including the library's fragments.
          observed={jobId=request.jobId,address=self.address,
            payloadBytes=#payload,planBytes=#serialization.serialize(request.plan),
            packetBytes=0,packetLimit=limit,parts=4,fragments=0,physicalPackets={}}
          craftPayloads[#craftPayloads+1]=observed
        end
        local result=table.pack(pcall(send,self,message,table.unpack(args,1,args.n)))
        observed=previous
        if not result[1] then error(result[2],0) end
        return table.unpack(result,2,result.n)
      end
      return conn
    end
  end
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
local controllerMemory={total=computer.totalMemory(),freeAtStart=computer.freeMemory()}
local component=require('component')
if component.isAvailable('gpu') then
  local screen=assert(component.gpu.getScreen(),'GPU not bound to native screen')
  controllerMemory.screen=screen
  controllerMemory.keyboards=component.proxy(screen).getKeyboards()
  assert(#controllerMemory.keyboards>0,'native screen has no keyboard')
end
local componentCounter=assert(loadfile('/home/program/component-counter.lua'))()
package.loaded.runner_component_calls=componentCounter
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
if not ok then print('Native entry failed:',err) end
local data={jobs=archivedJobs,fleet={},files={},boots=boots,returned=ok,programStarts=count+1,reloadPending=reloadPending}
controllerMemory.freeAtEnd=computer.freeMemory()
data.controllerMemory=controllerMemory
data.craftPayloads=craftPayloads
data.flightMetrics=tripMetrics
local componentCalls=io.open('/home/component-calls.lua','r')
if componentCalls then
  data.componentCalls=serialization.unserialize(componentCalls:read('*a'));componentCalls:close()
end
local planning=io.open('/home/planning-metrics.lua','r')
if planning then data.planning=serialization.unserialize(planning:read('*a'));planning:close() end
local lg=package.loaded.logistics
local warehouse=io.open('/home/warehouse-results.lua','r')
if warehouse then data.warehouse=assert(serialization.unserialize(warehouse:read('*a')));warehouse:close() end
-- Preserve the terminal MES ledger even when a later native acceptance oracle
-- fails before warehouse-results is written.
local mesExecution=io.open('/home/mes-execution.lua','r')
if mesExecution then data.mesExecution=assert(serialization.unserialize(mesExecution:read('*a')));mesExecution:close() end
local mesProgress=io.open('/home/mes-progress.lua','r')
if mesProgress then data.mesProgress=assert(serialization.unserialize(mesProgress:read('*a')));mesProgress:close() end
local mesFetchTimings=io.open('/home/mes-fetch-timings.lua','r')
if mesFetchTimings then data.mesFetchTimings=assert(serialization.unserialize(mesFetchTimings:read('*a')));mesFetchTimings:close() end
local memory=io.open('/home/warehouse-memory.lua','r')
if memory then data.warehouseMemory=assert(serialization.unserialize(memory:read('*a')));memory:close() end
local performance=io.open('/home/warehouse-performance.lua','r')
if performance then data.warehousePerformance=assert(serialization.unserialize(performance:read('*a')));performance:close() end
local ui=io.open('/home/warehouse-ui-results.lua','r')
if ui then data.warehouseUI=assert(serialization.unserialize(ui:read('*a')));ui:close() end
local uiPlanning=io.open('/home/ui-planning.lua','r')
if uiPlanning then data.warehouseUIPlanning=assert(serialization.unserialize(uiPlanning:read('*a')));uiPlanning:close() end
if lg then
  for id=1,1000 do local s=lg.status(id);if s then data.jobs[tostring(id)]=s end end
  for _,d in ipairs(lg.drones()) do
    data.fleet[#data.fleet+1]={name=d.name,address=d.address,state=d.state,node=d.node,cargo=d.cargo,releasePending=d.releasePending,boots=d.boots}
  end
end
for _,path in ipairs({'/etc/logistics.cfg','/etc/logistics.drones','/etc/logistics.routes','/etc/warehouse.cfg','/etc/warehouse.stacks'}) do
  local f=io.open(path,'r')
  if f then local s=f:read('*a');f:close();data.files[path]=assert(serialization.unserialize(s)) end
end
-- Binary store.lua records are decoded from the final native HDD in Python
-- (native_store_evidence), never interpreted as OpenOS serialization lines.
-- Stream through OpenOS's bounded file buffer, not one large recursively
-- concatenated JSON string competing with the loaded controller libraries.
data.storeMeasurements=package.loaded.runner_store_measurements
local out=assert(io.open('/home/equivalence.json','w'));json(out,data);out:close()
if not ok then error(err,0) end
