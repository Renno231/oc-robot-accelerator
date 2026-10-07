-- Native OC controller acceptance: actual warehouse/map/logistics, test-only
-- GPU buffer, and computer.pushSignal keys. qmenu is the unmodified user file.
return function(done,wait)
local fs=require('filesystem');local computer=require('computer');local event=require('event')
local component=require('component');local unicode=require('unicode');local keys=require('keyboard').keys
local tty=require('tty');local wh=require('warehouse');local lg=require('logistics');local map=require('map')
fs.makeDirectory('/lib/warehouse')
for _,name in ipairs({'view','ui'}) do assert(fs.copy('/home/program/lib/warehouse/'..name..'.lua','/lib/warehouse/'..name..'.lua')) end
assert(fs.copy('/home/program/lib/qmenu.lua','/lib/qmenu.lua'))
local freeBeforeUI=computer.freeMemory();local view=require('warehouse.view')
local iron={name='minecraft:iron_ingot',damage=0}
local function snapshot()
  local state={members=wh.members(),groups=wh.groups(),storages=map.storages(),contents={},jobs=lg.jobs(),drones=lg.drones(),now=computer.uptime()}
  for name in pairs(state.storages) do state.contents[name]=wh.contents(name) end;return state
end
local function has(model,key) for _,r in ipairs(model.rows) do if r.key==key then return r end end end
local state=snapshot()
assert(wh.count(iron)==382)
for _,size in ipairs({{50,16},{160,50}}) do
  local m=view.build(state,{kind='items',top=true},size[1],size[2]);assert(m.rows[1].count==nil)
  local foundIron=false;for _,r in ipairs(m.rows) do if r.value and r.value.name==iron.name then assert(r.text:find('382',1,true),'item row count');foundIron=true end end
  assert(foundIron and m.total==2,'distinct catalogue items')
  local rows=view.items(state);assert(rows[1].count>=rows[2].count,'descending item sort')
  local f=view.build(state,{kind='items',search='iron'},size[1],size[2]);assert(f.total==1,'substring filter')
  assert(view.build(state,{kind='items',search='no such item'},size[1],size[2]).total==0)
  local st=view.build(state,{kind='storages',top=true},size[1],size[2]);assert(st.total==68 and st.pages==math.ceil(68/(size[2]-6)))
  local last=view.build(state,{kind='storages',page=st.pages},size[1],size[2]);assert(last.page==st.pages)
  for _,r in ipairs(st.rows) do assert(unicode.len(r.text)<=size[1]) end
end
assert(view.clip('abé中→z',6)=='abé中→' and view.clip('abé中→z',5)=='abé中' and view.clip('é',0)=='','UTF-8/display-width clipping')
local synthetic={members=state.members,groups=state.groups,storages=state.storages,contents=state.contents,jobs={{id=2,state='queued'},{id=1,state='done'}},drones=state.drones,now=state.now}
assert(has(view.build(synthetic,{kind='job',job=2},160,50),'cancel'))
assert(not has(view.build(synthetic,{kind='job',job=1},160,50),'cancel'))
assert(view.build(synthetic,{kind='jobs'},160,50).rows[1].value==2,'newest job first')
synthetic.jobs={{id=3,state='failed',item=iron,held={{drone='d1',count=3,item=iron}},
  blockedReports={{link={a='A',b='B'},leg={a='H',b='B'},links={{a='A',b='B'}},offset=1.25,stalledSeconds=5}}}}
local blocked=view.build(synthetic,{kind='job',job=3},160,50)
assert(has(blocked,'blocked:1').text:find('A→B',1,true) and has(blocked,'blockedOffset:1').text:find('1.25',1,true),'blocked report details')
assert(has(blocked,'held:1').text:find('d1',1,true) and not has(blocked,'cancel'),'held cargo details/cancel availability')
synthetic.jobs[1].reason=string.rep('é',90)
assert(has(view.build(synthetic,{kind='job',job=3},50,16),'reason:line:2'),'long full job reason was clipped instead of paged')
assert(has(view.build(state,{kind='storage',storage='s0_0_N'},160,50),'membership'))
local selected=view.storageRows(state)[50].key
assert(has(view.build(state,{kind='storages',selected=selected},50,16),selected),'logical selection page')

state=nil;synthetic=nil;blocked=nil
-- OC does not expose collectgarbage to applications. Its kernel performs a
-- full collection every ten native resumes; yield a bounded number of turns
-- after the allocation-heavy headless cases before loading the UI modules.
for n=1,30 do event.pull(0) end

assert(not component.isAvailable('gpu') and not component.isAvailable('screen') and not component.isAvailable('keyboard'),'runner unexpectedly has native UI hardware')
local gpu={address='warehouse-test-gpu'};local w,h,depth=50,16,4;local fg,bg=3,5;local fp,bp=true,true
local buffer,cells,rowCache={},{},{};local writes=0
function gpu.getResolution() return w,h end
function gpu.setResolution(x,y) w,h=x,y;rowCache={};return true end
function gpu.getDepth() return depth end
function gpu.getForeground() return fg,fp end
function gpu.getBackground() return bg,bp end
function gpu.setForeground(v,p) local old=fg;fg,fp=v,p or false;return old end
function gpu.setBackground(v,p) local old=bg;bg,bp=v,p or false;return old end
function gpu.getScreen() return 'warehouse-test-screen' end
function gpu.getViewport() return w,h end
function gpu.setViewport(x,y) w,h=x,y;rowCache={};return true end
function gpu.bind() return true end
function gpu.set(x,y,text)
  assert(y>=1 and y<=h,'GPU y outside buffer');assert(x>=1,'GPU x outside buffer');writes=writes+1
  buffer[y]=buffer[y] or {};local changed=false
  for n=1,unicode.len(text) do
    assert(x+n-1<=w,'GPU text exceeds width');local char=unicode.sub(text,n,n);local id=char..':'..fg..':'..bg
    if not buffer[y][x+n-1] or buffer[y][x+n-1][1]~=char then changed=true end
    cells[id]=cells[id] or {char,fg,bg};buffer[y][x+n-1]=cells[id]
  end
  if changed then rowCache[y]=nil end;return true
end
function gpu.fill(x,y,width,height,char) for line=y,y+height-1 do gpu.set(x,line,string.rep(char,width)) end;return true end
function gpu.copy(x,y,width,height,tx,ty)
  local copy={};for line=0,height-1 do copy[line]={};for col=0,width-1 do copy[line][col]=buffer[y+line] and buffer[y+line][x+col] end end
  for line=0,height-1 do
    for col=0,width-1 do buffer[y+line+ty]=buffer[y+line+ty] or {};buffer[y+line+ty][x+col+tx]=copy[line][col] end
    rowCache[y+line+ty]=nil
  end;return true
end
function gpu.get(x,y) local cell=buffer[y] and buffer[y][x];return cell and cell[1] or ' ',cell and cell[2] or fg,cell and cell[3] or bg end
local function line(y)
  if not rowCache[y] then local out={};for x=1,w do out[x]=gpu.get(x,y) end;rowCache[y]=table.concat(out) end
  return rowCache[y]
end
local proxy=component.proxy;component.proxy=function(address) if address==gpu.address then return gpu end;return proxy(address) end
local oldGpu=rawget(component,'gpu');component.gpu=gpu
local oldTtyGpu=tty.window.gpu;tty.bind(gpu);tty.setViewport(47,14,1,1,3,2)
local ui=require('warehouse.ui');require('qmenu')
local freeAfterLibrary=computer.freeMemory();local minimumFree=freeAfterLibrary
local result={sessions=0,renders=0,view=true,live=false,restored=true,monochrome=false}
local function key(k,char) computer.pushSignal('key_down','warehouse-test-keyboard',char or 0,k,'test') end
local function session(script,inputs,sessionOptions)
  sessionOptions=sessionOptions or {};local index,steps,pending=1,0,false;local oldView={tty.getViewport()}
  local oldFg,oldFp=gpu.getForeground();local oldBg,oldBp=gpu.getBackground()
  local options={input=function(prompt,default,menu)
    assert(inputs and #inputs>0,'unexpected text input: '..prompt);local text=table.remove(inputs,1)
    local field=menu:getOption('input');gpu.set(field:x(),field:y(),view.fit(text,w)) -- imitate the terminal's direct writes
    return text
  end,onRender=function(model,s,menu,cause)
    steps=steps+1;assert(steps<1000,'UI script hung at step '..index);result.renders=result.renders+1
    minimumFree=math.min(minimumFree,computer.freeMemory())
    assert(line(1):find('Warehouse',1,true),'header missing')
    assert(line(2):find('members',1,true),'status missing')
    for _,r in ipairs(model.rows) do assert(line(r.y)==r.text,'row buffer mismatch: '..r.key..' '..line(r.y)) end
    if pending and cause~=pending then return end
    pending=false
    local command=script[index];assert(command,'UI script exhausted')
    if command.check then command.check(model,s,menu,line) end
    if command.wait then if not command.wait(model,s,menu,line) then return end end
    if command.key then index=index+1;pending='key_down';key(command.key,command.char)
    elseif command.signal then index=index+1;pending=command.signal;computer.pushSignal(command.signal,table.unpack(command.args or {}))
    elseif command.row then
      assert(not command.kind or command.kind==s.kind,'wrong screen at '..index..': '..s.kind)
      local target
      for _,r in ipairs(model.rows) do if r.key==command.row or type(command.row)=='function' and command.row(r) then target=r.key;break end end
      if not target then pending='key_down';key(keys.pageDown);return end
      if menu:getSelected().name~=target then pending='key_down';key(keys.down);return end
      index=index+1;pending='key_down';key(keys.enter)
    end
  end}
  for k,v in pairs(sessionOptions) do options[k]=v end
  local ok,err=ui.show(options);assert(ok,err);assert(index>#script,'UI exited early at '..index)
  assert(fg==oldFg and bg==oldBg and fp==oldFp and bp==oldBp,'UI did not restore colours/palette mode')
  local restored={tty.getViewport()};for n,v in ipairs(oldView) do assert(restored[n]==v,'UI did not restore viewport') end
  assert(not inputs or #inputs==0,'unused text input');result.sessions=result.sessions+1
end
local function itemRow(r) return r.action=='item' and r.value.name==iron.name end
-- Session 1: navigation and wrapped back option, four top-level tabs.
local beforeDirty
session({{signal='warehouse',args={'changed'},check=function() beforeDirty=writes end},
  {key=keys.slash or 53,char=47,check=function() assert(writes==beforeDirty,'unchanged screen redrawn');result.dirty=true end},
  {row='input',kind='input'},
  {key=keys.slash or 53,char=47,check=function(model,s) assert(s.kind=='items' and model.total==1,'UI search did not filter') end},
  {row='input',kind='input'},
  {key=keys.up,check=function(model) assert(model.total==2,'empty UI search did not clear') end},
  {row='back',check=function(_,_,menu) assert(menu:getSelected().name=='back','list wrap') end}}, {'iron',''})
session({{key=keys.right},{key=keys.right,check=function(_,s) assert(s.kind=='storages') end},
  {key=keys.right,check=function(_,s) assert(s.kind=='machines') end},{key=keys.q,check=function(_,s) assert(s.kind=='jobs') end}},nil)
-- Session 2: fetch 10 to a nonmember (remove temporarily), then completion
-- redraws the item total without sending any key; selected logical row stays.
wh.remove('s7_3_S');local fetched
session({{row=itemRow,kind='items'},{row='fetch',kind='item'},{row='storage:s7_3_S',kind='pick'},
  {row='input',kind='input'},{row='yes',kind='confirm'},
  {wait=function(model,s,menu)
    if not fetched then local jobs=lg.jobs();fetched=jobs[1].id end
    local j=lg.status(fetched);if j.state~='done' then return false end
    assert(j.moved==10);assert(model.title:find('Total: 372',1,true),'live total did not update')
    assert(menu:getSelected().name=='fetch','live logical selection changed');result.live=true;return true
  end,key=keys.q},{key=keys.q}}, {'10'})
done(fetched)
local fetchedState=snapshot();local detail=view.build(fetchedState,{kind='job',job=fetched},160,50)
assert(has(detail,'stepItem:1').text:find(iron.name,1,true) and has(detail,'stepCounts:1').text:find('taken=10',1,true),'real per-step job details')
fetchedState=nil;detail=nil
for _,j in ipairs(lg.jobs(true)) do
  assert(not j.steps and not j.scan and not j.blockedReports,'compact enumeration copied a read packet')
  local full=lg.status(j.id);assert(j.state==full.state and j.moved==full.moved and j.requested==full.requested,'compact counters changed')
  if j.id==fetched then j.item.name='mutated';assert(lg.status(fetched).steps[1].item.name==iron.name,'summary exposed private job tables') end
end
assert(done(lg.transfer(iron,10,'s7_3_S','s7_0_N',{drones=1,retries=0})).state=='done')
wh.add('s7_3_S');assert(wh.count(iron)==382)
-- Session 3: public config changes from UI; typed filter and priority.
session({{key=keys.right},{row='storage:furnace-output',kind='storages',check=function(model)
    local r=assert(has(model,'storage:s0_0_N'));assert(buffer[r.y][1][2]==0x55CC55,'member mark colour')
  end},{row='membership',kind='storage'},
  {row='filter',kind='storage'},{row='typed',kind='filter'},{row='input',kind='input'},{row='input',kind='input'},
  {key=keys.q,check=function() assert(wh.members()['furnace-output'].filter[1].name==iron.name) end},
  {row='priority',kind='storage'},{row='input',kind='input'},
  {key=keys.q,check=function() assert(wh.members()['furnace-output'].priority==17);assert(loadfile('/bin/warehouse.lua'))('members') end},{key=keys.q}}, {iron.name,'0','17'})
wh.remove('furnace-output')
-- Session 4: a furnace with input/fuel/output roles, delete with confirm.
session({{key=keys.right},{key=keys.right},{row='new',kind='machines'},{row='input',kind='input'},
  {row='typed',kind='pick'},{row='input',kind='input'},
  {row='add',kind='pick'},{row='input',kind='input'},{row='storage:furnace-input',kind='pick'},
  {row='add',kind='pick'},{row='input',kind='input'},{row='storage:furnace-fuel',kind='pick'},
  {row='add',kind='pick'},{row='input',kind='input'},{row='storage:furnace-output',kind='pick'},
  {row='finish',kind='pick'},
  {row='machine:ui-furnace',kind='machines',check=function(model,_,menu)
    local g=assert(wh.groups()['ui-furnace']);assert(g.type=='furnace' and g.roles.input=='furnace-input' and g.roles.fuel=='furnace-fuel' and g.roles.output=='furnace-output')
    if menu:getSelected().name~='machine:ui-furnace' then local r=assert(has(model,'machine:ui-furnace'));assert(buffer[r.y][1][2]==0x55CCCC,'group colour') end
  end},
  {row='delete',kind='machine'},{row='yes',kind='confirm'},{key=keys.q,check=function() assert(not wh.groups()['ui-furnace']) end}},
  {'ui-furnace','furnace','input','fuel','output'})
-- Session 5: hold both real drones on long go routes so the third job is queued.
local steps={};for n=1,4 do steps[#steps+1]={go='FT'};steps[#steps+1]={go='H'} end
local busy1=lg.job(steps,{drones=1});local busy2=lg.job(steps,{drones=1})
wait(function() return lg.status(busy1).state=='active' and lg.status(busy2).state=='active' end,120)
local queued=lg.job({{read='s0_0_N'}},{drones=1})
session({{key=keys.right},{key=keys.right},{key=keys.right},{row='job:'..queued,kind='jobs'},
  {row='cancel',kind='job'},{key=keys.q,check=function() assert(lg.status(queued).reason=='cancelled') end},{key=keys.down},
  {key=keys.q,check=function(model) local r=assert(has(model,'job:'..queued));assert(buffer[r.y][1][2]==0xFF5555,'failed job colour') end}},nil)
done(busy1);done(busy2)
-- Session 6: failure stays in footer and UI remains usable.
session({{row=itemRow},{row='fetch'},{row='storage:s7_3_S'},{row='input'},{row='yes'},
  {key=keys.q,check=function(_,_,_,lines) assert(lines(h):find('requested 9999',1,true),'API error footer missing') end},{key=keys.q}}, {'9999'})
-- Session 7: interrupted exits from a detail screen, including depth 1.
depth=1
session({{row=itemRow},{signal='interrupted',check=function(_,_,menu)
  local o=menu:getSelected();local c=buffer[o:y()][1];assert(c[2]==0 and c[3]==0xFFFFFF,'monochrome selection inversion');result.monochrome=true
end}},nil)
-- Explicit unexpected render error also restores all borrowed state.
local v={tty.getViewport()};local oldFg,oldBg=fg,bg
local ok,err=ui.show({onRender=function() error('test render failure') end});assert(not ok and err:find('test render failure',1,true))
assert(fg==oldFg and bg==oldBg);local restored={tty.getViewport()};for n,value in ipairs(v) do assert(restored[n]==value) end
result.errorRestored=true
gpu.setResolution(160,50)
session({{key=keys.right},{key=keys.right},{key=keys.right},{key=keys.q}},nil)
result.writes=writes
result.memory={freeBeforeUI=freeBeforeUI,freeAfterLibrary=freeAfterLibrary,minimumFree=minimumFree,freeAfterUI=computer.freeMemory(),total=computer.totalMemory()}
component.gpu=oldGpu;component.proxy=proxy;tty.window.gpu=oldTtyGpu
buffer=nil;cells=nil;rowCache=nil
for n=1,30 do event.pull(0) end
-- Compare both implementations on the restored, real 64-inventory catalogue.
-- Run after the UI so its fake pixel buffer and initial model snapshots need
-- not coexist with the second warehouse library during module compilation.
local listen=event.listen;event.listen=function() return true end
local beforeWh=assert(loadfile('/home/program/warehouse-before.lua'))();event.listen=listen
local plan,job=lg.plan,lg.job;local planning={}
lg.job=function(steps) return steps end
for _,variant in ipairs({'before','after'}) do
  local api=variant=='before' and beforeWh or wh;planning[variant]={}
  for _,kind in ipairs({'fetch','store'}) do
    local calls=0;lg.plan=function(...) calls=calls+1;return plan(...) end
    local start=os.clock();local value,err
    if kind=='fetch' then value,err=api.fetch(iron,10,'s7_3_S') else value,err=api.store(iron,10,'s7_3_S') end
    local elapsed=os.clock()-start;assert(value,err)
    planning[variant][kind]={cpuSeconds=elapsed,plans=calls}
  end
end
lg.plan=plan;beforeWh=nil
assert(planning.after.fetch.plans<planning.before.fetch.plans and planning.after.store.plans<planning.before.store.plans)
local pf=assert(io.open('/home/ui-planning.lua','w'));pf:write(require('serialization').serialize(planning));pf:close()
-- Real Theta* unreachable-source fallback, and fallback to another face of a
-- shared inventory for store. Do not submit these dry-run plans.
for _,other in ipairs({'N6_0','N7_1','FT'}) do map.unlink('N7_0',other) end
local fallback=assert(wh.fetch(iron,10,'s7_3_S'));assert(fallback[1].take=='s4_0_N','unreachable highest-count source was not skipped')
for _,other in ipairs({'N6_0','N7_1','FT'}) do map.link('N7_0',other) end
wh.add('shared',{inventory='chest00',priority=100});map.unlink('alias','H')
fallback=assert(wh.store(iron,10,'s7_3_S'));assert(fallback[2].put=='s0_0_N','unreachable chosen face was not skipped')
map.link('alias','H');wh.add('shared',{inventory='chest00'})
lg.job=job;result.unreachable=true
-- Exactly one catalogue signal per finished handler, and after config edits.
while event.pull(0) do end
local changes=0;local function changed(_,kind) assert(kind=='changed');changes=changes+1 end
event.listen('warehouse',changed)
wh.group('ui-signal','test',{role='furnace-output'});assert(event.pull(0,'warehouse'));assert(changes==1)
wh.ungroup('ui-signal');assert(event.pull(0,'warehouse'));assert(changes==2)
wh.add('furnace-output');assert(event.pull(0,'warehouse'));assert(changes==3)
wh.remove('furnace-output');assert(event.pull(0,'warehouse'));assert(changes==4)
assert(done(lg.job({{read='s0_0_N'}},{drones=1})).state=='done')
assert(event.pull(0,'warehouse'));assert(changes==5 and not event.pull(0,'warehouse'),'duplicate/missing catalogue signal')
event.ignore('warehouse',changed);result.signals=true
local f=assert(io.open('/home/warehouse-ui-results.lua','w'));f:write(require('serialization').serialize(result));f:close()
print('warehouse UI native acceptance passed',result.sessions,result.renders)
end
