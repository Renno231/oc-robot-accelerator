-- Manage: the crafting system's own plan, kit, tool and stockkeeper screens
-- (craft_management_ui), run full screen while this UI is suspended.
local ui=require("mes_ui.core")
local S={hints="Enter opens · R refresh · H help",
  help={{"Enter","open the selected manager; Q or Back in it returns here"}}}
local entries={
  {kind="plans",title="Plans",dir="/usr/craftplans/",what="saved craft plans: create, explain, edit choices, run, copy, delete"},
  {kind="kits",title="Kits",dir="/usr/craftkits/",what="craft kits: several plans run together, live or pinned"},
  {kind="tools",title="Tools",what="tool profiles: durability and wear of reusable crafting tools"},
  {kind="stockkeeper",title="Stockkeeper",dir="/usr/stockkeeper/",what="stock rules: rerun a plan or kit when an item runs low"}}
-- Modules the managers keep state in (stockkeeper's rule timers) stay loaded;
-- everything else they load is released again on return.
local keep={stockkeeper=true}

local function saved(dir)
  if not dir then return "" end
  local fs=require("filesystem");if not fs.exists(dir) then return "none saved" end
  local n=0;for _ in fs.list(dir) do n=n+1 end;return n.." saved"
end
function S:open()
  local a=ui.area();self.rows={}
  self.list=ui.list(self.menu,{name="m",x=1,y=a.y+1,w=a.w,h=#entries,
    count=function() return #self.rows end,
    row=function(i) local r=self.rows[i];return r.text end,
    activate=function(i) self:launch(entries[i]) end})
  self:refresh()
end
function S:refresh()
  for i,e in ipairs(entries) do self.rows[i]={text="  "..ui.fit(e.title,14)..ui.fit(saved(e.dir),12)..e.what} end
  self.list:refresh();self:draw()
end
function S:draw()
  ui.title("Manage","the crafting system's management screens")
  local a=ui.area()
  ui.text(3,a.y+#entries+2,"These open the crafting system's own screens full size; leaving one (Q or Back) returns here.",ui.P.dim)
end
function S:launch(e)
  local before={};for k in pairs(package.loaded) do before[k]=true end
  local code,err=ui.suspend(function() return require("craft_management_ui").show(e.kind,{}) end)
  for k in pairs(package.loaded) do if not before[k] and not keep[k] then package.loaded[k]=nil end end
  if code==0 then ui.ok("Back from "..e.title) else ui.fail(e.title..": "..tostring(err or code)) end
  self:refresh()
end
return S
