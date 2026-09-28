import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

import runner_jobs as jobs
import runner_support as support


class SupportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)/'jobs'; self.root.mkdir()
        self.id = 'a'*32; self.job = self.root/self.id; self.job.mkdir()
        self.runtime = self.job/'runtime'; self.runtime.mkdir()
        self.owner = {'jobId': self.id, 'token': 'b'*32}
        (self.root/'.owner').mkdir()
        jobs._atomic(self.root/'.owner/owner.json', self.owner)
        self.meta = dict(schemaVersion=1, jobId=self.id, scenarioId='example', state='running',
                         heartbeat=time.time()-60, created=time.time()-90, acknowledged=True,
                         reason='running', submitPid=2147483640, workerPid=2147483641, serverPid=2147483642)
        jobs._atomic(self.job/'job.json', self.meta)
        self.quiet = patch.object(support, '_processes', return_value=[])
        self.quiet.start(); self.addCleanup(self.quiet.stop)

    def test_recovery_requires_explicit_confirmation_and_preserves_original_metadata(self):
        before=(self.job/'job.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'confirm'):
            support.recover(self.root, self.id)
        result=support.recover(self.root, self.id, confirm_stopped=True)
        self.assertEqual('released',result['status'])
        self.assertFalse((self.root/'.owner').exists())
        self.assertEqual(before,(self.job/'job.json').read_bytes())
        self.assertEqual(self.owner,json.loads((self.job/'recovered-owner/owner.json').read_text()))
        self.assertEqual('unavailable',jobs.status(self.root,self.id)['state'])

    def test_refuse_fresh_owner_even_if_process_snapshot_empty(self):
        self.meta['heartbeat']=time.time(); jobs._atomic(self.job/'job.json',self.meta)
        with self.assertRaisesRegex(ValueError,'responsive'):
            support.recover(self.root,self.id,confirm_stopped=True)
        self.assertTrue((self.root/'.owner').exists())

    def test_refuse_live_pid_reused_pid_unknown_command_and_unrecorded_matching_server(self):
        for processes in ([dict(pid=2147483641,name='unrelated',command='elsewhere')],
                          [dict(pid=14,name='java',command=None)],
                          [dict(pid=15,name='java',command='java -Drobotspike.root='+str(self.runtime))],
                          [dict(pid=16,name='python',command='runner_jobs.py _worker --job '+self.id)]):
            with self.subTest(processes=processes),patch.object(support,'_processes',return_value=processes):
                with self.assertRaisesRegex(ValueError,'live|uncertain'):
                    support.recover(self.root,self.id,confirm_stopped=True)
        self.assertTrue((self.root/'.owner').exists())

    def test_recorded_pid_reused_by_recovery_process_is_not_exempt(self):
        self.meta['submitPid']=os.getpid(); jobs._atomic(self.job/'job.json',self.meta)
        with patch.object(support,'_processes',return_value=[dict(pid=os.getpid(),name='python',command='recover')]):
            with self.assertRaisesRegex(ValueError,'live'):
                support.recover(self.root,self.id,confirm_stopped=True)
        self.assertTrue((self.root/'.owner').exists())

    def test_selected_renamed_runtime_with_unknown_command_refuses_recovery(self):
        jobs._atomic(self.job/'launch.json',{'java':'C:/owned-jdk/bin/renamed-runtime.exe'})
        with patch.object(support,'_processes',return_value=[dict(pid=14,name='renamed-runtime.exe',command=None)]):
            with self.assertRaisesRegex(ValueError,'uncertain'):
                support.recover(self.root,self.id,confirm_stopped=True)
        self.assertTrue((self.root/'.owner').exists())
        (self.job/'launch.json').write_text('{invalid')
        with self.assertRaises(ValueError): support.recover(self.root,self.id,confirm_stopped=True)

    def test_refuse_unknown_metadata_and_changed_owner(self):
        (self.job/'job.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'metadata'):
            support.recover(self.root,self.id,confirm_stopped=True)
        jobs._atomic(self.job/'job.json',self.meta)
        with patch.object(support,'_processes',side_effect=[[],[dict(pid=2147483641,name='python',command='alive')]]):
            with self.assertRaisesRegex(ValueError,'live'):
                support.recover(self.root,self.id,confirm_stopped=True)
        self.assertTrue((self.root/'.owner').exists())

    def test_scan_failure_is_fail_closed(self):
        with patch.object(support,'_processes',side_effect=TimeoutError('scan timeout')):
            with self.assertRaises(TimeoutError): support.recover(self.root,self.id,confirm_stopped=True)
        self.assertTrue((self.root/'.owner').exists())

    def test_diagnostics_allowlist_caps_hashes_and_never_overwrites(self):
        (self.runtime/'stdout.log').write_bytes(b'x'*300000)
        (self.runtime/'program.log').write_text('private console; review before sharing')
        (self.runtime/'observations.ndjson').write_text('not included by default')
        (self.job/'launch.json').write_text('SECRET TOKEN')
        (self.job/'inputs').mkdir(); (self.job/'inputs/secret.lua').write_text('secret')
        output=Path(self.tmp.name)/'diagnostics.zip'
        result=support.diagnostics(self.root,self.id,output)
        self.assertEqual('exported',result['status'])
        with zipfile.ZipFile(output) as archive:
            self.assertNotIn('launch.json',archive.namelist())
            self.assertNotIn('runtime/observations.ndjson',archive.namelist())
            self.assertEqual(128*1024,len(archive.read('runtime/stdout.log')))
            manifest=json.loads(archive.read('diagnostics.json'))
            self.assertTrue(manifest['files']['runtime/stdout.log']['truncated'])
            self.assertEqual(300000-128*1024,manifest['files']['runtime/stdout.log']['offset'])
            self.assertIn('sensitive',manifest['warning'])
        before=output.read_bytes()
        with self.assertRaises(FileExistsError): support.diagnostics(self.root,self.id,output)
        self.assertEqual(before,output.read_bytes())

    def test_diagnostics_optional_observations_and_invalid_metadata_are_retained(self):
        (self.runtime/'observations.ndjson').write_bytes(b'{partial')
        (self.job/'job.json').write_text('{invalid')
        output=Path(self.tmp.name)/'diagnostics.zip'
        support.diagnostics(self.root,self.id,output,include_observations=True)
        with zipfile.ZipFile(output) as archive:
            self.assertEqual(b'{partial',archive.read('runtime/observations.ndjson'))
            self.assertEqual(b'{invalid',archive.read('job.json'))

    def test_diagnostics_refuses_links_and_cleans_partial_archive(self):
        outside=Path(self.tmp.name)/'outside'; outside.write_text('secret')
        try: (self.runtime/'stdout.log').symlink_to(outside)
        except OSError: self.skipTest('symlink privilege unavailable')
        output=Path(self.tmp.name)/'diagnostics.zip'
        with self.assertRaises(ValueError): support.diagnostics(self.root,self.id,output)
        self.assertFalse(output.exists())
        self.assertEqual('secret',outside.read_text())

    def test_cleanup_only_inactive_runtime_preserves_inputs_and_job(self):
        support.recover(self.root,self.id,confirm_stopped=True)
        (self.job/'inputs').mkdir(); (self.job/'inputs/keep').write_text('input')
        (self.runtime/'world').mkdir(); (self.runtime/'world/data').write_text('owned')
        with self.assertRaisesRegex(ValueError,'confirm'):
            support.cleanup(self.root,self.id)
        result=support.cleanup(self.root,self.id,confirm_delete_runtime=True)
        self.assertEqual('removed',result['status'])
        self.assertFalse(self.runtime.exists())
        self.assertEqual('input',(self.job/'inputs/keep').read_text())
        self.assertTrue((self.job/'job.json').exists())

    def test_cleanup_refuses_admission_and_unaudited_unavailable_job(self):
        with self.assertRaisesRegex(ValueError,'admission'):
            support.cleanup(self.root,self.id,confirm_delete_runtime=True)
        jobs._release(self.root,self.id,self.owner['token'])
        with self.assertRaisesRegex(ValueError,'recovery|terminal'):
            support.cleanup(self.root,self.id,confirm_delete_runtime=True)

    def test_actual_process_scan_detects_live_python_job_argument(self):
        self.quiet.stop()
        child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)',self.id],creationflags=support.supervisor.NO_WINDOW)
        try:
            found=support._processes({child.pid},time.monotonic()+15)
            self.assertTrue(any(p['pid']==child.pid for p in found))
            with self.assertRaisesRegex(ValueError,'live'):
                support.recover(self.root,self.id,confirm_stopped=True)
        finally:
            child.terminate(); child.wait(timeout=5)
        self.assertEqual('released',support.recover(self.root,self.id,confirm_stopped=True)['status'])

    def test_actual_worker_crash_keeps_live_server_protected(self):
        self.quiet.stop()
        from test_runner_jobs import JobsTests
        fixture=JobsTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        value=fixture.submit('wait'); job=fixture.root/value['jobId']
        launched=job/'runtime/launched'; deadline=time.monotonic()+5
        while not launched.exists() and time.monotonic()<deadline: time.sleep(.02)
        self.assertTrue(launched.exists())
        fixture.workers[-1].kill(); fixture.workers[-1].wait(timeout=5)
        metadata=json.loads((job/'job.json').read_text()); metadata['heartbeat']=time.time()-60
        jobs._atomic(job/'job.json',metadata)
        try:
            with self.assertRaisesRegex(ValueError,'live'):
                support.recover(fixture.root,value['jobId'],confirm_stopped=True)
            self.assertTrue((fixture.root/'.owner').exists())
        finally:
            # This test owns the just-launched fake process; production recovery never kills.
            pid=metadata['serverPid']
            if os.name=='nt':
                subprocess.run(['taskkill','/PID',str(pid),'/T','/F'],capture_output=True,timeout=5,creationflags=support.supervisor.NO_WINDOW)
            else:
                import signal
                try: os.killpg(pid,signal.SIGKILL)
                except ProcessLookupError: pass

    def test_cli_support_and_setup_cleanup_error_remain_json(self):
        import runner
        output=io.StringIO()
        target=Path(self.tmp.name)/'diagnostics.zip'
        with contextlib.redirect_stdout(output):
            code=runner.main(['diagnostics',self.id,'--jobs-root',str(self.root),'--output',str(target)])
        self.assertEqual(0,code); self.assertEqual('exported',json.loads(output.getvalue())['status'])
        output=io.StringIO()
        with contextlib.redirect_stdout(output),patch('runner_setup.doctor',side_effect=RuntimeError('drain cleanup unresolved')):
            code=runner.main(['doctor','--installation','unused'])
        self.assertEqual(1,code); self.assertEqual('RuntimeError',json.loads(output.getvalue())['error'])

    def test_cleanup_rejects_linked_world_directory_without_deleting_target(self):
        support.recover(self.root,self.id,confirm_stopped=True)
        outside=Path(self.tmp.name)/'outside'; outside.mkdir(); (outside/'keep').write_text('input')
        linked=self.runtime/'world'
        if os.name=='nt':
            command=subprocess.run(['cmd','/c','mklink','/J',str(linked),str(outside)],capture_output=True,creationflags=support.supervisor.NO_WINDOW)
            if command.returncode: self.skipTest('junction creation unavailable')
        else: linked.symlink_to(outside,target_is_directory=True)
        try:
            with self.assertRaises(ValueError): support.cleanup(self.root,self.id,confirm_delete_runtime=True)
            with self.assertRaises(ValueError):
                (self.runtime/'stdout.log').mkdir()
                support.diagnostics(self.root,self.id,Path(self.tmp.name)/'bad.zip')
            self.assertEqual('input',(outside/'keep').read_text())
            self.assertFalse((Path(self.tmp.name)/'bad.zip').exists())
        finally:
            if os.name=='nt': linked.rmdir()
            else: linked.unlink()


if __name__=='__main__': unittest.main()
