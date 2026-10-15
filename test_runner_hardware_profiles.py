import unittest
from runner_hardware_profiles import resolve_profile, preflight_standard_builder_recipe
from runner_scenario import _hardware

class Profiles(unittest.TestCase):
    def test_builder_is_survival_and_fills_inventory_without_exceeding_native_budget(self):
        p = _hardware('builder-max')
        self.assertEqual(p['tier'],3)
        self.assertEqual(p['upgrades'].count('inventoryupgrade'),4)
        self.assertEqual(p['memory'],['ram6','ram6'])
        self.assertEqual(preflight_standard_builder_recipe(p),31)
    def test_over_budget_custom_recipe_is_rejected_before_submission(self):
        p=resolve_profile('builder-max')
        p['containers'].append({'item':'upgradecontainer1','component':'batteryupgrade1'})
        with self.assertRaisesRegex(ValueError,'33/32'): _hardware(p)
    def test_profile_is_not_shared_mutable_state(self):
        p=resolve_profile('builder-max');p['upgrades'].clear()
        self.assertEqual(resolve_profile('builder-max')['upgrades'].count('inventoryupgrade'),4)
    def test_unknown_profile_is_not_silently_defaulted(self):
        with self.assertRaises(ValueError): _hardware('anything')

if __name__=='__main__': unittest.main()
