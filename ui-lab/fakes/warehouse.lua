-- UI-lab fake of the warehouse API (contract shapes).
local D=require("lab_data");local event=require("event")
local M={};local lg=function() return require("logistics") end
local function copy(t) if type(t)~="table" then return t end;local o={};for k,v in pairs(t) do o[k]=copy(v) end;return o end
local function changed() D.revision=D.revision+1;event.push("warehouse","changed") end
function M.revision() return D.revision end
function M.totals() return D.items end
function M.members() return copy(D.members) end
function M.add(s,settings) assert(require("map").storage(s),"unknown storage");D.members[s]=copy(settings or {});changed();return true end
function M.remove(s) local e=D.members[s]~=nil;D.members[s]=nil;changed();return e end
function M.groups(kind) local o={};for n,g in pairs(D.groups) do if not kind or g.type==kind then o[n]=copy(g) end end;return o end
function M.group(name,kind,roles) assert(type(name)=="string" and name~="" and next(roles),"group name, type and roles required");D.groups[name]={type=kind,roles=copy(roles)};changed();return true end
function M.ungroup(name) local e=D.groups[name]~=nil;D.groups[name]=nil;changed();return e end
local function find(i) for _,t in ipairs(D.items) do if t.item.name==i.name and t.item.damage==(i.damage or 0) then return t end end end
function M.find(i)
  local t=find(i);if not t or t.count==0 then return {} end
  local out,left,k={},t.count,0
  while left>0 do k=k+1;local c=math.min(left,64*3);out[#out+1]={storage="s"..((k*3)%8).."_"..(k%4).."_"..(k%2==0 and "N" or "S"),count=c};left=left-c end
  return out
end
function M.count(i) local t=find(i);return t and t.count or 0 end
function M.contents(s) return {items={},slots=27,freeSlots=27} end
function M.stackSize(i) return 64 end
function M.inflight() return {} end
function M.scan(list) if type(list)=="string" then list={list} end;local ids={};for _,s in ipairs(list or {"all"}) do ids[#ids+1]=lg().fake("read",{storage=s}) end;return ids end
function M.fetch(i,n,to) local t=find(i);if not t or t.count<n then return nil,"requested "..n..", available "..(t and t.count or 0) end;t.count=t.count-n;changed();return lg().fake("fetch",{storage=to},i,n) end
function M.store(i,n,from) return lg().fake("store",{storage=from},i,n) end
return M
