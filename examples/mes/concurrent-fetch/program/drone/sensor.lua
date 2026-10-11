local modem,token,controller,_,port=...
local tr=component.proxy(component.list('transposer')())
local function enc(v)
 if type(v)=='table' then local o={'{'};for k,a in pairs(v) do o[#o+1]='['..enc(k)..']='..enc(a)..',' end;o[#o+1]='}';return table.concat(o)
 elseif type(v)=='string' then return string.format('%q',v) else return tostring(v) end
end
local side,size,reason
for s=0,5 do local n=tr.getInventorySize(s);if n and n>0 then if side then reason='several inventories' end;side=s;size=n end end
reason=reason or not side and 'no chest'
local seq,last,prev,report,acked,poll,retry,reply=0,nil,nil,nil,nil,0,0
local function send() if report then modem.send(controller,port,token,'report',enc(report));retry=computer.uptime()+10 end end
while true do
local now=computer.uptime()
if now>=poll then
  poll=now+2
  if reason then if not report then seq=seq+1;report={seq=seq,state='setup',reason=reason};send() end
  else
   local listing={};for slot,v in pairs(tr.getAllStacks(side).getAll()) do if v.size and v.size>0 then listing[slot]={name=v.name,damage=v.damage,label=v.label,size=v.size} end end
   local hash=enc(listing)
   if hash==prev and hash~=last then seq=seq+1;report={seq=seq,size=size,listing=listing,reply=reply};reply=nil;last=hash;acked=false;send() end
   prev=hash
  end
 end
if not acked and now>=retry then send() end
local e={computer.pullSignal(math.max(0,math.min(poll,retry>now and retry or poll)-computer.uptime()))}
if e[1]=='modem_message' and e[3]==controller and e[4]==port and e[6]==token then
  if e[7]=='ack' and e[8]==seq then acked=true elseif e[7]=='status' then prev=nil;last=nil;poll=0;reply=e[8] end
 end
end
