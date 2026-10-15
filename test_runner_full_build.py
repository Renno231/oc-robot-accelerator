import unittest
import runner_scenario
from test_runner_hardware import configured

class FullBuildScenarioTests(unittest.TestCase):
    def fixture(self):
        value=configured()
        value['world']['fullBuild']={'min':[0,65,0],'max':[203,137,199],
            'expected':'expected.bin.gz','palette':['minecraft:air','minecraft:stone'],
            'chest':value['robot']['position'],'materials':[{'item':'minecraft:stone','count':1013113}]}
        value['execution']={'maxTicks':200000000,'timeoutSeconds':90000}
        return value
    def test_workload_scope_is_separate_from_observation_region(self):
        value=runner_scenario.normalize(self.fixture())
        self.assertEqual(value['world']['fullBuild']['max'],[203,137,199])
        self.assertEqual(value['execution']['maxTicks'],200000000)
    def test_explicit_return_bays_keep_native_chest_capacity(self):
        value=self.fixture();value['world']['fullBuild']['returnSlots']=1
        self.assertEqual(runner_scenario.normalize(value)['world']['fullBuild']['returnSlots'],1)
        for bad in (-1,27,True,1.5):
            value['world']['fullBuild']['returnSlots']=bad
            with self.assertRaises(ValueError):runner_scenario.normalize(value)
    def test_explicit_tick_budget_can_exceed_island_budget(self):
        value=self.fixture();value['execution']['maxTicks']=300000000
        self.assertEqual(runner_scenario.normalize(value)['execution']['maxTicks'],300000000)
    def test_empty_materials_and_unsafe_expected_path_rejected(self):
        for field,bad in [('materials',[]),('palette',[]),('expected','../expected.gz')]:
            with self.subTest(field=field):
                value=self.fixture();value['world']['fullBuild'][field]=bad
                with self.assertRaises(ValueError):runner_scenario.normalize(value)
    def test_resume_requires_saved_world_and_explicit_census(self):
        value=self.fixture()
        value['world']['fullBuild']['resume']={'robot':[151,78,43],'builtBlocks':367543}
        with self.assertRaises(ValueError):runner_scenario.normalize(value)
        value['world']['source']='saved-world'
        value['robot']['position']=[87,78,108]
        result=runner_scenario.normalize(value)
        self.assertEqual(result['robot']['position'],[87,78,108])
        self.assertEqual(result['world']['fullBuild']['resume']['builtBlocks'],367543)
    def test_workspace_spawn_does_not_expand_observation_scope(self):
        value=self.fixture();value['robot']['position']=[87,78,108]
        result=runner_scenario.normalize(value)
        self.assertEqual(result['world']['region'],value['world']['region'])
        value['robot']['position']=[1000,78,108]
        with self.assertRaises(ValueError):runner_scenario.normalize(value)

if __name__=='__main__':unittest.main()
