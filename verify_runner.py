"""Opt-in serialized real-server acceptance. Retains owned cases/jobs/report for inspection."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

import runner_observations
from supervisor import NO_WINDOW

HERE=Path(__file__).resolve().parent


def hashes(root):
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file()}


class Acceptance:
    def __init__(self,args):
        self.args=args; self.root=Path(args.output).absolute(); self.root.mkdir(parents=True,exist_ok=False)
        self.jobs=self.root/'jobs'; self.rows=[]

    def cli(self,*arguments,timeout=150):
        command=[sys.executable,str(HERE/'runner.py'),*map(str,arguments)]
        result=subprocess.run(command,cwd=HERE,capture_output=True,text=True,timeout=timeout,creationflags=NO_WINDOW)
        value=json.loads(result.stdout)
        return result.returncode,value,command

    def case(self,label,*,mode='coordinated',program=None,patch=None,version=3):
        target=self.root/'scenarios'/label
        shutil.copytree(HERE/'examples/mining',target)
        manifest=target/'scenario.json'; data=json.loads(manifest.read_text())
        data['id']=label; data['execution']['mode']=mode; data['schemaVersion']=version
        if version<3: data['robot']['hardware']='tier3'
        if program is not None:
            (target/'program/main.lua').write_text(program,encoding='utf-8'); data['expect']={}
        if patch: patch(data)
        manifest.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
        return manifest

    def run(self,label,manifest,expected,*,detached=False,cancel=False,command_timeout=150):
        before=hashes(manifest.parent)
        arguments=['run',manifest,'--jobs-root',self.jobs,'--java',self.args.java,
                   '--template',self.args.template,'--control-jar',self.args.control_jar]
        if detached or cancel: arguments.append('--detach')
        code,status,command=self.cli(*arguments,timeout=command_timeout)
        commands=[command]
        if 'jobId' not in status: raise AssertionError((label,status))
        jobid=status['jobId']; history=[status]
        if detached or cancel:
            _,current,command=self.cli('status',jobid,'--jobs-root',self.jobs); commands.append(command); history.append(current)
            if cancel:
                # Wait for an actual running server, rather than cancel only a template copy.
                until=time.monotonic()+60
                while current.get('state') not in ('running','failed','passed','cancelled') and time.monotonic()<until:
                    time.sleep(.1)
                    _,current,_=self.cli('status',jobid,'--jobs-root',self.jobs)
                if current.get('state')!='running': raise AssertionError(('no running server to cancel',current))
                code,current,command=self.cli('cancel',jobid,'--jobs-root',self.jobs); commands.append(command); history.append(current)
            code,status,command=self.cli('wait',jobid,'--jobs-root',self.jobs,'--timeout','120',timeout=135)
            commands.append(command); history.append(status)
        job=self.jobs/jobid; runtime=job/'runtime'
        mod=json.loads((runtime/'result.json').read_text()) if (runtime/'result.json').exists() else None
        supervisor=json.loads((runtime/'supervisor.json').read_text())
        row={'label':label,'jobId':jobid,'commands':commands,'statusHistory':history,'status':status,
             'cliExit':code,'result':mod,'supervisor':supervisor,'inputUnchanged':before==hashes(manifest.parent)}
        self.rows.append(row); self.save()
        assert row['inputUnchanged'],label+' source mutation'
        assert status['state']==expected,(label,status)
        assert supervisor['cleanup_ok'],label+' cleanup'
        assert not (self.jobs/'.owner').exists(),label+' admission retained after cleanup'
        assert (code==0)==(expected=='passed'),(label,code)
        if mod and expected!='cancelled':
            assert mod['status']==('passed' if expected=='passed' else 'failed'),(label,mod)
        return runtime,row

    def save(self):
        (self.root/'acceptance.json').write_text(json.dumps({'schemaVersion':1,'runs':self.rows},indent=2)+'\n',encoding='utf-8')

    def execute(self):
        baseline,_=self.run('mining-baseline',self.case('mining-baseline',mode='baseline'),'passed')
        coordinated,row=self.run('mining-coordinated',self.case('mining-coordinated'),'passed',detached=True)
        for runtime in (baseline,coordinated):
            assert 'Mining complete' in (runtime/'program.log').read_text()
            outputs=list((runtime/'world/opencomputers').glob('*/home/program/report.txt'))
            assert len(outputs)==1,outputs
            assert outputs[0].read_text().strip()=='Mined and returned: 4'
            assert not (runtime.parent/'inputs/program/report.txt').exists()
            state=runner_observations.reconstruct(runtime/'observations.ndjson')
            assert state['summary']['finalRecorded'] and state['summary']['records']>2
            assert state['last']['robot']['position']==[0,65,0]
            assert state['blocks'][(0,65,-4)]['block']=='minecraft:air'
        self.cli('observations',row['jobId'],'--jobs-root',self.jobs)
        for version in (1,2):
            label='legacy-v'+str(version)
            self.run(label,self.case(label,version=version),'passed')
        second='local robot=require("robot")\nassert(robot.turnRight())\nassert(robot.turnLeft())\nprint("second program")\n'
        runtime,_=self.run('second-program',self.case('second-program',program=second,
            patch=lambda s:s['robot'].update(energy=12345.5,facing='east')),'passed')
        initial=json.loads((runtime/'observations.ndjson').open(encoding='utf-8').readline())
        assert initial['robot']['energy']==12345.5
        assert initial['robot']['facing']=='east'
        _,error=self.run('lua-error',self.case('lua-error',program='error("intentional acceptance error")\n'),'failed')
        assert error['result']['program']['status']=='error'
        assert 'intentional acceptance error' in error['result']['program']['message']
        _,shutdown=self.run('explicit-shutdown',self.case('explicit-shutdown',program='require("computer").shutdown()\n'),'failed')
        assert shutdown['result']['program']['status']=='not_returned'
        assert shutdown['result']['reason']=='program_not_returned',shutdown['result']
        assert shutdown['result']['robot']['state']=='Stopped',shutdown['result']
        _,overflow=self.run('console-overflow',self.case('console-overflow',
            program='for i=1,20 do print(string.rep("x",65536)) end\n'),'failed')
        assert 'program_console_limit' in overflow['result']['reason'],overflow['result']
        _,assertion=self.run('assertion-failure',self.case('assertion-failure',
            patch=lambda s:s['expect'].update(position=[1,65,0])),'failed')
        assert assertion['result']['program']['status']=='returned'
        assert assertion['result']['reason']=='assertion_failed',assertion['result']
        sleeper='while true do require("computer").pullSignal(1) end\n'
        _,limited=self.run('tick-limit',self.case('tick-limit',program=sleeper,
            patch=lambda s:s['execution'].update(maxTicks=300)),'failed')
        assert 'tick_limit' in limited['result']['reason']
        self.run('cancel-running',self.case('cancel-running',program=sleeper),'cancelled',cancel=True)
        _,shutdown_zero=self.run('shutdown-zero-delay',self.case('shutdown-zero-delay',
            program='require("computer").shutdown()\n',
            patch=lambda s:s['execution'].update(executionDelayMillis=0)),'failed')
        assert shutdown_zero['result']['reason']=='program_not_returned',shutdown_zero['result']
        assert shutdown_zero['result']['robot']['state']=='Stopped',shutdown_zero['result']
        _,sleep_zero=self.run('sleep-zero-delay',self.case('sleep-zero-delay',program=sleeper,
            patch=lambda s:s['execution'].update(executionDelayMillis=0,maxTicks=300)),'failed')
        assert sleep_zero['result']['reason']=='tick_limit',sleep_zero['result']
        # Generate a clean closed saved world by failing before any robot is placed.
        def occupied(s): s['world']['blocks'].append({'min':[0,65,0],'max':[0,65,0],'block':'minecraft:stone'})
        clean,failed=self.run('occupied-setup',self.case('occupied-setup',patch=occupied),'failed')
        assert 'robot_cell_not_air' in failed['result']['reason']
        imported=self.case('copied-world')
        shutil.copytree(clean/'world',imported.parent/'source-world')
        data=json.loads(imported.read_text()); data['world']['source']='source-world'; imported.write_text(json.dumps(data))
        self.run('copied-world',imported,'passed')
        stale=self.case('stale-disk-world',program='require("computer").shutdown()\n',version=2)
        shutil.copytree(clean/'world',stale.parent/'source-world')
        old_disk=stale.parent/'source-world/opencomputers/robot-runner-disk/home'
        old_disk.mkdir(parents=True)
        (old_disk/'runner-outcome').write_text('returned\n')
        (old_disk/'old-user-file.txt').write_text('must remain unchanged')
        data=json.loads(stale.read_text()); data['world']['source']='source-world'; stale.write_text(json.dumps(data))
        _,collision=self.run('stale-disk-world',stale,'failed')
        assert 'runner_disk_collision' in collision['result']['reason'],collision['result']
        def rack(s):
            s['world']['blocks'].append({'min':[1,65,0],'max':[1,65,0],
                                        'block':'opencomputers:rack','properties':{}})
        _,host=self.run('additional-rack',self.case('additional-rack',patch=rack),'failed')
        assert 'additional_loaded_oc_machine' in host['result']['reason'],host['result']
        self.save()
        print(json.dumps({'status':'passed','runs':len(self.rows),'report':str(self.root/'acceptance.json')}))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,help='new short owned directory, outside template')
    parser.add_argument('--java',required=True)
    parser.add_argument('--template',default=str(HERE/'.cache/server'))
    parser.add_argument('--control-jar',default=str(HERE/'build/libs/robot-spike.jar'))
    args=parser.parse_args(); acceptance=Acceptance(args)
    try: acceptance.execute()
    except BaseException:
        acceptance.save()
        # The worker remains the process owner. Request cancellation, never kill metadata PIDs.
        if acceptance.jobs.exists():
            for job in acceptance.jobs.iterdir():
                if job.is_dir() and len(job.name)==32:
                    try:
                        acceptance.cli('cancel',job.name,'--jobs-root',acceptance.jobs)
                        acceptance.cli('wait',job.name,'--jobs-root',acceptance.jobs,'--timeout','15',timeout=20)
                    except (OSError,ValueError,subprocess.TimeoutExpired): pass
        raise


if __name__=='__main__': main()
