-- Standalone named flight graph. Coordinates are block coordinates, not a sensor.
local serialization = require("serialization")
local store=require('logistics.store')
local filesystem=require('filesystem')
local db
local function record(key,value)
  db=db or store.open('/etc/map.db','log')
  if value==nil then db:delete(key) else db:put(key,value) end
end
local function linkKey(a,b) return 'l:'..(a<b and a..'|'..b or b..'|'..a) end
local M, nodes, links, storages = {}, {}, {}, {}
local created=0
local revision,clearHalf=0,nil
local clearModel
local cachedX,cachedY,cachedZ,cachedOffset
local clear={}
local minX,minY,minZ,maxX,maxY,maxZ,sizeY,sizeZ=0,0,0,0,0,0,1,1
local namesCache,storageNamesCache
local distanceCache={}
local function edited() revision=revision+1;clearHalf=nil;namesCache=nil;storageNamesCache=nil;distanceCache={} end
function M.revision() return revision end
-- SHARED/read-only name indexes, invalidated only by map edits.
function M.names()
  if not namesCache then namesCache={};for name in pairs(nodes) do namesCache[#namesCache+1]=name end;table.sort(namesCache) end
  return namesCache
end
function M.storageNames()
  if not storageNamesCache then storageNamesCache={};for name in pairs(storages) do storageNamesCache[#storageNamesCache+1]=name end;table.sort(storageNamesCache) end
  return storageNamesCache
end
-- Sparse numeric keys, with strides fixed for this map revision. Unlike a
-- global bit-pack this supports negative/world coordinates without aliases.
function M.blockKey(x,y,z)
  if x<minX or x>maxX or y<minY or y>maxY or z<minZ or z>maxZ then return nil end
  return ((x-minX)*sizeY+(y-minY))*sizeZ+(z-minZ)
end
-- Exact segment vs expanded closed voxel, with conservative roundoff tolerance.
local function touches(px,py,pz,dx,dy,dz,x,y,z,hx,hy,hz)
  local lo,hi=0,1
  for axis=1,3 do
    local p,d,b,half
    if axis==1 then p,d,b,half=px,dx,x,hx elseif axis==2 then p,d,b,half=py,dy,y,hy else p,d,b,half=pz,dz,z,hz end
    local low,high=b-half-1e-9,b+1+half+1e-9
    if d==0 then if p<low or p>high then return false end
    else
      local a,c=(low-p)/d,(high-p)/d
      if a>c then a,c=c,a end
      lo=math.max(lo,a);hi=math.min(hi,c)
      if lo>hi then return false end
    end
  end
  return true
end
-- Amanatides-Woo center traversal widened by ceil(half). No voxel tables,
-- string keys, or visitor closures are allocated in the hot loop.
local function walk(p,q,half,build,avoid,wanted)
  local hx,hy,hz,oy
  if type(half)=="table" then hx,hy,hz,oy=half.x,half.y,half.z,half.offsetY or 0 else hx,hy,hz,oy=half,half,half,0 end
  local px,py,pz=p.x+0.5,p.y+0.5+oy,p.z+0.5
  local dx,dy,dz=q.x-p.x,q.y-p.y,q.z-p.z
  local x,y,z=math.floor(px),math.floor(py),math.floor(pz)
  local sx,sy,sz=dx>=0 and 1 or -1,dy>=0 and 1 or -1,dz>=0 and 1 or -1
  local tx=dx==0 and math.huge or ((dx>0 and x+1 or x)-px)/dx
  local ty=dy==0 and math.huge or ((dy>0 and y+1 or y)-py)/dy
  local tz=dz==0 and math.huge or ((dz>0 and z+1 or z)-pz)/dz
  local ax,ay,az=dx==0 and math.huge or math.abs(1/dx),dy==0 and math.huge or math.abs(1/dy),dz==0 and math.huge or math.abs(1/dz)
  local radius=math.max(1,math.ceil(math.max(hx,hy,hz)))
  while true do
    for bx=x-radius,x+radius do for by=y-radius,y+radius do for bz=z-radius,z+radius do
      if touches(px,py,pz,dx,dy,dz,bx,by,bz,hx,hy,hz) then
        local key=M.blockKey(bx,by,bz)
        if wanted then if key==wanted then return true end
        elseif build then assert(key);clear[key]=true
        elseif not clear[key] or (avoid and avoid.blocks and avoid.blocks[key]) then return false end
      end
    end end end
    local t=math.min(tx,ty,tz)
    if t>1 then break end
    if tx<=t+1e-12 then x=x+sx;tx=tx+ax end
    if ty<=t+1e-12 then y=y+sy;ty=ty+ay end
    if tz<=t+1e-12 then z=z+sz;tz=tz+az end
  end
  return not wanted
end
function M.buildClear(half)
  local hx,hy,hz,oy
  if type(half)=="table" then hx,hy,hz,oy=half.x,half.y,half.z,half.offsetY or 0 else hx,hy,hz,oy=half,half,half,0 end
  if clearHalf and hx==cachedX and hy==cachedY and hz==cachedZ and oy==cachedOffset then return clear end
  assert(type(hx)=="number" and hx>=0 and hx<math.huge and type(hy)=="number" and hy>=0 and hy<math.huge and type(hz)=="number" and hz>=0 and hz<math.huge,"box half-size required")
  assert(type(oy)=="number" and math.abs(oy)<math.huge,"finite center offset required")
  clear={};M.clear=clear
  maxX,maxY,maxZ=-math.huge,-math.huge,-math.huge
  minX,minY,minZ=math.huge,math.huge,math.huge
  for _,p in pairs(nodes) do
    minX=math.min(minX,math.floor(p.x+0.5-hx-1e-9));maxX=math.max(maxX,math.floor(p.x+0.5+hx+1e-9))
    minY=math.min(minY,math.floor(p.y+0.5+oy-hy-1e-9));maxY=math.max(maxY,math.floor(p.y+0.5+oy+hy+1e-9))
    minZ=math.min(minZ,math.floor(p.z+0.5-hz-1e-9));maxZ=math.max(maxZ,math.floor(p.z+0.5+hz+1e-9))
  end
  if not next(nodes) then minX,minY,minZ,maxX,maxY,maxZ=0,0,0,0,0,0 end
  sizeY,sizeZ=maxY-minY+1,maxZ-minZ+1
  assert((maxX-minX+1)*sizeY*sizeZ<2^53,"map bounds exceed exact numeric voxel keys")
  for name,p in pairs(nodes) do
    walk(p,p,half,true)
    for other in pairs(links[name]) do if name<other then walk(p,nodes[other],half,true) end end
  end
  clearHalf=half
  clearModel={x=hx,y=hy,z=hz,offsetY=oy}
  cachedX,cachedY,cachedZ,cachedOffset=hx,hy,hz,oy
  return clear
end
M.clear=clear
function M.clearLine(p,q,half,avoid)
  -- Querying a larger box must not manufacture additional known air. The
  -- link sweep model is configured explicitly by buildClear; edits retain it.
  if not clearHalf then M.buildClear(clearModel or half) end
  if type(p)=="string" then p=nodes[p] end
  if type(q)=="string" then q=nodes[q] end
  return p~=nil and q~=nil and walk(p,q,half,false,avoid)
end
function M.linksAtBlock(key,half)
  M.buildClear(half)
  local out={}
  for a,adj in pairs(links) do for b in pairs(adj) do
    if a<b and walk(nodes[a],nodes[b],half,false,nil,key) then out[#out+1]={a=a,b=b} end
  end end
  table.sort(out,function(a,b) return a.a<b.a or (a.a==b.a and a.b<b.b) end)
  return out
end
function M.smooth(route,half,avoid)
  if not route or #route<2 then return route end
  local out={route[1]};local anchor,last=route[1],route[1]
  for i=2,#route do
    if not M.clearLine(anchor,route[i],half,avoid) then
      if last==anchor then return nil end
      out[#out+1]=last;anchor=last
      if not M.clearLine(anchor,route[i],half,avoid) then return nil end
    end
    last=route[i]
  end
  out[#out+1]=last;return out
end
local function copy(v) return serialization.unserialize(serialization.serialize(v)) end
local function distance(a,b)
  local x,y,z=a.x-b.x,a.y-b.y,a.z-b.z
  return math.sqrt(x*x+y*y+z*z)
end
function M.add(name,x,y,z,opts)
  assert(type(name)=="string" and name~="", "node name required")
  assert(not storages[name],"name already used by a storage")
  local coordinates={x,y,z}
  for i=1,3 do local n=coordinates[i];assert(type(n)=="number" and n==n and math.abs(n)<math.huge and n%1==0,"block coordinate required") end
  opts=opts or {}; local faces={}
  for side,v in pairs(opts.faces or {}) do assert(type(side)=="number" and side%1==0 and side>=0 and side<=5 and type(v)=="boolean","invalid face");faces[side]=v end
  local stamp=nodes[name] and nodes[name].created
  if not stamp then created=math.max(os.time(),created+1);stamp=created end
  nodes[name]={x=x,y=y,z=z,faces=faces,charger=opts.charger==true,created=stamp};links[name]=links[name] or {}
  for _,s in pairs(storages) do if s.node==name then faces[s.side]=true end end
  record('n:'..name,nodes[name])
  edited()
  return M.node(name)
end
function M.remove(name)
  edited()
  for other in pairs(links[name] or {}) do record(linkKey(name,other)) end
  record('n:'..name)
  nodes[name]=nil;links[name]=nil
  for _,adj in pairs(links) do adj[name]=nil end
  for s,e in pairs(storages) do if e.node==name then storages[s]=nil;record('s:'..s) end end
end
function M.name(storage,node,side)
  assert(type(storage)=="string" and storage~="","storage name required")
  assert(not nodes[storage],"name already used by a node")
  assert(nodes[node] and type(side)=="number" and side%1==0 and side>=0 and side<=5,"invalid storage face")
  local count=0
  for name,e in pairs(storages) do
    if name~=storage and e.node==node then
      assert(e.side~=side,"face already named");count=count+1
    end
  end
  assert(count<5,"node already has five storages")
  storages[storage]={node=node,side=side}
  if not nodes[node].faces[side] then nodes[node].faces[side]=true;record('n:'..node,nodes[node]) end
  record('s:'..storage,storages[storage])
  edited()
  return M.storage(storage)
end
function M.unname(storage) local existed=storages[storage]~=nil;storages[storage]=nil;record('s:'..storage);edited();return existed end
function M.storage(storage) return storages[storage] and copy(storages[storage]) end
function M.storages() return copy(storages) end
function M.node(name) return nodes[name] and copy(nodes[name]) end
-- A node name, or a storage name standing for its node.
function M.place(name) return nodes[name] and name or storages[name] and storages[name].node end
function M.nodes() return copy(nodes) end
function M.links(n)
  if not links[n] then return end
  local out={};for k in pairs(links[n]) do out[#out+1]=k end;return out
end
function M.link(a,b)
  assert(nodes[a] and nodes[b] and a~=b,"unknown/same node")
  links[a][b]=true;links[b][a]=true
  record(linkKey(a,b),true)
  edited()
end
function M.unlink(a,b)
  edited()
  if links[a] then links[a][b]=nil end
  if links[b] then links[b][a]=nil end
  record(linkKey(a,b))
end
-- Any-angle A*: same graph neighbours and deterministic tie ordering as route.
function M.theta(a,b,half,avoid)
  if not nodes[a] or not nodes[b] then return nil end
  M.buildClear(half)
  local open,g,f,parent={[a]=true},{[a]=0},{[a]=distance(nodes[a],nodes[b])},{}
  while next(open) do
    local current
    for n in pairs(open) do if not current or f[n]<f[current] or (f[n]==f[current] and n<current) then current=n end end
    if current==b then
      local path={b};while parent[current] do current=parent[current];table.insert(path,1,current) end;return path
    end
    open[current]=nil
    for n in pairs(links[current]) do
      local blocked=avoid and (avoid[current..":"..n] or avoid[n..":"..current] or (avoid[current] and avoid[current][n]))
      if not blocked and M.clearLine(current,n,half,avoid) then
        local from=current
        if parent[current] and M.clearLine(parent[current],n,half,avoid) then from=parent[current] end
        local cost=g[from]+distance(nodes[from],nodes[n])
        if not g[n] or cost<g[n] then parent[n]=from;g[n]=cost;f[n]=cost+distance(nodes[n],nodes[b]);open[n]=true end
      end
    end
  end
end
function M.route(a,b,avoid)
  if not nodes[a] or (b and not nodes[b]) then return nil end
  local open,g,f,previous={[a]=true},{[a]=0},{[a]=b and distance(nodes[a],nodes[b]) or 0},{}
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
        previous[n]=current;g[n]=cost;f[n]=cost+(b and distance(nodes[n],nodes[b]) or 0);open[n]=true
      end
    end
  end
  if not b then return g end
end
function M.distances(a)
  for _,v in ipairs(distanceCache) do if v[1]==a then return v[2] end end
  local g=M.route(a) or {};distanceCache[#distanceCache+1]={a,g}
  if #distanceCache>4 then table.remove(distanceCache,1) end
  return g
end
function M.save()
  db=db or store.open('/etc/map.db','log');db:flush()
end
function M.load()
  local exists=filesystem.exists('/etc/map.db')
  local file=not exists and io.open('/etc/map.cfg','r')
  local data
  if file then
    local text=file:read('*a');file:close()
    local ok,value=pcall(function()
      assert(#text>0,'empty map.cfg')
      local v=serialization.unserialize(text)
      assert(type(v)=='table' and type(v.nodes)=='table' and type(v.links)=='table','invalid map.cfg')
      v.storages=v.storages or {}
      return v
    end)
    if not ok then M.loadError=tostring(value);io.stderr:write('map: '..M.loadError..'\n');return false,M.loadError end
    data=value
  end
  db=db or store.open('/etc/map.db','log')
  if data then
    for n,p in pairs(data.nodes) do db:put('n:'..n,p) end
    for a,adj in pairs(data.links) do for b in pairs(adj) do if a<b then db:put(linkKey(a,b),true) end end end
    for n,s in pairs(data.storages) do db:put('s:'..n,s) end
    db:flush();assert(filesystem.rename('/etc/map.cfg','/etc/map.cfg.bak'))
    nodes,links,storages=data.nodes,data.links,data.storages
  else
    local records=db:load()
    nodes,links,storages={},{},{}
    for key,value in pairs(records) do
      local kind,n=key:sub(1,2),key:sub(3)
      if kind=='n:' then nodes[n]=value;links[n]={} elseif kind=='s:' then storages[n]=value end
    end
    for key in pairs(records) do if key:sub(1,2)=='l:' then
      local a,b=key:sub(3):match('^(.-)|(.+)$');links[a][b]=true;links[b][a]=true
    end end
  end
  M.loadError=nil
  edited()
  for _,node in pairs(nodes) do created=math.max(created,node.created or 0) end
  return exists or data~=nil
end
M.load()
return M
