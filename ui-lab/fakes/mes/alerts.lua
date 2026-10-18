-- UI-lab fake of mes_alerts (drone-logistics 16bd577): the same calls
-- (list, dismiss, settings, owners, set, start), record fields
-- {id,kind,key,text,raised,state[,cleared][,dismissed][,machine,load][,item]},
-- list filter rule, set() checks and error texts (stats keys go to the
-- stats fake), the 24 h / 200-row pruning with its "removed" signal, the
-- one-shot timer that prunes at the earliest cleared row's expiry, the
-- quiet set of evicted dismissed conditions, and the ("alert",id,kind,
-- state) signal. One store, so a dismissal is shared. Not modelled: the
-- sources' re-scan after set() and persistence.
-- Lab hooks stand in for the causes, as the engine's observe() and another
-- screen would: labRaise/labClear/labDismiss by (kind,key).
local event=require("event");local now=require("computer").uptime;local stats=require("logistics.stats")
local M={};local rows,quiet,index,cfg,seq={},{},{},{heldMinutes=10,stuckFactor=1},0
local expiry,deadline
local function pair(kind,key) return kind..":"..tostring(key) end
local function emit(r) event.push("alert",r.id,r.kind,r.state) end
local function copy(r) local t={};for k,v in pairs(r) do t[k]=v end;return t end
local function prune()
  local changed=false
  for i=#rows,1,-1 do local r=rows[i]
    if r.cleared and now()-r.cleared>=86400 then table.remove(rows,i);r.state="removed";emit(r);changed=true end
  end
  while #rows>200 do
    local at
    for _,state in ipairs({"cleared","dismissed"}) do
      for i,r in ipairs(rows) do if r.state==state then at=i;break end end
      if at then break end
    end
    if not at then break end
    local r=table.remove(rows,at);local k=pair(r.kind,r.key)
    if r.state=="dismissed" then quiet[k]=r.kind~="runFailed" and {r.kind,r.key,r.id} or nil;index[k]=nil end
    r.state="removed";emit(r);changed=true
  end
  local due
  for _,r in ipairs(rows) do if r.cleared then due=math.min(due or math.huge,r.cleared+86400) end end
  if due~=deadline then
    if expiry then event.cancel(expiry) end
    deadline=due;expiry=due and event.timer(math.max(0,due-now()),prune,1)
  end
  return changed
end
function M.list(filter)
  prune();local out={}
  for _,r in ipairs(rows) do
    local match=not filter or filter==r.state or filter==r.kind
    if type(filter)=="table" then match=true;for k,v in pairs(filter) do if r[k]~=v then match=false end end end
    if match then out[#out+1]=copy(r) end
  end
  return out
end
function M.dismiss(id)
  for _,r in ipairs(rows) do if r.id==id and r.state=="active" then r.state="dismissed";r.dismissed=true;emit(r);prune();return true end end
  return false
end
function M.settings() local out=stats.settings();for k,v in pairs(cfg) do out[k]=v end;return out end
function M.owners()
  local out={};for k in pairs(stats.settings()) do out[k]="stats" end
  for k in pairs(cfg) do out[k]="alerts" end;return out
end
function M.set(k,v)
  if cfg[k] then
    local held=k=="heldMinutes"
    assert(type(v)=="number" and v<math.huge and (held and v>=1 and v%1==0 or not held and v>0),
      k..(held and " must be a whole number of minutes >= 1" or " must be a finite multiplier > 0"))
    if cfg[k]==v then return end;cfg[k]=v;prune()
  else stats.set(k,v) end
end
function M.start() return M end
-- observe(kind,key,true,...) at once (no due time); age: seconds since it
-- was raised (for a list with history).
function M.labRaise(kind,key,text,age,machine,load,item)
  local k=pair(kind,key);if index[k] or quiet[k] then return end
  seq=seq+1;local r={id=seq,kind=kind,key=key,text=text,raised=now()-(age or 0),state="active",machine=machine,load=load,item=item}
  rows[#rows+1]=r;index[k]=r;emit(r);prune()
end
-- observe(kind,key,false); age: seconds since it cleared.
function M.labClear(kind,key,age)
  local k=pair(kind,key);local r=index[k]
  if r then r.state="cleared";r.cleared=now()-(age or 0);index[k]=nil;emit(r);prune()
  elseif quiet[k] then local q=quiet[k];quiet[k]=nil;event.push("alert",q[3],kind,"removed") end
end
function M.labDismiss(kind,key) local r=index[pair(kind,key)];if r then M.dismiss(r.id) end end
-- alerts3: three active alerts of different kinds, raised 25, 8 and 2 m ago.
function M.labThree()
  M.labRaise("droneLost","drone5","Drone lost: drone5",1500)
  M.labRaise("importBlocked","in2","stock full: 40 Cobblestone left in in2",480)
  M.labRaise("machineStuck","furnaceA:3","Machine stuck: furnaceA",120,"furnaceA",3)
end
-- alertshist: a failed run with its item and an older record without one
-- (id only); a stuck machine whose name has a colon; drone2 held,
-- dismissed, then cleared; drone4 lost, cleared 24 h less 20 s ago (the
-- expiry timer removes it 20 s in: a "removed" signal).
function M.labHistory()
  M.labRaise("runFailed","5f0c2a9e41b7d3c8a6e2f9b1d4c7a038","Run failed: minecraft:iron_ingot",300,nil,nil,"minecraft:iron_ingot")
  M.labRaise("runFailed","c19d7e2b8a4f6035e1b9d2c7f8a40e6b","Run failed: c19d7e2b8a4f6035e1b9d2c7f8a40e6b",5400)
  M.labRaise("machineStuck","press:north:4","Machine stuck: press:north",600,"press:north",4)
  M.labRaise("droneHeld","drone2","Cargo held: drone2",3600);M.labDismiss("droneHeld","drone2");M.labClear("droneHeld","drone2",900)
  M.labRaise("droneLost","drone4","Drone lost: drone4",90000);M.labClear("droneLost","drone4",86380)
end
return M
