-- One survey: its proposal (groups, machines, mismatches, ignored blocks),
-- the user's choices and approval; or its progress, failure or outcome.
-- Nothing is pre-picked: every group shows "role: ?" until the user picks,
-- a "choose" face must be picked, and the user types each name prefix.
-- Approve is refused, with the reason on its row, until every included
-- group has its choices. The record is re-read on open, R and the survey's
-- own signal; station rows on the station signal.
local ui=require("mes_ui.core");local V=require("mes_ui.survey");local map=require("map")
local S={hints="Enter choose · Space include/leave out · A approve · R refresh · H help",
  help={{"Enter","on a group: role, face, name prefix; on an action row, run it"},{"Space","leave the selected group out, or take it back in"},{"A","approve the included groups"}}}
local function stations() local ok,m=pcall(require,"stations");return ok and m or nil end
-- Choices outlive the screen (and a tab switch) until the UI quits.
ui.surveyChoices=ui.surveyChoices or {}
local roleText={stock="stock: count and use its contents",other="other: a buffer, machine face or other storage",
  import="import: drones move what you put in into stock",export="export: fetched items are delivered here for you"}
local kindText={wall="wall",row="row",storage="single chest"}
local function blocks(g) local n=0;for _,v in ipairs(g.inventories) do n=n+(v.parts and #v.parts or 1) end;return n end
local function label(n) return n and ui.label(n) or "?" end
-- What approval names: a single chest takes the prefix, a row or wall
-- prefix1..prefixN, one per physical block.
local function names(g,prefix) if g.kind=="storage" then return {prefix} end;local t={};for k=1,blocks(g) do t[k]=prefix..k end;return t end

function S:open(arg)
  local a=ui.area();self.id=arg.id;self.rows={}
  self.choices=ui.surveyChoices[self.id] or {};ui.surveyChoices[self.id]=self.choices
  self.lw=ui.wide() and math.floor(a.w*0.66) or a.w
  self.list=ui.list(self.menu,{name="v",x=1,y=a.y,w=self.lw,h=a.h,
    count=function() return #self.rows end,
    row=function(i,w) return self:row(i,w) end,
    activate=function(i) self:activate(self.rows[i]) end,
    moved=function(i) self:pane(i) end})
  self:read();self:rebuild();self.list:refresh();self.list:first()
end
function S:read()
  local sv=V.engine();self.r=sv and sv.get(self.id)
  for _,g in ipairs(self.r and self.r.groups or {}) do if not self.choices[g.id] then self.choices[g.id]={include=true} end end
end
-- The first reason approval would be refused, in the engine's order (role,
-- face, prefix), then names already used or claimed by another group.
function S:blocked()
  local used,n={},0;local st=stations()
  for _,x in ipairs(st and st.list() or {}) do used[x.name]="station "..x.name end
  for _,g in ipairs(self.r.groups) do local c=self.choices[g.id]
    if c.include then n=n+1
      if not c.role then return "group "..g.id.." needs a role",g.id end
      if g.face=="choose" and not c.face then return "group "..g.id.." needs a face",g.id end
      if not c.prefix then return "group "..g.id.." needs a name prefix",g.id end
      for _,s in ipairs(names(g,c.prefix)) do
        local by=used[s] or map.node(s) and "a map node" or map.storage(s) and "a named storage"
        if by then return "group "..g.id..": name "..s.." is taken by "..(type(by)=="number" and "group "..by or by),g.id end
        used[s]=g.id
      end
    end
  end
  if n==0 then return "no groups included: include one, or reject the survey" end
  return nil,n
end
function S:rebuild()
  local rows,P,r=self.rows,ui.P,self.r;for k=#rows,1,-1 do rows[k]=nil end
  local function head(t,fg) rows[#rows+1]={head=t,fg=fg or P.accent} end
  local function line(t,fg) rows[#rows+1]={head=t,fg=fg or P.dim} end
  if not r then head("Survey #"..self.id.." is gone",P.bad);return end
  local st=r.state
  if st=="surveying" then
    head("Surveying · "..V.stateText.surveying)
    local m=r.metrics or {}
    line("  "..(m.scans or 0).." scans · "..(m.hops or 0).." hops · "..(m.analyzes or 0).." analyzed  (as of opening; R re-reads)",P.fg)
    line("  Survey drones: "..(V.droneText()));line("  The proposal shows here when the scan is done.")
  elseif st=="failed" then
    head("Failed",P.bad);for _,l in ipairs(V.wrap(r.reason or "no reason given",self.lw-6)) do line("  "..l,P.bad) end
    rows[#rows+1]={again=true}
  elseif st=="rejected" then head("Rejected · nothing was made",P.dim)
  elseif st=="approved" then head("Approved · S1 commissioning has taken over",P.good)
    line("  Each station test-flies its new path, reads its chests and registers them (Setup › Stations).")
  end
  if r.stations and #r.stations>0 then
    head("Stations "..(st=="failed" and "made before the failure" or "made by this survey"))
    for _,n in ipairs(r.stations) do rows[#rows+1]={station=n} end
    rows[#rows+1]={jump=true}
  end
  if st=="surveying" and #r.groups==0 and #r.mismatches==0 then return end
  local editable=st=="proposed"
  if #r.groups>0 or st=="proposed" then
    head("Groups ("..#r.groups..")"..(editable and " · Enter: role, face, prefix · Space: leave out" or ""))
    for _,g in ipairs(r.groups) do rows[#rows+1]={group=g} end
    if #r.groups==0 then line("  none: no new chests were found") end
  end
  if editable then rows[#rows+1]={approve=true};rows[#rows+1]={reject=true} end
  local machines,other={},{}
  for _,v in ipairs(r.ignored) do if v.kind=="ignored" then other[#other+1]=v else machines[#machines+1]=v end end
  if #r.mismatches>0 then
    head("Mismatches ("..#r.mismatches..") · nothing changed: the map and stations still have them",P.bad)
    for _,m in ipairs(r.mismatches) do rows[#rows+1]={mismatch=m} end
  end
  head("Machines ("..#machines..") · not yet supported (S2): no station is made")
  for _,v in ipairs(machines) do rows[#rows+1]={ignored=v} end
  head("Ignored ("..#other..")")
  for _,v in ipairs(other) do rows[#rows+1]={ignored=v} end
  if r.limitation then line("Note: "..r.limitation) end
end
local function known(k) return k.station and "station "..k.station or k.storage and "storage "..k.storage or k.node and "map node "..k.node or "known" end
function S:row(i,w)
  local x=self.rows[i];local P=ui.P
  if x.head then return x.head,x.fg,true end
  -- Spacing and pair are in the pane: face, role and prefix fit 160 columns.
  if x.group then local g,c=x.group,self.choices[x.group.id];local n=#g.inventories
    local kind=g.kind=="wall" and "wall "..math.floor(n/g.levels).." × "..g.levels or g.kind=="row" and "row × "..n or "single chest"
    local count=n.." inv"..(blocks(g)>n and " · "..blocks(g).." blocks" or "")
    local face=g.face=="choose" and (c.face and c.face.." (picked)" or "choose: "..table.concat(g.faces,"/")) or g.face
    local t="  "..(c.include and "[x] " or "[ ] ")..ui.fit("#"..g.id,4)..ui.fit(kind,15)..ui.fit(label(g.name),9)..ui.fit(count,18)
      ..ui.fit("face "..face,24)..ui.fit("role: "..(c.role or "?"),13).."prefix: "..(c.prefix or "?")
    if self.r.state~="proposed" then return t,c.include and P.fg or P.dim end
    local missing=not c.role or g.face=="choose" and not c.face or not c.prefix
    return t,not c.include and P.dim or missing and P.warn or P.good
  end
  if x.approve then local why,n=self:blocked()
    if why then return "  ✗ Approve: "..why,P.bad end
    return "  ▶ Approve "..n.." group"..(n==1 and "" or "s").." → "..n.." station"..(n==1 and "" or "s"),P.good end
  if x.reject then return "  ✗ Reject the whole survey",P.fg end
  if x.again then return "  ▶ Survey the same corners again",P.good end
  if x.jump then return "  ▶ Go to Setup › Stations",P.good end
  if x.station then local st=stations();local s
    for _,v in ipairs(st and st.list() or {}) do if v.name==x.station then s=v end end
    if not s then return "  "..ui.fit(x.station,18).."gone",P.dim end
    return "  "..ui.fit(s.name,18)..ui.fit(s.kind..(s.count and " × "..s.count or ""),14)..ui.fit(s.state,10)..(s.state=="checking" and (s.phase or "") or s.reason or ""),
      P[({checking="accent",ready="good",failed="bad",removing="accent"})[s.state] or "fg"]
  end
  if x.mismatch then local m=x.mismatch
    return "  "..ui.fit(V.pos(m.position),16)..ui.fit(known(m.known),22)..(m.reading==0 and "expected a block, reads air" or "expected air, reads a block")..(m.block and " · "..label(m.block.name) or ""),P.bad
  end
  local v=x.ignored;return "  "..ui.fit(label(v.name),20)..ui.fit(V.pos(v.position),16)..(v.facing and "facing "..v.facing or ""),P.fg
end
function S:pane(i)
  if not ui.wide() then return end
  local a=ui.area();local x=self.rows[i or self.list.cur];local P=ui.P;local w=a.w-self.lw;local lines={}
  local function add(t,fg) for _,l in ipairs(V.wrap(t,w-4)) do lines[#lines+1]={l,fg} end end
  local function kv(k,v,fg) lines[#lines+1]={ui.fit(k,10)..tostring(v),fg} end
  local r=self.r
  if x and x.group then local g,c=x.group,self.choices[x.group.id];local n=#g.inventories
    lines[1]={"Group #"..g.id.."  "..(kindText[g.kind] or g.kind),P.accent}
    kv("Block",label(g.name).."  ("..g.name..")")
    kv("Members",n.." inventor"..(n==1 and "y" or "ies")..(blocks(g)>n and ", "..blocks(g).." blocks (double chests)" or ""))
    if g.kind=="wall" then kv("Shape",math.floor(n/g.levels).." wide × "..g.levels.." levels, level step "..g.levelSpacing) end
    if g.kind~="storage" then kv("Runs",g.rowDir) end
    kv("Spacing",g.spacing..(g.spacing==2 and "  (every other block)" or "  (adjacent)"));kv("Pair",g.pair..(g.pair==2 and "  (two blocks per inventory)" or "  (one block per inventory)"))
    kv("Face",g.face=="choose" and "choose one of "..table.concat(g.faces,", ") or g.face.."  (the only reachable face)",g.face=="choose" and not c.face and P.warn or nil)
    lines[#lines+1]="";lines[#lines+1]={"Your choices",P.dim}
    kv("Include",c.include and "yes" or "no: left out",not c.include and P.dim or nil)
    kv("Role",c.role and roleText[c.role] or "? — pick one",not c.role and P.warn or nil)
    if g.face=="choose" then kv("Face",c.face or "? — pick one",not c.face and P.warn or nil) end
    kv("Prefix",c.prefix or "? — type one",not c.prefix and P.warn or nil)
    if c.prefix then local t=names(g,c.prefix);kv("Names",#t==1 and t[1] or t[1].." … "..t[#t]) end
    lines[#lines+1]="";lines[#lines+1]={"Members",P.dim}
    for _,v in ipairs(g.inventories) do local p=v.parts
      lines[#lines+1]="  "..V.pos(v)..(p and " + "..V.pos(p[2]).."  double" or "  "..tostring(v.size or "").." slots")
    end
  elseif x and x.mismatch then local m=x.mismatch
    lines={{"Mismatch at "..V.pos(m.position),P.bad},""}
    kv("Known as",known(m.known));kv("Reads",m.reading==0 and "air" or "a block (density "..tostring(m.reading)..")")
    if m.block then kv("Analyzed",m.block.name) end
    lines[#lines+1]="";add("Nothing changed: the map and the stations still have it as before. Check the block in the world, then fix it or remove what is stale (Setup).",P.warn)
  elseif x and x.ignored then local v=x.ignored
    lines={{label(v.name),P.accent},v.name,""};kv("At",V.pos(v.position));if v.facing then kv("Facing",v.facing) end
    kv("Listed",v.kind);if v.reason then kv("Reason",v.reason) end
    if v.kind~="ignored" then lines[#lines+1]="";add("Machine stations come with S2; until then no station is made for it.",P.dim) end
  elseif x and x.approve then lines={{"Approve",P.accent},""}
    local why=self:blocked();if why then add("Refused until: "..why,P.bad);lines[#lines+1]="" end
    add("Approval makes one station per included group. S1 commissioning then test-flies each new path link, reads each chest and registers it; Setup › Stations shows the progress. Groups left out are not made.")
  elseif x and x.reject then lines={{"Reject",P.accent},""};add("Nothing is made. The survey stays listed as rejected.")
  elseif x and x.again then lines={{"Survey again",P.accent},""};add("Opens the survey form with this survey's corners: "..V.area(r.area))
  else
    lines={{"Survey #"..self.id.."  "..(r and r.state or "gone"),r and P[V.stateFg[r.state]] or P.bad}}
    if r then lines[#lines+1]=V.stateText[r.state];lines[#lines+1]=""
      kv("Area",V.area(r.area));kv("Size",V.size(r.area).."  (x × y × z)");if r.origin then kv("From",V.pos(r.origin).."  (nearest mapped node)") end
      local m=r.metrics or {};kv("Work",(m.scans or 0).." scans · "..(m.hops or 0).." hops · "..(m.analyzes or 0).." analyzed")
      if r.reason then lines[#lines+1]="";add(r.reason,P.bad) end
    end
  end
  ui.pane(lines,self.lw+1,a.y,w,a.h)
end
function S:draw()
  local r=self.r
  ui.title("Setup › Surveys › #"..self.id..(r and " · "..r.state or ""),r and (V.area(r.area).." · "..V.size(r.area)) or "")
  self:pane()
end
function S:refresh() self:read();self:rebuild();self.list:refresh();self:draw() end
function S:signal(name,id)
  if name=="survey" and id==self.id then self.reread,self.outdated=true,true
  elseif name=="station" and self.r and self.r.stations then self.outdated=true end
end
function S:update()
  if self.reread then self.reread=nil;self:read() end
  self:rebuild();self.list:refresh();self:draw()
end
local function choose(title,values,cur,done,text,help)
  local rows,at={{text=help,fg=ui.P.dim,locked=true}},1
  for _,v in ipairs(values) do rows[#rows+1]={text=(v==cur and "● " or "  ")..(text and text(v) or v),value=v};if v==cur then at=#rows end end
  ui.pick(title,rows,done,{nofilter=true,at=at})
end
-- Role, face (when it is "choose") and prefix for one group.
function S:edit(g)
  local c=self.choices[g.id];local function done() self.list:refresh();self:pane() end
  local fields={{label="Include",show=function() return c.include and "yes: make a station" or "no: leave it out" end,edit=function(r) c.include=not c.include;r() end},
    {label="Role",show=function() return c.role and roleText[c.role] or "? — pick one" end,colour=function() return not c.role and ui.P.warn or nil end,edit=function(r)
      choose("Role · group "..g.id,{"stock","other","import","export"},c.role,function(v) c.role=v;r() end,function(v) return roleText[v] end,"What the chests are for; nothing is picked for you.") end}}
  if g.face=="choose" then fields[#fields+1]={label="Face",show=function() return c.face or "? — pick one of "..table.concat(g.faces,", ") end,colour=function() return not c.face and ui.P.warn or nil end,edit=function(r)
      choose("Face · group "..g.id,g.faces,c.face,function(v) c.face=v;r() end,nil,"The reachable faces the survey found; drones use the one you pick.") end} end
  fields[#fields+1]={label="Name prefix",show=function() if not c.prefix then return "? — type one" end;local t=names(g,c.prefix);return c.prefix.."  → "..(#t==1 and t[1] or t[1].." … "..t[#t]) end,
    colour=function() return not c.prefix and ui.P.warn or nil end,edit=function(r)
      ui.prompt("Name prefix · group "..g.id,g.kind=="storage" and "The chest's name" or "Members are prefix1, prefix2, …",c.prefix,function(v) c.prefix=v;r() end,
        {check=function(v) if v:find("%s") then return nil,"no spaces" end;return true end}) end}
  ui.form("Group #"..g.id.." · "..(kindText[g.kind] or g.kind).." · "..label(g.name),fields,"Done",function(close) close();done() end,90)
end
function S:approve()
  local why=self:blocked();if why then ui.fail("Approve refused: "..why);return end
  local sv=V.engine();local choices={}
  for _,g in ipairs(self.r.groups) do local c=self.choices[g.id]
    if c.include then choices[g.id]={role=c.role,prefix=c.prefix,face=g.face=="choose" and c.face or nil} end
  end
  ui.busy("Approving survey #"..self.id.."…")
  local ok,err=sv.approve(self.id,choices)
  if not ok then ui.fail("Approve refused: "..tostring(err):gsub("^[^:]+:%d+: ",""));self:refresh();return end
  ui.ok("Approved: S1 commissioning has taken over; Setup › Stations shows the progress")
  self:refresh()
end
function S:activate(x)
  if not x then return end
  if x.group and self.r.state=="proposed" then self:edit(x.group)
  elseif x.approve then self:approve()
  elseif x.reject then ui.confirm("Reject survey #"..self.id,"Reject the whole survey? Nothing is made.",function()
      if ui.try(V.engine().reject,self.id) then ui.ok("Survey #"..self.id.." rejected") end;self:refresh() end)
  elseif x.again then V.request(self.r.area,function() ui.pop() end)
  elseif x.jump or x.station then local name=x.station or self.r.stations[1];ui.switch("setup");local s=ui.current();if s.focus then s:focus("station",name) end
  end
end
function S:key(char,code)
  local x=self.rows[self.list.cur]
  if char==32 and x and x.group and self.r.state=="proposed" then local c=self.choices[x.group.id];c.include=not c.include;self.list:refresh();self:pane();return true end
  if code==ui.keys.a and self.r and self.r.state=="proposed" then self:approve();return true end
end
return S
