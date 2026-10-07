-- Setup: one tree of machine types, machines (with their faces), crafters
-- and storages. Enter on any row edits it; "+" rows start a picker flow.
local ui=require("mes_ui.core");local map=require("map");local wh=require("warehouse")
local F=require("mes_ui.flows")
local S={hints="Enter edit · + rows add · D remove",filterable=false}
local function mes() return require("mes") end

function S:open()
  local a=ui.area();self.rows={}
  self.list=ui.list(self.menu,{name="t",x=1,y=a.y,w=a.w,h=a.h,
    count=function() return #self.rows end,
    row=function(i) local r=self.rows[i];return r.text,r.fg,r.heading end,
    activate=function(i) self:activate(self.rows[i]) end})
  self:rebuild();self.list:refresh();self.list:first()
end
local function sorted(t) local k={};for n in pairs(t) do k[#k+1]=n end;table.sort(k);return k end
local function faceText(s)
  local e=map.storage(s);if not e then return "missing!" end
  return e.node.." "..ui.sideGlyph[e.side]
end
function S:rebuild()
  local rows,P=self.rows,ui.P;for k=#rows,1,-1 do rows[k]=nil end
  local function add(text,fg,kind,ref,extra) rows[#rows+1]={text=text,fg=fg,kind=kind,ref=ref,extra=extra,heading=kind=="heading"} end
  local types,crafters,groups,members=mes().types(),mes().crafters(),wh.groups(),wh.members()
  local byType={};for n,g in pairs(groups) do byType[g.type]=(byType[g.type] or 0)+1 end
  add("Machine types",P.accent,"heading")
  for _,t in ipairs(sorted(types)) do local d=types[t]
    local io="in→"..table.concat(d.inputs,",").."  out←"..d.output..(d.fuel and "  fuel→"..d.fuel.role or "")
    add("  "..ui.fit(t,14)..ui.fit(io,44).."×"..(byType[t] or 0).."  batch "..d.batch,nil,"type",t)
  end
  add("  + New machine type",P.good,"newType")
  add("",nil,"heading")
  add("Machines",P.accent,"heading")
  for _,n in ipairs(sorted(groups)) do local g=groups[n]
    if g.type~="crafter" then
      add("  "..ui.fit(n,14)..g.type..(types[g.type] and "" or "  (unknown type!)"),(not types[g.type]) and P.bad or nil,"machine",n)
      local order=types[g.type] and types[g.type].roles or sorted(g.roles)
      for _,role in ipairs(order) do local s=g.roles[role]
        add("    "..ui.fit(role,10)..ui.fit(s or "— unassigned",16)..(s and faceText(s) or ""),s and P.dim or P.bad,"role",n,role)
      end
    end
  end
  add("  + New machine",P.good,"newMachine")
  add("",nil,"heading")
  add("Crafters",P.accent,"heading")
  for _,n in ipairs(sorted(crafters)) do local c=crafters[n]
    add("  "..ui.fit(n,14).."robot "..c.robot:sub(1,8).."…  buffer "..c.buffer.."  "..faceText(c.buffer),nil,"crafter",n)
  end
  add("  + New crafter",P.good,"newCrafter")
  add("",nil,"heading")
  local used=F.roleOf();local names=map.storageNames();local stock=0
  for _ in pairs(members) do stock=stock+1 end
  add("Storages  "..#names.." named · "..stock.." in stock"..(self.showAll and "" or "   (Enter to list)"),P.accent,"storages")
  if self.showAll then
    for _,s in ipairs(names) do local m=members[s]
      local tag=used[s] or (m and ("stock"..(m.priority and " p"..m.priority or "")..(m.filter and " filter:"..ui.label(m.filter[1])..(#m.filter>1 and "+" or "") or ""))) or "—"
      add("  "..ui.fit(s,16)..ui.fit(faceText(s),16)..tag,used[s] and P.dim or nil,"storage",s)
    end
  end
  add("  + Add storage",P.good,"newStorage")
end
function S:draw()
  local g=0;for n,x in pairs(wh.groups()) do if x.type~="crafter" then g=g+1 end end
  ui.title("Setup","nodes "..#map.names().." · storages "..#map.storageNames().." · machines "..g)
end
function S:refresh() self:rebuild();self.list:refresh();self:draw() end
function S:signal(name,what) if name=="warehouse" or (name=="mes" and what=="changed") then self:refresh() end end

function S:activate(r)
  if not r then return end
  local k=r.kind
  if k=="newType" then F.editType(nil,nil,function() self:refresh() end)
  elseif k=="type" then F.editType(r.ref,mes().types()[r.ref],function() self:refresh() end)
  elseif k=="newMachine" then F.newMachine()
  elseif k=="machine" then
    local g=wh.groups()[r.ref];local def=mes().types()[g.type]
    ui.pick(r.ref,{{text="Reassign all faces…",value="faces"},{text="Remove machine",value="remove",fg=ui.P.bad}},function(v)
      if v=="faces" and def then F.assignRoles(r.ref,g.type,def,{},1)
      elseif v=="remove" then ui.confirm("Remove "..r.ref,"Remove machine "..r.ref.."? Its storages stay named.",function() ui.try(wh.ungroup,r.ref);ui.ok("Removed "..r.ref) end) end
    end,{nofilter=true})
  elseif k=="role" then
    local g=wh.groups()[r.ref]
    F.pickStorage(r.ref.." · "..r.extra,{free=true,add=r.ref.."."..r.extra},function(s)
      g.roles[r.extra]=s;if ui.try(wh.group,r.ref,g.type,g.roles) then ui.ok(r.ref.." "..r.extra.." → "..s) end
    end)
  elseif k=="newCrafter" then F.newCrafter()
  elseif k=="crafter" then
    local c=mes().crafters()[r.ref]
    ui.pick(r.ref,{{text="Change buffer chest…",value="buf"},{text="Remove crafter",value="remove",fg=ui.P.bad}},function(v)
      if v=="buf" then F.pickStorage(r.ref.." · buffer",{free=true,add=r.ref..".buf"},function(s) c.buffer=s;if ui.try(mes().setCrafter,r.ref,c) then ui.ok(r.ref.." buffer → "..s) end end)
      elseif v=="remove" then ui.confirm("Remove "..r.ref,"Remove crafter "..r.ref.."?",function() ui.try(mes().removeCrafter,r.ref) end) end
    end,{nofilter=true})
  elseif k=="storages" then self.showAll=not self.showAll;self:refresh()
  elseif k=="newStorage" then F.addStorage(nil,function() self:refresh() end)
  elseif k=="storage" then
    local used=F.roleOf()[r.ref]
    local rows={{text="Stock settings…",value="stock"},{text="Read it now (drone)",value="scan"},{text="Remove name",value="remove",fg=ui.P.bad}}
    ui.pick(r.ref..(used and " ("..used..")" or ""),rows,function(v)
      if v=="stock" then F.membership(r.ref)
      elseif v=="scan" then local ids=ui.try(wh.scan,r.ref);if ids then ui.ok("Reading "..r.ref.." (job #"..tostring(ids[1])..")") end
      elseif v=="remove" then
        if used then ui.fail(r.ref.." is "..used.."; reassign that first");return end
        ui.confirm("Remove "..r.ref,"Remove storage name "..r.ref.."?",function() wh.remove(r.ref);map.unname(r.ref);map.save();self:refresh();ui.ok("Removed "..r.ref) end)
      end
    end,{nofilter=true})
  end
end
function S:key(char,code)
  if char==68 or char==100 then -- D/d removes the selected thing
    local r=self.rows[self.list.cur]
    if r and (r.kind=="machine" or r.kind=="crafter" or r.kind=="storage" or r.kind=="type") then
      if r.kind=="type" then
        for _,g in pairs(wh.groups(r.ref)) do ui.fail("machines still use type "..r.ref);return true end
        ui.confirm("Remove type","Remove machine type "..r.ref.."?",function() ui.try(mes().removeType,r.ref) end)
      else self:activate(r) end
      return true
    end
  end
end
return S
