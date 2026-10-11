-- UI-lab fake of mes_alerts: the same calls, record fields
-- {id,kind,key,text,raised,state[,cleared]}, list filter rule, settings
-- check (same error text; stats keys go to the stats fake) and the
-- ("alert",id,kind,state) signal. One store, so a dismissal is shared.
-- Lab hooks stand in for the causes: labRaise/labClear/labDismiss by
-- (kind,key), as the engine's observe() and another screen would.
local event=require("event");local now=require("computer").uptime;local stats=require("stats")
local M={};local rows,cfg,seq={},{heldMinutes=10,stuckFactor=1},0
local function emit(r) event.push("alert",r.id,r.kind,r.state) end
local function copy(r) local t={};for k,v in pairs(r) do t[k]=v end;return t end
local function open(kind,key) for _,r in ipairs(rows) do if r.kind==kind and r.key==key and r.state~="cleared" then return r end end end
function M.list(filter)
  local out={}
  for _,r in ipairs(rows) do
    local match=not filter or filter==r.state or filter==r.kind
    if type(filter)=="table" then match=true;for k,v in pairs(filter) do if r[k]~=v then match=false end end end
    if match then out[#out+1]=copy(r) end
  end
  return out
end
function M.dismiss(id)
  for _,r in ipairs(rows) do if r.id==id and r.state=="active" then r.state="dismissed";emit(r);return true end end
  return false
end
function M.settings() local out=stats.settings();for k,v in pairs(cfg) do out[k]=v end;return out end
function M.set(k,v)
  if cfg[k] then
    assert(type(v)=="number" and v>=0 and v<math.huge,"invalid setting")
    if cfg[k]==v then return end;cfg[k]=v
  else stats.set(k,v) end
end
function M.start() return M end
-- age: seconds since it was raised (for a list with history).
function M.labRaise(kind,key,text,age)
  if open(kind,key) then return end
  seq=seq+1;local r={id=seq,kind=kind,key=key,text=text,raised=now()-(age or 0),state="active"};rows[#rows+1]=r;emit(r)
end
function M.labClear(kind,key) local r=open(kind,key);if r then r.state="cleared";r.cleared=now();emit(r) end end
function M.labDismiss(kind,key) local r=open(kind,key);if r then M.dismiss(r.id) end end
-- alerts3: three active alerts of different kinds, raised 25, 8 and 2 m ago.
function M.labThree()
  M.labRaise("droneLost","drone5","Drone lost: drone5",1500)
  M.labRaise("importBlocked","in2","stock full: 40 Cobblestone left in in2",480)
  M.labRaise("machineStuck","furnaceA:3","Machine stuck: furnaceA",120)
end
return M
