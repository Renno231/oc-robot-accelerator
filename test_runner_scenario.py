"""Contract tests for caller-owned scenarios and pristine frozen inputs."""
import copy
import json
import os
from unittest import mock
from pathlib import Path
import tempfile
import unittest

import runner_scenario as scenario


def minimal():
    return {'schemaVersion': 1, 'id': 'mining', 'program': {'directory': 'program'},
            'world': {'region': {'min': [-2, 64, -4], 'max': [2, 68, 2]}},
            'robot': {'position': [0, 65, 0]}}


class ScenarioContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'program').mkdir()
        (self.source / 'program/main.lua').write_text('return 42', encoding='utf-8')
        self.manifest = self.source / 'scenario.json'

    def load(self, value=None, **kw):
        self.manifest.write_text(json.dumps(minimal() if value is None else value), encoding='utf-8')
        return scenario.load(self.manifest, **kw)

    def test_defaults_and_normalized_fixture(self):
        spec = self.load()
        self.assertEqual(spec.normalized['execution'], {'mode': 'coordinated', 'maxTicks': 10000,
            'timeoutSeconds': 120, 'executionDelayMillis': 12, 'stallTicks': 0})
        self.assertEqual(spec.normalized['program'], {'directory': 'program', 'entry': 'main.lua'})
        self.assertEqual(spec.normalized['robot']['tool']['item'], 'minecraft:diamond_pickaxe')
        self.assertEqual(spec.normalized['robot']['energy'], 20000)  # Fits the real preset's 20500 buffer.
        self.assertEqual(json.loads(Path('fixtures/runner-normalized.json').read_text()), spec.normalized)

    def test_input_enumeration_errors_fail_closed_in_both_scan_passes(self):
        assets=self.source/'program/assets'; assets.mkdir(); (assets/'needed.txt').write_text('required')
        original=os.scandir
        for deny_pass in (1,2):
            visits=[]
            def denied(path):
                if Path(path)==assets:
                    visits.append(1)
                    if len(visits)==deny_pass: raise PermissionError('input unreadable')
                return original(path)
            with self.subTest(deny_pass=deny_pass), mock.patch.object(os,'scandir',side_effect=denied):
                with self.assertRaisesRegex(ValueError,'input unreadable'):
                    spec=self.load(); scenario.freeze(spec,self.root/('frozen'+str(deny_pass)))

    def test_inventory_rejects_live_permission_errors_but_tolerates_live_disappearance(self):
        import supervisor
        assets=self.source/'program/assets'; assets.mkdir()
        original=os.scandir
        for live in (False,True):
            def denied(path):
                if Path(path)==assets: raise PermissionError('inventory unreadable')
                return original(path)
            with self.subTest(live=live), mock.patch.object(os,'scandir',side_effect=denied):
                with self.assertRaises(PermissionError):
                    supervisor._inventory(self.source,1024,100,live=live)
        def vanished(path):
            if Path(path)==assets: raise FileNotFoundError('renamed during live scan')
            return original(path)
        with mock.patch.object(os,'scandir',side_effect=vanished):
            supervisor._inventory(self.source,1024,100,live=True)
            with self.assertRaises(FileNotFoundError): supervisor._inventory(self.source,1024,100)

    def test_validation_does_not_write_outputs(self):
        before = sorted(p.relative_to(self.source).as_posix() for p in self.source.rglob('*'))
        self.load()
        after = sorted(p.relative_to(self.source).as_posix() for p in self.source.rglob('*'))
        self.assertEqual(sorted(before + ['scenario.json']), after)

    def test_strict_shapes_numbers_and_caps(self):
        cases = [('schemaVersion', True), ('schemaVersion', 3), ('id', 'Bad'), ('extra', 1)]
        for key, value in cases:
            data = minimal(); data[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError): self.load(data)
        changes = [({'maxTicks': True}, 'execution'), ({'maxTicks': 1.5}, 'execution'),
                   ({'timeoutSeconds': 601}, 'execution'), ({'executionDelayMillis': 1}, 'execution'),
                   ({'extra': 1}, 'observations'), ({'everyTicks': 0}, 'observations')]
        for patch, key in changes:
            data = minimal(); data[key] = patch
            with self.subTest(patch=patch), self.assertRaises(ValueError): self.load(data)
        for energy in [float('nan'), float('inf'), 0, True, 50001]:
            data = minimal(); data['robot']['energy'] = energy
            with self.subTest(energy=energy), self.assertRaises(ValueError): self.load(data)

    def test_region_volumes_and_expectations_are_bounded(self):
        for region in [{'min': [0, 64, 0], 'max': [100, 100, 100]},
                       {'min': [0, 0, 0], 'max': [0, 64, 0]},
                       {'min': [2, 65, 2], 'max': [0, 64, 0]}]:
            data = minimal(); data['world']['region'] = region
            with self.subTest(region=region), self.assertRaises(ValueError): self.load(data)
        for key in ['blocks', 'expect']:
            data = minimal()
            if key == 'blocks':
                data['world']['blocks'] = [{'min': [0, 65, 0], 'max': [3, 65, 0], 'block': 'minecraft:stone'}]
            else:
                data['expect'] = {'blocks': [{'position': [100, 65, 0], 'block': 'minecraft:air'}]}
            with self.subTest(key=key), self.assertRaises(ValueError): self.load(data)
        data = minimal(); data['expect'] = {'inventory': [{'item': 'minecraft:stone', 'minCount': 0}] * 65}
        with self.assertRaises(ValueError): self.load(data)

    def test_inventory_and_nbt_bounds(self):
        slot = {'slot': 1, 'item': 'minecraft:stone', 'count': 16}
        data = minimal(); data['robot']['inventory'] = [slot, slot]
        with self.assertRaises(ValueError): self.load(data)
        for nbt in ['{' * 17 + '}' * 17, '{a:"' + 'x' * 4096 + '"}', '{a:1']:
            data = minimal(); data['robot']['tool'] = {'item': 'minecraft:diamond_pickaxe', 'nbt': nbt}
            with self.subTest(nbt=nbt[:30]), self.assertRaises(ValueError): self.load(data)
        data = minimal(); data['robot']['tool'] = {'item': 'minecraft:diamond_pickaxe', 'nbt': '{x:"[[["}'}
        self.load(data)

    def test_paths_and_links_fail_closed(self):
        for directory in ['../escape', '/tmp', 'C:/disk', 'program/../program', '.', 'program\\bad', 'CON', 'program/']:
            data = minimal(); data['program']['directory'] = directory
            with self.subTest(directory=directory), self.assertRaises(ValueError): self.load(data)
        data = minimal(); data['program']['entry'] = '../main.lua'
        with self.assertRaises(ValueError): self.load(data)
        link = self.source / 'linked'
        try: link.symlink_to(self.source / 'program', target_is_directory=True)
        except OSError: return  # Platform symlink privilege is reported separately.
        data = minimal(); data['program']['directory'] = 'linked'
        with self.assertRaises(ValueError): self.load(data)

    def test_duplicate_json_keys_and_manifest_limit(self):
        for content in ['{"schemaVersion":1,"schemaVersion":1}', ' ' * (scenario.MANIFEST_BYTES + 1)]:
            self.manifest.write_text(content)
            with self.subTest(size=len(content)), self.assertRaises(ValueError): scenario.load(self.manifest)

    def test_missing_program_wrong_entry_and_program_size(self):
        data = minimal(); data['program']['entry'] = 'absent.lua'
        with self.assertRaises(ValueError): self.load(data)
        (self.source / 'program/main.lua').write_bytes(b'x' * (scenario.PROGRAM_FILE_BYTES + 1))
        with self.assertRaises(ValueError): self.load()

    def test_root_overlap_and_source_world_requirements(self):
        for output in [self.source, self.source / 'jobs', self.root]:
            with self.subTest(output=output), self.assertRaises(ValueError): self.load(forbidden_roots=[output])
        data = minimal(); data['world']['source'] = 'program'
        with self.assertRaises(ValueError): self.load(data)
        (self.source / 'world').mkdir()
        data['world']['source'] = 'world'
        with self.assertRaises(ValueError): self.load(data)
        (self.source / 'world/level.dat').write_bytes(b'fixture')
        self.assertEqual(self.load(data).normalized['world']['source'], 'world')

    def test_freeze_preserves_original_and_separate_program_copy(self):
        spec = self.load()
        destination = self.root / 'inputs'
        hashes = scenario.freeze(spec, destination)
        self.assertEqual((destination / 'program/main.lua').read_text(), 'return 42')
        (self.source / 'program/main.lua').write_text('return 99')
        self.assertEqual((destination / 'program/main.lua').read_text(), 'return 42')
        self.assertIn('program/main.lua', hashes)
        self.assertIn('scenario.json', hashes)
        self.assertIn('runner-scenario.json', hashes)
        self.assertEqual(json.loads((destination / 'runner-scenario.json').read_text()), spec.normalized)
        with self.assertRaises(FileExistsError): scenario.freeze(spec, destination)

    def test_empty_program_directories_survive_freeze(self):
        (self.source / 'program/output/nested').mkdir(parents=True)
        spec = self.load()
        scenario.freeze(spec, self.root / 'inputs')
        self.assertTrue((self.root / 'inputs/program/output/nested').is_dir())

    def test_huge_energy_rejected_as_validation_error(self):
        data = minimal(); data['robot']['energy'] = 10 ** 1000
        with self.assertRaises(ValueError): self.load(data)

    def test_freeze_checks_cancellation(self):
        spec = self.load()
        def cancelled(): raise InterruptedError('cancelled')
        with self.assertRaises(InterruptedError): scenario.freeze(spec, self.root / 'inputs', check=cancelled)

    def test_rejects_program_change_between_validation_and_freeze(self):
        spec = self.load()
        (self.source / 'program/main.lua').write_text('return 420000')
        with self.assertRaises(ValueError): scenario.freeze(spec, self.root / 'inputs')


if __name__ == '__main__': unittest.main()
