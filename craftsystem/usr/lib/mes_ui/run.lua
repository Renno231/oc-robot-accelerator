-- Run view: each stage's live state, the drones, and where things are if it
-- fails. Reads mes.status only when a mes event for this run arrives.
local ui=require("mes_ui.core")
local S={hints="⌫ back (the run continues)"}
local function mes() return require("mes") end
local look={waiting={"◌","dim"},fetching={"⇣","accent"},crafting={"⚙","accent"},processing={"♨","warn"},storing={"⇡","accent"},done={"✓","good"},failed={"✗","bad"}}

function S:open(arg)
  self.id=arg.id;self.rows={};local a=ui.area()
  self.list=ui.list(self.menu,{name="r",x=1,y=a.y,w=a.w,h=a.h,
    count=function() return #self.rows end,
    row=function(i) local r=self.rows[i];return r[1],r[2],true end})
  self:refresh()
end
function S:rebuild()
  local st=mes().status(self.id);self.st=st;local rows,P=self.rows,ui.P
  for k=#rows,1,-1 do rows[k]=nil end
  if not st then rows[1]={"run #"..self.id.." is gone (rebooted?)",P.bad};return end
  local w=ui.area().w;local barW=math.max(6,math.min(24,w-60))
  for i,s in ipairs(st.stages) do
    local l=look[s.state] or {"·","fg"}
    local who=s.kind=="robot" and ("Robot "..(s.crafter or "")) or ("Machines "..(type(s.groups)=="table" and table.concat(s.groups,", ") or tostring(s.groups or "")))
    local active=i==st.stage and st.status=="running"
    rows[#rows+1]={(active and "▸ " or "  ")..l[1].." "..ui.fit(i..". "..who,28)..ui.fit(s.state,11)..ui.bar(s.done or 0,s.total or 0,barW).." "..(s.done or 0).."/"..(s.total or 0),P[l[2]]}
    if s.detail and s.detail~="" then rows[#rows+1]={"       "..s.detail,P.dim} end
  end
  rows[#rows+1]={"",P.fg}
  if st.status=="running" then
    for _,d in ipairs(require("logistics").drones()) do rows[#rows+1]={"  drone "..ui.fit(d.name,6)..ui.fit(d.state,10).."at "..tostring(d.node),P.dim} end
  else
    local fin=st.finished and st.started and string.format(" in %ds",math.floor(st.finished-st.started)) or ""
    rows[#rows+1]={st.status=="complete" and ("✓ Complete"..fin) or ("✗ "..st.status..fin),P[st.status=="complete" and "good" or "bad"]}
    if st.reason then rows[#rows+1]={"  "..st.reason,P.bad} end
    if st.where and #st.where>0 then
      rows[#rows+1]={"  Items left outside stock:",P.warn}
      for _,x in ipairs(st.where) do rows[#rows+1]={"    "..ui.fit(ui.label(x.item),24)..ui.right(ui.num(x.count),6).."  in "..x.storage,P.warn} end
    end
  end
end
function S:draw()
  local st=self.st
  ui.title(st and ("Run #"..self.id.." · "..ui.label(st.item or "?").." ×"..tostring(st.qty or "")) or "Run",st and st.status or "")
end
function S:refresh() self:rebuild();self.list:refresh();self:draw() end
function S:signal(name,what,id)
  if name=="mes" and id==self.id then self:refresh()
  elseif name=="logistics" and self.st and self.st.status=="running" then self:refresh() end
end
return S
