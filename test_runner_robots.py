import copy
import json
from pathlib import Path
import tempfile
import unittest

import runner_scenario as scenario
from runner_drones import completed_result, observation
from runner_jobs import _install


def valid():
    return json.loads(Path('examples/robots/crafting-smoke/scenario.json').read_text())


class RobotScenarioTests(unittest.TestCase):
    def test_native_recipe_and_normalized_program_identity(self):
        value = valid(); normalized = scenario.normalize(value)
        self.assertEqual(normalized, scenario.normalize(normalized))
        for i, robot in enumerate(normalized['robots']):
            self.assertEqual(robot['program'], {'directory': f'robot-program-{i}', 'entry': 'main.lua'})
            self.assertIn('craftingupgrade', robot['hardware']['upgrades'])
            self.assertIn('wlancard2', robot['hardware']['cards'])
            self.assertNotIn('tool', robot)
        value['robots'] += copy.deepcopy(value['robots'])
        value['robots'][2]['position'] = [0, 66, 0]; value['robots'][3]['position'] = [2, 66, 0]
        self.assertEqual(len(scenario.normalize(value)['robots']), 4)
        value.pop('computer'); value['containerEdits'] = []; value['expect']['robots'] = [{'index': 0}]
        self.assertEqual(scenario.normalize(value)['drones'], [])

    def test_infinite_energy_explicit_and_legacy_unchanged(self):
        v = valid()
        for flag in (True, False):
            v['execution']['infiniteEnergy'] = flag
            self.assertIs(scenario.normalize(v)['execution']['infiniteEnergy'], flag)
        v['execution'].pop('infiniteEnergy')
        self.assertNotIn('infiniteEnergy', scenario.normalize(v)['execution'])
        for flag in (1, None, 'true'):
            v['execution']['infiniteEnergy'] = flag
            with self.assertRaises(ValueError): scenario.normalize(v)
        for version in (2, 3):
            old = {'schemaVersion': version, 'id': 'legacy', 'world': valid()['world'],
                   'program': {'directory': 'program'}, 'robot': {'position': [0, 65, 0]},
                   'execution': {'infiniteEnergy': True}}
            if version == 3: old['robot']['hardware'] = valid()['robots'][0]['hardware']
            with self.assertRaises(ValueError): scenario.normalize(old)

    def test_reject_robot_shapes(self):
        cases = [(['robots'], []), (['robots'], valid()['robots'] * 3),
                 (['robots', 0, 'facing'], 'up'), (['robots', 0, 'position'], [999, 65, 0]),
                 (['robots', 1, 'position'], [0, 65, 0]), (['robots', 0, 'tool'], {}),
                 (['robots', 0, 'program', 'directory'], '../escape'),
                 (['robots', 0, 'program', 'entry'], 'main.txt'),
                 (['robots', 0, 'inventory'], [{'slot': 65, 'item': 'minecraft:stone', 'count': 1}]),
                 (['expect', 'robots'], [{'index': 2}]),
                 (['expect', 'robots'], [{'index': 0, 'inventory': [{'slot': 1, 'count': 1}]}])]
        cases += [(['robots', 0, 'energy'], v) for v in (0, True, float('inf'), 2147483648)]
        for path, replacement in cases:
            with self.subTest(path=path):
                v = valid(); target = v
                for key in path[:-1]: target = target[key]
                target[path[-1]] = replacement
                with self.assertRaises(ValueError): scenario.normalize(v)

    def test_container_edit_triggers_and_bounds(self):
        for edit in ({'atTick': 0}, {'request': {'computer': 0, 'marker': 'home/a', 'signal': 'a_done'}}):
            v = valid(); v['containerEdits'] = [dict(position=[4, 64, 0], slot=1, count=1, **edit)]
            self.assertEqual(scenario.normalize(v), scenario.normalize(scenario.normalize(v)))
        for change in ({'count': 0}, {'slot': 65}, {'expectedCount': 1}, {'atTick': 4},
                       {'request': {'computer': 1, 'marker': 'home/a', 'signal': 'done'}},
                       {'request': {'computer': 0, 'marker': '../escape', 'signal': 'done'}},
                       {'request': {'computer': 0, 'marker': 'home/a', 'signal': 'bad signal'}},
                       {'position': [1, 64, 0]}):
            v = valid(); v['containerEdits'][0].update(change)
            with self.assertRaises(ValueError): scenario.normalize(v)
        v = valid(); v['containerEdits'][0].pop('request')
        with self.assertRaises(ValueError): scenario.normalize(v)

    def test_container_bound_128(self):
        v = valid(); v['world']['region'] = {'min': [0, 63, 0], 'max': [127, 67, 2]}
        v['world']['blocks'] = []; v['containerEdits'] = []
        v['containers'] = [{'position': [x, 64, 0], 'block': 'minecraft:chest', 'slots': []} for x in range(128)]
        v['expect']['containers'] = [{'position': c['position'], 'slots': []} for c in v['containers']]
        n = scenario.normalize(v); self.assertEqual(len(n['containers']), 128)
        for key in ('containers', 'expect'):
            bad = copy.deepcopy(v)
            if key == 'containers': bad[key].append(copy.deepcopy(bad[key][-1]))
            else: bad[key]['containers'].append(copy.deepcopy(bad[key]['containers'][-1]))
            with self.assertRaises(ValueError): scenario.normalize(bad)

    def test_frozen_robot_trees_and_install_hash_drift(self):
        spec = scenario.load('examples/robots/crafting-smoke/scenario.json')
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); scenario.freeze(spec, root/'inputs')
            runtime = root/'runtime'; (runtime/'config/opencomputers').mkdir(parents=True)
            _install(root/'inputs', runtime, spec.normalized['execution'], lambda: None)
            for i in range(2):
                self.assertEqual((runtime/f'robot-program-{i}'/'main.lua').read_bytes(),
                                 (spec.robot_programs[i][1]/'main.lua').read_bytes())
            self.assertIn('ignorePower=true', (runtime/'config/opencomputers/settings.conf').read_text())
            (root/'inputs/robot-program-1/main.lua').write_text('changed')
            other = root/'other'; (other/'config/opencomputers').mkdir(parents=True)
            with self.assertRaises(ValueError): _install(root/'inputs', other, spec.normalized['execution'], lambda: None)

    def test_source_overlap_missing_entry_and_file_bounds(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); v = valid()
            for name in ('controller', 'crafter-a', 'crafter-b'):
                (root/name).mkdir(); (root/name/'main.lua').write_text('return')
            manifest = root/'scenario.json'
            def load(): manifest.write_text(json.dumps(v)); return scenario.load(manifest)
            load()
            v['robots'][1]['program']['directory'] = 'crafter-a'
            with self.assertRaises(ValueError): load()
            v['robots'][1]['program']['directory'] = 'crafter-b'
            (root/'crafter-b/main.lua').unlink()
            with self.assertRaises(ValueError): load()
            (root/'crafter-b/main.lua').write_bytes(b'x'*(scenario.PROGRAM_FILE_BYTES+1))
            with self.assertRaises(ValueError): load()

    def test_completion_requires_all_clean_stopped_returned_robots(self):
        value = {'runnerSchemaVersion': 1, 'scenarioId': 'test', 'mode': 'coordinated', 'drones': [],
                 'robots': [{'index': 0, 'state': 'Stopped', 'lastError': None, 'program': {'status': 'returned'}}]}
        completed_result(value, 'test', 0, robot_count=1)
        for change in ({'index': True}, {'state': 'Stopping'}, {'lastError': 'boom'}, {'program': {'status': 'error'}}):
            bad = copy.deepcopy(value); bad['robots'][0].update(change)
            with self.assertRaises(ValueError): completed_result(bad, 'test', 0, robot_count=1)
        with self.assertRaises(ValueError): completed_result(value, 'test', 0, robot_count=2)

    def test_coordinator_accepts_healthy_persistent_robot_service(self):
        value = {'runnerSchemaVersion': 1, 'scenarioId': 'test', 'mode': 'coordinated', 'drones': [],
                 'computer': {'lastError': None}, 'program': {'status': 'returned'},
                 'robots': [{'index': 0, 'state': 'Paused', 'lastError': None, 'program': {'status': 'not_returned'}}]}
        completed_result(value, 'test', 0, computer_present=True, robot_count=1)
        for change in ({'lastError': 'boom'}, {'program': {'status': 'error'}}, {'state': 'Stopped'}):
            bad = copy.deepcopy(value); bad['robots'][0].update(change)
            with self.assertRaises(ValueError): completed_result(bad, 'test', 0, computer_present=True, robot_count=1)
        value['program']['status'] = 'not_returned'
        with self.assertRaises(ValueError): completed_result(value, 'test', 0, computer_present=True, robot_count=1)

    def test_robot_observation_validation(self):
        record = {'drones': [], 'robots': [{'index': 0, 'position': [0, 65, 0], 'facing': 'north', 'energy': 20000}]}
        observation(record)
        for change in ({'index': True}, {'position': [0, 65]}, {'facing': 'up'}, {'energy': True}):
            bad = copy.deepcopy(record); bad['robots'][0].update(change)
            with self.assertRaises(ValueError): observation(bad)


if __name__ == '__main__': unittest.main()
