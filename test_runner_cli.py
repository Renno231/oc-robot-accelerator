"""CLI JSON/initialization/dispatch behavior without invoking Minecraft."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import runner
from supervisor import NO_WINDOW


class Cli(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def invoke(self, *args):
        out=io.StringIO()
        with contextlib.redirect_stdout(out): code=runner.main(list(args))
        return code,json.loads(out.getvalue())

    def test_init_mining_example_validate_and_refuse_overwrite(self):
        target=self.root/'sample'
        code,value=self.invoke('init',str(target)); self.assertEqual(code,0)
        self.assertTrue((target/'program/main.lua').is_file())
        self.assertTrue((target/'program/miner.lua').is_file())
        code,value=self.invoke('validate',str(target/'scenario.json')); self.assertEqual(code,0)
        self.assertEqual(value['scenario']['id'],'mining-example')
        self.assertEqual(value['scenario']['schemaVersion'],3)
        self.assertEqual(value['scenario']['execution']['mode'],'coordinated')
        self.assertEqual(value['scenario']['execution']['executionDelayMillis'],12)
        raw=json.loads((target/'scenario.json').read_text())
        self.assertEqual(raw['robot']['hardware'],{'preset':'hardware/tier3.json'})
        self.assertEqual(value['scenario']['robot']['hardware']['storage'],['hdd3'])
        self.assertGreater(value['programFiles'],2)
        code,value=self.invoke('init',str(target)); self.assertEqual(code,1)
        self.assertEqual(value['status'],'error')

    def test_init_includes_editable_hardware_presets_and_validate_resolves_overrides(self):
        target=self.root/'presets'
        self.assertEqual(self.invoke('init',str(target))[0],0)
        path=target/'scenario.json'; value=json.loads(path.read_text()); value['schemaVersion']=3
        for tier in (1,2,3,'creative'):
            preset=target/'hardware'/('creative.json' if tier=='creative' else 'tier'+str(tier)+'.json')
            self.assertTrue(preset.is_file())
            value['robot']['hardware']={'preset':'hardware/'+preset.name,'overrides':{'cards':[]}}
            path.write_text(json.dumps(value))
            code,result=self.invoke('validate',str(path)); self.assertEqual(code,0)
            self.assertEqual(result['scenario']['robot']['hardware']['tier'],tier)
            self.assertEqual(result['scenario']['robot']['hardware']['cards'],[])

    def test_bad_scenario_returns_one_json_error(self):
        code,value=self.invoke('validate',str(self.root/'missing.json'))
        self.assertEqual(code,1); self.assertIn('message',value)

    def test_detach_does_not_wait_and_failure_propagates(self):
        state={'state':'running','jobId':'a'*32}
        args=['run','scenario.json','--jobs-root',str(self.root),'--java','java']
        with mock.patch.object(runner.jobs,'submit',return_value=state), mock.patch.object(runner.jobs,'wait_foreground') as wait:
            code,value=self.invoke(*args,'--detach'); self.assertEqual(code,0); wait.assert_not_called()
        with mock.patch.object(runner.jobs,'submit',return_value=state), mock.patch.object(runner.jobs,'wait_foreground',return_value={'state':'failed'}):
            code,value=self.invoke(*args); self.assertEqual(code,1)

    def test_foreground_interrupt_requests_cancel_and_collects_status(self):
        state={'state':'running','jobId':'a'*32}
        with mock.patch.object(runner.jobs,'submit',return_value=state), mock.patch.object(runner.jobs,'wait_foreground',side_effect=KeyboardInterrupt()), mock.patch.object(runner.jobs,'wait',return_value={'state':'cancelled'}), mock.patch.object(runner.jobs,'cancel') as cancel:
            code,value=self.invoke('run','s.json','--jobs-root',str(self.root),'--java','java')
            self.assertEqual(code,130); cancel.assert_called_once()
            self.assertEqual(value['state'],'cancelled')

    def test_foreground_ack_interrupt_waits_for_owned_job(self):
        jobid='a'*32
        with mock.patch.object(runner.jobs,'submit',side_effect=runner.jobs.SubmissionInterrupted(jobid)), mock.patch.object(runner.jobs,'wait',return_value={'jobId':jobid,'state':'cancelled','cleanupOk':True}) as wait, mock.patch.object(runner.jobs,'cancel') as cancel:
            code,value=self.invoke('run','s.json','--jobs-root',str(self.root),'--java','java')
        self.assertEqual(code,130); self.assertEqual(value['jobId'],jobid)
        self.assertTrue(value['cleanupOk']); wait.assert_called_once_with(str(self.root),jobid,timeout=10)
        cancel.assert_called_once_with(str(self.root),jobid)

    def test_corrupt_persisted_metadata_and_observations_stay_json(self):
        jobid='a'*32; job=self.root/jobid; (job/'runtime').mkdir(parents=True)
        for payload in ('{"schemaVersion":1,"jobId":"'+jobid+'","state":[],"heartbeat":1}',
                        '{"schemaVersion":1,"jobId":"'+jobid+'","state":"passed","heartbeat":1e999}',
                        '{"schemaVersion":1,"jobId":"'+jobid+'","state":"passed","heartbeat":1}'):
            (job/'job.json').write_text(payload)
            code,value=self.invoke('status',jobid,'--jobs-root',str(self.root))
            self.assertEqual(code,1); self.assertEqual(value['state'],'unavailable')
        record={'schemaVersion':1,'sequence':0,'tick':0,'kind':'initial','everyTicks':1,
                'region':{'min':[0,0,0],'max':[0,0,0]},
                'blocks':[{'position':[0,0,0],'block':'minecraft:air','properties':{}}],
                'robot':{'position':[0,0,0],'energy':12345}}
        (job/'runtime/observations.ndjson').write_text(json.dumps(record).replace('12345','1e999')+'\n')
        code,value=self.invoke('observations',jobid,'--jobs-root',str(self.root))
        self.assertEqual(code,1); self.assertEqual(value['status'],'error')
        with mock.patch.object(runner.jobs,'status',return_value={'state':'running','energy':float('inf')}):
            code,value=self.invoke('status',jobid,'--jobs-root',str(self.root))
            self.assertEqual(code,1); self.assertEqual(value['status'],'error')

    def test_status_wait_cancel_dispatch_and_timeout_does_not_cancel(self):
        for command in ('status','wait','cancel'):
            with mock.patch.object(runner.jobs,command,return_value={'state':'passed'}) as call:
                code,value=self.invoke(command,'a'*32,'--jobs-root',str(self.root)); self.assertEqual(code,0); call.assert_called_once()
        with mock.patch.object(runner.jobs,'wait',side_effect=TimeoutError('wait timeout')), mock.patch.object(runner.jobs,'cancel') as cancel:
            code,value=self.invoke('wait','a'*32,'--jobs-root',str(self.root),'--timeout','1')
            self.assertEqual(code,1); cancel.assert_not_called()

    def test_setup_doctor_and_installed_run_dispatch(self):
        import runner_setup
        with mock.patch.object(runner_setup,'install',return_value={'status':'ready'}) as install:
            code,value=self.invoke('setup','--installation',str(self.root/'i'),'--java','java','--accept-eula')
            self.assertEqual(code,0); install.assert_called_once_with(str(self.root/'i'),'java',900,accept_eula=True)
        with mock.patch.object(runner_setup,'doctor',return_value={'status':'incomplete'}):
            code,value=self.invoke('doctor','--installation',str(self.root/'i')); self.assertEqual(code,1)
        paths={'java':'selected-java','template':self.root/'i/payload/server',
               'control_jar':self.root/'i/payload/control.jar','runtime_libraries':self.root/'i/payload/runtime-libraries',
               'control_identity':{'size':7,'sha256':'a'*64}}
        with mock.patch.object(runner_setup,'resolve',return_value=paths), mock.patch.object(runner.jobs,'submit',return_value={'state':'passed'}) as submit:
            code,value=self.invoke('run','s.json','--installation',str(self.root/'i'),'--jobs-root',str(self.root/'jobs'))
            self.assertEqual(code,0)
            submit.assert_called_once_with('s.json',str(self.root/'jobs'),'selected-java',paths['template'],paths['control_jar'],runtime_libraries=paths['runtime_libraries'],control_identity=paths['control_identity'])
        with mock.patch.object(runner.jobs,'submit') as submit:
            code,value=self.invoke('run','s.json','--installation','i','--template','t','--jobs-root','j')
            self.assertEqual(code,1); submit.assert_not_called()
            code,value=self.invoke('run','s.json','--jobs-root','j')
            self.assertEqual(code,1); submit.assert_not_called()

    def test_actual_cli_stdout_is_json(self):
        result=subprocess.run([sys.executable,str(Path(runner.__file__)),'init',str(self.root/'subprocess')],capture_output=True,text=True,timeout=10,creationflags=NO_WINDOW)
        self.assertEqual(result.returncode,0,result.stderr); self.assertEqual(json.loads(result.stdout)['status'],'created')


if __name__=='__main__': unittest.main()
