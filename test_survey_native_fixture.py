"""Physical power and bounded diagnostics for the six-carrier survey rooms."""
import json
from pathlib import Path
import tempfile
import unittest
from build_native_survey import build


class SurveyNativeFixtureTests(unittest.TestCase):
    def test_every_home_is_powered_and_diagnostics_are_bounded(self):
        for case in ('survey-wall', 'survey-mixed'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                scenario = build(Path(directory), case)
                value = json.loads(scenario.read_text())
                blocks = {tuple(b['position']): b['block'] for b in value['blocks']}
                for z in range(2, 8):
                    self.assertEqual(blocks[-2, 64, z], 'opencomputers:charger')
                    self.assertEqual(blocks[-2, 63, z], 'minecraft:redstone_block')
                self.assertEqual(sum('geolyzer' in d['hardware']['upgrades'] for d in value['drones']), 1)
                self.assertFalse(value['execution']['infiniteEnergy'])
                self.assertFalse((scenario.parent / 'program/route-metrics-enabled').exists())


if __name__ == '__main__':
    unittest.main()
