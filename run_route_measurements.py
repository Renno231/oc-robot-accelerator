"""Native before/smooth/Theta mode variants with OC CPU/flight evidence."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from build_machine_comparisons import prepare
from supervisor import NO_WINDOW

WORKER=TASK=DISPATCH=None

def communicate():
    if not WORKER: return
    subprocess.run(['cmd.exe','/d','/c','orca','orchestration','send','--from',WORKER,'--type','heartbeat','--subject','alive','--task-id',TASK,'--dispatch-id',DISPATCH,'--phase','verifying'],check=True,creationflags=NO_WINDOW)
    result=subprocess.run(['cmd.exe','/d','/c','orca','orchestration','check','--terminal',WORKER,'--json'],capture_output=True,text=True,check=True,creationflags=NO_WINDOW)
    print(result.stdout,flush=True)
    value=json.loads(result.stdout).get('result',{})
    if value.get('count',0) and not value.get('replayed',False): raise RuntimeError('new coordinator follow-up; pause')

def prepare_variant(case,destination,variant,mode):
    path=prepare(Path('examples/logistics')/case,destination,mode)
    program=destination/'program'
    (program/'route-metrics-enabled').write_text('native per-tick measurement\n')
    for helper in ('planning-metrics.lua','room.lua'): (program/helper).write_bytes((Path('examples/logistics')/helper).read_bytes())
    if variant=='before':
        for part,relative in [('map','lib/map.lua'),('logistics','lib/logistics.lua'),('agent','drone/agent.lua')]:
            (program/relative).write_bytes(Path('.cache/t7-before-'+part+'.lua').read_bytes())
        (program/'testsuite.lua').write_bytes(Path('.cache/t7-before-testsuite.lua').read_bytes())
    else:
        # Benchmark both planners on exactly the geometry used by the job.
        target=program/('room.lua' if 'room' in case else 'testsuite.lua')
        text=target.read_text();needle="local half={x=.375,y=.1875,z=.375,offsetY=.1875}" if 'room' in case else 'local logistics=require("logistics")'
        text=text.replace(needle,"require('planning-metrics')(map)\n  "+needle)
        target.write_text(text)
        lib=program/'lib/logistics.lua';text=lib.read_text()
        call='map.theta(a,b,half,avoid)' if variant=='theta' else 'map.smooth(map.route(a,b,avoid),half,avoid)'
        for expression in ('map.smooth(map.route(a,b,avoid),half,avoid)','map.theta(a,b,half,avoid)'):
            text=text.replace('local names='+expression,'local names='+call)
        assert text.count('local names='+call)==1,'planner variant substitution'
        lib.write_text(text)
    agent=program/'drone/agent.lua'
    # Paired routes must use the same home: Lua hash iteration is unspecified.
    # Measurement-only deterministic fleet order, identical in all variants.
    lib=program/'lib/logistics.lua';text=lib.read_text()
    ordered='for _,d in ipairs((function() local names,out={},{};for n in pairs(fleet) do names[#names+1]=n end;table.sort(names);for _,n in ipairs(names) do out[#out+1]=fleet[n] end;return out end)()) do'
    text=text.replace('for _,d in pairs(fleet) do',ordered,1);lib.write_text(text)
    agent.write_bytes(Path('examples/logistics/flight-metrics-hook.lua').read_bytes()+b'\n'+agent.read_bytes())
    return path

def run(root,installation,jobs,cases,variants,modes):
    root.mkdir(parents=True,exist_ok=True);record=root/'runs.json'
    runs=json.loads(record.read_text()) if record.exists() else []
    for case in cases:
        for variant in variants:
            for mode in modes:
                existing=[r for r in runs if r['case']==case and r['variant']==variant and r['mode']==mode]
                if existing:
                    if existing[-1]['state']!='passed': raise RuntimeError('previous failed variant; use a fresh evidence root')
                    continue
                communicate();destination=root/case/variant/mode
                path=destination/'scenario.json'
                if not path.exists(): path=prepare_variant(case,destination,variant,mode)
                process=subprocess.Popen([sys.executable,'runner.py','run',str(path),'--installation',str(installation),'--jobs-root',str(jobs)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,creationflags=NO_WINDOW)
                while True:
                    try: out,err=process.communicate(timeout=240);break
                    except subprocess.TimeoutExpired: communicate()
                (destination/'native-command.log').write_text(out+'\n'+err)
                state=json.loads(out.strip().splitlines()[-1]);row={k:state[k] for k in ('jobId','state','elapsedWallSeconds')};row.update(case=case,variant=variant,mode=mode)
                runs.append(row);record.write_text(json.dumps(runs,indent=2)+'\n');print(json.dumps(row),flush=True)
                communicate()
                if state['state']!='passed': raise RuntimeError('native route measurement failed '+str(row))
    return runs

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path('.cache/T7-measure'));p.add_argument('--installation',type=Path,default=Path('C:/or/drone-install-T7'));p.add_argument('--jobs-root',type=Path,default=Path('C:/or/drone-jobs'))
    p.add_argument('--cases',nargs='+',default=['storage-room','obstacle-room','steps','split']);p.add_argument('--variants',nargs='+',default=['before','smooth','theta']);p.add_argument('--modes',nargs='+',default=['baseline','coordinated'])
    p.add_argument('--worker');p.add_argument('--task');p.add_argument('--dispatch')
    a=p.parse_args()
    if any((a.worker,a.task,a.dispatch)) and not all((a.worker,a.task,a.dispatch)): p.error('worker/task/dispatch must be supplied together')
    WORKER,TASK,DISPATCH=a.worker,a.task,a.dispatch
    run(a.root,a.installation,a.jobs_root,a.cases,a.variants,a.modes)
