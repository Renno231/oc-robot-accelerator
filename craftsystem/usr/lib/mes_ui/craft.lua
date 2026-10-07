-- Craft: runs at the top, then craftable items matching the filter.
local ui=require("mes_ui.core");local wh=require("warehouse")
local S={filterable=true,hints="type to search · Enter craft or open run"}
local function mes() return require("mes") end
local glyph={running="▶",complete="✓",failed="✗",unknown="?"}
local colour={running="accent",complete="good",failed="bad",unknown="warn"}

function S:open()
  local a=ui.area();self.rows={}
  self.list=ui.list(self.menu,{name="c",x=1,y=a.y,w=a.w,h=a.h,
    count=function() return #self.rows end,
    row=function(i,w) local r=self.rows[i];return r.text,r.fg,r.heading end,
    activate=function(i) self:activate(self.rows[i]) end})
  self:rebuild();self.list:refresh()
  for i,r in ipairs(self.rows) do if not r.heading then self.list:set(i);break end end
end
function S:rebuild()
  local rows,P=self.rows,ui.P;for k=#rows,1,-1 do rows[k]=nil end
  local a=ui.area()
  local runs=mes().runs()
  if #runs>0 then
    rows[1]={text="Runs",fg=P.accent,heading=true}
    for k=1,math.min(#runs,4) do local r=runs[k]
      rows[#rows+1]={text="  "..glyph[r.status].." #"..r.id.."  "..ui.fit(ui.label(r.item).." ×"..r.qty,30)..r.status..(r.status=="running" and " · stage "..r.stage.."/"..r.stages or ""),fg=P[colour[r.status]],run=r.id}
    end
    rows[#rows+1]={text="",heading=true}
  end
  rows[#rows+1]={text=ui.filterText=="" and "Craftable  (type to search)" or ("Craftable matching \""..ui.filterText.."\""),fg=P.accent,heading=true}
  local room=math.max(a.h*2,24)
  local found=ui.try(mes().search,ui.filterText,room) or {}
  for _,id in ipairs(found) do
    local have=wh.count(ui.item(id))
    rows[#rows+1]={text="  "..ui.fit(ui.label(id),32)..ui.right(have>0 and ui.num(have).." in stock" or "",14),item=id}
  end
  if #found==0 then rows[#rows+1]={text="  nothing craftable matches",fg=P.dim,heading=true} end
  self.found=#found
end
function S:draw() ui.title("Craft","pick an item, preview its plan, run it") end
function S:filtered()
  self:rebuild();local first
  for i,r in ipairs(self.rows) do if r.item then first=i;break end end
  self.list:set(first or 1)
end
function S:signal(name,what)
  if name=="mes" and (what=="done" or what=="stage") then
    self:rebuild();self.list:refresh()
  end
end
function S:activate(r)
  if not r then return end
  if r.run then ui.push("mes_ui.run",{id=r.run});return end
  if not r.item then return end
  ui.prompt("Craft "..ui.label(r.item),"How many?",1,function(n)
    ui.busy("Planning "..n.." "..ui.label(r.item).."…")
    local plan=ui.try(mes().plan,r.item,n)
    if plan then ui.push("mes_ui.plan",{plan=plan}) end
  end,{integer=true,min=1})
end
return S
