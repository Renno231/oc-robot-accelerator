import unittest
from test_runner_hardware import configured
from runner_scenario import normalize

class ViewerTests(unittest.TestCase):
    def test_absent_by_default(self):
        self.assertNotIn('viewer',normalize(configured())['execution'])
    def test_normalized_with_default_hold(self):
        value=configured();value['execution']={'viewer':{'port':25570,'players':['CamWide','CamOrbit']}}
        self.assertEqual(normalize(value)['execution']['viewer'],{'port':25570,'players':['CamWide','CamOrbit'],'holdSeconds':0})
    def test_invalid(self):
        for viewer in ({'port':80,'players':['CamWide']},{'port':25570,'players':[]},
                       {'port':25570,'players':['CamWide','CamWide']},{'port':25570,'players':['bad name']},
                       {'port':25570,'players':['CamWide'],'holdSeconds':601},{'players':['CamWide']},
                       {'port':25570,'players':['CamWide'],'extra':1}):
            value=configured();value['execution']={'viewer':viewer}
            with self.assertRaises(ValueError):normalize(value)
