-- UI-lab fake of drone-logistics survey (as at 9e186b5): the same calls
-- (request, list, get, approve, reject, tiles, group), record fields
-- {id,area,origin,state,reason,groups,mismatches,ignored,limitation,
-- metrics[,choices][,stations]}, request/approve/reject checks and
-- error texts, and the ("survey",id,state) signal on every transition.
-- group, list, get, reject and approve are the real code; approve calls
-- the stations fake. Not modelled: flights, scans and persistence. A new
-- request is surveyed by timers: 8 s later it is proposed with the lab
-- fixture's candidates, or fails when x1 >= 100.
-- Lab hooks: labScenario() seeds one record per state and marks drone1 a
-- survey drone; labNoDrone() clears every survey mark.
local event=require("event");local lg=require("logistics");local stations=require("logistics.stations");local map=require("logistics.map")
local M={};local records={}
local names={'bottom','top','north','south','west','east'}
local dirs={{0,-1,0},{0,1,0},{0,0,-1},{0,0,1},{-1,0,0},{1,0,0}}
local limitation='replacements of the same density are not detected'
local function copy(t)
  if type(t)~='table' then return t end
  local out={};for k,v in pairs(t) do out[k]=copy(v) end;return out
end
local function key(p) return p.x..','..p.y..','..p.z end
local function offset(p,d) return {x=p.x+d[1],y=p.y+d[2],z=p.z+d[3]} end
local function transition(r,state,reason)
  r.state=state;r.reason=reason;records['sv_'..r.id]=r;event.push('survey',r.id,state)
end
function M.tiles(a)
  local out={}
  for y=a.y1,a.y2,4 do for z=a.z1,a.z2,4 do for x=a.x1,a.x2,4 do
    out[#out+1]={x=x,y=y,z=z,w=math.min(4,a.x2-x+1),d=math.min(4,a.z2-z+1),h=math.min(4,a.y2-y+1)}
  end end end
  return out
end
-- Plain-data grouping, shared by synthetic fixtures and physical survey results.
function M.group(candidates)
  local available={};local groups={}
  table.sort(candidates,function(a,b) return a.x<b.x or a.x==b.x and (a.z<b.z or a.z==b.z and a.y<b.y) end)
  for _,c in ipairs(candidates) do available[key(c)]=c end
  local function face(c) return #c.faces==1 and c.faces[1] or 'choose' end
  for _,c in ipairs(candidates) do if c.size==54 and not c.alias then
    for _,i in ipairs({6,4}) do
      local other=available[key(offset(c,dirs[i]))]
      if other and other.size==54 and other.name==c.name and not other.alias and not other.parts then
        c.parts={copy(c),other};other.alias=true;break
      end
    end
  end end
  local used={}
  local function compatible(a,b)
    return b and not b.alias and not used[b] and b.name==a.name and b.size==a.size and face(b)==face(a) and face(a)~='choose'
  end
  for _,c in ipairs(candidates) do if not c.alias and not used[c] then
    local row={c};local direction=6;local step=c.size==54 and 2 or 1
    for _,i in ipairs({6,4,2}) do
      local d=dirs[i];local q=offset(c,{d[1]*step,d[2]*step,d[3]*step})
      if compatible(c,available[key(q)]) then direction=i;break end
    end
    used[c]=true
    local d=dirs[direction];local last=c
    while face(c)~='choose' do
      local nextOne=available[key(offset(last,{d[1]*step,d[2]*step,d[3]*step}))]
      if not compatible(c,nextOne) then break end
      row[#row+1]=nextOne;used[nextOne]=true;last=nextOne
    end
    groups[#groups+1]={kind=#row>1 and 'row' or 'storage',name=c.name,face=face(c),faces=c.faces,
      role='?',spacing=step,pair=c.size==54 and 2 or 1,rowDir=names[direction],inventories=row}
  end end
  local function shape(g)
    local t={g.name,g.face,g.rowDir,g.spacing}
    for _,p in ipairs(g.inventories) do t[#t+1]=p.x..':'..p.z end
    return table.concat(t,'/')
  end
  table.sort(groups,function(a,b) return a.inventories[1].y<b.inventories[1].y end)
  local result={};local consumed={}
  for i,g in ipairs(groups) do if not consumed[i] then
    local levels=1;local stepY;local last=g.inventories[1].y;local signature=shape(g)
    if g.kind=='row' and g.rowDir~='top' then
      for j=i+1,#groups do local h=groups[j];local y=h.inventories[1].y
        if not consumed[j] and h.kind=='row' and shape(h)==signature and y>last and (not stepY or y-last==stepY) then
          stepY=stepY or y-last;last=y;levels=levels+1;consumed[j]=true
          for _,p in ipairs(h.inventories) do g.inventories[#g.inventories+1]=p end
        end
      end
    end
    if levels>1 then g.kind='wall';g.levels=levels;g.levelSpacing=stepY end
    g.id=#result+1;result[#result+1]=g
  end end
  return result
end
-- Lab fixture, area (0,64,8)-(17,67,12), approach 4:65:7: a 4x3 single-chest
-- wall facing north, a double-chest row (3 doubles), a free-standing chest
-- with two reachable faces, a furnace, five ignored blocks, and station ore's
-- first member reading air.
local origin={x=4,y=65,z=7}
local function walk(to)
  local p,out={x=origin.x,y=origin.y,z=origin.z},{}
  for _,a in ipairs({'z','y','x'}) do while p[a]~=to[a] do p[a]=p[a]+(to[a]>p[a] and 1 or -1);out[#out+1]={x=p.x,y=p.y,z=p.z} end end
  return out
end
local function chest(x,y,z,size,faces)
  local c={x=x,y=y,z=z,name='minecraft:chest',size=size,facing='north',faces=faces or {'north'},paths={}}
  for _,f in ipairs(c.faces) do local i;for j,n in ipairs(names) do if n==f then i=j end end;c.paths[f]=walk(offset(c,dirs[i])) end
  return c
end
local function proposal(r)
  local c={}
  for y=64,66 do for x=2,5 do c[#c+1]=chest(x,y,10,27) end end
  for x=8,13 do c[#c+1]=chest(x,64,10,54) end
  c[#c+1]=chest(16,64,10,27,{'north','top'})
  r.groups=M.group(c)
  r.ignored={{position={x=15,y=64,z=10},facing='north',kind='machine, not yet supported (S2)',name='minecraft:furnace'},
    {position={x=7,y=66,z=8},facing='south',kind='ignored',name='minecraft:torch'},
    {position={x=1,y=64,z=11},kind='ignored',name='minecraft:stone'},{position={x=17,y=64,z=11},kind='ignored',name='minecraft:stone'},
    {position={x=6,y=64,z=10},kind='ignored',name='minecraft:planks'},{position={x=14,y=64,z=10},kind='ignored',name='minecraft:crafting_table'}}
  r.mismatches={{position={x=0,y=64,z=9},known={station='ore'},reading=0,block={name='minecraft:air'}}}
  r.metrics={scans=31,hops=96,analyzes=26,energy=1180.4,tripEnergy=842.0}
end
local function record(a)
  local id=1;while records['sv_'..id] do id=id+1 end
  return {id=id,area=a,origin=copy(origin),groups={},mismatches={},ignored={},limitation=limitation,metrics={scans=0,hops=0,analyzes=0,energy=0,tripEnergy=0}}
end
function M.request(area)
  if type(area)~='table' then return nil,'integer corners required' end
  local a={}
  for _,axis in ipairs({'x','y','z'}) do
    local l,h=area[axis..'1'],area[axis..'2']
    if type(l)~='number' or type(h)~='number' or l%1~=0 or h%1~=0 then return nil,'integer corners required' end
    a[axis..'1']=math.min(l,h);a[axis..'2']=math.max(l,h)
    if math.abs(h-l)+1>(axis=='y' and 16 or 32) then return nil,'area cap is 32 x 16 x 32' end
  end
  local capable=false;for _,d in ipairs(lg.drones()) do if d.survey then capable=true end end
  if not capable then return nil,'no survey drone registered' end
  if not next(map.nodes()) then return nil,'no mapped approach node' end
  local r=record(a);transition(r,'surveying')
  local function done()
    if r.state~='surveying' then return end
    if a.x1>=100 then return transition(r,'failed','no scanned-air approach to area') end
    proposal(r);transition(r,'proposed')
  end
  event.timer(8,done);return r.id
end
function M.get(id) local r=records['sv_'..id];return r and copy(r) end
function M.list()
  local out={};for _,r in pairs(records) do out[#out+1]={id=r.id,state=r.state,area=copy(r.area),reason=r.reason,
    groups=#r.groups,mismatches=#r.mismatches,ignored=#r.ignored} end
  table.sort(out,function(a,b) return a.id<b.id end);return out
end
function M.reject(id)
  local r=records['sv_'..id];if not r or r.state~='proposed' then return nil,'not proposed' end
  transition(r,'rejected');return true
end
function M.approve(id,choices)
  local r=records['sv_'..id];if not r or r.state~='proposed' then return nil,'not proposed' end
  choices=choices or {}
  local requests={}
  for _,g in ipairs(r.groups) do local c=choices[g.id]
    if c then
      if not ({stock=true,other=true,import=true,export=true})[c.role] then return nil,'role required' end
      local face=g.face=='choose' and c.face or g.face;local allowed=false
      for _,f in ipairs(g.faces) do if f==face then allowed=true end end
      if not allowed then return nil,'reachable face required' end
      if type(c.prefix)~='string' or c.prefix=='' then return nil,'name prefix required' end
      local first=g.inventories[1];local members,paths={},{}
      for _,inventory in ipairs(g.inventories) do
        local primary=#members+1
        for _,p in ipairs(inventory.parts or {inventory}) do
          members[#members+1]={x=p.x,y=p.y,z=p.z,alias=primary}
          local route=p.paths[face];if not route then return nil,'face unavailable on double half' end
          paths[#paths+1]={r.origin};for _,q in ipairs(route) do paths[#paths][#paths[#paths]+1]=q end
        end
      end
      requests[#requests+1]={kind=g.kind,spec={x=first.x,y=first.y,z=first.z,face=face,role=c.role,
        name=c.prefix,prefix=c.prefix,count=#members,spacing=g.spacing,pair=g.pair,rowDir=g.rowDir,members=members,paths=paths}}
    end
  end
  if #requests==0 then return nil,'no groups selected' end
  r.choices=copy(choices);r.stations={}
  for _,q in ipairs(requests) do local name,reason=stations.add(q.kind,q.spec)
    if not name then transition(r,'failed',reason);return nil,reason end
    r.stations[#r.stations+1]=name
  end
  transition(r,'approved');return true
end
-- Seeded without signals: #1 rejected, #2 failed, #3 proposed, #4 surveying
-- (proposed 45 s in, by the survey signal).
function M.labScenario()
  require("lab_data").drones[1].survey=true;if records.sv_1 then return end
  local function seed(a,state,reason) local r=record(a);r.state,r.reason=state,reason;records['sv_'..r.id]=r;return r end
  proposal(seed({x1=-6,y1=64,z1=-6,x2=-1,y2=66,z2=-1},'rejected'))
  seed({x1=30,y1=64,z1=30,x2=45,y2=70,z2=40},'failed','no scanned-air approach to area')
  proposal(seed({x1=0,y1=64,z1=8,x2=17,y2=67,z2=12},'proposed'))
  local r=seed({x1=20,y1=64,z1=0,x2=35,y2=67,z2=6},'surveying')
  r.metrics={scans=12,hops=40,analyzes=3,energy=402.5,tripEnergy=310.0}
  local function finish() if r.state=='surveying' then proposal(r);transition(r,'proposed') end end
  event.timer(45,finish)
end
function M.labNoDrone() for _,d in ipairs(require("lab_data").drones) do d.survey=nil end end
return M
