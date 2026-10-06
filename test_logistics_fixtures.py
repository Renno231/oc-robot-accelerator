"""Freeze/deployment checks; Lua behavior is established by native L1-L7, not mocks."""
from pathlib import Path
import unittest
import runner_scenario

CASES = ('pair', 'transfer', 'split', 'shortfall', 'full', 'power', 'security', 'held', 'stack-capacity', 'names', 'steps', 'wait', 'blocked', 'blocked-held', 'furnace', 'fixes')


class LogisticsFixturesTests(unittest.TestCase):
    def test_loader_envelope_and_canonical_program_copies(self):
        source = Path('drone-logistics')
        loader = (source / 'drone/loader.lua').read_bytes()
        self.assertLessEqual(len(loader), 4096)
        for name in CASES:
            with self.subTest(name=name):
                root = Path('examples/logistics') / name
                self.assertEqual(loader, (root / 'loader.lua').read_bytes())
                for path in ('lib/map.lua', 'lib/logistics.lua', 'bin/logistics.lua'):
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
