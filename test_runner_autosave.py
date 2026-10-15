import unittest
from test_runner_hardware import configured
from runner_scenario import normalize

class AutosaveTests(unittest.TestCase):
    def test_native_default_stays_implicit(self):
        self.assertNotIn('autosaveWallSeconds',normalize(configured())['execution'])
    def test_explicit_wall_clock_and_native_zero(self):
        for seconds in (0,45,2147483647):
            value=configured();value['execution']={'autosaveWallSeconds':seconds}
            self.assertEqual(normalize(value)['execution']['autosaveWallSeconds'],seconds)
    def test_invalid_intervals(self):
        for seconds in (-1,True,1.5,2147483648):
            value=configured();value['execution']={'autosaveWallSeconds':seconds}
            with self.assertRaises(ValueError):normalize(value)
