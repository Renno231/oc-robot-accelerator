"""Frozen deployment/bounds checks; warehouse behavior is proven in native OC."""
from pathlib import Path
import hashlib
import unittest
import runner_scenario


class WarehouseFixturesTests(unittest.TestCase):
    def test_ui_deployment_uses_unmodified_qmenu_and_pure_view(self):
        root=Path('examples/warehouse/room/program')
        for path in ('usr/lib/logistics/warehouse/view.lua','usr/lib/logistics/warehouse/ui.lua'):
            self.assertEqual((Path('drone-logistics')/path).read_bytes(),(root/path).read_bytes())
        self.assertEqual(Path('fixtures/qmenu.lua').read_bytes(),(root/'lib/qmenu.lua').read_bytes())
        self.assertEqual('5c2bc7dc41f18f70de3c01463d6c90720a19a7dc3260cd0ca7e3be4bbd020f27',hashlib.sha256(Path('fixtures/qmenu.lua').read_bytes()).hexdigest())
        text=Path('drone-logistics/usr/lib/logistics/warehouse/view.lua').read_text(encoding='utf-8')
        for dependency in ('component','gpu','term','qmenu','tty'):
            self.assertNotIn('require("'+dependency+'")',text)
        self.assertEqual(Path('examples/warehouse/ui-tests.lua').read_bytes(),(root/'ui-tests.lua').read_bytes())

    def test_room_is_bounded_and_copies_canonical_api(self):
        root = Path('examples/warehouse/room')
        spec = runner_scenario.load(root / 'scenario.json').normalized
        self.assertEqual(64, len(spec['containers']))
        self.assertEqual(2, len(spec['drones']))
        self.assertEqual('baseline', spec['execution']['mode'])
        self.assertEqual(Path('examples/warehouse/room.lua').read_bytes(), (root / 'program/main.lua').read_bytes())
        for path in ('usr/lib/logistics/map.lua', 'usr/lib/logistics/init.lua', 'usr/lib/logistics/warehouse.lua', 'usr/lib/cbor.lua', 'usr/lib/logistics/store.lua', 'usr/lib/logistics/drone/agent.lua', 'usr/bin/warehouse.lua'):
            self.assertEqual((Path('drone-logistics') / path).read_bytes(), (root / 'program' / path).read_bytes())
        self.assertEqual(Path('drone-logistics/drone/loader.lua').read_bytes(), (root / 'loader.lua').read_bytes())
        for chest in spec['containers']:
            expected = 'minecraft:trapped_chest' if chest['position'][0] % 2 else 'minecraft:chest'
            self.assertEqual(expected, chest['block'])

    def test_logistics_has_no_warehouse_dependency(self):
        text = Path('drone-logistics/usr/lib/logistics/init.lua').read_text()
        self.assertNotIn('warehouse', text)

    def test_slot_scope_scenario_copies_canonical_api(self):
        root=Path('examples/warehouse/slots')
        spec=runner_scenario.load(root/'scenario.json').normalized
        self.assertEqual(3,len(spec['containers']))
        self.assertEqual(Path('examples/warehouse/slots.lua').read_bytes(),(root/'program/main.lua').read_bytes())
        for path in ('usr/lib/logistics/map.lua','usr/lib/logistics/init.lua','usr/lib/logistics/warehouse.lua','usr/lib/cbor.lua','usr/lib/logistics/store.lua','usr/lib/logistics/drone/agent.lua','usr/bin/warehouse.lua'):
            self.assertEqual((Path('drone-logistics')/path).read_bytes(),(root/'program'/path).read_bytes())

    def test_nbt_scenario_uses_real_native_tagged_stacks(self):
        root=Path('examples/warehouse/nbt');spec=runner_scenario.load(root/'scenario.json').normalized
        stacks=spec['containers'][0]['slots']
        self.assertEqual(5,len(stacks));self.assertEqual(5,len({s['nbt'] for s in stacks}))
        self.assertTrue(all(s['count']==16 and s['item']=='minecraft:iron_ingot' for s in stacks))
        for path in ('usr/lib/logistics/map.lua','usr/lib/logistics/init.lua','usr/lib/logistics/warehouse.lua','usr/lib/cbor.lua','usr/lib/logistics/store.lua','usr/lib/logistics/drone/agent.lua','usr/bin/warehouse.lua'):
            self.assertEqual((Path('drone-logistics')/path).read_bytes(),(root/'program'/path).read_bytes())


if __name__ == '__main__':
    unittest.main()
