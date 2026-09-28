"""Paired native/accelerated OpenOS comparisons with all observed discrepancies retained.

Baseline keeps native host scheduling. Paced uses the idle-compression owner's
admission without skipping waiting; neither promises identical host CPU durations.
The comparison checks a bounded workload, not universal timing equivalence.
"""
import argparse
import json
from decimal import Decimal
from pathlib import Path
import subprocess
from verify_runner import Acceptance, HERE
from verify_hardware import hardware

HEADER='''local r=require('robot')
local c=require('computer')
local records={}
local function record(name,...)
 local row={name}
 for i=1,select('#',...) do row[#row+1]=tostring(select(i,...)) end
 row[#row+1]=string.format('%.8f',c.uptime())
 row[#row+1]=string.format('%.8f',c.energy())
 row[#row+1]=tostring(r.durability())
 records[#records+1]=table.concat(row,'\\t')
end
record('cold-entry')
while c.uptime()<30 do c.pullSignal(math.max(0,30-c.uptime())) end
record('work-start')
'''
TAIL='''record('work-end')
for _,row in ipairs(records) do print(row) end
'''
MINING='''for i=1,48 do record('swing',i,r.swing()); record('forward',i,r.forward()) end
for i=1,48 do record('back',i,r.back()) end
'''
BOUNDARIES='''for i=1,32 do assert(c.pushSignal('queued-check',i)) end
local signals={}
while #signals<32 do
 local name,value=c.pullSignal(0)
 if name=='queued-check' then signals[#signals+1]=value end
end
for i=1,32 do assert(signals[i]==i) end
record('signals',#signals)
assert(r.inventorySize()==16)
for i=1,5000 do r.count(1) end
record('direct-calls',5000)
os.sleep(1.25); record('sleep')
for i=1,24 do record('right',i,r.turnRight()); record('left',i,r.turnLeft()) end
'''
NEAR_BREAK='''for i=1,16 do
 local durability=r.durability()
 if not durability then break end
 local ok,why=r.swing();record('swing',i,ok,why)
 if not ok then break end
 record('forward',i,r.forward())
end
'''


def compare_journals(reference,candidate):
    a,b=reference['journal'],candidate['journal']
    if not a or not b or a[0][0]!='cold-entry' or b[0][0]!='cold-entry':
        raise ValueError('missing startup evidence')
    if len(a)<3 or len(b)<3 or a[1][0]!='work-start' or b[1][0]!='work-start':
        raise ValueError('missing work boundary')
    def times(rows): return [Decimal(row[-3]) for row in rows]
    def energy(rows): return [Decimal(row[-2]) for row in rows]
    def relative(values): return [x-values[0] for x in values]
    def differences(a,b):
        return [{'index':i,'reference':a[i] if i<len(a) else None,'candidate':b[i] if i<len(b) else None}
                for i in range(max(len(a),len(b))) if i>=len(a) or i>=len(b) or a[i]!=b[i]][:12]
    checks={
        'valuesMatch':[row[:-3] for row in a]==[row[:-3] for row in b],
        'workUptimeMatch':times(a[1:])==times(b[1:]),
        'workEnergyDeltaMatch':relative(energy(a[1:]))==relative(energy(b[1:])),
        'wearMatch':[row[-1] for row in a]==[row[-1] for row in b]}
    return dict(checks,counts=[len(a),len(b)],coldEntry=[a[0],b[0]],
                workStart=[a[1],b[1]],absoluteEnergyMatch=energy(a)==energy(b),
                rawDifferences=differences(a,b),
                fixtureSeconds=[row['result']['elapsedNanos']/1e9 for row in (reference,candidate)],
                wholeJobSeconds=[row['supervisor']['elapsed_wall_seconds'] for row in (reference,candidate)],
                scope='Work-boundary action/tick/energy-delta/seeded robot wear only; raw startup energy and all other differences remain visible. No whole-world random replay or universal parity claim.')


class AccelerationAcceptance(Acceptance):
    def execute(self):
        reports={}
        for label,body,length in [('cross-chunk',MINING,48),('boundaries',BOUNDARIES,4),('near-break',NEAR_BREAK,16)]:
            if self.args.cases and label not in self.args.cases: continue
            pair=[]
            for mode in ('coordinated',self.args.reference):
                def patch(s):
                    s.update(schemaVersion=3)
                    s['robot']['hardware']=hardware(3,upgrades=['inventoryupgrade'])
                    s['robot']['randomSeed']=17
                    if label=='near-break': s['robot']['tool']={'item':'minecraft:iron_pickaxe','metadata':246}
                    s['world']['region']={'min':[-1,64,-length-1],'max':[1,67,1]}
                    s['world']['blocks']=[
                        {'min':[-1,64,-length-1],'max':[1,64,1],'block':'minecraft:stone'},
                        {'min':[-1,65,-length-1],'max':[1,67,1],'block':'minecraft:air'},
                        {'min':[0,65,-length],'max':[0,65,-1],'block':'minecraft:stone'}]
                    s['execution'].update(executionDelayMillis=self.args.execution_delay,maxTicks=10000,timeoutSeconds=240)
                    s['observations'].update(everyTicks=10)
                runtime,row=self.run(label+'-'+mode,self.case(label+'-'+mode,mode=mode,
                    program=HEADER+body+TAIL,patch=patch),'passed',command_timeout=260)
                row['journal']=[line.split('\t') for line in (runtime/'program.log').read_text().splitlines()]
                self.save();pair.append(row)
            report=compare_journals(*reversed(pair));report['referenceMode']=self.args.reference
            report['coldAndWorkJournalMatch']=pair[0]['journal']==pair[1]['journal']
            reports[label]=report
            (self.root/'comparisons.json').write_text(json.dumps(reports,indent=2)+'\n')
            print(json.dumps({'case':label,**report}),flush=True)
            assert all(report[key] for key in ('valuesMatch','workUptimeMatch','workEnergyDeltaMatch','wearMatch')),report
            # Cold boot is measured, never erased. Native host dispatch/CPU costs
            # vary across processes; exact cold journals are not an invariant of
            # idle compression (unlike the discarded fixed-batch prototype).
        print(json.dumps({'status':'passed','runs':len(self.rows),'report':str(self.root/'comparisons.json')}))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True);p.add_argument('--java',required=True)
    p.add_argument('--template',default=str(HERE/'.cache/server'))
    p.add_argument('--control-jar',default=str(HERE/'build/libs/robot-spike.jar'))
    p.add_argument('--cases',nargs='+',choices=['cross-chunk','boundaries','near-break'])
    p.add_argument('--reference',choices=['paced','baseline'],default='baseline')
    p.add_argument('--execution-delay',type=int,choices=[0,12],default=12)
    a=p.parse_args();test=AccelerationAcceptance(a)
    try: test.execute()
    except BaseException:
        test.save()
        if test.jobs.exists():
            for job in test.jobs.iterdir():
                if job.is_dir() and len(job.name)==32:
                    try:
                        test.cli('cancel',job.name,'--jobs-root',test.jobs)
                        test.cli('wait',job.name,'--jobs-root',test.jobs,'--timeout','15',timeout=20)
                    except (OSError,ValueError,subprocess.TimeoutExpired): pass
        raise


if __name__=='__main__': main()
