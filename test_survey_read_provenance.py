"""Unrelated station edits preserve reads; changed physical identities do not."""
import unittest
import test_read_provenance


class SurveyReadProvenanceTests(test_read_provenance.CachedRoleApiTests):
    def test_a_other_station_membership_keeps_read_and_prior_epochs(self):
        self.lua.execute('''
          local lg=installHooks()
          local first=lg.job({{read='stock'}});finishRead(first,'stock',nil,5)
          local mutation=lg.job({{take='alias',item=item,count=1}})
          jobs[mutation]={state='done',steps={{take=storages.alias,item=item,taken=1,maxSize=64}}}
          listener('logistics',mutation);assert(wh.count(item)==4)
          local scan=wh.scan('stock')[1]
          wh.add('buffer') -- station B joins while A's read is in flight
          finishRead(scan,'stock',nil,7)
          assert(wh.count(item)==7 and wh.settled(scan),'unrelated membership lost A read')
        ''')

    def test_b_own_endpoint_inventory_identity_change_discards_read(self):
        self.lua.execute('''
          local lg=installHooks()
          local first=lg.job({{read='stock'}});finishRead(first,'stock',nil,5)
          local stale=lg.job({{read='stock'}})
          wh.add('stock',{inventory='double'}) -- this face acquired a new alias identity
          finishRead(stale,'stock',nil,9)
          assert(not wh.contents('stock') and wh.count(item)==5 and wh.settled(stale))
        ''')

    def test_c_normal_mes_read_survives_unrelated_station_add(self):
        self.lua.execute('''
          local lg=installHooks()
          local job=lg.job({{read='stock'}}) -- ordinary MES/logistics read, not wh.scan
          storages.stationB={node='stationB',side=3};wh.add('stationB')
          finishRead(job,'stock',nil,11)
          assert(wh.count(item)==11 and wh.contents('stock').verified and wh.settled(job))
        ''')


if __name__ == '__main__':
    unittest.main()
