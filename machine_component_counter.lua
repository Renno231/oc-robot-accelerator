-- Acceptance instrumentation: public controller component-method entry points.
local component=require('component')
local counter={total=0,byType={},byMethod={}}
local decorated=setmetatable({},{__mode='k'})
local active
local function record(address,method)
  local kind=component.type(address) or 'unknown'
  counter.total=counter.total+1
  counter.byType[kind]=(counter.byType[kind] or 0)+1
  local key=kind..'.'..tostring(method)
  counter.byMethod[key]=(counter.byMethod[key] or 0)+1
end
local function counted(fn,address,method,...)
  local previous=active
  if not active or active.address~=address or active.method~=method then record(address,method) end
  active={address=address,method=method}
  local result=table.pack(pcall(fn,...))
  active=previous
  if not result[1] then error(result[2],0) end
  return table.unpack(result,2,result.n)
end
local invoke=component.invoke
-- OC's callable-table proxy methods delegate to this public invoke entry point.
-- Function-style proxies are decorated too; the active key prevents counting
-- their delegation to invoke twice.
component.invoke=function(address,method,...)
  return counted(invoke,address,method,address,method,...)
end
local function decorate(proxy)
  if type(proxy)~='table' or decorated[proxy] then return proxy end
  decorated[proxy]=true
  local address=proxy.address
  for method in pairs(component.methods(address) or {}) do
    local fn=proxy[method]
    if type(fn)=='function' then
      proxy[method]=function(...) return counted(fn,address,method,...) end
    end
  end
  return proxy
end
local proxy=component.proxy
component.proxy=function(...) return decorate(proxy(...)) end
-- Include already-created primary proxies held by OpenOS. Their table identity
-- stays unchanged; cached references see the same transparent method wrappers.
for address in component.list() do decorate(proxy(address)) end
local function copy(t) local out={};for k,v in pairs(t) do out[k]=v end;return out end
local function snapshot()
  return {total=counter.total,byType=copy(counter.byType),byMethod=copy(counter.byMethod)}
end
local function delta(before,after)
  local out={scope='controller',coverage='public component proxy/invoke method entries',
    total=after.total-before.total,byType={},byMethod={}}
  for _,key in ipairs({'byType','byMethod'}) do
    for k,n in pairs(after[key]) do
      local count=n-(before[key][k] or 0)
      if count>0 then out[key][k]=count end
    end
  end
  return out
end
return {snapshot=snapshot,delta=delta}
