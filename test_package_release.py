"""The public ZIP is a bounded, deterministic first-party distribution, not a runtime dump."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import package_release as package
from supervisor import NO_WINDOW


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='runner-package-')
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name); self.root=self.base/'source'; self.root.mkdir()
        for name in package.FILES:
            path=self.root/name; path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes((name+'\n').encode())
        (self.root/'runtime-profile.json').write_text(json.dumps({'profileId':package.PROFILE_ID}))
        self.jar=self.root/'build/control.jar'; self.jar.parent.mkdir()
        self.make_jar()
        self.out=self.base/'runner.zip'

    def make_jar(self,extra=()):
        with zipfile.ZipFile(self.jar,'w') as z:
            z.writestr('META-INF/MANIFEST.MF',package.REQUIRED_MANIFEST)
            for name in ('RobotSpike','PacingPlugin'):
                z.writestr('ocelot/spike/'+name+'.class',b'\xca\xfe\xba\xbe'+bytes(20))
            z.writestr('robot.lua',b'return true\n')
            for name,data in extra: z.writestr(name,data)

    def build(self,out=None):
        return package.build(self.root,self.jar,out or self.out,'0.1.0-rc.1')

    def test_deterministic_allowlist_identity_and_exclusions(self):
        (self.root/'private-world.jar').write_bytes(b'never include')
        private_names=('robot-programs/example-private/main.lua', 'private/user-program.lua',
                       '.taskreports/raw-source.zip', 'evidence/program.lua')
        for name in private_names:
            path=self.root/name; path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(b'PRIVATE_INPUT_MUST_NOT_SHIP')
        first=self.build(); other=self.base/'second.zip'; self.build(other)
        self.assertEqual(self.out.read_bytes(),other.read_bytes())
        self.assertEqual(first['sha256'],hashlib.sha256(self.out.read_bytes()).hexdigest())
        self.assertEqual(self.out.with_suffix('.zip.sha256').read_text(),first['sha256']+'  runner.zip\n')
        with zipfile.ZipFile(self.out) as z:
            self.assertEqual(z.namelist(),sorted(z.namelist()))
            self.assertEqual(set(z.namelist()),set(package.FILES)|{'lib/robot-control.jar','release.json'})
            self.assertTrue(set(private_names).isdisjoint(z.namelist()))
            self.assertTrue(all(b'PRIVATE_INPUT_MUST_NOT_SHIP' not in z.read(name) for name in z.namelist()))
            manifest=json.loads(z.read('release.json'))
            self.assertEqual(manifest['profileId'],package.PROFILE_ID)
            self.assertEqual(manifest['version'],'0.1.0-rc.1')
            self.assertEqual(manifest['controlJar']['sha256'],hashlib.sha256(self.jar.read_bytes()).hexdigest())
            self.assertEqual(set(manifest['files']),set(z.namelist())-{'release.json'})
            for name,record in manifest['files'].items():
                self.assertEqual(record,{'size':len(z.read(name)),'sha256':hashlib.sha256(z.read(name)).hexdigest()})
                self.assertEqual(z.getinfo(name).date_time,(1980,1,1,0,0,0))
            self.assertEqual((z.getinfo('robot-runner').external_attr>>16)&0o777,0o755)

    def test_existing_archive_or_checksum_never_overwritten(self):
        for path in (self.out,self.out.with_suffix('.zip.sha256')):
            path.write_bytes(b'original')
            with self.assertRaises(FileExistsError): self.build()
            self.assertEqual(path.read_bytes(),b'original'); path.unlink()
            self.assertFalse(self.out.exists())

    def test_missing_input_and_wrong_profile_leave_no_outputs(self):
        (self.root/'runtime-profile.json').write_text('{"profileId":"wrong"}')
        with self.assertRaises(ValueError): self.build()
        (self.root/'runner.py').unlink()
        with self.assertRaises((ValueError,FileNotFoundError)): self.build()
        self.assertFalse(self.out.exists()); self.assertFalse(self.out.with_suffix('.zip.sha256').exists())

    def test_third_party_traversal_duplicate_and_missing_control_entries_refused(self):
        for name in ('net/minecraft/Foo.class','META-INF/services/foo','ocelot/spike/../bad.class',
                     'ocelot/spike/Evil.txt','robot.lua'):
            with self.subTest(name=name):
                self.make_jar([(name,b'x')])
                with self.assertRaises(ValueError): self.build()
        with zipfile.ZipFile(self.jar,'w') as z: z.writestr('robot.lua',b'x')
        with self.assertRaises(ValueError): self.build()
        self.assertFalse(self.out.exists())

    def test_directory_entries_cannot_hide_links_or_payload(self):
        import stat
        for mode,data in ((stat.S_IFLNK|0o777,b'outside-target'),
                          (stat.S_IFDIR|0o755,b'x'*(package.FILE_LIMIT+1)),
                          (stat.S_IFDIR|0o755,b'x')):
            with self.subTest(mode=mode,size=len(data)):
                entry=zipfile.ZipInfo('META-INF/'); entry.create_system=3
                entry.external_attr=mode<<16
                self.make_jar([(entry,data)])
                output=self.base/('malformed-'+str(mode)+'-'+str(len(data))+'.zip')
                with self.assertRaises(ValueError): self.build(output)
                self.assertFalse(output.exists())
                self.assertFalse(output.with_suffix('.zip.sha256').exists())
        entry=zipfile.ZipInfo('META-INF/'); entry.create_system=3
        entry.external_attr=(stat.S_IFDIR|0o755)<<16
        self.make_jar([(entry,b'')]); self.build()

    def test_bounds_and_version_reject_before_output(self):
        with patch.object(package,'FILE_LIMIT',3):
            with self.assertRaisesRegex(ValueError,'bound'): self.build()
        for version in ('../escape','1.2.3/dir','v0.1','0.1.0\n'):
            with self.assertRaises(ValueError): package.build(self.root,self.jar,self.out,version)
        with patch.object(package,'TOTAL_LIMIT',100):
            with self.assertRaisesRegex(ValueError,'bound'): self.build()
        self.assertFalse(self.out.exists())

    def test_output_failure_removes_only_owned_files(self):
        original=zipfile.ZipFile.writestr
        def fail(z,name,data,*args,**kwargs):
            if (name.filename if isinstance(name,zipfile.ZipInfo) else name)=='release.json':
                raise OSError('injected disk failure')
            return original(z,name,data,*args,**kwargs)
        with patch.object(zipfile.ZipFile,'writestr',fail):
            with self.assertRaises(OSError): self.build()
        self.assertFalse(self.out.exists()); self.assertFalse(self.out.with_suffix('.zip.sha256').exists())

    def test_real_cli_relocates_and_launchers_forward_arguments(self):
        package.build(package.HERE,self.jar,self.out,'0.1.0-rc.1')
        extracted=self.base/'extracted package'; extracted.mkdir()
        with zipfile.ZipFile(self.out) as z: z.extractall(extracted)
        target=self.base/'scenario with spaces'
        if sys.platform=='win32':
            command=['cmd.exe','/d','/c','call',str(extracted/'robot-runner.cmd')]
        else: command=['sh',str(extracted/'robot-runner')]
        import os
        env=dict(os.environ,ROBOT_RUNNER_PYTHON=sys.executable,PYTHONPATH='')
        result=subprocess.run(command+['init',str(target)],cwd=self.base,env=env,capture_output=True,text=True,timeout=15,creationflags=NO_WINDOW)
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        self.assertEqual(json.loads(result.stdout)['status'],'created')
        result=subprocess.run(command+['validate',str(target/'scenario.json')],cwd=self.base,env=env,capture_output=True,text=True,timeout=15,creationflags=NO_WINDOW)
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        self.assertEqual(json.loads(result.stdout)['scenario']['execution']['mode'],'coordinated')
        self.assertEqual(json.loads(result.stdout)['scenario']['schemaVersion'],3)
        result=subprocess.run(command+['validate',str(target/'missing.json')],cwd=self.base,env=env,capture_output=True,text=True,timeout=15,creationflags=NO_WINDOW)
        self.assertEqual(result.returncode,1,result.stderr+result.stdout)
        self.assertEqual(json.loads(result.stdout)['status'],'error')
        script=('import sys,pathlib,json; sys.path.insert(0,sys.argv[1]); import runner,runner_setup; '
                'p,k,h=runner_setup._control(); '
                'print(json.dumps({"kind":k,"paths":[m.__file__ for n,m in sys.modules.items() '
                'if n.startswith("runner") or n in ("supervisor","runtime_profile","bootstrap")]}))')
        result=subprocess.run([sys.executable,'-c',script,str(extracted)],cwd=self.base,env=env,capture_output=True,text=True,timeout=15,creationflags=NO_WINDOW)
        self.assertEqual(result.returncode,0,result.stderr)
        state=json.loads(result.stdout); self.assertEqual(state['kind'],'package')
        self.assertTrue(all(Path(path).is_relative_to(extracted) for path in state['paths']))

    def test_source_link_or_junction_is_rejected(self):
        link=self.base/'linked'; outside=self.root
        if sys.platform=='win32':
            made=subprocess.run(['cmd.exe','/c','mklink','/J',str(link),str(outside)],capture_output=True,creationflags=NO_WINDOW)
            self.assertEqual(made.returncode,0,made.stderr)
            self.addCleanup(lambda: link.rmdir())
        else: link.symlink_to(outside,target_is_directory=True)
        with self.assertRaises(ValueError): package.build(link,self.jar,self.out,'0.1.0-rc.1')
        self.assertFalse(self.out.exists())


if __name__=='__main__': unittest.main()
