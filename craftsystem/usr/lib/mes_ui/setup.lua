-- Setup: one tree of machine types, machines (with their faces), crafters,
-- stations and storages. Enter on any row edits it; "+" rows start a flow.
local ui=require("mes_ui.core");local map=require("map");local wh=require("warehouse")
local F=require("mes_ui.flows")
local S={hints="Enter edit · + rows add · D remove · R refresh · H help",filterable=false,
  help={{"Enter","edit the selected row; on a + row, add one"},{"D","remove the selected machine, crafter, station, storage or type"}}}
local function mes() return require("mes") end
local ok,st=pcall(require,"stations");if not ok then st=nil end
local function iochest() local k,m=pcall(require,"iochest");return k and m or nil end
local ioFg={active="accent",partial="warn",idle="good"}
-- An IO record's state as its io signal names it.
local function ioState(r) return next(r.pending or {}) and "active" or r.reason and "partial" or "idle" end
-- listing/balance entries {item,count}, biggest first.
local function ioItems(r)
  local out={};for _,e in pairs(r.listing or {}) do if e.count>0 then out[#out+1]=e end end
  table.sort(out,function(a,b) return a.count>b.count end);return out
end
local function ioSummary(r,w)
  local items=ioItems(r);if #items==0 then return "empty" end
  local n,parts=0,{};for _,e in ipairs(items) do n=n+math.ceil(e.count/(wh.stackSize(e.item) or 64));parts[#parts+1]=ui.label(e.item).." "..ui.num(e.count) end
  return ui.fit(n.." stack"..(n==1 and "" or "s")..": "..table.concat(parts,", "),w)
end
local phaseText={link="linking",row="testing row",read="reading"}
local stateFg={checking="accent",removing="accent",ready="good",failed="bad"}
local counts={} -- row sizes by station name: list() has no count
local function wrap(s,w)
  local out,line={},"";for word in tostring(s):gmatch("%S+") do
    if line~="" and #line+1+#word>w then out[#out+1]=line;line=word else line=line=="" and word or line.." "..word end
  end
  if line~="" then out[#out+1]=line end;return out
end

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
  local list=st and st.list() or {};self.stations={};local n={}
  for _,x in ipairs(list) do self.stations[x.name]=x;n[x.state]=(n[x.state] or 0)+1 end
  add("Stations  "..(st and #list..((n.checking or 0)>0 and " · "..n.checking.." checking" or "")..((n.failed or 0)>0 and " · "..n.failed.." failed" or "") or "(stations library not loaded)"),P.accent,"heading")
  for _,x in ipairs(list) do
    if x.kind=="row" and not counts[x.name] then local r=st.get(x.name);counts[x.name]=r and r.spec.count or "?" end
    local busy=x.state=="removing" and "moving items" or x.state=="checking" and phaseText[x.phase] or ""
    add("  "..ui.fit(x.name,16)..ui.fit(x.kind=="row" and "row ×"..counts[x.name] or x.kind,10)..ui.fit(x.state,10)..busy,P[stateFg[x.state] or "fg"],"station",x.name)
    if x.state=="failed" and x.reason then for _,l in ipairs(wrap(x.reason,ui.size()-12)) do add("      "..l,P.dim,"station",x.name) end end
    if x.note then add("      note: "..x.note,P.warn,"station",x.name) end
  end
  if st then add("  + Add storage…",P.good,"newStation","storage");add("  + Add row…",P.good,"newStation","row") end
  add("",nil,"heading")
  local io=iochest();local ios=io and ui.try(io.list) or {};self.io={}
  local nio={active=0,partial=0}
  for _,r in ipairs(ios) do self.io[r.name]=r;local k=ioState(r);nio[k]=(nio[k] or 0)+1 end
  add("IO  "..(io and #ios.." chests"..(nio.active>0 and " · "..nio.active.." active" or "")..(nio.partial>0 and " · "..nio.partial.." partial" or "") or "(iochest library not loaded)"),P.accent,"heading")
  for _,r in ipairs(ios) do local k=ioState(r)
    add("  "..ui.fit(r.name,16)..ui.fit(r.role=="import" and "In" or "Out",5)..ui.fit(r.sensor or "no sensor",14)..ui.fit(k,9)..ioSummary(r,ui.size()-48),P[ioFg[k]],"io",r.name)
    if r.reason then for _,l in ipairs(wrap(r.reason,ui.size()-12)) do add("      "..l,P.warn,"io",r.name) end end
  end
  if io and #ios==0 then add("  none: add a storage or row with role import or export",P.dim,"heading") end
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
  add("  + Name a mapped storage…",P.good,"newStorage")
end
function S:draw()
  local g=0;for n,x in pairs(wh.groups()) do if x.type~="crafter" then g=g+1 end end
  ui.title("Setup","nodes "..#map.names().." · storages "..#map.storageNames().." · machines "..g)
end
function S:refresh() self:rebuild();self.list:refresh();self:draw() end
-- io signals re-read the IO rows; phase changes push no station signal: while a station is busy, its
-- logistics jobs finishing re-read the list.
function S:signal(name,what)
  local busy=false;for _,x in pairs(self.stations or {}) do if x.state=="checking" or x.state=="removing" then busy=true end end
  if name=="warehouse" or name=="station" or name=="io" or (name=="mes" and what=="changed") or (name=="logistics" and busy) then self:refresh() end
end

-- Remove; a station holding items asks whether to move or forget them.
local function remove(name,items)
  local done,err=st.remove(name,items and {items=items})
  if done then if items=="move" then ui.ok(name..": moving its items to stock, then removing") end;ui.current():refresh();return end
  local k=tostring(err):match("^holds (%d+) items")
  if not k or items then ui.fail(err);return end
  ui.pick("Remove "..name,{{text="Move the "..k.." items to other stock, or forget them?",locked=true},
    {text="  Move",value="move"},{text="  Forget",value="forget",fg=ui.P.warn},{text="  Cancel",value=false}},function(v) if v then remove(name,v) end end,{nofilter=true})
end
local function askRemove(name) ui.confirm("Remove "..name,"Remove station "..name.."? Its names and the nodes and links it made go.",function() remove(name) end) end
local function details(name)
  local r=st.get(name);if not r then ui.fail(name.." is gone");return end
  local P,sp=ui.P,r.spec;local pair=sp.pair or 1
  local lines={{name.."  "..r.state..(r.phase and r.state~="ready" and " · "..(phaseText[r.phase] or r.phase) or ""),P[stateFg[r.state] or "fg"]},
    r.kind=="row" and ("row ×"..sp.count.."  face "..sp.face.." · runs "..sp.rowDir.." · spacing "..sp.spacing.." · pair "..pair.." · "..sp.role) or ("storage  face "..sp.face.." · "..sp.role),"",{"Members",P.accent}}
  for i,m in ipairs(r.members) do
    local inv=r.members[(i-1)//pair*pair+1].storage;local size=r.sizes[inv]
    lines[#lines+1]="  "..ui.fit(m.storage,16)..ui.fit("("..m.x..","..m.y..","..m.z..")",16).."hover "..ui.fit(m.node.." "..ui.sideGlyph[m.side],18)
      ..(inv~=m.storage and "shares "..inv or size and size.." slots" or "not read")
  end
  lines[#lines+1]={"Created",P.accent}
  local links={};for _,l in ipairs(r.created.links) do links[#links+1]=l[1].."–"..l[2] end
  for _,v in ipairs({{"nodes",r.created.nodes},{"links",links}}) do
    for k,l in ipairs(wrap(#v[2]>0 and table.concat(v[2],", ") or "none",100)) do lines[#lines+1]="  "..ui.fit(k==1 and v[1] or "",7)..l end
  end
  if r.reason then lines[#lines+1]={"Reason",P.accent};for _,l in ipairs(wrap(r.reason,100)) do lines[#lines+1]={"  "..l,P.bad} end end
  if r.note then lines[#lines+1]={"Note",P.accent};lines[#lines+1]={"  "..r.note,P.warn} end
  ui.show("Station · "..name,lines)
end
function S:station(name)
  local x=self.stations[name];if not x then return end
  local rows={}
  if x.state=="failed" then rows[#rows+1]={text="Retry (after fixing the spot)",value="retry"} end
  if x.state=="failed" or x.state=="ready" then rows[#rows+1]={text="Remove station",value="remove",fg=ui.P.bad} end
  rows[#rows+1]={text="Details",value="details"}
  ui.pick(name.." · "..x.state,rows,function(v)
    if v=="retry" then if ui.try(st.retry,name) then ui.ok(name..": checking again");self:refresh() end
    elseif v=="remove" then askRemove(name)
    else details(name) end
  end,{nofilter=true})
end

-- IO chest actions: In imports now; Out without a sensor is marked emptied;
-- any without a sensor gets one attached.
local function ioDetails(r)
  local P=ui.P;local k=ioState(r)
  local lines={{r.name.."  "..(r.role=="import" and "In" or "Out").." · "..(r.sensor or "no sensor").." · "..k,P[ioFg[k]]}}
  if r.reason then for _,l in ipairs(wrap(r.reason,100)) do lines[#lines+1]={"  "..l,P.warn} end end
  lines[#lines+1]={"Contents",P.accent}
  local items=ioItems(r);for _,e in ipairs(items) do lines[#lines+1]="  "..ui.fit(ui.label(e.item),32)..ui.right(ui.num(e.count),8) end
  if #items==0 then lines[#lines+1]={"  empty",P.dim} end
  local jobs={};for id in pairs(r.pending or {}) do jobs[#jobs+1]="#"..tostring(id) end;table.sort(jobs)
  lines[#lines+1]={"Jobs",P.accent};lines[#lines+1]={"  "..(#jobs>0 and table.concat(jobs,", ") or "none"),#jobs>0 and P.fg or P.dim}
  ui.show("IO · "..r.name,lines)
end
function S:attach(r)
  local io=iochest();local lg=require("logistics")
  local function go(sensor)
    ui.busy("Attaching "..sensor.." to "..r.name.."…")
    local ok,res,err=pcall(io.attach,sensor,r.name)
    if not ok then ui.fail((tostring(res):gsub("^[^:]+:%d+: ","")))
    elseif res then ui.ok(sensor.." attached to "..r.name) else ui.fail(tostring(err)) end
    self:refresh()
  end
  -- Registered sensors: logistics names them only if it has sensors().
  if not lg.sensors then
    ui.prompt("Attach sensor · "..r.name,"Registered sensor name (Fleet registers new ones)","",go)
    return
  end
  local used={};for _,x in pairs(self.io) do if x.sensor then used[x.sensor]=x.name end end
  local rows={}
  for _,n in ipairs(lg.sensors()) do if not used[n] then rows[#rows+1]={text=n,value=n} end end
  for _,n in ipairs(lg.sensors()) do if used[n] then rows[#rows+1]={text=ui.fit(n,16).."on "..used[n],locked=true} end end
  if #rows==0 then ui.fail("no registered sensors: register one on Fleet");return end
  ui.pick("Attach sensor · "..r.name,rows,go)
end
function S:ioRow(name)
  local r=self.io[name];if not r then return end;local io=iochest()
  local rows={}
  if r.role=="import" then rows[#rows+1]={text="Import now",value="import"} end
  if r.role=="export" and not r.sensor then rows[#rows+1]={text="Mark emptied (I took everything out)",value="emptied"} end
  if not r.sensor then rows[#rows+1]={text="Attach sensor…",value="attach"} end
  rows[#rows+1]={text="Details",value="details"}
  ui.pick(name.." · "..(r.role=="import" and "In" or "Out")..(r.sensor and " · "..r.sensor or ""),rows,function(v)
    if v=="import" then
      -- With a sensor it asks the sensor; without, a drone reads the chest once.
      local ok,res=pcall(io.importNow,name)
      if not ok then ui.fail((tostring(res):gsub("^[^:]+:%d+: ","")))
      else ui.ok(name..": importing"..(type(res)=="number" and " (read job #"..res..")" or "")) end
      self:refresh()
    elseif v=="emptied" then if ui.try(io.markEmptied,name) then ui.ok(name.." marked empty") end;self:refresh()
    elseif v=="attach" then self:attach(r)
    else ioDetails(r) end
  end,{nofilter=true})
end

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
  elseif k=="station" then self:station(r.ref)
  elseif k=="io" then self:ioRow(r.ref)
  elseif k=="newStation" then F.addStation(r.ref,function() self:refresh() end)
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
  if code==ui.keys.d then -- D removes the selected thing
    local r=self.rows[self.list.cur]
    if r and (r.kind=="machine" or r.kind=="crafter" or r.kind=="storage" or r.kind=="type" or r.kind=="station") then
      if r.kind=="station" then
        local x=self.stations[r.ref]
        if x.state=="ready" or x.state=="failed" then askRemove(r.ref)
        else ui.fail(r.ref.." is "..x.state) end
      elseif r.kind=="type" then
        for _,g in pairs(wh.groups(r.ref)) do ui.fail("machines still use type "..r.ref);return true end
        ui.confirm("Remove type","Remove machine type "..r.ref.."?",function() ui.try(mes().removeType,r.ref) end)
      else self:activate(r) end
      return true
    end
  end
end
return S
