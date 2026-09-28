"""Public workload inputs stay executable through the real scenario contract."""
import unittest
from pathlib import Path

import runner_scenario
import verify_public_workloads as workloads


class PublicWorkloadsTest(unittest.TestCase):
    def test_cross_chunk_example_is_self_contained_and_accelerated(self):
        path=Path(__file__).parent/'examples/cross-chunk/scenario.json'
        scenario=runner_scenario.load(path)
        self.assertEqual(scenario.normalized['schemaVersion'],3)
        self.assertEqual(scenario.normalized['execution']['mode'],'coordinated')
        self.assertEqual(scenario.normalized['execution']['executionDelayMillis'],12)
        self.assertEqual(scenario.normalized['robot']['hardware']['cpu'],'cpu3')
        self.assertEqual((scenario.program/'distance.txt').read_text().strip(),'48')
        self.assertEqual(scenario.normalized['expect']['position'],[0,65,0])
        self.assertEqual(scenario.normalized['world']['region']['min'],[-2,64,-49])

    def test_cases_keep_real_power_bounds_and_explicit_modes(self):
        cases=workloads.cases()
        self.assertEqual(len({name for name,_,_,_ in cases}),len(cases))
        for name,spec,program,expected in cases:
            with self.subTest(case=name):
                normalized=runner_scenario.normalize(spec)
                self.assertEqual(normalized['execution']['executionDelayMillis'],12)
                self.assertGreater(normalized['robot']['energy'],0)
                self.assertLessEqual(normalized['robot']['energy'],20500)
                self.assertIn(expected,('passed','failed'))
                self.assertTrue(program or name.startswith('cross-chunk'))
        endurance=next(spec for name,spec,_,_ in cases if name=='endurance-coordinated')
        self.assertGreater(endurance['execution']['maxTicks'],10000)
        self.assertEqual(endurance['observations']['onFull'],'stop')
        self.assertEqual(endurance['observations']['maxBytes'],1048576)
        self.assertTrue(any(name=='recording-fail' and expected=='failed' for name,_,_,expected in cases))

    def test_comparison_keeps_resource_and_timing_differences(self):
        def row(job,time,energy):
            return {'jobId':job,'status':{'state':'passed'},'supervisor':{'cleanup_ok':True,'elapsed_wall_seconds':time},
                    'result':{'status':'passed','elapsedNanos':int(time*1e9),'ticks':200,
                              'robot':{'position':[0,65,0],'facing':'north','inventory':[], 'tool':{},'energy':energy}},
                    'programOutputs':{'actions.tsv':'swing\t1\ttrue\tblock\t'+str(time)+'\t'+str(energy)+'\n'},
                    'finalBlocks':[],'observationSummary':{'finalRecorded':True}}
        comparison=workloads.compare(row('reference',2,99),row('candidate',1,98))
        self.assertTrue(comparison['actionValuesMatch'])
        self.assertFalse(comparison['actionUptimeMatch'])
        self.assertFalse(comparison['actionEnergyMatch'])
        self.assertFalse(comparison['allSelectedObservationsMatch'])
        self.assertEqual(comparison['fixtureSpeedup'],2)
        bad=row('failed',1,99); bad['status']['state']='failed'
        with self.assertRaises(ValueError): workloads.compare(row('reference',2,99),bad)
        truncated=row('truncated',1,99); truncated['observationSummary']['finalRecorded']=False
        with self.assertRaises(ValueError): workloads.compare(row('reference',2,99),truncated)


if __name__=='__main__': unittest.main()
