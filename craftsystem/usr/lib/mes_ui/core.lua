-- Production UI shell. qmenu owns every focusable thing (rows, cells, fields,
-- faces); the GPU is used directly only for frames and static text.
-- Screens are modules loaded on entry and unloaded when their tab is left,
-- and lists format only their visible rows: nothing copies whole datasets
-- per redraw.
local component=require("component");local event=require("event");local computer=require("computer")
local unicode=require("unicode");local keyboard=require("keyboard");local keys=keyboard.keys
local qmenu=require("qmenu")

local ui={tabs={"craft","stock","setup","recipes","jobs","fleet","alerts","manage"},
  titles={craft="Craft",stock="Stock",setup="Setup",recipes="Recipes",jobs="Jobs",fleet="Fleet",alerts="Alerts",manage="Manage"},badges={},keys=keys}
local P={bg=0x10161C,bar=0x1D2731,box=0x26323E,fg=0xD6DDE4,dim=0x6E7C88,accent=0x4FB3E8,
  good=0x7BC96F,warn=0xE6B450,bad=0xE0646E,sel=0x4FB3E8,selFg=0x10161C}
ui.P=P
local gpu,W,H
local stack,modals,tabHits={},{},{}
local message,messageColour,messageUntil
local running,repaintAll,footerDirty,headerDirty,guarded
local status,statusAt="",-math.huge
local termFg,termBg
local ioLast={} -- IO chest name -> {state,reason} last signalled
local alertText,alertHit -- the alert bar's text; its first column on the tab bar
-- F starts search: typed characters edit the filter until Enter.
ui.filterText="";ui.searching=false

---------------------------------------------------------------- text helpers
local len,sub=unicode.len,unicode.sub
function ui.fit(s,w)
  s=tostring(s or "");if w<=0 then return "" end
  local n=len(s)
  if n>w then return w>1 and sub(s,1,w-1).."…" or sub(s,1,w) end
  return n<w and s..string.rep(" ",w-n) or s
end
function ui.right(s,w) s=tostring(s or "");local n=len(s);if n>=w then return ui.fit(s,w) end;return string.rep(" ",w-n)..s end
function ui.num(n)
  local s=tostring(math.floor(n or 0));local neg=s:sub(1,1)=="-";if neg then s=s:sub(2) end
  s=s:reverse():gsub("(%d%d%d)","%1,"):reverse():gsub("^,","");return (neg and "-" or "")..s
end
-- Warehouse items are {name,damage,label}; the crafting system uses
-- "mod:name[:damage]" with damage 0 omitted.
function ui.id(i) if type(i)=="string" then return i end;return i.name..((i.damage or 0)~=0 and ":"..i.damage or "") end
function ui.item(id)
  if type(id)=="table" then return id end
  local name,d=id:match("^([^:]+:[^:]+):(%d+)$");if name then return {name=name,damage=tonumber(d)} end
  return {name=id,damage=0}
end
-- Bare IDs take the in-game label of a stocked item when there is one, else
-- a readable form of the name: "minecraft:brick_block" -> "Brick Block".
local labels,labelsRev={},nil
function ui.label(i)
  if type(i)=="table" then if i.label and i.label~="" then return i.label end;i=ui.id(i) end
  i=tostring(i)
  local wh=package.loaded.warehouse
  if wh and wh.revision()~=labelsRev then
    labelsRev=wh.revision();for k in pairs(labels) do labels[k]=nil end
    for _,e in ipairs(wh.totals()) do if e.item.label then labels[ui.id(e.item)]=e.item.label end end
  end
  if labels[i] then return labels[i] end
  local name,d=i:match("^[^:]+:([^:]+):?(%d*)$")
  if not name then return i end
  name=name:gsub("_"," "):gsub("(%a)(%w*)",function(a,b) return a:upper()..b end)
  return d~="" and name.." ("..d..")" or name
end
ui.sides={[0]="down","up","north","south","west","east"}
ui.sideGlyph={[0]="▼","▲","N","S","W","E"}
function ui.bar(done,total,w)
  if w<=0 then return "" end
  local k=total>0 and math.floor(math.min(1,done/total)*w+0.5) or 0
  return string.rep("█",k)..string.rep("░",w-k)
end

---------------------------------------------------------------- drawing
function ui.text(x,y,s,fg,bg) gpu.setForeground(fg or P.fg);gpu.setBackground(bg or P.bg);gpu.set(x,y,s) end
function ui.fill(x,y,w,h,bg) if w>0 and h>0 then gpu.setBackground(bg or P.bg);gpu.fill(x,y,w,h," ") end end
function ui.size() return W,H end
function ui.wide() return W>=100 end
-- Content area below the tab bar and the screen's title line.
function ui.area() return {x=1,y=3,w=W,h=H-3} end
function ui.title(left,right)
  ui.fill(1,2,W,1,P.bg);ui.text(2,2,ui.fit(left,W-2),P.accent)
  if right and right~="" then local r=ui.fit(right,math.floor(W/2));ui.text(W-len(r),2,r,P.dim) end
end
function ui.style(o,fg,bg)
  bg=bg or o._uiBase
  -- Locked rows (headings, details) keep their colour; qmenu draws them
  -- with the locked style.
  if o._uiFg~=fg or o._uiBg~=bg then o._uiFg,o._uiBg=fg,bg;o:setStyle("normal",fg,bg);o:setStyle("locked",fg,bg) end
end
function ui.decorate(o,bg)
  bg=bg or P.bg;o._uiBase=bg;o._uiFg,o._uiBg=nil,bg
  o:setStyle("normal",P.fg,bg);o:setStyle("selected",P.selFg,P.sel);o:setStyle("locked",P.dim,bg)
  o:setStyle("activated",P.selFg,P.good)
  return o
end
-- Static detail pane to the right of a list on wide screens.
function ui.pane(lines,x,y,w,h)
  ui.fill(x,y,w,h,P.bg);gpu.setBackground(P.bar);gpu.fill(x,y,1,h,"│");gpu.setBackground(P.bg)
  for k=1,math.min(#lines,h) do local l=lines[k]
    if type(l)=="table" then ui.text(x+2,y+k-1,ui.fit(l[1],w-3),l[2] or P.fg) else ui.text(x+2,y+k-1,ui.fit(l,w-3),P.fg) end
  end
end

---------------------------------------------------------------- list widget
-- h fixed row options whose text is rewritten on scroll: scrolling allocates
-- only the visible rows' strings. spec: name,x,y,w,h,count(),row(i,w)->
-- text,fg,locked; optional prepare(top,h), activate(i), moved(i), key(code,i).
local List={};List.__index=List
function ui.list(menu,spec)
  local L=setmetatable({menu=menu,spec=spec,top=1,cur=1,opts={}},List)
  local blank=string.rep(" ",spec.w)
  for k=1,spec.h do
    local o=ui.decorate(menu:addOption(spec.name..k,spec.x,spec.y+k-1,blank),spec.bg)
    o:bind(keys.up,function() L:move(-1) end);o:bind(keys.down,function() L:move(1) end)
    o:bind(keys.pageUp,function() L:move(-spec.h) end);o:bind(keys.pageDown,function() L:move(spec.h) end)
    o:bind(keys.left,function() L:move(-spec.h) end);o:bind(keys.right,function() L:move(spec.h) end)
    o:bind(keys.home,function() L:set(1) end);o:bind(keys["end"],function() L:set(math.huge) end)
    o:bind(keys.enter,function() local n=spec.count();if n>0 and spec.activate and not L.lockedRow then spec.activate(L.cur) end end)
    o._uiTouch=function() L:set(L.top+k-1) end
    L.opts[k]=o
  end
  return L
end
function List:move(d)
  local n=self.spec.count();if n==0 then return end
  local c=self.cur+d;local step=d<0 and -1 or 1
  -- Skip locked (heading) rows in the direction of travel when possible.
  while c>=1 and c<=n and self.locked and self.locked[c] do c=c+step end
  if c<1 or c>n then c=math.max(1,math.min(n,self.cur+d));if self.locked and self.locked[c] then return end end
  self:set(c)
end
function List:set(c)
  local n=self.spec.count();c=math.max(1,math.min(n,c));self.cur=c
  local h=self.spec.h
  if c<self.top then self.top=c elseif c>=self.top+h then self.top=c-h+1 end
  self:refresh();if self.spec.moved and n>0 then self.spec.moved(c) end
end
function List:refresh()
  local spec=self.spec;local n=spec.count();local h,w=spec.h,spec.w
  if self.cur>n then self.cur=math.max(1,n) end
  if self.top>math.max(1,n-h+1) then self.top=math.max(1,n-h+1) end
  if self.cur<self.top then self.top=self.cur end
  if spec.prepare then spec.prepare(self.top,h) end
  self.locked=self.locked or {}
  for k=1,h do
    local i=self.top+k-1;local o=self.opts[k]
    if i<=n then
      local t,fg,locked=spec.row(i,w);o:text(ui.fit(t,w));ui.style(o,fg or P.fg)
      self.locked[i]=locked or nil
      if o:lock()~=(locked==true and i~=self.cur) then o:lock(locked==true and i~=self.cur) end
    else
      o:text(string.rep(" ",w));if not o:lock() then o:lock(true) end
    end
  end
  self.lockedRow=self.locked[self.cur]
  if n>0 then self.menu:setSelected(self.opts[self.cur-self.top+1]) else self.menu:setSelected(self.opts[1]) end
end
function List:select(i) self:set(i) end
-- Move to the first row that is not a heading.
function List:first()
  local n=self.spec.count()
  for i=1,n do local _,_,locked=self.spec.row(i,self.spec.w);if not locked then self:set(i);return end end
end

---------------------------------------------------------------- modals
-- A modal owns a separate qmenu Menu; keys route to the top modal only.
local function frame(m)
  local x,y,w,h=m.x,m.y,m.w,m.h
  ui.fill(x,y,w,h,P.box)
  gpu.setForeground(P.accent);gpu.setBackground(P.box)
  gpu.set(x,y,"┌"..string.rep("─",w-2).."┐");gpu.set(x,y+h-1,"└"..string.rep("─",w-2).."┘")
  gpu.fill(x,y+1,1,h-2,"│");gpu.fill(x+w-1,y+1,1,h-2,"│")
  ui.text(x+2,y," "..ui.fit(m.title,math.min(len(m.title),w-6)).." ",P.fg,P.box)
  if m.paint then m.paint(m) end
end
function ui.modal(spec)
  local m={menu=qmenu.create(),title=spec.title or ""}
  m.menu._onError=ui.notify
  m.w=math.min(W-2,spec.w or 50);m.h=math.min(H-2,spec.h or 12)
  m.x=math.floor((W-m.w)/2)+1;m.y=math.floor((H-m.h)/2)+1
  m.ix,m.iy,m.iw,m.ih=m.x+2,m.y+1,m.w-4,m.h-2
  modals[#modals+1]=m
  spec.build(m)
  frame(m);m.menu:draw(true)
  return m
end
function ui.close(m)
  for k=#modals,1,-1 do if modals[k]==m then table.remove(modals,k) end end
  repaintAll=true
end
function ui.inModal() return #modals>0 end
local function modalNote(m,text,colour)
  ui.fill(m.ix,m.y+m.h-2,m.iw,1,P.box);if text then ui.text(m.ix,m.y+m.h-2,ui.fit(text,m.iw),colour or P.dim,P.box) end
end

-- Pick one row. rows: array of {text,value,fg,locked}. Typing filters.
-- opts.at: the row to start on, locked or not (default: the first selectable).
function ui.pick(title,rows,done,opts)
  opts=opts or {}
  local index,filter={},""
  local function rebuild()
    for k=#index,1,-1 do index[k]=nil end
    local f=filter:lower()
    for k,r in ipairs(rows) do if f=="" or r.keep or r.text:lower():find(f,1,true) then index[#index+1]=k end end
  end
  rebuild()
  local h=math.min(H-6,math.max(4,#rows+(opts.note and 1 or 0)))
  local w=opts.w or 50
  for _,r in ipairs(rows) do w=math.max(w,math.min(W-6,len(r.text)+6)) end
  return ui.modal({title=title,w=w,h=h+3+(opts.note and 1 or 0),build=function(m)
    local L
    L=ui.list(m.menu,{name="p",x=m.ix,y=m.iy,w=m.iw,h=m.ih-1,bg=P.box,count=function() return #index end,
      row=function(i) local r=rows[index[i]];return r.text,r.fg,r.locked end,
      activate=function(i) local r=rows[index[i]];if r.locked then return end;ui.close(m);done(r.value,r) end})
    m.paint=function() modalNote(m,filter~="" and ("filter: "..filter.."▏") or opts.note or (opts.nofilter and "Enter picks · ⌫ back" or "type to filter · ⌫ back")) end
    m.key=function(char,code)
      if code==keys.back then
        if filter=="" then ui.close(m);if opts.cancel then opts.cancel() end;return true end
        filter=sub(filter,1,len(filter)-1)
      elseif char>=32 and char<127 and not opts.nofilter then filter=filter..string.char(char)
      else return false end
      -- With a filter typed, land on the first real match, not a pinned row.
      rebuild();local first=1
      if filter~="" then for i,k in ipairs(index) do if not rows[k].keep and not rows[k].locked then first=i;break end end end
      L:set(first);m.paint(m);return true
    end
    L:refresh()
    -- Start on opts.at, else the first selectable row.
    for i=1,#index do if opts.at and index[i]==opts.at or not opts.at and not rows[index[i]].locked then L:set(i);break end end
  end})
end

-- Several of rows; space toggles, Enter confirms. chosen: set of values.
function ui.checklist(title,rows,chosen,done)
  local L
  return ui.modal({title=title,w=math.max(40,math.min(W-6,60)),h=math.min(H-4,#rows+4),build=function(m)
    L=ui.list(m.menu,{name="c",x=m.ix,y=m.iy,w=m.iw,h=m.ih-1,bg=P.box,count=function() return #rows end,
      row=function(i) local r=rows[i];return (chosen[r.value] and "[x] " or "[ ] ")..r.text,chosen[r.value] and P.good or P.fg end,
      activate=function() ui.close(m);done(chosen) end})
    m.paint=function() modalNote(m,"space toggles · Enter confirms · ⌫ cancel") end
    m.key=function(char,code)
      if code==keys.back then ui.close(m);return true end
      if char==32 then local r=rows[L.cur];chosen[r.value]=not chosen[r.value] or nil;L:refresh();return true end
    end
    L:refresh()
  end})
end

-- One-line text entry, edited in place; opts.number, opts.integer, opts.min,
-- opts.optional (blank returns false), opts.check(value)->ok,err.
function ui.prompt(title,label,initial,done,opts)
  opts=opts or {}
  local value=initial~=nil and tostring(initial) or ""
  -- The prefill is a suggestion: the first typed character replaces it.
  local fresh=value~=""
  local field
  return ui.modal({title=title,w=math.min(W-4,math.max(40,len(label)+24)),h=6,build=function(m)
    ui.text(m.ix,m.iy,ui.fit(label,m.iw),P.dim,P.box)
    field=ui.decorate(m.menu:addOption("f",m.ix,m.iy+1,ui.fit(value.."▏",m.iw)),P.bg)
    local function show() field:text(ui.fit(value.."▏",m.iw)) end
    m.paint=function() ui.text(m.ix,m.iy,ui.fit(label,m.iw),P.dim,P.box);modalNote(m,"Enter accepts · ⌫ on empty cancels") end
    m.key=function(char,code)
      if code==keys.enter then
        local v=value
        if v=="" and opts.optional then ui.close(m);done(false);return true end
        if opts.number or opts.integer then
          v=tonumber(v)
          if not v or (opts.integer and v%1~=0) or (opts.min and v<opts.min) then modalNote(m,"enter a "..(opts.integer and "whole " or "").."number"..(opts.min and " ≥ "..opts.min or ""),P.bad);return true end
        elseif v=="" then modalNote(m,"required",P.bad);return true end
        if opts.check then local ok,err=opts.check(v);if not ok then modalNote(m,err,P.bad);return true end end
        ui.close(m);done(v);return true
      elseif code==keys.back then
        if value=="" then ui.close(m);if opts.cancel then opts.cancel() end;return true end
        value=fresh and "" or sub(value,1,len(value)-1);fresh=false;show();return true
      elseif char>=32 and char<127 then if fresh then value="" end;fresh=false;value=value..string.char(char);show();return true end
      return true
    end
  end})
end

function ui.confirm(title,question,done)
  -- No comes first so a stray Enter never confirms.
  return ui.pick(title,{{text=question,locked=true},{text="  No",value=false},{text="  Yes",value=true,fg=P.warn}},function(v) if v then done() end end,{nofilter=true})
end

-- Locked rows ({text,fg} or text) in a closable box.
function ui.show(title,lines)
  local rows={};for _,l in ipairs(lines) do rows[#rows+1]={text=type(l)=="table" and l[1] or l,fg=type(l)=="table" and l[2] or nil,locked=true} end
  ui.pick(title,rows,function() end,{nofilter=true,note="⌫ close"})
end

-- A form: rows of label/value; Enter edits a row. fields[k]={label,show=fn,
-- edit=fn(refresh)}; the final row runs save(close). w: width, default 64.
function ui.form(title,fields,saveText,save,w)
  local L
  local labelW=0;for _,f in ipairs(fields) do labelW=math.max(labelW,len(f.label)) end
  return ui.modal({title=title,w=math.min(W-4,w or 64),h=math.min(H-2,#fields+5),build=function(m)
    L=ui.list(m.menu,{name="r",x=m.ix,y=m.iy,w=m.iw,h=m.ih-1,bg=P.box,count=function() return #fields+2 end,
      row=function(i)
        if i==#fields+1 then return "",nil,true end
        if i==#fields+2 then return "▶ "..saveText,P.good end
        local f=fields[i];return ui.fit(f.label,labelW).."  "..tostring(f.show()),f.colour and f.colour() or P.fg
      end,
      activate=function(i)
        if i==#fields+2 then save(function() ui.close(m) end,function() L:refresh() end)
        elseif fields[i] then fields[i].edit(function() L:refresh();m.menu:draw() end) end
      end})
    m.paint=function() modalNote(m,"Enter edits · ⌫ cancels") end
    m.key=function(_,code) if code==keys.back then ui.close(m);return true end end
    L:refresh()
  end})
end

---------------------------------------------------------------- messages
function ui.notify(text,colour)
  message=tostring(text);messageColour=colour or P.warn;messageUntil=computer.uptime()+5;footerDirty=true
end
function ui.ok(text) ui.notify(text,P.good) end
function ui.fail(text) ui.notify(text,P.bad) end
-- Call fn; report thrown errors and nil,err returns. Returns fn's values.
function ui.try(fn,...)
  local r=table.pack(pcall(fn,...))
  if not r[1] then ui.fail(tostring(r[2]):gsub("^[^:]+:%d+: ",""));return nil end
  if r[2]==nil and r[3] then ui.fail(r[3]);return nil end
  return table.unpack(r,2,r.n)
end
-- Show a status line immediately, before a blocking call.
function ui.busy(text) ui.notify(text,P.accent);ui.flush() end

---------------------------------------------------------------- header/footer
-- A count after a tab's title, e.g. "Fleet (2)"; 0 or nil hides it.
function ui.badge(name,n) n=(n or 0)>0 and n or nil;if ui.badges[name]~=n then ui.badges[name]=n;headerDirty=true end end
-- Announcing drones, robots and sensors: read at start and on an announce,
-- never polled; sets the Fleet badge. Robots only once mes has pendingRobots.
function ui.newHardware()
  local ok,lg=pcall(require,"logistics");local d=ok and lg.pending() or {};local s=ok and lg.pending("sensor") or {}
  local okm,m=pcall(require,"mes");local r=okm and m.pendingRobots and ui.try(m.pendingRobots) or {}
  ui.badge("fleet",#d+#r+#s);return d,r,s
end
function ui.setStatus(text) if text~=status then status=text;headerDirty=true end end
-- Alerts (mes_alerts): kind and subject in plain words. The alert bar is
-- the count and the newest active one at the right of the tab bar, read at
-- start and on each "alert" signal; with none it draws nothing.
ui.alertKinds={runFailed="Run failed",droneLost="Drone lost",droneHeld="Drone held too long",stockFull="Stock full",
  machineStuck="Machine stuck",importBlocked="Import blocked",exportFull="Export chest full"}
function ui.alertSubject(r)
  local k,key=r.kind,tostring(r.key)
  if k=="runFailed" then return "run "..key elseif k=="stockFull" then return "stock" end
  local m,n=key:match("^(.*):(%d+)$");if k=="machineStuck" and m then return m..", load "..n end
  return key
end
function ui.readAlerts()
  local ok,al=pcall(require,"mes_alerts");local n,new=0
  if ok then for _,r in ipairs(ui.try(al.list,"active") or {}) do n=n+1;if not new or r.id>new.id then new=r end end end
  alertText=new and "▲ "..n.." alert"..(n==1 and "" or "s").." · newest: "..(ui.alertKinds[new.kind] or new.kind).." · "..ui.alertSubject(new) or nil
  headerDirty=true
end
local function header()
  ui.fill(1,1,W,1,P.bar);local x=2
  ui.text(x,1,"◆ MES",P.accent,P.bar);x=x+7
  local current=stack[1] and stack[1].tab
  for k,name in ipairs(ui.tabs) do
    local t=" "..ui.titles[name]..(ui.badges[name] and " ("..ui.badges[name]..")" or "").." "
    if name==current then ui.text(x,1,t,P.selFg,P.sel) else ui.text(x,1,t,P.fg,P.bar) end
    tabHits[k]={x,x+len(t)-1,name};x=x+len(t)+1
  end
  alertHit=nil
  if alertText and W-x>8 then
    local a=" "..ui.fit(alertText,math.min(len(alertText),W-x-4)).." ";alertHit=W-len(a)+1;ui.text(alertHit,1,a,P.selFg,P.bad)
  end
  local e=alertHit and alertHit-1 or W
  local s=ui.fit(status,math.max(0,e-x-2));ui.text(e-len(s),1,s,P.dim,P.bar)
  headerDirty=false
end
local function footer()
  ui.fill(1,H,W,1,P.bar)
  local top=stack[#stack]
  local hint=modals[1] and "" or (top and top.hints or "")
  if message then ui.text(2,H,ui.fit(message,W-2),messageColour,P.bar)
  elseif ui.searching then ui.text(2,H,ui.fit("search: "..ui.filterText.."▏   Enter done · ⌫ erase · ↑↓ list",W-2),P.accent,P.bar)
  else
    local r="H help · Tab next tab · ⌫ back · Q quit";local room=W-2-len(r)-2
    ui.text(2,H,ui.fit(hint,math.max(0,room)),P.dim,P.bar);if room>0 then ui.text(W-len(r),H,r,P.dim,P.bar) end
  end
  footerDirty=false
end

---------------------------------------------------------------- screens
local function current() return stack[#stack] end
local function paint()
  ui.fill(1,1,W,H,P.bg);header()
  local s=current()
  if s then if s.draw then s:draw() end;s.menu:draw(true) end
  for _,m in ipairs(modals) do frame(m);m.menu:draw(true) end
  footer();repaintAll=false
end
local function open(modname,arg)
  local mod=require(modname)
  local s=setmetatable({mod=modname,tab=stack[1] and stack[1].tab or arg and arg.tab},{__index=mod})
  s.menu=qmenu.create();s.menu._onError=ui.notify
  stack[#stack+1]=s;ui.filterText="";ui.searching=false
  ui.fill(1,2,W,H-2,P.bg)
  s:open(arg);repaintAll=true
  return s
end
-- Push a sub-screen in the current tab.
function ui.push(modname,arg) return open(modname,arg) end
function ui.pop()
  local s=table.remove(stack);if s and s.close then s:close() end
  if #stack==0 then running=false end
  ui.filterText=current() and current().filter or "";ui.searching=false;repaintAll=true
end
-- Replace the top screen (e.g. plan preview -> its run view).
function ui.replace(modname,arg) local s=table.remove(stack);if s and s.close then s:close() end;return open(modname,arg) end
function ui.switch(name)
  for k=#modals,1,-1 do modals[k]=nil end
  local loaded={}
  while #stack>0 do local s=table.remove(stack);if s.close then s:close() end;loaded[s.mod]=true end
  -- Leaving a tab releases its code; the next visit reloads it.
  for modname in pairs(loaded) do package.loaded[modname]=nil end
  stack[1]=nil;local s=open("mes_ui."..name,{tab=name});s.tab=name;headerDirty=true
end
function ui.current() return current() end

---------------------------------------------------------------- events
local function hit(menu,x,y)
  for _,o in pairs(menu._options) do
    if o._y==y and x>=o._x and x<o._x+len(o._text) then return o end
  end
end
local function touch(x,y)
  local m=modals[#modals]
  if not m and y==1 and alertHit and x>=alertHit then if stack[1].tab~="alerts" then ui.switch("alerts") end;return end
  if not m and y==1 then for _,t in ipairs(tabHits) do if x>=t[1] and x<=t[2] then ui.switch(t[3]);return end end;return end
  local menu=m and m.menu or current().menu
  local o=hit(menu,x,y)
  if not o then
    if m and (x<m.x or x>=m.x+m.w or y<m.y or y>=m.y+m.h) then ui.close(m) end
    return
  end
  if o:lock() then return end
  if menu:getSelected()==o then menu:handleEvent(keys.enter);return end
  if o._uiTouch then o._uiTouch() else menu:setSelected(o) end
end
-- Keys every screen shares; a screen's key() runs first and may claim any.
local global={
  {"Tab / Shift+Tab","next / previous tab"},{"↑ ↓  PgUp PgDn  ← →","move · page"},
  {"⌫","back"},{"H","this help"},{"Q  or  Ctrl+Q","quit"}}
function ui.help()
  local s=current();local rows={}
  local function add(k,d,fg) rows[#rows+1]={text=ui.fit(k,22)..(d or ""),fg=fg,locked=true} end
  add(ui.titles[s.tab] or "",nil,P.accent)
  for _,h in ipairs(s.help or {}) do add("  "..h[1],h[2]) end
  if s.filterable then add("  F","search: type, Enter done");add("  Shift+F","clear the search") end
  if s.refresh then add("  R","refresh this view") end
  add("",nil);add("Everywhere",nil,P.accent)
  for _,h in ipairs(global) do add("  "..h[1],h[2]) end
  ui.pick("Keys · "..(ui.titles[s.tab] or ""),rows,function() end,{nofilter=true,note="⌫ close",w=64})
end
local function searchKey(s,char,code)
  if code==keys.back then
    if ui.filterText=="" then ui.searching=false else ui.filterText=sub(ui.filterText,1,len(ui.filterText)-1);s:filtered(ui.filterText) end
  elseif code==keys.enter then ui.searching=false
  elseif code==keys.up or code==keys.down or code==keys.pageUp or code==keys.pageDown then ui.searching=false;s.menu:handleEvent(code)
  elseif char>=32 and char<127 then ui.filterText=ui.filterText..string.char(char);s:filtered(ui.filterText) end
  footerDirty=true
end
local function key(char,code)
  if keyboard.isControlDown() and (code==keys.q or code==keys.c) then running=false;return end
  local m=modals[#modals]
  if m then
    if not (m.key and m.key(char,code)) then m.menu:handleEvent(code) end
    return
  end
  local s=current()
  if ui.searching and code~=keys.tab then return searchKey(s,char,code) end
  if code==keys.tab then
    ui.searching=false
    local cur=stack[1].tab;local n=#ui.tabs
    for k,name in ipairs(ui.tabs) do if name==cur then
      ui.switch(ui.tabs[(k+(keyboard.isShiftDown() and n-2 or 0))%n+1]);return
    end end
  end
  if s.key and s:key(char,code) then return end
  if code==keys.q then ui.quit();return
  elseif code==keys.h then ui.help();return
  elseif code==keys.f and s.filterable then
    if keyboard.isShiftDown() then ui.filterText="";s:filtered("") else ui.searching=true end
    footerDirty=true;return
  elseif code==keys.r and s.refresh then s:refresh();ui.ok("Refreshed");return end
  if code==keys.back then
    if s.filterable and ui.filterText~="" then ui.filterText=sub(ui.filterText,1,len(ui.filterText)-1);s:filtered(ui.filterText);return end
    if #stack>1 then ui.pop() end;return
  end
  s.menu:handleEvent(code)
end
local function signal(name,...)
  for k=#stack,1,-1 do local s=stack[k];if s.signal then s:signal(name,...) end end
  for _,m in ipairs(modals) do if m.signal then m.signal(name,...) end end
  if ui.statusSource and computer.uptime()-statusAt>=1 then statusAt=computer.uptime();ui.setStatus(ui.statusSource()) end
end
local handle
-- A failing screen or callback reports in the footer; the UI keeps running.
function guarded(e)
  local ok,err=xpcall(handle,debug.traceback,e)
  if not ok then
    ui.fail((tostring(err):match("^[^\n]*"):gsub("^[^:]+:%d+: ","")));repaintAll=true
    pcall(function() local f=io.open("/tmp/mes_ui.log","a");f:write(err,"\n");f:close() end)
  end
end
function handle(e)
  local name=e[1]
  if name=="key_down" then key(e[3] or 0,e[4] or 0)
  elseif name=="touch" then touch(math.floor(e[3]),math.floor(e[4]))
  elseif name=="scroll" then local menu=modals[1] and modals[#modals].menu or current().menu
    for _=1,3 do menu:handleEvent((e[5] or 0)>0 and keys.up or keys.down) end
  elseif name=="interrupted" then running=false
  elseif name=="screen_resized" then W,H=gpu.getResolution();repaintAll=true
  elseif name=="warehouse" or name=="logistics" or name=="mes" or name=="logistics_work" then signal(name,table.unpack(e,2))
  elseif name=="alert" then ui.readAlerts();signal(name,table.unpack(e,2))
  elseif name=="logistics_announce" or name=="mes_robot_announce" then
    -- The open Fleet screen re-reads them itself.
    if stack[1].tab~="fleet" then ui.newHardware();ui.notify("New "..(e[3]=="sensor" and "sensor" or name=="mes_robot_announce" and "robot" or "drone").." waiting: register it on Fleet",P.accent) end
    signal(name,table.unpack(e,2))
  elseif name=="io" then
    -- IO chests: one line on a new reason or a change of state, wherever the
    -- user is; never over a line that already says it or one just shown.
    local n,st,why=tostring(e[2]),e[3],e[4];local was=ioLast[n] or {}
    if was[1]~=st or was[2]~=why then ioLast[n]={st,why}
      if why and why~=was[2] then if not (message and message:find(why,1,true)) then ui.notify(n..": "..why) end
      elseif st=="active" and was[1]~="active" then if not message then ui.notify(n..": moving items",P.accent) end
      elseif st~="active" and was[1]=="active" then ui.ok(n..": done"..(why and " · "..why or "")) end
    end
    signal(name,table.unpack(e,2))
  elseif name=="logistics_released" then
    -- The open Fleet screen shows the listing; elsewhere one footer line.
    local n,who=0,tostring(e[2])
    if stack[1].tab~="fleet" and e[3]=="ok" then
      for _,d in ipairs(require("logistics").drones()) do if d.name==e[2] then for _ in pairs(d.cargo or {}) do n=n+1 end end end
      ui.ok(n>0 and who.." holds "..n.." stack"..(n==1 and "" or "s") or who.." is empty")
    elseif stack[1].tab~="fleet" then ui.fail(who..": cargo report timeout") end
    signal(name,table.unpack(e,2))
  elseif name=="station" then
    -- One line wherever the user is; the station was started async.
    local st=e[3];if st=="ready" then ui.ok("Station "..e[2].." ready") elseif st=="failed" then ui.fail("Station "..e[2].." failed: see Setup") elseif st=="removed" then ui.ok("Station "..e[2].." removed") end
    signal(name,table.unpack(e,2))
  end
end
function ui.flush()
  if repaintAll then paint() return end
  if headerDirty then header() end
  local s=current();if s then s.menu:draw() end
  for _,m in ipairs(modals) do m.menu:draw() end
  if footerDirty then footer() end
end
function ui.repaint() repaintAll=true end
function ui.quit() running=false end
local function isOpen(m) for _,x in ipairs(modals) do if x==m then return true end end end
-- Block the caller until modal m closes, handling events meanwhile: lets a
-- synchronous callback (the planner's selectChoice) ask the user. Returns
-- false if the UI is quitting.
function ui.wait(m)
  ui.flush()
  while running and isOpen(m) do
    local e=table.pack(event.pull(message and math.max(0.05,messageUntil-computer.uptime()) or math.huge))
    if e[1] then guarded(e) end
    if message and computer.uptime()>=messageUntil then message=nil;footerDirty=true end
    if running then ui.flush() end
  end
  return running
end
-- Hand the whole screen to another full-screen program (fn) and take it back
-- afterwards. The UI registers no listeners and pulls no events while fn
-- runs; events fn consumes are gone, so the header is re-read and every
-- screen repainted on return. Returns fn's results, or nil,err if it threw.
function ui.suspend(fn,...)
  for k=#modals,1,-1 do modals[k]=nil end
  gpu.setForeground(termFg);gpu.setBackground(termBg);gpu.fill(1,1,W,H," ")
  pcall(function() require("term").setCursor(1,1) end)
  local r=table.pack(xpcall(fn,debug.traceback,...))
  pcall(function() require("term").setCursorBlink(false) end)
  W,H=gpu.getResolution();repaintAll=true
  if ui.statusSource then statusAt=computer.uptime();status=ui.statusSource() end
  ui.readAlerts()
  if not r[1] then
    pcall(function() local f=io.open("/tmp/mes_ui.log","a");f:write(r[2],"\n");f:close() end)
    return nil,(tostring(r[2]):match("^[^\n]*"):gsub("^[^:]+:%d+: ",""))
  end
  return table.unpack(r,2,r.n)
end

function ui.run(opts)
  opts=opts or {}
  gpu=assert(component.gpu,"the production UI needs a GPU");W,H=gpu.getResolution()
  assert(W>=50 and H>=16,"the production UI needs at least 50x16")
  if gpu.getDepth()==1 then
    for k in pairs(P) do P[k]=0xFFFFFF end;P.bg,P.bar,P.box,P.selFg=0,0,0,0
  end
  local fg,bg=gpu.getForeground(),gpu.getBackground();termFg,termBg=fg,bg
  ui.statusSource=opts.status or function()
    local ok,lg=pcall(require,"logistics");if not ok then return "" end
    local idle,total=0,0;for _,d in ipairs(lg.drones()) do total=total+1;if d.state=="idle" then idle=idle+1 end end
    return total>0 and (total.." drones · "..(total-idle).." busy") or "no drones"
  end
  ui.setStatus(ui.statusSource());statusAt=computer.uptime();ui.newHardware();ui.readAlerts()
  running=true;ui.switch(opts.tab or "craft")
  if opts.push then ui.push(opts.push,opts.arg) end
  ui.flush()
  while running do
    local wait=message and math.max(0.05,messageUntil-computer.uptime()) or math.huge
    local e=table.pack(event.pull(wait))
    if e[1] then guarded(e) end
    -- Coalesce bursts (job progress, key repeat) into one draw.
    for _=1,32 do
      if not running then break end
      local more=table.pack(event.pull(0));if not more[1] then break end;guarded(more)
    end
    if message and computer.uptime()>=messageUntil then message=nil;footerDirty=true end
    if running then ui.flush() end
  end
  while #stack>0 do local s=table.remove(stack);if s.close then s:close() end;package.loaded[s.mod]=nil end
  for k=#modals,1,-1 do modals[k]=nil end
  gpu.setForeground(fg);gpu.setBackground(bg);gpu.fill(1,1,W,H," ")
  pcall(function() require("term").setCursor(1,1) end)
end
return ui
