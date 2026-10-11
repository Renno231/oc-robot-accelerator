local w=require('warehouse')
local c=require('computer')
local e=require('event')
local ser=require('serialization')
local db=require('store').open('/etc/stats','log')
local D=db:load()
local C=D.settings or {fillWarn=.8,fillBad=.95,fullSoonHours=2}
local H=D.hours or {}
local M,timer,cache,rates,revision={}
local h0=math.floor(c.uptime()/3600)
local B={u=0,i={}}
local function key(i) return ser.serialize({i.name,i.damage or 0,i.label},false) end
local function roll()
local h=math.floor(c.uptime()/3600)
if h==h0 then return end
H[#H+1]=B
for n=1,math.min(h-h0-1,24) do H[#H+1]={u=0,i={}} end
while #H>24 do table.remove(H,1) end
H.serial=(H.serial or 0)+1
h0=h;B={u=0,i={}}
cache=nil;rates=nil
db:put('hours',H);db:flush()
e.push('stats');e.cancel(timer);timer=e.timer(3600-c.uptime()%3600,roll,1)
end
local function rate(k)
if not rates then
rates={}
local function add(id,d,n)
local r=rates[id] or {0,0,0,0};rates[id]=r
if n==0 then r[1]=r[1]+d end;r[2]=r[2]+d/6
if d>0 then r[3]=r[3]+1 elseif d<0 then r[4]=r[4]+1 end
end
for n=0,5 do
local b=H[#H-n]
if b then
add(false,b.u,n)
for id,d in pairs(b.i) do
local a=ser.unserialize(id);add(key{name=a[1],damage=a[2]},d,n)
if a[3] then add(id,d,n) end
end
end
end
end
return table.unpack(rates[k and key(k) or false] or {0,0,0,0})
end
local function sum()
if cache and revision==w.revision() then return cache end
local r={slots=0,freeSlots=0,items=0,kinds=0,storages=0,unknown=0,unread={},perStorage={}}
for _,fs in pairs(w.entries()) do
local v=fs[1];local a=v.entry;r.storages=r.storages+1
if a and a.slots then
local t={};for _,i in pairs(a.items) do if i.count>0 then t[#t+1]={item=i.item,count=i.count} end end
table.sort(t,function(x,y) return x.count>y.count end)
while #t>3 do table.remove(t) end
r.perStorage[#r.perStorage+1]={name=v.storage,slots=a.slots,freeSlots=a.freeSlots,fill=a.slots>0 and 1-a.freeSlots/a.slots or 0,top=t,time=a.time,beforeRestart=a.beforeRestart}
r.slots=r.slots+a.slots;r.freeSlots=r.freeSlots+a.freeSlots
else r.unknown=r.unknown+1;r.unread[#r.unread+1]=v.storage end
end
for _,v in ipairs(w.totals()) do r.items=r.items+v.count;r.kinds=r.kinds+1 end
r.usedSlots=r.slots-r.freeSlots;r.fill=r.slots>0 and r.usedSlots/r.slots or 0
local x,y,p,n=rate()
r.trend={usedPerHour1=x,usedPerHour6=y,state=p>=3 and y>0 and 'growing' or n>=3 and 'shrinking' or 'stable'}
if r.trend.state=='growing' then r.trend.fullInHours=r.freeSlots/y end
revision=w.revision();cache=r;return r
end
function M.summary()
roll();local r=sum()
for _,v in ipairs(r.perStorage) do v.age=not v.beforeRestart and v.time and c.uptime()-v.time or nil end
return r
end
function M.item(i)
roll();local n,f=w.count(i),w.available(i);local x,y=rate(i)
return {count=n,free=f,reserved=n-f,where=w.find(i),perHour1=x,perHour6=y}
end
function M.settings() local t={};for k,v in pairs(C) do t[k]=v end;return t end
function M.set(k,v)
assert(C[k],'unknown setting '..tostring(k))
assert(type(v)=='number' and v>=0 and v<math.huge and (k=='fullSoonHours' or v<=1),
k..' must be '..(k=='fullSoonHours' and 'finite and >= 0' or 'between 0 and 1'))
assert((k~='fillWarn' or v<C.fillBad) and (k~='fillBad' or v>C.fillWarn),'fillWarn must be below fillBad')
if C[k]==v then return end
C[k]=v;db:put('settings',C);db:flush()
cache=nil
e.push('stats')
end
function M.warnings()
local r=M.summary();local out={}
if r.fill>=C.fillWarn then out[#out+1]={kind='fill',fill=r.fill} end
local h=r.trend.fullInHours
if h and h<=C.fullSoonHours then out[#out+1]={kind='fullSoon',hours=h} end
for _,v in ipairs(r.perStorage) do if v.fill>=C.fillWarn then out[#out+1]={kind='storageFill',name=v.name,fill=v.fill} end end
return out
end
local L,U={},sum().usedSlots
for _,v in ipairs(w.totals()) do L[key(v.item)]=v.count end
e.listen('warehouse',function(_,what)
if what~='changed' then return end
roll();local u=sum().usedSlots;B.u=B.u+u-U;U=u
local N={};for _,v in ipairs(w.totals()) do N[key(v.item)]=v.count end
for k in pairs(L) do if not N[k] then N[k]=0 end end
for k,v in pairs(N) do local d=v-(L[k] or 0);if d~=0 then B.i[k]=(B.i[k] or 0)+d end;if v==0 then N[k]=nil end end
L=N
end)
timer=e.timer(3600-c.uptime()%3600,roll,1)
return M
