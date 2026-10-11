local event=require('event')
local computer=require('computer')
local logistics=require('logistics')
local stats=require('stats')
local io=require('iochest')
local M={}
function M.start(world,observe,has,settings,seed)
 local known,held={},{}
 for _,v in ipairs(seed) do known[v[1]..':'..tostring(v[2])]=v end
 local function scan(kinds,fn)
  local seen={}
  fn(function(kind,key,on,text,due,machine,load)
   local k=kind..':'..tostring(key);seen[k]=true;known[k]={kind,key}
   observe(kind,key,on,text,due,machine,load)
  end)
  for k,v in pairs(known) do if kinds[v[1]] and not seen[k] then observe(v[1],v[2],false);known[k]=nil end end
 end
 local function drones()
  scan({droneLost=true,droneHeld=true},function(send)
   for _,d in ipairs(logistics.drones()) do
    send('droneLost',d.name,d.lost or d.state=='lost','Drone lost: '..d.name)
    local on=d.state=='held';held[d.name]=on and (held[d.name] or computer.uptime()) or nil
    send('droneHeld',d.name,on,'Cargo held: '..d.name,on and held[d.name]+settings().heldMinutes*60)
   end
  end)
 end
 local function machines()
  scan({machineStuck=true},function(send)
   for name,g in pairs(world.groups) do for _,l in ipairs(g.loads) do
    local pending=false;for _,n in pairs(l.remaining) do if n>0 then pending=true end end
    if l.due and l.duration then
     send('machineStuck',name..':'..l.sequence,pending and not l.quarantined,'Machine stuck: '..name,
       l.due+settings().stuckFactor*l.duration+.001,name,l.sequence)
    end
   end end
  end)
 end
 local function stock()
  local cfg=settings();local soon,bad=false,false
  for _,w in ipairs(stats.warnings()) do
   soon=soon or w.kind=='fullSoon';bad=bad or w.kind=='fill' and w.fill>=cfg.fillBad
  end
  observe('stockFull','stock',soon or bad or has('stockFull','stock') and stats.summary().fill>=cfg.fillBad-.02,'Stock full')
 end
 local function chests()
  scan({importBlocked=true,exportFull=true},function(send)
   for _,r in ipairs(io.list()) do
    local kind=r.role=='import' and 'importBlocked' or 'exportFull'
    send(kind,r.name,r.reason and r.reason:find(r.role=='import' and 'stock full' or 'chest full',1,true),r.reason)
   end
  end)
 end
 for _,name in ipairs({'logistics_drone','logistics','logistics_work','logistics_held','logistics_released'}) do event.listen(name,drones) end
 event.listen('mes_machine',machines)
 event.listen('warehouse',stock);event.listen('stats',stock);event.listen('io',chests)
 event.listen('mes',function(_,kind,id,state,item) if kind=='done' and state=='failed' then observe('runFailed',id,true,'Run failed: '..(item or id)) end end)
 return function() drones();machines();stock();chests() end
end
return M
