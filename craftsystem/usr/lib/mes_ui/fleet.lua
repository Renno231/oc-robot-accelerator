-- Fleet: announcing hardware, drones, crafters and machines in one list.
-- Reads logistics, map and mes on open, R and their change signals only.
local ui=require("mes_ui.core");local lg=require("logistics");local map=require("map");local wh=require("warehouse")
local S={hints="Enter register · release · found · details · R refresh · H help",
  help={{"Enter","new drone, robot or sensor: register · held drone: release cargo"},{"","lost drone: mark found · other rows: details"}}}
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
-- Timing: machine.seconds={plan,lo,hi,samples,source}, seconds per input item.
-- source learned: plan=hi; relearn (hi unknown): plan=max(estimate,2·lo);
-- estimate: the type's configured seconds, else the median hi of the type's
-- learned machines, else none. Which estimate is read from types and peers.
local inf=math.huge
local function secs(v) return (string.format("%.1f",v):gsub("%.0$","")) end
local function timing(name,m,res,types)
  local t=m.seconds;if not t then return end
  local peers=0;for n,x in pairs(res.machines) do if n~=name and x.type==m.type and x.seconds and x.seconds.hi<inf then peers=peers+1 end end
  local est=(types[m.type] or {}).seconds and "estimate" or peers>0 and "type" or "unknown"
  local tag=t.source=="learned" and "learned" or t.source=="relearn" and t.plan<=2*t.lo and "2× lower" or est
  local range=t.hi<inf and (t.lo>0 and secs(t.lo).."–"..secs(t.hi).." s" or "≤"..secs(t.hi).." s") or t.lo>0 and "≥"..secs(t.lo).." s" or "no bounds"
  return {t=t,tag=tag,range=range,peers=peers,n=t.samples.." sample"..(t.samples==1 and "" or "s")}
end
local function explain(x,kind)
  local t=x.t;local why={learned="learned upper bound",["2× lower"]="twice the learned lower bound",
    estimate="the "..kind.." type's estimate",type="median of "..x.peers.." learned "..kind..(x.peers==1 and "" or "s")}
  return x.tag=="unknown" and "No time known yet (no estimate, "..x.n..")." or "Planned at "..secs(t.plan).." s per item ("..why[x.tag]..", "..x.n..").",
    t.hi<inf and (t.lo>0 and "Range "..x.range.."." or "At most "..secs(t.hi).." s; no lower bound yet.")
    or t.lo>0 and "More than "..secs(t.lo).." s; no upper bound yet."
    or x.tag=="unknown" and "Loads are checked after a short wait, then at growing intervals, until output appears; that teaches it."
    or "No bounds learned yet."
end
local function energy(d) return d.energy and (math.floor(d.energy/FULL*100+0.5).."%") or "—" end
-- Sensors are not in drones(); logistics.sensors() names them when present.
local function nextName(drones,base)
  local used={};for _,d in ipairs(drones) do used[d.name]=true end
  for _,n in ipairs(lg.sensors and lg.sensors() or {}) do used[n]=true end
  local n=1;while used[base..n] do n=n+1 end;return base..n
end
function S:rebuild()
  local rows,P=self.rows,ui.P;for k=#rows,1,-1 do rows[k]=nil end
  local function add(text,fg,kind,ref) rows[#rows+1]={text=text,fg=fg,kind=kind,ref=ref,heading=kind=="heading"} end
  local pending,robots,sensors=ui.newHardware();local drones=lg.drones();self.pending,self.drones=pending,drones
  local res=ui.try(function() return mes().resources() end) or {crafters={},machines={}};self.res=res
  -- Types read /etc/mes.cfg: once, then again only when the config changes.
  self.types=self.types or ui.try(function() return mes().types() end) or {}
  if #pending+#robots+#sensors>0 then
    add("New hardware  "..#pending+#robots+#sensors.." waiting",P.warn,"heading")
    for _,a in ipairs(pending) do add("  drone · "..a:sub(1,8).."… · on a charger · Register",P.good,"new",a) end
    for _,a in ipairs(robots) do a=type(a)=="table" and a.address or a;add("  robot · "..a:sub(1,8).."… · unpaired cproc · Register",P.good,"newRobot",a) end
    for _,a in ipairs(sensors) do add("  sensor · "..a:sub(1,8).."… · IO chest sensor · Register",P.good,"newSensor",a) end
    add("",nil,"heading")
  end
  local n={idle=0,working=0,held=0,lost=0}
  for _,d in ipairs(drones) do local k=d.lost and "lost" or d.state;if n[k] then n[k]=n[k]+1 end end
  add("Drones  "..#drones.." · "..n.idle.." idle · "..n.working.." working · "..n.held.." held · "..n.lost.." lost",P.accent,"heading")
  for _,d in ipairs(drones) do
    local place=d.node or (d.home and "home "..d.home) or "?"
    local t="  "..ui.fit(d.name,12)..ui.fit(d.lost and "LOST" or d.state or "?",10)..ui.fit(place,18)..ui.right(energy(d),5).."  "
      ..ui.fit(cargoText(d),56)..(d.job and "job #"..d.job..(d.trip and " trip "..d.trip or "") or "")..(d.releasePending and "  releasing…" or "")
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
  for _,name in ipairs(mn) do local m=res.machines[name];local k=#(m.loads or {});local x=timing(name,m,res,self.types)
    add("  "..ui.fit(name,14)..ui.fit(m.type or "?",12)..ui.fit(m.state or "?",10)..ui.fit(k.." load"..(k==1 and "" or "s"),10)
      ..(x and ui.fit(x.tag=="unknown" and "time unknown" or secs(x.t.plan).." s/item "..x.tag,24)..ui.fit(x.range,16)..x.n or ""),
      m.state=="idle" and P.good or P.accent,"machine",name)
  end
end
function S:draw()
  local ch=0;for _,e in pairs(map.nodes()) do if e.charger then ch=ch+1 end end
  local new=ui.badges.fleet
  ui.title("Fleet",#(self.drones or {}).." drones · "..ch.." chargers"..(new and " · "..new.." new" or ""))
end
function S:refresh() self:rebuild();self.list:refresh();self:draw() end
function S:signal(name,drone,status)
  if name=="mes" and drone=="changed" then self.types=nil end
  if name=="logistics_released" then self:released(drone,status)
  elseif name=="logistics" or name=="mes" or name=="logistics_announce" or name=="mes_robot_announce" then self:refresh() end
end

local show=ui.show
local function value(v)
  if type(v)~="table" then return tostring(v) end
  local parts={};for _,k in ipairs(sorted(v)) do parts[#parts+1]=tostring(k).."="..value(v[k]) end
  return "{"..table.concat(parts,", ").."}"
end
local function fields(t,skip)
  local lines={};for _,k in ipairs(sorted(t)) do if not (skip and skip[k]) then lines[#lines+1]=ui.fit(k,14)..value(t[k]) end end
  return lines
end

-- A release finished: the listing is what the drone still holds (the
-- scheduler returns it to stock), or the report timed out.
function S:released(name,status)
  self:refresh();local P=ui.P
  if status~="ok" then ui.fail(tostring(name)..": cargo report timeout");return end
  local d;for _,x in ipairs(self.drones) do if x.name==name then d=x end end
  local s=stacks({cargo=d and d.cargo or {}})
  if #s==0 then ui.ok(name.." is empty, now idle");return end
  local lines={{name.." still holds:",P.accent}}
  for _,e in ipairs(s) do lines[#lines+1]="  "..ui.label(e.item).." ×"..e.count end
  lines[#lines+1]={"The scheduler returns them to stock.",P.dim}
  ui.ok(name.." holds "..#s.." stack"..(#s==1 and "" or "s"));show("Cargo · "..name,lines)
end

function S:register(address)
  local drones=self.drones
  ui.prompt("Register drone","Name for drone "..address:sub(1,8).."…",nextName(drones,"drone"),function(name)
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
-- Sensor: a name only; Setup's IO section attaches it to a chest.
function S:registerSensor(address)
  ui.prompt("Register sensor","Name for sensor "..address:sub(1,8).."…",nextName(self.drones,"sensor"),function(name)
    if ui.try(lg.register,address,name,nil) then ui.ok("Registered sensor "..name..": attach it in Setup · IO") end
    self:refresh()
  end,{check=function(v)
    if not v:match("^[%w_-]+$") then return nil,"letters, digits, _ and - only" end
    if #v>48 then return nil,"48 characters at most" end
    for _,d in ipairs(self.drones) do if d.name==v then return nil,"name already used" end end
    return true
  end})
end
-- Robot: crafter name, then its buffer: a non-stock storage that is no
-- crafter's buffer or machine's face.
function S:registerRobot(address)
  local crafters=mes().crafters();local n=1;while crafters["cpu"..n] do n=n+1 end
  ui.prompt("Register robot","Crafter name for robot "..address:sub(1,8).."…","cpu"..n,function(name)
    local members,taken,rows=wh.members(),{},{}
    for _,x in pairs(crafters) do taken[x.buffer]=true end
    for _,x in pairs(wh.groups()) do for _,s in pairs(x.roles) do taken[s]=true end end
    for _,s in ipairs(map.storageNames()) do if not members[s] and not taken[s] then local e=map.storage(s)
      rows[#rows+1]={text=ui.fit(s,16).." "..e.node.." "..ui.sideGlyph[e.side],value=s}
    end end
    if #rows==0 then ui.fail("no free non-stock storage: name the chest in front of the robot in Setup");return end
    ui.pick(name.." · buffer: the chest the robot faces",rows,function(buf)
      ui.confirm("Register robot","Register "..address:sub(1,8).."… as "..name..", buffer "..buf.."?",function()
        if ui.try(mes().registerRobot,address,name,buf) then ui.ok("Crafter "..name.." registered: buffer "..buf) end
        self:refresh()
      end)
    end)
  end,{check=function(v)
    if not v:match("^[%w_-]+$") then return nil,"letters, digits, _ and - only" end
    if crafters[v] or wh.groups()[v] then return nil,"name already used" end
    return true
  end})
end
function S:activate(r)
  if not r then return end
  local k,P=r.kind,ui.P
  if k=="new" then self:register(r.ref)
  elseif k=="newRobot" then self:registerRobot(r.ref)
  elseif k=="newSensor" then self:registerSensor(r.ref)
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
        -- Returns at once; the listing arrives as logistics_released.
        if ui.try(lg.release,d.name) then ui.notify("Releasing "..d.name.."…",P.accent) end;self:refresh()
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
    local lines=fields(t,{loads=true,seconds=true})
    table.insert(lines,1,{r.ref,P.accent})
    if k=="machine" then
      lines[#lines+1]=ui.fit("loads",14)..#(t.loads or {})
      for i,l in ipairs(t.loads or {}) do lines[#lines+1]={"  "..i..". "..value(l),P.dim} end
      local x=timing(r.ref,t,self.res,self.types)
      if x then local a,b=explain(x,t.type or "?");lines[#lines+1]={"Timing",P.accent};lines[#lines+1]="  "..a;lines[#lines+1]="  "..b end
    end
    show((k=="crafter" and "Crafter · " or "Machine · ")..r.ref,lines)
  end
end
return S
