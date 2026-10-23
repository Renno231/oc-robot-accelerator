"""Real MES/warehouse/logistics/store over continuing physical hardware doubles."""
from pathlib import Path
import unittest

import test_logistics_restart
import test_mes_ocparts_plan


class MesRestartTests(unittest.TestCase):
    def test_mes_log_rotation_handles_outlive_the_foreground_command(self):
        lua=self.start()
        lua.execute('''
          local root={data={handles={}}};local child={data={handles={}}};local current=child
          local process={}
          function process.info(level)
            if not level or level<=1 then return current end
            if level==2 and current==child then return root end
          end
          function process.removeHandle(h,p)
            local handles=(p or current).data.handles
            for i,v in ipairs(handles) do if v==h then return table.remove(handles,i) end end
          end
          function process.addHandle(h,p)
            local close=h.close;table.insert((p or current).data.handles,h)
            h.close=function(self,...)
              process.removeHandle(self,p);self.close=close;return close(self,...)
            end
            return h
          end
          package.loaded.process=process
          local open=io.open;local closed={}
          io.open=function(...)
            local h=open(...);if not h then return end
            local write,flush,close=h.write,h.flush,h.close
            h.write=function(self,...) assert(not closed[self],'closed command handle');return write(self,...) end
            h.flush=function(self,...) assert(not closed[self],'closed command handle');return flush(self,...) end
            h.close=function(self,...) local result=close(self,...);closed[self]=true;return result end
            return process.addHandle(h)
          end
          local unrelated=assert(io.open('/home/command-output','w'))
          local persist=require('mes.persist');local p=persist.open()
          for n=1,60 do persist.plan(p,{id=1,plan={marker=n},opts={}}) end
          assert(renames>0,'fixture did not exercise log compaction')
          assert(#child.data.handles==1 and child.data.handles[1]==unrelated,'MES retained command-owned files')
          while #child.data.handles>0 do child.data.handles[#child.data.handles]:close() end
          current=root
          persist.plan(p,{id=1,plan={marker=61},opts={}});p.store:flush()
          assert(p.store:load().plan_1.plan.marker==61 and closed[unrelated])
          p.store:close();assert(#root.data.handles==0)
        ''')

    def start(self, mode='log'):
        lua = test_logistics_restart.LogisticsRestartTests().start(mode)
        lib = (Path(__file__).parent / 'craftsystem/usr/lib').as_posix()
        lua.execute(f'package.path="{lib}/?.lua;{lib}/?/init.lua;"..package.path')
        for name in ('stats', 'housekeeping', 'survey'):
            lua.globals()[name.upper()] = Path(f'drone-logistics/usr/lib/logistics/{name}.lua').read_text()
        for name in ('alerts','alert_sources'):
            lua.globals()['MES_'+name.upper()] = Path('craftsystem/usr/lib/mes/'+name+'.lua').read_text()
        lua.execute(r'''
          package.preload.process=function()
            local root={data={handles={}}}
            return {info=function(level) if not level or level<=1 then return root end end}
          end
          TIME=10;BOOT=0;TIMERS={};PHYSICAL={};INV={source={['mod:raw']=100},input={},output={},buffer={}}
          package.preload["logistics.stations"]=function() return {} end
          package.preload["logistics.survey"]=function() return assert(load(SURVEY))() end
          package.preload["logistics.stats"]=function() return assert(load(STATS))() end
          package.preload["logistics.housekeeping"]=function() return assert(load(HOUSEKEEPING))() end
          package.preload["logistics.iochest"]=function() return {list=function() return {} end} end
          package.preload["mes.alerts"]=function() return assert(load(MES_ALERTS))() end
          package.preload["mes.alert_sources"]=function() return assert(load(MES_ALERT_SOURCES))() end
          local serialization=require('serialization');local serialize=serialization.serialize
          COUNTS={};local store=require('logistics.store');local open=store.open;local cbor=require('cbor')
          store.open=function(path,...)
            local s=open(path,...);local current={};local load,put,delete,flush=s.load,s.put,s.delete,s.flush
            local function count(field)
              local c=COUNTS[path] or {writes=0,flushes=0};COUNTS[path]=c;c[field]=c[field]+1
            end
            function s:load()
              local rows=load(self);current={};for k,v in pairs(rows) do current[k]=cbor.encode(v) end;return rows
            end
            function s:put(k,v)
              local bytes=cbor.encode(v);if current[k]~=bytes then count('writes');current[k]=bytes end
              return put(self,k,v)
            end
            function s:delete(k)
              if current[k] then count('writes');current[k]=nil end;return delete(self,k)
            end
            function s:flush() count('flushes');return flush(self) end
            return s
          end
          serialization.serialize=function(t,...)
            if type(t)=='table' and type(t[1])=='string' and type(t[2])=='number' then
              local key=t[1]..'/'..tostring(t[2])..'/'..tostring(t[3]);serial[key]=clone(t);return key
            end
            return serialize(t,...)
          end
          CFG={crafters={cpu={robot='robot'}},machineTypes={furnace={inputs={'input'},output='output',
            roles={'input','output'},roleSlots={input={1},output={1}},batch=1,seconds=1,blocking=true}}}
          local previous='dest'
          for i,name in ipairs({'input','output','buffer'}) do
            map.add(name,6+i*2,0,0);map.name(name..'_face',name,0)
            map.link(previous,name);previous=name -- Same collinear distances as the direct-flight stub.
          end
          local config={members={stock={filter={{name='mod:raw',damage=0},{name='mod:metal',damage=0},
            {name='mod:crafted',damage=0},{name='minecraft:brick',damage=0},
            {name='minecraft:brick_block',damage=0}}},input_face={},output_face={},buffer_face={}},groups={
            kiln={type='furnace',roles={input='input_face',output='output_face'}},
            cpu={type='crafter',roles={buffer='buffer_face'}}}}
          files['/etc/warehouse.cfg']=require('serialization').serialize(config)
          package.preload["mes.config"]=function() return {installRobots=function() end,config=function() return CFG end} end
          package.preload.recipes=function() return {getAll=function() return {} end} end
          package.preload.oredict=function() return {get=function() end,getByItemName=function() end} end
          package.preload["craft.tools"]=function() return {list=function() return {} end} end
          local computer=require('computer');computer.uptime=function() return TIME-BOOT end
          local event=require('event')
          event.timer=function(period,fn,times)
            TIMERS[#TIMERS+1]={period=period,fn=fn,at=TIME+period,times=times or 1};return #TIMERS
          end
          event.cancel=function(id) if TIMERS[id] then TIMERS[id].cancelled=true end end
          local raw={name='mod:raw',damage=0,label='Raw'}
          function held(node,id) return (INV[node] or {})[id] or 0 end
          function add(node,id,n) INV[node][id]=held(node,id)+n;assert(INV[node][id]>=0) end
          local function stack(id,n)
            local name,damage=id:match('^(.*):(%d+)$')
            return {name=name or id,damage=tonumber(damage) or 0,label=id,size=n,maxSize=64}
          end
          local function process()
            local recipe=MACHINE_RECIPE or {input='mod:raw',output='mod:metal'};local position=0
            while held('input',recipe.input)>0 do
              if recipe.fuel and (PROCESS_N or 0)%8==0 then
                if held('fuel','minecraft:coal')==0 then break end;add('fuel','minecraft:coal',-1)
              end
              PROCESS_N=(PROCESS_N or 0)+1;position=position+1;add('input',recipe.input,-1)
              PHYSICAL[#PHYSICAL+1]={at=TIME+position*(DELAY or 1),fn=function() add('output',recipe.output,1) end}
            end
          end
          function finishPhysical(deliver)
            assert(FAKE.working);local rows={};local cargo={};local carried=0
            for _,s in pairs(FAKE.cargo) do
              local id=require('item_identity').stackName(s);cargo[id]=s.size;carried=carried+s.size
            end
            for i,s in ipairs(FAKE.task.steps or {}) do
              local id=s.item and require('item_identity').stackName(s.item);local n=s.count or (s.rest and carried) or 0
              local row={moved=n,maxSize=64};rows[i]=row
              if s.read then
                row.read=s.read;row.size=27;row.listing={}
                for item,count in pairs(INV[s.read.node]) do if count>0 then row.listing[#row.listing+1]=stack(item,count) end end
              end
              if s.take then
                n=math.min(n,held(s.take.node,id));add(s.take.node,id,-n)
                row.taken=n;row.moved=n;cargo[id]=(cargo[id] or 0)+n;carried=carried+n
                row.short=n<(s.count or 0);row.left=held(s.take.node,id)
              end
              if s.put then
                id=id or next(cargo);n=math.min(n,cargo[id] or 0)
                add(s.put.node,id,n);cargo[id]=cargo[id]-n;carried=carried-n;row.moved=n
                if s.put.node=='input' or s.put.node=='fuel' then process() end
              end
            end
            FAKE.working=false;FAKE.held=0;FAKE.cargo={}
            FAKE.last={id=FAKE.trip,result={state='idle',steps=rows,held=0}}
            if deliver then report(FAKE.last.id,clone(FAKE.last.result));drain() end
          end
          ROBOT={};ROBOT_CALLS=0;ADOPTS=0;local sink
          local function receipt(token)
            local r=ROBOT
            if r.status=='RUNNING' then sink(token,'robot_progress',{address='robot',receipt={jobId=r.id,status='RUNNING'}})
            else sink(token,'robot_terminal',{address='robot',success=r.status=='COMPLETE',
              status=r.status=='COMPLETE' and 'complete' or r.status=='NOT_FOUND' and 'unknown' or 'failed',
              unknown=r.status=='NOT_FOUND' or nil,receipt={jobId=r.id,status=r.status,
                buffer=r.status=='COMPLETE' and clone(INV.buffer) or nil}}) end
          end
          package.preload["craft.client"]=function() return {
            install=function(cb) sink=cb;sink(nil,'robot_transport',{address='robot',state='ready'});return {{address='robot'}} end,
            tick=function() end,
            nextDue=function() end,
            inspect=function(token) sink(token,'robot_status',{address='robot',busy=ROBOT.status=='RUNNING'});return true end,
            status=function() return {busy=ROBOT.status=='RUNNING'} end,
            adopt=function(token,address,id) ADOPTS=ADOPTS+1;ROBOT.token=token;ROBOT.id=id;receipt(token);return true end,
            begin=function(token,address,plan,id)
              ROBOT_CALLS=ROBOT_CALLS+1;ROBOT={token=token,id=id,status='RUNNING'}
              sink(token,'robot_admitted',{address=address,jobId=id,disposition='accepted'})
              local physical=ROBOT
              PHYSICAL[#PHYSICAL+1]={at=TIME+1,robot=physical,fn=function()
                for _,t in ipairs(plan.tasks) do
                  local ops=t.qty_produced/t.recipeOutput
                  for _,item in pairs(t.recipe) do if item~='minecraft:air' then add('buffer',item,-ops) end end
                  add('buffer',t.item,t.qty_produced)
                end
                physical.status='COMPLETE';receipt(physical.token)
              end};return true
            end} end
          function restartRobot()
            for i=#PHYSICAL,1,-1 do if PHYSICAL[i].robot==ROBOT then table.remove(PHYSICAL,i) end end
            -- cproc's startup dump returns the unfinished craft's inventory.
            ROBOT.status='NOT_FOUND';receipt(ROBOT.token)
          end
          local catalogue=require('logistics.store').open('/etc/warehouse.db','log');catalogue:load()
          catalogue:put('stock',{items={raw={item=raw,count=100,maxSize=64,stacks=2,room=28}},
            slots=27,freeSlots=25,verified=true,time=TIME});catalogue:flush();catalogue:close()
          function reboot()
            BOOT=TIME;TIMERS={};LISTEN={};EVENTS={}
            for _,name in ipairs({'mes','mes.service','mes.state','mes.persist','logistics.warehouse','logistics','logistics.stats','logistics.survey','logistics.housekeeping','mes.alerts','mes.alert_sources'}) do package.loaded[name]=nil end
            lg=require('logistics');wh=require('logistics.warehouse');M=require('mes');assert(M.start{config=CFG})
            answerStatus();drain();require('mes.service').pump()
          end
          function step()
            TIME=TIME+0.1
            for i=#PHYSICAL,1,-1 do local p=PHYSICAL[i];if p.at<=TIME then table.remove(PHYSICAL,i);p.fn() end end
            if FAKE.working then finishPhysical(true) else drain() end
            for i=1,#TIMERS do local t=TIMERS[i];if not t.cancelled and TIME>=t.at then
              t.times=t.times-1;t.cancelled=t.times==0;t.at=TIME+t.period;t.fn()
            end end;drain();require('mes.service').pump()
          end
          function untilFact(fn)
            for i=1,2000 do if fn() then return end;step() end
            error('no fact: '..require('serialization').serialize(M.status()))
          end
          function submit(machine,quantity)
            local t={item=machine and 'mod:metal' or 'mod:crafted',qty_produced=quantity or 1,
              recipeOutput=1,recipe={'mod:raw'},node='n',input_nodes={'raw'},
              machineType=machine and 'furnace' or nil,isProcessing=machine and true or nil}
            return assert(M.run({tasks={t},requestItem=t.item,requestQuantity=t.qty_produced},{config=CFG}))
          end
          reboot()
          wh.observed('stock',{{item=raw,count=100,maxSize=64}})
          function saved()
            local cbor=require('cbor');local out={}
            for _,path in ipairs({'/etc/mes.state','/etc/mes.history'}) do
            if dirs[path] then
              for name,bytes in pairs(disk) do if name:sub(1,#path+1)==path..'/' then
                local key=name:sub(#path+2):gsub('%%(%x%x)',function(h) return string.char(tonumber(h,16)) end)
                out[key]=cbor.decode(bytes)
              end end
            else
              local bytes=disk[path] or '';local pos=1;local reader={}
              function reader:read(n) local value=bytes:sub(pos,pos+n-1);pos=pos+#value;return value end
              while pos<=#bytes do local row=cbor.decode_file(reader);out[row.k]=row.v end
            end
            end
            return out
          end
          function stage() return saved().st_1_1 end
        ''')
        return lua

    def test_complete_run_with_canonical_layers(self):
        lua = self.start()
        self.assertEqual(lua.execute('''
          local id=submit(true);untilFact(function() return M.status(id).status~='running' end)
          local r=M.status(id);assert(r.status=='complete',r.reason)
          return held('source','mod:metal'),held('source','mod:raw')
        '''), (1, 99))

    def test_complete_run_delivers_to_its_export_chest(self):
        lua = self.start()
        self.assertEqual(lua.execute('''
          local fetched
          package.loaded['logistics.iochest']={list=function() return {{name='out',role='export'}} end,
            fetch=function(i,n,to) fetched=i.name..' '..n..' '..to;return 7 end}
          local t={item='mod:metal',qty_produced=1,recipeOutput=1,recipe={'mod:raw'},node='n',
            input_nodes={'raw'},machineType='furnace',isProcessing=true}
          local id=assert(M.run({tasks={t},requestItem=t.item,requestQuantity=1},{config=CFG,deliver='out'}))
          untilFact(function() return M.status(id).status~='running' end)
          local r=M.status(id);assert(r.status=='complete',r.reason)
          return fetched,r.delivery and r.delivery.job,r.delivery and r.delivery.reason
        '''), ('mod:metal 1 out', 7, None))

    def test_waiting_for_stock_survives_restart_and_warehouse_read_wakes_order(self):
        for machine in (False, True):
            for mode in ('log', 'files'):
                with self.subTest(machine=machine, mode=mode):
                    lua = self.start(mode)
                    lua.globals().MACHINE = machine
                    lua.execute('''
                      INV.source['mod:raw']=0
                      wh.observed('stock',{});drain();require('mes.service').pump()
                      local id=submit(MACHINE)
                      untilFact(function() return (M.status(id).stages[1].detail or ''):find('Waiting for mod:raw',1,true) end)
                      assert(M.status(id).status=='running')
                      reboot()
                      assert(M.status(id).status=='running')
                      add('source','mod:raw',1)
                      assert(wh.scan('stock'))
                      untilFact(function() return M.status(id).status~='running' end)
                      assert(M.status(id).status=='complete',M.status(id).reason)
                      assert(held('source',MACHINE and 'mod:metal' or 'mod:crafted')==1)
                      assert(ROBOT_CALLS==(MACHINE and 0 or 1))
                    ''')

    def compare_restart(self, machine, predicate, setup='', two=False):
        for mode in ('log', 'files'):
            outcomes = []
            for restart in (False, True):
                with self.subTest(mode=mode, restart=restart):
                    lua = self.start(mode)
                    lua.globals().RESTART = restart
                    lua.execute(setup)
                    lua.globals().MACHINE = machine
                    lua.globals().TWO = two
                    result = lua.execute('''
                      first=submit(MACHINE);if TWO then second=submit(true) end
                      untilFact(function() return ''' + predicate + ''' end)
                      if RESTART then reboot() end
                      untilFact(function() return M.status(first).status~='running'
                        and (not second or M.status(second).status~='running') end)
                      local r=M.status(first);assert(r.status=='complete',r.reason)
                      if second then assert(M.status(second).status=='complete',M.status(second).reason) end
                      return held('source','mod:raw'),held('source','mod:metal'),held('source','mod:crafted'),
                        r.trips+(second and M.status(second).trips or 0),ROBOT_CALLS
                    ''')
                    outcomes.append(result)
            self.assertEqual(outcomes[0], outcomes[1])

    def test_restart_during_machine_load(self):
        self.compare_restart(True, "saved().grp_kiln and saved().grp_kiln.loading~=nil")

    def test_restart_during_collection(self):
        self.compare_restart(True, "saved().grp_kiln and saved().grp_kiln.collection~=nil")

    def test_restart_robot_keeps_crafting(self):
        self.compare_restart(False, "stage() and stage().phase=='robot_crafting'")

    def test_restart_during_robot_fetch(self):
        self.compare_restart(False, "stage() and stage().phase=='robot_fetching'")

    def test_restart_two_runs_sharing_machine(self):
        self.compare_restart(True, "saved().grp_kiln and #saved().grp_kiln.runs==2", two=True)

    def test_restart_with_stuck_machine_load(self):
        for mode in ('log', 'files'):
            outcomes=[]
            for restart in (False, True):
                lua=self.start(mode);lua.globals().RESTART=restart
                outcomes.append(lua.execute('''
                  DELAY=80;local old=submit(true)
                  untilFact(function() return M.status(old).status~='running' end)
                  assert(M.status(old).status=='failed');untilFact(function() return held('output','mod:metal')>0 end)
                  assert(saved().stuck_kiln and #saved().stuck_kiln==1);DELAY=1
                  if RESTART then reboot() end
                  local id=submit(true);untilFact(function() return M.status(id).status~='running' end)
                  local r=M.status(id);assert(r.status=='complete',r.reason)
                  return held('source','mod:raw'),held('source','mod:metal'),r.trips
                '''))
            self.assertEqual(*outcomes)

    def test_restart_keeps_output_check_and_retry_budget_and_due_time(self):
        for mode in ('log', 'files'):
            for phase in ('checking', 'idle'):
                outcomes = []
                for restart in (False, True):
                    with self.subTest(mode=mode, phase=phase, restart=restart):
                        lua = self.start(mode)
                        lua.globals().PHASE = phase
                        lua.globals().RESTART = restart
                        outcomes.append(lua.execute('''
                          DELAY=80;local id=submit(true)
                          untilFact(function()
                            local g=saved().grp_kiln
                            return g and g.outputRetried and g.phase==PHASE
                              and (PHASE~='checking' or g.outputRead.submitted)
                          end)
                          local before=saved()
                          local remaining=before.grp_kiln.loads[1].due-before.run_1.now
                          if RESTART then
                            reboot()
                            local after=saved()
                            assert(after.grp_kiln.outputRetried)
                            if PHASE=='idle' then
                              local state=require('mes.state');local nextDue=state.nextDue;local due
                              state.nextDue=function(w) due=nextDue(w);return due end
                              require('mes.service').pump();state.nextDue=nextDue
                              assert(math.abs(due-remaining)<0.001)
                            end
                          end
                          untilFact(function() return M.status(id).status~='running' end)
                          local r=M.status(id)
                          assert(r.status=='failed' and r.reason=='kiln: Machine produced no output after recovery')
                          assert(saved().stuck_kiln[1].unresolved['mod:metal']==1)
                          return r.trips,held('source','mod:raw'),held('source','mod:metal')
                        '''))
                self.assertEqual(outcomes[0], outcomes[1])

    def test_restart_during_recovery_scan(self):
        self.compare_restart(True, "saved().grp_kiln and saved().grp_kiln.recovery "
          "and saved().grp_kiln.recovery.phase=='reading' and saved().grp_kiln.recovery.read.submitted", setup='''
          DELAY=80;local old=submit(true)
          untilFact(function() return M.status(old).status~='running' end)
          assert(M.status(old).status=='failed');untilFact(function() return held('output','mod:metal')>0 end)
          assert(saved().stuck_kiln and #saved().stuck_kiln==1);DELAY=1
        ''')

    def test_restart_read_blocked_by_inflight_mutation(self):
        for mode in ('log', 'files'):
            outcomes=[]
            for restart in (False, True):
                with self.subTest(mode=mode, restart=restart):
                    lua=self.start(mode);lua.globals().RESTART=restart
                    outcomes.append(lua.execute('''
                      local ids=assert(wh.fetchMany({{item={name='mod:raw',damage=0},count=1}},'input_face'))
                      local scans=assert(wh.scan('stock'));drain()
                      assert(not wh.settled(ids[1]) and not wh.settled(scans[1]))
                      local function up(fn,key)
                        for i=1,50 do local name,value=debug.getupvalue(fn,i);if name==key then return value end end
                      end
                      local function blocked()
                        local callback=up(lg.onRead,'readObservers')['warehouse.role-cache']
                        assert(up(callback,'pendingReads')[scans[1]][1].blocked,'read provenance must be blocked')
                      end
                      blocked()
                      if RESTART then reboot() end
                      blocked()
                      -- A stale listing must remain unusable even after the mutation finishes.
                      untilFact(function() return wh.settled(ids[1]) end)
                      INV.source['mod:raw']=42
                      untilFact(function() return wh.settled(scans[1]) end)
                      assert(wh.count({name='mod:raw',damage=0})==99,'blocked read was applied')
                      return wh.count({name='mod:raw',damage=0}),lg.status(ids[1]).trips,lg.status(scans[1]).trips
                    '''))
            self.assertEqual(*outcomes)

    def test_robot_not_found_rereads_once_and_refetches_only_missing(self):
        for mode in ('log', 'files'):
            outcomes=[]
            for restart in (False, True):
                lua=self.start(mode);lua.globals().RESTART=restart
                outcomes.append(lua.execute('''
                  local id=submit(false);untilFact(function() return ROBOT.status=='RUNNING' end)
                  local oldId=ROBOT.id;restartRobot();if RESTART then reboot() end
                  untilFact(function() return M.status(id).status~='running' end)
                  local r=M.status(id);assert(r.status=='complete',r.reason)
                  assert(ROBOT_CALLS==2 and ROBOT.id~=oldId and ROBOT.id:match('^mes%-%d+%-%d+%-%d+$'))
                  local reads,fetches=0,0
                  for _,j in ipairs(lg.jobs()) do for _,s in ipairs(j.steps or {}) do
                    if s.read and s.read.node=='buffer' then reads=reads+1 end
                    if s.take and s.take.node=='source' then fetches=fetches+(s.taken or 0) end
                  end end
                  assert(reads==1 and fetches==1,'returned input must not be fetched again')
                  return held('source','mod:raw'),held('source','mod:crafted'),r.trips
                '''))
            self.assertEqual(*outcomes)

    def robot_remainder(self, partial, intermediate=False, bricks=False):
        for mode in ('log', 'files'):
            with self.subTest(mode=mode):
                lua=self.start(mode)
                lua.globals().PARTIAL=partial;lua.globals().INTERMEDIATE=intermediate;lua.globals().BRICKS=bricks
                lua.execute('''
                  local tasks={{item='mod:crafted',qty_produced=4,recipeOutput=1,
                    recipe={'mod:raw'},node='crafted',input_nodes={'raw'}}}
                  if INTERMEDIATE then tasks={
                    {item='mod:metal',qty_produced=4,recipeOutput=1,
                      recipe={'mod:raw','mod:raw'},node='metal',input_nodes={'raw','raw'}},
                    {item='mod:crafted',qty_produced=4,recipeOutput=1,
                      recipe={'mod:metal'},node='crafted',input_nodes={'metal'}}} end
                  local raw,product,qty,inputs='mod:raw','mod:crafted',4,INTERMEDIATE and 8 or 4
                  if BRICKS then
                    raw,product,qty,inputs='minecraft:brick','minecraft:brick_block',16,64
                    INV.source={['minecraft:brick']=100}
                    wh.observed('stock',{{item={name=raw,damage=0},count=100,maxSize=64}})
                    local scans=assert(wh.scan('stock'));untilFact(function() return wh.settled(scans[1]) end)
                    tasks={{item=product,qty_produced=qty,recipeOutput=1,
                      recipe={[1]=raw,[2]=raw,[4]=raw,[5]=raw},node='blocks',
                      input_nodes={[1]='brick',[2]='brick',[4]='brick',[5]='brick'}}}
                  end
                  local id=assert(M.run({tasks=tasks,requestItem=product,requestQuantity=qty},{config=CFG}))
                  untilFact(function() return ROBOT.status=='RUNNING' end)
                  local old=ROBOT.id
                  if PARTIAL then
                    if INTERMEDIATE then
                      add('buffer','mod:raw',-4);add('buffer','mod:metal',1)
                    else add('buffer',raw,BRICKS and -4 or -1) end
                    add('buffer',product,1)
                  end
                  restartRobot()
                  untilFact(function() return M.status(id).status~='running' end)
                  assert(M.status(id).status=='complete',M.status(id).reason)
                  assert(ROBOT_CALLS==2 and ROBOT.id~=old)
                  local reads,fetches=0,0
                  for _,j in ipairs(lg.jobs()) do for _,s in ipairs(j.steps or {}) do
                    if s.read and s.read.node=='buffer' then reads=reads+1 end
                    if s.take and s.take.node=='source' then fetches=fetches+(s.taken or 0) end
                  end end
                  assert(reads==1 and fetches==inputs,'remainder must use physical buffer, not fetch again')
                  assert(held('source',raw)==100-inputs)
                  assert(held('source',product)==qty and held('source','mod:metal')==0)
                  assert(held('buffer',raw)==0 and held('buffer','mod:metal')==0 and held('buffer',product)==0)
                ''')

    def test_robot_remainder_partial_single_step(self):
        self.robot_remainder(True, bricks=True)

    def test_robot_remainder_partial_intermediate(self):
        self.robot_remainder(True, True)

    def test_robot_remainder_nothing_completed(self):
        self.robot_remainder(False)

    def test_lost_fetch_retries_or_waits_for_found_without_double_counting(self):
        for machine in (False, True):
            for stock in (1, 100):
                with self.subTest(machine=machine, stock=stock):
                    lua = self.start()
                    lua.globals().MACHINE = machine
                    lua.globals().STOCK = stock
                    lua.execute('''
                      INV.source['mod:raw']=STOCK
                      wh.observed('stock',{{item={name='mod:raw',damage=0},count=STOCK,maxSize=64}})
                      local id=submit(MACHINE,1)
                      untilFact(function() return FAKE.working end)
                      add('source','mod:raw',-1);FAKE.held=1
                      FAKE.cargo={{name='mod:raw',damage=0,size=1,maxSize=64}}
                      report(FAKE.trip,{state='progress',steps={{taken=1,moved=1}},held=1,
                        cargo={{item={name='mod:raw',damage=0},count=1}}})
                      emit('modem_message','local','remote',27103,0,'secret','boot')
                      FAKE.working=false;report(0,{state='lost',cargo=FAKE.cargo});drain()
                      require('mes.service').pump()
                      local r=M.status(id);assert(r.status=='running')
                      local detail=r.stages[1].detail
                      assert(detail:find(STOCK==1 and 'press Found' or 'Retrying',1,true),detail)
                      assert(held('source','mod:raw')==STOCK-1)
                      assert(lg.found('d1'));report(0,{state='ready',held=1,cargo=FAKE.cargo});drain()
                      untilFact(function() return M.status(id).status~='running' end)
                      assert(M.status(id).status=='complete',M.status(id).reason)
                      assert(held('source','mod:raw')==STOCK-1 and FAKE.held==0)
                      assert(held('source',MACHINE and 'mod:metal' or 'mod:crafted')==1)
                      assert(not M.status(id).stages[1].itemsMoved,'finished ledgers stay on disk')
                      local movement=saved()['done_'..id].stages[1].itemsMoved[1]
                      assert(movement.quantity==1 and movement.moved==1 and #movement.jobs==2)
                    ''')

    def test_lost_fetch_retry_failure_keeps_both_reasons(self):
        self.start().execute('''
          local function lose()
            add('source','mod:raw',-1);FAKE.held=1
            FAKE.cargo={{name='mod:raw',damage=0,size=1,maxSize=64}}
            report(FAKE.trip,{state='progress',steps={{taken=1,moved=1}},held=1,
              cargo={{item={name='mod:raw',damage=0},count=1}}})
            emit('modem_message','local','remote',27103,0,'secret','boot')
            FAKE.working=false;report(0,{state='lost',cargo=FAKE.cargo});drain()
            require('mes.service').pump()
          end
          local id=submit(true,1);untilFact(function() return FAKE.working end);lose()
          assert(M.status(id).status=='running')
          assert(lg.found('d1'));report(0,{state='ready',held=1,cargo=FAKE.cargo});drain()
          untilFact(function() return FAKE.working and not FAKE.task.cargo end)
          lose()
          assert(M.status(id).reason=='drone lost: d1; retry: drone lost: d1')
          assert(held('source','mod:raw')==99 and FAKE.held==1 and held('source','mod:metal')==0)
          assert(lg.found('d1'));report(0,{state='ready',held=1,cargo=FAKE.cargo});drain()
          untilFact(function() return M.status(id).status~='running' end)
          local r=M.status(id)
          assert(r.status=='failed' and r.reason=='drone lost: d1; retry: drone lost: d1',r.reason)
          assert(held('source','mod:raw')==100 and FAKE.held==0 and held('source','mod:metal')==0)
        ''')

    def test_history_newest_twenty_snapshots_survive_restart(self):
        for mode in ('log', 'files'):
            with self.subTest(mode=mode):
                lua = self.start(mode)
                lua.execute('''
                  for i=1,25 do local id=submit(true);untilFact(function() return M.status(id).status~='running' end) end
                  local before=M.runs();assert(#before==20 and before[1].id==25 and before[20].id==6)
                  local db=saved();assert(#db.ids.done==20 and not db.done_5 and not db.plan_25)
                  local service=require('mes.service');local history
                  for i=1,30 do local name,value=debug.getupvalue(service.runs,i);if name=='history' then history=value end end
                  assert(history and not history[5]);for _,r in pairs(history) do
                    assert(not r.world and not r.ports and not r.plan and not r.actions and not r.cfg)
                    for _,st in ipairs(r.stages) do assert(not st.itemsMoved and not st.loadLedger) end
                  end
                  reboot();local after=M.runs();assert(#after==20 and after[1].id==25 and after[20].id==6)
                  assert(M.status(25).status=='complete' and M.status(5)==nil)
                ''')

    def test_learned_bounds_survive_cbor_restart(self):
        for mode in ('log', 'files'):
            with self.subTest(mode=mode):
                lua = self.start(mode)
                lua.execute('''
                  local id=submit(true,1);untilFact(function() return M.status(id).status~='running' end)
                  assert(M.status(id).status=='complete')
                  local t=assert(saved().timing.kiln);assert(t.samples>0 and t.hi<math.huge)
                  local hi,source=t.hi,M.resources{config=CFG}.machines.kiln.seconds.source;reboot()
                  local row=M.resources{config=CFG}.machines.kiln
                  assert(row.seconds.hi==hi and row.seconds.source==source)
                ''')

    def test_idle_ticks_do_not_write_or_flush_mes(self):
        lua=self.start()
        lua.execute('''
          local id=submit(true);untilFact(function() return M.status(id).status~='running' end)
          COUNTS={};for i=1,50 do step() end
          assert(not COUNTS['/etc/mes.state'],'idle ticks must not save')
        ''')

    def test_not_found_fetches_positive_deficit_only(self):
        for mode in ('log', 'files'):
            for restart in (False, True):
                with self.subTest(mode=mode, restart=restart):
                    lua=self.start(mode);lua.globals().RESTART=restart
                    lua.execute('''
                      local id=submit(false);untilFact(function() return ROBOT.status=='RUNNING' end)
                      add('buffer','mod:raw',-1);restartRobot();if RESTART then reboot() end
                      untilFact(function() return M.status(id).status~='running' end)
                      assert(M.status(id).status=='complete' and held('source','mod:raw')==98)
                      local reads,fetched=0,0
                      for _,j in ipairs(lg.jobs()) do for _,s in ipairs(j.steps or {}) do
                        if s.read and s.read.node=='buffer' then reads=reads+1 end
                        if s.take and s.take.node=='source' then fetched=fetched+s.taken end
                      end end
                      assert(reads==1 and fetched==2 and held('source','mod:crafted')==1)
                    ''')

    def test_headless_ocparts_store_measurement(self):
        planner=test_mes_ocparts_plan.OcpartsMesPlanTests();planner.setUp();plan=planner.plan()
        lua=self.start()
        def transfer(value):
            if hasattr(value, 'items'):
                return lua.table_from({k:transfer(v) for k,v in value.items()})
            return value
        lua.globals().PLAN=transfer(plan)
        lua.globals().INITIAL=lua.table_from(test_mes_ocparts_plan.generator.OCPARTS_STOCK)
        result=lua.execute('''
          PLAN.stages=nil
          CFG.machineTypes.furnace.batch=16;CFG.machineTypes.furnace.blocking=false
          CFG.machineTypes.furnace.fuel={role='fuel',item='minecraft:coal',per=8}
          CFG.machineTypes.furnace.roles={'input','fuel','output'};CFG.machineTypes.furnace.roleSlots.fuel={1}
          INV.source={};INV.fuel={};map.add('fuel',14,0,0);map.name('fuel_face','fuel',0)
          map.link('buffer','fuel')
          local all={};for id in pairs(INITIAL) do all[id]=true end
          for _,t in ipairs(PLAN.tasks) do
            all[t.item]=true;for _,id in pairs(t.recipe) do if id~='minecraft:air' then all[id]=true end end
            if t.isProcessing then MACHINE_RECIPE={input=t.recipe[1],output=t.item,fuel=true} end
          end
          local function item(id)
            local name,damage=id:match('^(.*):(%d+)$');return {name=name or id,damage=tonumber(damage) or 0}
          end
          local filters={};local counts={}
          for id in pairs(all) do filters[#filters+1]=item(id) end
          for id,n in pairs(INITIAL) do INV.source[id]=n;counts[#counts+1]={item=item(id),count=n,maxSize=64} end
          wh.add('stock',{filter=filters});wh.add('fuel_face',{})
          wh.group('kiln','furnace',{input='input_face',output='output_face',fuel='fuel_face'})
          local scans=assert(wh.scan('stock'));untilFact(function() return wh.settled(scans[1]) end);COUNTS={}
          local service=require('mes.service');local pump=service.pump
          service.pump=function(...)
            local before=(COUNTS['/etc/mes.state'] or {}).flushes or 0;pump(...)
            assert(((COUNTS['/etc/mes.state'] or {}).flushes or 0)-before<=1,'more than one save per pump')
          end
          local id=assert(M.run(PLAN,{config=CFG}));untilFact(function() return M.status(id).status~='running' end)
          local r=M.status(id);assert(r.status=='complete',r.reason)
          assert(held('source','opencomputers:component:6')==64)
          local result={trips=r.trips,counts=clone(COUNTS),stock=clone(INV.source)}
          COUNTS={};for i=1,50 do step() end;assert(not COUNTS['/etc/mes.state'])
          return result
        ''')
        for identity,quantity in test_mes_ocparts_plan.generator.OCPARTS_FINAL.items():
            self.assertEqual(quantity,result['stock'][identity] or 0,identity)
        self.assertGreater(result['counts']['/etc/mes.state']['writes'],0)
        print('OCPARTS trips:',result['trips'])
        for path,counts in sorted(result['counts'].items()):
            print(path,'changed-record writes:',counts['writes'],'explicit flushes:',counts['flushes'])
