"""Public scenario v2: explicit compatibility, finite long jobs and recording policy."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import runner_scenario as scenario
from test_runner_scenario import minimal


def public():
    value = minimal()
    value['schemaVersion'] = 2
    return value


class PublicScenarioContract(unittest.TestCase):
    def test_v1_normalized_contract_is_unchanged(self):
        normalized = scenario.normalize(minimal())
        self.assertEqual(normalized, json.loads(Path('fixtures/runner-normalized.json').read_text()))
        # Frozen local-v1 fixture in evidence/runner/source.zip, canonical wire encoding.
        self.assertEqual(hashlib.sha256(scenario.normalized_bytes(normalized)).hexdigest(),
                         'e14139708e7c1400ada2ce05b2624c5d2e543db10aeaecb92addd9159d0191d1')
        for key, value in [('maxBytes', 1048576), ('onFull', 'stop')]:
            old = minimal(); old['observations'] = {key: value}
            with self.subTest(key=key), self.assertRaises(ValueError): scenario.normalize(old)
        for key, value in [('maxTicks', 10001), ('timeoutSeconds', 601), ('stallTicks', 10001)]:
            old = minimal(); old['execution'] = {key: value}
            with self.subTest(key=key), self.assertRaises(ValueError): scenario.normalize(old)

    def test_v2_safe_defaults_and_exact_normalized_fixture(self):
        value = scenario.normalize(public())
        self.assertEqual(value['schemaVersion'], 2)
        self.assertEqual(value['execution'], {'mode': 'baseline', 'maxTicks': 10000,
            'timeoutSeconds': 600, 'executionDelayMillis': 12, 'stallTicks': 0})
        self.assertEqual(value['observations'], {'everyTicks': 20, 'maxBytes': 33554432, 'onFull': 'stop'})
        self.assertEqual(value, json.loads(Path('fixtures/runner-public-normalized.json').read_text()))

    def test_long_budget_inclusive_limits_and_explicit_modes(self):
        for mode in ['baseline', 'coordinated']:
            for delay in [0, 12]:
                value = public()
                value['execution'] = {'mode': mode, 'maxTicks': 1728000, 'timeoutSeconds': 90000,
                                      'executionDelayMillis': delay, 'stallTicks': 1728000}
                self.assertEqual(scenario.normalize(value)['execution'], value['execution'])
        value = public(); value['execution'] = {'maxTicks': 1, 'timeoutSeconds': 1, 'stallTicks': 0}
        self.assertEqual(scenario.normalize(value)['execution']['maxTicks'], 1)

    def test_v2_rejects_unbounded_ambiguous_and_out_of_range_inputs(self):
        cases = [('maxTicks', 1728001), ('maxTicks', 0), ('maxTicks', True), ('maxTicks', 1.0),
                 ('timeoutSeconds', 90001), ('timeoutSeconds', 0), ('timeoutSeconds', float('inf')),
                 ('stallTicks', 1728001), ('stallTicks', -1), ('mode', 'unpaced'),
                 ('executionDelayMillis', 1), ('maxTicks', 2**63), ('unknown', 1)]
        for key, raw in cases:
            value = public(); value['execution'] = {key: raw}
            with self.subTest(key=key, raw=raw), self.assertRaises(ValueError): scenario.normalize(value)
        for version in [0, 3, True, 2.0]:
            value = public(); value['schemaVersion'] = version
            with self.subTest(version=version), self.assertRaises(ValueError): scenario.normalize(value)

    def test_recording_policies_are_bounded_and_explicit(self):
        for cap in [1048576, 33554432]:
            for policy in ['stop', 'fail']:
                value = public(); value['observations'] = {'everyTicks': 200, 'maxBytes': cap, 'onFull': policy}
                self.assertEqual(scenario.normalize(value)['observations'], value['observations'])
        for patch in [{'maxBytes': 1048575}, {'maxBytes': 33554433}, {'maxBytes': True},
                      {'maxBytes': 1048576.0}, {'onFull': 'rotate'}, {'onFull': None},
                      {'everyTicks': 201}, {'unknown': 'stop'}]:
            value = public(); value['observations'] = patch
            with self.subTest(patch=patch), self.assertRaises(ValueError): scenario.normalize(value)

    def test_normalized_v2_survives_load_freeze_with_long_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root/'source'; (source/'program').mkdir(parents=True)
            (source/'program/main.lua').write_text('return 42', encoding='utf-8')
            value = public(); value['execution'] = {'maxTicks': 1728000, 'timeoutSeconds': 90000}
            manifest = source/'scenario.json'; manifest.write_text(json.dumps(value), encoding='utf-8')
            loaded = scenario.load(manifest)
            hashes = scenario.freeze(loaded, root/'inputs')
            frozen = scenario.read_json(root/'inputs/runner-scenario.json')
            self.assertEqual(frozen, loaded.normalized)
            self.assertEqual(frozen['execution']['timeoutSeconds'], 90000)
            self.assertIn('runner-scenario.json', hashes)


if __name__ == '__main__': unittest.main()
