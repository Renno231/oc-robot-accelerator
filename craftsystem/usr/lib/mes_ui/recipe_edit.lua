-- Recipe preview/editor. The scanned chest is drawn as a grid of qmenu
-- options bound to each other by arrow keys; crafting recipes are drawn as
-- a crafting table with an arrow to the product.
local ui=require("mes_ui.core")
local S={hints="arrows move · Enter edit cell · S save · ⌫ back"}
local function mes() return require("mes") end
local GRID={1,2,3,10,11,12,19,20,21}

local function stackOf(id,qty,label) local i=ui.item(id);return {name=i.name,damage=i.damage,size=qty,label=label} end
function S:open(arg)
  local d=arg.draft;self.d=d;self.readonly=arg.readonly;self.item=arg.item;self.index=arg.index
  self.kind=d.kind;self.type=d.machineType;self.ore={}
  -- Cells are the editable truth; saving re-derives the draft through mes.
  self.size=arg.size or 27;self.cells={}
  if arg.slots then for k,s in pairs(arg.slots) do self.cells[k]={name=s.name,damage=s.damage,size=s.size,label=s.label} end
  elseif d.kind=="crafting" then
    for g=1,9 do local id=d.grid and d.grid[g];if id then self.cells[GRID[g]]=stackOf(id,1) end end
    self.cells[14]=stackOf(d.outputs[1].item,d.outputs[1].qty)
  else
    for k,x in ipairs(d.inputs) do self.cells[x.slot or k]=stackOf(x.item,x.qty) end
    for k,x in ipairs(d.outputs) do self.cells[x.slot or self.size-4+k]=stackOf(x.item,x.qty) end
  end
  for _,x in ipairs(d.inputs) do if x.ore and x.slot then self.ore[x.slot]=x.ore end end
  self.dirty=false;self:layout()
end
function S:role(slot)
  if self.kind=="crafting" then
    if slot==14 then return "output" end
    for _,g in ipairs(GRID) do if g==slot then return "input" end end
    return "unused"
  end
  return slot>self.size-4 and "output" or "input"
end
function S:cellText(slot,w)
  local c=self.cells[slot]
  if not c then return ui.fit(self:role(slot)=="unused" and "" or "·",w) end
  local name=self.ore[slot] and ("#"..self.ore[slot]) or ui.label(c.label and c or ui.id(c))
  local q=(c.size or 1)>1 and "×"..c.size or ""
  return ui.fit(ui.fit(name,math.max(1,w-#q-1))..q,w)
end
function S:cellColour(slot)
  local P=ui.P;if not self.cells[slot] then return P.dim end
  local r=self:role(slot);return r=="output" and P.warn or r=="input" and P.accent or P.bad
end
function S:layout()
  local a=ui.area();local W=a.w;local menu=self.menu;local keys=ui.keys
  self.opts={}
  local function cell(slot,x,y,w)
    local o=ui.decorate(menu:addOption("c"..slot,x,y,self:cellText(slot,w)),ui.P.bar)
    ui.style(o,self:cellColour(slot));o._w=w
    o:onSelect(function() self:info(slot) end)
    o:onActivate(function() self:edit(slot) end)
    self.opts[slot]=o;return o
  end
  local function link(a,key,b) if self.opts[a] and self.opts[b] then self.opts[a]:bind(key,"c"..b) end end
  if self.kind=="crafting" then
    local cw=math.max(8,math.min(18,math.floor((W-12)/4)));local x0=3;local y0=a.y+2
    for g,slot in ipairs(GRID) do local r,c=(g-1)//3,(g-1)%3;cell(slot,x0+c*(cw+1),y0+r*2,cw) end
    self.arrowX=x0+3*(cw+1)+1;self.arrowY=y0+2
    cell(14,self.arrowX+5,y0+2,cw)
    for g,slot in ipairs(GRID) do local r,c=(g-1)//3,(g-1)%3
      if c<2 then link(slot,keys.right,GRID[g+1]) else link(slot,keys.right,14) end
      if c>0 then link(slot,keys.left,GRID[g-1]) end
      if r>0 then link(slot,keys.up,GRID[g-3]) end
      if r<2 then link(slot,keys.down,GRID[g+3]) end
    end
    link(14,keys.left,11);self.bottomY=y0+6;self.lastRow={19,20,21,14}
  else
    local cols=9;local rows=math.ceil(self.size/cols)
    local cw=math.max(5,math.min(16,math.floor((W-2)/cols)-1));local y0=a.y+2
    -- Large inventories scroll by being clipped: show the rows that fit.
    local maxRows=math.max(1,a.h-8);self.clipped=rows>maxRows;rows=math.min(rows,maxRows)
    local gap=rows*2-1<=maxRows and 2 or 1
    for k=1,math.min(self.size,rows*cols) do local r,c=(k-1)//cols,(k-1)%cols;cell(k,2+c*(cw+1),y0+r*gap,cw) end
    for k=1,math.min(self.size,rows*cols) do local c=(k-1)%cols
      if c>0 then link(k,keys.left,k-1) end;if c<cols-1 then link(k,keys.right,k+1) end
      link(k,keys.up,k-cols);link(k,keys.down,k+cols)
    end
    self.bottomY=y0+(rows-1)*gap+1;self.lastRow={}
    for k=(rows-1)*cols+1,math.min(self.size,rows*cols) do self.lastRow[#self.lastRow+1]=k end
  end
  if not self.readonly then
    local save=ui.decorate(menu:addOption("save",3,self.bottomY+3,"▶ Save recipe"),ui.P.bg);ui.style(save,ui.P.good)
    save:onActivate(function() self:save() end)
    for _,k in ipairs(self.lastRow) do self.opts[k]:bind(keys.down,"save") end
    save:bind(keys.up,"c"..self.lastRow[1])
  end
  menu:setSelected("c"..self:firstCell())
end
function S:firstCell() local m;for s in pairs(self.cells) do if self.opts[s] and (not m or s<m) then m=s end end;return m or 1 end
function S:summary()
  -- Same item in several slots is summed: "Planks ×4 → Crafting Table ×1".
  local order,sum={input={},output={}},{input={},output={}}
  for slot=1,self.size do local c=self.cells[slot];local r=self:role(slot)
    if c and order[r] then
      local t=self.ore[slot] and "#"..self.ore[slot] or ui.label(c.label and c or ui.id(c))
      if not sum[r][t] then order[r][#order[r]+1]=t;sum[r][t]=0 end
      sum[r][t]=sum[r][t]+(c.size or 1)
    end
  end
  local function join(r) local t={};for _,n in ipairs(order[r]) do t[#t+1]=n.." ×"..sum[r][n] end;return table.concat(t,", ") end
  return join("input").."  →  "..join("output")
end
function S:draw()
  local a=ui.area();local P=ui.P
  local what=self.kind=="crafting" and "Crafting recipe" or ("Processing recipe · "..tostring(self.type))
  ui.title((self.readonly and "" or "Import · ")..what,(self.readonly and (self.d.source or "") or (self.dirty and "edited" or "as scanned")))
  if self.kind=="crafting" then
    ui.text(3,a.y,"Crafting grid",P.dim);ui.text(self.arrowX,self.arrowY,"═══▶",P.warn)
  else
    ui.text(2,a.y,"Chest layout: ",P.dim);ui.text(16,a.y,"inputs",P.accent);ui.text(23,a.y,"· product (last 4 slots)",P.warn)
    if self.clipped then ui.text(2,self.bottomY,"(rows beyond the screen are not shown)",P.dim) end
  end
  ui.fill(1,self.bottomY+1,a.w,1,P.bg);ui.text(3,self.bottomY+1,ui.fit(self:summary(),a.w-4),P.fg)
  self:info(self.selectedSlot or self:firstCell())
end
function S:info(slot)
  self.selectedSlot=slot;local a=ui.area();local c=self.cells[slot]
  local t="Slot "..slot.." · "..self:role(slot)
  if c then t=t.." · "..(c.label or ui.label(ui.id(c))).." ("..ui.id(c)..") ×"..(c.size or 1)..(self.ore[slot] and " · any #"..self.ore[slot] or "") else t=t.." · empty" end
  ui.fill(1,self.bottomY+2,a.w,1,ui.P.bg);ui.text(3,self.bottomY+2,ui.fit(t,a.w-4),ui.P.dim)
end
function S:redrawCell(slot)
  local o=self.opts[slot];if not o then return end
  o:text(self:cellText(slot,o._w));ui.style(o,self:cellColour(slot));self.dirty=true;self:draw()
end
function S:edit(slot)
  if self.readonly then return end
  local c=self.cells[slot];local role=self:role(slot)
  if role=="unused" then ui.fail("crafting recipes use the 3×3 grid and slot 14 only");return end
  local F=require("mes_ui.flows")
  local function put() F.pickItem("Slot "..slot.." item",function(i)
      local function set(q) self.cells[slot]={name=i.name,damage=i.damage or 0,size=q,label=i.label};self.ore[slot]=nil;self:redrawCell(slot) end
      if role=="input" and self.kind=="crafting" then set(1) else ui.prompt("Slot "..slot,"Quantity",1,set,{integer=true,min=1}) end
    end) end
  if not c then return put() end
  local rows={}
  if not (self.kind=="crafting" and role=="input") then rows[#rows+1]={text="Quantity… (now "..(c.size or 1)..")",value="qty"} end
  rows[#rows+1]={text="Replace item…",value="put"}
  if role=="input" then
    for _,f in ipairs(ui.try(mes().oreFamilies,ui.id(c)) or {}) do rows[#rows+1]={text="Accept any #"..f..(self.ore[slot]==f and "  (on)" or ""),value="ore:"..f} end
    if self.ore[slot] then rows[#rows+1]={text="Exact item only",value="exact"} end
  end
  rows[#rows+1]={text="Clear slot",value="clear",fg=ui.P.bad}
  ui.pick("Slot "..slot.." · "..(c.label or ui.label(ui.id(c))),rows,function(v)
    if v=="qty" then ui.prompt("Slot "..slot,"Quantity",c.size or 1,function(q) c.size=q;self:redrawCell(slot) end,{integer=true,min=1})
    elseif v=="put" then put()
    elseif v=="clear" then self.cells[slot]=nil;self.ore[slot]=nil;self:redrawCell(slot)
    elseif v=="exact" then self.ore[slot]=nil;self:redrawCell(slot)
    elseif v:sub(1,4)=="ore:" then self.ore[slot]=v:sub(5);self:redrawCell(slot) end
  end,{nofilter=true})
end
function S:save()
  local d=ui.try(mes().recipeFromSlots,self.kind,self.cells,self.size,self.type);if not d then return end
  for _,x in ipairs(d.inputs) do if self.ore[x.slot] then x.ore=self.ore[x.slot] end end
  local ok,why=mes().saveRecipe(d)
  if ok then ui.ok("Saved: "..self:summary());ui.pop()
  elseif why=="duplicate" then ui.notify("That recipe already exists; nothing added")
  else ui.fail(tostring(why)) end
end
function S:key(char,code)
  if (char==83 or char==115) and not self.readonly then self:save();return true end
  if (char==68 or char==100) and self.readonly then
    if self.d.source=="db" then ui.fail("recipes from the database can't be removed here");return true end
    ui.confirm("Remove recipe","Remove this "..(self.d.source or "").." recipe?",function()
      if ui.try(mes().removeRecipe,self.item,self.index) then ui.ok("Removed");ui.pop() end end)
    return true
  end
  if code==ui.keys.back and self.dirty and not self.readonly then
    ui.confirm("Discard","Discard your edits to this recipe?",function() ui.pop() end);return true
  end
end
return S
