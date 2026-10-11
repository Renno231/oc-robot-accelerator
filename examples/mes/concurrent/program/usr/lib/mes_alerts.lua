local event=require('event')
local now=require('computer').uptime
local stats=require('stats')
local ser=require('serialization')
local disk=require('store').open('/etc/mes.alerts','log')
local data=disk:load().state or {}
local rows=data.rows or {}
local quiet=data.quiet or {}
local cfg=data.settings or {heldMinutes=10,stuckFactor=1}
local seq=data.serial or 0
local index,timers={},{}
local M,refresh={}
local function pair(kind,key) return kind..':'..tostring(key) end
local shift=now()-(data.time or now())
for _,r in ipairs(rows) do
 r.raised=r.raised+shift
 if r.state=='dismissed' then r.dismissed=true end
 if r.cleared then r.cleared=r.cleared+shift else index[pair(r.kind,r.key)]=r end
end
local function emit(r) event.push('alert',r.id,r.kind,r.state) end
local function prune()
 local changed=false
 for i=#rows,1,-1 do local r=rows[i]
  if r.cleared and now()-r.cleared>=86400 then table.remove(rows,i);r.state='removed';emit(r);changed=true end
 end
 while #rows>200 do
  local at
  for _,state in ipairs({'cleared','dismissed'}) do
   for i,r in ipairs(rows) do if r.state==state then at=i;break end end
   if at then break end
  end
  if not at then break end
  local r=table.remove(rows,at);local k=pair(r.kind,r.key)
  if r.state=='dismissed' then quiet[k]=r.kind~='runFailed' and {r.kind,r.key,r.id} or nil;index[k]=nil end
  r.state='removed';emit(r);changed=true
 end
 return changed
end
local function save()
 prune();disk:put('state',{rows=rows,quiet=quiet,settings=cfg,serial=seq,time=now()});disk:flush()
end
local function has(kind,key) local k=pair(kind,key);return index[k] or quiet[k] end
local function observe(kind,key,present,text,due,machine,load)
 local k=pair(kind,key);local r=index[k];local timer=timers[k]
 if not present then
  if timer then event.cancel(timer.id);timers[k]=nil end
  if r then r.state='cleared';r.cleared=now();index[k]=nil;emit(r);save()
  elseif quiet[k] then local q=quiet[k];quiet[k]=nil;event.push('alert',q[3],kind,'removed');save() end
 elseif not has(kind,key) then
  if due and due>now() then
   if not timer or timer.due~=due then
    if timer then event.cancel(timer.id) end
    timers[k]={due=due,id=event.timer(due-now(),function() timers[k]=nil;refresh() end,1)}
   end
  else
   if timer then event.cancel(timer.id);timers[k]=nil end
   seq=seq+1;r={id=seq,kind=kind,key=key,text=text,raised=now(),state='active',machine=machine,load=load}
   rows[#rows+1]=r;index[k]=r;emit(r);save()
  end
 end
end
function M.list(filter)
 if prune() then save() end
 local out={}
 for _,r in ipairs(rows) do
  local match=not filter or filter==r.state or filter==r.kind
  if type(filter)=='table' then match=true;for k,v in pairs(filter) do if r[k]~=v then match=false end end end
  if match then out[#out+1]=ser.unserialize(ser.serialize(r)) end
 end
 return out
end
function M.dismiss(id)
 for _,r in ipairs(rows) do if r.id==id and r.state=='active' then r.state='dismissed';r.dismissed=true;emit(r);save();return true end end
 return false
end
function M.settings() local out=stats.settings();for k,v in pairs(cfg) do out[k]=v end;return out end
function M.owners()
 local out={};for k in pairs(stats.settings()) do out[k]='stats' end
 for k in pairs(cfg) do out[k]='alerts' end;return out
end
function M.set(k,v)
 if cfg[k] then
  local held=k=='heldMinutes'
  assert(type(v)=='number' and v<math.huge and (held and v>=1 and v%1==0 or not held and v>0),
   k..(held and ' must be a whole number of minutes >= 1' or ' must be a finite multiplier > 0'))
  if cfg[k]==v then return end;cfg[k]=v;save()
 else stats.set(k,v) end
 if refresh then refresh() end
end
function M.start(world)
 if refresh then return M end
 local seed={};for _,r in pairs(index) do seed[#seed+1]={r.kind,r.key} end
 for _,q in pairs(quiet) do seed[#seed+1]=q end
 refresh=require('mes_alert_sources').start(world,observe,has,M.settings,seed)
 if prune() then save() end
 refresh();return M
end
return M
