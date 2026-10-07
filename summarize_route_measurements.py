"""Aggregate native route evidence; reject missing coverage or arrival violations."""
import argparse
import csv
import json
import math
from pathlib import Path


def summarize(root, jobs):
    output=[]
    for run in json.loads((root/'runs.json').read_text()):
        assert run['state']=='passed', run
        runtime=jobs/run['jobId']/'runtime'
        result=json.loads((runtime/'result.json').read_text())
        evidence=list(runtime.glob('world/opencomputers/*/home/equivalence.json'))
        assert len(evidence)==1, evidence
        data=json.loads(evidence[0].read_text())
        assert data['returned'], data
        streams={}
        for line in (runtime/'route-observations.ndjson').read_text().splitlines():
            observation=json.loads(line)
            for drone in observation['drones']:
                stream=streams.setdefault(drone['index'], [])
                # Installing the downloaded EEPROM reboots the native machine.
                # Trip uptime belongs to that final agent epoch, not loader boot.
                if stream and drone['uptime']<stream[-1]['uptime']: stream.clear()
                stream.append({**drone,'tick':observation['tick'],'wallNanos':observation['wallNanos']})
        assert all(s[-1]['tick']>=result['ticks'] for s in streams.values()), 'incomplete native coverage'
        row={**run,'ticks':result['ticks'],'elapsedNanos':result['elapsedNanos'],
             'rate':result['ticks']*1e9/result['elapsedNanos'],'planning':data.get('planning'),'trips':[],
             'jobs':data['jobs']}
        if run['case']=='storage-room':
            with (runtime/'observations.ndjson').open() as f: initial=json.loads(f.readline())
            chests=[b for b in initial['blocks'] if b['block']=='minecraft:chest']
            assert len(chests)==64
            assert all(b['properties']['facing']==('south' if b['position'][2]==1 else 'north') for b in chests)
            row['nativeInwardChests']=len(chests)
        for trip in data['flightMetrics']:
            stream=streams[int(trip['drone'][1:])-1]
            start=min(range(len(stream)),key=lambda i:abs(stream[i]['uptime']-trip['start']))
            end=min(range(start,len(stream)),key=lambda i:abs(stream[i]['uptime']-trip['finish']))
            assert abs(stream[start]['uptime']-trip['start'])<=.051
            assert abs(stream[end]['uptime']-trip['finish'])<=.051
            assert abs((stream[end]['tick']-stream[start]['tick'])-trip['seconds']*20)<=2, 'wrong uptime epoch'
            distance=sum(math.dist(stream[i-1]['position'],stream[i]['position']) for i in range(start+1,end+1))
            accesses=[]
            for access in trip['accesses']:
                x,y,z,count,offset,velocity=access
                assert 0<=offset<.02 and 0<=velocity<.02, access
                accesses.append(dict(x=x,y=y,z=z,count=count,offset=offset,velocity=velocity))
            accesses.sort(key=lambda a:(a['x'],a['y'],a['z']))
            row['trips'].append({**trip,'accesses':accesses,'gameTicks':round(trip['seconds']*20),
                'wallSeconds':(stream[end]['wallNanos']-stream[start]['wallNanos'])/1e9,
                'nativeDistance':distance,'energyUsed':stream[end]['energyConsumed']-stream[start]['energyConsumed'],
                'samples':end-start+1})
        row['trips'].sort(key=lambda t:t['trip'])
        assert row['trips'], 'missing flight instrumentation'
        output.append(row)
    return output


def write_tables(data, destination):
    destination.mkdir(parents=True,exist_ok=True)
    (destination/'T7-measurements.json').write_text(json.dumps(data,indent=2)+'\n')
    fields=['case','variant','mode','jobId','trip','drone','wallSeconds','gameTicks','energyUsed','stops','blockedStops','nativeDistance','distance']
    with (destination/'T7-trips.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for run in data:
            for trip in run['trips']: writer.writerow({k:trip.get(k,run.get(k)) for k in fields})
    fields=['case','variant','mode','jobId','trip','drone','x','y','z','count','offset','velocity']
    with (destination/'T7-accesses.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for run in data:
            for trip in run['trips']:
                for access in trip['accesses']:writer.writerow({k:access.get(k,trip.get(k,run.get(k))) for k in fields})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True)
    p.add_argument('--jobs-root',type=Path,default=Path('C:/or/drone-jobs'))
    p.add_argument('--output',type=Path,default=Path('C:/or/drone-jobs'))
    a=p.parse_args();data=summarize(a.root,a.jobs_root);write_tables(data,a.output)
    print('Native runs',len(data),'trips',sum(len(r['trips']) for r in data))
