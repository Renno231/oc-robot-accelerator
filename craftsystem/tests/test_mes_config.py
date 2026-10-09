from test_support import LuaCase, ROOT
from test_transport import TransportFixture


class MesConfigTests(LuaCase):
    def setUp(self):
        super().setUp()
        self.module('mes_config', 'lib/mes_config.lua')
        self.lua.execute('''
            CFG={machineTypes={},crafters={}}; OPT={config=CFG}; EVENTS={}; GROUPS={}
            package.preload.event=function() return {
              push=function(...) EVENTS[#EVENTS+1]={...} end,
              pull=function(n) TIME=TIME+n end} end
            package.preload.computer=function() return {uptime=function() return TIME end} end
            package.preload.hosts=function() return {getHost=function(key)
              if key~='addr' and key~='robot-name' then return nil end
              return {getAddress=function() return 'addr' end,getKeys=function() return {service='craftServer'} end,
                getWakeKey=function() return 'paired-wake' end}
            end} end
            package.preload.warehouse=function() return {
              groups=function() return GROUPS end,
              group=function(n,k,r) assert(r.buffer~='bad','unknown storage');GROUPS[n]={type=k,roles=r};return true end,
              ungroup=function(n) GROUPS[n]=nil;return true end} end
            C=require('mes_config')
            function def() return {inputs={'input'},output='output',fuel={role='fuel',item='minecraft:coal',per=8},batch=64,seconds=10,blocking=true,
              roleSlots={input={1},fuel={1},output={1}}} end
        ''')

    def test_defaults_copies_and_events(self):
        self.lua.execute('''
            local d=def();assert(C.setType('furnace',d,OPT));assert(d.blocking==true and d.roles==nil)
            local t=C.types(OPT);assert(t.furnace.blocking==true)
            assert(table.concat(t.furnace.roles,',')=='input,fuel,output')
            t.furnace.inputs[1]='broken';assert(C.types(OPT).furnace.inputs[1]=='input')
            t.furnace.roleSlots.input[1]=9;assert(C.types(OPT).furnace.roleSlots.input[1]==1)
            assert(C.config(OPT)==CFG);assert(EVENTS[1][1]=='mes' and EVENTS[1][2]=='changed')
            d.blocking=false;d.roles={'output','input','fuel'};assert(C.setType('furnace',d,OPT))
            assert(C.types(OPT).furnace.blocking==false);assert(C.types(OPT).furnace.roles[1]=='output')
            assert(C.removeType('furnace',OPT));assert(next(C.types(OPT))==nil);assert(#EVENTS==3)
        ''')

    def test_validation_has_no_effects(self):
        self.lua.execute('''
            local changes={
              function(d) d.inputs={} end, function(d) d.inputs={'x','x'} end,
              function(d) d.inputs={[1]='x',[3]='y'} end,
              function(d) d.output='' end, function(d) d.roles={'input'} end,
              function(d) d.roles={'input','output','fuel','fuel'} end,
              function(d) d.batch=0 end, function(d) d.batch=1.5 end,
              function(d) d.seconds=-1 end, function(d) d.seconds=math.huge end,
              function(d) d.seconds=0/0 end, function(d) d.blocking=1 end,
              function(d) d.blocking=nil end,
              function(d) d.fuel.per=0 end, function(d) d.fuel.per=math.huge end,
              function(d) d.fuel.role='' end, function(d) d.fuel.item='ore:coal' end,
              function(d) d.fuel.item='minecraft:coal:' end,
              function(d) d.fuel.item='minecraft:*' end,
              function(d) d.fuel.item='minecraft:air' end}
            for _,change in ipairs(changes) do
              local d=def();change(d);local ok,err=C.setType('bad',d,OPT);assert(ok==nil and type(err)=='string')
            end
            local ok,err=C.setType(' ',def(),OPT);assert(ok==nil and type(err)=='string');assert(next(CFG.machineTypes)==nil and #EVENTS==0)
            local omitted=def();omitted.blocking=nil
            ok,err=C.setType('missingBlocking',omitted,OPT);assert(ok==nil and err:find('Blocking',1,true))
            CFG.machineTypes.legacy={inputs={'input'},output='output',batch=64,seconds=10}
            assert(C.types(OPT).legacy.blocking==nil)
            local d=def();d.seconds=0;d.fuel=nil;d.roleSlots.fuel=nil;assert(C.setType('valid',d,OPT))
        ''')

    def test_required_face_relative_role_slots(self):
        self.lua.execute('''
            local changes={
              function(d) d.roleSlots=nil end,
              function(d) d.roleSlots.input=nil end,
              function(d) d.roleSlots.output={} end,
              function(d) d.roleSlots.fuel={1,1} end,
              function(d) d.roleSlots.input={[1]=1,[3]=3} end,
              function(d) d.roleSlots.output={0} end,
              function(d) d.roleSlots.output={-1} end,
              function(d) d.roleSlots.output={1.5} end,
              function(d) d.roleSlots.output={'1'} end,
              function(d) d.roleSlots.output={math.huge} end,
              function(d) d.roleSlots.extra={1} end}
            for _,change in ipairs(changes) do
              local d=def();change(d);local ok,err=C.setType('bad',d,OPT)
              assert(ok==nil and type(err)=='string')
            end
            assert(next(CFG.machineTypes)==nil and #EVENTS==0)
            local d=def();d.blocking=false
            assert(C.setType('furnace',d,OPT))
            local t=C.types(OPT).furnace
            assert(t.roleSlots.input[1]==1 and t.roleSlots.fuel[1]==1 and t.roleSlots.output[1]==1)
            assert(#t.roleSlots.output==1 and t.blocking==false)
            d.roleSlots.input[1]=99;assert(C.types(OPT).furnace.roleSlots.input[1]==1)
            local alloy={roles={'copper','tin','output'},inputs={'copper','tin'},output='output',batch=64,seconds=3,
              blocking=true,roleSlots={copper={1,3},tin={1,2},output={2}}}
            assert(C.setType('alloy',alloy,OPT))
            assert(table.concat(C.types(OPT).alloy.roles,',')=='copper,tin,output')
        ''')

    def test_crafters_only_config_and_group_registration(self):
        self.lua.execute('''
            assert(C.setCrafter('cpu',{robot='addr',buffer='buf',status='busy'},OPT))
            assert(GROUPS.cpu.type=='crafter' and GROUPS.cpu.roles.buffer=='buf')
            local c=C.crafters(OPT);assert(c.cpu.status==nil and c.cpu.buffer=='buf')
            c.cpu.robot='changed';assert(C.crafters(OPT).cpu.robot=='addr')
            assert(not pcall(C.setCrafter,'cpu',{robot='',buffer='buf'},OPT))
            assert(not pcall(C.setCrafter,'unpaired',{robot='unknown',buffer='buf'},OPT))
            assert(not GROUPS.unpaired and not CFG.crafters.unpaired)
            assert(not pcall(C.setCrafter,'other',{robot='addr',buffer='bad'},OPT));assert(not CFG.crafters.other)
            GROUPS.machine={type='furnace'}
            assert(not pcall(C.setCrafter,'machine',{robot='addr',buffer='buf'},OPT))
            assert(not pcall(C.removeCrafter,'machine',OPT));assert(GROUPS.machine.type=='furnace')
            assert(C.removeCrafter('cpu',OPT));assert(not GROUPS.cpu and not CFG.crafters.cpu)
            assert(#EVENTS==2)
        ''')

    def mock_disk(self):
        self.lua.execute('''
            DISK=nil; SAVED=nil; WRITES=0; CLOSE_RESULT=true; CLOSE_ERROR=nil; TEMP={}
            local function copied(t)
              if type(t)~='table' then return t end
              local out={};for k,v in pairs(t) do out[k]=copied(v) end;return out
            end
            package.preload.filesystem=function() return {
              exists=function() return DISK~=nil end,
              remove=function(p) TEMP[p]=nil;return true end,
              rename=function(old,new)
                assert(new=='/etc/mes.cfg')
                if RENAME_FAIL then return nil,'rename error' end
                assert(TEMP[old]);DISK=copied(TEMP[old]);TEMP[old]=nil;return true
              end} end
            package.preload.serialization=function() return {
              unserialize=function(s) if s=='invalid' then return nil end;return copied(DISK) end,
              serialize=function(t) if ENCODE_FAIL then error('encode error') end;SAVED=copied(t);return 'serialized' end} end
            io.open=function(p,mode)
              if mode=='r' then
                assert(p=='/etc/mes.cfg')
                if DISK==nil then return nil,'missing' end
                return {read=function() return DISK=='invalid' and 'invalid' or 'serialized' end,close=function() return true end}
              end
              assert(mode=='w' and p:match('^/etc/mes%.cfg%.tmp%.%d+$'))
              if OPEN_FAIL then return nil,'open error' end
              local buffer=nil;local f={}
              function f:write(s)
                assert(s=='serialized');WRITES=WRITES+1
                if WRITE_FAIL then return nil,'write error' end
                buffer=copied(SAVED);return self
              end
              function f:flush()
                if FLUSH_FAIL then return nil,'flush error' end
                if buffer then TEMP[p]=copied(buffer) end;return true
              end
              function f:close()
                self:flush() -- actual OpenOS close discards this result
                return CLOSE_RESULT,CLOSE_ERROR
              end
              return f
            end
        ''')

    def test_file_persistence_and_missing_config(self):
        self.mock_disk()
        self.lua.execute('''
            assert(next(C.types())==nil);assert(C.setType('furnace',def()))
            assert(WRITES==1 and C.types().furnace.blocking)
            assert(C.setCrafter('cpu',{robot='addr',buffer='buf'}));assert(WRITES==2)
            assert(C.crafters().cpu.robot=='addr');assert(C.removeCrafter('cpu'));assert(WRITES==3)
            assert(C.removeType('furnace'));assert(WRITES==4)
            assert(C.setType('injected',def(),OPT));assert(WRITES==4)
            DISK='invalid';assert(not pcall(C.config))
        ''')

    def test_openos_close_nil_success_and_explicit_failure(self):
        self.mock_disk()
        self.lua.execute('''
            CLOSE_RESULT=nil;assert(C.setType('furnace',def()));assert(#EVENTS==1)
            CLOSE_RESULT=false;assert(not pcall(C.setType,'failed',def()));assert(#EVENTS==1)
            CLOSE_RESULT=nil;CLOSE_ERROR='close error'
            local ok,err=pcall(C.setType,'failedAgain',def());assert(not ok and err:find('close error',1,true))
            assert(#EVENTS==1)
        ''')

    def test_atomic_failures_preserve_existing_config_and_emit_no_success(self):
        self.mock_disk()
        self.lua.execute('''
            CLOSE_RESULT=nil;assert(C.setType('original',def()))
            for _,flag in ipairs({'ENCODE_FAIL','OPEN_FAIL','WRITE_FAIL','FLUSH_FAIL','RENAME_FAIL'}) do
                _G[flag]=true
                local ok=pcall(C.setType,'failed',def());assert(not ok,flag)
                _G[flag]=nil
                assert(C.types().original and not C.types().failed and #EVENTS==1,flag)
                assert(next(TEMP)==nil,flag)
            end
            CLOSE_ERROR='close error'
            assert(not pcall(C.removeType,'original'));CLOSE_ERROR=nil
            assert(C.types().original and #EVENTS==1 and next(TEMP)==nil)
            -- Reload reads the durable file, not the failed mutation's table.
            package.loaded.mes_config=nil;local reloaded=require('mes_config')
            assert(reloaded.types().original and not reloaded.types().failed)
            assert(reloaded.removeType('original'));assert(next(reloaded.types())==nil and #EVENTS==2)
        ''')

class MesPairedHostsTests(TransportFixture):
    def test_sorted_status_copies_preserve_names_cid_wake_keys(self):
        self.lua.execute('''
            local hosts=C.require('hosts')
            assert(hosts.addHost('robot-a',A.cid,'My Robot','wake-robot-a',{service='craftServer',tool='key'},true))
            hosts.addHost('other','other-cid','other','secret',{service='unrelated'},true)
            hosts.addHost('no-key','no-key-cid','no-key',nil,{service='craftServer'},true)
            spawn(function() C.robots=C.require('mes_config').robots(0.3) end,C)
            untilDone(function() return C.robots end)
            local robots=C.robots
            assert(#robots==2 and robots[1].address=='robot-a' and robots[2].address=='robot-b')
            assert(robots[1].name=='My Robot' and robots[1].busy==false and robots[2].busy==false)
            local a=hosts.getHost('My Robot')
            assert(a:getCID()==A.cid and a:getWakeKey()=='wake-robot-a' and a:get('tool')=='key')
            robots[1].address='changed'
            spawn(function() C.again=C.require('mes_config').robots() end,C)
            untilDone(function() return C.again end)
            assert(C.again[1].address=='robot-a' and C.again[1].name=='My Robot')
            job(C,'My Robot');untilDone(function() return C.result end)
            assert(C.result.success and C.result.serverAddress=='robot-a')
        ''')

    def test_host_listing_failure_and_timeout_validation(self):
        self.lua.execute('''
            C.require('hosts').getAll=function() error('hosts unavailable') end
            local m=C.require('mes_config');local robots,err=m.robots(0)
            assert(not robots and err:find('hosts unavailable'))
            assert(not pcall(m.robots,-1) and not pcall(m.robots,math.huge))
        ''')


class MesCliTests(LuaCase):
    def setUp(self):
        super().setUp()
        source = (ROOT / 'usr/bin/mes.lua').read_text(encoding='utf-8')
        self.lua.globals().CLI_SOURCE = source
        self.lua.execute('''
            ARGS={};FLAGS={};ERRORS='';PULLS=0;SETTLE_CHECKS=0
            io.stderr={write=function(self,s) ERRORS=ERRORS..s end}
            package.preload.shell=function() return {parse=function() return ARGS,FLAGS end} end
            package.preload.event=function() return {pull=function() PULLS=PULLS+1 end} end
            API={plan=function(item,qty,opts) assert(item=='m:x' and qty==4);return {missing={}} end,
              run=function(p,o) RUN=true;return 42 end,
              wait=function(id) assert(RUN and id==42);WAIT=true;return {status='complete'} end}
            RECIPE_API={
              readSlots=function(s) SOURCE=s;return {marker=true},27 end,
              transposerInventories=function() return {{address='addr',side=2,size=27,used=1}} end,
              slotsFromListing=function(l,size) assert(l[3].name=='m:x' and size==27);CONVERT=true;return l,size end,
              recipeFromSlots=function(k,s,size,t) KIND=k;TYPE=t;return {kind=k} end,
              save=function(d) SAVED=true;return true end,
              list=function(item) assert(item=='m:x');return {{kind='crafting',source='user',inputs={},outputs={{item='m:x',qty=4}}}} end,
              remove=function(item,n) assert(item=='m:x' and n==2);REMOVED=true;return true end}
            package.preload.mes=function() return API end
            package.preload.recipes=function() return RECIPE_API end
            package.preload.warehouse=function() return {
              scan=function(s) assert(s=='buf');return {7} end,
              settled=function(id) assert(id==7);SETTLE_CHECKS=SETTLE_CHECKS+1;return SETTLE_CHECKS>1 end} end
            package.preload.logistics=function() return {status=function(id)
              assert(id==7);return {state=SCAN_STATE or 'done',reason='scan error',steps={{listing={[3]={name='m:x',size=1}},size=27}}}
            end} end
            function cli() return assert(load(CLI_SOURCE))() end
        ''')

    def test_craft_and_saved_run_wait_for_id(self):
        self.lua.execute('''
            ARGS={'craft','m:x','4'};assert(cli()==0 and WAIT)
            ARGS={'run','saved.plan'};WAIT=false;assert(cli()==0 and WAIT)
            API.run=function() return nil,'busy' end;assert(cli()==1 and ERRORS:find('busy'))
        ''')

    def test_run_failure_reason(self):
        self.lua.execute('''
            ARGS={'run','saved.plan'};API.wait=function() return {status='failed',reason='output short'} end
            assert(cli()==1 and ERRORS:find('output short',1,true))
        ''')

    def test_storage_import_waits_settlement_then_uses_listing(self):
        self.lua.execute('''
            ARGS={'recipe','import'};FLAGS={storage='buf',kind='processing',type='furnace'}
            assert(cli()==0 and PULLS==1 and CONVERT and SAVED and KIND=='processing' and TYPE=='furnace')
        ''')

    def test_failed_scan_is_not_imported(self):
        self.lua.execute('''
            ARGS={'recipe','import'};FLAGS={storage='buf',kind='crafting'};SCAN_STATE='partial'
            assert(cli()==1 and not SAVED and not CONVERT and ERRORS:find('scan error',1,true))
        ''')

    def test_transposer_import_and_default_selection(self):
        self.lua.execute('''
            ARGS={'recipe','import'};FLAGS={side='2',transposer='explicit',kind='crafting'}
            assert(cli()==0 and SOURCE.transposer=='explicit' and SOURCE.side==2)
            FLAGS.transposer=nil;assert(cli()==0 and SOURCE.transposer=='addr')
            RECIPE_API.transposerInventories=function() return {{address='a',side=2},{address='b',side=2}} end
            assert(cli()==1 and ERRORS:find('Multiple transposers',1,true))
        ''')

    def test_recipe_list_remove_and_validation(self):
        self.lua.execute('''
            ARGS={'recipe','list','m:x'};assert(cli()==0)
            ARGS={'recipe','remove','m:x','2'};assert(cli()==0 and REMOVED)
            ARGS={'recipe','remove','m:x','0'};assert(cli()==1)
            ARGS={'recipe','import'};FLAGS={side='6',kind='crafting'};assert(cli()==1)
            FLAGS={side='2',storage='buf',kind='crafting'};assert(cli()==1)
            FLAGS={side='2',kind='processing'};assert(cli()==1)
            FLAGS={side='2',kind='crafting'};RECIPE_API.save=function() return nil,'duplicate' end
            assert(cli()==1 and ERRORS:find('duplicate',1,true))
        ''')
