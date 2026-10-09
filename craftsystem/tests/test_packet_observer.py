from test_support import ROOT
from test_transport import TransportFixture


class PacketObserverTests(TransportFixture):
    def test_observer_measures_actual_fragment_frames(self):
        self.lua.globals().OBSERVER_SOURCE = (ROOT.parent / 'machine_evidence.lua').read_text().split("local starts=io.open", 1)[0]
        self.lua.execute('''
            local robot=peer('fragment-robot');server(robot)
            local controller=peer('fragment-controller')
            assert(controller.require('hosts').addHost(robot.address,robot.cid,robot.address,
                robot.require('hosts').localhost():getWakeKey(),{service='craftServer'}))
            controller.require('computer').getDeviceInfo=function()
                return {[controller.address]={capacity='8192'}}
            end
            controller.payloads=assert(load(OBSERVER_SOURCE..'\\nreturn craftPayloads','observer','t',controller.env))()
            controller.plan={requestItem='t:part',quantity=1,large=string.rep('x',25000)}
            job(controller,'fragment-robot',nil,controller.plan)
            untilDone(function() return controller.result end)
            assert(controller.result.success)
            local rows=controller.payloads;assert(#rows==1)
            local row=rows[1]
            assert(row.planBytes>25000 and row.payloadBytes>25000)
            assert(row.fragments==4 and #row.physicalPackets==4)
            local largest=0
            for _,p in ipairs(row.physicalPackets) do
                assert(p.bytes<=8192 and p.ninfo:match(',m,%d,4$'))
                largest=math.max(largest,p.bytes)
            end
            assert(row.packetBytes==largest and row.packetBytes>8000)
        ''')
