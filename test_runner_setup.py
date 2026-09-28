"""Public installation state and process boundaries; no network or game processes."""
import hashlib
import json
import os
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import runner_setup as setup
import runtime_profile as profile


def pin(data):
    return {'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.tool=self.root/'tool'; self.tool.mkdir()
        (self.tool/'build/libs').mkdir(parents=True)
        (self.tool/'build/libs/robot-spike.jar').write_bytes(b'control')
        self.home=self.root/'install'; self.java=self.root/'java'; self.java.write_bytes(b'java')
        self.jars={'minecraft_server.1.12.2.jar':pin(b'minecraft'),
                   'forge-1.12.2-14.23.5.2860.jar':pin(b'forge'),'mods/OpenComputers.jar':pin(b'oc')}
        self.patches=[patch.object(setup,'HERE',self.tool),
                      patch.object(setup,'java_check',return_value={'path':str(self.java),'version':'1.8.0-test'}),
                      patch.object(profile,'TEMPLATE_JARS',self.jars),
                      patch.object(profile,'OVERLAYS',tuple(dict(a,**pin(a['name'].encode())) for a in profile.OVERLAYS)),
                      patch.object(setup,'_acquire',side_effect=self.acquire),
                      patch.object(setup,'_install_forge',side_effect=self.forge)]
        for p in self.patches: p.start(); self.addCleanup(p.stop)
        self.calls=[]

    def acquire(self,path,artifact,owner):
        owner.check(); path.parent.mkdir(parents=True,exist_ok=True)
        data=b'oc' if artifact['name'].startswith('OpenComputers') else b'installer'
        if artifact in profile.OVERLAYS: data=artifact['name'].encode()
        path.write_bytes(data)
        self.calls.append(path.name)

    def forge(self,java,installer,server,owner):
        owner.check(); server.mkdir(parents=True,exist_ok=True)
        (server/'minecraft_server.1.12.2.jar').write_bytes(b'minecraft')
        (server/'forge-1.12.2-14.23.5.2860.jar').write_bytes(b'forge')

    def install(self):
        return setup.install(self.home,self.java,timeout=30,accept_eula=True)

    def test_absent_doctor_does_not_create_or_acquire(self):
        value=setup.doctor(self.home)
        self.assertEqual('absent',value['status']); self.assertFalse(self.home.exists()); self.assertEqual([],self.calls)

    def test_ready_paths_inventory_and_idempotent_setup(self):
        value=self.install(); self.assertEqual('ready',value['status'])
        self.assertFalse((self.home/'.stage').exists())
        metadata=json.loads((self.home/'installation.json').read_text())
        self.assertEqual(profile.PROFILE_ID,metadata['profileId']); self.assertEqual('source-build',metadata['origin'])
        before={str(p.relative_to(self.home)):p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        self.assertEqual('ready',setup.doctor(self.home)['status'])
        self.assertEqual('ready',self.install()['status'])
        after={str(p.relative_to(self.home)):p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        self.assertEqual(before,after)
        resolved=setup.resolve(self.home)
        self.assertEqual(self.home/'payload/server',resolved['template'])
        self.assertEqual(self.home/'payload/runtime-libraries',resolved['runtime_libraries'])
        self.assertEqual(self.home/'payload/control.jar',resolved['control_jar'])

    def test_changed_or_extra_payload_rejected_without_repair(self):
        self.install(); (self.home/'payload/control.jar').write_bytes(b'tampered')
        self.assertEqual('incompatible',setup.doctor(self.home)['status'])
        with self.assertRaises(ValueError): self.install()
        self.assertEqual(b'tampered',(self.home/'payload/control.jar').read_bytes())
        with self.assertRaises(ValueError): setup.resolve(self.home)

    def test_existing_empty_or_failed_target_preserved(self):
        self.home.mkdir(); (self.home/'user.txt').write_text('keep')
        with self.assertRaises(ValueError): self.install()
        self.assertEqual('incomplete',setup.doctor(self.home)['status'])
        self.assertEqual('keep',(self.home/'user.txt').read_text())

    def test_failed_installer_never_ready_and_retains_diagnostic(self):
        with patch.object(setup,'_install_forge',side_effect=RuntimeError('installer failed')):
            with self.assertRaises(RuntimeError): self.install()
        self.assertEqual('incomplete',setup.doctor(self.home)['status'])
        record=json.loads((self.home/'installation.json').read_text())
        self.assertEqual('failed',record['state']); self.assertIn('installer failed',record['error'])
        self.assertFalse((self.home/'payload').exists())

    def test_interrupted_setup_is_incomplete(self):
        with patch.object(setup,'_install_forge',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): self.install()
        self.assertEqual('incomplete',setup.doctor(self.home)['status'])
        self.assertEqual('failed',json.loads((self.home/'installation.json').read_text())['state'])

    def test_package_control_identity_checked_before_install(self):
        (self.tool/'lib').mkdir(); (self.tool/'lib/robot-control.jar').write_bytes(b'package')
        metadata={'schemaVersion':1,'profileId':profile.PROFILE_ID,
                  'controlJar':dict(path='lib/robot-control.jar',**pin(b'package'))}
        (self.tool/'release.json').write_text(json.dumps(metadata))
        self.install(); self.assertEqual(b'package',(self.home/'payload/control.jar').read_bytes())
        self.assertEqual('package',json.loads((self.home/'installation.json').read_text())['origin'])
        (self.tool/'lib/robot-control.jar').write_bytes(b'bad')
        with self.assertRaises(ValueError): setup.install(self.root/'other',self.java,timeout=30,accept_eula=True)
        self.assertFalse((self.root/'other').exists())

    def test_changed_selected_control_during_setup_cannot_publish_ready(self):
        def mutate(java,installer,server,owner):
            self.forge(java,installer,server,owner)
            (self.tool/'build/libs/robot-spike.jar').write_bytes(b'changed-after-preflight')
        with patch.object(setup,'_install_forge',side_effect=mutate):
            with self.assertRaises(ValueError): self.install()
        self.assertEqual('incomplete',setup.doctor(self.home)['status'])

    def test_public_acceptance_is_explicit_and_doctor_checks_record(self):
        with self.assertRaises(ValueError): setup.install(self.home,self.java,timeout=30)
        self.assertFalse(self.home.exists()); self.install()
        record=json.loads((self.home/'installation.json').read_text()); record['eulaAccepted']=False
        (self.home/'installation.json').write_text(json.dumps(record))
        self.assertEqual('incompatible',setup.doctor(self.home)['status'])

    def test_no_fallback_from_malformed_package_to_developer_build(self):
        (self.tool/'release.json').write_text('{"schemaVersion":1}')
        with self.assertRaises(ValueError): self.install()
        self.assertFalse(self.home.exists())

    def test_invalid_timeout_or_java_creates_nothing(self):
        for timeout in (True,0,29,1801,float('inf')):
            with self.assertRaises(ValueError): setup.install(self.home,self.java,timeout=timeout)
        with patch.object(setup,'java_check',side_effect=ValueError('Java 8 required')):
            with self.assertRaises(ValueError): self.install()
        self.assertFalse(self.home.exists())

    def test_missing_changed_java_is_incompatible_not_repaired(self):
        self.install()
        with patch.object(setup,'java_check',side_effect=ValueError('Java 8 required')):
            self.assertEqual('incompatible',setup.doctor(self.home)['status'])

    def test_linked_ancestor_is_rejected_before_any_mutation(self):
        outside=self.root/'outside'; outside.mkdir(); link=self.root/'link'
        if os.name=='nt':
            subprocess.run(['cmd','/c','mklink','/J',str(link),str(outside)],check=True,capture_output=True,creationflags=setup.supervisor.NO_WINDOW)
        else: link.symlink_to(outside,target_is_directory=True)
        try:
            with self.assertRaises(ValueError): setup.install(link/'nested/install',self.java,30,accept_eula=True)
            self.assertEqual([],list(outside.iterdir())); self.assertEqual([],self.calls)
        finally:
            if os.name=='nt': link.rmdir()
            else: link.unlink()

    def test_extra_payload_file_and_verification_deadline_are_rejected(self):
        self.install(); (self.home/'payload/extra').write_text('extra')
        self.assertEqual('incompatible',setup.doctor(self.home)['status'])
        (self.home/'payload/extra').unlink()
        with patch.object(setup.time,'monotonic',side_effect=[0,31]):
            self.assertEqual('incompatible',setup.doctor(self.home)['status'])

    def test_metadata_oversize_and_nonfinite_are_incompatible(self):
        self.home.mkdir(); (self.home/'installation.json').write_bytes(b' '* (128*1024+1))
        self.assertEqual('incompatible',setup.doctor(self.home)['status'])
        (self.home/'installation.json').write_text('{"created":1e999}')
        self.assertEqual('incompatible',setup.doctor(self.home)['status'])


if __name__=='__main__': unittest.main()
