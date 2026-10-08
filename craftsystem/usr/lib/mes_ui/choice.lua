-- Planning choices, as craft.lua asks them. mes.plan calls select() with the
-- planner's yield and resumes with its return; each modal blocks in ui.wait.
--   {"select_recipe",item,recipes,inventory}    -> recipe | nil (skip: first) | false (external only)
--   {"skip_inventory_check",item,recipe}        -> true (always manufacture) | false (use stock)
--   {"select_oredict",original,candidates,recipe,slot,inventory} -> item id | nil (planner default)
-- Cancelling raises "Planning cancelled", which mes.plan returns as its error.
local ui=require("mes_ui.core");local wh=require("warehouse")
local C={}
local CANCEL="Planning cancelled"
local keys=ui.keys
-- craft.lua's ingredient colours.
local palette={0xFF6B6B,0x4ECDC4,0x45B7D1,0xF7DC6F,0xBB8FCE,0x85C88A}
local function mes() return require("mes") end

-- Recipe slot values: "id", "id,qty" (processing), "ore:name", "a | b", "mod:x:*".
local function strip(v) local id,q=tostring(v):match("^(.-),([%d%.]+)$");return id or tostring(v),tonumber(q) or 1 end
local function name(id)
  if id:sub(1,4)=="ore:" then return "#"..id:sub(5) end
  if id:find(" | ",1,true) then local t={};for p in id:gmatch("[^|]+") do t[#t+1]=ui.label((p:match("^%s*(.-)%s*$"))) end;return table.concat(t," / ") end
  local base=id:match("^(.-):%*%s*$");if base then return ui.label(base).." (any)" end
  return ui.label(id)
end
local function count(id) local ok,n=pcall(wh.count,ui.item(id));return ok and n or 0 end
local function slots(recipe)
  local out={};for k,v in pairs(recipe) do if type(k)=="number" and strip(v)~="minecraft:air" then out[#out+1]=k end end
  table.sort(out);return out
end

-- The recipe drawn as craft.lua draws it: a 3×3 grid of numbered slots
-- coloured per ingredient, the slot list in the same colours, the product.
-- Processing recipes list their inputs. hl inverts one slot.
local function drawRecipe(recipe,item,x,y,w,h,hl)
  local P=ui.P;ui.fill(x,y,w,h,P.box)
  local colours,k={},0
  for _,s in ipairs(slots(recipe)) do local id=strip(recipe[s]);if not colours[id] then colours[id]=palette[k%#palette+1];k=k+1 end end
  local lx=x
  if not recipe.isProcessing then
    for i=0,8 do
      local id=recipe[i+1] and strip(recipe[i+1]);if id=="minecraft:air" then id=nil end
      local bg,fg=id and colours[id] or 0x333333,id and 0x000000 or P.dim
      if hl==i+1 then fg,bg=bg,0x000000 end
      ui.text(x+(i%3)*5,y+(i//3)*2,string.format(" %2d ",i+1),fg,bg)
    end
    lx=x+17
  else ui.text(x,y,ui.fit("Processing · "..tostring(recipe.machineType or "machine"),w),P.warn,P.box);y=y+1;h=h-1 end
  local row=0
  for _,s in ipairs(slots(recipe)) do
    if row>=h-1 then ui.text(lx,y+row,"…",P.dim,P.box);break end
    local id,q=strip(recipe[s])
    local fg=colours[id];if hl==s then fg=P.fg end
    ui.text(lx,y+row,ui.fit((hl==s and "▶" or " ")..string.format("%2d",s)..": "..name(id)..(q~=1 and " ×"..q or "").."  "..id,x+w-lx),fg,P.box)
    row=row+1
  end
  if item then ui.text(lx,y+math.min(row,h-1),ui.fit("  → "..name(item).." ×"..(recipe.qty or 1),x+w-lx),P.fg,P.box) end
end
local function rows(recipe) local n=#slots(recipe)+1;if recipe.isProcessing then return n+1 end;return math.max(6,n) end

-- Run a modal to its answer; any close without one cancels the plan.
local function ask(build)
  local answer={}
  local m=build(function(v) answer.done=true;answer.value=v end)
  ui.wait(m)
  if not answer.done then error(CANCEL,0) end
  return answer.value
end
local function cancelKey(m,inner)
  m.key=function(char,code)
    if code==keys.q or code==keys.back then ui.close(m);return true end
    return inner and inner(char,code)
  end
end

local function selectRecipe(item,recipes)
  local tall=0;for _,r in ipairs(recipes) do tall=math.max(tall,rows(r)) end
  return ask(function(done)
    local cur=1
    return ui.modal({title="Recipe for "..name(item),w=96,h=math.min(40,tall+8),build=function(m)
      local nav=ui.decorate(m.menu:addOption("nav",m.ix,m.iy,""),ui.P.box)
      local skip=ui.decorate(m.menu:addOption("skip",m.ix,m.iy+1,ui.fit("Skip selection (use recipe 1)",m.iw)),ui.P.box)
      local ext=ui.decorate(m.menu:addOption("ext",m.ix,m.iy+2,ui.fit("External material only (do not manufacture)",m.iw)),ui.P.box)
      local function show() nav:text(ui.fit("◀ Recipe "..cur.." of "..#recipes.." ▶   Enter uses it",m.iw)) end
      local function turn(d) cur=(cur-1+d)%#recipes+1;show();m.paint(m) end
      for _,o in ipairs({nav,skip,ext}) do o:bind(keys.left,function() turn(-1) end);o:bind(keys.right,function() turn(1) end) end
      nav:bind(keys.down,"skip");nav:bind(keys.up,"ext");skip:bind(keys.up,"nav");skip:bind(keys.down,"ext");ext:bind(keys.up,"skip");ext:bind(keys.down,"nav")
      nav:onActivate(function() ui.close(m);done(recipes[cur]) end)
      skip:onActivate(function() ui.close(m);done(nil) end)
      ext:onActivate(function() ui.close(m);done(false) end)
      m.paint=function()
        drawRecipe(recipes[cur],item,m.ix,m.iy+4,m.iw,m.ih-6)
        ui.text(m.ix,m.y+m.h-2,ui.fit("←→ other recipes · Enter choose · Q or ⌫ cancels the plan",m.iw),ui.P.dim,ui.P.box)
      end
      cancelKey(m);show();m.menu:setSelected("nav")
    end})
  end)
end

local function selectOre(original,candidates,recipe,slot,inventory)
  local names,seen={},{}
  local function add(n) if not seen[n] then seen[n]=true;names[#names+1]=n end end
  for _,n in ipairs(candidates or {}) do add(n) end
  -- Wildcards resolve to the stacks the planner's snapshot holds, as the
  -- user's management screen does.
  for _,w in ipairs((candidates or {}).wildcards or {}) do
    local found=false
    if inventory and inventory.countItemByName then
      local _,at=inventory:countItemByName(w)
      for _,s in ipairs(at or {}) do add(require("item_identity").stackName(inventory:getItemInSlot(s)));found=true end
    end
    if not found then add((w:gsub(":%*%s*$",""))) end
  end
  if #names<=1 then return nil end
  local list={};for _,n in ipairs(names) do list[#list+1]={id=n,count=count(n)} end
  table.sort(list,function(a,b) if a.count~=b.count then return a.count>b.count end;return a.id<b.id end)
  if type(recipe)~="table" then recipe=nil end
  local top=recipe and rows(recipe) or 0
  return ask(function(done)
    local listH=math.min(#list,10)
    return ui.modal({title="Ingredient for slot "..tostring(slot).." · "..name(original),w=96,h=top+listH+6,build=function(m)
      local L=ui.list(m.menu,{name="o",x=m.ix,y=m.iy+top+2,w=m.iw,h=listH,bg=ui.P.box,count=function() return #list end,
        row=function(i,w) local e=list[i];return ui.fit(name(e.id),34)..ui.right(ui.num(e.count),10).." in stock   "..e.id,e.count>0 and ui.P.fg or ui.P.dim end,
        activate=function(i) ui.close(m);done(list[i].id) end})
      m.paint=function()
        if recipe then drawRecipe(recipe,nil,m.ix,m.iy,m.iw,top,slot) end
        ui.text(m.ix,m.iy+top+1,ui.fit("Use which item for "..name(original).."?   "..#list.." variants, most stocked first",m.iw),ui.P.accent,ui.P.box)
        ui.text(m.ix,m.y+m.h-2,ui.fit("↑↓ choose · ←→ page · Enter use · Q or ⌫ cancels the plan",m.iw),ui.P.dim,ui.P.box)
      end
      cancelKey(m);L:refresh()
    end})
  end)
end

local function skipCheck(item)
  return ask(function(done)
    -- No first, as craft.lua defaults: a stray Enter keeps using stock.
    local m=ui.pick("Inventory check",{{text="Skip inventory check for "..name(item).."?",locked=true},
      {text="  No: use "..name(item).." from stock first",value=false},
      {text="  Yes: always manufacture it with the chosen recipe",value=true,fg=ui.P.warn}},done,
      {nofilter=true,note="Enter choose · Q or ⌫ cancels the plan"})
    cancelKey(m);return m
  end)
end

function C.select(y)
  local kind=y[1]
  if kind=="select_recipe" then
    if y[3]==nil then return nil end
    return selectRecipe(y[2],y[3])
  elseif kind=="skip_inventory_check" then return skipCheck(y[2])
  elseif kind=="select_oredict" then
    return selectOre(y[2],y[3],y[4],y[5],y[6])
  end
  ui.notify("unknown planning choice "..tostring(kind).."; using the default")
end

-- Plan with choices; nil (and a footer message) if it failed or was cancelled.
function C.plan(item,qty)
  ui.busy("Planning "..qty.." "..ui.label(item).."…")
  local ok,p,err=pcall(mes().plan,item,qty,{selectChoice=C.select})
  if not ok then err=p;p=nil end
  if p then ui.notify("Planned "..qty.." "..ui.label(item),ui.P.good);return p end
  err=tostring(err):gsub("^[^:]+:%d+: ","")
  if err:find(CANCEL,1,true) then ui.notify(CANCEL) else ui.fail(err) end
end
-- Ask how many, plan, open the plan preview.
function C.craft(item)
  ui.prompt("Craft "..ui.label(item),"How many?",1,function(n)
    local plan=C.plan(item,n);if plan then ui.push("mes_ui.plan",{plan=plan}) end
  end,{integer=true,min=1})
end
return C
