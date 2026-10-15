-- Surveys: every survey with its state and reason, re-read on open, R and
-- the ("survey",id,state) signal only. Enter reviews one (mes_ui.survey_review);
-- "+ Survey an area" asks for two corners and starts one. The helpers below
-- are shared with the review screen.
local ui=require("mes_ui.core")
local S={hints="Enter review · + rows survey an area · R refresh · H help",
  help={{"Enter","review the selected survey; on the + row, survey an area"}}}
local function engine() local ok,m=pcall(require,"survey");return ok and m or nil end
S.engine=engine
S.stateFg={surveying="accent",proposed="warn",approved="good",rejected="dim",failed="bad"}
S.stateText={surveying="a survey drone is scanning the area",proposed="waiting for your approval",
  approved="approved: stations are commissioning",rejected="rejected: nothing was made",failed="failed"}
function S.pos(p) return "("..p.x..","..p.y..","..p.z..")" end
function S.area(a) return "("..a.x1..","..a.y1..","..a.z1..")–("..a.x2..","..a.y2..","..a.z2..")" end
function S.size(a) return (a.x2-a.x1+1).." × "..(a.y2-a.y1+1).." × "..(a.z2-a.z1+1) end
function S.wrap(s,w)
  local out,line={},"";for word in tostring(s):gmatch("%S+") do
    if line~="" and #line+1+#word>w then out[#out+1]=line;line=word else line=line=="" and word or line.." "..word end
  end
  if line~="" then out[#out+1]=line end;return out
end
-- Survey-capable drones (geolyzer): logistics sends the first idle one.
function S.drones()
  local out={}
  for _,d in ipairs(require("logistics").drones()) do if d.survey then out[#out+1]=d.name.." ("..tostring(d.state)..")" end end
  return out
end
function S.droneText()
  local d=S.drones()
  if #d==0 then return "none registered: a drone with a geolyzer registers on Fleet",ui.P.bad end
  return #d==1 and d[1].." goes" or "the first idle of "..table.concat(d,", ")
end

-- Two typed corners, "x y z" each; the engine checks the cap and refuses
-- with its own text.
local function parse(v)
  local t={};for n in tostring(v):gmatch("[^%s,]+") do t[#t+1]=tonumber(n) end
  if #t~=3 then return nil,"three whole numbers: x y z" end
  for _,n in ipairs(t) do if n%1~=0 then return nil,"whole numbers only" end end
  return t
end
function S.request(from,done)
  local sv=engine();if not sv then ui.fail("the survey library is not loaded");return end
  local c={from and {from.x1,from.y1,from.z1},from and {from.x2,from.y2,from.z2}}
  local function corner(k) return {label="Corner "..k,show=function() return c[k] and table.concat(c[k],"  ") or "— required (x y z)" end,
    colour=function() return not c[k] and ui.P.warn or nil end,edit=function(r)
      ui.prompt("Corner "..k,"Block coordinates of corner "..k..": x y z",c[k] and table.concat(c[k]," "),function(v) c[k]=parse(v);r() end,{check=parse})
    end} end
  local function area() return c[1] and c[2] and {x1=c[1][1],y1=c[1][2],z1=c[1][3],x2=c[2][1],y2=c[2][2],z2=c[2][3]} end
  local function over() local a=area();return a and (math.abs(a.x2-a.x1)>=32 or math.abs(a.y2-a.y1)>=16 or math.abs(a.z2-a.z1)>=32) end
  local fixed=function() ui.notify("shown for information") end
  ui.form("Survey an area",{corner(1),corner(2),
    {label="Size",show=function() local a=area();if not a then return "x × y × z · cap 32 × 16 × 32" end
      return (math.abs(a.x2-a.x1)+1).." × "..(math.abs(a.y2-a.y1)+1).." × "..(math.abs(a.z2-a.z1)+1).."  (x × y × z) · cap 32 × 16 × 32"..(over() and "  · over the cap" or "") end,
      colour=function() return over() and ui.P.bad or ui.P.dim end,edit=fixed},
    {label="Survey drone",show=function() return (S.droneText()) end,colour=function() local _,fg=S.droneText();return fg or ui.P.dim end,edit=fixed},
  },"Start survey",function(close)
    local a=area();if not a then ui.fail("enter both corners");return end
    local id,err=sv.request(a)
    if not id then ui.fail("Refused: "..tostring(err):gsub("^[^:]+:%d+: ",""));return end
    close();ui.ok("Survey #"..id.." started: it shows here when the drone has scanned the area")
    if done then done(id) end
  end,90,{logistics_drone=true})
end

function S:open(arg)
  local a=ui.area();self.rows={}
  self.lw=ui.wide() and math.floor(a.w*0.62) or a.w
  self.list=ui.list(self.menu,{name="s",x=1,y=a.y+1,w=self.lw,h=a.h-1,
    count=function() return #self.rows end,
    row=function(i,w) return self:row(i,w) end,
    activate=function(i) self:activate(self.rows[i]) end,
    moved=function(i) self:pane(i) end})
  self:rebuild();self.list:refresh()
  if arg and arg.request then S.request(nil,function() self:refresh() end) end
end
function S:rebuild()
  local rows=self.rows;local was=rows[self.list.cur];was=was and was.id
  for k=#rows,1,-1 do rows[k]=nil end
  rows[1]={add=true}
  local sv=engine();local all=sv and ui.try(sv.list) or {};self.n={}
  for k=#all,1,-1 do local r=all[k];rows[#rows+1]=r;self.n[r.state]=(self.n[r.state] or 0)+1;if r.id==was then self.list.cur=#rows end end
  self.total=#all;self.dirty=false
end
local function plural(n,w,many) return n.." "..(n==1 and w or many or w.."s") end
S.plural=plural
function S:row(i,w)
  local r=self.rows[i];local P=ui.P
  if r.add then return "  + Survey an area…",P.good end
  local found=r.reason or r.state=="surveying" and "scanning…" or plural(r.groups,"group").." · "..plural(r.mismatches,"mismatch","mismatches").." · "..r.ignored.." ignored"
  return ui.right("#"..r.id,5).."  "..ui.fit(r.state,11)..ui.fit(S.area(r.area),28)..found,P[S.stateFg[r.state]]
end
function S:pane(i)
  if not ui.wide() then return end
  local a=ui.area();local r=self.rows[i or self.list.cur];local P=ui.P;local w=a.w-self.lw;local lines
  local function add(t,fg) for _,l in ipairs(S.wrap(t,w-4)) do lines[#lines+1]={l,fg} end end
  if not r or r.add then
    lines={{"Survey an area",P.accent},""}
    add("Enter two corners; a drone with a geolyzer scans the area, finds the chests and proposes stations. You review and approve; nothing is made before that.")
    lines[#lines+1]="";lines[#lines+1]={"Cap",P.dim};add("32 × 16 × 32 blocks (x × y × z)")
    lines[#lines+1]="";lines[#lines+1]={"Survey drone",P.dim};local t,fg=S.droneText();add(t,fg)
  else
    lines={{"Survey #"..r.id.."  "..r.state,P[S.stateFg[r.state]]},S.stateText[r.state],"",
      ui.fit("Area",8)..S.area(r.area),ui.fit("Size",8)..S.size(r.area).."  (x × y × z)"}
    if r.state~="surveying" then lines[#lines+1]=ui.fit("Found",8)..plural(r.groups,"group")..", "..r.ignored.." ignored"
      if r.mismatches>0 then lines[#lines+1]={ui.fit("",8)..plural(r.mismatches,"mismatch","mismatches")..": nothing changed",P.bad} end end
    if r.reason then lines[#lines+1]="";lines[#lines+1]={"Reason",P.dim};add(r.reason,P.bad) end
    if r.state=="surveying" then lines[#lines+1]="";lines[#lines+1]={"Survey drones",P.dim};local t,fg=S.droneText();add(t,fg) end
    lines[#lines+1]="";add(r.state=="proposed" and "Enter reviews the proposal and approves it." or r.state=="failed" and "Enter shows it; you can survey the same corners again." or "Enter shows it.",P.dim)
  end
  ui.pane(lines,self.lw+1,a.y,w,a.h)
end
function S:draw()
  if self.dirty then self:rebuild();self.list:refresh() end
  local n=self.n;local parts={}
  for _,k in ipairs({"proposed","surveying","failed"}) do if n[k] then parts[#parts+1]=n[k].." "..k end end
  ui.title("Setup › Surveys",self.total.." surveys"..(#parts>0 and " · "..table.concat(parts," · ") or ""))
  ui.text(1,ui.area().y,ui.fit("   Id  State      Area                        Found, or the reason",self.lw),ui.P.dim)
  self:pane()
end
function S:refresh() self:rebuild();self.list:refresh();self:draw() end
-- A drone's pushed state only redraws the pane (it names the survey drones).
function S:update() self:draw() end
function S:signal(name)
  if name=="survey" then self.dirty,self.outdated=true,true elseif name=="logistics_drone" then self.outdated=true end
end
function S:activate(r)
  if not r then return end
  if r.add then S.request(nil,function() self:refresh() end);return end
  ui.push("mes_ui.survey_review",{id=r.id})
end
return S
