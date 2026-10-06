import json
from pathlib import Path
import tempfile
import unittest
from build_machine_comparisons import prepare
from compare_machine_jobs import comparable,diff,normalize,identities,compare,additional_files
from reload_machine_probe import command_for
from run_machine_comparisons import scenario_paths


class MachineComparisonsTest(unittest.TestCase):
    def test_additional_mapping_files_come_from_both_real_program_disks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for source,disk,text in (('program','a','controller'),('second-program','b','tablet')):
                (root/source).mkdir();(root/source/'main.lua').write_text(text)
                drive=root/'world/opencomputers'/disk
                (drive/'home/program').mkdir(parents=True);(drive/'home/program/main.lua').write_text(text)
                (drive/'etc').mkdir();(drive/'etc/mapclient.cfg').write_text(text)
            self.assertEqual(additional_files(root),{'computer/etc/mapclient.cfg':'controller','secondComputer/etc/mapclient.cfg':'tablet'})
            (root/'world/opencomputers/b/home/program/main.lua').write_text('controller')
            with self.assertRaises(ValueError): additional_files(root)
    def test_sweep_covers_all_requested_families(self):
        paths=scenario_paths()
        self.assertEqual(len(paths),24)
        self.assertEqual([sum(p.parts[1]==family for p in paths) for family in ('logistics','mapping','drones')],[16,2,6])
    def test_reload_command_changes_only_root_and_adds_explicit_probe_phase(self):
        original=['java','-Drobotspike.root=old','-Drobotspike.mode=baseline','-jar','forge.jar']
        command=command_for(original,Path('new'),'resume')
        self.assertNotIn('-Drobotspike.root=old',command)
        self.assertIn('-Drobotspike.reloadProbe=resume',command)
        self.assertIn('-Drobotspike.mode=baseline',command)
        self.assertEqual(original[1],'-Drobotspike.root=old')
    def test_preparation_preserves_source_and_observes_only_controller(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';(source/'program').mkdir(parents=True)
            (source/'program/main.lua').write_text('return 1')
            (source/'scenario.json').write_text(json.dumps({'computer':{'program':{'directory':'program'}}}))
            path=prepare(source,root/'copy','coordinated')
            self.assertEqual((source/'program/main.lua').read_text(),'return 1')
            self.assertEqual((path.parent/'program/native-main.lua').read_text(),'return 1')
            self.assertEqual(json.loads(path.read_text())['execution']['mode'],'coordinated')
            with self.assertRaises(FileExistsError): prepare(source,path.parent,'baseline')

    def test_accounting_inventory_and_positions_are_strict(self):
        self.assertEqual(diff({'remaining':0},{'remaining':0}),[])
        self.assertEqual(diff({'remaining':0},{'remaining':1})[0]['path'],'$.remaining')
        r={'status':'passed','reason':'passed','drones':[{'index':0,'blockPosition':[0,65,0],'inventory':[],'running':True}]}
        c=comparable({'state':'passed'},r,None)
        r['drones'][0]['inventory']=[{'count':1}]
        self.assertTrue(diff(c,comparable({'state':'passed'},r,None)))

    def test_only_recorded_native_identity_fields_are_normalized(self):
        self.assertEqual(identities({'files':[]}),{})
        evidence={'files':{'/etc/logistics.drones':{'d1':{'address':'uuid','token':'abc123'}}}}
        self.assertEqual(normalize({'uuid':['abc123',5,'other']},identities(evidence)),{'address:d1':['token:d1',5,'other']})

    def test_native_creation_clock_is_reported_and_order_remains_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for job,stamps in (('a',(1,2)),('b',(4,5))):
                native=root/job/'runtime';disk=native/'world/opencomputers/disk/home';disk.mkdir(parents=True)
                (root/job/'job.json').write_text(json.dumps({'state':'passed','elapsedWallSeconds':1}))
                (native/'result.json').write_text(json.dumps({'scenarioId':'test','status':'passed','reason':'passed','computer':{'energy':1},'ticks':1}))
                (disk/'equivalence.json').write_text(json.dumps({'jobs':{},'boots':[],'files':{'/etc/map.cfg':{'nodes':{'A':{'created':stamps[0]},'B':{'created':stamps[1]}}}}}))
            value=compare(root,'a','b');self.assertEqual(len(value['differences']),2);self.assertEqual(value['unexpectedDifferences'],[])
            path=root/'b/runtime/world/opencomputers/disk/home/equivalence.json';data=json.loads(path.read_text());data['files']['/etc/map.cfg']['nodes']['A']['created']=6;path.write_text(json.dumps(data))
            self.assertTrue(compare(root,'a','b')['unexpectedDifferences'])


if __name__=='__main__': unittest.main()
