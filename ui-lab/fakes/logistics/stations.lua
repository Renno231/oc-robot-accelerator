-- UI-lab fake of drone-logistics stations (same calls, returns and signal).
-- A new station links (or, with supplied members and paths, as survey
-- approval gives, flies its path then reads), reads, then is ready (failed
-- when x>=100); retry succeeds; "move" removal takes 2 s. A phase step
-- pushes a logistics event and ("station",name,"checking",phase), as the
-- real one does. Walls need supplied members.
local event=require("event");local map=require("logistics.map")
local M={};local R={};local items={}
local faces={bottom=0,top=1,north=2,south=3,west=4,east=5}
local dirs={{0,-1,0},{0,1,0},{0,0,-1},{0,0,1},{-1,0,0},{1,0,0}}
local function copy(t) if type(t)~="table" then return t end;local o={};for k,v in pairs(t) do o[k]=copy(v) end;return o end
local function integer(n) return type(n)=="number" and n%1==0 end
local function build(kind,s)
  local f,d=faces[s.face],faces[s.rowDir];local count=s.members and #s.members or kind=="storage" and 1 or s.count;local name=kind=="storage" and s.name or s.prefix
  assert(kind=="storage" or kind=="row" or kind=="wall" and s.members,"invalid kind")
  for _,k in ipairs({"x","y","z"}) do assert(integer(s[k]),"integer coordinates required") end
  assert(f and ({stock=1,other=1,import=1,export=1})[s.role],"invalid face or role")
  assert(integer(count) and count>=1 and (s.members or count<=64),"invalid member count")
  assert(s.members or kind=="storage" or d and d~=f and d~=f~1 and (s.spacing==1 or s.spacing==2),"invalid row direction or spacing")
  assert(s.pair==nil or s.pair==1 or s.pair==2,"pair must be 1 or 2")
  -- Real stations names members on the map at once: check them too.
  local used={};for _,r in pairs(R) do for _,m in ipairs(r.members) do used[m.storage]=true end end
  local function free(n) assert(type(n)=="string" and n~="" and not map.node(n) and not map.storage(n) and not R[n] and not used[n],"name already used or empty") end
  free(name)
  local r={name=name,kind=kind,spec=copy(s),state="checking",phase=s.paths and "path" or "link",members={},created={nodes={},links={}},sizes={}}
  for i=1,count do
    local v,a=dirs[(d or 0)+1],dirs[f+1];local n=(i-1)*(s.spacing or 1)
    local m={storage=kind=="storage" and name or name..i,side=f~1,x=s.x+v[1]*n,y=s.y+v[2]*n,z=s.z+v[3]*n}
    if s.members then local p=s.members[i];m.x,m.y,m.z,m.alias=p.x,p.y,p.z,p.alias or i end
    if kind~="storage" then free(m.storage) end;m.node=string.format("h%d_%d_%d",m.x+a[1],m.y+a[2],m.z+a[3]);r.created.nodes[i]=m.node;r.members[i]=m
    if i>1 then r.created.links[#r.created.links+1]={r.members[i-1].node,m.node} end
  end
  table.insert(r.created.links,1,{"0:65:2",r.members[1].node})
  return r
end
local function signal(r,state,reason) r.state=state;r.reason=reason;if state=="ready" then r.phase=nil end;event.push("station",r.name,state) end
local function finish(r)
  if r.spec.x>=100 then return signal(r,"failed","no clear path from the network to ("..r.spec.x..","..r.spec.y..","..r.spec.z.."): tried 7:65:2, 6:65:2, 5:65:2; clear the path or add a node nearer") end
  local p=r.spec.pair or 1
  for i,m in ipairs(r.members) do if (m.alias or (i-1)//p*p+1)==i then r.sizes[m.storage]=p==2 and 54 or 27 end end
  signal(r,"ready")
end
local function progress(r)
  local function read() if r.state=="checking" then r.phase="read";event.push("logistics",0,"done");event.push("station",r.name,"checking","read");event.timer(2,function() if r.state=="checking" then finish(r) end end) end end
  event.timer(2,read)
end
function M.add(kind,s)
  local ok,r=pcall(build,kind,s);if not ok then return nil,r end
  R[r.name]=r;progress(r);return r.name
end
function M.retry(name)
  local r=R[name];if not r or r.state~="failed" or not r.phase then return nil,"station is not retryable" end
  r.state="checking";r.reason=nil;r.spec.x=r.spec.x%100
  local function done() if r.state=="checking" then finish(r) end end
  event.timer(3,done);return true
end
function M.remove(name,opts)
  local r=R[name];opts=opts or {}
  if not r or r.state~="ready" and r.state~="failed" then return nil,"station is not removable" end
  if opts.items and opts.items~="move" and opts.items~="forget" then return nil,"items must be move or forget" end
  if (items[name] or 0)>0 and not opts.items then return nil,"holds "..items[name].." items: remove with move or forget" end
  local function gone() R[name]=nil;items[name]=nil;event.push("station",name,"removed") end
  if opts.items=="move" and (items[name] or 0)>0 then r.state="removing";r.phase=nil;event.timer(2,gone) else gone() end
  return true
end
function M.get(name) return copy(R[name]) end
function M.list()
  local out={};for _,r in pairs(R) do out[#out+1]={name=r.name,kind=r.kind,state=r.state,phase=r.phase,reason=r.reason,note=r.note,count=#r.members} end
  table.sort(out,function(a,b) return a.name<b.name end);return out
end
-- Lab fixture: one of each state, built without timers.
local function fixture(kind,s,state,phase,reason,note,held)
  local r=build(kind,s);r.state,r.phase,r.reason,r.note=state,phase,reason,note;R[r.name]=r;items[r.name]=held
  if state=="ready" then r.phase=nil;local p=s.pair or 1;for i,m in ipairs(r.members) do if (i-1)%p==0 then r.sizes[m.storage]=note and 54 or 27 end end end
end
fixture("storage",{x=2,y=64,z=6,face="top",name="stock1",role="stock"},"ready",nil,nil,nil,140)
fixture("row",{x=0,y=64,z=9,face="top",rowDir="east",count=6,spacing=1,pair=1,prefix="ore",role="stock"},"checking","row")
fixture("row",{x=12,y=64,z=-4,face="north",rowDir="east",count=3,spacing=2,pair=1,prefix="east",role="other"},"failed","row",
  "blocked between (12,64,-5) and (16,64,-5): clear the row's hover line")
fixture("row",{x=0,y=64,z=12,face="top",rowDir="east",count=4,spacing=1,pair=1,prefix="chest",role="stock"},"ready",nil,nil,
  "these may be double chests; remove and re-add with pair 2",12)
fixture("storage",{x=40,y=70,z=-12,face="west",name="far",role="stock"},"failed","link",
  "no clear path from the network to (40,70,-12): tried 7:65:2, 6:65:2, 5:65:2; clear the path or add a node nearer")
-- IO chests (the iochest fake's rows).
fixture("storage",{x=-4,y=64,z=0,face="west",name="in1",role="import"},"ready")
fixture("storage",{x=-4,y=64,z=2,face="west",name="in2",role="import"},"ready")
fixture("storage",{x=-4,y=64,z=4,face="west",name="out1",role="export"},"ready")
return M
