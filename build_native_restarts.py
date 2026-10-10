"""Fixture-only power cycles through public OpenComputers shutdown(true)."""
import argparse
import json
from pathlib import Path
from build_machine_comparisons import prepare

CASES = ('mes-load', 'mes-collection', 'mes-robot', 'mes-trip',
         'drone-trip', 'robot-craft', 'mes-cargo')


def controller(source, case):
    prefix = source.split('local address,distances')[0]
    prefix = prefix.replace("{'map','logistics','warehouse'}", "{'cbor','store','map','logistics','warehouse'}")
    prefix = prefix.replace("local serialization=require('serialization');local component=require('component')",
        "local serialization=require('serialization');local component=require('component')\nlocal r4BootClock=os.time()/72")
    prefix = prefix.replace("local lg=require('logistics');local wh=require('warehouse');local mes=require('mes')",
        "local lg=require('logistics');local r4NavigationReadyClock=os.time()/72\nlocal wh=require('warehouse');local mes=require('mes')")
    prefix = prefix.replace("assert(hosts.addHost(component.modem.address,computer.address(),'controller',fixtureWake,{}))",
        "if not fs.exists('/home/r4-run.lua') then assert(hosts.addHost(component.modem.address,computer.address(),'controller',fixtureWake,{})) end")
    prefix = prefix.replace("assert(loadfile('/home/program/install.lua'))()",
                            "if not fs.exists('/home/r4-run.lua') then assert(loadfile('/home/program/install.lua'))()\n"
                            "else package.path='/usr/lib/?.lua;/usr/lib/?/init.lua;'..package.path end")
    setup = source.split('local address,distances')[1].split('local function scan(storages)')[0]
    setup = 'local address,distances' + setup
    helpers = source.split('local function scan(storages)')[1].split('local result={case=case')[0]
    helpers = ('local function scan(storages)' + helpers).replace('\nscan()\n', '\n')
    recipes = source.split("  -- Use the project's actual archive writer")[1].split("  if case=='specific-group'")[0]
    recipes = '  -- Use the project\'s actual archive writer' + recipes
    recipes = recipes.replace("local target=case=='torches16' and 'minecraft:torch' or 'minecraft:brick_block'",
                              "local target='minecraft:brick_block'")
    recipes = recipes.split('  result.rawTaskOrder=')[0]
    return prefix + helpers + "\nlocal restartCase='" + case + "'\n" + '''
local f=io.open('/home/r4-run.lua','r')
local record=f and serialization.unserialize(f:read('*a'))
if f then f:close() end
-- The harness rc task runs before the enabled mes service in rc.cfg.
-- Start the public service before asking it for a persisted run.
if record then
  assert(mes.start())
  local f=assert(io.open('/home/r4-clock.lua','r'));local clock=assert(serialization.unserialize(f:read('*a')));f:close()
  save('/home/r4-restart-window.lua',{shutdown=clock.shutdown,bootEntry=r4BootClock,
    navigationReady=r4NavigationReadyClock,serviceReady=os.time()/72})
end
if not record then
''' + setup + '\nscan()\n' + recipes + '''
  save('/home/mes.plan',plan)
  local id=assert(mes.run('/home/mes.plan',{crafter='cpu1',pollSeconds=0.2}))
  record={id=id,case=restartCase,started=computer.uptime()}
  save('/home/r4-run.lua',record)
end
local function restart(reason,detail)
  if fs.exists('/home/r4-trigger.lua') then return end
  save('/home/r4-trigger.lua',{case=restartCase,reason=reason,detail=detail,
    uptime=computer.uptime(),status=mes.status(record.id)})
  save('/home/r4-clock.lua',{shutdown=os.time()/72})
  computer.shutdown(true)
end
local recoveryStarted,recoveryFinished=false,false
local cycleTarget
local function recoveryFact(kind,data)
  local f=assert(io.open('/home/r4-recovery-sequence.lua-lines','a'))
  f:write(serialization.serialize({kind=kind,data=data,uptime=computer.uptime(),worldClock=os.time()/72}), '\\n');f:close()
end
local carriedHome=false
event.listen('r4_drone_home',function() carriedHome=true end)
local timer=event.timer(0.1,function()
  if restartCase=='drone-trip' and not recoveryStarted then
    if not cycleTarget then
      for _,stage in ipairs((mes.status(record.id) or {}).stages or {}) do
        for _,p in ipairs(stage.physicalJobs or {}) do
          local j=lg.status(p.job)
          if j and j.state=='active' and j.tripTimings[1] then
            cycleTarget=j.tripTimings[1].drone
            recoveryFact('selected',{drone=cycleTarget,job=p.job})
            component.modem.broadcast(27103,'r4_fixture','r4_cycle_target',cycleTarget)
            break
          end
        end
        if cycleTarget then break end
      end
    end
    local lost
    for _,d in ipairs(lg.drones()) do if d.name==cycleTarget and d.state=='lost' and d.cargo and next(d.cargo) then lost=d end end
    if lost then
      recoveryStarted=true
      local blocked,id
      for _,j in ipairs(lg.jobs(true)) do
        local detail=lg.status(j.id)
        if detail.reason=='drone lost: '..cycleTarget then blocked=detail;id=j.id;break end
      end
      assert(blocked and #blocked.held>0,'lost cargo or blocked reason missing')
      recoveryFact('lost',lost)
      recoveryFact('held recorded',{job=id,status=blocked})
      save('/home/r4-trigger.lua',{case=restartCase,reason='drone lost: '..cycleTarget,job=id,
        partial=blocked,cargo=lost.cargo,status=mes.status(record.id)})
      -- This diagnostic read proves another drone serves a job while the selected carrier is lost.
      local other=done(lg.job({{read='furnB.in'}},{drones=1,retries=0}))
      assert(other.state=='done' and other.tripTimings[1].drone~=cycleTarget,'fleet stopped serving other jobs')
      save('/home/r4-other-job.lua',other)
      recoveryFact('move_drone requested',{drone=cycleTarget,home=lost.home})
      save('/home/r4-carry-home-'..cycleTarget,{drone=cycleTarget,home=lost.home})
      wait(function() return carriedHome end,30)
      recoveryFact('move_drone completed',{drone=cycleTarget})
      assert(lg.found(cycleTarget))
      recoveryFact('Found',{drone=cycleTarget,job=id})
      save('/home/r4-found.lua',{drone=cycleTarget,job=id,uptime=computer.uptime()})
      recoveryFinished=true
    end
    return
  end
  if fs.exists('/home/r4-trigger.lua') then return end
  local status=mes.status(record.id)
  for _,stage in ipairs(status and status.stages or {}) do
    if restartCase=='mes-robot' and stage.kind=='robot' and stage.craftStarted and not stage.craftFinished then
      restart('robot craft active',stage);return
    end
    for _,p in ipairs(stage.physicalJobs or {}) do
      local j=lg.status(p.job)
      if j and j.state=='active' then
        if restartCase=='mes-load' and stage.kind=='machine' and p.kind=='fetch' then
          restart('machine load delivery active',{physical=p,job=j});return
        elseif restartCase=='mes-collection' and p.kind=='collect' then
          restart('output collection active',{physical=p,job=j});return
        elseif restartCase=='mes-trip' then
          restart('MES-owned drone trip active',{physical=p,job=j});return
        end
      end
    end
  end
end,math.huge)
event.listen('modem_message',function(_,_,sender,port,_,_,kind,id,text)
  if restartCase=='mes-cargo' and port==27103 and kind=='report' and type(text)=='string' then
    local r=serialization.unserialize(text)
    if r and r.state=='progress' and (r.held or 0)>0 then
      restart('drone reports physical cargo',{sender=sender,job=id,report=r})
    end
  end
end)
local outcome=assert(mes.wait(record.id))
if restartCase=='drone-trip' then recoveryFact('MES outcome',outcome) end
event.cancel(timer)
save('/home/mes-execution.lua',outcome)
assert(outcome.status=='complete',outcome.reason or outcome.error or outcome.status)
if restartCase:match('^mes%-') then assert(fs.exists('/home/r4-trigger.lua'),'restart phase not observed') end
if restartCase=='drone-trip' then assert(recoveryFinished,'lost/found operator sequence not observed') end
wait(function() for _,d in ipairs(lg.drones()) do if d.state~='idle' then return false end end;return true end,60)
scan()
assert(count('minecraft:brick_block')==16 and count('minecraft:clay_ball')==0 and count('minecraft:brick')==0 and count('minecraft:coal')==8,
  'final warehouse records disagree with requested physical production')
assert(not next(read('cpu1.buf')),'robot buffer not empty')
for _,n in ipairs({'A','B'}) do
  for _,s in pairs(read('furn'..n..'.in')) do assert(s.name=='minecraft:coal','unexpected furnace contents') end
end
save('/home/warehouse-results.lua',{case=restartCase,status=outcome.status,runId=record.id,
  afterScan={brick_block=count('minecraft:brick_block'),clay=count('minecraft:clay_ball'),brick=count('minecraft:brick'),coal=count('minecraft:coal')}})
'''


ROBOT_INJECTION = '''
-- Observation only, on the same world clock plus each machine's own uptime.
local serialization=require('serialization')
local function robotTrace(kind,data)
  local f=assert(io.open('/home/r4-robot-trace.lua-lines','a'))
  f:write(serialization.serialize({kind=kind,data=data,uptime=computer.uptime(),worldClock=os.time()/72}), '\\n');f:close()
end
robotTrace('boot',{cycled=require('filesystem').exists('/home/r4-robot-cycled')})
-- Preserve the harness-owned console across later boots.
local rc='/etc/rc.d/robot_runner.lua'
local f=assert(io.open(rc,'r'));local source=f:read('*a');f:close()
source=source:gsub("('/home/runner%-console.log', )'w'", "%1'a'")
f=assert(io.open(rc,'w'));f:write(source);f:close()
local api=require('api');local originalExpose=api.expose
api.expose=function(...)
  local args=table.pack(...)
  robotTrace('expose call',{name=args[1],port=args[3]})
  local result=table.pack(pcall(originalExpose,...))
  robotTrace('expose result',{ok=result[1],result=tostring(result[2])})
  if not result[1] then error(result[2],0) end
  return table.unpack(result,2,result.n)
end
local originalPrint=print
print=function(...)
  robotTrace('print',table.pack(...))
  return originalPrint(...)
end
-- One actual crafting operation occurs, then power is cycled before its receipt.
local originalCraft=component.crafting.craft
component.crafting.craft=function(...)
  local result=table.pack(originalCraft(...))
  if not require('filesystem').exists('/home/r4-robot-cycled') then
    local f=assert(io.open('/home/r4-robot-cycled','w'));f:write(tostring(computer.uptime()));f:close()
    robotTrace('shutdown after real craft',{result=result})
    computer.shutdown(true)
  end
  return table.unpack(result,1,result.n)
end
'''

CLIENT_DIAGNOSTICS = '''
-- Observe public calls/facts without changing their arguments, results or errors.
local diagnosticRequire=require
local clientObserved=false
local observedProxies={}
local function clientTrace(kind,data)
  local f=assert(io.open('/home/r4-client-trace.ndjson','a'))
  json(f,{kind=kind,data=data,uptime=computer.uptime(),worldClock=os.time()/72})
  f:write('\\n');f:close()
end
require=function(name)
  local value=diagnosticRequire(name)
  if name=='craft_client' and not clientObserved then
    clientObserved=true
    local install=value.install
    value.install=function(callback,options)
      clientTrace('install call',{options=options})
      return install(function(token,what,data)
        clientTrace('fact',{token=token,what=what,data=data})
        return callback(token,what,data)
      end,options)
    end
    for _,method in ipairs({'prepare','inspect'}) do
      local original=value[method]
      value[method]=function(...)
        clientTrace(method..' call',{args=table.pack(...)})
        local result=table.pack(pcall(original,...))
        if method=='prepare' and result[1] and type(result[2])=='table' then
          local entry=result[2]
          clientTrace('prepare result',{ok=true,result=tostring(entry),address=entry.address})
          if entry.proxy and not observedProxies[entry.proxy] then
            observedProxies[entry.proxy]=true
            local get=entry.proxy.getConnection;local previous
            entry.proxy.getConnection=function(...)
              local returned=table.pack(get(...))
              local connected=returned[1].connected
              if connected~=previous then
                previous=connected;clientTrace('getConnection result',{address=entry.address,connected=connected})
              end
              return table.unpack(returned,1,returned.n)
            end
          end
        else clientTrace(method..' result',{ok=result[1],values={result[2],result[3]}}) end
        if not result[1] then error(result[2],0) end
        return table.unpack(result,2,result.n)
      end
    end
  end
  return value
end
'''

HELD_DIAGNOSTICS = '''
-- Observe the designed held-return path without changing callback behaviour.
local function heldTrace(kind,data)
  local f=assert(io.open('/home/r4-held-trace.ndjson','a'))
  json(f,{kind=kind,data=data,uptime=computer.uptime(),worldClock=os.time()/72})
  f:write('\\n');f:close()
end
local heldCallback=false
local listen=event.listen
event.listen=function(name,callback)
  if name~='logistics_held' then return listen(name,callback) end
  heldTrace('handler registered',{})
  return listen(name,function(...)
    heldTrace('handler entry',{args=table.pack(...)})
    heldCallback=true
    local result=table.pack(pcall(callback,...))
    heldCallback=false
    heldTrace('handler result',{ok=result[1],values={result[2],result[3]}})
    if not result[1] then error(result[2],0) end
    return table.unpack(result,2,result.n)
  end)
end
local push=event.push
event.push=function(name,...)
  if name=='logistics_held' then heldTrace('held push',{args=table.pack(...)}) end
  return push(name,...)
end
local onError=event.onError
event.onError=function(message)
  heldTrace('event error',{message=tostring(message)})
  return onError(message)
end
event.listen('modem_message',function(_,_,sender,port,_,_,kind,id,text)
  if port==27103 and kind=='report' then
    heldTrace('report',{sender=sender,report=require('serialization').unserialize(text)})
  end
end)
local heldRequire=require
local heldObserved=false
require=function(name)
  local value=heldRequire(name)
  if name=='logistics' and not heldObserved then
    heldObserved=true
    for _,method in ipairs({'drones','job','plan','found'}) do
      local original=value[method]
      value[method]=function(...)
        local observed=heldCallback or method=='found'
        if observed then heldTrace(method..' call',{args=table.pack(...)}) end
        local result=table.pack(pcall(original,...))
        if observed then heldTrace(method..' result',{ok=result[1],values={result[2],result[3]}}) end
        if not result[1] then error(result[2],0) end
        return table.unpack(result,2,result.n)
      end
    end
  end
  return value
end
'''

DRONE_INJECTION = '''
-- Preserve the existing pairing data; the EEPROM code comment records one cycle.
local ee=component.proxy(component.list('eeprom')())
local originalMove=drone.move
local originalPull=computer.pullSignal
local r4Selected=false
computer.pullSignal=function(...)
  local result=table.pack(originalPull(...))
  if result[1]=='modem_message' and result[4]==port and result[6]=='r4_fixture'
      and result[7]=='r4_cycle_target' and result[8]==name then r4Selected=true end
  return table.unpack(result,1,result.n)
end
drone.move=function(...)
  local result=originalMove(...)
  if r4Selected and not ee.get():find('-- R4 power cycled',1,true) then
    local loaded=false
    for i=1,slots do if inv.getStackInInternalSlot(i) then loaded=true end end
    if loaded then
      ee.set(ee.get()..'\\n-- R4 power cycled\\n')
      computer.pullSignal(0.1)
      computer.shutdown(true)
    end
  end
  return result
end
'''


def build(root, case):
    root = Path(root)
    path = prepare('examples/mes/bricks16', root / 'fixture', 'coordinated')
    fixture = path.parent
    source = (fixture / 'program/native-main.lua').read_text()
    main = controller(source, case)
    (fixture / 'program/native-main.lua').write_text(main)
    observer = fixture / 'program/main.lua'
    text = observer.read_text().replace('local ok,err=xpcall', """
-- Retain each completed trip/read across MES boots and the 32-job retention window.
event.listen('logistics',function(_,id)
  local lg=package.loaded.logistics
  local status=lg and lg.status(id)
  if status then
    local f=assert(io.open('/home/r4-jobs.ndjson','a'))
    json(f,{id=id,status=status,boot=count+1});f:write('\\n');f:close()
  end
end)
event.listen('modem_message',function(_,_,sender,port,_,_,kind,id,text)
  if port==27103 and kind=='r4_wait' then
    local f=assert(io.open('/home/r4-route-waits.ndjson','a'))
    json(f,{sender=sender,trip=id,wait=assert(require('serialization').unserialize(text))});f:write('\\n');f:close()
  end
end)
local ok,err=xpcall""", 1)
    observer.write_text(text)
    if case == 'robot-craft':
        observer.write_text(text.replace('local ok,err=xpcall', CLIENT_DIAGNOSTICS + '\nlocal ok,err=xpcall', 1))
    elif case == 'drone-trip':
        observer.write_text(text.replace('local ok,err=xpcall', HELD_DIAGNOSTICS + '\nlocal ok,err=xpcall', 1))
    agent = fixture / 'program/drone/agent.lua'
    text = agent.read_text().replace('local function askRoute(from,to,blocked)\n',
        'local function askRoute(from,to,blocked)\n  local r4WaitStarted=os.time()/72\n', 1)
    text = text.replace('        return answer.route\n',
        '''        modem.send(controller,port,token,"r4_wait",activeTrip,encode({drone=name,
          started=r4WaitStarted,finished=os.time()/72,from=from,to=to,blocked=blocked~=nil}))
        return answer.route
''', 1)
    agent.write_text(text)
    if case == 'robot-craft':
        entry = fixture / 'robot-program/main.lua'
        text = entry.read_text().replace("fixtureName,fixtureWake,{service='craftServer'}))",
            "fixtureName,fixtureWake,{service='craftServer'},true))")
        text = text.replace("assert(loadfile('/home/program/install.lua'))()",
            "if not require('filesystem').exists('/home/r4-robot-cycled') then assert(loadfile('/home/program/install.lua'))() end", 1)
        text = text.replace("assert(loadfile('/usr/bin/cproc.lua'))", ROBOT_INJECTION + "\nassert(loadfile('/usr/bin/cproc.lua'))")
        entry.write_text(text)
    if case == 'drone-trip':
        entry = fixture / 'program/drone/agent.lua'
        text = entry.read_text().replace('local function encode(v)', DRONE_INJECTION + '\nlocal function encode(v)', 1)
        text = text.replace('local function report(id,data)\n',
            'local function report(id,data)\n  data.actualOffset=drone.getOffset()\n', 1)
        entry.write_text(text)
    value = json.loads(path.read_text())
    assert len(value['drones']) >= 6
    value['id'] = 'r4-' + case
    if case == 'drone-trip':
        # Pairing orders these fixture positions by controller distance.
        indices = sorted(range(len(value['drones'])), key=lambda i: sum(
            (a-b)**2 for a,b in zip(value['drones'][i]['position'], value['computer']['position'])))
        value['droneActions'] = [{'action': 'move_drone', 'drone': index,
            'to': value['drones'][index]['position'],
            'request': {'computer': 0, 'marker': f'home/r4-carry-home-d{number}',
                        'signal': 'r4_drone_home'}} for number,index in enumerate(indices, 1)]
    path.write_text(json.dumps(value, indent=2) + '\n')
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--case', choices=CASES + ('baseline',), required=True)
    args = parser.parse_args()
    print(build(args.root, args.case))
