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
local mes,lg,wh=require('mes'),require('logistics'),require('warehouse')
local case=assert(loadfile('/home/program/case.lua'))()
local setup=assert(loadfile('/home/program/setup.lua'))()
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
  if case.name=='ocparts' then assert(loadfile('/home/program/ocparts-imports.lua'))() end
  if run then return run(wait,done) end
  local target=case.name=='torches16' and 'minecraft:torch' or
    (case.name=='ocparts' and 'opencomputers:component:6' or 'minecraft:brick_block')
  local plan=assert(mes.plan(target,case.quantity))
  if case.name=='specific-group' then
    for i,stage in ipairs(plan.stages) do if stage.kind=='machine' then assert(mes.choose(plan,i,'furnaceA')) end end
  elseif case.name=='shortfall' then
    assert(io.open('/home/warehouse-remove-items','w')):close()
    assert(event.pull(10,'warehouse_items_removed'),'native stock removal missing')
  end
  local ids
  if case.name=='ocparts' then
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
    local result=assert(mes.wait(id))
    assert(result.status==(case.name=='shortfall' and 'failed' or 'complete'),result.reason or result.error)
    if case.name=='shortfall' then
      for _,stage in ipairs(result.stages) do
        if stage.kind=='robot' then assert(not stage.receipt and not stage.craftStarted) end
      end
    end
  end
  if case.name~='shortfall' then assert(wh.count(item(target))==case.quantity,'wrong output count') end
  if case.name=='concurrent' then assert(wh.count(item('minecraft:torch'))==16) end
end
wait(function()
  for _,drone in ipairs(lg.drones()) do if drone.state~='idle' then return end end
  return true
end)
return 'MES PASS: '..case.name
