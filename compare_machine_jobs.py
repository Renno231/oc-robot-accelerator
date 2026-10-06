"""Compare native acceptance outcomes from two job IDs, not expected fixture values."""
import argparse
import json
from pathlib import Path

def additional_files(runtime):
    """Read non-serialized mapping files from each real, identifiable case HDD."""
    out={}
    for host,source in (('computer','program'),('secondComputer','second-program')):
        entry=runtime/source/'main.lua'
        if not entry.is_file(): continue
        drives=[p.parent.parent.parent for p in (runtime/'world/opencomputers').glob('*/home/program/main.lua') if p.read_bytes()==entry.read_bytes()]
        if len(drives)!=1: raise ValueError('ambiguous or absent native program disk: '+host)
        for name in ('etc/mapd.cfg','etc/mapclient.cfg','home/ui-input.txt'):
            path=drives[0]/name
            if path.is_file(): out[host+'/'+name]=path.read_text()
    return out


def read_job(root,job):
    directory=Path(root)/job
    state=json.loads((directory/'job.json').read_text())
    result=json.loads((directory/'runtime/result.json').read_text())
    result['additionalProgramFiles']=additional_files(directory/'runtime')
    files=list((directory/'runtime/world/opencomputers').glob('*/home/equivalence.json'))
    evidence=json.loads(files[0].read_text()) if files else None
    if len(files)>1: raise ValueError('ambiguous evidence disks')
    return state,result,evidence


def identities(evidence):
    out={}
    if evidence:
        files=evidence['files']
        registry=files.get('/etc/logistics.drones',{}) if isinstance(files,dict) else {}
        for name,d in (registry.items() if isinstance(registry,dict) else []):
            out[d['address']]='address:'+name
            out[d['token']]='token:'+name
    return out


def normalize(value,replacements):
    if isinstance(value,dict): return {normalize(k,replacements):normalize(v,replacements) for k,v in value.items()}
    if isinstance(value,list): return [normalize(v,replacements) for v in value]
    if isinstance(value,str): return replacements.get(value,value)
    return value


def diff(a,b,path='$'):
    if type(a)!=type(b): return [{'path':path,'a':a,'b':b}]
    if isinstance(a,dict):
        out=[]
        for key in sorted(a.keys()|b.keys()):
            if key not in a or key not in b: out.append({'path':path+'.'+key,'a':a.get(key),'b':b.get(key)})
            else: out+=diff(a[key],b[key],path+'.'+key)
        return out
    if isinstance(a,list):
        if len(a)!=len(b): return [{'path':path,'a':a,'b':b}]
        return sum((diff(x,y,path+'['+str(i)+']') for i,(x,y) in enumerate(zip(a,b))),[])
    return [] if a==b else [{'path':path,'a':a,'b':b}]


def comparable(state,result,evidence):
    native={k:result.get(k) for k in ('status','reason','program','containers','additionalProgramFiles')}
    native['jobState']=state['state']
    native['drones']=[{k:d.get(k) for k in ('index','blockPosition','inventory','lastError','observedError','running')} for d in result.get('drones',[])]
    if evidence:
        evidence=normalize(evidence,identities(evidence))
        # Blocked offset/speed/time are measured separately, never cargo accounting.
        native['blockedReports']={}
        for id,job in (evidence['jobs'].items() if isinstance(evidence['jobs'],dict) else []):
            native['blockedReports'][id]=job.pop('blockedReports',None)
        native['evidence']=evidence
        native['boots']=native['evidence'].pop('boots')
    return native


def compare(root,a,b):
    sa,ra,ea=read_job(root,a);sb,rb,eb=read_job(root,b)
    if ra['scenarioId']!=rb['scenarioId']: raise ValueError('different scenarios')
    if ('computer' in ra and ea is None) or ('computer' in rb and eb is None): raise ValueError('missing native Lua evidence')
    ca=comparable(sa,ra,ea);cb=comparable(sb,rb,eb)
    measured={k:{'a':ca.pop(k,None),'b':cb.pop(k,None)} for k in ('blockedReports','boots')}
    differences=diff(ca,cb)
    # os.time is native world time (OC OSAPI.scala:65-76). Retain raw file
    # differences, but classify timestamp-only changes only if node order agrees.
    allowed=set()
    fa=ca.get('evidence',{}).get('files',{})
    fb=cb.get('evidence',{}).get('files',{})
    ma=fa.get('/etc/map.cfg',{}).get('nodes',{}) if isinstance(fa,dict) else {}
    mb=fb.get('/etc/map.cfg',{}).get('nodes',{}) if isinstance(fb,dict) else {}
    if isinstance(ma,dict) and isinstance(mb,dict) and ma.keys()==mb.keys():
        if sorted(ma,key=lambda k:(ma[k].get('created',0),k))==sorted(mb,key=lambda k:(mb[k].get('created',0),k)):
            allowed={'$.evidence.files./etc/map.cfg.nodes.'+k+'.created' for k in ma}
    measured['bootIntervals']={}
    for side in ('a','b'):
        previous={};intervals={}
        for boot in measured['boots'][side] or []:
            sender=boot['sender']
            if sender in previous: intervals.setdefault(sender,[]).append(boot['time']-previous[sender])
            previous[sender]=boot['time']
        measured['bootIntervals'][side]=intervals
    return {'a':a,'b':b,'scenario':ra['scenarioId'],'differences':differences,
            'unexpectedDifferences':[d for d in differences if d['path'] not in allowed],
            'clockFileDifferences':[d for d in differences if d['path'] in allowed],'measurements':measured,
            'ticks':{'a':ra['ticks'],'b':rb['ticks'],'delta':rb['ticks']-ra['ticks']},
            'wallSeconds':{'a':sa['elapsedWallSeconds'],'b':sb['elapsedWallSeconds']},
            'energy':{'a':[d['energy'] for d in ra.get('drones',[])]+[ra[k]['energy'] for k in ('computer','secondComputer') if k in ra],
                      'b':[d['energy'] for d in rb.get('drones',[])]+[rb[k]['energy'] for k in ('computer','secondComputer') if k in rb]}}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('a');p.add_argument('b');p.add_argument('--jobs-root',type=Path,default=Path('C:/or/drone-jobs'))
    args=p.parse_args();value=compare(args.jobs_root,args.a,args.b);print(json.dumps(value,indent=2));raise SystemExit(bool(value['unexpectedDifferences']))
