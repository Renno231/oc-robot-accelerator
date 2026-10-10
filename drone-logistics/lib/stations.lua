local map=require('map')
local lg=require('logistics')
local wh=require('warehouse')
local event=require('event')
local ser=require('serialization')
local store=require('store').open('/etc/stations','log')
local records=store:load()
local M={}
local faces={bottom=0,top=1,north=2,south=3,west=4,east=5}
local dirs={{0,-1,0},{0,1,0},{0,0,-1},{0,0,1},{-1,0,0},{1,0,0}}
local function copy(v) return ser.unserialize(ser.serialize(v)) end
local function pos(p) return string.format('(%d,%d,%d)',p.x,p.y,p.z) end
local function inventory(r,i)
  local pair=r.spec.pair or 1;return r.members[(i-1)//pair*pair+1].storage
end
local function move(r)
  local ids={}
  for i,m in ipairs(r.members) do if m.storage==inventory(r,i) then
    local c=wh.contents(m.storage)
    for _,v in pairs(c and c.items or {}) do if v.count>0 then
      local id,err=wh.store(v.item,v.count,m.storage)
      if not id then return ids,err end;ids[#ids+1]=id
    end end
  end end
  return ids
end
local function save(r) records['st_'..r.name]=r;store:put('st_'..r.name,r);store:flush() end
local function signal(r,state,reason)
  r.state=state;r.reason=reason
  if state=='ready' then r.phase=nil;r.jobs={} end
  save(r);event.push('station',r.name,state)
end
local function cleanup(r)
  for _,m in ipairs(r.members) do map.unname(m.storage) end
  for _,v in ipairs(r.created.links) do map.unlink(v[1],v[2]) end
  local used={}
  for _,s in pairs(map.storages()) do used[s.node]=true end
  for _,s in pairs(records) do if s~=r then for _,m in ipairs(s.members) do used[m.node]=true end end end
  for _,n in ipairs(r.created.nodes) do if not used[n] then map.remove(n) end end
  map.save();records['st_'..r.name]=nil;store:delete('st_'..r.name);store:flush()
  event.push('station',r.name,'removed')
end
local start,advance
local function phase(r,p)
  r.phase=p;r.jobs={};start(r)
end
start=function(r,replay)
  local first=r.members[1].node
  if r.state=='removing' then
    local err;r.jobs,err=move(r);if err then return signal(r,'failed',err) end
    if #r.jobs==0 then return cleanup(r) end
  elseif r.phase=='link' then
    local candidate=replay and r.tried[#r.tried]
    if not candidate and #r.tried<3 then
      local skip={[first]=true};for _,n in ipairs(r.created.nodes) do skip[n]=true end
      for _,n in ipairs(r.tried) do skip[n]=true end
      local nodes,choices=map.nodes(),{}
      local p=nodes[first]
      for n,q in pairs(nodes) do if not skip[n] and #map.links(n)>0 then
        choices[#choices+1]={n,(q.x-p.x)^2+(q.y-p.y)^2+(q.z-p.z)^2}
      end end
      table.sort(choices,function(a,b) return a[2]<b[2] or a[2]==b[2] and a[1]<b[1] end)
      candidate=choices[1] and choices[1][1]
      if candidate then r.tried[#r.tried+1]=candidate end
    end
    if not candidate then return signal(r,'failed','no clear path from the network to '..pos(map.node(first))..': tried '..table.concat(r.tried,', ')..'; clear the path or add a node nearer') end
    r.jobs={lg.test(candidate,first)}
  elseif r.phase=='row' then r.jobs={lg.test(first,r.members[#r.members].node)}
  else
    local names=r.bad
    if #names==0 then names={};for i,m in ipairs(r.members) do if inventory(r,i)==m.storage then names[#names+1]=m.storage end end end
    r.jobs=wh.scan(names)
  end
  save(r)
end
advance=function(r)
  local results={}
  for _,id in ipairs(r.jobs) do
    local s=lg.status(id)
    if not s then
      return start(r,true)
    end
    if s.state~='done' and s.state~='failed' and s.state~='partial' then return end
    results[#results+1]=s
  end
  if r.state=='removing' then
    for _,s in ipairs(results) do if s.state~='done' then return signal(r,'failed',s.reason) end end
    return cleanup(r)
  end
  if r.phase~='read' then
    local s=results[1]
    if s.test=='ok' then
      if r.phase=='link' then
        local a,b=r.tried[#r.tried],r.members[1].node
        map.link(a,b);r.created.links[#r.created.links+1]={a,b};map.save()
        return phase(r,#r.members>1 and 'row' or 'read')
      end
      for i=2,#r.members do
        local a,b=r.members[i-1].node,r.members[i].node
        map.link(a,b);r.created.links[#r.created.links+1]={a,b}
      end
      map.save();return phase(r,'read')
    elseif s.test~='blocked' then return signal(r,'failed',r.phase..': '..tostring(s.reason))
    elseif r.phase=='link' then return start(r) end
    return signal(r,'failed','blocked between '..pos(map.node(r.members[1].node))..' and '..pos(map.node(r.members[#r.members].node))..": clear the row's hover line")
  end
  local checked,reason={}
  for _,s in ipairs(results) do
    if s.state~='done' and s.reason then reason='read: '..s.reason end
    for _,v in ipairs(s.steps or {}) do if v.read then
    checked[v.read.node..':'..v.read.side]=s.state=='done' and v.size and v.size>0 and v.size or false
  end end end
  local names=#r.bad>0 and r.bad or nil
  local bad,reasons={},{}
  for i,m in ipairs(r.members) do
    local wanted=not names
    for _,n in ipairs(names or {}) do if n==m.storage then wanted=true end end
    local size=checked[m.node..':'..m.side]
    local key=inventory(r,i)
    if size then
      if r.spec.pair==2 and r.sizes[key] and r.sizes[key]~=size then
        reason='inventory size mismatch at '..pos(m)..': remove and re-add the row'
      end
      r.sizes[key]=size
      if (r.spec.pair or 1)==1 and r.spec.spacing==1 and i>1 and size>=54 and r.sizes[r.members[i-1].storage]==size then
        r.note='these may be double chests; remove and re-add with pair 2'
      end
    elseif wanted and key==m.storage then
      bad[#bad+1]=m.storage;reasons[#reasons+1]='no inventory on the '..r.spec.face..' face at '..pos(m)
    end
  end
  r.bad=bad
  if #bad>0 or reason then return signal(r,'failed',reason or table.concat(reasons,'; ')) end
  if r.spec.role=='stock' then for i,m in ipairs(r.members) do wh.add(m.storage,{inventory=inventory(r,i)}) end end
  signal(r,'ready')
end
local function integer(n) return type(n)=='number' and n%1==0 end
local function validate(kind,s)
  local f,d=faces[s.face],faces[s.rowDir]
  local count=kind=='storage' and 1 or s.count
  local name=kind=='storage' and s.name or s.prefix
  assert(kind=='storage' or kind=='row','invalid kind')
  for _,k in ipairs({'x','y','z'}) do assert(integer(s[k]),'integer coordinates required') end
  assert(f and (s.role=='stock' or s.role=='other'),'invalid face or role')
  assert(integer(count) and count>=1 and count<=64,'count must be 1..64')
  assert(kind=='storage' or d and d~=f and d~=f~1 and (s.spacing==1 or s.spacing==2),'invalid row direction or spacing')
  assert(s.pair==nil or s.pair==1 or s.pair==2,'pair must be 1 or 2')
  local nodes,storages=map.nodes(),map.storages()
  local function free(n) assert(type(n)=='string' and n~='' and not nodes[n] and not storages[n] and not records['st_'..n],'name already used or empty') end
  free(name)
  local r={name=name,kind=kind,spec=copy(s),state='checking',phase='read',members={},created={nodes={},links={}},tried={},jobs={},bad={},sizes={}}
  local positions,counts,used={},{},{}
  for n,p in pairs(nodes) do positions[pos(p)]=n end
  for _,v in pairs(storages) do counts[v.node]=(counts[v.node] or 0)+1;used[v.node..':'..v.side]=true end
  for i=1,count do
    local storage=kind=='storage' and name or name..i;free(storage)
    local v,a=dirs[(d or 0)+1],dirs[f+1];local n=(i-1)*(s.spacing or 1)
    local m={storage=storage,side=f~1,x=s.x+v[1]*n,y=s.y+v[2]*n,z=s.z+v[3]*n}
    local h={x=m.x+a[1],y=m.y+a[2],z=m.z+a[3]};m.node=positions[pos(h)]
    if m.node then
      assert(not used[m.node..':'..m.side] and (counts[m.node] or 0)<5,'face already named or node full')
      if #map.links(m.node)==0 then r.phase='link' end
    else
      m.node=string.format('h%d_%d_%d',h.x,h.y,h.z);free(m.node)
      r.created.nodes[#r.created.nodes+1]=m.node;r.phase='link'
    end
    r.members[i]=m
  end
  return r
end
function M.add(kind,s)
  local ok,r=pcall(validate,kind,s);if not ok then return nil,r end
  local v=dirs[faces[s.face]+1]
  for _,m in ipairs(r.members) do
    if not map.node(m.node) then map.add(m.node,m.x+v[1],m.y+v[2],m.z+v[3]) end
    map.name(m.storage,m.node,m.side)
  end
  map.save();save(r);start(r);return r.name
end
function M.retry(name)
  local r=records['st_'..name]
  if not r or r.state~='failed' or not r.phase then return nil,'station is not retryable' end
  r.state='checking';r.reason=nil;r.jobs={}
  if r.phase=='link' then r.tried={} end
  start(r);return true
end
function M.remove(name,opts)
  local r=records['st_'..name];opts=opts or {}
  if not r or r.state~='ready' and r.state~='failed' then return nil,'station is not removable' end
  if opts.items and opts.items~='move' and opts.items~='forget' then return nil,'items must be move or forget' end
  local total=0
  for i,m in ipairs(r.members) do
    for g,v in pairs(wh.groups()) do for role,n in pairs(v.roles) do
      if n==m.storage then return nil,m.storage..' is '..g..'.'..role..'; reassign it first' end
    end end
    for _,v in ipairs(wh.inflight()) do if v.storage==m.storage then return nil,m.storage..' has items reserved by a running job' end end
    local c=wh.contents(m.storage)
    if m.storage==inventory(r,i) and wh.members()[m.storage] then for _,v in pairs(c and c.items or {}) do total=total+v.count end end
  end
  if total>0 and not opts.items then return nil,'holds '..total..' items: remove with move or forget' end
  r.state='removing';r.phase=nil;r.reason=nil;r.jobs={}
  for _,m in ipairs(r.members) do wh.remove(m.storage) end
  if opts.items=='move' then
    local err;r.jobs,err=move(r);if err then signal(r,'failed',err);return true end
  end
  save(r);if #r.jobs==0 then cleanup(r) end;return true
end
function M.get(name) local r=records['st_'..name];return r and copy(r) end
function M.list()
  local out={};for _,r in pairs(records) do out[#out+1]={name=r.name,kind=r.kind,state=r.state,phase=r.phase,reason=r.reason,note=r.note} end
  table.sort(out,function(a,b) return a.name<b.name end);return out
end
event.listen('logistics',function(_,id)
  for _,r in pairs(records) do if r.state=='checking' or r.state=='removing' then
    for _,job in ipairs(r.jobs) do if job==id then advance(r);break end end
  end end
end)
for _,r in pairs(records) do if r.state=='checking' or r.state=='removing' then
  if #r.jobs==0 and r.state=='checking' then start(r) else advance(r) end
end end
return M
