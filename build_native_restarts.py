"""Power-cycle cases over current MES assembly; no guest diagnostic wrappers."""
import argparse
import json
from pathlib import Path
from examples.mes.build_fixtures import build_native, write_fixture

CASES = ('mes-load', 'mes-collection', 'mes-robot', 'mes-trip',
         'drone-trip', 'robot-craft', 'mes-cargo')

CONTROLLER = r'''
local fs,event,computer=require('filesystem'),require('event'),require('computer')
local ser,component=require('serialization'),require('component')
local restartCase=assert(loadfile('/home/program/restart-case.lua'))()
local function save(path,value)
  local f=assert(io.open(path,'w'));assert(f:write(ser.serialize(value,false)));f:close()
end
local f=io.open('/home/r4-run.lua','r')
local record=f and assert(ser.unserialize(f:read('*a')))
if f then f:close() end
if record then
  local rc=assert(loadfile('/bin/rc.lua'));assert(rc('mes','start')~=1)
else
  assert(loadfile('/home/program/main.lua'))(function()
    local mes=require('mes')
    local id=assert(mes.run(assert(mes.plan('minecraft:brick_block',16))))
    record={id=id,case=restartCase};save('/home/r4-run.lua',record)
  end)
end
local mes,lg,wh=require('mes'),require('logistics'),require('warehouse')
local function wait(predicate)
  while not predicate() do event.pull() end
end
local function restart(reason)
  if fs.exists('/home/r4-trigger.lua') then return end
  save('/home/r4-trigger.lua',{case=restartCase,reason=reason})
  computer.shutdown(true)
end
local cycleTarget,recoveryStarted,recoveryFinished,carriedHome
local function lostAlert(state)
  for _,row in ipairs(require('mes_alerts').list()) do
    if row.kind=='droneLost' and row.key==cycleTarget and row.state==state then return row end
  end
end
event.listen('r4_drone_home',function() carriedHome=true end)
local function check()
  if restartCase=='drone-trip' and not recoveryStarted then
    if not cycleTarget then
      for _,stage in ipairs((mes.status(record.id) or {}).stages or {}) do
        for _,p in ipairs(stage.physicalJobs or {}) do
          local j=lg.status(p.job)
          if j and j.state=='active' and j.tripTimings[1] then
            cycleTarget=j.tripTimings[1].drone
            component.modem.broadcast(27103,'r4_fixture','r4_cycle_target',cycleTarget)
            break
          end
        end
        if cycleTarget then break end
      end
    end
    local lost
    for _,d in ipairs(lg.drones()) do
      if d.name==cycleTarget and d.state=='lost' and d.cargo and next(d.cargo) then lost=d end
    end
    if lost then
      recoveryStarted=true
      wait(function() return lostAlert('active') end)
      local blocked
      for _,j in ipairs(lg.jobs(true)) do
        local detail=lg.status(j.id)
        if detail.reason=='drone lost: '..cycleTarget then blocked=detail;break end
      end
      assert(blocked and #blocked.held>0,'lost cargo or blocked reason missing')
      save('/home/r4-trigger.lua',{case=restartCase,reason=blocked.reason,cargo=lost.cargo})
      -- A separate requested read must remain serviceable while one drone is lost.
      local id=assert(lg.job({{read='furnB.in'}},{drones=1,retries=0}))
      wait(function() return lg.status(id).state=='done' end)
      assert(lg.status(id).tripTimings[1].drone~=cycleTarget)
      save('/home/r4-carry-home-'..cycleTarget,{drone=cycleTarget})
      wait(function() return carriedHome end)
      assert(lg.found(cycleTarget))
      wait(function() return lostAlert('cleared') end)
      recoveryFinished=true
    end
    return
  end
  if fs.exists('/home/r4-trigger.lua') then return end
  for _,stage in ipairs((mes.status(record.id) or {}).stages or {}) do
    if restartCase=='mes-robot' and stage.kind=='robot' and stage.craftStarted and not stage.craftFinished then
      restart('robot craft active');return
    end
    for _,p in ipairs(stage.physicalJobs or {}) do
      local j=lg.status(p.job)
      if j and j.state=='active' then
        if restartCase=='mes-load' and stage.kind=='machine' and p.kind=='fetch' then
          restart('machine load delivery active');return
        elseif restartCase=='mes-collection' and p.kind=='collect' then
          restart('output collection active');return
        elseif restartCase=='mes-trip' then
          restart('MES-owned drone trip active');return
        end
      end
    end
  end
end
event.listen('mes',check)
event.listen('logistics',check)
event.listen('logistics_work',check)
event.listen('logistics_held',check)
event.listen('modem_message',function(_,_,_,port,_,_,kind,_,text)
  if restartCase=='mes-cargo' and port==27103 and kind=='report' and type(text)=='string' then
    local r=ser.unserialize(text)
    if r and r.state=='progress' and (r.held or 0)>0 then restart('drone reports physical cargo') end
  end
end)
check()
local outcome=assert(mes.wait(record.id))
assert(outcome.status=='complete',outcome.reason or outcome.error or outcome.status)
if restartCase:match('^mes%-') then assert(fs.exists('/home/r4-trigger.lua'),'restart phase not observed') end
if restartCase=='drone-trip' then assert(recoveryFinished,'lost/found operator sequence not observed') end
wait(function() for _,d in ipairs(lg.drones()) do if d.state~='idle' then return false end end;return true end)
assert(wh.count({name='minecraft:brick_block',damage=0})==16)
return 'Restart case complete: '..restartCase
'''

# Fault injection wraps only physical hardware. Production protocol/library
# calls and their results remain real; receipts are captured by the host.
ROBOT_INJECTION = r'''
local component,computer,fs=require('component'),require('computer'),require('filesystem')
local craft=component.crafting.craft
component.crafting.craft=function(...)
  local result=table.pack(craft(...))
  if not fs.exists('/home/r4-robot-cycled') then
    assert(io.open('/home/r4-robot-cycled','w')):close()
    computer.shutdown(true)
  end
  return table.unpack(result,1,result.n)
end
'''

DRONE_INJECTION = r'''
local ee=component.proxy(component.list('eeprom')())
local originalMove,originalPull=drone.move,computer.pullSignal
local selected=false
computer.pullSignal=function(...)
  local result=table.pack(originalPull(...))
  if result[1]=='modem_message' and result[4]==port and result[6]=='r4_fixture'
      and result[7]=='r4_cycle_target' and result[8]==name then selected=true end
  return table.unpack(result,1,result.n)
end
drone.move=function(...)
  local result=originalMove(...)
  if selected and not ee.get():find('-- R4 power cycled',1,true) then
    for i=1,slots do if inv.getStackInInternalSlot(i) then
      ee.set(ee.get()..'\n-- R4 power cycled\n')
      computer.shutdown(true)
    end end
  end
  return result
end
'''


def build(root, case):
    if case not in CASES + ('baseline',): raise ValueError('unknown restart case')
    path = build_native(Path(root) / 'fixture', 'bricks16')
    if case == 'baseline': return path
    fixture = path.parent
    (fixture / 'program/restart.lua').write_text(CONTROLLER)
    (fixture / 'program/restart-case.lua').write_text("return '" + case + "'\n")
    value = json.loads(path.read_text());value['id'] = 'restart-' + case
    value['controller']['program']['entry'] = 'restart.lua'
    if case == 'robot-craft':
        entry = fixture / 'robot-program/main.lua'
        entry.write_text(ROBOT_INJECTION + entry.read_text())
    if case == 'drone-trip':
        entry = fixture / 'program/usr/lib/logistics/agent.lua'
        text = entry.read_text();marker = 'local function encode(v)'
        assert marker in text
        entry.write_text(text.replace(marker, DRONE_INJECTION + '\n' + marker, 1))
        indices = sorted(range(len(value['drones'])), key=lambda i: sum(
            (a-b)**2 for a,b in zip(value['drones'][i]['position'], value['controller']['position'])))
        value['droneActions'] = [{'action': 'move_drone', 'drone': index,
            'to': value['drones'][index]['position'],
            'request': {'computer': 0, 'marker': f'home/r4-carry-home-d{number}',
                        'signal': 'r4_drone_home'}} for number,index in enumerate(indices, 1)]
    return write_fixture(path, value)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--case', choices=CASES + ('baseline',), required=True)
    args = parser.parse_args()
    print(build(args.root, args.case))
