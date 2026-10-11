"""Synchronous generic mutation receipts for cached physical observations."""
import unittest

import test_stock_api


class LogisticsMutationTests(unittest.TestCase):
    def setUp(self):
        fixture = test_stock_api.LibraryApiTests()
        fixture.setUp()
        fixture.load_logistics()
        self.lua = fixture.lua

    def test_optional_steps_argument_carries_claim_without_changing_old_observers(self):
        self.lua.execute('''
          OLD=0
          lg.onMutation('old',function(id,endpoints)
            OLD=OLD+1;assert(endpoints[1].node=='source')
          end)
          lg.onMutation('claim',function(id,endpoints,steps)
            assert(steps[1].take.slots[1]==2)
            steps[1].claimed=16
          end)
          local id=lg.job({{take={storage='source',slots={2}},item={name='mod:x'},count=32},
            {put='dest',item={name='mod:x'},rest=true}})
          local s=lg.status(id)
          assert(OLD==1 and s.steps[1].claimed==16 and s.steps[2].claimed==nil)
          assert(s.steps[1].count==32 and s.steps[1].take.slots[1]==2)
        ''')

    def test_normalized_private_receipts_before_return_and_transfer(self):
        self.lua.execute('''
          CALLS={}
          assert(lg.onMutation('test',function(id,endpoints)
            CALLS[#CALLS+1]={id=id,endpoints=endpoints}
            assert(lg.status(id).state=='queued')
            endpoints[1].node='caller-private';endpoints[1].slots[1]=99
          end))
          local id=lg.job({{take={storage='source',slots={2}},item={name='mod:x'},count=1},
            {put={storage='dest',slots={1}},item={name='mod:x'},count=1}})
          assert(#CALLS==1 and CALLS[1].id==id and #CALLS[1].endpoints==2)
          local s=lg.status(id)
          assert(s.steps[1].take.node=='source' and s.steps[1].take.slots[1]==2)
          assert(s.steps[2].put.node=='dest' and s.steps[2].put.slots[1]==1)
          id=lg.transfer({name='mod:x'},1,{storage='source',slots={2}},
            {storage='dest',slots={1}},{overflow={storage='overflow',slots={3}}})
          assert(#CALLS==2 and CALLS[2].id==id and #CALLS[2].endpoints==3)
          assert(lg.status(id).from.slots[1]==2)
        ''')

    def test_read_and_invalid_jobs_do_not_claim_mutations(self):
        self.lua.execute('''
          N=0;lg.onMutation('test',function() N=N+1 end)
          local read=lg.job({{read='source'}});assert(lg.status(read).state=='queued' and N==0)
          local invalid=lg.job({{take='source',item={name='mod:x'},count=-1}})
          assert(lg.status(invalid).state=='failed' and N==0)
          assert(lg.onMutation('test',nil))
          lg.transfer({name='mod:x'},1,'source','dest');assert(N==0)
        ''')

    def test_observer_error_isolated_and_registration_validated(self):
        self.lua.execute('''
          lg.onMutation('bad',function() error('observer failed') end)
          CALLED=false;lg.onMutation('good',function() CALLED=true end)
          local id=lg.transfer({name='mod:x'},1,'source','dest')
          assert(CALLED and lg.status(id).state=='queued')
          assert(not pcall(lg.onMutation,'',function() end))
          assert(not pcall(lg.onMutation,'key',false))
        ''')

    def test_read_submission_receipts_private_and_no_transfer_notification(self):
        self.lua.execute('''
          READS={};lg.onRead('test',function(id,endpoints)
            READS[#READS+1]={id=id,endpoints=endpoints}
            assert(lg.status(id).state=='queued')
            endpoints[1].node='private';endpoints[1].slots[1]=99
          end)
          local id=lg.job({{read={storage='source',slots={2}}}})
          assert(#READS==1 and READS[1].id==id and #READS[1].endpoints==1)
          assert(lg.status(id).steps[1].read.node=='source' and lg.status(id).steps[1].read.slots[1]==2)
          lg.transfer({name='mod:x'},1,'source','dest');assert(#READS==1)
          local invalid=lg.job({{read='source',put='dest'}})
          assert(lg.status(invalid).state=='failed' and #READS==1)
          lg.onRead('test',nil);lg.job({{read='source'}});assert(#READS==1)
          assert(not pcall(lg.onRead,'',function() end))
          assert(not pcall(lg.onRead,'test',false))
        ''')

    def test_mixed_job_mutation_precedes_read_provenance(self):
        self.lua.execute('''
          EPOCH=0;CAPTURED=nil
          lg.onMutation('mut',function() EPOCH=EPOCH+1 end)
          lg.onRead('read',function() CAPTURED=EPOCH end)
          lg.job({{take='source',item={name='mod:x'},count=1},{read='source'}})
          assert(EPOCH==1 and CAPTURED==1)
        ''')
