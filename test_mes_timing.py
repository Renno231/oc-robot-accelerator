"""Receipt-only timing arithmetic, epochs, probes and persistence."""
import unittest
from pathlib import Path
from lupa.lua53 import LuaRuntime


class TimingTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        source = Path('craftsystem/usr/lib/mes_timing.lua').read_text()
        self.lua.execute('T=(function()\n' + source + '\nend)()')
        self.lua.execute('''
          SIGNALS={};package.preload.event=function() return {push=function(...) SIGNALS[#SIGNALS+1]={...} end} end
          w={now=0,machines={a={type='furnace'},b={type='furnace'},c={type='furnace'}}}
          g={name='a',mt={seconds=10,roleSlots={output={1}},output='output'},
             fuel={credit=100,admitted=0},loads={},quarantined={}}
          function load(n,at)
            w.now=at or w.now
            local l={ops=n,request={perOp=1,run={},outputs={brick=1}},
              bundle={action={submittedAt=w.now}},remaining={brick=n}}
            g.loads[#g.loads+1]=l
            local duration=T.load(w,g,l);l.duration=duration;l.due=w.now+duration
            return l,duration
          end
          function receipt(l,k,early,late,steps)
            w.now=late;l.consumed=k;l.remaining.brick=l.ops-k
            T.observe(w,g,{bundle={action={submittedAt=early,results={{steps=steps or {}}}},run={jobs={}}}})
          end
          function clear() g.loads={} end
        ''')

    def test_source_learned(self):
        self.lua.execute("T.seconds(w,g);w.timing.a.hi=4;local n,t,s=T.seconds(w,g);assert(n==4 and s=='learned')")

    def test_source_lower(self):
        self.lua.execute("T.seconds(w,g);w.timing.a.lo=6;local n,t,s=T.seconds(w,g);assert(n==12 and s=='lower');w.timing.a.lo=5;n,t,s=T.seconds(w,g);assert(s=='config')")

    def test_source_config(self):
        self.lua.execute("local n,t,s=T.seconds(w,g);assert(n==10 and s=='config');g.mt.seconds=0;n,t,s=T.seconds(w,g);assert(n==0 and s=='config')")

    def test_source_type(self):
        self.lua.execute("g.mt.seconds=nil;w.timing={b={hi=8},c={hi=12}};local n,t,s=T.seconds(w,g);assert(n==10 and s=='type')")

    def test_source_none(self):
        self.lua.execute("g.mt.seconds=nil;local n,t,s=T.seconds(w,g);assert(n==0 and s=='none')")

    def test_timing_signal_matches_persisted_changes(self):
        self.lua.execute('''
          puts=0;p={db={},known={},store={put=function() puts=puts+1 end}}
          T.seconds(w,g);T.persist(p,w);assert(puts==0 and #SIGNALS==0)
          w.timing.a.hi=10;T.persist(p,w);assert(puts==1 and #SIGNALS==1)
          assert(SIGNALS[1][1]=='mes' and SIGNALS[1][2]=='timing' and SIGNALS[1][3]=='a')
          w.timing.a.hi=10.4;T.persist(p,w);w.timing.a.hi=10.5;T.persist(p,w)
          assert(puts==1 and #SIGNALS==1)
          w.timing.a.hi=10.501;T.persist(p,w);T.persist(p,w)
          assert(puts==2 and #SIGNALS==2)
        ''')

    def test_sequential_bonus_interval(self):
        self.lua.execute('''
          l=load(16);w.timing.a.lo=9
          q=load(16,5)
          q.consumed=2;receipt(l,16,180,182)
          assert(w.timing.a.lo<=10 and w.timing.a.hi>=10)
          assert(g.epoch.k==18 and g.epoch.n==32)
        ''')

    def test_low_estimate_short_and_recovery(self):
        self.lua.execute('''
          g.mt.seconds=5;l=load(16);receipt(l,8,80,82)
          assert(w.timing.a.lo==80/9 and w.timing.a.hi==82/8)
          receipt(l,16,165,167);clear();q,d=load(16,170)
          assert(d>=160 and d<168)
        ''')

    def test_high_estimate_latency_and_probe(self):
        self.lua.execute('''
          g.mt.seconds=30;l=load(16);receipt(l,16,480,482);clear()
          local original=w.timing.a.hi
          w.timing.a.sinceFree=5;w.timing.a.sinceProbe=5
          q,d=load(16,500);assert(q.probe and d<original*16)
          receipt(q,16,500+d,502+d)
          assert(w.timing.a.hi<original)
        ''')

    def test_unset_estimate_uses_observed_lower_bound(self):
        self.lua.execute('''
          g.mt.seconds=nil;l,d=load(16);assert(d==0)
          receipt(l,0,1,2);assert(w.timing.a.lo==1)
          assert(T.seconds(w,g)==2)
          receipt(l,2,20,22);assert(w.timing.a.hi==11)
        ''')

    def test_fuel_and_capacity_excluded(self):
        self.lua.execute('''
          g.mt.fuel={per=8};g.fuel.credit=0;l=load(16)
          receipt(l,0,100,102);assert(w.timing.a.samples==0 and g.timingExcluded.fuel==1)
          clear();g.fuel.credit=100;l=load(64)
          receipt(l,64,640,642,{{take={},taken=64,maxSize=64}})
          assert(w.timing.a.samples==0 and g.timingExcluded.capacity==1)
        ''')

    def test_idle_gap_upper_only_until_clean_start(self):
        self.lua.execute('''
          l=load(16);q=load(16,200);receipt(l,16,210,212)
          assert(w.timing.a.samples==1 and w.timing.a.lo==0 and w.timing.a.hi>=10)
          assert(g.timingExcluded.unknown==1)
          clear();l=load(16,220);receipt(l,16,380,382)
          assert(w.timing.a.samples==2)
        ''')

    def test_slow_and_fast_contradictions(self):
        self.lua.execute('''
          T.seconds(w,g);w.timing.a.lo=9;w.timing.a.hi=10
          l=load(16);receipt(l,7,160,162)
          assert(w.timing.a.hi==math.huge and w.timing.a.lo==20)
          receipt(l,16,320,322);clear();l=load(16,330)
          receipt(l,16,410,412)
          assert(w.timing.a.lo==0 and w.timing.a.hi==82/16)
        ''')

    def test_restart_threshold(self):
        self.lua.execute('''
          puts=0;p={db={},known={},store={put=function(_,key,value) puts=puts+1 end}}
          T.seconds(w,g);w.timing.a.lo=9;w.timing.a.hi=11
          T.persist(p,w);assert(puts==1)
          w.timing.a.hi=10.8;T.persist(p,w);assert(puts==1)
          w.timing.a.hi=10.4;T.persist(p,w);assert(puts==2)
          local restart={timing=p.timing,machines=w.machines}
          assert(T.seconds(restart,g)==10.4)
          local fresh={name='a',mt=g.mt,loads={},quarantined={}}
          assert(fresh.epoch==nil)
        ''')

    def test_restart_inflight_delivery_is_not_a_new_epoch(self):
        self.lua.execute('''
          l=load(16);l.timingRestart=true;clear();g.loads={l};g.epoch=nil
          T.load(w,g,l);receipt(l,16,160,162)
          assert(w.timing.a.samples==0 and g.timingExcluded.restart==1)
        ''')

    def test_individual_machines_and_type_median(self):
        self.lua.execute('''
          T.seconds(w,g);w.timing.a.hi=10
          b={name='b',mt={seconds=10}};T.seconds(w,b);w.timing.b.hi=20
          c={name='c',mt={}}
          assert(T.seconds(w,g)==10 and T.seconds(w,b)==20 and T.seconds(w,c)==15)
        ''')

    def test_one_probe_then_tight_range_stops(self):
        self.lua.execute('''
          T.seconds(w,g);w.timing.a.lo=5;w.timing.a.hi=20
          local probes=0
          for i=1,5 do clear();local l=load(16,i*400);if l.probe then probes=probes+1 end end
          assert(probes==1)
          receipt(g.loads[1],16,2160,2162)
          assert(w.timing.a.hi<20)
          w.timing.a.lo=9;w.timing.a.hi=10
          for i=1,20 do clear();local l=load(16,3000+i*200);assert(not l.probe) end
        ''')

    def test_stopped_quarantined_and_per_op_units(self):
        self.lua.execute('''
          l=load(16);l.request.run.stopping=true;receipt(l,8,80,82)
          assert(g.timingExcluded.stopped==1)
          clear();l=load(16);g.quarantined={{}};receipt(l,8,80,82)
          assert(g.timingExcluded.quarantine==1)
          g.quarantined={};clear();w.now=0;l=load(16)
          l.request.perOp=2;g.epoch.n=32
          receipt(l,8,160,162)
          assert(w.timing.a.lo==160/18)
        ''')


if __name__ == '__main__':
    unittest.main()
