-- Programs download on boot.
local modem=component.proxy(component.list("modem")())
local ee=component.proxy(component.list("eeprom")())
local port=27103
modem.open(port)
local token,controller,name=ee.getData():match("^([^|]+)|([^|]+)|([^|]+)$")
if not token then
  while true do
    modem.broadcast(port,"lgx_hello",component.list("drone")() and "drone" or component.list("transposer")() and "sensor")
    local untilTime=computer.uptime()+1
    repeat
      local e={computer.pullSignal(math.max(0,untilTime-computer.uptime()))}
      if e[1]=="modem_message" and e[4]==port and e[6]=="lgx_pair" then
        local record=tostring(e[7]).."|"..e[3].."|"..tostring(e[8])
        if #record<=ee.getDataSize() and type(e[7])=="string" and #e[7]==6 and type(e[8])=="string" and not e[8]:find("|",1,true) then
          ee.setData(record)
          computer.shutdown(true)
        end
      end
    until computer.uptime()>=untilTime
  end
end
modem.setWakeMessage(token,true)
local parts,total={},nil
modem.send(controller,port,token,"boot",component.list("geolyzer")()~=nil)
local retry=computer.uptime()+5
while true do
  local e={computer.pullSignal(1)}
  if computer.uptime()>=retry then
    modem.send(controller,port,token,"boot",component.list("geolyzer")()~=nil);retry=computer.uptime()+5
  end
  if e[1]=="modem_message" and e[3]==controller and e[4]==port and e[6]==token then
    if e[7]=="code" then
      local i,n,s=e[8],e[9],e[10]
      if type(i)=="number" and type(n)=="number" and n>=1 and n<=16 and i>=1 and i<=n and i%1==0 and n%1==0 and type(s)=="string" and #s<=7000 and (not total or total==n) then
        total=n;parts[i]=s
      end
    elseif e[7]=="start" and total then
      local complete=true
      for i=1,total do if not parts[i] then complete=false end end
      if complete then
        local code=table.concat(parts);parts=nil
        local agent=assert(load(code,"=agent","t",_G));code=nil
        return agent(modem,token,controller,name,port,e[8],e[9],e[10])
      end
    end
  end
end
