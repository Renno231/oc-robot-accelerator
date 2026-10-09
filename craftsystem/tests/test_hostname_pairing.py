from test_support import ROOT
from test_transport import TransportFixture


class HostnamePairingTests(TransportFixture):
    def setUp(self):
        super().setUp()
        self.lua.globals().PAIR_SOURCE = (ROOT / 'usr/bin/pair.lua').read_text(encoding='utf-8')

    def test_actual_pair_without_names_uses_hostname(self):
        self.lua.execute('''
            local robot=peer('hostname-robot');local controller=peer('hostname-controller')
            for _,p in ipairs({robot,controller}) do
                p.disk['/etc/tnet.hosts']=p.require('serialization').serialize({})
                p.require('hosts').reload()
            end
            robot.disk['/etc/hostname']='Craft Robot\\n'
            controller.disk['/etc/hostname']='Controller\\n'
            robot.args={'server','5991'}
            robot.options={secret='robot-secret',keys='service,craftServer'}
            controller.args={'client','5991'}
            controller.options={secret='controller-secret',server='Craft Robot',['server-secret']='robot-secret'}
            for _,p in ipairs({robot,controller}) do
                spawn(function()
                    local ok,err=pcall(assert(load(PAIR_SOURCE,'pair','t',p.env)))
                    assert(ok or (err=='PAIR_EXIT' and p.exitCode==0),err)
                    p.pairDone=true
                end,p)
            end
            untilDone(function() return robot.pairDone and controller.pairDone end,15)
            assert(robot.require('hosts').localhost():getName()=='Craft Robot')
            assert(controller.require('hosts').localhost():getName()=='Controller')
            assert(controller.require('hosts').getHost('Craft Robot'):getWakeKey()=='robot-secret')
            assert(robot.require('hosts').getHost('Controller'):getAddress()=='hostname-controller')
        ''')

    def test_local_registration_default_and_explicit_precedence(self):
        self.lua.execute('''
            local p=peer('hostname-default')
            p.disk['/etc/tnet.hosts']=p.require('serialization').serialize({})
            local hosts=p.require('hosts');hosts.reload()
            p.disk['/etc/hostname']='Survival CPU\\n'
            assert(hosts.addHost(p.address,p.cid,nil,'wake',{}))
            assert(hosts.localhost():getName()=='Survival CPU')
            hosts.reload();assert(hosts.localhost():getName()=='Survival CPU')
            assert(hosts.addHost(p.address,p.cid,'Explicit CPU','wake',{},true))
            assert(hosts.localhost():getName()=='Explicit CPU')
            hosts.localhost()._data.name=nil
            assert(hosts.localhost():getName()=='Survival CPU')
        ''')
