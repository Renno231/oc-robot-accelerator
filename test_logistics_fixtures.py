"""Freeze/deployment checks; Lua behavior is established by native L1-L7, not mocks."""
from pathlib import Path
import unittest
import runner_scenario

CASES = ('pair', 'transfer', 'split', 'shortfall', 'full', 'power', 'security', 'held', 'stack-capacity', 'names', 'steps', 'wait', 'blocked', 'blocked-held', 'furnace', 'fixes', 'storage-room', 'obstacle-room')


class LogisticsFixturesTests(unittest.TestCase):
    def test_storage_room_native_geometry(self):
        spec=runner_scenario.load(Path('examples/logistics/storage-room/scenario.json')).normalized
        self.assertEqual(64,len(spec['containers']))
        self.assertEqual(2,len(spec['drones']))
        for chest in spec['containers']:
            x,y,z=chest['position']
            self.assertIn(x,range(8));self.assertIn(y,range(65,69));self.assertIn(z,(1,3))
            self.assertEqual('south' if z==1 else 'north',chest['properties']['facing'])
    def test_loader_envelope_and_canonical_program_copies(self):
        source = Path('drone-logistics')
        loader = (source / 'drone/loader.lua').read_bytes()
        self.assertLessEqual(len(loader), 4096)
        for name in CASES:
            with self.subTest(name=name):
                root = Path('examples/logistics') / name
                self.assertEqual(loader, (root / 'loader.lua').read_bytes())
                for path in ('lib/map.lua', 'lib/logistics.lua', 'lib/cbor.lua', 'lib/store.lua', 'bin/logistics.lua'):
                    self.assertEqual((source / path).read_bytes(), (root / 'program' / path).read_bytes())
                agent = (root / 'program/drone/agent.lua').read_bytes()
                if name == 'security':
                    agent = agent.split(b'\n', 2)[2]  # Two explicit native adversary fixture lines.
                elif name == 'fixes':
                    prefix=Path('examples/logistics/fixes-hook.lua').read_bytes()+b'\n'
                    self.assertTrue(agent.startswith(prefix));agent=agent[len(prefix):]
                self.assertEqual((source / 'drone/agent.lua').read_bytes(), agent)
                self.assertEqual(Path('examples/logistics/testsuite.lua').read_bytes(), (root / 'program/testsuite.lua').read_bytes())

    def test_native_scenarios_load_with_empty_pairing_data(self):
        for name in CASES:
            with self.subTest(name=name):
                spec = runner_scenario.load(Path('examples/logistics') / name / 'scenario.json')
                self.assertEqual('baseline', spec.normalized['execution']['mode'])
                for drone in spec.normalized['drones']:
                    self.assertEqual('', drone['eepromData'])
                    self.assertEqual(['ram1'], drone['hardware']['memory'])
                    self.assertEqual(['wlancard2'], drone['hardware']['cards'])


if __name__ == '__main__':
    unittest.main()
