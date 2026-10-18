-- UI-lab fake of drone-logistics map (same public names/shapes).
local D=require("lab_data");local M={};local rev=1;local names,snames
local function copy(t) if type(t)~="table" then return t end;local o={};for k,v in pairs(t) do o[k]=copy(v) end;return o end
local function edited() rev=rev+1;names=nil;snames=nil end
function M.revision() return rev end
function M.node(n) return copy(D.nodes[n]) end
function M.nodes() return copy(D.nodes) end
function M.storage(s) return copy(D.storages[s]) end
function M.storages() return copy(D.storages) end
function M.place(n) return D.nodes[n] and n or D.storages[n] and D.storages[n].node end
function M.names() if not names then names={};for n in pairs(D.nodes) do names[#names+1]=n end;table.sort(names) end;return names end
function M.storageNames() if not snames then snames={};for n in pairs(D.storages) do snames[#snames+1]=n end;table.sort(snames) end;return snames end
function M.name(s,node,side)
  assert(type(s)=="string" and s~="","storage name required");assert(not D.nodes[s],"name already used by a node")
  for n,e in pairs(D.storages) do assert(not(n~=s and e.node==node and e.side==side),"face already named") end
  D.storages[s]={node=node,side=side};D.nodes[node].faces[side]=true;edited();return M.storage(s)
end
function M.unname(s) local e=D.storages[s]~=nil;D.storages[s]=nil;edited();return e end
function M.save() end
return M
