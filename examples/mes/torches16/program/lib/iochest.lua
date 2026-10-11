local st=require('stations')
local wh=require('warehouse')
local lg=require('logistics')
local event=require('event')
local ser=require('serialization')
local disk=require('store').open('/etc/io','log')
local rows=disk:load()
local M,aliases,sizes,seen={},{},{},{}
local function key(i) return i.name..':'..(i.damage or 0) end
local function copy(v) return ser.unserialize(ser.serialize(v)) end
local function save(r)
 disk:put(r.name,r);disk:flush();event.push('io',r.name,next(r.pending) and 'active' or r.reason and 'partial' or 'idle',r.reason)
end
local function sync()
 aliases={};sizes={}
 for _,v in ipairs(st.list()) do local s=st.get(v.name)
  if s.state=='ready' and (s.spec.role=='import' or s.spec.role=='export') then
   for i,m in ipairs(s.members) do
    local pair=s.spec.pair or 1;local n=s.members[math.floor((i-1)/pair)*pair+1].storage
    aliases[m.storage]=n;sizes[n]=s.sizes[n]
    if not rows[n] then rows[n]={name=n,role=s.spec.role,listing={},pending={}};save(rows[n]) end
   end
  end
 end
end
local function row(n,role)
 sync();local r=rows[aliases[n]];assert(r and (not role or r.role==role),'invalid IO role');return r
end
local function add(out,i,n)
 local k=key(i);local e=out[k] or {item={name=i.name,damage=i.damage or 0,label=i.label},count=0}
 e.count=math.max(0,e.count+n);out[k]=e
end
local function listing(raw)
 local out={};for _,v in pairs(raw or {}) do add(out,v,v.size) end;return out
end
local function balance(r,sign)
 local out=copy(r.listing);for _,p in pairs(r.pending) do for _,v in pairs(p.a) do add(out,v.item,sign*v.count) end end;return out
end
local function remember(r,ids,read)
 for _,id in ipairs(ids) do local counts={}
  for _,s in ipairs(lg.status(id).steps or {}) do if s.take then add(counts,s.item,s.count) end end
  r.pending[id]={a=counts,read=read}
 end
end
local function import(r)
 local req={};for _,v in pairs(balance(r,-1)) do if v.count>0 then req[#req+1]=v end end
 r.reason=nil
 if #req>0 then
  local ids,err=wh.collect(r.name,req,{partial=true});if not ids then r.reason=err else remember(r,ids) end
  for _,v in pairs(balance(r,-1)) do
   if v.count>0 then r.reason=r.reason or ('stock full: '..v.count..' '..(v.item.label or v.item.name)..' left in '..r.name) end
  end
 end;save(r)
end
local function report(r,p)
 if p.state=='setup' then if r.reason~=p.reason then r.reason=p.reason;save(r) end
 elseif (not r.refresh or p.reply==r.refresh) and (not r.seq or p.seq>r.seq) then r.seq=p.seq;r.listing=listing(p.listing);r.reason=nil
  local ready=p.reply==r.refresh;if ready then r.refresh=nil end
  if r.role=='import' and ready then import(r) else save(r) end
 end
 lg.ackSensor(r.sensor,p.seq)
end
function M.list()
 sync();local out={};for n in pairs(sizes) do out[#out+1]=copy(rows[n]) end
 table.sort(out,function(a,b) return a.name<b.name end);return out
end
function M.attach(sensor,n)
 local r=row(n);if r.sensor then return r.sensor==sensor or nil,'inventory already has sensor '..r.sensor end
 local p=seen[sensor];if not p then return nil,'waiting for sensor report' end
 if p.size~=sizes[r.name] then return nil,p.reason or ('sensor sees '..tostring(p.size)..' slots, expected '..sizes[r.name]) end
 for _,v in pairs(rows) do if v.sensor==sensor then return nil,'sensor already attached to '..v.name end end
 r.sensor=sensor;r.seq=nil;report(r,p);return true
end
function M.importNow(n)
 local r=row(n,'import');if r.sensor then if not r.refresh then import(r) end;return true end
 local ids=wh.scan(r.name);remember(r,ids,true);save(r);return ids[1]
end
function M.markEmptied(n)
 local r=row(n,'export');assert(not r.sensor,'sensor reports the chest');r.listing={};r.reason=nil;save(r);return true
end
local function fetch(req,n,one,opts)
 local r=row(n,'export');local stock=balance(r,1)
 local free=sizes[r.name];for _,v in pairs(stock) do free=free-math.ceil(v.count/(wh.stackSize(v.item) or 64)) end
 local out={};r.reason=nil
 for _,v in ipairs(req) do local k=key(v.item);local max=wh.stackSize(v.item) or 64;local old=stock[k] and stock[k].count or 0
  local slots=math.ceil(old/max);local count=math.min(v.count,math.max(0,(free+slots)*max-old))
  if count<v.count then r.reason='export chest full: take items from '..r.name end
  if count>0 then out[#out+1]={item=v.item,count=count};free=free-math.ceil((old+count)/max)+slots;stock[k]={item=v.item,count=old+count} end
 end
 local ids,err={}
 if #out>0 then if one then local id;id,err=wh.fetch(out[1].item,out[1].count,r.name,opts);ids=id and {id}
  else ids,err=wh.fetchMany(out,r.name,opts) end
  if ids then remember(r,ids) end
 end
 r.reason=err or r.reason;save(r);if one then return ids and ids[1],r.reason end;return ids,r.reason
end
function M.fetch(i,count,n,opts) return fetch({{item=i,count=count}},n,true,opts) end
function M.fetchMany(req,n,opts) return fetch(req,n,false,opts) end
local function completed(_,id)
 local s=lg.status(id);if not s or s.state=='queued' or s.state=='active' then return end
 for _,r in pairs(rows) do if r.pending[id] then
  if r.pending[id].read then
   for _,v in ipairs(s.steps or {}) do if v.listing then r.listing=listing(v.listing) end end
   r.pending[id]=nil;if s.state=='done' then import(r) else r.reason=s.reason;save(r) end
  else
   if not r.sensor then for _,v in ipairs(s.steps or {}) do if r.role=='export' and v.put or r.role=='import' and v.take then
    add(r.listing,v.item,r.role=='export' and (v.moved or 0) or -(v.taken or 0)+(v.returned or 0))
   end end
   if s.state~='done' then r.reason=r.reason or s.reason or (r.role=='export' and 'export chest full: take items from '..r.name or 'collection shortfall') end end
   r.pending[id]=nil
   if r.sensor then r.refresh=id;r.reason=nil;lg.ackSensor(r.sensor,id,'status') end;save(r)
  end
 end end
end
event.listen('station',sync)
event.listen('logistics',completed)
event.listen('logistics_sensor',function(_,name,kind,payload)
 if kind~='report' then return end;local p=ser.unserialize(payload);seen[name]=p
 for _,r in pairs(rows) do if r.sensor==name then report(r,p) end end
end)
sync();for _,r in pairs(rows) do for id in pairs(r.pending) do completed(nil,id) end
 if r.refresh then lg.ackSensor(r.sensor,r.refresh,'status') end
end
return M
