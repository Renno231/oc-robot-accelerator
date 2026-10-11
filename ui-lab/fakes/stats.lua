-- UI-lab fake of drone-logistics stats: same calls, field names, settings
-- check (same error text) and warnings rule. Scenarios (launcher arg
-- stats<name>): 76 (default; 412/540 slots, growing, full in ~3 h), 96 (bad,
-- full within 2 h), empty (no storages, no items), unread (76 with 3 stock
-- members never read). Sand: 64 reserved, in three storages. Used slots
-- follow the item total, so a fetch changes the summary.
local D=require("lab_data");local wh=require("warehouse");local computer=require("computer")
local M={};local C={fillWarn=.8,fillBad=.95,fullSoonHours=2}
local scenarios={
  ["76"]={n=20,used=412,u1=48,u6=42.7,state="growing",unknown=0},
  ["96"]={n=20,used=518,u1=20,u6=18,state="growing",unknown=0},
  empty={n=0,used=0,u1=0,u6=0,state="stable",unknown=0},
  unread={n=20,used=412,u1=48,u6=42.7,state="growing",unknown=3}}
local sc,t0,items0
local function total() local n,k=0,0;for _,v in ipairs(D.items) do if v.count>0 then n=n+v.count;k=k+1 end end;return n,k end
function M.labScenario(name)
  sc=assert(scenarios[name],"unknown stats scenario");t0=computer.uptime()
  if name=="empty" then for k=#D.items,1,-1 do D.items[k]=nil end end
  items0=total()
end
M.labScenario("76")
-- Ages in seconds; -50 is an entry observed before a restart (uptime clock).
local ages={8,75,300,1500,7200,90000,-50}
function M.summary()
  local items,kinds=total();local n=sc.n;local slots=n*27
  local used=math.max(0,math.min(slots,sc.used+(items-items0)//64))
  local names={};for s in pairs(D.members) do if s:match("^s%d") then names[#names+1]=s end end;table.sort(names)
  local r={slots=slots,freeSlots=slots-used,usedSlots=used,fill=slots>0 and used/slots or 0,items=items,kinds=kinds,storages=n+sc.unknown,unknown=sc.unknown,perStorage={}}
  local base,rem=used//math.max(1,n),used%math.max(1,n);local d=math.max(0,math.min(5,27-base-1,base))
  local off={d,-d,d//2,-(d//2),0}
  for i=1,n do
    local u=base+(i<=rem and 1 or 0)+off[(i-1)%5+1]
    local top={};for j=0,2 do local e=D.items[(i+7*j-1)%#D.items+1];if e and e.count>0 then top[#top+1]={item=e.item,count=e.count} end end
    table.sort(top,function(x,y) return x.count>y.count end)
    r.perStorage[i]={name=names[i],slots=27,freeSlots=27-u,fill=u/27,top=top,age=ages[(i-1)%#ages+1]<0 and -50 or ages[(i-1)%#ages+1]+computer.uptime()-t0}
  end
  r.trend={usedPerHour1=sc.u1,usedPerHour6=sc.u6,state=sc.state}
  if sc.state=="growing" then r.trend.fullInHours=r.freeSlots/sc.u6 end
  return r
end
local trend={["minecraft:sand"]={64,21.3},["minecraft:cobblestone"]={-128,-40.5}}
function M.item(i)
  local n=wh.count(i);local res=i.name=="minecraft:sand" and math.min(n,64) or 0;local t=trend[i.name] or {0,0}
  return {count=n,free=n-res,reserved=res,where=wh.find(i),perHour1=t[1],perHour6=t[2]}
end
function M.settings() local t={};for k,v in pairs(C) do t[k]=v end;return t end
function M.set(k,v)
  assert(C[k] and type(v)=='number' and v>=0 and v<math.huge and (k=='fullSoonHours' or v<=1),'invalid setting')
  C[k]=v
end
function M.warnings()
  local r=M.summary();local out={}
  if r.fill>=C.fillWarn then out[#out+1]={kind='fill',fill=r.fill} end
  local h=r.trend.fullInHours
  if h and h<=C.fullSoonHours then out[#out+1]={kind='fullSoon',hours=h} end
  for _,v in ipairs(r.perStorage) do if v.fill>=C.fillWarn then out[#out+1]={kind='storageFill',name=v.name,fill=v.fill} end end
  return out
end
return M
