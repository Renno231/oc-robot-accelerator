-- Native acceptance: assembly, public setup calls, then the production MES.
-- Wire capture and persisted receipt analysis belong to the host runner.
local run=... -- Specialized cases share this assembly, registration and recipe setup.
local fs=require('filesystem')
local event=require('event')
local function install(source,target)
  fs.makeDirectory(target)
  for name in fs.list(source) do
    local a,b=fs.concat(source,name),fs.concat(target,name)
    if fs.isDirectory(a) then install(a,b) else assert(fs.copy(a,b)) end
  end
end
install('/home/program/usr','/usr')
install('/home/program/etc','/etc')
package.path='/usr/lib/?.lua;/usr/lib/?/init.lua;'..package.path
local function wait(predicate)
  while true do local value=predicate();if value then return value end;event.pull() end
end
local distances={}
event.listen('modem_message',function(_,_,address,_,distance)
  distances[address]=distance
end)
-- Invoke rc in this boot process, not a subprocess that closes store handles.
local rc=assert(loadfile('/bin/rc.lua'))
assert(rc('mes','enable')~=1);assert(rc('mes','start')~=1)
local mes,lg,wh=require('mes'),require('logistics'),require('logistics.warehouse')
local case=assert(loadfile('/home/program/case.lua'))()
local ocparts=case.name=='ocparts' or case.name=='ocparts-repeat' or case.name=='robot-parts' or case.name=='robot-expand'
local setup=assert(loadfile('/home/program/setup.lua'))()
if case.name=='shortfall' then wh.remove('s7_3_S') end
local drones=wait(function() local rows=lg.pending();if #rows==6 then return rows end end)
table.sort(drones,function(a,b) return assert(distances[a])<assert(distances[b]) end)
for i,address in ipairs(drones) do assert(lg.register(address,'d'..i,setup.homes[i])) end
wait(function()
  for _,drone in ipairs(lg.drones()) do if drone.state~='idle' then return end end
  return true
end)
local function done(id)
  return wait(function()
    local result=assert(lg.status(id))
    if result.state~='active' and result.state~='queued' and wh.settled(id) then return result end
  end)
end
for _,id in ipairs(wh.scan()) do assert(done(id).state=='done') end
local robots=wait(function() local rows=mes.pendingRobots();if #rows==case.robots then return rows end end)
table.sort(robots,function(a,b) return assert(distances[a.address])<assert(distances[b.address]) end)
for i,robot in ipairs(robots) do
  local name='cpu'..i
  assert(mes.registerRobot(robot.address,name,name..'.buf'))
end
-- Registration returns before the announced transport's first status arrives.
-- Wait on the same cached resource view the MES displays, without querying it.
wait(function()
  local rows=mes.resources().crafters
  for i=1,case.robots do if not rows['cpu'..i] or rows['cpu'..i].state~='idle' then return end end
  return true
end)
assert(mes.setType('furnace',{inputs={'input'},output='output',roles={'input','fuel','output'},
  roleSlots={input={1},fuel={1},output={1}},fuel={role='fuel',item='minecraft:coal',per=8},
  batch=case.batch,seconds=case.seconds,blocking=true})) -- One input slot: another recipe waits; same-recipe top-ups remain allowed.
local function item(id)
  local name,damage=id:match('^(.*):(%d+)$')
  return {name=name or id,damage=tonumber(damage) or 0}
end
if case.name=='concurrent-fetch' then
  local a=assert(wh.fetch(item('minecraft:clay_ball'),64,'furnA.in',{drones=1,retries=0}))
  local b=assert(wh.fetch(item('minecraft:clay_ball'),64,'furnB.in',{drones=1,retries=0}))
  for _,id in ipairs({a,b}) do local r=done(id);assert(r.state=='done' and r.moved==64) end
else
  fs.makeDirectory('/usr/lib/oredict')
  assert(require('liblz16').open('/usr/lib/oredict/oredict.dblz','wb')):close()
  local file=assert(io.open('/home/program/recipes.tsv','r'))
  local archive=assert(require('liblz16').open('/usr/lib/recipes/misc.dblz','wb'))
  assert(archive:write(file:read('*a')));file:close();archive:close()
  local builder=require('recipes.build');local db=builder.build();assert(builder.save(db))
  local recipes=require('recipes');recipes.install(db)
  assert(recipes.registerProcessingRecipe('minecraft:coal:1','furnace',{recipe={'minecraft:log'},qty=1}))
  assert(recipes.registerProcessingRecipe('minecraft:brick','furnace',{recipe={'minecraft:clay_ball'},qty=1}))
  if ocparts then assert(loadfile('/home/program/ocparts-imports.lua'))() end
  if run then return run(wait,done) end
  if case.orders then
    for _,order in ipairs(case.orders) do
      local plan=assert(mes.plan(order[1],order[2]))
      assert(#plan.missing==0,'missing materials for '..order[1])
      local result=assert(mes.wait(assert(mes.run(plan))))
      assert(result.status=='complete',result.reason or result.error)
    end
    for _,order in ipairs(case.orders) do
      assert(wh.count(item(order[1]))==order[2],'wrong parts count: '..order[1])
    end
    if case.name=='robot-expand' then
      local map=require('logistics.map')
      map.add('11:65:2',11,65,2,{faces={[3]=true}})
      map.add('12:65:2',12,65,2,{faces={[2]=true}})
      map.link('10:65:2','11:65:2');map.link('11:65:2','12:65:2')
      map.name('assembly','11:65:2',3);map.name('cpu3.buf','12:65:2',2);map.save()
      for _,order in ipairs(case.orders) do
        local result=done(assert(wh.fetch(item(order[1]),order[2],'assembly')))
        assert(result.state=='done' and result.moved==order[2],'parts pickup failed')
      end
      -- Host staging performs the player's assembly/installation/placement only.
      assert(io.open('/home/assemble-robot','w')):close()
      assert(event.pull('robot_assembled'))
      local robot=wait(function() local pending=mes.pendingRobots();if #pending==1 then return pending[1] end end)
      assert(mes.registerRobot(robot.address,'cpu3','cpu3.buf'))
      wait(function() local cpu=mes.resources().crafters.cpu3;return cpu and cpu.state=='idle' end)
      local ids={}
      for i,order in ipairs({{'opencomputers:component:11',2,'cpu3'},
                            {'minecraft:chest',1,'cpu1'},{'minecraft:chest',1,'cpu2'}}) do
        local plan=assert(mes.plan(order[1],order[2]));assert(#plan.missing==0)
        for n,stage in ipairs(plan.stages) do
          if stage.kind=='robot' then assert(mes.choose(plan,n,order[3])) end
        end
        ids[i]=assert(mes.run(plan))
      end
      for _,id in ipairs(ids) do local result=assert(mes.wait(id));assert(result.status=='complete',result.reason or result.error) end
      assert(wh.count(item('opencomputers:component:11'))==2)
      assert(wh.count(item('minecraft:chest'))==2)
    end
  else
  local target=case.name=='torches16' and 'minecraft:torch' or
    (case.name=='cake' and 'minecraft:cake') or
    (case.name=='order-control' and 'minecraft:planks') or
    (ocparts and 'opencomputers:component:6' or 'minecraft:brick_block')
  local plan=assert(mes.plan(target,case.name=='stockkeeper' and 8 or case.quantity))
  if case.name=='specific-group' then
    for i,stage in ipairs(plan.stages) do if stage.kind=='machine' then assert(mes.choose(plan,i,'furnaceA')) end end
  elseif case.name=='shortfall' then
    assert(io.open('/home/warehouse-remove-items','w')):close()
    assert(event.pull(10,'warehouse_items_removed'),'native stock removal missing')
  end
  local ids
  if case.name=='order-control' then
    for i in ipairs(plan.stages) do assert(mes.choose(plan,i,'cpu1')) end
    local first=assert(mes.run(plan))
    local other=assert(mes.plan('minecraft:stick',4))
    for i in ipairs(other.stages) do assert(mes.choose(other,i,'cpu1')) end
    local second=assert(mes.run(other))
    assert(mes.status(first).status=='running')
    for _,s in ipairs(mes.status(second).stages) do assert(s.state=='waiting') end
    local shell=require('shell')
    assert(shell.execute('mes runs'))
    assert(shell.execute('mes status '..second))
    assert(shell.execute('mes stop '..second))
    local stopped=assert(mes.wait(second))
    assert(stopped.status=='failed' and stopped.reason=='Stopped by player')
    for _,s in ipairs(stopped.stages) do assert(not s.craftStarted) end
    assert(wh.count(item('minecraft:stick'))==0)
    ids={first}
  elseif case.name=='stockkeeper' then
    local plans,keeper=require('craft.plans'),require('craft.stockkeeper')
    assert(plans.save('Bricks',plan))
    assert(keeper.save('Bricks',{item=target,quantity=16,trigger='replacement',
      source={kind='plan',name='Bricks'}}))
    assert(keeper.enable('Bricks'))
    wait(function()
      local s=assert(keeper.status('Bricks'));local r=s.lastResult
      assert(not r or r.success or r.status=='skipped',r and r.message)
      return wh.count(item(target))==16 and not s.busy
    end)
    assert(keeper.disable('Bricks'))
    ids={}
  elseif case.name=='merged-kit' or case.name=='selected-kit' then
    local plans,kits=require('craft.plans'),require('craft.kits')
    local torches=assert(mes.plan('minecraft:torch',16))
    if case.name=='selected-kit' then
      for _,entry in ipairs({{plan,'cpu2','furnaceA'},{torches,'cpu1','furnaceB'}}) do
        for i,s in ipairs(entry[1].stages) do assert(mes.choose(entry[1],i,s.kind=='robot' and entry[2] or entry[3])) end
      end
    end
    assert(plans.save('Bricks',plan))
    assert(plans.save('Torches',torches))
    assert(kits.save('Build',{executionMode='merged',accounting=case.name=='selected-kit' and 'refresh' or 'saved',entries={
      {binding='live',planName='Bricks'},assert(kits.pin('Torches'))}}))
    local result=kits.run('Build');assert(result.success,result.message)
    assert(result.completedEntries==2 and #result.entries==1)
    ids={result.entries[1].runId}
  elseif ocparts then
    -- The foreground submitter exits; only the rc service owns the running plan.
    local file=assert(io.open('/home/native.plan','w'))
    assert(file:write(require('serialization').serialize(plan,false)));file:close()
    file=assert(io.open('/home/submit.lua','w'))
    assert(file:write([[local mes=require('mes')
local id=assert(mes.run('/home/native.plan'))
local f=assert(io.open('/home/submitted-id','w'));assert(f:write(tostring(id)));f:close()
return 0
]]));file:close()
    assert(require('shell').execute('/home/submit.lua'))
    file=assert(io.open('/home/submitted-id','r'));local id=assert(tonumber(file:read('*a')));file:close()
    assert(mes.status(id).status=='running','submitter did not exit mid-run')
    ids={id}
  else ids={assert(mes.run(plan))} end
  if case.name=='concurrent' then ids[2]=assert(mes.run(assert(mes.plan('minecraft:torch',16)))) end
  for _,id in ipairs(ids) do
    if case.name=='shortfall' then
      wait(function()
        local status=mes.status(id)
        assert(status.status=='running',status.reason or 'shortage abandoned the order')
        for _,stage in ipairs(status.stages) do
          if stage.kind=='robot' then assert(not stage.craftStarted) end
          if stage.kind=='machine' and stage.done==48 and
            (stage.detail or ''):find('Waiting for minecraft:clay_ball',1,true) then return true end
        end
      end)
      assert(wh.count(item('minecraft:brick'))==48)
      local refill=assert(lg.transfer(item('minecraft:clay_ball'),16,'s7_3_S','s0_0_N'))
      assert(done(refill).state=='done') -- Its normal warehouse receipt wakes the same order.
    end
    local result=assert(mes.wait(id))
    assert(result.status=='complete',result.reason or result.error)
  end
  assert(wh.count(item(target))==case.quantity,'wrong output count')
  if case.name=='ocparts-repeat' then
    -- Same live service and stock: the first order's surplus feeds the next.
    local id=assert(mes.run(assert(mes.plan(target,3))))
    local result=assert(mes.wait(id));assert(result.status=='complete',result.reason or result.error)
    assert(wh.count(item(target))==8,'second order did not add three components')
  end
  if case.name=='concurrent' or case.name=='merged-kit' or case.name=='selected-kit' then assert(wh.count(item('minecraft:torch'))==16) end
  if case.name=='cake' then assert(wh.count(item('minecraft:bucket'))==3,'empty buckets not returned') end
  end
end
wait(function()
  for _,drone in ipairs(lg.drones()) do if drone.state~='idle' then return end end
  return true
end)
return 'MES PASS: '..case.name
