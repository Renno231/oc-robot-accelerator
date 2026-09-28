"""Job lifecycle contracts, with real worker/server subprocess boundaries."""
import contextlib
import hashlib
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import runner_jobs as jobs
import supervisor

HERE = Path(__file__).resolve().parent
FAKE_SERVER = '''import json, pathlib, sys, time
root = pathlib.Path(next(a.split('=',1)[1] for a in sys.argv if a.startswith('-Drobotspike.root=')))
mode = next(a.split('=',1)[1] for a in sys.argv if a.startswith('-Drobotspike.mode='))
(root / 'launched').write_text(str(__import__('os').getpid()))
behavior = (root / 'behavior.txt').read_text().strip()
if behavior == 'wait': time.sleep(60)
if behavior == 'pause': time.sleep(0.6)
(root / 'program' / 'main.lua').write_text('changed execution copy')
result = {'status':'passed','reason':'fake','mode':mode,'ticks':2,'elapsedNanos':1,
          'runnerSchemaVersion':1,'scenarioId':'test','program':{'status':'returned','message':''}}
(root / 'result.json').write_text(json.dumps(result))
print('server output must not be protocol output', flush=True)
sys.exit(3 if behavior == 'nonzero' else 0)
'''


class JobsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / 'jobs'; self.root.mkdir()
        self.source = self.base / 'source'; (self.source / 'program').mkdir(parents=True)
        (self.source / 'program' / 'main.lua').write_text('return 42')
        (self.source / 'program' / 'empty').mkdir()
        self.manifest = self.source / 'scenario.json'
        self.spec = {'schemaVersion':1,'id':'test','program':{'directory':'program'},
                     'world':{'region':{'min':[0,4,0],'max':[1,5,1]}},'robot':{'position':[0,4,0]},
                     'execution':{'timeoutSeconds':8}}
        self.manifest.write_text(json.dumps(self.spec))
        self.template = self.base / 'template'; self.template.mkdir()
        for name in supervisor.REQUIRED:
            p = self.template / name; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(b'fixture')
        (self.template / 'eula.txt').write_text('eula=true\n')
        (self.template / 'libraries').mkdir(); (self.template / 'libraries' / 'dummy.jar').write_bytes(b'fixture')
        (self.template / 'behavior.txt').write_text('success')
        (self.template / 'scenario.json').write_text('{"laps":256}')
        self.jar = self.base / 'control.jar'; self.jar.write_bytes(b'control')
        server = self.base / 'server.py'; server.write_text(FAKE_SERVER)
        self.java = self.base / ('java.cmd' if os.name == 'nt' else 'java')
        if os.name == 'nt': self.java.write_text('@echo off\n"%s" "%s" %%*\n' % (sys.executable,server))
        else:
            self.java.write_text('#!%s\n%s' % (sys.executable, FAKE_SERVER)); self.java.chmod(0o755)
        worker = self.base / 'worker.py'
        worker.write_text('import sys,hashlib\nsys.path.insert(0, '+repr(str(HERE))+')\n'
                          'import runner_jobs,supervisor,runtime_profile\n'
                          'supervisor.PINNED={k:hashlib.sha256(b"fixture").hexdigest() for k in supervisor.PINNED}\n'
                          'runtime_profile.apply=lambda *a,**k:{}\n'
                          'runtime_profile.verify_proof=lambda *a,**k:{"fakeProcessBoundary":True}\n'
                          'sys.exit(runner_jobs.main())\n')
        self.worker = [sys.executable, str(worker)]
        self.workers = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for process in self.workers:
            if process.poll() is None: supervisor._stop_tree(process)
        # Crash tests deliberately leave admission held; their server is explicitly cleaned by the test.
        self.temp.cleanup()

    def submit(self, behavior='success', **kwargs):
        (self.template / 'behavior.txt').write_text(behavior)
        real = subprocess.Popen
        def launch(*args, **kw):
            process = real(*args, **kw); self.workers.append(process); return process
        with mock.patch.object(jobs.subprocess, 'Popen', side_effect=launch):
            return jobs.submit(self.manifest,self.root,str(self.java),self.template,self.jar,
                               worker_command=kwargs.pop('worker_command_override',self.worker), **kwargs)

    def finish(self, value, timeout=12):
        value = jobs.wait(self.root,value['jobId'],timeout)
        for process in self.workers:
            if process.poll() is None: process.wait(timeout=5)
        return value

    def test_real_worker_immutable_inputs_and_success(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output): value = self.submit()
        self.assertEqual(output.getvalue(),'')
        value = self.finish(value)
        self.assertEqual(value['state'],'passed',value)
        job = self.root / value['jobId']
        self.assertEqual((job / 'inputs/program/main.lua').read_text(),'return 42')
        self.assertEqual((self.source / 'program/main.lua').read_text(),'return 42')
        self.assertEqual((job / 'runtime/program/main.lua').read_text(),'changed execution copy')
        self.assertTrue((job / 'runtime/program/empty').is_dir())
        self.assertFalse((job / 'runtime/scenario.json').exists())
        self.assertFalse((self.root / '.owner').exists())
        settings = (job / 'runtime/config/opencomputers/settings.conf').read_text()
        self.assertIn('enableHttp=false',settings)
        self.assertIn('enableTcp=false',settings)
        self.assertNotIn(' enable=false',settings)
        self.assertIn('ignorePower=false',settings)
        report = json.loads((job / 'runtime/supervisor.json').read_text())
        self.assertTrue(report['cleanup_ok']); self.assertIn('runner/program/main.lua',report['sha256'])

    def test_installed_libraries_cross_real_detached_worker_boundary(self):
        libraries=self.base/'installation/payload/runtime-libraries'; libraries.mkdir(parents=True)
        worker=Path(self.worker[1])
        worker.write_text(worker.read_text().replace('runtime_profile.apply=lambda *a,**k:{}',
            'def apply(root, cache, check):\n (root/"selected-libraries.txt").write_text(str(cache))\n return {}\n'
            'runtime_profile.apply=apply'))
        identity={'size':7,'sha256':hashlib.sha256(b'control').hexdigest()}
        value=self.finish(self.submit(runtime_libraries=libraries,control_identity=identity))
        self.assertEqual('passed',value['state'],value)
        job=self.root/value['jobId']
        self.assertEqual(str(libraries),json.loads((job/'launch.json').read_text())['runtimeLibraries'])
        self.assertEqual(str(libraries),(job/'runtime/selected-libraries.txt').read_text())
        with self.assertRaisesRegex(ValueError,'overlap'):
            jobs.submit(self.manifest,libraries.parent/'jobs',str(self.java),self.template,self.jar,
                        runtime_libraries=libraries,control_identity=identity,worker_command=self.worker)

    def test_installed_control_changed_before_worker_copy_is_rejected(self):
        libraries=self.base/'installation/payload/runtime-libraries'; libraries.mkdir(parents=True)
        worker=Path(self.worker[1])
        worker.write_text(worker.read_text().replace('sys.exit(runner_jobs.main())',
            'from pathlib import Path\nPath('+repr(str(self.jar))+').write_bytes(b"changed")\nsys.exit(runner_jobs.main())'))
        identity={'size':7,'sha256':hashlib.sha256(b'control').hexdigest()}
        value=self.finish(self.submit(runtime_libraries=libraries,control_identity=identity))
        self.assertEqual('failed',value['state'],value)
        self.assertIn('selected control identity',value['reason'])
        self.assertFalse((self.root/value['jobId']/'runtime/launched').exists())
        self.assertFalse((self.root/'.owner').exists())

    def test_admission_cancel_idempotence_and_terminal_immutability(self):
        value = self.submit('wait')
        with self.assertRaisesRegex(ValueError,'admission|active|owner'):
            # Do not mutate the live first worker's template via submit('success').
            jobs.submit(self.manifest,self.root,str(self.java),self.template,self.jar,
                        worker_command=self.worker)
        jobs.cancel(self.root,value['jobId']); jobs.cancel(self.root,value['jobId'])
        final = self.finish(value)
        self.assertEqual(final['state'],'cancelled',final)
        self.assertEqual(jobs.cancel(self.root,value['jobId'])['state'],'cancelled')
        self.assertFalse((self.root / '.owner').exists())

    def test_large_legal_scenario_freezes_and_installs_with_same_byte_cap(self):
        self.spec['robot']['inventory']=[{'slot':i+1,'item':'minecraft:stone','count':1,
            'nbt':'{text:"'+'x'*4086+'"}'} for i in range(16)]
        self.spec['world']['blocks']=[{'min':[0,4,0],'max':[1,5,1],'block':'minecraft:stone'} for _ in range(128)]
        self.spec['expect']={'blocks':[{'position':[0,4,0],'block':'minecraft:stone'} for _ in range(256)],
                             'inventory':[{'item':'minecraft:stone','minCount':1} for _ in range(64)]}
        self.manifest.write_text(json.dumps(self.spec,separators=(',',':')),encoding='utf-8')
        spec=jobs.scenario.load(self.manifest)
        frozen=self.base/'frozen'; jobs.scenario.freeze(spec,frozen)
        runtime=self.base/'install'; (runtime/'config/opencomputers').mkdir(parents=True)
        jobs._install(frozen,runtime,spec.normalized['execution'],lambda:None)
        self.assertLessEqual((frozen/'runner-scenario.json').stat().st_size,jobs.scenario.MANIFEST_BYTES)
        self.assertEqual(jobs.scenario.read_json(runtime/'runner-scenario.json'),spec.normalized)

    def test_nonzero_server_cannot_pass(self):
        final = self.finish(self.submit('nonzero'))
        self.assertEqual(final['state'],'failed',final)
        self.assertIn('nonzero',final['reason'])

    def test_public_long_budget_reaches_real_worker_and_cancels(self):
        self.spec['schemaVersion']=2
        self.spec['execution']={'maxTicks':1728000,'timeoutSeconds':90000}
        self.manifest.write_text(json.dumps(self.spec))
        value=self.submit('wait')
        job=self.root/value['jobId']
        deadline=time.monotonic()+5
        while jobs.status(self.root,value['jobId'])['state']=='launching' and time.monotonic()<deadline:
            time.sleep(.02)
        launch=json.loads((job/'launch.json').read_text())
        self.assertEqual(launch['deadline'],launch['start']+90000)
        self.assertEqual(launch['execution']['maxTicks'],1728000)
        jobs.cancel(self.root,value['jobId']); final=self.finish(value)
        self.assertEqual(final['state'],'cancelled',final)
        self.assertTrue(final['cleanupOk']); self.assertFalse((self.root/'.owner').exists())
        report=json.loads((job/'runtime/supervisor.json').read_text())
        self.assertIn('-Drobotspike.maxTicks=1728000',report['command'])
        self.assertIn('-Drobotspike.timeoutSeconds=90000',report['command'])

    def test_wait_accepts_finite_public_budget_but_rejects_invalid(self):
        with mock.patch.object(jobs,'status',return_value={'state':'passed','jobId':'a'*32}):
            self.assertEqual(jobs.wait(self.root,'a'*32,90000)['state'],'passed')
            for value in [90001,0,-1,float('inf'),float('nan'),True]:
                with self.subTest(value=value), self.assertRaises(ValueError): jobs.wait(self.root,'a'*32,value)

    def test_foreground_accepts_exact_maximum_deadline_despite_subtraction_roundoff(self):
        jobid='a'*32; job=self.root/jobid; job.mkdir()
        start=1000000.1; deadline=start+jobs.scenario.MAX_TIMEOUT_SECONDS
        self.assertGreater(deadline-start,jobs.scenario.MAX_TIMEOUT_SECONDS)
        launch={'jobId':jobid,'start':start,'deadline':deadline}
        (job/'launch.json').write_text(json.dumps(launch))
        with mock.patch.object(jobs,'_wait',return_value={'state':'passed'}) as wait, \
                mock.patch.object(jobs.time,'monotonic',return_value=start):
            self.assertEqual(jobs.wait_foreground(self.root,jobid)['state'],'passed')
            wait.assert_called_once_with(self.root,jobid,deadline+10,stop_unavailable=True)
        for invalid in (start, deadline+0.001, float('inf')):
            launch['deadline']=invalid
            (job/'launch.json').write_text(json.dumps(launch))
            with self.subTest(deadline=invalid), self.assertRaises(ValueError):
                jobs.wait_foreground(self.root,jobid)

    def test_foreground_uses_owned_deadline_past_600_and_returns_unavailable(self):
        jobid='a'*32; job=self.root/jobid; job.mkdir()
        (job/'launch.json').write_text(json.dumps({'jobId':jobid,'start':0,'deadline':1200}))
        statuses=[{'state':'running'},{'state':'running'},{'state':'passed'}]
        with mock.patch.object(jobs,'status',side_effect=statuses), mock.patch.object(jobs.time,'monotonic',side_effect=[700,701,702]), mock.patch.object(jobs.time,'sleep'), mock.patch.object(jobs,'cancel') as cancel:
            self.assertEqual(jobs.wait_foreground(self.root,jobid)['state'],'passed')
            cancel.assert_not_called()
        with mock.patch.object(jobs,'status',return_value={'state':'unavailable'}), mock.patch.object(jobs,'cancel') as cancel:
            self.assertEqual(jobs.wait_foreground(self.root,jobid)['state'],'unavailable')
            cancel.assert_not_called()
        self.assertFalse((job/'cancel').exists())

    def test_foreground_crosses_600_and_times_out_only_after_owned_cleanup_grace(self):
        jobid='a'*32; job=self.root/jobid; job.mkdir()
        (job/'launch.json').write_text(json.dumps({'jobId':jobid,'start':0,'deadline':1200}))
        with mock.patch.object(jobs,'status',side_effect=[{'state':'running'}]*3+[{'state':'passed'}]), mock.patch.object(jobs.time,'monotonic',side_effect=[599,599,601,1209.99]), mock.patch.object(jobs.time,'sleep'), mock.patch.object(jobs,'cancel') as cancel:
            self.assertEqual(jobs.wait_foreground(self.root,jobid)['state'],'passed')
            cancel.assert_not_called()
        with mock.patch.object(jobs,'status',return_value={'state':'running'}), mock.patch.object(jobs.time,'monotonic',side_effect=[599,1209.99,1210]), mock.patch.object(jobs.time,'sleep') as sleep, mock.patch.object(jobs,'cancel') as cancel:
            with self.assertRaisesRegex(TimeoutError,'not cancelled'): jobs.wait_foreground(self.root,jobid)
            self.assertAlmostEqual(sleep.call_args.args[0],.01)
            cancel.assert_not_called()
        self.assertFalse((job/'cancel').exists())

    def test_wait_timeout_does_not_cancel(self):
        value = self.submit('wait')
        with self.assertRaises(TimeoutError): jobs.wait(self.root,value['jobId'],0.05)
        self.assertFalse((self.root / value['jobId'] / 'cancel').exists())
        jobs.cancel(self.root,value['jobId']); self.finish(value)

    def test_shared_deadline_timeout(self):
        self.spec['execution']['timeoutSeconds']=1
        self.manifest.write_text(json.dumps(self.spec))
        final = self.finish(self.submit('wait'))
        self.assertEqual(final['state'],'failed',final)
        self.assertIn('timeout',final['reason'])
        self.assertFalse((self.root / '.owner').exists())

    def test_reserved_template_and_extra_mod_fail_before_server(self):
        for name in ('runner-scenario.json','world/level.dat','mods/extra.jar',
                     'observations-status.json','.observations-status.json.tmp'):
            with self.subTest(name=name):
                p=self.template/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_text('{}')
                final=self.finish(self.submit())
                self.assertEqual(final['state'],'failed',final)
                self.assertFalse((self.root/final['jobId']/'runtime/launched').exists())
                p.unlink()
                if name.startswith('world/'): p.parent.rmdir()

    def test_atomic_metadata_retries_transient_windows_reader_lock(self):
        target=self.base/'atomic.json'; replace=os.replace; attempts=[]
        def transient(source,destination):
            attempts.append(1)
            if len(attempts)<3: raise PermissionError('reader briefly holds Windows file')
            return replace(source,destination)
        with mock.patch.object(jobs.os,'replace',side_effect=transient):
            jobs._atomic(target,{'value':42})
        self.assertEqual(json.loads(target.read_text()),{'value':42})
        self.assertEqual(len(attempts),3)

    def test_partial_metadata_and_invalid_id_never_report_completion(self):
        for bad in ('../escape','x','a'*32+'/x'):
            with self.assertRaises(ValueError): jobs.status(self.root,bad)
        jobid='a'*32; (self.root/jobid).mkdir(); (self.root/jobid/'job.json').write_text('{')
        value=jobs.status(self.root,jobid)
        self.assertEqual(value['state'],'unavailable')

    def test_prelaunch_cancel_stops_freeze_without_worker(self):
        original=jobs.scenario.freeze
        def cancelled(spec,destination,check):
            (destination.parent/'cancel').write_text('cancel')
            check()
            return original(spec,destination,check)
        with mock.patch.object(jobs.scenario,'freeze',side_effect=cancelled):
            value=self.submit()
        self.assertEqual(value['state'],'cancelled')
        self.assertTrue(value['cleanupOk'])
        self.assertFalse(self.workers)
        self.assertFalse((self.root/'.owner').exists())

    def test_active_freeze_refreshes_heartbeat(self):
        original=jobs.scenario.freeze
        def checked(spec,destination,check):
            path=destination.parent/'job.json'
            old=json.loads(path.read_text()); old['heartbeat']=time.time()-10
            jobs._atomic(path,old)
            time.sleep(.55); check()
            value=jobs.status(self.root,destination.parent.name)
            self.assertEqual(value['state'],'launching',value)
            self.assertLess(time.time()-value['heartbeat'],1)
            return original(spec,destination,check)
        with mock.patch.object(jobs.scenario,'freeze',side_effect=checked):
            value=self.submit()
        self.assertEqual(self.finish(value)['state'],'passed')

    def test_interrupt_during_ack_retains_job_identity_and_requests_cleanup(self):
        real_status=jobs.status; interrupted=[]
        def interrupt_once(root,jobid):
            if not interrupted:
                interrupted.append(jobid)
                raise KeyboardInterrupt()
            return real_status(root,jobid)
        with mock.patch.object(jobs,'status',side_effect=interrupt_once):
            try: self.submit('wait')
            except KeyboardInterrupt as exc:
                self.assertEqual(getattr(exc,'jobid',None),interrupted[0])
            else: self.fail('interrupt not propagated')
        final=self.finish({'jobId':interrupted[0]})
        self.assertEqual(final['state'],'cancelled')
        self.assertTrue(final['cleanupOk'])

    def test_foreground_cli_ack_interrupt_waits_for_actual_worker_cleanup(self):
        import runner
        real_status=jobs.status; real_submit=jobs.submit; interrupted=[]
        delayed=self.base/'delayed_worker.py'
        delayed.write_text('import time,runpy\ntime.sleep(.6)\nrunpy.run_path('+repr(self.worker[1])+',run_name="__main__")\n')
        def interrupt_once(root,jobid):
            if not interrupted:
                interrupted.append(jobid); raise KeyboardInterrupt()
            return real_status(root,jobid)
        def submit(*args):
            return real_submit(*args,worker_command=[sys.executable,str(delayed)])
        real_popen=subprocess.Popen
        def launch(*args,**kw):
            process=real_popen(*args,**kw); self.workers.append(process); return process
        output=io.StringIO(); start=time.monotonic()
        with mock.patch.object(jobs.subprocess,'Popen',side_effect=launch), mock.patch.object(jobs,'submit',side_effect=submit), mock.patch.object(jobs,'status',side_effect=interrupt_once), contextlib.redirect_stdout(output):
            code=runner.main(['run',str(self.manifest),'--jobs-root',str(self.root),'--java',str(self.java),
                              '--template',str(self.template),'--control-jar',str(self.jar)])
        value=json.loads(output.getvalue())
        self.assertEqual(code,130); self.assertEqual(value['jobId'],interrupted[0])
        self.assertEqual(value['state'],'cancelled'); self.assertTrue(value['cleanupOk'])
        self.assertGreaterEqual(time.monotonic()-start,.6)
        self.assertFalse((self.root/'.owner').exists())

    def test_malformed_or_incomplete_metadata_never_reports_terminal(self):
        jobid='b'*32; path=self.root/jobid/'job.json'; path.parent.mkdir()
        valid={'schemaVersion':1,'jobId':jobid,'scenarioId':'test','state':'passed',
               'heartbeat':time.time(),'created':time.time()-2,'completed':time.time(),
               'acknowledged':True,'cleanupOk':True,'reason':'done'}
        for patch in ({'state':[]},{'heartbeat':float('inf')},{'completed':None},
                      {'cleanupOk':False},{'schemaVersion':True},{'acknowledged':1}):
            with self.subTest(patch=patch):
                path.write_text(json.dumps(dict(valid,**patch)))
                self.assertEqual(jobs.status(self.root,jobid)['state'],'unavailable')
        path.write_text(json.dumps(valid).replace(str(valid['heartbeat']),'1e999'))
        self.assertEqual(jobs.status(self.root,jobid)['state'],'unavailable')
        path.write_text(json.dumps(valid))
        self.assertEqual(jobs.status(self.root,jobid)['state'],'passed')

    def test_owner_death_before_java_keeps_admission(self):
        dead=self.base/'dead.py'; dead.write_text('import time\ntime.sleep(60)\n')
        with self.assertRaises(TimeoutError):
            self.submit(worker_command_override=[sys.executable,str(dead)],ack_timeout=0.2)
        self.assertTrue((self.root/'.owner').is_dir())
        with self.assertRaises(ValueError): self.submit()

    def test_owner_death_after_java_keeps_admission(self):
        value=self.submit('wait'); job=self.root/value['jobId']; launched=job/'runtime/launched'
        deadline=time.monotonic()+5
        while not launched.exists() and time.monotonic()<deadline: time.sleep(.02)
        self.assertTrue(launched.exists())
        # Simulate abrupt owner-only loss, not a normal cancellation/cleanup path.
        self.workers[-1].kill(); self.workers[-1].wait(timeout=5)
        self.assertTrue((self.root/'.owner').exists())
        with self.assertRaises(ValueError): self.submit()
        pid=int(launched.read_text())
        try:
            if os.name=='nt': subprocess.run(['taskkill','/PID',str(pid),'/T','/F'],capture_output=True,timeout=5,creationflags=supervisor.NO_WINDOW)
            else: os.kill(pid,9)
        except ProcessLookupError: pass

    def test_concurrent_submission_admits_only_one_owner(self):
        (self.template/'behavior.txt').write_text('wait')
        def attempt():
            try:
                return jobs.submit(self.manifest,self.root,str(self.java),self.template,self.jar,worker_command=self.worker)
            except ValueError as exc: return str(exc)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:attempt(),range(2)))
        accepted=[result for result in results if isinstance(result,dict)]
        self.assertEqual(len(accepted),1,results)
        self.assertIn('admission',next(result for result in results if isinstance(result,str)))
        jobs.cancel(self.root,accepted[0]['jobId']); self.finish(accepted[0])

    def test_cleanup_failure_retains_owner_and_never_publishes_terminal(self):
        worker=self.base/'failed_cleanup.py'
        worker.write_text('import sys\nsys.path.insert(0,'+repr(str(HERE))+')\n'
                          'import runner_jobs,supervisor\n'
                          'supervisor.execute=lambda *a,**k:{"report":{"cleanup_ok":False,"cancelled":False,'
                          '"status":"failed","reason":"test cleanup failure","elapsed_wall_seconds":0}}\n'
                          'sys.exit(runner_jobs.main())\n')
        value=self.submit(worker_command_override=[sys.executable,str(worker)])
        self.workers[-1].wait(timeout=5)
        final=jobs.status(self.root,value['jobId'])
        self.assertNotIn(final['state'],jobs.TERMINAL)
        self.assertTrue((self.root/'.owner').exists())
        self.assertIn('cleanup unresolved',final['reason'])

    def test_frozen_input_removal_is_detected_before_execution(self):
        import runner_scenario
        spec=runner_scenario.load(self.manifest)
        inputs=self.base/'frozen'; runner_scenario.freeze(spec,inputs)
        (inputs/'program/main.lua').unlink()
        runtime=self.base/'install'; runtime.mkdir()
        with self.assertRaisesRegex(ValueError,'hash drift'):
            jobs._install(inputs,runtime,spec.normalized['execution'],lambda:None)

    def test_budget_is_applied_before_program_tree_scan(self):
        original=jobs.scenario._scan
        def slow_scan(*args,**kwargs):
            time.sleep(1.05)
            return original(*args,**kwargs)
        self.spec['execution']['timeoutSeconds']=1; self.manifest.write_text(json.dumps(self.spec))
        with mock.patch.object(jobs.scenario,'_scan',side_effect=slow_scan):
            with self.assertRaises(TimeoutError): self.submit()
        self.assertFalse((self.root/'.owner').exists())

    def test_overlap_rejected_before_admission(self):
        with self.assertRaises(ValueError):
            jobs.submit(self.manifest,self.source/'jobs',str(self.java),self.template,self.jar)
        self.assertFalse((self.source/'jobs'/'.owner').exists())

    def test_cancel_completion_race_always_terminal_after_cleanup(self):
        for _ in range(3):
            value=self.submit('pause'); jobs.cancel(self.root,value['jobId'])
            final=self.finish(value)
            self.assertIn(final['state'],('passed','cancelled'))
            self.assertEqual(jobs.status(self.root,value['jobId'])['state'],final['state'])
            self.assertFalse((self.root/'.owner').exists())


if __name__=='__main__': unittest.main()
