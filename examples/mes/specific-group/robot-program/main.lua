assert(loadfile('/home/program/install.lua'))()
local component=require('component');local event=require('event')
local computer=require('computer');local hosts=require('hosts')
local fixtureName='cpu1'
local fixtureWake='T13Fixture-'..fixtureName
-- Harness-only pairing-equivalent address books; production lookup uses hosts.
assert(hosts.addHost(component.modem.address,computer.address(),fixtureName,fixtureWake,{service='craftServer'}))
component.modem.open(27105)
-- Repeat announcement on query, including after cproc has entered its loop.
event.listen('modem_message',function(_,_,sender,port,_,token,cid,wake)
  if port==27105 and token=='mes_robot_query' then
    assert(hosts.addHost(sender,cid,'controller',wake,{},true))
    component.modem.send(sender,27105,'mes_robot_ready',component.modem.address,fixtureName,computer.address(),fixtureWake)
  end
end)
component.modem.broadcast(27105,'mes_robot_ready',component.modem.address,fixtureName,computer.address(),fixtureWake)
assert(loadfile('/usr/bin/cproc.lua'))('--side=3')
