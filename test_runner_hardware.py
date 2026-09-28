"""Configurable native robot recipes; no component catalog duplicated in Python."""
import copy
import unittest
import runner_scenario as scenario
from test_runner_scenario import minimal


def configured():
    value = minimal()
    value['schemaVersion'] = 3
    value['robot']['hardware'] = {
        'tier': 2, 'cpu': 'cpu2', 'memory': ['ram3', 'ram4'],
        'cards': ['redstonecard1'], 'upgrades': ['inventoryupgrade', 'craftingupgrade'],
        'storage': ['hdd2'], 'bootDrive': 0,
        'containers': [{'item': 'upgradecontainer1', 'component': 'inventoryupgrade'}]}
    return value


class HardwareContract(unittest.TestCase):
    def test_configured_recipe_preserves_user_selection_and_freezes_independently(self):
        raw = configured()
        normalized = scenario.normalize(raw)
        self.assertEqual(normalized['robot']['hardware'], raw['robot']['hardware'])
        raw['robot']['hardware']['memory'][0] = 'ram1'
        self.assertEqual(normalized['robot']['hardware']['memory'][0], 'ram3')
        self.assertEqual(normalized['observations']['onFull'], 'stop')
        self.assertEqual(scenario.normalize(normalized), normalized)

    def test_new_scenarios_default_to_fast_execution_without_changing_legacy_inputs(self):
        value=configured(); value.pop('execution',None)
        self.assertEqual(scenario.normalize(value)['execution']['mode'],'coordinated')
        self.assertEqual(scenario.normalize(value)['execution']['executionDelayMillis'],12)
        for version,mode in [(1,'coordinated'),(2,'baseline')]:
            legacy=minimal();legacy['schemaVersion']=version;legacy.pop('execution',None)
            result=scenario.normalize(legacy)['execution']
            self.assertEqual((result['mode'],result['executionDelayMillis']),(mode,12))
        value['execution']={'mode':'baseline','executionDelayMillis':12}
        self.assertEqual(scenario.normalize(value)['execution']['mode'],'baseline')
        self.assertEqual(scenario.normalize(value)['execution']['executionDelayMillis'],12)
        value['execution']={'mode':'coordinated','executionDelayMillis':0}
        self.assertEqual(scenario.normalize(value)['execution']['executionDelayMillis'],0)

    def test_paced_model_reference_is_explicit_and_v3_only(self):
        value=configured();value['execution']={'mode':'paced'}
        self.assertEqual(scenario.normalize(value)['execution']['mode'],'paced')
        for version in (1,2):
            value=minimal();value['schemaVersion']=version;value['execution']={'mode':'paced'}
            with self.assertRaises(ValueError):scenario.normalize(value)

    def test_no_silent_fixed_hardware_for_v3_and_no_legacy_reinterpretation(self):
        for hardware in [None, 'tier3', {}, {'tier': 3}]:
            value = configured(); value['robot']['hardware'] = hardware
            with self.subTest(hardware=hardware), self.assertRaises(ValueError): scenario.normalize(value)
        for version in [1, 2]:
            value = configured(); value['schemaVersion'] = version
            with self.subTest(version=version), self.assertRaises(ValueError): scenario.normalize(value)
            value['robot'].pop('hardware')
            self.assertEqual(scenario.normalize(value)['robot']['hardware'], 'tier3')

    def test_optional_slots_default_empty_not_forced_equipment(self):
        value = configured(); value['robot']['hardware'] = {
            'tier': 1, 'cpu': 'cpu1', 'memory': ['ram2'], 'storage': ['hdd1'], 'bootDrive': 0}
        result = scenario.normalize(value)['robot']['hardware']
        self.assertEqual(result['upgrades'], [])
        self.assertEqual(result['cards'], [])
        self.assertEqual(result['containers'], [])

    def test_creative_tier_is_explicit_and_preserves_the_selected_components(self):
        value=configured();value['robot']['hardware']['tier']='creative'
        self.assertEqual(scenario.normalize(value)['robot']['hardware'],value['robot']['hardware'])
        for tier in ['4','Creative','3',4,None]:
            value['robot']['hardware']['tier']=tier
            with self.subTest(tier=tier),self.assertRaises(ValueError):scenario.normalize(value)

    def test_recipe_shape_and_bounds(self):
        patches = [{'tier': 0}, {'tier': 4}, {'tier': True}, {'cpu': '../cpu3'},
                   {'memory': []}, {'memory': ['ram6'] * 3}, {'cards': ['a'] * 4},
                   {'upgrades': ['a'] * 10}, {'containers': [{'item': 'a'}] * 4},
                   {'storage': []}, {'storage': ['hdd1'] * 3}, {'bootDrive': 1},
                   {'bootDrive': False}, {'cpu': None}, {'invented': 1},
                   {'containers': [{'item': 'a', 'component': None}]},
                   {'containers': [{'item': 'a', 'slot': 1}]}]
        for patch in patches:
            value = configured(); value['robot']['hardware'].update(copy.deepcopy(patch))
            with self.subTest(patch=patch), self.assertRaises(ValueError): scenario.normalize(value)

    def test_experience_upgrade_initial_level_or_raw_xp_preserved(self):
        for setting in [{'level':0}, {'level':30}, {'experience':0}, {'experience':400.5}]:
            component=dict(item='experienceupgrade',**setting)
            value=configured(); value['robot']['hardware']['upgrades']=[component]
            value['robot']['hardware']['containers']=[{'item':'upgradecontainer3','component':component}]
            normalized=scenario.normalize(value)['robot']['hardware']
            self.assertEqual(normalized['upgrades'],[component])
            self.assertEqual(normalized['containers'][0]['component'],component)
        for component in [{'item':'experienceupgrade'}, {'item':'experienceupgrade','level':31},
                          {'item':'experienceupgrade','level':-1}, {'item':'experienceupgrade','level':True},
                          {'item':'experienceupgrade','level':1.5}, {'item':'experienceupgrade','experience':float('inf')},
                          {'item':'experienceupgrade','experience':-1}, {'item':'experienceupgrade','experience':True},
                          {'item':'experienceupgrade','level':1,'experience':10}, {'item':'inventoryupgrade','level':10},
                          {'item':'experienceupgrade','experience':2147483648}]:
            value=configured();value['robot']['hardware']['upgrades']=[component]
            with self.subTest(component=component),self.assertRaises(ValueError): scenario.normalize(value)

    def test_optional_robot_rng_seed_is_explicit_bounded_and_v3_only(self):
        value=configured()
        self.assertNotIn('randomSeed',scenario.normalize(value)['robot'])
        for seed in [0,17,2147483647]:
            value['robot']['randomSeed']=seed
            self.assertEqual(scenario.normalize(value)['robot']['randomSeed'],seed)
        for seed in [-1,2147483648,True,0.5,'17',None]:
            value['robot']['randomSeed']=seed
            with self.subTest(seed=seed),self.assertRaises(ValueError): scenario.normalize(value)
        for version in [1,2]:
            value=minimal();value['schemaVersion']=version;value['robot']['randomSeed']=17
            with self.assertRaises(ValueError): scenario.normalize(value)

    def test_v3_inventory_and_energy_follow_configurable_native_capacity(self):
        value = configured()
        value['robot']['inventory'] = [{'slot': 64, 'item': 'minecraft:stone', 'count': 64}]
        value['robot']['energy'] = 100000
        normalized = scenario.normalize(value)
        self.assertEqual(normalized['robot']['inventory'][0]['slot'], 64)
        self.assertEqual(normalized['robot']['energy'], 100000)
        for slot in [0, 65, True]:
            value['robot']['inventory'][0]['slot'] = slot
            with self.subTest(slot=slot), self.assertRaises(ValueError): scenario.normalize(value)
        for version in [1, 2]:
            value = minimal(); value['schemaVersion'] = version
            value['robot']['inventory'] = [{'slot': 17, 'item': 'minecraft:stone', 'count': 1}]
            with self.assertRaises(ValueError): scenario.normalize(value)


if __name__ == '__main__': unittest.main()
