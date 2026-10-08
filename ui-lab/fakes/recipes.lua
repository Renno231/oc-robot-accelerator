-- UI-lab fake of the recipes library's management API (T11 contract,
-- "Recipes"): chest import, user/processing recipe store, ore families.
local M={}
local function copy(t) if type(t)~="table" then return t end;local o={};for k,v in pairs(t) do o[k]=copy(v) end;return o end
local recipes={}
function M.transposerInventories() return {{address="3fa2c1d0-aaaa-bbbb-cccc-000000000001",side=2,size=27,used=2},{address="3fa2c1d0-aaaa-bbbb-cccc-000000000001",side=1,size=27,used=10}} end
function M.readSlots(src)
  if src.side==1 then
    local s={};for _,k in ipairs({1,2,3,10,11,12}) do s[k]={name="minecraft:planks",damage=0,label="Oak Wood Planks",size=1} end
    s[14]={name="minecraft:crafting_table",damage=0,label="Crafting Table",size=1}
    -- not a crafting table recipe shape, but a 2x3 stand-in for the lab
    return s,27
  end
  return {[1]={name="minecraft:log",damage=0,label="Oak Wood",size=1},[24]={name="minecraft:coal",damage=1,label="Charcoal",size=1}},27
end
function M.slotsFromListing(listing,size) local s={};for k,v in pairs(listing) do s[k]={name=v.name,damage=v.damage,label=v.label,size=v.size} end;return s,size end
local function id(st) return st.name..((st.damage or 0)~=0 and ":"..st.damage or "") end
function M.recipeFromSlots(kind,slots,size,machineType)
  local d={kind=kind,machineType=machineType,inputs={},outputs={},grid={},labels={}}
  if kind=="processing" then
    assert(machineType and require("mes").types()[machineType],"pick a machine type")
    for k=1,size do local st=slots[k];if st then
      d.labels[id(st)]=st.label
      if k>size-4 then d.outputs[#d.outputs+1]={slot=k,item=id(st),qty=st.size} else d.inputs[#d.inputs+1]={slot=k,item=id(st),qty=st.size} end
    end end
    if #d.inputs==0 then return nil,"no inputs: put ingredients in the first slots" end
    if #d.inputs>16 then return nil,"at most 16 inputs" end
    if #d.outputs==0 then return nil,"no output: put the product in one of the last four slots" end
  else
    if size%9~=0 or size<27 then return nil,"crafting import needs a 9-wide chest (27+ slots)" end
    local map={1,2,3,10,11,12,19,20,21}
    for g,k in ipairs(map) do local st=slots[k];if st then d.grid[g]=id(st);d.labels[id(st)]=st.label;d.inputs[#d.inputs+1]={slot=k,item=id(st),qty=1} end end
    local out=slots[14];if not out then return nil,"put the crafted item in slot 14" end
    d.labels[id(out)]=out.label;d.outputs[1]={slot=14,item=id(out),qty=out.size}
    if #d.inputs==0 then return nil,"the 3x3 grid is empty" end
    for k=1,size do if slots[k] and k~=14 then local inGrid=false;for _,g in ipairs(map) do if g==k then inGrid=true end end
      if not inGrid then return nil,"slot "..k.." is outside the grid; leave it empty" end end end
  end
  return d
end
function M.save(d)
  local key=d.outputs[1].item;recipes[key]=recipes[key] or {}
  local sig=d.kind..(d.machineType or "");for _,i in ipairs(d.inputs) do sig=sig..i.item..i.qty end
  for _,r in ipairs(recipes[key]) do if r.sig==sig then return nil,"duplicate" end end
  local r=copy(d);r.sig=sig;r.source=d.kind=="processing" and "processing" or "user";table.insert(recipes[key],r);return true
end
function M.list(item)
  local out={};for _,r in ipairs(recipes[item] or {}) do out[#out+1]=copy(r) end
  if item=="minecraft:torch" then out[#out+1]={kind="crafting",source="db",grid={nil,"minecraft:coal:1",nil,nil,"minecraft:stick"},inputs={{item="minecraft:coal:1",qty=1},{item="minecraft:stick",qty=1}},outputs={{item="minecraft:torch",qty=4}}} end
  return out
end
function M.remove(item,i) local l=recipes[item];if not l or not l[i] then return nil,"only user and processing recipes can be removed" end;table.remove(l,i);return true end
function M.oreFamilies(item) if item:find("planks") then return {"plankWood"} elseif item:find("log") then return {"logWood"} end;return {} end
return M
