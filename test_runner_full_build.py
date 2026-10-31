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

class MetadataTests(unittest.TestCase):
    def test_coloured_kinds_are_stocked_and_verified_by_metadata(self):
        value=FullBuildScenarioTests().fixture();fixture=value['world']['fullBuild']
        fixture['palette']=['minecraft:air','minecraft:wool:9','minecraft:wool:14']
        fixture['materials']=[{'item':'minecraft:wool','count':5,'metadata':9},{'item':'minecraft:wool','count':3,'metadata':14}]
        self.assertEqual(runner_scenario.normalize(value)['world']['fullBuild']['materials'][1]['metadata'],14)
        for field,bad in [('palette',['minecraft:wool:16']),('palette',['minecraft:wool:x']),
                          ('materials',[{'item':'minecraft:wool','count':1,'metadata':16}])]:
            with self.subTest(bad=bad):
                broken=FullBuildScenarioTests().fixture();broken['world']['fullBuild'][field]=bad
                with self.assertRaises(ValueError):runner_scenario.normalize(broken)

class FourRobotFullBuildTests(unittest.TestCase):
    """Several v4 robots share one full-build volume; each restocks from its own chest and budget."""
    def fixture(self):
        corners=[[-1,65,-1],[204,65,-1],[-1,65,200],[204,65,200]]
        robot=lambda i:{'position':[corners[i][0]+(1 if i%2==0 else -1),65,corners[i][2]],'facing':'north','energy':210500,
                        'hardware':configured()['robot']['hardware'],'program':{'directory':'robot-%d'%i}}
        stock=[{'item':'minecraft:stone','count':250000}]
        return {'schemaVersion':4,'id':'island-four','world':{'region':{'min':[-2,64,-2],'max':[6,67,6]},
                'fullBuild':{'min':[0,65,0],'max':[203,137,199],'expected':'expected.bin.gz',
                             'palette':['minecraft:air','minecraft:stone'],'chest':corners[0],'materials':stock,
                             'extraChests':[{'position':c,'materials':stock} for c in corners[1:]]}},
                'drones':[],'robots':[robot(i) for i in range(4)],
                'execution':{'mode':'coordinated','infiniteEnergy':True,'maxTicks':200000000,'timeoutSeconds':90000}}
    def test_robots_and_chests_may_stand_on_the_work_space_rim(self):
        value=runner_scenario.normalize(self.fixture())
        self.assertEqual(value,runner_scenario.normalize(value))
        self.assertEqual([r['position'] for r in value['robots']],[[0,65,-1],[203,65,-1],[0,65,200],[203,65,200]])
        self.assertEqual([c['position'] for c in value['world']['fullBuild']['extraChests']],[[204,65,-1],[-1,65,200],[204,65,200]])
    def test_extra_chests_are_bounded_distinct_and_inside_the_rim(self):
        for change in ('outside','duplicate','empty','four','resume','no-materials'):
            with self.subTest(change=change):
                value=self.fixture();fixture=value['world']['fullBuild'];extra=fixture['extraChests']
                if change=='outside':extra[0]['position']=[206,65,-1]
                if change=='duplicate':extra[0]['position']=fixture['chest']
                if change=='empty':fixture['extraChests']=[]
                if change=='four':extra.append({'position':[100,65,-1],'materials':extra[0]['materials']})
                if change=='resume':fixture['resume']={'robot':[0,65,-1],'builtBlocks':0};value['world']['source']='saved-world'
                if change=='no-materials':extra[0]['materials']=[]
                with self.assertRaises(ValueError):runner_scenario.normalize(value)
    def test_robot_far_from_the_work_space_rejected(self):
        value=self.fixture();value['robots'][3]['position']=[300,65,300]
        with self.assertRaises(ValueError):runner_scenario.normalize(value)

if __name__=='__main__':unittest.main()
