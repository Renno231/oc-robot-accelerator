-- Recipes: import by laying items out in a chest, or browse by item.
local ui=require("mes_ui.core");local wh=require("warehouse")
local S={filterable=true,hints="Enter import or show · type to search items"}
local function mes() return require("mes") end
local function recipes() return require("recipes") end

function S:open()
  local a=ui.area();self.rows={}
  self.list=ui.list(self.menu,{name="r",x=1,y=a.y,w=a.w,h=a.h,
    count=function() return #self.rows end,
    row=function(i) local r=self.rows[i];return r.text,r.fg,r.heading end,
    activate=function(i) self:activate(self.rows[i]) end})
  self:rebuild();self.list:refresh()
end
function S:rebuild()
  local rows,P=self.rows,ui.P;for k=#rows,1,-1 do rows[k]=nil end
  rows[1]={text="+ Import a recipe from a chest…",fg=P.good,import=true}
  rows[2]={text="",heading=true}
  rows[3]={text=ui.filterText=="" and "Items with recipes  (type to search)" or ("Items matching \""..ui.filterText.."\""),fg=P.accent,heading=true}
  for _,id in ipairs(ui.try(mes().search,ui.filterText,math.max(24,ui.area().h*2)) or {}) do
    rows[#rows+1]={text="  "..ui.fit(ui.label(id),32)..id,item=id}
  end
end
function S:draw() ui.title("Recipes","processing and crafting recipes") end
function S:filtered() self:rebuild();self.list:set(self.rows[4] and 4 or 1) end
function S:activate(r)
  if not r then return end
  if r.import then return self:import() end
  if r.item then
    local list=ui.try(recipes().list,r.item) or {}
    if #list==0 then ui.notify("no recipes for "..ui.label(r.item));return end
    local rows={}
    for k,x in ipairs(list) do
      local ins={};for _,i in ipairs(x.inputs) do ins[#ins+1]=ui.label(i.item).."×"..i.qty end
      rows[#rows+1]={text=ui.fit((x.kind=="processing" and x.machineType or "crafting").." · "..x.source,22)..table.concat(ins,", "),value=k}
    end
    ui.pick(ui.label(r.item).." · "..#list.." recipe"..(#list==1 and "" or "s"),rows,function(k)
      ui.push("mes_ui.recipe_edit",{draft=list[k],item=r.item,index=k,readonly=true})
    end,{nofilter=true})
  end
end

-- Source (transposer side or a drone-read storage), kind, type, then edit.
function S:import()
  local rows={}
  for _,t in ipairs(ui.try(recipes().transposerInventories) or {}) do
    rows[#rows+1]={text="Transposer "..t.address:sub(1,8).."… "..ui.fit(ui.sides[t.side],6)..t.size.." slots, "..t.used.." used",value={transposer=t.address,side=t.side}}
  end
  rows[#rows+1]={text="A mapped storage (a drone reads it)…",value={storage=true},fg=ui.P.accent}
  ui.pick("Import · where are the items laid out?",rows,function(src)
    if src.storage then
      require("mes_ui.flows").pickStorage("Import · read which storage?",{},function(s) self:readStorage(s) end)
    else
      local slots,size=ui.try(recipes().readSlots,src);if slots then self:kind(slots,size) end
    end
  end,{nofilter=true})
end
function S:readStorage(storage)
  local ids=ui.try(wh.scan,storage);if not ids then return end
  self.waiting={id=ids[1],storage=storage}
  ui.notify("Reading "..storage.." by drone (job #"..tostring(ids[1])..")…",ui.P.accent)
end
function S:signal(name,id,state)
  local w=self.waiting
  if name=="logistics" and w and id==w.id then
    self.waiting=nil
    local s=require("logistics").status(id);local step=s and s.steps and s.steps[1]
    if not step or not step.listing then ui.fail("could not read "..w.storage..": "..tostring(s and (s.reason or s.state)));return end
    local slots,size=ui.try(recipes().slotsFromListing,step.listing,step.size);if slots then self:kind(slots,size) end
  end
end
function S:kind(slots,size)
  local used=0;for _ in pairs(slots) do used=used+1 end
  if used==0 then ui.fail("that inventory is empty");return end
  ui.pick("Import · "..used.." stacks found · what kind?",{
    {text="Processing: inputs first, product in the last 4 slots",value="processing"},
    {text="Crafting: 3×3 in the left columns, product in slot 14",value="crafting"}},function(kind)
    if kind=="crafting" then
      local d=ui.try(recipes().recipeFromSlots,"crafting",slots,size);if d then ui.push("mes_ui.recipe_edit",{draft=d,size=size,slots=slots}) end
    else
      local rows={};for n,def in pairs(mes().types()) do rows[#rows+1]={text=ui.fit(n,14).." in→"..table.concat(def.inputs,","),value=n} end
      rows[#rows+1]={text="+ New machine type…",value=false,fg=ui.P.accent}
      local function go(t) local d=ui.try(recipes().recipeFromSlots,"processing",slots,size,t);if d then ui.push("mes_ui.recipe_edit",{draft=d,size=size,slots=slots}) end end
      ui.pick("Import · which machine type makes it?",rows,function(t)
        if t then go(t) else require("mes_ui.flows").editType(nil,nil,go) end
      end)
    end
  end,{nofilter=true})
end
return S
