-- Alerts: the alert engine's records (mes_alerts), active first, then the
-- dismissed and cleared ones it keeps; the detail of the selected one,
-- dismiss (shared by every screen) and the alert settings. Read on open,
-- R and the "alert" signal only; nothing is polled.
local ui=require("mes_ui.core");local computer=require("computer")
local S={hints="Enter detail · D dismiss · S settings · R refresh · H help",
  help={{"Enter","detail: the cause and what clears it"},{"D","dismiss the selected active alert, on every screen"},{"S","alert settings and thresholds"}}}
local function engine() local ok,m=pcall(require,"mes_alerts");return ok and m or nil end
local function pct(f) return math.floor((f or 0)*100+0.5).."%" end
local function ago(t)
  local s=computer.uptime()-(t or 0)
  if s<60 then return math.max(0,math.floor(s)).." s ago" elseif s<3600 then return math.floor(s/60).." m ago" elseif s<86400 then return math.floor(s/3600).." h ago" end
  return math.floor(s/86400).." d ago"
end
local function wrap(s,w)
  local out,line={},"";for word in tostring(s):gmatch("%S+") do
    if line~="" and #line+1+#word>w then out[#out+1]=line;line=word else line=line=="" and word or line.." "..word end
  end
  if line~="" then out[#out+1]=line end;return out
end
local sections={{"active","Active",""},{"dismissed","Dismissed"," · hidden on every screen until the cause clears"},{"cleared","Cleared"," · kept for 24 h"}}
local stateFg={active="bad",dismissed="warn",cleared="dim"}

function S:open()
  local a=ui.area();self.rows={};self.n={}
  self.lw=ui.wide() and math.floor(a.w*0.58) or a.w
  self.list=ui.list(self.menu,{name="a",x=1,y=a.y+1,w=self.lw,h=a.h-1,
    count=function() return #self.rows end,
    row=function(i,w) return self:row(i,w) end,
    activate=function(i) self:detail(i) end,
    moved=function(i) self:pane(i) end})
  self:rebuild();self.list:refresh();self.list:first()
end
-- Keeps the cursor on the same alert across a re-read.
function S:rebuild()
  local rows,P=self.rows,ui.P;local was=rows[self.list.cur];was=was and was.id
  for k=#rows,1,-1 do rows[k]=nil end
  local m=engine();local all=m and ui.try(m.list) or {};self.cfg=m and ui.try(m.settings) or {}
  table.sort(all,function(p,q) return p.id>q.id end)
  for _,s in ipairs(sections) do
    local n=0;for _,r in ipairs(all) do if r.state==s[1] then n=n+1 end end;self.n[s[1]]=n
    if #rows>0 then rows[#rows+1]={heading=""} end
    rows[#rows+1]={heading=s[2].." ("..n..")"..s[3],fg=n>0 and s[1]=="active" and P.bad or P.accent}
    for _,r in ipairs(all) do if r.state==s[1] then rows[#rows+1]=r;if r.id==was then self.list.cur=#rows end end end
    if n==0 then rows[#rows+1]={heading="  none",fg=P.dim} end
  end
  self.dirty=false
end
function S:row(i,w)
  local r=self.rows[i];local P=ui.P
  if r.heading then return r.heading,r.fg,true end
  local st=r.state=="cleared" and "cleared "..ago(r.cleared) or r.state
  return "  "..ui.fit(ui.alertKinds[r.kind] or r.kind,22)..ui.fit(ui.alertSubject(r),w-60)..ui.fit(ago(r.raised),14)..ui.fit(st,22),P[stateFg[r.state]]
end
-- Cause and what clears it, from the alert table (ALERTS spec).
function S:lines(r,w)
  local P,c=ui.P,self.cfg;local k,who=r.kind,ui.alertSubject(r);local cause,clears
  if k=="runFailed" then cause="Run "..tostring(r.key).." ended failed.";clears="Only dismissing it: the failure is in the past, so nothing else clears it."
  elseif k=="droneLost" then cause="Logistics marked "..who.." lost.";clears="The drone is found (Fleet: Enter on it marks it found) or reports ready again."
  elseif k=="droneHeld" then cause=who.." has been held, keeping its cargo, for longer than "..tostring(c.heldMinutes).." min.";clears="It is no longer held: its cargo is released (Fleet: Enter on it)."
  elseif k=="stockFull" then cause="Stock is "..pct(c.fillBad).." full or more, or at this rate it will be full within "..tostring(c.fullSoonHours).." h."
    clears="Fill drops below "..pct((c.fillBad or 0)-.02).." and stock is no longer forecast to be full soon."
  elseif k=="machineStuck" then local mn,ln=tostring(r.key):match("^(.*):(%d+)$")
    cause="Load "..(ln or "?").." on machine "..(mn or who).." is past its due time by more than "..tostring(c.stuckFactor).."× its duration, and its output has not been collected."
    clears="Its output is collected, or the load is quarantined."
  elseif k=="importBlocked" then cause="Import chest "..who.." cannot put its items away: stock is full.";clears="The chest no longer reports stock full (there is room in stock)."
  elseif k=="exportFull" then cause="Export chest "..who.." is full.";clears="The chest no longer reports it is full (take items out of it)."
  else cause=tostring(r.text);clears="Its cause clears." end
  local lines={{ui.alertKinds[k] or k,P.accent},who,""}
  local function add(t,fg) for _,l in ipairs(wrap(t,w)) do lines[#lines+1]={l,fg} end end
  lines[#lines+1]=ui.fit("Raised",10)..ago(r.raised).." · alert #"..r.id
  lines[#lines+1]={ui.fit("State",10)..(r.state=="cleared" and "cleared "..ago(r.cleared) or r.state),P[stateFg[r.state]]}
  lines[#lines+1]="";lines[#lines+1]={"Cause",P.dim};add(cause)
  if (k=="importBlocked" or k=="exportFull") and r.text then add("Reported: "..r.text,P.warn) end
  lines[#lines+1]="";lines[#lines+1]={"Clears when",P.dim};add(clears)
  lines[#lines+1]=""
  if r.state=="active" then add("D dismisses it on every screen.",P.dim)
  elseif r.state=="dismissed" then add(k=="runFailed" and "Dismissed on every screen." or "Dismissed on every screen. If the cause clears and comes back, that is a new alert.",P.dim) end
  return lines
end
function S:pane(i)
  if not ui.wide() then return end
  local a=ui.area();local r=self.rows[i or self.list.cur];local P=ui.P;local w=a.w-self.lw
  local lines=r and r.id and self:lines(r,w-4)
    or (self.n.active+self.n.dismissed+self.n.cleared==0 and {{"No alerts",P.good},"","A new alert shows at the top right of every tab;","click it to come here."} or {})
  ui.pane(lines,self.lw+1,a.y,w,a.h)
end
function S:draw()
  if self.dirty then self:rebuild();self.list:refresh() end
  local a=ui.area();local n=self.n
  ui.title("Alerts",n.active.." active · "..n.dismissed.." dismissed · "..n.cleared.." cleared")
  ui.text(1,a.y,ui.fit(ui.fit("  Alert",24)..ui.fit("Subject",self.lw-60)..ui.fit("Raised",14).."State",self.lw),ui.P.dim)
  self:pane()
end
function S:refresh() self:rebuild();self.list:refresh();self:draw() end
function S:signal(name)
  if name~="alert" then return end
  self.dirty=true
  if ui.current()==self and not ui.inModal() then self:draw() end
end
function S:dismiss(r)
  if not (r and r.id) then return end
  if r.state~="active" then ui.notify("Only an active alert can be dismissed");return end
  local m=engine();local ok=m and ui.try(m.dismiss,r.id)
  if ok then ui.ok("Dismissed on every screen: "..(ui.alertKinds[r.kind] or r.kind).." · "..ui.alertSubject(r)) elseif ok==false then ui.notify("Already dismissed or cleared") end
end
function S:detail(i)
  local r=self.rows[i];if not (r and r.id) then return end
  local rows={}
  for _,l in ipairs(self:lines(r,64)) do rows[#rows+1]={text=type(l)=="table" and l[1] or l,fg=type(l)=="table" and l[2] or nil,locked=true} end
  if r.state=="active" then rows[#rows]=nil elseif rows[#rows].text~="" then rows[#rows+1]={text="",locked=true} end
  rows[#rows+1]={text="  Close",value=false}
  if r.state=="active" then rows[#rows+1]={text="  Dismiss on every screen",value=true,fg=ui.P.warn} end
  ui.pick((ui.alertKinds[r.kind] or r.kind).." · "..ui.alertSubject(r),rows,function(v) if v then self:dismiss(r) end end,{nofilter=true,w=70,note="Enter picks · ⌫ close"})
end

-- Settings: every key settings() returns, edited through set(), which
-- checks it; a refusal shows the engine's own error. The stock thresholds
-- belong to the stats service and also set the Stock tab's warnings.
local defs={heldMinutes={"Drone held alert after","min"},stuckFactor={"Machine stuck alert when overdue by","× duration"},
  fillBad={"Stock full alert when stock is","% full"},fullSoonHours={"Stock full alert when full within","h"},
  fillWarn={"Stock warning (not an alert) at","% full"}}
local order={"heldMinutes","stuckFactor","fillBad","fullSoonHours","fillWarn"}
local function show(k,v) local d=defs[k];local p=d and d[2]:sub(1,1)=="%";if type(v)~="number" then return tostring(v) end
  return string.format("%g",p and v*100 or v)..(d and (p and "" or " ")..d[2] or "") end
function S.settings()
  local m=engine();if not m then ui.fail("the alert engine is not available");return end
  local cfg=ui.try(m.settings);if not cfg then return end
  local okS,st=pcall(require,"stats");local fromStats=okS and ui.try(st.settings) or {}
  local list={};for _,k in ipairs(order) do if cfg[k]~=nil then list[#list+1]=k end end
  local extra={};for k in pairs(cfg) do if not defs[k] then extra[#extra+1]=k end end;table.sort(extra)
  for _,k in ipairs(extra) do list[#list+1]=k end
  local L
  ui.modal({title="Alert settings",w=92,h=#list+4,build=function(md)
    L=ui.list(md.menu,{name="s",x=md.ix,y=md.iy,w=md.iw,h=#list,bg=ui.P.box,count=function() return #list end,
      row=function(i) local k=list[i];local d=defs[k]
        return ui.fit(d and d[1] or k,md.iw-48)..ui.right(show(k,cfg[k]),16).."   "..ui.fit(fromStats[k]~=nil and "stock stats · "..k or "alerts · "..k,29) end,
      activate=function(i)
        local k=list[i];local d=defs[k];local p=d and d[2]:sub(1,1)=="%"
        local label=(d and d[1] or k)..(p and " (percent)" or d and " ("..d[2]..")" or "")
        ui.prompt(d and d[1] or k,label,string.format("%g",p and cfg[k]*100 or cfg[k]),function()
          cfg=ui.try(m.settings) or cfg;L:refresh();ui.ok("Saved: "..(d and d[1] or k).." "..show(k,cfg[k]))
        end,{number=true,check=function(v)
          local ok,err=pcall(m.set,k,p and v/100 or v)
          if ok then return true end;return nil,"Refused: "..(tostring(err):gsub("^[^:]+:%d+: ",""))
        end})
      end})
    md.paint=function() ui.text(md.ix,md.y+md.h-2,ui.fit("Enter edits · saved at once · ⌫ close",md.iw),ui.P.dim,ui.P.box) end
    md.key=function(_,code) if code==ui.keys.back then ui.close(md);return true end end
    L:refresh()
  end})
end
function S:key(_,code)
  local keys=ui.keys
  if code==keys.d then self:dismiss(self.rows[self.list.cur]);return true end
  if code==keys.s then S.settings();return true end
end
return S
