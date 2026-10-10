from test_transport import TransportFixture
from test_support import ROOT


class RobotRegisterTests(TransportFixture):
    def setUp(self):
        super().setUp()
        self.lua.globals().PAIR_SOURCE = (ROOT / 'usr/bin/pair.lua').read_text(encoding='utf-8')
        self.lua.execute(r'''
          PEERS={};TASKS={};PACKETS={};TRACE={}
          function cold(address,name,cid)
            local p=peer(address);p.require('hosts').removeHost(address)
            if cid then p.cid=cid;p.require('component').computer.address=cid end
            p.disk['/etc/hostname']=name
            local io=p.require('io');local open=io.open
            io.open=function(path,mode)
              if mode=='r' and p.disk[path]==nil then return nil,'absent' end
              local f=open(path,mode)
              local write=f.write
              if write then f.write=function(self,data) write(self,data);return self end end
              return f
            end
            p.env.io=io
            local fs=p.require('filesystem')
            fs.rename=function(a,b) p.disk[b]=p.disk[a];p.disk[a]=nil;return true end
            local pull=p.event.pull
            p.event.pull=function(n,filter)
              if not filter then return pull(n) end
              local result
              local cb=function(...) result=table.pack(...) end
              p.event.listen(filter,cb);coroutine.yield(n or 0.01);p.event.ignore(filter,cb)
              if result then return table.unpack(result,1,result.n) end
            end
            return p
          end
          function controller(p)
            p.members={stock={},reserved={},alias={inventory='reserved'}}
            p.groups={reserve={type='other',roles={buffer='reserved'}}}
            p.loaded.warehouse={members=function() return p.members end,groups=function() return p.groups end,
              group=function(n,k,r) p.groups[n]={type=k,roles=r};return true end}
            p.loaded.map={storage=function(b) return b=='other' or p.members[b] and {node=b,side=0} end}
            p.announces={}
            p.event.listen('mes_robot_announce',function(_,a) p.announces[a]=(p.announces[a] or 0)+1 end)
            p.config=p.require('mes_config');p.config.installRobots()
          end
          R=cold('rr-r','unpaired-r');S=cold('rr-s','unpaired-s');T=cold('rr-t','unpaired-t')
          C=cold('rr-controller','control');controller(C)
          server(R);server(S);server(T);advance(0.1)
          function registered()
            assert(C.config.registerRobot(R.address,'cpu','other'))
            untilDone(function() return R.require('hosts').localhost() end,2)
          end
          function snapshot(p)
            local out={}
            local rows=p.require('serialization').unserialize(p.disk['/etc/tnet.hosts'])
            for _,h in ipairs(rows) do
              h.paired_at=nil;out[h.name]=h
            end
            return out
          end
          function equal(a,b)
            if type(a)~=type(b) then return false end
            if type(a)~='table' then return a==b end
            for k,v in pairs(a) do if not equal(v,b[k]) then return false end end
            for k in pairs(b) do if a[k]==nil then return false end end
            return true
          end
        ''')

    def test_three_announcements_once_and_install_once(self):
        self.lua.execute('''
          C.config.installRobots();advance(2.1)
          assert(#C.config.pendingRobots()==3)
          for _,p in ipairs({R,S,T}) do assert(C.announces[p.address]==1) end
        ''')

    def test_manual_pair_host_entries_and_craft_roundtrip(self):
        self.lua.execute('''
          registered();job(C,R.address);untilDone(function() return C.result end)
          assert(C.result.success and R.executions==1)
          local robot,ctrl=snapshot(R),snapshot(C)
          local ra,rc,ca,cc=R.address,R.cid,C.address,C.cid
          local rw,cw=robot.cpu.wake,ctrl.control.wake
          assert(#rw==12 and rw:match('^%x+$') and #cw==12)
          assert(robot.control.wake==nil and robot.cpu.keys.service=='craftServer')
          PEERS={};TASKS={};PACKETS={}
          R=cold(ra,'cpu',rc);C=cold(ca,'control',cc)
          R.args={'server','27105'};R.options={secret=rw,keys='service,craftServer'}
          C.args={'client','27105'};C.options={secret=cw,server='cpu',['server-secret']=rw}
          local function pair(p)
            p.pair=spawn(function()
              local ok,err=pcall(assert(load(PAIR_SOURCE,'pair','t',p.env)))
              assert(ok or err=='PAIR_EXIT',err)
            end,p)
          end
          pair(R);pair(C)
          untilDone(function() return C.exitCode==0 end)
          assert(equal(robot,snapshot(R)) and equal(ctrl,snapshot(C)))
        ''')

    def test_validation_changes_nothing_and_stock_rejected(self):
        self.lua.execute('''
          local before=C.disk['/etc/hosts'];local groups=C.require('serialization').serialize(C.groups)
          for _,args in ipairs({{R.address,'bad name','other'},{R.address,'','other'},
            {R.address,string.rep('x',49),'other'},{R.address,'cpu','stock'},
            {R.address,'cpu','missing'},{'absent','cpu','other'}}) do
            local ok,err=C.config.registerRobot(table.unpack(args))
            assert(ok==nil and type(err)=='string')
            if args[3]=='stock' then assert(err:find('Buffer is stock',1,true)) end
            assert(C.disk['/etc/hosts']==before and C.disk['/etc/mes.cfg']==nil)
            assert(C.require('serialization').serialize(C.groups)==groups)
          end
          registered()
          before=C.disk['/etc/hosts'];local cfg=C.disk['/etc/mes.cfg']
          for _,args in ipairs({{S.address,'cpu','reserved'},{S.address,'second','other'}}) do
            local ok,err=C.config.registerRobot(table.unpack(args));assert(not ok and err)
            assert(C.disk['/etc/hosts']==before and C.disk['/etc/mes.cfg']==cfg)
          end
          assert(C.config.registerRobot(S.address,'second','reserved'))
          before=C.disk['/etc/hosts'];cfg=C.disk['/etc/mes.cfg']
          local ok,err=C.config.registerRobot(T.address,'third','alias')
          assert(not ok and err:find('Buffer is used',1,true))
          assert(C.disk['/etc/hosts']==before and C.disk['/etc/mes.cfg']==cfg)
        ''')

    def test_station_other_buffer_is_accepted(self):
        self.lua.execute('''
          assert(not C.members.other and C.loaded.map.storage('other'))
          registered();assert(C.config.crafters().cpu.buffer=='other')
        ''')

    def test_lost_welcome_resends_same_wake(self):
        self.lua.execute('''
          local send=C.modem.send;local lost=false;local wakes={}
          C.modem.send=function(to,port,kind,data,...)
            if kind=='mes_robot_welcome' then
              wakes[#wakes+1]=C.require('serialization').unserialize(data).wake
              if not lost then lost=true;return true end
            end
            return send(to,port,kind,data,...)
          end
          registered();assert(lost and #wakes>=2 and wakes[1]==wakes[2])
          assert(#C.config.pendingRobots()==2 and C.announces[R.address]==1)
        ''')

    def test_controller_restart_rebuilds_two_pending(self):
        self.lua.execute('''
          registered();assert(#C.config.pendingRobots()==2)
          C.listeners.modem_message={};C.loaded.mes_config=nil
          C.config=C.require('mes_config');C.config.installRobots()
          assert(#C.config.pendingRobots()==0)
          advance(1.2);assert(#C.config.pendingRobots()==2)
        ''')

    def test_boot_notice_inspects_missing_receipt_within_two_seconds(self):
        self.lua.execute('''
          registered();R.duration=30;local facts={};local cc=C.require('craft_client')
          spawn(function()
            cc.install(function(token,what,data) facts[#facts+1]={token=token,what=what,data=data,at=NOW} end,
              {connectTimeout=0.2,rpcTimeout=60,idleTimeout=60})
            assert(cc.begin('run',R.address,{requestItem='t:target'},'rr-job',{idleTimeout=60}))
          end,C)
          C.event.timer(0.1,function() cc.tick(NOW) end,math.huge)
          untilDone(function() return R.executions==1 end)
          local boot=NOW
          local keep={};for _,t in ipairs(TASKS) do if t.peer~=R then keep[#keep+1]=t end end;TASKS=keep
          R.listeners={};R.timers={}
          for _,m in ipairs({'tnet','api','pubsub','craft_receipts'}) do R.loaded[m]=nil end
          server(R)
          local function found()
            for _,f in ipairs(facts) do
              if f.what=='robot_status' and f.data.receipt and f.data.receipt.status=='NOT_FOUND' then
                RECOVERY_SECONDS=f.at-boot;assert(RECOVERY_SECONDS<2);return true
              end
            end
          end
          untilDone(found,2)
          local noticed=false
          for _,f in ipairs(facts) do if f.what=='robot_transport' and f.data.state=='rebooted' then noticed=true end end
          assert(noticed)
        ''')
