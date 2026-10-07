-- Jobs: logistics jobs newest first, read one window at a time.
local ui=require("mes_ui.core");local lg=require("logistics")
local S={hints="Enter details · ↑↓ PgUp PgDn"}
local colour={done="good",partial="warn",failed="bad",running="accent",queued="dim",cancelled="dim"}

local function where(e) if type(e)~="table" then return e and tostring(e) or "" end;return e.storage or e.node or "?" end
function S:open()
  local a=ui.area();self.total=0;self.window={};self.wtop=1
  self.lw=ui.wide() and math.floor(a.w*0.6) or a.w
  self.list=ui.list(self.menu,{name="j",x=1,y=a.y+1,w=self.lw,h=a.h-1,
    count=function() return self.total end,
    prepare=function(top,h) self:fetch(top,h) end,
    row=function(i,w) return self:row(i,w) end,
    activate=function(i) self:details(i) end,
    moved=function(i) if ui.wide() then self:details(i,true) end end})
  local _,total=lg.jobs(true,1,0);self.total=total or 0
  self.list:refresh()
end
function S:fetch(top,h)
  if self.wtop==top and self.fresh then return end
  local w,total=lg.jobs(true,top,h);self.window,self.wtop,self.fresh=w,top,true;self.total=total or #w
end
function S:job(i) return self.window[i-self.wtop+1] end
function S:row(i,w)
  local j=self:job(i);if not j then return "" end
  local what=j.item and (ui.label(j.item).." "..(j.moved or 0).."/"..(j.requested or 0)) or "action"
  local route=where(j.from).." → "..where(j.to)
  local t=ui.right("#"..j.id,5).." "..ui.fit(j.state,8)..ui.fit(what,math.max(10,w-40))..route
  return t,ui.P[colour[j.state] or "fg"]
end
function S:draw()
  ui.title("Jobs",ui.num(self.total).." logistics jobs")
  local a=ui.area();ui.text(1,a.y,ui.fit("   Id State   Item",self.lw),ui.P.dim)
  if ui.wide() then self:details(self.list.cur,true) end
end
function S:details(i,pane)
  local j=self:job(i);if not j then return end
  local s=lg.status(j.id);if not s then return end
  local lines={{"Job #"..j.id.."  "..s.state,ui.P[colour[s.state] or "fg"]}}
  if s.item then lines[#lines+1]=ui.label(s.item).."  "..(s.moved or 0).." of "..(s.requested or 0) end
  lines[#lines+1]="from "..where(s.from).."  to "..where(s.to)
  if s.trips then lines[#lines+1]="trips "..s.trips end
  if s.reason then lines[#lines+1]={s.reason,ui.P.bad} end
  if s.short then lines[#lines+1]={"short: found "..tostring(s.found),ui.P.warn} end
  if (s.refused or 0)>0 then lines[#lines+1]={"refused "..s.refused,ui.P.warn} end
  for k,st in ipairs(s.steps or {}) do
    local kind=st.read and "read" or st.take and "take" or st.put and "put" or st.go and "go" or "step"
    local n=st.taken or st.moved or (st.listing and "listing") or ""
    lines[#lines+1]={k..". "..kind.." "..where(st.read or st.take or st.put or st.go).." "..tostring(n),ui.P.dim}
  end
  if pane then local a=ui.area();ui.pane(lines,self.lw+1,a.y,a.w-self.lw,a.h)
  else
    local rows={};for _,l in ipairs(lines) do rows[#rows+1]={text=type(l)=="table" and l[1] or l,fg=type(l)=="table" and l[2] or nil,locked=true} end
    ui.pick("Job #"..j.id,rows,function() end,{nofilter=true,note="⌫ close"})
  end
end
function S:signal(name)
  if name=="logistics" or name=="logistics_work" then self.fresh=false;self.list:refresh();ui.title("Jobs",ui.num(self.total).." logistics jobs") end
end
return S
