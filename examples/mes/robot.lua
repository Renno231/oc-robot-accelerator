assert(loadfile('/home/program/install.lua'))()
local component=require('component');local event=require('event')
component.modem.open(27105)
-- Repeat announcement on query, including after cproc has entered its loop.
event.listen('modem_message',function(_,_,sender,port,_,token)
  if port==27105 and token=='mes_robot_query' then
    component.modem.send(sender,27105,'mes_robot_ready',component.modem.address)
  end
end)
component.modem.broadcast(27105,'mes_robot_ready',component.modem.address)
assert(loadfile('/usr/bin/cproc.lua'))('--side=3')
