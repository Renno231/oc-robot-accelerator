"""Check frozen mapping inputs; behavior is tested on native OC, without mocks."""
from pathlib import Path
import tempfile
import unittest
import runner_scenario


class MappingFixturesTests(unittest.TestCase):
    def test_independent_programs_and_canonical_copies(self):
        source=Path('drone-logistics')
        for case in ('service','actions'):
            root=Path('examples/mapping')/case
            with self.subTest(case=case):
                spec=runner_scenario.load(root/'scenario.json')
                self.assertEqual('second-program',spec.normalized['secondComputer']['program']['directory'])
                self.assertEqual('baseline',spec.normalized['execution']['mode'])
                for program in ('program','client'):
                    for path in ('lib/map.lua','lib/mapclient.lua','bin/mapd.lua','bin/mapclient.lua'):
                        self.assertEqual((source/path).read_bytes(),(root/program/path).read_bytes())
                with tempfile.TemporaryDirectory() as t:
                    destination=Path(t)/'inputs';hashes=runner_scenario.freeze(spec,destination)
                    self.assertIn('second-program/main.lua',hashes)
                    self.assertEqual((root/'client/main.lua').read_bytes(),(destination/'second-program/main.lua').read_bytes())
                if case=='service':
                    self.assertEqual([],spec.normalized['drones'])
                    self.assertFalse((root/'program/lib/logistics.lua').exists())
                else:
                    self.assertEqual((source/'drone/loader.lua').read_bytes(),(root/'loader.lua').read_bytes())
                    self.assertLessEqual((root/'loader.lua').stat().st_size,4096)
                    for path in ('lib/logistics.lua','drone/agent.lua'):
                        self.assertEqual((source/path).read_bytes(),(root/'program'/path).read_bytes())


if __name__=='__main__':
    unittest.main()
