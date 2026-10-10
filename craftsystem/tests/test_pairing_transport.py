from test_support import ROOT
from test_transport import TransportFixture


class PairingTransportTests(TransportFixture):
    def setUp(self):
        super().setUp()
        self.lua.globals().PAIR_SOURCE = (ROOT / 'usr/bin/pair.lua').read_text(encoding='utf-8')

    def test_actual_auto_pair_then_paired_job_and_unpaired_refusal(self):
        self.lua.execute('''
            local robot=peer('paired-robot');local controller=peer('paired-controller')
            for _,p in ipairs({robot,controller}) do
                p.disk['/etc/tnet.hosts']=p.require('serialization').serialize({})
                p.require('hosts').reload();assert(not p.require('hosts').localhost())
            end
            robot.args={'server','5991','Craft Robot'}
            robot.options={secret='robot-secret',keys='service,craftServer'}
            controller.args={'client','5991','Controller'}
            controller.options={secret='controller-secret',server='Craft Robot',['server-secret']='robot-secret'}
            local function runPair(p)
                return spawn(function()
                    local ok,err=pcall(assert(load(PAIR_SOURCE,'pair','t',p.env)))
                    assert(ok or (err=='PAIR_EXIT' and p.exitCode==0),err)
                    p.pairDone=true
                end,p)
            end
            runPair(robot);runPair(controller)
            untilDone(function() return robot.pairDone and controller.pairDone end,15)
            local remote=controller.require('hosts').getHost('Craft Robot')
            assert(remote:getAddress()=='paired-robot' and remote:getCID()==robot.cid)
            assert(remote:getWakeKey()=='robot-secret' and remote:getKeys().service=='craftServer')
            assert(robot.require('hosts').localhost():getWakeKey()=='robot-secret')
            assert(robot.require('hosts').getHost('Controller'):getAddress()=='paired-controller')
            robot.args=nil;robot.options=nil;server(robot);advance(0.1)
            job(controller,'Craft Robot');untilDone(function() return controller.result end)
            assert(controller.result.success and controller.result.serverAddress=='paired-robot' and robot.executions==1)
            local stranger=peer('unpaired-controller');local before=#TRACE
            job(stranger,'paired-robot');untilDone(function() return stranger.result end)
            assert(not stranger.result.success and not stranger.result.mayHaveExecuted)
            assert(stranger.result.message:find('not paired') and #TRACE==before)
            -- Also exercise the server's wake validator, bypassing consumer checks.
            spawn(function()
                local ok,err=pcall(stranger.require('api').connect,'craftServer',5990,'paired-robot',nil,0.3)
                assert(not ok and err:find('no response'));stranger.refused=true
            end,stranger)
            untilDone(function() return stranger.refused end)
            assert(robot.executions==1)
        ''')

    def test_unpaired_cproc_announces_until_interrupted(self):
        self.lua.execute('''
            local p=peer('unpaired-robot')
            p.disk['/etc/tnet.hosts']=p.require('serialization').serialize({});p.require('hosts').reload()
            server(p);advance(2.1)
            assert(not p.require('hosts').localhost() and p.executions==0)
            local hellos=0
            for _,m in ipairs(TRACE) do if m.from==p.address and m.args[1]=='mes_robot_hello' then hellos=hellos+1 end end
            assert(hellos>=2)
            emit(p,'interrupted');advance(1.1)
            assert(countListeners(p,'interrupted')==0 and countListeners(p,'modem_message')==0)
        ''')
