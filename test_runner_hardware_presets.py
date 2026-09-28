"""Editable scenario-local hardware presets resolve and freeze as full native recipes."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import runner_scenario as scenario
import runner_jobs as jobs
from test_runner_hardware import configured


class HardwarePresets(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.source=self.root/'source'; self.source.mkdir()
        (self.source/'program').mkdir(); (self.source/'program/main.lua').write_text('return')
        (self.source/'hardware').mkdir()
        self.preset=self.source/'hardware/custom.json'
        self.base=configured()['robot']['hardware']
        self.preset.write_text(json.dumps(self.base))
        self.manifest=self.source/'scenario.json'
        self.value=configured(); self.value['robot']['hardware']={'preset':'hardware/custom.json'}

    def load(self):
        self.manifest.write_text(json.dumps(self.value))
        return scenario.load(self.manifest)

    def test_preset_overrides_and_direct_config_have_one_resolved_contract(self):
        self.value['robot']['hardware']['overrides']={'memory':['ram2'], 'cards':[], 'containers':[]}
        result=self.load().normalized
        direct=configured(); direct['robot']['hardware'].update(memory=['ram2'],cards=[],containers=[])
        self.assertEqual(result,scenario.normalize(direct))
        self.assertEqual(json.loads(self.preset.read_text()),self.base)

    def test_user_edits_apply_to_next_job_but_not_already_loaded_inputs(self):
        first=self.load(); before=self.preset.read_bytes()
        self.base['memory']=['ram1']; self.preset.write_text(json.dumps(self.base))
        second=self.load()
        self.assertNotEqual(first.normalized,second.normalized)
        frozen=self.root/'frozen'; hashes=scenario.freeze(first,frozen)
        self.assertEqual((frozen/'hardware-preset.json').read_bytes(),before)
        self.assertIn('hardware-preset.json',hashes)
        self.assertEqual(json.loads((frozen/'runner-scenario.json').read_text()),first.normalized)
        runtime=self.root/'runtime';(runtime/'config/opencomputers').mkdir(parents=True)
        jobs._install(frozen,runtime,first.normalized['execution'],lambda:None)
        self.assertFalse((runtime/'hardware-preset.json').exists())
        (frozen/'hardware-preset.json').write_text('{}')
        runtime=self.root/'runtime2';(runtime/'config/opencomputers').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError,'hash drift'):
            jobs._install(frozen,runtime,first.normalized['execution'],lambda:None)

    def test_references_cannot_escape_chain_or_smuggle_unknown_fields(self):
        for ref in ['../outside.json','/absolute.json','C:/outside.json','hardware/../custom.json']:
            self.value['robot']['hardware']={'preset':ref}
            with self.subTest(ref=ref), self.assertRaises(ValueError): self.load()
        for obj in [ {'preset':'hardware/custom.json','cpu':'cpu1'},
                     {'preset':'hardware/custom.json','overrides':{'typo':1}},
                     {'preset':'hardware/custom.json','overrides':{'memory':None}},
                     {'preset':'hardware/custom.json','overrides':{'preset':'another.json'}} ]:
            self.value['robot']['hardware']=obj
            with self.subTest(obj=obj),self.assertRaises(ValueError): self.load()
        self.value['robot']['hardware']={'preset':'hardware/custom.json'}
        for raw in ['{"preset":"another.json"}', '{"tier":1,"tier":2}', 'x'*131073]:
            self.preset.write_text(raw)
            with self.subTest(raw=raw[:40]), self.assertRaises(ValueError): self.load()

    def test_legacy_scenarios_do_not_gain_preset_resolution(self):
        self.value['schemaVersion']=2
        with self.assertRaises(ValueError): self.load()

    def test_link_policy_applies_to_preset_reads(self):
        real=scenario._no_link
        def deny(path):
            if Path(path)==self.preset: raise ValueError('link/reparse preset')
            return real(path)
        with patch.object(scenario,'_no_link',side_effect=deny):
            with self.assertRaisesRegex(ValueError,'link/reparse preset'): self.load()


if __name__=='__main__': unittest.main()
