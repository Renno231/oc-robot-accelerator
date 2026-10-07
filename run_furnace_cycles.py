"""Bounded native T10 matrix, with durable results and cooperative liveness."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from build_machine_comparisons import prepare
from compare_machine_jobs import compare, read_job
from supervisor import NO_WINDOW
from run_machine_comparisons import communicate
import run_machine_comparisons as orchestration

spec=importlib.util.spec_from_file_location('furnace_generator',Path('examples/warehouse/build_furnace_cycle.py'))
generator=importlib.util.module_from_spec(spec);spec.loader.exec_module(generator)


def verified_stock_scan(job,evidence):
    """A completed scan may be evicted in different two-drone finish order.

    Accept only a whole missing finished stock-read record whose contents and
    free-slot count exactly match that side's still-strict final catalogue.
    Machine reads, transfer states, partials and changed read bodies stay strict.
    """
    if not isinstance(job,dict) or job.get('state')!='done' or job.get('remaining')!=0 or job.get('requested')!=0 or job.get('moved')!=0 or job.get('trips')!=1 or job.get('held'):
        return False
    steps=job.get('steps',[])
    if len(steps)!=1 or not steps[0].get('read') or steps[0].get('size')!=27: return False
    step=steps[0];read=step['read'];match=re.fullmatch(r'([0-7]):(65|66|67|68):2',read.get('node',''))
    if not match or read.get('side') not in (2,3) or 'listing' not in step: return False
    name='s'+match[1]+'_'+str(int(match[2])-65)+'_'+('N' if read['side']==2 else 'S')
    entry=evidence.get('files',{}).get('/etc/warehouse.db',{}).get(name)
    if not entry or entry.get('slots')!=27: return False
    listing=step['listing'];stacks=list(listing.values()) if isinstance(listing,dict) else listing
    if not isinstance(stacks,list) or entry.get('freeSlots')!=27-len(stacks): return False
    actual={}
    for stack in stacks:
        key=(stack['name'],stack.get('damage',0),stack.get('label'))
        count,maximum=actual.get(key,(0,stack['maxSize']))
        if maximum!=stack['maxSize']: return False
        actual[key]=(count+stack['size'],maximum)
    contents=entry.get('items',{});values=contents.values() if isinstance(contents,dict) else contents
    # Catalogue keeps learned identities at count zero; they are not physical
    # stacks. Their metadata still remains strict in the overall comparison.
    expected={(v['item']['name'],v['item'].get('damage',0),v['item'].get('label')):(v['count'],v['maxSize']) for v in values if v['count']>0}
    return actual==expected


def compare_cycle_jobs(jobs,a,b):
    comparison=compare(jobs,a,b)
    _,_,ea=read_job(jobs,a);_,_,eb=read_job(jobs,b)
    wa,wb=ea['warehouse'],eb['warehouse']
    counters_equal=all(wa.get(k)==wb.get(k) for k in ('doneJobs','partialJobs','trips','beforeScan','afterScan'))
    retained_equal=len(ea['jobs'])==len(eb['jobs'])==32
    retention=[];unexpected=[]
    for difference in comparison['unexpectedDifferences']:
        missing=re.fullmatch(r'\$\.evidence\.jobs\.\d+',difference['path'])
        a_missing,b_missing=difference['a'] is None,difference['b'] is None
        present=difference['b'] if a_missing else difference['a'];evidence=eb if a_missing else ea
        if counters_equal and retained_equal and missing and a_missing!=b_missing and verified_stock_scan(present,evidence): retention.append(difference)
        else: unexpected.append(difference)
    comparison['retentionDifferences']=retention;comparison['unexpectedDifferences']=unexpected
    return comparison


def run(root, installation, jobs, cases):
    root.mkdir(parents=True,exist_ok=True)
    record=root/'runs.json';rows=json.loads(record.read_text()) if record.exists() else []
    configs={'128':(128,False,1),'100':(100,False,1),'shortfall':(128,True,1),'ram2':(128,False,2),'concurrent-probe':(128,False,1)}
    for case,mode in cases:
        prior=next((r for r in rows if r['case']==case and r['mode']==mode),None)
        if prior:
            if prior['state']!='passed': raise RuntimeError('existing failed attempt requires an explicit fresh retry root')
            continue
        communicate()
        source=root/'sources'/case
        if not source.exists():
            generator.build(source,*configs[case])
            if case=='concurrent-probe':
                config=source/'program/cycle-config.lua';config.write_text('return {seed=128,concurrentProbe=true}\n')
                path=source/'scenario.json';value=json.loads(path.read_text());value['expect']['containers']=[];path.write_text(json.dumps(value,indent=2)+'\n')
        destination=root/'fixtures'/case/mode
        path=destination/'scenario.json'
        if not path.exists(): path=prepare(source,destination,mode)
        process=subprocess.Popen([sys.executable,'runner.py','run',str(path),'--installation',str(installation),'--jobs-root',str(jobs)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,creationflags=NO_WINDOW)
        while True:
            try: stdout,stderr=process.communicate(timeout=240);break
            except subprocess.TimeoutExpired: communicate()
        (destination/'native-command.log').write_text(stdout+'\n'+stderr)
        state=json.loads(stdout.strip().splitlines()[-1])
        row={'case':case,'mode':mode,'jobId':state['jobId'],'state':state['state'],'wallSeconds':state['elapsedWallSeconds'],'commandExit':process.returncode}
        rows.append(row);record.write_text(json.dumps(rows,indent=2)+'\n');print(json.dumps(row),flush=True)
        communicate()
        if row['state']!='passed': raise RuntimeError('furnace acceptance failed: '+str(row))
    comparisons=[]
    for case in configs:
        ids={r['mode']:r['jobId'] for r in rows if r['case']==case}
        if 'baseline' in ids and 'coordinated' in ids:
            comparison=compare_cycle_jobs(jobs,ids['baseline'],ids['coordinated']);comparison['case']=case;comparisons.append(comparison)
    (root/'comparisons.json').write_text(json.dumps(comparisons,indent=2)+'\n')
    if any(r['unexpectedDifferences'] for r in comparisons): raise RuntimeError('native mode comparison differs')
    return rows


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path('.cache/t10-cycles'))
    p.add_argument('--installation',type=Path,default=Path('C:/or/drone-install-T10'));p.add_argument('--jobs-root',type=Path,default=Path('C:/or/drone-jobs'))
    p.add_argument('--worker');p.add_argument('--task');p.add_argument('--dispatch');p.add_argument('--coordinated-only',action='store_true')
    a=p.parse_args()
    if any((a.worker,a.task,a.dispatch)) and not all((a.worker,a.task,a.dispatch)): p.error('all lifecycle identities required')
    orchestration.WORKER,orchestration.TASK,orchestration.DISPATCH=a.worker,a.task,a.dispatch
    cases=[(case,'coordinated') for case in ('concurrent-probe','128','100','shortfall','ram2')]
    if not a.coordinated_only: cases += [(case,'baseline') for case in ('128','100','shortfall')]
    run(a.root,a.installation,a.jobs_root,cases)
