-- Stock: warehouse totals, filter as you type, locations and fetch; the
-- stock stats header (fill, trend, warnings) above the list.
local ui=require("mes_ui.core");local wh=require("warehouse");local X=require("mes_ui.stockstats")
local S={filterable=true,hints="Enter/E fetch · C craft · W where · I item · O storages · T thresholds · S rescan item · F search · H help",
  help={{"Enter / E","fetch the selected item to a storage"},{"C","craft the selected item"},
    {"W","show where it is"},{"I","item detail: free, reserved, trend, where"},{"O","stock overview: every storage's fill"},
    {"T","edit the warning thresholds"},{"S","rescan the storages holding it"},{"Shift+R","rescan every stock storage (drones)"}}}

function S:open()
  local a=ui.area();self.index={};self.rev=-1;self.t={};X.read(self.t)
  self.lw=ui.wide() and math.floor(a.w*0.58) or a.w
  self.list=ui.list(self.menu,{name="i",x=1,y=a.y+5,w=self.lw,h=a.h-5,
    count=function() return #self.index end,
    row=function(i,w) return self:row(i,w) end,
    activate=function(i) self:actions(i) end,
    moved=function(i) self:detail(i) end})
  self:rebuild();self.list:refresh();self:detail(self.list.cur)
end
function S:rebuild()
  local t=wh.totals();self.totals=t;self.rev=wh.revision()
  local idx,f=self.index,ui.filterText:lower();local units=0
  for k=#idx,1,-1 do idx[k]=nil end
  for k=1,#t do local e=t[k]
    if f=="" or ui.label(e.item):lower():find(f,1,true) or e.item.name:find(f,1,true) then idx[#idx+1]=k;units=units+e.count end
  end
  self.units=units
end
function S:row(i,w)
  local e=self.totals[self.index[i]]
  local count=ui.right(ui.num(e.count),9);local where=ui.right(e.storages.."▪",5)
  return ui.fit(ui.label(e.item),w-15)..count..where,e.count==0 and ui.P.dim or ui.P.fg
end
function S:draw()
  local a=ui.area()
  if self.dirty or X.stale(self.t) then self.dirty=false;X.read(self.t) end
  ui.title("Stock",#self.index.." items · "..ui.num(self.units).." units"..(ui.filterText~="" and " · filter: "..ui.filterText or ""))
  X.header(self.t,1,a.y,a.w)
  ui.text(1,a.y+4,ui.fit("  Item",self.lw-15)..ui.right("Count",9)..ui.right("In",5),ui.P.dim)
  if ui.wide() then self:detail(self.list.cur) end
end
function S:selected(i) local k=self.index[i or self.list.cur];return k and self.totals[k] end
-- Count, free against reserved, the trend and where it is; from stats when
-- it runs, else the count and where from the warehouse.
function S:lines(e)
  local P=ui.P;local lines={{ui.label(e.item),P.accent},{ui.id(e.item),P.dim},""}
  local st=X.stats();local d=st and ui.try(st.item,e.item)
  local function add(k,v,fg) lines[#lines+1]={ui.fit(k,10)..ui.right(v,10),fg} end
  add("Count",ui.num(d and d.count or e.count))
  if d then
    add("Free",ui.num(d.free));add("Reserved",ui.num(d.reserved),d.reserved>0 and P.warn or nil)
    lines[#lines+1]="";lines[#lines+1]={"Per hour",P.dim}
    add("  last 1 h",X.rate(d.perHour1),d.perHour1<0 and P.warn or nil);add("  avg 6 h",X.rate(d.perHour6),d.perHour6<0 and P.warn or nil)
  end
  local where=d and d.where or wh.find(e.item)
  lines[#lines+1]="";lines[#lines+1]={"Where ("..#where..")",P.dim}
  for _,f in ipairs(where) do lines[#lines+1]="  "..ui.fit(f.storage,18)..ui.right(ui.num(f.count),8) end
  if #where==0 then lines[#lines+1]={"  nowhere: count is zero",P.dim} end
  return lines
end
function S:detail(i)
  if not ui.wide() then return end
  local a=ui.area();local e=self:selected(i)
  ui.pane(e and self:lines(e) or {},self.lw+1,a.y+4,a.w-self.lw,a.h-4)
end
function S:filtered() self:rebuild();self.list:set(1);self:draw() end
-- A warehouse change re-reads the stats; drawn now when Stock is on top,
-- else when it is shown again.
function S:signal(name,what)
  if name~="warehouse" then return end
  if what=="changed" then self.dirty=true end
  if wh.revision()~=self.rev then self:rebuild();self.list:refresh();self.dirty=true end
  if self.dirty and ui.current()==self and not ui.inModal() then self:draw() end
end
function S:refresh() self:rebuild();self.list:refresh();self.dirty=true;self:draw() end
function S:close() package.loaded["mes_ui.stockstats"]=nil end
function S:key(char,code)
  local keys=ui.keys
  if code==keys.r and require("keyboard").isShiftDown() then
    local ids=ui.try(wh.scan);if ids then ui.ok("Rescanning: "..#ids.." read jobs queued") end;return true
  end
  if code==keys.o then ui.push("mes_ui.stockstats");return true end
  if code==keys.t then X.thresholds();return true end
  if code==keys.i then local e=self:selected();if e then ui.show(ui.label(e.item),self:lines(e)) end;return true end
  local v=code==keys.e and "fetch" or code==keys.w and "where" or code==keys.s and "scan" or code==keys.c and "craft"
  if v then self:action(v);return true end
end
-- Enter is fetch, as E (export) and Enter are in the inventory program.
function S:actions(i) self:action("fetch",i) end
function S:action(v,i)
  local e=self:selected(i);if not e then return end
  if v=="craft" then require("mes_ui.choice").craft(ui.id(e.item))
  elseif v=="fetch" then
    local function count(to,io)
      ui.prompt("Fetch "..ui.label(e.item),"How many? (have "..ui.num(e.count)..")",math.min(e.count,64),function(n)
        if not io then local id=ui.try(wh.fetch,e.item,n,to);if id then ui.ok("Job #"..tostring(id)..": fetching "..n.." "..ui.label(e.item).." → "..to) end;return end
        -- An export chest takes what fits; the reason says why it is short.
        local ok,id,why=pcall(io.fetch,e.item,n,to)
        if not ok then ui.fail((tostring(id):gsub("^[^:]+:%d+: ","")))
        elseif not id then ui.fail(tostring(why or "nothing fetched"))
        elseif why then ui.notify("Job #"..tostring(id)..": "..ui.label(e.item).." → "..to.." · "..why)
        else ui.ok("Job #"..tostring(id)..": fetching "..n.." "..ui.label(e.item).." → "..to) end
      end,{integer=true,min=1})
    end
    local function other() require("mes_ui.flows").pickStorage("Fetch "..ui.label(e.item).." to…",{},count) end
    -- Export chests first; with exactly one it is preselected.
    local okio,io=pcall(require,"iochest");local rows={}
    if okio then for _,r in ipairs(ui.try(io.list) or {}) do if r.role=="export" then
      rows[#rows+1]={text=ui.fit(r.name,16)..ui.fit(r.sensor or "no sensor",14)..(r.reason or ""),value=r.name,fg=r.reason and ui.P.warn or nil}
    end end end
    if #rows==0 then other();return end
    local one=#rows==1
    table.insert(rows,1,{text="Export chests",fg=ui.P.accent,locked=true})
    rows[#rows+1]={text="Another storage…",value=false}
    ui.pick("Fetch "..ui.label(e.item).." to…",rows,function(to) if to then count(to,io) else other() end end,{nofilter=true,at=not one and 1 or nil})
  elseif v=="where" then
    local list={};for _,f in ipairs(wh.find(e.item)) do list[#list+1]={text=ui.fit(f.storage,24)..ui.right(ui.num(f.count),8),locked=true} end
    if #list==0 then list[1]={text="nowhere: count is zero",locked=true} end
    ui.pick(ui.label(e.item).." · "..ui.num(e.count),list,function() end,{nofilter=true,note="⌫ close"})
  elseif v=="scan" then
    local names={};for _,f in ipairs(wh.find(e.item)) do names[#names+1]=f.storage end
    if #names>0 then local ids=ui.try(wh.scan,names);if ids then ui.ok(#ids.." read jobs queued") end else ui.notify("nothing to rescan: count is zero") end
  end
end
return S
