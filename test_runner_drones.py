import copy
import json
from pathlib import Path
import tempfile
import unittest
import runner_scenario as scenario
from runner_jobs import _install


def valid():
    return {'schemaVersion': 4, 'id': 'drone-test',
            'world': {'region': {'min': [-2, 64, -2], 'max': [8, 68, 2]}},
            'drones': [{'position': [0, 65, 0], 'hardware': {'tier': 2, 'cpu': 'cpu1', 'memory': ['ram2']},
                        'eeprom': 'main.lua'}],
            'containers': [{'position': [0, 64, 0], 'block': 'minecraft:chest',
                            'slots': [{'slot': 1, 'item': 'minecraft:iron_ingot', 'count': 64}]}],
            'expect': {'containers': [{'position': [0, 64, 0], 'slots': [{'slot': 1, 'count': 0}]}],
                       'drones': [{'index': 0, 'blockPosition': [0, 65, 0],
                                   'inventory': [{'slot': 1, 'item': 'minecraft:iron_ingot', 'count': 64}]}]}}


class DroneScenarioTests(unittest.TestCase):
    def test_placed_blocks_default_to_baseline_without_changing_plain_robot_default(self):
        v=valid();v.pop('drones');v['robot']={'position':[0,65,0],'hardware':{'tier':3,'cpu':'cpu3','memory':['ram6'],'storage':['hdd3'],'bootDrive':0}}
        v['program']={'directory':'program'};v['expect']={};v.pop('execution',None);v['blocks']=[]
        self.assertEqual(scenario.normalize(v)['execution']['mode'],'baseline')
        v['execution']={'mode':'coordinated'}
        self.assertEqual(scenario.normalize(v)['execution']['mode'],'coordinated')
        v.pop('execution');v.pop('blocks')
        self.assertEqual(scenario.normalize(v)['execution']['mode'],'coordinated')

    def test_valid_and_idempotent(self):
        n = scenario.normalize(valid())
        self.assertEqual(n, scenario.normalize(n))
        self.assertEqual(n['execution']['mode'], 'baseline')
        self.assertNotIn('program', n)
        for tier in (1, 2, 'creative'):
            v = valid(); v['drones'][0]['hardware']['tier'] = tier
            v['drones'] *= 4
            self.assertEqual(len(scenario.normalize(v)['drones']), 4)

    def test_rejections(self):
        cases = [(['drones'], []), (['drones'], valid()['drones'] * 5),
                 (['robot'], {}), (['program'], {'directory': 'program'}),
                 (['execution'], {'mode': 'paced'}),
                 (['drones', 0, 'hardware', 'tier'], 3), (['drones', 0, 'hardware', 'tier'], True),
                 (['drones', 0, 'hardware', 'memory'], []), (['drones', 0, 'hardware', 'memory'], ['ram1'] * 3),
                 (['drones', 0, 'hardware', 'cards'], ['redstonecard1'] * 4),
                 (['drones', 0, 'hardware', 'upgrades'], ['inventoryupgrade'] * 10),
                 (['drones', 0, 'hardware', 'cpu'], 'bad:name'),
                 (['drones', 0, 'hardware', 'storage'], []),
                 (['drones', 0, 'position'], [99, 65, 0]),
                 (['drones', 0, 'eeprom'], '../main.lua'), (['drones', 0, 'eeprom'], 'main.txt'),
                 (['drones', 0, 'eepromData'], 12), (['drones', 0, 'eepromData'], 'x' * (1024 * 1024 + 1)),
                 (['drones', 0, 'inventory'], [{'slot': 9, 'item': 'minecraft:stone', 'count': 1}]),
                 (['drones', 0, 'inventory'], [{'slot': 1, 'item': 'minecraft:stone', 'count': 1}] * 2),
                 (['containers'], valid()['containers'] * 129),
                 (['containers'], valid()['containers'] * 2),
                 (['containers', 0, 'position'], [99, 65, 0]),
                 (['containers', 0, 'slots'], [{'slot': 1, 'item': 'minecraft:stone', 'count': 0}]),
                 (['containers', 0, 'slots'], [{'slot': 1, 'item': 'minecraft:stone', 'count': 65}]),
                 (['expect', 'containers', 0, 'position'], [1, 64, 0]),
                 (['expect', 'drones', 0, 'index'], 1),
                 (['expect', 'drones', 0, 'blockPosition'], [99, 65, 0]),
                 (['expect', 'drones', 0, 'inventory'], [{'slot': 1, 'count': 1}]),
                 (['expect', 'drones', 0, 'inventory'], [{'slot': 1, 'count': 0}] * 2),
                 (['expect', 'position'], [0, 65, 0]), (['unknown'], 1)]
        cases += [(['drones', 0, 'energy'], v) for v in (0, -1, True, float('inf'), float('nan'), 2147483648)]
        for path, replacement in cases:
            with self.subTest(path=path, value=str(replacement)[:64]):
                v = valid(); target = v
                for key in path[:-1]: target = target[key]
                target[path[-1]] = replacement
                with self.assertRaises(ValueError): scenario.normalize(v)
        for path in (['drones'], ['drones', 0, 'eeprom'], ['drones', 0, 'hardware']):
            v = valid(); target = v
            for key in path[:-1]: target = target[key]
            del target[path[-1]]
            with self.assertRaises(ValueError): scenario.normalize(v)

    def test_freeze_install_and_local_file_checks(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); src = root / 'src'; src.mkdir()
            (src / 'main.lua').write_text('computer.shutdown()')
            (src / 'scenario.json').write_text(json.dumps(valid()))
            spec = scenario.load(src / 'scenario.json')
            scenario.freeze(spec, root / 'inputs')
            runtime = root / 'runtime'; (runtime / 'config/opencomputers').mkdir(parents=True)
            _install(root / 'inputs', runtime, spec.normalized['execution'], lambda: None)
            self.assertEqual((runtime / 'eeprom/main.lua').read_text(), 'computer.shutdown()')
            (src / 'main.lua').unlink()
            with self.assertRaises(ValueError): scenario.load(src / 'scenario.json')
            (src / 'main.lua').mkdir()
            with self.assertRaises(ValueError): scenario.load(src / 'scenario.json')

    def test_eeprom_input_bounds_and_case_aliases(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); v = valid(); manifest = root / 'scenario.json'
            manifest.write_text(json.dumps(v))
            (root / 'main.lua').write_bytes(b'x' * (scenario.PROGRAM_FILE_BYTES + 1))
            with self.assertRaises(ValueError): scenario.load(manifest)
            (root / 'main.lua').write_text('computer.shutdown()')
            v['drones'].append(copy.deepcopy(v['drones'][0])); v['drones'][1]['eeprom'] = 'MAIN.lua'
            manifest.write_text(json.dumps(v))
            with self.assertRaises(ValueError): scenario.load(manifest)
            (root / 'code').mkdir(); (root / 'code/a.lua').write_text(''); (root / 'code/b.lua').write_text('')
            v['drones'][0]['eeprom'] = 'code/a.lua'; v['drones'][1]['eeprom'] = 'CODE/b.lua'
            manifest.write_text(json.dumps(v))
            with self.assertRaises(ValueError): scenario.load(manifest)
            v['drones'][1]['eeprom'] = 'code/a.lua'; manifest.write_text(json.dumps(v))
            self.assertEqual(len(scenario.load(manifest).eeprom_entries), 1)

    def test_legacy_and_v4_robot(self):
        v = {'schemaVersion': 3, 'id': 'robot-test', 'program': {'directory': 'program'},
             'world': valid()['world'], 'robot': {'position': [0, 65, 0],
             'hardware': {'tier': 1, 'cpu': 'cpu1', 'memory': ['ram1'], 'storage': ['hdd1'], 'bootDrive': 0}}}
        old = scenario.normalize(v); v['schemaVersion'] = 4
        new = scenario.normalize(v)
        self.assertEqual(new['robot'], old['robot']); self.assertEqual(new['execution'], old['execution'])
        for version in (1, 2):
            legacy = copy.deepcopy(v); legacy['schemaVersion'] = version; del legacy['robot']['hardware']
            self.assertEqual(scenario.normalize(legacy)['robot']['hardware'], 'tier3')
            legacy['drones'] = valid()['drones']
            with self.assertRaises(ValueError): scenario.normalize(legacy)
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); (root / 'program').mkdir(); (root / 'program/main.lua').write_text('return')
            (root / 'hardware.json').write_text(json.dumps(v['robot']['hardware']))
            v['robot']['hardware'] = {'preset': 'hardware.json'}
            (root / 'scenario.json').write_text(json.dumps(v))
            loaded = scenario.load(root / 'scenario.json')
            self.assertIsNotNone(loaded.hardware_preset)
            self.assertEqual(loaded.normalized['robot'], old['robot'])

    def test_completion_guard_is_machine_specific(self):
        from runner_drones import completed_result
        value = {'runnerSchemaVersion': 1, 'scenarioId': 'test', 'mode': 'baseline',
                 'drones': [{'index': 0, 'state': 'Stopped', 'lastError': None}]}
        completed_result(value, 'test', 1)
        value['mode']='coordinated';completed_result(value,'test',1)
        for key, replacement in [('mode', 'paced'), ('scenarioId', 'other'), ('drones', [])]:
            v = dict(value); v[key] = replacement
            with self.assertRaises(ValueError): completed_result(v, 'test', 1)
        value['drones'][0]['lastError'] = 'boom'
        with self.assertRaises(ValueError): completed_result(value, 'test', 1)
        value['drones'][0]['lastError'] = None; value['drones'][0]['index'] = False
        with self.assertRaises(ValueError): completed_result(value, 'test', 1)

    def test_drone_observation_summary(self):
        import runner_observations
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / 'observations.ndjson'
            record = {'schemaVersion': 1, 'sequence': 0, 'tick': 3, 'kind': 'initial',
                      'region': {'min': [0, 65, 0], 'max': [0, 65, 0]}, 'everyTicks': 10,
                      'blocks': [{'position': [0, 65, 0], 'block': 'minecraft:air', 'properties': {}}],
                      'drones': [{'index': 0, 'position': [0.5, 65.0, 0.5], 'blockPosition': [0, 65, 0], 'energy': 5000.0}]}
            p.write_text(json.dumps(record) + '\n')
            self.assertEqual(runner_observations.summary(p)['lastDrones'], record['drones'])
            record['drones'][0]['energy'] = True
            p.write_text(json.dumps(record) + '\n')
            with self.assertRaises(ValueError): runner_observations.summary(p)


if __name__ == '__main__': unittest.main()
