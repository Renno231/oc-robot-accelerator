"""Release-package acceptance in a fresh owned root; no source imports or caches."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import zipfile

p=argparse.ArgumentParser();p.add_argument('--archive',required=True);p.add_argument('--root',required=True);p.add_argument('--java',required=True)
a=p.parse_args();archive=Path(a.archive).resolve();root=Path(a.root).resolve();root.mkdir(exist_ok=False)
package=root/'package';package.mkdir();commands=[]
sha=lambda b:hashlib.sha256(b).hexdigest()
with zipfile.ZipFile(archive) as z:
    release=json.loads(z.read('release.json'))
    assert set(z.namelist())==set(release['files'])|{'release.json'}
    for name,item in release['files'].items():
        assert not name.startswith('/') and ':' not in name and '\\' not in name and all(x not in ('','..','.') for x in name.split('/'))
        data=z.read(name);assert item=={'size':len(data),'sha256':sha(data)}
    z.extractall(package)
assert archive.with_suffix('.zip.sha256').read_text().split()[0]==sha(archive.read_bytes())
env=dict(os.environ,PYTHONPATH='',ROBOT_RUNNER_PYTHON=sys.executable)
launcher=['cmd.exe','/d','/c','call',str(package/'robot-runner.cmd')] if os.name=='nt' else ['sh',str(package/'robot-runner')]
installation=root/'install';jobs=root/'jobs';scenario=root/'scenario';job=None

def run(args,expected=0,timeout=60):
    start=time.monotonic()
    r=subprocess.run(launcher+args,cwd=root,env=env,capture_output=True,text=True,timeout=timeout,
                     creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    item={'command':launcher+args,'cwd':str(root),'exitCode':r.returncode,'elapsedSeconds':time.monotonic()-start,'stdout':r.stdout,'stderr':r.stderr}
    commands.append(item);(root/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
    assert r.returncode==expected,item
    return json.loads(r.stdout)

result={'platform':platform.platform(),'python':sys.version,'archiveSha256':sha(archive.read_bytes()),'controlJar':release['controlJar'],'root':str(root),'status':'running'}
(root/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
try:
    assert run(['doctor','--installation',str(installation)],1)['status']=='absent'
    assert not installation.exists()
    setup=run(['setup','--installation',str(installation),'--java',a.java,'--accept-eula','--timeout','900'],timeout=940)
    assert setup['status']=='ready',setup
    assert json.loads((installation/'installation.json').read_text())['origin']=='package'
    assert run(['doctor','--installation',str(installation)])['status']=='ready'
    assert run(['init',str(scenario)])['status']=='created'
    validated=run(['validate',str(scenario/'scenario.json')])['scenario']
    assert validated['schemaVersion']==3 and validated['execution']['mode']=='coordinated'
    assert validated['execution']['executionDelayMillis']==12
    assert validated['robot']['hardware']['storage']==['hdd3']
    finished=run(['run',str(scenario/'scenario.json'),'--installation',str(installation),'--jobs-root',str(jobs)],timeout=660)
    assert finished['state']=='passed',finished
    job=finished['jobId'];directory=jobs/job
    game=json.loads((directory/'runtime/result.json').read_text());sup=json.loads((directory/'runtime/supervisor.json').read_text())
    assert game['status']=='passed' and game['program']['status']=='returned' and sup['cleanup_ok']
    assert game['runnerTiming']['workerScheduling']=='idle-compression'
    assert game['runnerTiming']['skippedIdleNanos']>0
    assert (directory/'inputs/hardware-preset.json').is_file()
    assert not (jobs/'.owner').exists()
    assert run(['doctor','--installation',str(installation)])['status']=='ready'
    observed=run(['observations',job,'--jobs-root',str(jobs)])
    run(['view',job,'--jobs-root',str(jobs),'--output',str(root/'replay.html')])
    run(['inspect',job,'--jobs-root',str(jobs)])
    run(['diagnostics',job,'--jobs-root',str(jobs),'--output',str(root/'diagnostics.zip'),'--include-observations'])
    # Preserve bounded runtime records and generated user output before public cleanup.
    names=['job.json','launch.json','runtime/result.json','runtime/supervisor.json','runtime/runtime-logging.json','runtime/observations.ndjson','runtime/observations-status.json','runtime/program.log','runtime/stdout.log','runtime/stderr.log']
    for path in directory.rglob('report.txt'):
        if path.is_file(): names.append(path.relative_to(directory).as_posix())
    entries={}
    with zipfile.ZipFile(root/'job-evidence.zip','x',zipfile.ZIP_DEFLATED) as z:
        for name in names:
            path=directory/name
            if path.is_file():
                data=path.read_bytes();assert len(data)<=32*1024*1024
                entries[name]={'size':len(data),'sha256':sha(data)};z.writestr(name,data)
    (root/'job-evidence.json').write_text(json.dumps(entries,indent=2)+'\n')
    before=sha((installation/'installation.json').read_bytes())
    cleaned=run(['cleanup',job,'--jobs-root',str(jobs),'--confirm-delete-runtime'])
    assert not (directory/'runtime').exists() and (directory/'inputs').is_dir()
    assert sha((installation/'installation.json').read_bytes())==before
    assert run(['doctor','--installation',str(installation)])['status']=='ready'
    result.update(status='passed',jobId=job,game=game,supervisor=sup,observations=observed,cleanup=cleaned,commandCount=len(commands),installationOrigin='package',sourceCachesUsed=False)
except BaseException as exc:
    result.update(status='failed',error=repr(exc),jobId=job)
    raise
finally:
    (root/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'status':result['status'],'root':str(root),'jobId':job,'commands':len(commands)}))
