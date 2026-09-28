"""Real short child processes exercise setup cleanup and retained output bounds."""
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import runner_setup as setup


class SetupProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_large_single_write_fails_without_retaining_over_cap(self):
        owner=setup._Owner(self.root,time.monotonic()+5)
        with patch.object(setup.supervisor,'LOG_LIMIT',1024):
            with self.assertRaisesRegex(ValueError,'log bound'):
                owner.run([sys.executable,'-c','import sys; sys.stdout.write("x"*8192); sys.stdout.flush()'],timeout=5)
        self.assertLessEqual((self.root/'setup.log').stat().st_size,1024)

    def test_output_cap_is_shared_across_commands_and_header(self):
        owner=setup._Owner(self.root,time.monotonic()+5)
        with patch.object(setup.supervisor,'LOG_LIMIT',1024):
            owner.run([sys.executable,'-c','print("x"*400)'],timeout=5)
            with self.assertRaisesRegex(ValueError,'log bound'):
                owner.run([sys.executable,'-c','print("x"*600)'],timeout=5)
        self.assertLessEqual((self.root/'setup.log').stat().st_size,1024)

    def test_deadline_kills_child_before_it_can_write_late_file(self):
        owner=setup._Owner(self.root,time.monotonic()+.15)
        target=self.root/'late'
        code='import time; from pathlib import Path; time.sleep(1); Path('+repr(str(target))+').write_text("bad")'
        with self.assertRaises(TimeoutError): owner.run([sys.executable,'-c',code],timeout=5)
        self.assertFalse(target.exists())

    def test_command_failure_retains_log(self):
        owner=setup._Owner(self.root,time.monotonic()+5)
        with self.assertRaises(subprocess.CalledProcessError):
            owner.run([sys.executable,'-c','print("diagnostic"); raise SystemExit(2)'],timeout=5)
        self.assertIn('diagnostic',(self.root/'setup.log').read_text())

    def test_only_official_oc_endpoint_failure_gets_one_pinned_fallback(self):
        owner=setup._Owner(self.root,time.monotonic()+5)
        artifact=setup.bootstrap.ARTIFACTS[2]; path=self.root/artifact['name']
        with patch.object(setup.bootstrap,'acquire',side_effect=[subprocess.CalledProcessError(28,['curl']),None]) as call:
            setup._acquire(path,artifact,owner)
        self.assertEqual(2,call.call_count)
        self.assertEqual((path,setup.OC_API,artifact['sha256']),call.call_args.args)
        self.assertIn('Accept: application/octet-stream',call.call_args.kwargs['headers'])
        with patch.object(setup.bootstrap,'acquire',side_effect=ValueError('hash mismatch')) as call:
            with self.assertRaises(ValueError): setup._acquire(path,artifact,owner)
        self.assertEqual(1,call.call_count)
        with patch.object(setup.bootstrap,'acquire',side_effect=subprocess.CalledProcessError(22,['curl'])) as call:
            with self.assertRaises(subprocess.CalledProcessError): setup._acquire(path,setup.bootstrap.ARTIFACTS[1],owner)
        self.assertEqual(1,call.call_count)

    def test_storage_cap_is_checked(self):
        (self.root/'large').write_bytes(b'x'*50)
        owner=setup._Owner(self.root,time.monotonic()+5)
        with patch.object(setup.supervisor,'COPY_BYTES_LIMIT',20):
            with self.assertRaisesRegex(ValueError,'byte/file bound'): owner.scan()


if __name__=='__main__': unittest.main()
