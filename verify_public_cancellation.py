"""Cancel a real profile-verified, initialized server, not only its launch process."""
import argparse
import json
import time
from types import SimpleNamespace

import runner_jobs
import runtime_profile
from verify_runner import Acceptance, HERE, hashes


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True);parser.add_argument('--java',required=True)
    args=parser.parse_args()
    test=Acceptance(SimpleNamespace(output=args.output,java=args.java,
                    template=HERE/'.cache/server',control_jar=HERE/'build/libs/robot-spike.jar'))
    manifest=test.case('profile-cancellation',mode='baseline',program='while true do os.sleep(1) end',
                       version=2)
    before=hashes(manifest.parent); jobid=None; commands=[]
    try:
        code,status,command=test.cli('run',manifest,'--jobs-root',test.jobs,'--java',args.java,'--detach')
        commands.append(command);assert code==0,status;jobid=status['jobId']
        runtime=test.jobs/jobid/'runtime';until=time.monotonic()+60
        while True:
            if (runtime/'runtime-logging.json').exists() and (runtime/'observations.ndjson').exists():
                proof=runtime_profile.verify_proof(runtime)
                if (runtime/'observations.ndjson').stat().st_size>0:break
            current=runner_jobs.status(test.jobs,jobid)
            assert current['state'] not in runner_jobs.TERMINAL,current
            if time.monotonic()>=until:raise TimeoutError('profile initialization not observed')
            time.sleep(.05)
        initialized=time.time()
        code,cancelled,command=test.cli('cancel',jobid,'--jobs-root',test.jobs);commands.append(command)
        code,finished,command=test.cli('wait',jobid,'--jobs-root',test.jobs,'--timeout','30',timeout=40);commands.append(command)
        report=json.loads((runtime/'supervisor.json').read_text())
        record={'label':'profile-cancellation','jobId':jobid,'commands':commands,'initializedBeforeCancellation':initialized,
                'loggingProof':proof,'status':finished,'supervisor':report,'inputUnchanged':before==hashes(manifest.parent)}
        (test.root/'acceptance.json').write_text(json.dumps(record,indent=2)+'\n')
        assert code!=0 and finished['state']=='cancelled',finished
        assert report['cancelled'] and report['cleanup_ok'],report
        assert report['runtimeProfile']==runtime_profile.PROFILE_ID
        assert record['inputUnchanged'] and not (test.jobs/'.owner').exists()
        print(json.dumps({'status':'passed','jobId':jobid,'report':str(test.root/'acceptance.json')}))
    finally:
        if jobid is not None and runner_jobs.status(test.jobs,jobid)['state'] not in runner_jobs.TERMINAL:
            runner_jobs.cancel(test.jobs,jobid)
            runner_jobs.wait(test.jobs,jobid,30)


if __name__=='__main__':main()
