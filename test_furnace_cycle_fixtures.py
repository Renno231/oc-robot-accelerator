"""Bounds and source-copy contracts; real behavior is tested inside native OC."""
import importlib.util
import copy
import json
from pathlib import Path
import tempfile
import unittest
import runner_scenario
from compare_machine_jobs import compare
from run_furnace_cycles import verified_stock_scan

ROOT = Path(__file__).parent
spec = importlib.util.spec_from_file_location('build_furnace_cycle', ROOT/'examples/warehouse/build_furnace_cycle.py')
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class FurnaceCycleFixturesTests(unittest.TestCase):
    def test_generated_variants_match_seed_and_stock_expectations(self):
        for seed, shortfall, ram in ((128,False,1),(100,False,1),(128,True,1),(128,False,2)):
            with self.subTest(seed=seed,shortfall=shortfall,ram=ram), tempfile.TemporaryDirectory() as tmp:
                path=generator.build(Path(tmp)/'cycle',seed,shortfall,ram)
                value=runner_scenario.load(path).normalized
                self.assertEqual(64,len(value['containers']))
                self.assertEqual(2,len(value['drones']))
                self.assertEqual('coordinated',value['execution']['mode'])
                self.assertEqual(['ram6']*ram,value['computer']['hardware']['memory'])
                clay=sum(s['count'] for c in value['containers'] for s in c['slots'] if s['item']=='minecraft:clay_ball')
                self.assertEqual(seed,clay)
                self.assertEqual(2,sum(b['block']=='minecraft:furnace' for b in value['blocks']))
                expected=sum(s['count'] for c in value['expect']['containers'] for s in c['slots'] if s.get('item')=='minecraft:brick')
                self.assertEqual(seed-(20 if shortfall else 0),expected)
                program=path.parent/'program'
                for relative in ('lib/map.lua','lib/logistics.lua','lib/warehouse.lua','lib/cbor.lua','lib/store.lua','lib/warehouse/view.lua','lib/warehouse/ui.lua','drone/agent.lua'):
                    self.assertEqual((ROOT/'drone-logistics'/relative).read_bytes(),(program/relative).read_bytes())
                self.assertEqual((ROOT/'fixtures/qmenu.lua').read_bytes(),(program/'lib/qmenu.lua').read_bytes())
                self.assertTrue((program/'route-metrics-enabled').exists())

    def test_shipped_fixture_is_generated(self):
        with tempfile.TemporaryDirectory() as tmp:
            fresh=generator.build(Path(tmp)/'cycle').parent
            shipped=ROOT/'examples/warehouse/furnace-cycle'
            self.assertEqual({p.relative_to(fresh) for p in fresh.rglob('*') if p.is_file()},
                             {p.relative_to(shipped) for p in shipped.rglob('*') if p.is_file()})
            for file in fresh.rglob('*'):
                if file.is_file(): self.assertEqual(file.read_bytes(),(shipped/file.relative_to(fresh)).read_bytes(),str(file))

    def test_cycle_duration_is_measured_but_final_stock_is_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for job,seconds in (('a',1400),('b',1450)):
                runtime=root/job/'runtime';disk=runtime/'world/opencomputers/disk/home';disk.mkdir(parents=True)
                (root/job/'job.json').write_text(json.dumps({'state':'passed','elapsedWallSeconds':seconds}))
                (runtime/'result.json').write_text(json.dumps({'scenarioId':'warehouse-furnace-cycle','status':'passed','reason':'passed','computer':{'energy':1},'ticks':1}))
                (disk/'equivalence.json').write_text(json.dumps({'jobs':{},'boots':[],'files':{},'warehouse':{'gameSeconds':seconds,'afterScan':{'brick':128}}}))
            value=compare(root,'a','b');self.assertFalse(value['unexpectedDifferences']);self.assertEqual(1,len(value['clockFileDifferences']))
            path=root/'b/runtime/world/opencomputers/disk/home/equivalence.json';value=json.loads(path.read_text());value['warehouse']['afterScan']['brick']=127;path.write_text(json.dumps(value))
            differences=compare(root,'a','b')['unexpectedDifferences'];self.assertEqual('$.evidence.warehouse.afterScan.brick',differences[0]['path'])

    def test_retention_classification_requires_exact_finished_stock_read(self):
        job={'state':'done','remaining':0,'requested':0,'moved':0,'trips':1,'held':[],
             'steps':[{'read':{'node':'4:65:2','side':3},'size':27,'listing':[]}]}
        evidence={'files':{'/etc/warehouse.db':{'s4_0_S':{'slots':27,'freeSlots':27,'items':[]}}}}
        self.assertTrue(verified_stock_scan(job,evidence))
        known_empty=copy.deepcopy(evidence)
        known_empty['files']['/etc/warehouse.db']['s4_0_S']['items']={'clay':{'item':{'name':'minecraft:clay_ball','damage':0,'label':'Clay'},'count':0,'maxSize':64}}
        self.assertTrue(verified_stock_scan(job,known_empty))
        for field,value in (('state','partial'),('requested',1),('trips',2),('held',[{'count':1}])):
            other=copy.deepcopy(job);other[field]=value;self.assertFalse(verified_stock_scan(other,evidence))
        other=copy.deepcopy(job);other['steps'][0]['read']['node']='10:63:7';self.assertFalse(verified_stock_scan(other,evidence))
        other=copy.deepcopy(job);other['steps'][0]['listing']=[{'name':'minecraft:coal','damage':0,'label':'Coal','size':4,'maxSize':64}]
        self.assertFalse(verified_stock_scan(other,evidence))
        observed=copy.deepcopy(evidence);entry=observed['files']['/etc/warehouse.db']['s4_0_S'];entry['freeSlots']=26
        entry['items']={'coal':{'item':{'name':'minecraft:coal','damage':0,'label':'Coal'},'count':4,'maxSize':64}}
        self.assertTrue(verified_stock_scan(other,observed));entry['items']['coal']['count']=3
        self.assertFalse(verified_stock_scan(other,observed))


if __name__=='__main__':
    unittest.main()
