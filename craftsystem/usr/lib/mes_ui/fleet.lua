-- Fleet: announcing hardware, drones, crafters and machines in one list.
-- Reads logistics, map and mes on open, R and their change signals only.
local ui=require("mes_ui.core");local lg=require("logistics");local map=require("map")
local S={hints="Enter register · release · found · details · R refresh · H help",
  help={{"Enter","new hardware: register · held drone: release cargo"},{"","lost drone: mark found · other rows: details"}}}
local function mes() return require("mes") end
local stateColour={idle="good",working="accent",held="warn",charging="dim",booting="dim"}
local FULL=5000

function S:open()
  local a=ui.area();self.rows={}
  self.list=ui.list(self.menu,{name="f",x=1,y=a.y,w=a.w,h=a.h,
    count=function() return #self.rows end,
    row=function(i) local r=self.rows[i];return r.text,r.fg,r.heading end,
    activate=function(i) self:activate(self.rows[i]) end})
  self:rebuild();self.list:refresh();self.list:first()
end
local function sorted(t) local k={};for n in pairs(t or {}) do k[#k+1]=n end;table.sort(k);return k end
-- Cargo is a slot listing {name,damage,label,size}; held is {item,count}.
local function stacks(d)
  local out={};for _,e in pairs(d.cargo or d.held or {}) do
    if e.item then out[#out+1]={item=e.item,count=e.count or 0} else out[#out+1]={item=e,count=e.size or 0} end
  end
  return out
end
local function cargoText(d)
  local s=stacks(d);if #s==0 then return "empty" end
  local order,sum={},{}
  for _,e in ipairs(s) do local k=ui.id(e.item);if not sum[k] then order[#order+1]=e.item;sum[k]=0 end;sum[k]=sum[k]+e.count end
  local parts={};for _,i in ipairs(order) do parts[#parts+1]=ui.label(i).." ×"..sum[ui.id(i)] end
  return #s.." stack"..(#s==1 and "" or "s")..": "..table.concat(parts,", ")
end
local function energy(d) return d.energy and (math.floor(d.energy/FULL*100+0.5).."%") or "—" end
local function nextName(drones)
  local used={};for _,d in ipairs(drones) do used[d.name]=true end
  local n=1;while used["drone"..n] do n=n+1 end;return "drone"..n
end
function S:rebuild()
  local rows,P=self.rows,ui.P;for k=#rows,1,-1 do rows[k]=nil end
  local function add(text,fg,kind,ref) rows[#rows+1]={text=text,fg=fg,kind=kind,ref=ref,heading=kind=="heading"} end
  local pending,drones=lg.pending(),lg.drones();self.pending,self.drones=pending,drones
  ui.badge("fleet",#pending)
  local res=ui.try(function() return mes().resources() end) or {crafters={},machines={}};self.res=res
  if #pending>0 then
    add("New hardware  "..#pending.." waiting",P.warn,"heading")
    for _,a in ipairs(pending) do add("  drone · "..a:sub(1,8).."… · on a charger · Register",P.good,"new",a) end
    add("",nil,"heading")
  end
  local n={idle=0,working=0,held=0,lost=0}
  for _,d in ipairs(drones) do local k=d.lost and "lost" or d.state;if n[k] then n[k]=n[k]+1 end end
  add("Drones  "..#drones.." · "..n.idle.." idle · "..n.working.." working · "..n.held.." held · "..n.lost.." lost",P.accent,"heading")
  for _,d in ipairs(drones) do
    local place=d.node or (d.home and "home "..d.home) or "?"
    local t="  "..ui.fit(d.name,12)..ui.fit(d.lost and "LOST" or d.state or "?",10)..ui.fit(place,18)..ui.right(energy(d),5).."  "
      ..ui.fit(cargoText(d),56)..(d.job and "job #"..d.job or "")..(d.releasePending and "  releasing…" or "")
    add(t,d.lost and P.bad or P[stateColour[d.state] or "fg"],"drone",d.name)
  end
  if #drones==0 then add("  no drones registered",P.dim,"heading") end
  add("",nil,"heading")
  local cn=sorted(res.crafters)
  add("Crafters  "..#cn,P.accent,"heading")
  for _,name in ipairs(cn) do local c=res.crafters[name]
    local busy=c.run and ("run "..tostring(c.run)..(c.step and " step "..tostring(c.step) or "")) or ""
    add("  "..ui.fit(name,14)..ui.fit(c.state or "?",12)..ui.fit(busy,22).."buffer "..tostring(c.buffer),
      c.state=="idle" and P.good or c.state=="unknown" and P.dim or P.accent,"crafter",name)
  end
  add("",nil,"heading")
  local mn=sorted(res.machines)
  add("Machines  "..#mn,P.accent,"heading")
  for _,name in ipairs(mn) do local m=res.machines[name];local k=#(m.loads or {})
    add("  "..ui.fit(name,14)..ui.fit(m.type or "?",12)..ui.fit(m.state or "?",10)..k.." load"..(k==1 and "" or "s"),
      m.state=="idle" and P.good or P.accent,"machine",name)
  end
end
function S:draw()
  local ch=0;for _,e in pairs(map.nodes()) do if e.charger then ch=ch+1 end end
  ui.title("Fleet",#(self.drones or {}).." drones · "..ch.." chargers"..(#(self.pending or {})>0 and " · "..#self.pending.." new" or ""))
end
function S:refresh() self:rebuild();self.list:refresh();self:draw() end
function S:signal(name) if name=="logistics" or name=="mes" then self:refresh() end end

-- Locked rows in a closable box.
local function show(title,lines)
  local rows={};for _,l in ipairs(lines) do rows[#rows+1]={text=type(l)=="table" and l[1] or l,fg=type(l)=="table" and l[2] or nil,locked=true} end
  ui.pick(title,rows,function() end,{nofilter=true,note="⌫ close"})
end
local function value(v)
  if type(v)~="table" then return tostring(v) end
  local parts={};for _,k in ipairs(sorted(v)) do parts[#parts+1]=tostring(k).."="..value(v[k]) end
  return "{"..table.concat(parts,", ").."}"
end
local function fields(t,skip)
  local lines={};for _,k in ipairs(sorted(t)) do if not (skip and skip[k]) then lines[#lines+1]=ui.fit(k,14)..value(t[k]) end end
  return lines
end

function S:register(address)
  local drones=self.drones
  ui.prompt("Register drone","Name for drone "..address:sub(1,8).."…",nextName(drones),function(name)
    local homes={};for _,d in ipairs(drones) do if d.home then homes[d.home]=homes[d.home] and homes[d.home]..", "..d.name or d.name end end
    -- Free chargers first, so the pick starts on the first free one.
    local free,used={},{}
    for _,n in ipairs(map.names()) do local e=map.node(n)
      if e.charger then local t=homes[n] and used or free
        t[#t+1]={text=ui.fit(n,16).."("..e.x..", "..e.y..", "..e.z..")"..(homes[n] and "  home of "..homes[n] or "  free"),value=n,fg=homes[n] and ui.P.dim or nil}
      end
    end
    for _,r in ipairs(used) do free[#free+1]=r end
    if #free==0 then ui.fail("no charger nodes mapped");return end
    ui.pick("Register "..name.." · home charger",free,function(home)
      ui.confirm("Register drone","Register "..address:sub(1,8).."… as "..name.." at "..home.."?",function()
        if ui.try(lg.register,address,name,home) then ui.ok("Registered "..name.." at "..home) end
        self:refresh()
      end)
    end)
  end,{check=function(v)
    if not v:match("^[%w_-]+$") then return nil,"letters, digits, _ and - only" end
    if #v>48 then return nil,"48 characters at most" end
    for _,d in ipairs(drones) do if d.name==v then return nil,"name already used" end end
    return true
  end})
end
function S:activate(r)
  if not r then return end
  local k,P=r.kind,ui.P
  if k=="new" then self:register(r.ref)
  elseif k=="drone" then
    local d;for _,x in ipairs(self.drones) do if x.name==r.ref then d=x end end;if not d then return end
    if d.lost then
      ui.pick("Found "..d.name,{{text="Put the drone back on its charger "..tostring(d.home).." first.",locked=true},
        {text="  Not yet",value=false},{text="  It is on "..tostring(d.home)..": mark it found",value=true,fg=P.warn}},function(v)
        if v and ui.try(lg.found,d.name) then ui.ok(d.name.." found; booting at "..tostring(d.home)) end
        if v then self:refresh() end
      end,{nofilter=true})
    elseif d.state=="held" then
      ui.confirm("Release cargo","Release the cargo "..d.name.." holds? ("..cargoText(d)..")",function()
        ui.busy("Releasing "..d.name.."…")
        local got=ui.try(lg.release,d.name);self:refresh()
        if not got then return end
        local lines={{d.name.." released:",P.accent}}
        for _,e in ipairs(stacks({cargo=got})) do lines[#lines+1]="  "..ui.label(e.item).." ×"..e.count end
        if #lines==1 then lines[2]="  nothing" end
        ui.ok("Released "..d.name);show("Released · "..d.name,lines)
      end)
    else
      local lines=fields(d,{cargo=true,held=true})
      table.insert(lines,1,{d.name.."  "..(d.lost and "LOST" or tostring(d.state)),d.lost and P.bad or P[stateColour[d.state] or "fg"]})
      lines[#lines+1]=ui.fit("cargo",14)..cargoText(d)
      for _,e in ipairs(stacks(d)) do lines[#lines+1]={"  "..ui.label(e.item).." ×"..e.count,P.dim} end
      show("Drone · "..d.name,lines)
    end
  elseif k=="crafter" or k=="machine" then
    local t=(k=="crafter" and self.res.crafters or self.res.machines)[r.ref];if not t then return end
    local lines=fields(t,{loads=true})
    table.insert(lines,1,{r.ref,P.accent})
    if k=="machine" then
      lines[#lines+1]=ui.fit("loads",14)..#(t.loads or {})
      for i,l in ipairs(t.loads or {}) do lines[#lines+1]={"  "..i..". "..value(l),P.dim} end
    end
    show((k=="crafter" and "Crafter · " or "Machine · ")..r.ref,lines)
  end
end
return S
