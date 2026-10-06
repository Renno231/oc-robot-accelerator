"""Opt-in native two-process probe. Does not weaken ordinary job acceptance."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import time
from supervisor import NO_WINDOW


OUTPUTS=('result.json','result.json.tmp','observations.ndjson','observations-status.json','program.log','second-program.log','runtime-logging.json')


def command_for(template,root,phase):
    command=[v for v in template if not v.startswith('-Drobotspike.root=')]
    command[1:1]=['-Drobotspike.root='+str(root.resolve()),'-Drobotspike.reloadProbe='+phase]
    return command


def run(template,root,jar):
    template=Path(template);root=Path(root)
    if root.exists(): raise FileExistsError(root)
    excluded=set(OUTPUTS)|{'world','logs','supervisor.json','stderr.log','stdout.log','program-inputs.json','second-program-inputs.json'}
    shutil.copytree(template,root,ignore=lambda directory,names:[n for n in names if Path(directory)==template and n in excluded])
    shutil.copyfile(jar,root/'mods/robot-spike.jar')
    entry=root/'program/main.lua';entry.write_text(Path(__file__).with_name('machine_evidence.lua').read_text())
    original=json.loads((template/'supervisor.json').read_text())['command']
    phases=[]
    for phase in ('capture','resume'):
        before=time.monotonic()
        with (root/(phase+'-stdout.log')).open('wb') as output:
            process=subprocess.Popen(command_for(original,root,phase),cwd=root,stdout=output,stderr=subprocess.STDOUT,creationflags=NO_WINDOW)
            try: code=process.wait(timeout=180)
            except BaseException:
                process.kill();process.wait();raise
        result=json.loads((root/'result.json').read_text())
        phases.append({'phase':phase,'pid':process.pid,'exitCode':code,'wallSeconds':time.monotonic()-before,'result':result})
        if code!=0: raise RuntimeError('native process failed '+phase)
        if phase=='capture':
            if result['reason']!='reload_saved': raise RuntimeError('cargo save did not occur: '+result['reason'])
            destination=root/'phase-a';destination.mkdir()
            for name in OUTPUTS:
                path=root/name
                if path.exists(): path.rename(destination/name)
        elif result['status']!='passed': raise RuntimeError('native reload did not finish: '+result['reason'])
    evidence=list((root/'world/opencomputers').glob('*/home/equivalence.json'))
    if len(evidence)!=1: raise RuntimeError('reload evidence missing')
    final=json.loads(evidence[0].read_text())
    if final.get('programStarts')!=1 or final.get('reloadPending')!=1: raise RuntimeError('Lua/signal did not survive')
    data={'phases':phases,'saved':json.loads((root/'reload-state.json').read_text()),'evidence':final}
    (root/'reload-verification.json').write_text(json.dumps(data,indent=2)+'\n')
    return data


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('template',type=Path);p.add_argument('root',type=Path);p.add_argument('--jar',type=Path,default=Path('build/libs/robot-spike.jar'))
    a=p.parse_args();value=run(a.template,a.root,a.jar);print(json.dumps({'root':str(a.root),'phases':[{k:v for k,v in x.items() if k!='result'} for x in value['phases']]}))
