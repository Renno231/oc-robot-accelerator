-- Stock: warehouse totals, filter as you type, locations and fetch.
local ui=require("mes_ui.core");local wh=require("warehouse")
local S={filterable=true,hints="type to filter · Enter actions · R rescan all"}

function S:open()
  local a=ui.area();self.index={};self.rev=-1
  self.lw=ui.wide() and math.floor(a.w*0.58) or a.w
  self.list=ui.list(self.menu,{name="i",x=1,y=a.y+1,w=self.lw,h=a.h-1,
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
  ui.title("Stock",#self.index.." items · "..ui.num(self.units).." units"..(ui.filterText~="" and " · filter: "..ui.filterText or ""))
  ui.text(1,a.y,ui.fit("  Item",self.lw-15)..ui.right("Count",9)..ui.right("In",5),ui.P.dim)
  if ui.wide() then self:detail(self.list.cur) end
end
function S:selected(i) local k=self.index[i or self.list.cur];return k and self.totals[k] end
function S:detail(i)
  if not ui.wide() then return end
  local a=ui.area();local e=self:selected(i);local lines={}
  if e then
    lines[1]={ui.label(e.item),ui.P.accent};lines[2]={ui.id(e.item),ui.P.dim};lines[3]=""
    lines[4]="Total "..ui.num(e.count).." in "..e.storages.." storage"..(e.storages==1 and "" or "s");lines[5]=""
    for _,f in ipairs(wh.find(e.item)) do lines[#lines+1]=ui.fit(f.storage,18)..ui.right(ui.num(f.count),8) end
  end
  ui.pane(lines,self.lw+1,a.y,a.w-self.lw,a.h)
end
function S:filtered() self:rebuild();self.list:set(1);self:draw() end
function S:signal(name)
  if name=="warehouse" and wh.revision()~=self.rev then self:rebuild();self.list:refresh();self:draw() end
end
function S:key(char)
  if (char==82) then -- R
    local ids=ui.try(wh.scan);if ids then ui.ok("Rescanning: "..#ids.." read jobs queued") end;return true
  end
end
function S:actions(i)
  local e=self:selected(i);if not e then return end
  local rows={{text="Fetch to a storage…",value="fetch"},{text="Show where it is",value="where"},{text="Rescan its storages",value="scan"}}
  ui.pick(ui.label(e.item),rows,function(v)
    if v=="fetch" then
      require("mes_ui.flows").pickStorage("Fetch "..ui.label(e.item).." to…",{},function(to)
        ui.prompt("Fetch "..ui.label(e.item),"How many? (have "..ui.num(e.count)..")",math.min(e.count,64),function(n)
          local id=ui.try(wh.fetch,e.item,n,to);if id then ui.ok("Job #"..tostring(id)..": fetching "..n.." "..ui.label(e.item).." → "..to) end
        end,{integer=true,min=1})
      end)
    elseif v=="where" then
      local list={};for _,f in ipairs(wh.find(e.item)) do list[#list+1]={text=ui.fit(f.storage,24)..ui.right(ui.num(f.count),8),locked=true} end
      if #list==0 then list[1]={text="nowhere: count is zero",locked=true} end
      ui.pick(ui.label(e.item).." · "..ui.num(e.count),list,function() end,{nofilter=true,note="⌫ close"})
    elseif v=="scan" then
      local names={};for _,f in ipairs(wh.find(e.item)) do names[#names+1]=f.storage end
      if #names>0 then local ids=ui.try(wh.scan,names);if ids then ui.ok(#ids.." read jobs queued") end end
    end
  end,{nofilter=true})
end
return S
