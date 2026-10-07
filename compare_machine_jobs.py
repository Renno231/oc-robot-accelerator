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
        native['warehouseMemory']=native['evidence'].pop('warehouseMemory',None)
        native['warehousePerformance']=native['evidence'].pop('warehousePerformance',None)
    return native


def compare(root,a,b,reference_root=None):
    sa,ra,ea=read_job(reference_root or root,a);sb,rb,eb=read_job(root,b)
    if ra['scenarioId']!=rb['scenarioId']: raise ValueError('different scenarios')
    if ('computer' in ra and ea is None) or ('computer' in rb and eb is None): raise ValueError('missing native Lua evidence')
    ca=comparable(sa,ra,ea);cb=comparable(sb,rb,eb)
    measured={k:{'a':ca.pop(k,None),'b':cb.pop(k,None)} for k in ('blockedReports','boots','warehouseMemory','warehousePerformance')}
    # UI memory/CPU/draw totals vary with native event delivery; acceptance
    # booleans, session count, config, catalogue and physical jobs remain strict.
    measured['warehouseUI']={}
    for side,c in (('a',ca),('b',cb)):
        e=c.get('evidence',{})
        measured['warehouseUI'][side]={'planningCPU':{}}
        for variant,operations in e.get('warehouseUIPlanning',{}).items():
            measured['warehouseUI'][side]['planningCPU'][variant]={}
            for kind,stats in operations.items():
                measured['warehouseUI'][side]['planningCPU'][variant][kind]=stats.pop('cpuSeconds',None)
        ui=e.get('warehouseUI',{})
        for k in ('memory','renders','writes'):
            measured['warehouseUI'][side][k]=ui.pop(k,None)
    differences=diff(ca,cb)
    # os.time is native world time (OC OSAPI.scala:65-76). Retain raw file
    # differences, but classify timestamp-only changes only if node order agrees.
    allowed=set()
    fa=ca.get('evidence',{}).get('files',{})
    fb=cb.get('evidence',{}).get('files',{})
    # An empty Lua table exports as []: drone-only cases have no config files.
    # Keep its raw shape in differences; use an empty map only for leaf lookup.
    fa=fa if isinstance(fa,dict) else {}
    fb=fb if isinstance(fb,dict) else {}
    ma=fa.get('/etc/map.cfg',{}).get('nodes',{}) if isinstance(fa,dict) else {}
    mb=fb.get('/etc/map.cfg',{}).get('nodes',{}) if isinstance(fb,dict) else {}
    if isinstance(ma,dict) and isinstance(mb,dict) and ma.keys()==mb.keys():
        if sorted(ma,key=lambda k:(ma[k].get('created',0),k))==sorted(mb,key=lambda k:(mb[k].get('created',0),k)):
            allowed={'$.evidence.files./etc/map.cfg.nodes.'+k+'.created' for k in ma}
    # Catalogue observation uptime is a measurement, not item/capacity state.
    # All warehouse accounting, routes, group configuration and reboot results
    # remain strict; only the exact named timestamp leaf is classified.
    for prefix,wa,wb in (
            ('$.evidence.files./etc/warehouse.db.',fa.get('/etc/warehouse.db',{}),fb.get('/etc/warehouse.db',{})),
            ('$.evidence.warehouse.catalogue.',ca.get('evidence',{}).get('warehouse',{}).get('catalogue',{}),cb.get('evidence',{}).get('warehouse',{}).get('catalogue',{}))):
        if isinstance(wa,dict) and isinstance(wb,dict) and wa.keys()==wb.keys():
            allowed.update(prefix+k+'.time' for k in wa)
    # Furnace acceptance exports its controller uptime duration explicitly.
    # Inventory totals, load outcomes, shortage and job counts stay strict.
    if ra['scenarioId']=='warehouse-furnace-cycle':
        allowed.add('$.evidence.warehouse.gameSeconds')
    measured['bootIntervals']={}
    for side in ('a','b'):
        previous={};intervals={}
        for boot in measured['boots'][side] or []:
            sender=boot['sender']
            if sender in previous: intervals.setdefault(sender,[]).append(boot['time']-previous[sender])
            previous[sender]=boot['time']
        measured['bootIntervals'][side]=intervals
    out={'a':a,'b':b,'scenario':ra['scenarioId'],'differences':differences,
            'unexpectedDifferences':[d for d in differences if d['path'] not in allowed],
            'clockFileDifferences':[d for d in differences if d['path'] in allowed],'measurements':measured,
            'ticks':{'a':ra['ticks'],'b':rb['ticks'],'delta':rb['ticks']-ra['ticks']},
            'wallSeconds':{'a':sa['elapsedWallSeconds'],'b':sb['elapsedWallSeconds']},
            'energy':{'a':[d['energy'] for d in ra.get('drones',[])]+[ra[k]['energy'] for k in ('computer','secondComputer') if k in ra],
                      'b':[d['energy'] for d in rb.get('drones',[])]+[rb[k]['energy'] for k in ('computer','secondComputer') if k in rb]}}
    if reference_root is not None: out.update(aRoot=str(reference_root),bRoot=str(root))
    return out


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('a');p.add_argument('b');p.add_argument('--jobs-root',type=Path,default=Path('C:/or/drone-jobs'))
    p.add_argument('--reference-root',type=Path,help='optional separate jobs root holding the reference job')
    args=p.parse_args();value=compare(args.jobs_root,args.a,args.b,args.reference_root);print(json.dumps(value,indent=2));raise SystemExit(bool(value['unexpectedDifferences']))
