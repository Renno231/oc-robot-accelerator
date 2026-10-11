-- Stock stats: the header panel on Stock (totals, fill bar, trend, warnings),
-- the per-storage overview pushed from it, and the warning thresholds editor.
-- Everything is read from the stats service on open and on a warehouse
-- "changed"; nothing is polled.
local ui=require("mes_ui.core");local unicode=require("unicode")
local S={hints="T thresholds · ⌫ back · H help",help={{"T","edit the warning thresholds"}}}
local function stats() local ok,m=pcall(require,"stats");return ok and m or nil end
S.stats=stats
local function pct(f) return math.floor((f or 0)*100+0.5).."%" end
function S.rate(v) if (v or 0)==0 then return "0" end;return (string.format("%+.1f",v):gsub("%.0$","")) end
local function hours(h) if h<1 then return "~"..math.max(1,math.floor(h*60+0.5)).." m" end;return string.format("~%.1f h",h) end
local function age(s)
  -- Entry times are uptime: one from before a restart comes out negative.
  if not s then return "never" elseif s<0 then return "before restart" end
  if s<60 then return math.floor(s).." s ago" elseif s<3600 then return math.floor(s/60).." m ago" elseif s<86400 then return math.floor(s/3600).." h ago" end
  return math.floor(s/86400).." d ago"
end
local function level(f,c) return f>=c.fillBad and ui.P.bad or f>=c.fillWarn and ui.P.warn or nil end

-- Fill t with sum, warn, cfg; false when stats is not available. S.rev
-- counts threshold edits: a screen whose t.rev differs reads again.
S.rev=0
function S.stale(t) return t.rev~=S.rev end
function S.read(t)
  local st=stats();t.sum=nil;t.rev=S.rev;if not st then return false end
  t.sum=ui.try(st.summary);t.warn=ui.try(st.warnings) or {};t.cfg=st.settings()
  return t.sum~=nil
end

-- Four lines from y: totals and trend, fill bar, two warning lines.
function S.header(t,x,y,w)
  local P=ui.P;ui.fill(x,y,w,4,P.bg)
  local r,c=t.sum,t.cfg
  if not r then ui.text(x+1,y,"Stock stats unavailable",P.dim);return end
  local left="Stock "..ui.num(r.usedSlots).."/"..ui.num(r.slots).." slots ("..pct(r.fill)..") · "..ui.num(r.items).." items · "..ui.num(r.kinds).." kinds · "..r.storages.." storage"..(r.storages==1 and "" or "s")
  local tr=r.trend
  local right=(tr.fullInHours and "Full in "..hours(tr.fullInHours) or tr.state).." · "..S.rate(tr.usedPerHour1).." slots/h last hour · "..S.rate(tr.usedPerHour6).."/h over 6 h"
  local u=r.unknown>0 and " · "..r.unknown.." unread" or "";local ll=unicode.len(left)+unicode.len(u)
  if unicode.len(right)>w-ll-4 then right=ui.fit(right,math.max(0,w-ll-4)) end;local rx=x+w-unicode.len(right)-1
  ui.text(x+1,y,ui.fit(left,rx-x-3-unicode.len(u)),P.fg)
  if u~="" then ui.text(x+1+math.min(unicode.len(left),rx-x-3-unicode.len(u)),y,u,P.warn) end
  ui.text(rx,y,right,tr.fullInHours and tr.fullInHours<=c.fullSoonHours and P.bad or tr.state=="growing" and P.warn or P.dim)
  -- Fill bar in the threshold colour; the thresholds after it.
  local tail=" "..ui.right(pct(r.fill),4).."   warn at "..pct(c.fillWarn).." · bad at "..pct(c.fillBad)
  local bw=math.max(4,w-unicode.len(tail)-2);local bar=ui.bar(r.usedSlots,r.slots,bw);local k=r.slots>0 and math.floor(math.min(1,r.usedSlots/r.slots)*bw+0.5) or 0
  ui.text(x+1,y+1,unicode.sub(bar,1,k),level(r.fill,c) or P.good);ui.text(x+1+k,y+1,unicode.sub(bar,k+1),P.dim)
  ui.text(x+1+bw,y+1,r.slots>0 and tail or r.storages>0 and "  no storage read yet" or "  no stock storages",P.dim)
  -- Stock-wide warnings on one line, storages over the warn level on the next.
  local a,ca,list={},nil,{}
  for _,v in ipairs(t.warn) do
    if v.kind=="fill" then a[#a+1]="Stock "..pct(v.fill).." full";ca=ca==P.bad and P.bad or level(v.fill,c) or P.warn
    elseif v.kind=="fullSoon" then a[#a+1]="full in "..hours(v.hours).." at this rate";ca=P.bad
    elseif v.kind=="storageFill" then list[#list+1]=v
    else a[#a+1]=tostring(v.kind);ca=ca or P.warn end
  end
  local lines={}
  if #a>0 then lines[1]={"▲ "..table.concat(a," · "),ca} end
  if #list>0 then
    table.sort(list,function(p,q) return p.fill>q.fill end)
    local s={};for k=1,math.min(#list,12) do s[k]=list[k].name.." "..pct(list[k].fill) end
    lines[#lines+1]={"▲ "..#list.." storage"..(#list==1 and "" or "s").." at or over "..pct(c.fillWarn)..": "..table.concat(s,", ")..(#list>12 and ", …" or ""),level(list[1].fill,c) or P.warn}
  end
  if #lines==0 then lines[1]={"No warnings",P.good} end
  for k=1,#lines do ui.text(x+1,y+1+k,ui.fit(lines[k][1],w-2),lines[k][2]) end
end

-- Warning thresholds: applied at once; the stats service checks each value.
local defs={{"fillWarn","Warn when stock is this full","%"},{"fillBad","Bad when stock is this full","%"},{"fullSoonHours","Warn when it will be full within","h"}}
local function show(v,u) return string.format("%g",u=="%" and v*100 or v).." "..u end
function S.thresholds()
  local st=stats();if not st then ui.fail("stock stats unavailable");return end
  local cfg=st.settings();local L
  ui.modal({title="Stock warning thresholds",w=60,h=7,build=function(m)
    L=ui.list(m.menu,{name="t",x=m.ix,y=m.iy,w=m.iw,h=3,bg=ui.P.box,count=function() return #defs end,
      row=function(i) local d=defs[i];return ui.fit(d[2],m.iw-10)..ui.right(show(cfg[d[1]],d[3]),10) end,
      activate=function(i)
        local d=defs[i]
        ui.prompt(d[2],d[2]..(d[3]=="%" and " (percent, 0 to 100)" or " (hours)"),string.format("%g",d[3]=="%" and cfg[d[1]]*100 or cfg[d[1]]),function()
          cfg=st.settings();S.rev=S.rev+1;L:refresh();ui.ok("Saved: "..d[2].." "..show(cfg[d[1]],d[3]))
        end,{number=true,check=function(v)
          local ok,err=pcall(st.set,d[1],d[3]=="%" and v/100 or v)
          if ok then return true end;return nil,(tostring(err):gsub("^[^:]+:%d+: ",""))
        end})
      end})
    m.paint=function() ui.text(m.ix,m.y+m.h-2,ui.fit("Enter edits · saved at once · ⌫ close",m.iw),ui.P.dim,ui.P.box) end
    m.key=function(_,code) if code==ui.keys.back then ui.close(m);return true end end
    L:refresh()
  end})
end

-- The overview screen: one row per storage, fullest first.
function S:open()
  local a=ui.area();self.t={};self.rows={}
  self.list=ui.list(self.menu,{name="s",x=1,y=a.y+5,w=a.w,h=a.h-5,count=function() return #self.rows end,
    row=function(i,w) return self:row(i,w) end})
  self:load();self.list:refresh()
end
function S:load()
  local rows=self.rows;for k=#rows,1,-1 do rows[k]=nil end
  if S.read(self.t) then
    local r=self.t.sum;for k,v in ipairs(r.perStorage) do rows[k]=v end
    table.sort(rows,function(p,q) if p.fill~=q.fill then return p.fill>q.fill end;return p.name<q.name end)
    if r.unknown>0 then rows[#rows+1]={unread=r.unknown} end
    if #rows==0 then rows[1]={none=true} end
  end
  self.dirty=false
end
function S:row(i,w)
  local v=self.rows[i];local P=ui.P
  if v.none then return "  No stock storages",P.dim,true end
  if v.unread then return "  "..v.unread.." storage"..(v.unread==1 and "" or "s").." not read yet: no slot counts",P.warn,true end
  local top={};for k,e in ipairs(v.top) do top[k]=ui.label(e.item).." "..ui.num(e.count) end
  local used=v.slots-v.freeSlots
  local t="  "..ui.fit(v.name,20)..ui.right(used.."/"..v.slots,9)..ui.right(pct(v.fill),6).."  "..ui.bar(used,v.slots,10).."  "
  return t..ui.fit(table.concat(top,", "),w-unicode.len(t)-15)..ui.right(age(v.age),15),level(v.fill,self.t.cfg) or P.fg
end
function S:draw()
  if self.dirty or S.stale(self.t) then self:load();self.list:refresh() end
  local a=ui.area();local n=self.t.sum and self.t.sum.storages or 0
  ui.title("Stock overview",n.." storage"..(n==1 and "" or "s").." · fullest first")
  S.header(self.t,1,a.y,a.w)
  ui.text(1,a.y+4,ui.fit(ui.fit("  Storage",20+2)..ui.right("Slots",9)..ui.right("Fill",6).."              Top items",a.w-15)..ui.right("Observed",15),ui.P.dim)
end
function S:signal(name,what)
  if name~="warehouse" or what~="changed" then return end
  self.dirty=true
  if ui.current()==self and not ui.inModal() then self:draw() end
end
function S:key(_,code)
  if code==ui.keys.t then S.thresholds();return true end
end
return S
