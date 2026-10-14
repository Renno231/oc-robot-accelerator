local map=require('map')
local lg=require('logistics')
local stations=require('stations')
local event=require('event')
local ser=require('serialization')
local store=require('store').open('/etc/survey','log')
local records=store:load()
local M={}
local runs={}
local names={'bottom','top','north','south','west','east'}
local dirs={{0,-1,0},{0,1,0},{0,0,-1},{0,0,1},{-1,0,0},{1,0,0}}
local limitation='replacements of the same density are not detected'
local function copy(t)
  if type(t)~='table' then return t end
  local out={};for k,v in pairs(t) do out[k]=copy(v) end;return out
end
local function key(p) return p.x..','..p.y..','..p.z end
local function offset(p,d) return {x=p.x+d[1],y=p.y+d[2],z=p.z+d[3]} end
local function distance(p,q) return math.abs(p.x-q.x)+math.abs(p.y-q.y)+math.abs(p.z-q.z) end
local function gap(p,t)
  local n=0
  for _,a in ipairs({{t.x,t.w,p.x},{t.y,t.h,p.y},{t.z,t.d,p.z}}) do
    n=n+math.max(a[1]-a[3],0,a[3]-a[1]-a[2]+1)
  end
  return n
end
local function transition(r,state,reason)
  r.state=state;r.reason=reason;records['sv_'..r.id]=r
  store:put('sv_'..r.id,r);store:flush();event.push('survey',r.id,state)
end
function M.tiles(a)
  local out={}
  for y=a.y1,a.y2,4 do for z=a.z1,a.z2,4 do for x=a.x1,a.x2,4 do
    out[#out+1]={x=x,y=y,z=z,w=math.min(4,a.x2-x+1),d=math.min(4,a.z2-z+1),h=math.min(4,a.y2-y+1)}
  end end end
  return out
end
local function reachable(s)
  local queue={s.origin};s.air={[key(s.origin)]={p=s.origin}}
  local i=1
  while queue[i] do
    local p=queue[i];i=i+1
    for _,d in ipairs(dirs) do
      local q=offset(p,d);local k=key(q)
      if s.grid[k]==0 and not s.air[k] then
        q.torch=s.positions[k] and s.positions[k].torch
        s.air[k]={p=q,from=key(p)};queue[#queue+1]=q
      end
    end
  end
end
local function path(s,p)
  local out={};local n=s.air[key(p)]
  while n and n.from do table.insert(out,1,n.p);n=s.air[n.from] end
  return out
end
local function inArea(p,a)
  return p.x>=a.x1 and p.x<=a.x2 and p.y>=a.y1 and p.y<=a.y2 and p.z>=a.z1 and p.z<=a.z2
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
  -- Equal horizontal rows stacked at constant vertical spacing are one unit.
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
local advance
local function adjacent(s,p)
  local faces,paths={},{}
  for i,d in ipairs(dirs) do local q=offset(p,d)
    if s.air[key(q)] then faces[#faces+1]=names[i];paths[names[i]]=path(s,q) end
  end
  if #faces>0 then p.faces=faces;p.paths=paths;return p end
end
local function submit(s,command,context)
  s.context=context;s.job=lg.probe(s.node,command);s.result=nil
end
local function fail(s,reason) runs[s.record.id]=nil;transition(s.record,'failed',reason) end
local function scanFrom(s,t)
  local best,score
  for _,v in pairs(s.air) do
    local p=v.p;local fits=true
    for _,a in ipairs({{t.x,t.w,p.x},{t.y,t.h,p.y},{t.z,t.d,p.z}}) do
      if math.abs(a[1]-a[3])>32 or math.abs(a[1]+a[2]-1-a[3])>32 then fits=false end
    end
    local cost=gap(p,t)
    if fits and (not score or cost<score) then best=p;score=cost end
  end
  return best
end
advance=function(s)
  if #s.tiles>0 then
    local t=s.tiles[1];local p=scanFrom(s,t)
    if p and gap(p,t)<=1 then return submit(s,{path=path(s,p),scan=t},{tile=t}) end
    local target={x=t.x,y=t.y,z=t.z};local nearest,score
    for _,v in pairs(s.air) do local n=distance(v.p,target)
      if not score or n<score then nearest=v.p;score=n end
    end
    if s.bridgeScore and score>=s.bridgeScore then
      for k,value in pairs(s.grid) do if value~=0 and not s.analyzed[k] and not s.known[k] then
        local c=adjacent(s,s.positions[k])
        if c then local i;for j,n in ipairs(names) do if n==c.faces[1] then i=j end end
          return submit(s,{path=c.paths[c.faces[1]],side=(i-1)~1},{candidate=c,face=i,frontier=true})
        end
      end end
      return fail(s,'no scanned-air approach to area')
    end
    s.bridgeScore=score
    local box={w=4,d=4,h=4}
    for _,axis in ipairs({'x','y','z'}) do box[axis]=nearest[axis]+(target[axis]<nearest[axis] and -3 or 0) end
    return submit(s,{path=path(s,nearest),scan=box},{tile=box,bridge=true})
  end
  if not s.candidates then
    s.candidates={}
    for k,value in pairs(s.grid) do if (value~=0 and not s.analyzed[k]) or s.mismatch[k] and not s.analyzed[k] then
      local p=s.positions[k]
      if inArea(p,s.record.area) and not s.known[k] or s.mismatch[k] then
        if adjacent(s,p) then s.candidates[#s.candidates+1]=p end
      end
    end end
  end
  local c=table.remove(s.candidates,1)
  if c then
    local face=c.faces[1];local index
    for i,n in ipairs(names) do if face==n then index=i end end
    return submit(s,{path=c.paths[face],side=(index-1)~1},{candidate=c,face=index})
  end
  for _,c in ipairs(s.chests) do adjacent(s,c) end
  s.record.groups=M.group(s.chests);runs[s.record.id]=nil;transition(s.record,'proposed')
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
  local center={x=(a.x1+a.x2)/2,y=(a.y1+a.y2)/2,z=(a.z1+a.z2)/2}
  local node,origin,score;local known={}
  for n,p in pairs(map.nodes()) do
    known[key(p)]={air=true,node=n}
    local d=distance(p,center)
    if #map.links(n)>0 and (not score or d<score) then node=n;origin=p;score=d end
  end
  if not node then return nil,'no mapped approach node' end
  for name,e in pairs(map.storages()) do
    known[key(offset(map.node(e.node),dirs[e.side+1]))]={storage=name}
  end
  for _,summary in ipairs(stations.list()) do for _,p in ipairs(stations.get(summary.name).members) do known[key(p)]={station=summary.name} end end
  local id=1;while records['sv_'..id] do id=id+1 end
  local r={id=id,area=a,origin=origin,groups={},mismatches={},ignored={},limitation=limitation,metrics={scans=0,hops=0,analyzes=0,energy=0,tripEnergy=0}}
  local halo={};for _,axis in ipairs({'x','y','z'}) do halo[axis..'1']=a[axis..'1']-1;halo[axis..'2']=a[axis..'2']+1 end
  local s={record=r,node=node,origin=origin,known=known,grid={[key(origin)]=0},positions={[key(origin)]=origin},tiles=M.tiles(halo),chests={},mismatch={},analyzed={}}
  runs[id]=s;transition(r,'surveying');reachable(s);advance(s);return id
end
event.listen('survey_result',function(_,job,result)
  for _,s in pairs(runs) do if s.job==job then s.result=ser.unserialize(result) end end
end)
event.listen('logistics',function(_,job)
  for _,s in pairs(runs) do if s.job==job then
    local status=lg.status(job)
    if status.state=='failed' then return fail(s,status.reason) end
    if status.state~='done' then return end
    local result=s.result;if not result then return fail(s,'survey result missing') end
    for k,v in pairs(s.record.metrics) do s.record.metrics[k]=v+(result[k] or 0) end
    local context=s.context
    if context.tile then
      local t=context.tile;local i=1
      for y=t.y,t.y+t.h-1 do for z=t.z,t.z+t.d-1 do for x=t.x,t.x+t.w-1 do
        local p={x=x,y=y,z=z};local k=key(p);local value=result.values[i];i=i+1
        s.grid[k]=value;s.positions[k]=p
        local known=s.known[k]
        if known and ((known.air and value~=0) or (not known.air and value==0)) and not s.mismatch[k] then
          s.mismatch[k]=true;s.record.mismatches[#s.record.mismatches+1]={position=p,known=known,reading=value}
        end
      end end end
      if not context.bridge then table.remove(s.tiles,1);s.bridgeScore=nil end
      reachable(s)
    else
      local c=context.candidate;c.name=result.block.name;c.facing=result.block.facing or (result.block.properties or {}).facing;c.size=result.size
      s.analyzed[key(c)]=true
      if c.name=='minecraft:torch' and result.clear then
        s.grid[key(c)]=0;c.torch=true;s.positions[key(c)]=c;reachable(s);s.candidates=nil;s.bridgeScore=nil
      end
      if s.mismatch[key(c)] then
        for _,m in ipairs(s.record.mismatches) do if key(m.position)==key(c) then m.block=result.block end end
      elseif c.name=='minecraft:chest' and (c.size==27 or c.size==54) and inArea(c,s.record.area) then s.chests[#s.chests+1]=c
      else s.record.ignored[#s.record.ignored+1]={position={x=c.x,y=c.y,z=c.z},facing=c.facing,
        kind=(c.size or c.name:find('furnace')) and 'machine, not yet supported (S2)' or 'ignored',name=c.name,reason=result.reason} end
    end
    advance(s);return
  end end
end)
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
          -- Each route starts at the surveyed mapped approach, stored below.
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
local trimmed=false
for _,r in pairs(records) do
  if r.trips then r.trips=nil;store:put('sv_'..r.id,r);trimmed=true end
  if r.state=='surveying' then transition(r,'failed','survey interrupted; request again') end
end
if trimmed then store:flush() end
return M
