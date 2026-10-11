"""Microcontrollers reuse the v4 EEPROM contract, not an OpenOS program drive."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import runner_drones
import runner_scenario
from test_runner_drones import valid


def fixture():
    value = valid()
    value['computer'] = {'position': [-1, 65, 0],
        'hardware': {'tier': 3, 'cpu': 'cpu3', 'memory': ['ram6'],
                     'cards': ['wlancard2'], 'storage': ['hdd3'], 'bootDrive': 0},
        'program': {'directory': 'program', 'entry': 'main.lua'}}
    value['microcontrollers'] = [{'position': [2, 65, 0], 'eeprom': 'sensor.lua',
        'hardware': {'tier': 2, 'cpu': 'cpu1', 'memory': ['ram1'],
                     'cards': ['wlancard2'], 'upgrades': ['transposer']}}]
    return value


class MicrocontrollerTests(unittest.TestCase):
    def test_normalization_and_eeprom_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'program').mkdir()
            (root / 'program/main.lua').write_text('return true')
            (root / 'main.lua').write_text('computer.shutdown()')
            (root / 'sensor.lua').write_text('while true do computer.pullSignal() end')
            (root / 'scenario.json').write_text(json.dumps(fixture()))
            loaded = runner_scenario.load(root / 'scenario.json')
            self.assertEqual(loaded.normalized['microcontrollers'][0]['eepromData'], '')
            self.assertNotIn('inventory', loaded.normalized['microcontrollers'][0])
            self.assertEqual({str(p) for p, _ in loaded.eeprom_entries}, {'main.lua', 'sensor.lua'})
            (root / 'sensor.lua').unlink()
            with self.assertRaises(ValueError): runner_scenario.load(root / 'scenario.json')

    def test_controller_required_and_no_inventory(self):
        value = fixture()
        del value['computer']
        with self.assertRaises(ValueError): runner_drones.normalize(value)
        value = fixture()
        value['microcontrollers'][0]['inventory'] = []
        with self.assertRaises(ValueError): runner_drones.normalize(value)

    def test_result_checks_sensor_error_but_not_shutdown(self):
        value = {'runnerSchemaVersion': 1, 'scenarioId': 'probe', 'mode': 'coordinated',
            'drones': [], 'computer': {'lastError': None}, 'program': {'status': 'returned'},
            'microcontrollers': [{'index': 0, 'running': True, 'lastError': None}]}
        runner_drones.completed_result(value, 'probe', 0, True, microcontroller_count=1)
        bad = copy.deepcopy(value)
        bad['microcontrollers'][0]['lastError'] = 'boom'
        with self.assertRaises(ValueError): runner_drones.completed_result(bad, 'probe', 0, True, microcontroller_count=1)
        with self.assertRaises(ValueError): runner_drones.completed_result(value, 'probe', 0, True, microcontroller_count=2)

    def test_observation_shape(self):
        value = {'drones': [], 'computer': {}, 'microcontrollers': [{'index': 0,
            'position': [2, 65, 0], 'energy': 5000, 'running': True}]}
        runner_drones.observation(value)
        value['microcontrollers'][0]['energy'] = -1
        with self.assertRaises(ValueError): runner_drones.observation(value)
