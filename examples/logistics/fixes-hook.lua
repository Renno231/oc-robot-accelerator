-- Native L13 adversary/player-action fixture, never deployed in canonical code.
do
  local m,t,c,n,p=...
  local ee=component.proxy(component.list("eeprom")())
  local d=component.proxy(component.list("drone")())
  local inv=component.proxy(component.list("inventory_controller")())
  local initialLight=d.getLightColor()
  local send,pull=m.send,computer.pullSignal
  m.send=function(address,port,token,kind,id,data,...)
    local out={send(address,port,token,kind,id,data,...)}
    if n=="d1" and kind=="report" and id==0 and type(data)=="string" and data:find('"ready"',1,true) and ee.getLabel()=="L13 restarted" then
      assert(d.getLightColor()==initialLight and d.getStatusText()=="","found display not restored")
    end
    if n=="d1" and kind=="report" and type(data)=="string" and data:find('"progress"',1,true) and ee.getLabel()~="L13 restarted" then
      local f=load("return "..data,"=fixture","t",{});local result=f()
      if (result.taken or 0)>0 then
        ee.setLabel("L13 restarted");pull(0.2);computer.shutdown(true)
      end
    end
    return table.unpack(out)
  end
  computer.pullSignal=function(timeout)
    local e={pull(timeout)}
    if n=="d1" and e[1]=="modem_message" and e[3]==c and e[4]==p and e[6]==t then
      if e[7]=="fixture_home" then
        -- The controlled reboot occurs exactly at A. This hook stands in for
        -- a player carrying the lost drone to H, not production navigation.
        assert(d.getLightColor()==0xFF0000,"lost light not red")
        assert(d.getStatusText()=="LOST\nsee base","lost status text")
        d.move(0,0,-2)
        repeat pull(0.1) until d.getOffset()<0.02 and d.getVelocity()<0.02
        send(c,p,t,"fixture_placed",d.getLightColor())
        return
      elseif e[7]=="fixture_empty" then
        -- Player removes cargo into the fixture chest beside its charger.
        for i=1,d.inventorySize() do d.select(i);inv.dropIntoSlot(5,1,d.count(i)) end
        send(c,p,t,"fixture_emptied");return
      end
    end
    return table.unpack(e)
  end
end
