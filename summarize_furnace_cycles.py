"""Summarize strict native stocks and non-invasive per-tick T10 measurements."""
import argparse
import json
import math
from pathlib import Path


def summarize(root,jobs):
    rows=[]
    for run in json.loads((root/'runs.json').read_text()):
        assert run['state']=='passed',run
        runtime=jobs/run['jobId']/'runtime'
        result=json.loads((runtime/'result.json').read_text())
        evidence=list(runtime.glob('world/opencomputers/*/home/equivalence.json'));assert len(evidence)==1
        data=json.loads(evidence[0].read_text());assert data['returned']
        streams={}
        with (runtime/'route-observations.ndjson').open() as file:
            for line in file:
                observation=json.loads(line)
                for drone in observation['drones']:
                    stream=streams.setdefault(drone['index'],[])
                    if stream and drone['uptime']<stream[-1]['uptime']: stream.clear()
                    stream.append({**drone,'tick':observation['tick']})
        metrics=[]
        for index,stream in sorted(streams.items()):
            assert stream[-1]['tick']>=result['ticks'],'incomplete coverage'
            flying=output_stationary=distance=0.0;stops=commands=0;active=False
            for previous,current in zip(stream,stream[1:]):
                seconds=(current['tick']-previous['tick'])/20
                # The runner exports a final sample again at the completed
                # tick; it contributes no simulated duration.
                assert seconds in (0,.05),'missing native tick'
                distance+=math.dist(previous['position'],current['position'])
                speed=math.sqrt(sum(v*v for v in current['velocity']))
                offset=math.dist(current['position'],current['target'])
                arrived=offset<.02 and speed<.02
                if not arrived: flying+=seconds
                if current['target']!=previous['target']: commands+=1;active=True
                if active and arrived: stops+=1;active=False
                if arrived and any(math.dist(current['position'],p)<.02 for p in ((10.5,63.5,7.5),(10.5,63.5,9.5))):
                    output_stationary+=seconds
            assert not active,'flight remains active'
            assert commands==stops,'commanded flight failed to arrive'
            metrics.append({'index':index,'flightSeconds':flying,'outputFaceStationarySeconds':output_stationary,
                'stops':stops,'distance':distance,'energyConsumed':result['drones'][index]['energyConsumed'],
                'samples':len(stream)})
        warehouse=data['warehouse']
        members=data['files']['/etc/warehouse.cfg']['members']
        catalogue=data['files']['/etc/warehouse.db']
        assert len(members)==64 and all(catalogue[name]['slots']==27 for name in members),'room inventory alias/bounds'
        row={**run,'ticks':result['ticks'],'wholeGameSeconds':result['ticks']/20,'cycle':warehouse,'memory':data.get('warehouseMemory'),
            'drones':metrics,'stops':sum(m['stops'] for m in metrics),'flightSeconds':sum(m['flightSeconds'] for m in metrics),
            'outputFaceStationarySeconds':sum(m['outputFaceStationarySeconds'] for m in metrics),
            'droneEnergyConsumed':sum(m['energyConsumed'] for m in metrics),'finalContainers':result['containers']}
        if run['case']!='concurrent-probe':
            actual={}
            for container in result['containers']:
                for stack in container['slots']:
                    actual[stack['item']]=actual.get(stack['item'],0)+stack['count']
            stock={name:actual.get('minecraft:'+name,0) for name in ('brick','clay_ball','coal')}
            expected={'brick':warehouse['seed']-warehouse['removed'],'clay':0,'coal':4}
            assert {'brick':stock['brick'],'clay':stock['clay_ball'],'coal':stock['coal']}==expected
            assert warehouse['beforeScan']==warehouse['afterScan']==expected,'catalogue/native disagreement'
            assert actual.get('minecraft:iron_ingot')==17 and actual.get('minecraft:stone')==1664,'unrelated stock changed'
            assert all(not drone['inventory'] and drone['running'] for drone in result['drones']),'native drone cargo/state'
            assert all(warehouse['outputs'][name]['read']==load['moved'] for name,load in warehouse['loads'].items())
            # Full outputs are read after the source-derived test sleep, then
            # collected. There is no unproduced remainder for waitingTake to wait
            # for; output-face stationary time still includes native read/drop
            # actions and controller/agent callback latency and is not mislabeled.
            row['smeltingWaitSeconds']=0
            row['trips']=warehouse['trips']
        rows.append(row)
    return rows


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path('.cache/t10-cycles'))
    p.add_argument('--jobs-root',type=Path,default=Path('C:/or/drone-jobs'));p.add_argument('--output',type=Path,default=Path('C:/or/drone-jobs/T10-measurements.json'))
    a=p.parse_args();rows=summarize(a.root,a.jobs_root);a.output.write_text(json.dumps(rows,indent=2)+'\n')
    print(json.dumps([{k:r.get(k) for k in ('case','mode','jobId','wallSeconds','wholeGameSeconds','trips','stops','flightSeconds','outputFaceStationarySeconds','smeltingWaitSeconds','droneEnergyConsumed')} for r in rows],indent=2))
