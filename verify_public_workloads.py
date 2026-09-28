"""Opt-in, serialized real-engine public workloads; retain all original outcomes."""
import argparse
import copy
from decimal import Decimal
import json
import shutil
from types import SimpleNamespace

import runner_observations
import runtime_profile
from verify_runner import Acceptance, HERE

JOURNAL = '''local robot=require("robot")
local computer=require("computer")
local journal=assert(io.open("actions.tsv","w"))
local function record(name,...)
  local values={name}
  for i=1,select("#",...) do values[#values+1]=tostring(select(i,...)) end
  values[#values+1]=tostring(computer.uptime())
  values[#values+1]=tostring(computer.energy())
  journal:write(table.concat(values,"\\t"),"\\n"); journal:flush()
end
'''


def base(mode):
    spec=json.loads((HERE/'examples/mining/scenario.json').read_text())
    spec['schemaVersion']=2
    spec['robot']['hardware']='tier3'  # Explicit historical profile, independent of current init.
    spec['execution'].update(mode=mode,maxTicks=10000,timeoutSeconds=180)
    spec['observations']={'everyTicks':10,'maxBytes':33554432,'onFull':'stop'}
    spec['world']['blocks']=spec['world']['blocks'][:2]
    spec['expect']={'position':[0,65,0]}
    return spec


def block(spec,low,high,name):
    spec['world']['blocks'].append({'min':low,'max':high,'block':'minecraft:'+name})


def cases():
    result=[]
    for mode in ('baseline','coordinated'):
        spec=json.loads((HERE/'examples/cross-chunk/scenario.json').read_text())
        spec['schemaVersion']=2; spec['robot']['hardware']='tier3'
        spec['execution']['mode']=mode
        result.append(('cross-chunk-'+mode,spec,None,'passed'))
        spec=base(mode)
        block(spec,[0,65,-1],[0,65,-1],'bedrock')
        spec['expect']['blocks']=[{'position':[0,65,-1],'block':'minecraft:bedrock'}]
        program=JOURNAL+'''record("detect",robot.detect())
record("swing",robot.swing())
record("forward",robot.forward())
journal:close()
'''
        result.append(('obstacle-'+mode,spec,program,'passed'))
        spec=base(mode)
        block(spec,[0,65,-1],[0,67,-1],'gravel')
        spec['expect']['blocks']=[{'position':[0,65,-1],'block':'minecraft:air'},
                                  {'position':[0,67,-1],'block':'minecraft:air'}]
        program=JOURNAL+'''for i=1,3 do
  record("swing",i,robot.swing())
  os.sleep(1)
end
journal:close()
'''
        result.append(('falling-'+mode,spec,program,'passed'))
        spec=base(mode)
        block(spec,[-1,65,-2],[1,66,-2],'stone')
        block(spec,[-1,65,-1],[-1,66,-1],'stone')
        block(spec,[1,65,-1],[1,66,-1],'stone')
        block(spec,[0,65,-1],[0,65,-1],'water')
        program=JOURNAL+'''record("detect",robot.detect())
local ok,reason=robot.forward(); record("forward",ok,reason)
if ok then record("back",robot.back()) end
os.sleep(2)
record("detect-after",robot.detect())
journal:close()
'''
        result.append(('fluid-'+mode,spec,program,'passed'))
    spec=base('coordinated')
    block(spec,[0,65,-1],[0,65,-1],'stone')
    spec['robot']['inventory']=[{'slot':i,'item':'minecraft:cobblestone','count':64} for i in range(1,17)]
    spec['expect'].update(blocks=[{'position':[0,65,-1],'block':'minecraft:air'}],
                          inventory=[{'item':'minecraft:cobblestone','minCount':1024}])
    result.append(('inventory-full',spec,JOURNAL+'record("swing",robot.swing())\njournal:close()\n','passed'))
    spec=base('coordinated')
    block(spec,[0,65,-4],[0,65,-1],'stone')
    spec['robot']['tool']={'item':'minecraft:iron_pickaxe','metadata':249}
    program=JOURNAL+'''local moved=0
for i=1,4 do
  local durability,reason=robot.durability(); record("durability-before",i,durability,reason)
  if not durability then break end
  local ok,why=robot.swing(); record("swing",i,ok,why)
  if not ok then break end
  ok,why=robot.forward(); record("forward",i,ok,why)
  if not ok then break end
  moved=moved+1
end
for i=1,moved do
  local ok,why=robot.back(); record("back",i,ok,why); assert(ok,why)
end
record("durability-after",robot.durability())
journal:close()
'''
    result.append(('near-break-tool',spec,program,'passed'))
    spec=base('coordinated')
    spec['robot']['energy']=500
    spec['execution']['maxTicks']=2000
    program=JOURNAL+'''for i=1,10000 do
  local ok,reason=robot.turnRight(); record("turn",i,ok,reason)
  if not ok then error("native action failed: "..tostring(reason)) end
end
journal:close()
'''
    result.append(('energy-depletion',spec,program,'failed'))
    for label,spec,program,expected in list(result):
        if label in ('inventory-full','near-break-tool','energy-depletion'):
            reference=copy.deepcopy(spec)
            reference['execution']['mode']='baseline'
            result.append((label+'-baseline',reference,program,expected))
    spec=json.loads((HERE/'examples/mining/scenario.json').read_text())
    spec['schemaVersion']=2; spec['robot']['hardware']='tier3'
    spec['execution']['mode']='baseline'
    result.append(('fresh-recovery',spec,(HERE/'examples/mining/program/main.lua').read_text(),'passed'))
    spec=base('coordinated')
    spec['execution'].update(maxTicks=30000,timeoutSeconds=180)
    spec['observations']={'everyTicks':1,'maxBytes':1048576,'onFull':'stop'}
    result.append(('endurance-coordinated',spec,'os.sleep(1200); print("Twenty simulated minutes completed")\n','passed'))
    spec=base('coordinated')
    spec['observations']={'everyTicks':1,'maxBytes':1048576,'onFull':'fail'}
    result.append(('recording-fail',spec,'os.sleep(240)\n','failed'))
    for name,spec,_,_ in result: spec['id']=name
    return result


def capture(runtime,row):
    proof=runtime_profile.verify_proof(runtime)
    assert proof['profileId']==row['supervisor']['runtimeProfile']
    state=runner_observations.reconstruct(runtime/'observations.ndjson')
    row['observationSummary']=state['summary']
    disk=runtime/'world/opencomputers/robot-runner-disk/home/program'
    row['programOutputs']={p.name:p.read_text(encoding='utf-8') for p in
                           (disk/'report.txt',disk/'actions.tsv') if p.is_file()}
    row['finalBlocks']=[v for _,v in sorted(state['blocks'].items())]
    assert row['result']['observationCoverage']['bytesWritten']<=33554432
    return state


def compare(reference,candidate,expected_state='passed'):
    """Compare recorded selected outcomes; never turn different clocks/resources into parity."""
    if expected_state not in ('passed','failed'): raise ValueError('invalid comparison state')
    for row in (reference,candidate):
        if (row['status']['state']!=expected_state or row['result']['status']!=expected_state
                or not row['supervisor']['cleanup_ok']
                or not row['observationSummary']['finalRecorded']):
            raise ValueError('comparison requires expected terminal outcomes, cleanup and final observations')
    def actions(row):
        lines=[line.split('\t') for line in row['programOutputs'].get('actions.tsv','').splitlines()]
        if any(len(line)<3 for line in lines): raise ValueError('invalid action journal')
        times=[Decimal(line[-2]) for line in lines]; energy=[Decimal(line[-1]) for line in lines]
        if any(not n.is_finite() for n in times+energy): raise ValueError('nonfinite journal')
        return [line[:-2] for line in lines],times,energy
    left,right=actions(reference),actions(candidate)
    def intervals(values): return [b-a for a,b in zip(values,values[1:])]
    def first_difference(a,b):
        for i in range(max(len(a),len(b))):
            x=a[i] if i<len(a) else None; y=b[i] if i<len(b) else None
            if x!=y: return {'index':i,'reference':str(x),'candidate':str(y)}
        return None
    a,b=reference['result'],candidate['result']; ar,br=a['robot'],b['robot']
    checks={'actionValuesMatch':bool(left[0]) and left[0]==right[0],
            'actionUptimeMatch':left[1]==right[1],
            'actionIntervalsMatch':intervals(left[1])==intervals(right[1]),
            'actionEnergyMatch':left[2]==right[2],
            'finalTicksMatch':a['ticks']==b['ticks'],
            'finalPositionFacingMatch':(ar['position'],ar['facing'])==(br['position'],br['facing']),
            'finalInventoryMatch':ar['inventory']==br['inventory'],
            'finalToolMatch':ar['tool']==br['tool'],
            'finalEnergyMatch':ar['energy']==br['energy'],
            'finalObservedBlocksMatch':reference['finalBlocks']==candidate['finalBlocks']}
    return {'referenceJob':reference['jobId'],'candidateJob':candidate['jobId'],
            'expectedState':expected_state,'actionCounts':[len(left[0]),len(right[0])],**checks,
            'allSelectedObservationsMatch':all(checks.values()),
            'firstActionDifference':first_difference(left[0],right[0]),
            'firstIntervalDifference':first_difference(intervals(left[1]),intervals(right[1])),
            'firstEnergyDifference':first_difference(left[2],right[2]),
            'fixtureSpeedup':a['elapsedNanos']/b['elapsedNanos'],
            'totalSpeedup':reference['supervisor']['elapsed_wall_seconds']/candidate['supervisor']['elapsed_wall_seconds']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    parser.add_argument('--java',required=True)
    parser.add_argument('--cases',nargs='*',help='selected labels; default all; always a new output directory')
    args=parser.parse_args()
    definitions=cases()
    selected=set(args.cases or [case[0] for case in definitions])
    if selected-set(case[0] for case in definitions): parser.error('unknown workload label')
    test=Acceptance(SimpleNamespace(output=args.output,java=args.java,template=HERE/'.cache/server',
                    control_jar=HERE/'build/libs/robot-spike.jar'))
    try:
        for label,spec,program,expected in definitions:
            if label not in selected: continue
            folder=test.root/'scenarios'/label
            shutil.copytree(HERE/('examples/cross-chunk' if program is None else 'examples/mining'),folder)
            if program is not None: (folder/'program/main.lua').write_text(program,encoding='utf-8')
            manifest=folder/'scenario.json'; manifest.write_text(json.dumps(spec,indent=2)+'\n',encoding='utf-8')
            runtime,row=test.run(label,manifest,expected,command_timeout=spec['execution']['timeoutSeconds']+20)
            state=capture(runtime,row)
            test.save()  # Preserve measured outputs before any stronger workload assertion.
            if label.startswith('cross-chunk'):
                assert row['programOutputs']['report.txt'].strip()=='Mined and returned: 48'
                assert len(row['programOutputs']['actions.tsv'].splitlines())==144
                assert row['result']['robot']['position']==[0,65,0]
            elif label=='endurance-coordinated':
                coverage=row['observationSummary']['observationCoverage']
                assert row['result']['ticks']>24000,row['result']
                assert coverage['recordingStopped'] and not coverage['finalRecorded'],coverage
                assert coverage['lastObservedTick']>24000 and coverage['lastRecordedTick']<10000,coverage
                assert row['observationSummary']['coverageStatus']=='consistent'
            elif label=='recording-fail':
                assert 'observation_limit' in row['result']['reason'],row['result']
            elif label.startswith('energy-depletion'):
                assert 'not enough energy' in row['programOutputs']['actions.tsv'],row
                assert row['result']['robot']['energy']<2.5,row['result']
                assert row['result']['robot']['state']=='Stopped',row['result']
            elif label.startswith('inventory-full'):
                assert row['programOutputs']['actions.tsv'].startswith('swing\ttrue\tblock\t'),row
            print(json.dumps({'case':label,'state':row['status']['state'],'ticks':row['result']['ticks'],
                              'wallSeconds':row['supervisor']['elapsed_wall_seconds']}),flush=True)
        test.save()
        print(json.dumps({'status':'passed','cases':len(test.rows),'report':str(test.root/'acceptance.json')}))
    finally:
        test.save()
        # On assertion/timeout, ask the actual job owner to stop. Never act on a stale PID.
        if (test.jobs/'.owner').exists():
            for job in test.jobs.iterdir():
                if job.is_dir() and len(job.name)==32:
                    try:
                        test.cli('cancel',job.name,'--jobs-root',test.jobs)
                        test.cli('wait',job.name,'--jobs-root',test.jobs,'--timeout','15',timeout=20)
                    except (OSError,ValueError): pass


if __name__=='__main__': main()
