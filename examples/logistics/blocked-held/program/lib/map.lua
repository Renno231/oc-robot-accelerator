-- Standalone named flight graph. Coordinates are block coordinates, not a sensor.
local serialization = require("serialization")
local M, nodes, links, storages = {}, {}, {}, {}
local created=0
local function copy(v) return serialization.unserialize(serialization.serialize(v)) end
local function distance(a,b)
  local x,y,z=a.x-b.x,a.y-b.y,a.z-b.z
  return math.sqrt(x*x+y*y+z*z)
end
function M.add(name,x,y,z,opts)
  assert(type(name)=="string" and name~="", "node name required")
  local coordinates={x,y,z}
  for i=1,3 do local n=coordinates[i];assert(type(n)=="number" and n==n and math.abs(n)<math.huge and n%1==0,"block coordinate required") end
  opts=opts or {}; local faces={}
  for side,v in pairs(opts.faces or {}) do assert(type(side)=="number" and side%1==0 and side>=0 and side<=5 and type(v)=="boolean","invalid face");faces[side]=v end
  local stamp=nodes[name] and nodes[name].created
  if not stamp then created=math.max(os.time(),created+1);stamp=created end
  nodes[name]={x=x,y=y,z=z,faces=faces,charger=opts.charger==true,created=stamp};links[name]=links[name] or {}
  for _,s in pairs(storages) do if s.node==name then faces[s.side]=true end end
  return M.node(name)
end
function M.remove(name)
  nodes[name]=nil;links[name]=nil
  for _,adj in pairs(links) do adj[name]=nil end
  for s,e in pairs(storages) do if e.node==name then storages[s]=nil end end
end
function M.name(storage,node,side)
  assert(type(storage)=="string" and storage~="","storage name required")
  assert(nodes[node] and type(side)=="number" and side%1==0 and side>=0 and side<=5,"invalid storage face")
  local count=0
  for name,e in pairs(storages) do
    if name~=storage and e.node==node then
      assert(e.side~=side,"face already named");count=count+1
    end
  end
  assert(count<5,"node already has five storages")
  storages[storage]={node=node,side=side};nodes[node].faces[side]=true
  return M.storage(storage)
end
function M.unname(storage) local existed=storages[storage]~=nil;storages[storage]=nil;return existed end
function M.storage(storage) return storages[storage] and copy(storages[storage]) end
function M.storages() return copy(storages) end
function M.node(name) return nodes[name] and copy(nodes[name]) end
function M.nodes() return copy(nodes) end
function M.link(a,b)
  assert(nodes[a] and nodes[b] and a~=b,"unknown/same node")
  links[a][b]=true;links[b][a]=true
end
function M.unlink(a,b)
  if links[a] then links[a][b]=nil end
  if links[b] then links[b][a]=nil end
end
function M.route(a,b,avoid)
  if not nodes[a] or not nodes[b] then return nil end
  local open,g,f,previous={[a]=true},{[a]=0},{[a]=distance(nodes[a],nodes[b])},{}
  while next(open) do
    local current
    for n in pairs(open) do if not current or f[n]<f[current] or (f[n]==f[current] and n<current) then current=n end end
    if current==b then
      local path={current}
      while previous[current] do current=previous[current];table.insert(path,1,current) end
      return path
    end
    open[current]=nil
    for n in pairs(links[current]) do
      local blocked=avoid and (avoid[current..":"..n] or avoid[n..":"..current] or (avoid[current] and avoid[current][n]))
      local cost=g[current]+distance(nodes[current],nodes[n])
      if not blocked and (not g[n] or cost<g[n]) then
        previous[n]=current;g[n]=cost;f[n]=cost+distance(nodes[n],nodes[b]);open[n]=true
      end
    end
  end
end
function M.save()
  local file=assert(io.open("/etc/map.cfg","w"));file:write(serialization.serialize({nodes=nodes,links=links,storages=storages}));file:close()
end
function M.load()
  local file=io.open("/etc/map.cfg","r");if not file then return false end
  local data=serialization.unserialize(file:read("*a"));file:close()
  assert(type(data)=="table" and type(data.nodes)=="table" and type(data.links)=="table","invalid map file")
  nodes,links,storages=data.nodes,data.links,data.storages or {}
  for _,node in pairs(nodes) do created=math.max(created,node.created or 0) end
  return true
end
M.load()
return M
