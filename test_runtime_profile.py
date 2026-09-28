"""Versioned runtime profile integrity, without network or game execution."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import runtime_profile as profile


class RuntimeProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'runtime'; self.root.mkdir()
        self.cache = Path(self.temp.name)/'cache'; self.cache.mkdir()
        self.target = 'libraries/logging.jar'
        (self.root/'libraries').mkdir(); (self.root/self.target).write_bytes(b'original')
        (self.root/'mods').mkdir(); (self.root/'mods/robot-spike.jar').write_bytes(b'first party')
        (self.cache/'logging.jar').write_bytes(b'updated')
        self.base = {self.target: {'size':8,'sha256':hashlib.sha256(b'original').hexdigest()}}
        self.overlay = [{'name':'logging.jar','target':self.target,'size':7,
                         'sha256':hashlib.sha256(b'updated').hexdigest(),'url':'https://example.invalid/library'}]
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(profile,'TEMPLATE_JARS',self.base).start()
        mock.patch.object(profile,'OVERLAYS',self.overlay).start()

    def test_apply_records_original_and_effective_identity(self):
        hashes = profile.apply(self.root,self.cache)
        self.assertEqual((self.root/self.target).read_bytes(),b'updated')
        self.assertEqual((self.cache/'logging.jar').read_bytes(),b'updated')
        self.assertEqual(hashes['runtime-profile/'+self.target], self.overlay[0]['sha256'])

    def test_rejects_modified_template_missing_extra_and_tampered_overlay(self):
        for alteration in ('modified','missing','extra','overlay'):
            with self.subTest(alteration=alteration):
                target=self.root/self.target; target.write_bytes(b'original')
                (self.root/'extra.jar').unlink(missing_ok=True)
                (self.cache/'logging.jar').write_bytes(b'updated')
                if alteration=='modified': target.write_bytes(b'changed!')
                if alteration=='missing': target.unlink()
                if alteration=='extra': (self.root/'extra.jar').write_bytes(b'extra')
                if alteration=='overlay': (self.cache/'logging.jar').write_bytes(b'changed')
                with self.assertRaises((ValueError,OSError)): profile.apply(self.root,self.cache)
                if alteration != 'missing':
                    self.assertNotEqual(target.read_bytes(),b'updated')

    def test_program_data_jar_is_not_a_runtime_classpath_extension(self):
        (self.root/'program').mkdir()
        (self.root/'program/data.jar').write_bytes(b'user data not on Forge classpath')
        profile.apply(self.root,self.cache)
        self.assertEqual((self.root/self.target).read_bytes(),b'updated')

    def test_cancellation_checked_before_mutation(self):
        def cancel(): raise TimeoutError('budget')
        with self.assertRaises(TimeoutError): profile.apply(self.root,self.cache,cancel)
        self.assertEqual((self.root/self.target).read_bytes(),b'original')

    def test_proof_requires_loaded_sources_versions_hashes_and_core_provider(self):
        classes = {}
        for name in profile.REQUIRED_CLASSES:
            core=name.startswith('org.apache.logging.log4j.core.')
            artifact=profile.CORE if core else profile.API
            classes[name]={'source':artifact['target'],'version':'2.25.5','sha256':artifact['sha256']}
        factory='org.apache.logging.log4j.core.impl.Log4jContextFactory'
        classes[factory]={'source':profile.CORE['target'],'version':'2.25.5','sha256':profile.CORE['sha256']}
        proof={'schemaVersion':1,'profileId':profile.PROFILE_ID,'classes':classes,
               'contextClass':'org.apache.logging.log4j.core.LoggerContext','factoryClass':factory}
        path=self.root/'runtime-logging.json'
        path.write_text(json.dumps(proof)); self.assertEqual(profile.verify_proof(self.root),proof)
        for field,bad in [('source','minecraft_server.1.12.2.jar'),('version','2.15.0'),('sha256','0'*64)]:
            record=classes['org.apache.logging.log4j.LogManager']; original=record[field]; record[field]=bad
            path.write_text(json.dumps(proof))
            with self.assertRaises(ValueError): profile.verify_proof(self.root)
            record[field]=original
        proof['factoryClass']='org.apache.logging.log4j.simple.SimpleLoggerContextFactory'
        path.write_text(json.dumps(proof))
        with self.assertRaises(ValueError): profile.verify_proof(self.root)
        path.write_bytes(b' '*65537)
        with self.assertRaises(ValueError): profile.verify_proof(self.root)


if __name__ == '__main__': unittest.main()
