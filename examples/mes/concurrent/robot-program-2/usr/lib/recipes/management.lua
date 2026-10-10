-- Recipe management APIs, loaded lazily by the recipes library.
local recipes = require("recipes")
local identity = require("item_identity")
local M = {}
local function copy(v)
  if type(v) ~= "table" then return v end
  local out = {}; for k,x in pairs(v) do out[k] = copy(x) end; return out
end
local function integer(n) return type(n)=="number" and n>0 and n<math.huge and n%1==0 end
local function itemId(id, wildcard)
  if type(id)~="string" then return false end
  if id:match("^[%w_.%-]+:[%w_./%-]+$") then return true end
  if id:match("^[%w_.%-]+:[%w_./%-]+:%d+$") then return true end
  return wildcard and id:match("^[%w_.%-]+:[%w_./%-]+:%*$")~=nil
end
local function denseList(list)
  if type(list)~="table" or #list==0 then return false end
  local n=0
  for k in pairs(list) do if not integer(k) or k>#list then return false end;n=n+1 end
  return n==#list
end
local function changed() require("event").push("recipes", "changed") end
local function stack(v)
  if type(v) ~= "table" or not v.name or v.name == "minecraft:air" or (v.size or 0)<=0 then return nil end
  return {name=v.name, damage=v.damage or 0, label=v.label, size=v.size}
end
function M.slotsFromListing(listing, size)
  if type(listing)~="table" or not integer(size) then return nil,"invalid inventory listing" end
  local out={}
  for k,v in pairs(listing) do
    local slot=tonumber(k)
    if slot and slot>=1 and slot<=size and slot%1==0 then out[slot]=stack(v) end
  end
  return out,size
end
function M.readSlots(source)
  if type(source)~="table" or type(source.transposer)~="string" or
      type(source.side)~="number" or source.side%1~=0 or source.side<0 or source.side>5 then
    return nil,"transposer address and side (0-5) required"
  end
  local ok, slots, size = pcall(function()
    local proxy=require("component").proxy(source.transposer)
    local n=proxy.getInventorySize(source.side)
    if not integer(n) then return nil,"no inventory" end
    local iterator,err=proxy.getAllStacks(source.side)
    if not iterator then return nil,err or "cannot read inventory" end
    return M.slotsFromListing(iterator.getAll(),n)
  end)
  if not ok then return nil,tostring(slots) end
  return slots,size
end
function M.transposerInventories()
  local component=require("component"); local out={}
  for address in component.list("transposer") do
    for side=0,5 do
      local slots,size=M.readSlots({transposer=address,side=side})
      if slots then
        local used=0; for _ in pairs(slots) do used=used+1 end
        if used>0 then out[#out+1]={address=address,side=side,size=size,used=used} end
      end
    end
  end
  table.sort(out,function(a,b) return a.address==b.address and a.side<b.side or a.address<b.address end)
  return out
end
function M.recipeFromSlots(kind, slots, size, machineType)
  if kind~="processing" and kind~="crafting" then return nil,"invalid recipe kind" end
  if type(slots)~="table" or not integer(size) then return nil,"invalid inventory" end
  if kind=="processing" and (type(machineType)~="string" or machineType=="") then return nil,"pick a machine type" end
  local d={kind=kind,machineType=kind=="processing" and machineType or nil,inputs={},outputs={},grid={},labels={}}
  local function ingredient(k,qty)
    local st=stack(slots[k]); if not st then return nil end
    if not integer(st.size) then return nil,"invalid stack quantity" end
    local id=identity.stackName(st); d.labels[id]=st.label
    return {slot=k,item=id,qty=qty or st.size}
  end
  if kind=="processing" then
    if size<5 then return nil,"processing inventory needs at least five slots" end
    for k=1,size do
      local i,err=ingredient(k); if err then return nil,err end
      if i then local dst=k>size-4 and d.outputs or d.inputs;dst[#dst+1]=i end
    end
    if #d.inputs==0 then return nil,"no inputs: put ingredients in the first slots" end
    if #d.inputs>16 then return nil,"at most 16 inputs" end
    if #d.outputs==0 then return nil,"no output: put the product in one of the last four slots" end
  else
    if size<27 or size%9~=0 then return nil,"crafting import needs a 9-wide chest (27+ slots)" end
    local allowed={[14]=true}
    for g,k in ipairs({1,2,3,10,11,12,19,20,21}) do
      allowed[k]=true
      local i,err=ingredient(k,1);if err then return nil,err end
      if i then d.grid[g]=i.item; d.inputs[#d.inputs+1]=i end
    end
    local o,err=ingredient(14);if err then return nil,err end
    if not o then return nil,"put the crafted item in slot 14" end
    d.outputs[1]=o
    if #d.inputs==0 then return nil,"the 3x3 grid is empty" end
    for k=1,size do if stack(slots[k]) and not allowed[k] then return nil,"slot "..k.." is outside the grid; leave it empty" end end
  end
  return d
end
local function display(item,r,source)
  local d={kind=r.isProcessing and "processing" or "crafting",machineType=r.machineType,
    inputs={},outputs={{item=item,qty=r.qty or 1}},grid={},source=source}
  local keys={};for k in pairs(r) do if type(k)=="number" then keys[#keys+1]=k end end;table.sort(keys)
  for _,k in ipairs(keys) do
    local id,qty=r[k],1
    if r.isProcessing then local a,b=id:match("^(.-),([%d%.]+)$");if a then id,qty=a,tonumber(b) end
    else d.grid[k]=id end
    if id~="minecraft:air" then d.inputs[#d.inputs+1]={slot=k,item=id,qty=qty} end
  end
  for _,o in ipairs(r.byproducts or {}) do d.outputs[#d.outputs+1]=copy(o) end
  return d
end
local function entries(item)
  local out={}
  for _,pair in ipairs({{recipes.__userRecipes,"user"},{recipes.__processRecipes,"processing"}}) do
    local key=pair[1][item] and item or identity.canonical(item)
    for i,r in ipairs(pair[1][key] or {}) do out[#out+1]={r=r,source=pair[2],index=i,key=key} end
  end
  for i,r in ipairs(recipes.getDatabase(item) or {}) do out[#out+1]={r=r,source="db",index=i} end
  return out
end
function M.list(item)
  if type(item)~="string" then return {} end
  local out={};for _,e in ipairs(entries(item)) do out[#out+1]=display(item,e.r,e.source) end;return out
end
local function equal(a,b)
  if type(a)~=type(b) then return false end
  if type(a)~="table" then return a==b end
  for k,v in pairs(a) do if not equal(v,b[k]) then return false end end
  for k in pairs(b) do if a[k]==nil then return false end end
  return true
end
function M.save(draft)
  if type(draft)~="table" or (draft.kind~="processing" and draft.kind~="crafting") or
      not denseList(draft.inputs) or not denseList(draft.outputs) then return nil,"invalid recipe draft" end
  local d=copy(draft)
  for which,list in ipairs({d.inputs,d.outputs}) do for _,i in ipairs(list) do
    if type(i)~="table" or not itemId(i.item,which==1) or i.item=="minecraft:air" or not integer(i.qty) or
        (i.slot~=nil and not integer(i.slot)) then return nil,"invalid ingredient or quantity" end
    i.item=identity.canonical(i.item)
    if i.item=="minecraft:air" then return nil,"air is not an ingredient or output" end
  end end
  local item=d.outputs[1].item;local r={qty=d.outputs[1].qty}
  if d.kind=="processing" then
    if type(d.machineType)~="string" or d.machineType=="" or #d.inputs>16 or #d.outputs>4 then return nil,"invalid processing recipe" end
    r.isProcessing=true;r.machineType=d.machineType
    for k,i in ipairs(d.inputs) do r[k]=i.item..","..string.format("%g",i.qty) end
    if #d.outputs>1 then r.byproducts={};for k=2,#d.outputs do r.byproducts[#r.byproducts+1]={item=d.outputs[k].item,qty=d.outputs[k].qty} end end
  else
    if type(d.grid)~="table" or #d.outputs~=1 then return nil,"invalid crafting grid" end
    local n=0;local expected={};local actual={};local usedSlots={}
    local chestSlots={1,2,3,10,11,12,19,20,21}
    for k,id in pairs(d.grid) do
      if not integer(k) or k>9 or not itemId(id,true) then return nil,"invalid crafting grid" end
      id=identity.canonical(id)
      if id~="minecraft:air" then r[k]=id;n=n+1;expected[id]=(expected[id] or 0)+1 end
    end
    if n==0 then return nil,"empty crafting grid" end
    for _,i in ipairs(d.inputs) do
      if i.qty~=1 then return nil,"crafting inputs must consume one item per grid cell" end
      if i.slot then
        if usedSlots[i.slot] then return nil,"crafting inputs repeat a grid slot" end
        usedSlots[i.slot]=true
        local match=false
        for g,k in ipairs(chestSlots) do if k==i.slot and r[g]==i.item then match=true;break end end
        if not match then return nil,"crafting inputs do not match grid" end
      end
      actual[i.item]=(actual[i.item] or 0)+i.qty
    end
    if not equal(expected,actual) then return nil,"crafting inputs do not match grid" end
  end
  for _,e in ipairs(entries(item)) do
    -- DB recipes sometimes explicitly store empty grid cells as minecraft:air.
    local candidate=copy(e.r)
    for k,v in pairs(candidate) do if type(k)=="number" and type(v)=="string" then
      local id,qty=v,nil
      if candidate.isProcessing then id,qty=v:match("^(.-),([%d%.]+)$");id=id or v;qty=qty or "1" end
      id=identity.canonical(id)
      if id=="minecraft:air" then candidate[k]=nil
      else candidate[k]=qty and id..","..string.format("%g",tonumber(qty)) or id end
    end end
    for _,output in ipairs(candidate.byproducts or {}) do output.item=identity.canonical(output.item) end
    candidate.qty=candidate.qty or 1
    if equal(candidate,r) then return nil,"duplicate" end
  end
  if d.kind=="processing" then
    local ok,err=recipes.registerProcessingRecipe(item,d.machineType,{qty=r.qty,recipe=r,byproducts=r.byproducts})
    if not ok then return nil,err end
  else
    local list=recipes.__userRecipes[item] or {};recipes.__userRecipes[item]=list;list[#list+1]=r
    local ok,err=recipes.saveUserRecipes()
    if not ok then table.remove(list);if #list==0 then recipes.__userRecipes[item]=nil end;return nil,err end
  end
  changed();return true
end
function M.remove(item,index)
  if type(item)~="string" or not integer(index) then return nil,"invalid recipe index" end
  local e=entries(item)[index]
  if not e or e.source=="db" then return nil,"only user and processing recipes can be removed" end
  local target=e.source=="user" and recipes.__userRecipes or recipes.__processRecipes
  item=e.key
  local list=target[item];table.remove(list,e.index);if #list==0 then target[item]=nil end
  local ok,err
  if e.source=="user" then ok,err=recipes.saveUserRecipes() else ok,err=recipes.saveProcessingRecipes() end
  if not ok then target[item]=list;table.insert(list,e.index,e.r);return nil,err end
  changed();return true
end
function M.oreFamilies(item)
  if type(item)~="string" then return {} end
  local ore=require("oredict"); local out={};item=identity.canonical(item)
  for name in pairs(ore.cache) do
    for _,id in ipairs(ore.get(name) or {}) do
      local base=id:match("^(.*):%*$")
      if identity.canonical(id)==item or (base and (item==base or item:match("^(.*):%d+$")==base)) then out[#out+1]=name;break end
    end
  end
  table.sort(out);return out
end
function M.search(text,limit)
  text=tostring(text or ""):lower();limit=limit or 50
  if not integer(limit) then return {} end
  local out={};local seen={}
  -- Each priority tier keeps only its smallest remaining matching IDs (O(limit)).
  local function tier(iterator)
    local selected={};local n=limit-#out;if n<=0 then return end
    for id in iterator do
      if not seen[id] and id:lower():find(text,1,true) then
        local found=false;for _,v in ipairs(selected) do if v==id then found=true;break end end
        if not found then
          selected[#selected+1]=id;table.sort(selected)
          if #selected>n then table.remove(selected) end
        end
      end
    end
    for _,id in ipairs(selected) do out[#out+1]=id;seen[id]=true end
  end
  tier(coroutine.wrap(function()
    for id in pairs(recipes.__userRecipes) do coroutine.yield(id) end
    for id in pairs(recipes.__processRecipes) do coroutine.yield(id) end
  end))
  if #out<limit then tier(recipes.databaseIds()) end
  table.sort(out);return out
end
return M
