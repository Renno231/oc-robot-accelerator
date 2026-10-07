"""Sequential native acceptance sweep with durable progress and Orca liveness."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from build_machine_comparisons import prepare
from compare_machine_jobs import compare
from supervisor import NO_WINDOW

WORKER=TASK=DISPATCH=None
FAMILIES=('logistics','mapping','drones','warehouse')
CASES=None
VARIANTS=('baseline1','baseline2','coordinated')

def scenario_paths():
    return sorted(p for family in FAMILIES for p in (Path('examples')/family).glob('*/scenario.json') if not CASES or p.parent.name in CASES)


def communicate():
    if not WORKER: return
    heartbeat=['send','--from',WORKER,'--type','heartbeat','--subject','alive','--task-id',TASK,'--dispatch-id',DISPATCH,'--phase','verifying']
    subprocess.run(['cmd.exe','/d','/c','orca','orchestration',*heartbeat],check=True,creationflags=NO_WINDOW)
    check=subprocess.run(['cmd.exe','/d','/c','orca','orchestration','check','--terminal',WORKER,'--json'],capture_output=True,text=True,check=True,creationflags=NO_WINDOW)
    value=json.loads(check.stdout)
    if value.get('result',{}).get('count',0) and not value.get('result',{}).get('replayed',False):
        print(check.stdout,flush=True);raise RuntimeError('coordinator follow-up: pause sweep')


def run(root,installation,jobs):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    record=root/'runs.json';runs=json.loads(record.read_text()) if record.exists() else []
    sources=scenario_paths()
    if not sources or (CASES and not set(CASES).issubset({p.parent.name for p in sources})):
        raise ValueError('no scenarios or unknown case selected')
    for scenario in sources:
        label=str(scenario.parent).replace('\\','/')
        for variant in VARIANTS:
            if any(r['scenario']==label and r['variant']==variant for r in runs): continue
            communicate()
            mode='baseline' if variant.startswith('baseline') else 'coordinated'
            destination=root/'fixtures'/scenario.parent.relative_to('examples')/variant
            path=destination/'scenario.json'
            if not path.exists(): path=prepare(scenario.parent,destination,mode)
            command=[sys.executable,'runner.py','run',str(path),'--installation',str(installation),'--jobs-root',str(jobs)]
            process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,creationflags=NO_WINDOW)
            while True:
                try: stdout,stderr=process.communicate(timeout=240);break
                except subprocess.TimeoutExpired:
                    communicate()
            (destination/'native-command.log').write_text(stdout+'\n'+stderr)
            state=json.loads(stdout.strip().splitlines()[-1])
            row={'scenario':label,'variant':variant,'jobId':state['jobId'],'state':state['state'],'wallSeconds':state['elapsedWallSeconds'],'commandExit':process.returncode}
            runs.append(row);record.write_text(json.dumps(runs,indent=2)+'\n');print(json.dumps(row),flush=True)
            communicate()
    comparisons=[]
    for scenario in sources:
        label=str(scenario.parent).replace('\\','/')
        ids={r['variant']:r['jobId'] for r in runs if r['scenario']==label}
        entry={'scenario':label}
        if 'baseline1' in ids and 'baseline2' in ids: entry['natural']=compare(jobs,ids['baseline1'],ids['baseline2'])
        if 'baseline1' in ids and 'coordinated' in ids: entry['accelerated']=compare(jobs,ids['baseline1'],ids['coordinated'])
        comparisons.append(entry)
    (root/'comparisons.json').write_text(json.dumps(comparisons,indent=2)+'\n')
    return comparisons


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path('.cache/T6-final'));p.add_argument('--installation',type=Path,default=Path('C:/or/drone-install-T6'));p.add_argument('--jobs-root',type=Path,default=Path('C:/or/drone-jobs'))
    p.add_argument('--worker',default=WORKER);p.add_argument('--task',default=TASK);p.add_argument('--dispatch',default=DISPATCH)
    p.add_argument('--families',nargs='+',choices=FAMILIES,default=FAMILIES)
    p.add_argument('--cases',nargs='+',help='restrict to named scenario directories within the selected families')
    p.add_argument('--variants',nargs='+',choices=VARIANTS,default=VARIANTS)
    a=p.parse_args()
    if any((a.worker,a.task,a.dispatch)) and not all((a.worker,a.task,a.dispatch)): p.error('worker/task/dispatch must be supplied together')
    WORKER,TASK,DISPATCH=a.worker,a.task,a.dispatch;FAMILIES=a.families;CASES=a.cases;VARIANTS=a.variants;values=run(a.root,a.installation,a.jobs_root)
    runs=json.loads((a.root/'runs.json').read_text())
    bad_status=any(r['state']!=('failed' if r['scenario']=='examples/drones/error' else 'passed') for r in runs)
    raise SystemExit(bad_status or any(v[k]['unexpectedDifferences'] for v in values for k in ('natural','accelerated') if k in v))
