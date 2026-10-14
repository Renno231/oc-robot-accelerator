local M={}
local inf=math.huge
local function bounds(w,g)
 w.timing=w.timing or {}
 local t=w.timing[g.name]
 if not t then t={lo=0,hi=inf,samples=0,sinceFree=0,sinceProbe=0};w.timing[g.name]=t end
 return t
end
function M.seconds(w,g)
 local t=bounds(w,g);local estimate=g.mt and g.mt.seconds;local source='config'
 if not estimate then
  local values={}
  for name,v in pairs(w.timing) do
   if w.machines[name] and w.machines[name].type==(g.type or (w.machines[g.name] or {}).type) and v.hi<inf then values[#values+1]=v.hi end
  end
  table.sort(values);local n=#values
  estimate=n>0 and (values[(n+1)//2]+values[n//2+1])/2 or nil;source=n>0 and 'type' or 'none'
 end
 if t.hi<inf then return t.hi,t,'learned' end
 if 2*t.lo>(estimate or 0) then return 2*t.lo,t,'lower' end
 return estimate or 0,t,source
end
local function exclude(g,reason)
 g.epoch=nil;g.timingExcluded=g.timingExcluded or {}
 g.timingExcluded[reason]=(g.timingExcluded[reason] or 0)+1
end
function M.load(w,g,l)
 local plan,t=M.seconds(w,g);local a=l.bundle.submittedAt or l.bundle.action.submittedAt or w.now
 local n=l.ops*l.request.perOp;local e=g.epoch
 local first=#g.loads==1
 if first then e={a=a,b=w.now,n=0,k=0};g.epoch=e
 elseif not e then exclude(g,'unknown')
 elseif t.lo==0 or w.now>e.a+e.n*t.lo then
  exclude(g,'unknown');e.unknown=true;g.epoch=e
 end
 if e then e.n=e.n+n end
 if l.timingRestart then exclude(g,'restart') end
 if g.mt.fuel and g.fuel.credit*g.mt.fuel.per<g.fuel.admitted+n then exclude(g,'fuel') end
 t.sinceFree=t.sinceFree+1;t.sinceProbe=t.sinceProbe+1
 if t.hi<inf and t.hi>1.25*t.lo and t.sinceFree>=5 and t.sinceProbe>=5 then
  plan=(t.lo+t.hi)/2;t.sinceProbe=0;l.probe=true
 end
 return n*plan
end
function M.observe(w,g,c,err)
 local e=g.epoch
 if not e then return end
 if err or #g.quarantined>0 then exclude(g,'quarantine');return end
 local delta,free,quantum=0,false,nil
 for _,l in ipairs(g.loads) do
  if l.request.run.stopping then exclude(g,'stopped');return end
  local k=(l.consumed or 0)*l.request.perOp
  local added=k-(l.timingCollected or 0);delta=delta+added;l.timingCollected=k
  if k<l.ops*l.request.perOp then quantum=quantum or l.request.perOp end
  if not l.probe and ((c.bundle.action.submittedAt or w.now)<l.due and added>0 or k<l.ops*l.request.perOp and w.now>=l.due) then free=true end
  l.probe=nil
 end
 for _,receipt in ipairs(c.bundle.action.results or {}) do
  for _,s in ipairs(receipt.steps or {}) do
   if s.take and s.maxSize and (s.taken or s.moved or 0)>=s.maxSize*#g.mt.roleSlots[g.mt.output] then exclude(g,'capacity');return end
  end
 end
 e.k=e.k+delta
 local t=bounds(w,g);local lo,hi=t.lo,t.hi
 if e.k>0 then
  local v=(w.now-e.a)/e.k
  if v<t.lo then t.lo=0;t.hi=v else t.hi=math.min(t.hi,v) end
 end
 if not e.unknown and e.k<e.n then
  local v=math.max(0,((c.bundle.action.submittedAt or w.now)-e.b)/(e.k+(quantum or 1)))
  if v>=t.hi then t.hi=inf;t.lo=v else t.lo=math.max(t.lo,v) end
 end
 if t.lo~=lo or t.hi~=hi then t.samples=t.samples+1;if free then t.sinceFree=0 end end
end
function M.persist(p,w)
 p.timing=p.timing or p.db.timing or {}
 local changed=false
 for name,t in pairs(w.timing or {}) do
  local old=p.timing[name]
  local function moved(a,b) return a~=b and (a==inf or b==inf or math.abs(a-b)>b*.05) end
  if not old and (t.lo>0 or t.hi<inf) or old and (moved(t.lo,old.lo) or moved(t.hi,old.hi)) then
   local v={};for k,x in pairs(t) do v[k]=x end;p.timing[name]=v;changed=true;require('event').push('mes','timing',name)
  end
 end
 if changed then p.store:put('timing',p.timing) end
 p.known.timing=true
end
return M
