"""Native creative robots and finite robots charged from a creative case; no ignorePower override."""
import argparse
import json
import subprocess
from verify_runner import Acceptance, HERE
from verify_hardware import hardware

PROGRAM='''local r=require('robot')
local c=require('computer')
print('capacity',c.maxEnergy())
print('start',c.energy())
os.sleep(2)
print('near',c.energy())
for i=1,4 do assert(r.forward()) end
os.sleep(2)
print('away',c.energy())
for i=1,4 do assert(r.back()) end
print('returned',c.energy())
os.sleep(2)
print('recharged',c.energy())
print('power passed')
'''

class PowerAcceptance(Acceptance):
    def execute(self):
        for label in ('creative-robot','finite-robot','infinite-charger','charger-off','ordinary-case-rejected'):
            if self.args.cases and label not in self.args.cases:continue
            def patch(s):
                s.update(schemaVersion=3)
                s['robot'].update(hardware=hardware(3,upgrades=['inventoryupgrade']),energy=2000)
                if label=='creative-robot':s['robot']['hardware']={'preset':'hardware/creative.json'}
                s['execution'].update(executionDelayMillis=0,maxTicks=5000)
                s['world']={'region':{'min':[-1,64,-5],'max':[3,67,1]},'blocks':[
                    {'min':[-1,64,-5],'max':[3,64,1],'block':'minecraft:stone'},
                    {'min':[-1,65,-5],'max':[3,67,1],'block':'minecraft:air'}]}
                if label in ('infinite-charger','charger-off','ordinary-case-rejected'):
                    def block(p,name):return {'min':p,'max':p,'block':name}
                    s['world']['blocks'] += [block([1,65,0],'opencomputers:charger'),
                        block([2,65,0],'opencomputers:case1' if label=='ordinary-case-rejected' else 'opencomputers:casecreative')]
                    if label!='charger-off':s['world']['blocks'].append(block([1,64,0],'minecraft:redstone_block'))
            runtime,row=self.run(label,self.case(label,program=PROGRAM,patch=patch),'failed' if label=='ordinary-case-rejected' else 'passed')
            if label=='ordinary-case-rejected':
                assert 'additional_loaded_oc_machine' in row['result']['reason'],row['result'];continue
            log=(runtime/'program.log').read_text()
            assert 'power passed' in log,log
            values={line.split('\t')[0]:float(line.split('\t')[1]) for line in log.splitlines() if line.startswith(('capacity\t','start\t','near\t','away\t','returned\t','recharged\t'))}
            row['powerObserved']=values;self.save()
            if label=='creative-robot':
                assert values['near']>19000 and values['away']>19000 and values['recharged']>19000,values
            elif label=='infinite-charger':
                assert values['near']>values['start']+2000 and values['away']<values['near'],values
                # Infinite supply does not mean instantaneous transfer: OC's
                # native charger rate and redstone signal still control charging.
                assert values['recharged']>values['returned']+2000,values
            else:
                assert values['near']<values['start'] and values['away']<values['near'],values
                assert values['recharged']<values['returned']<values['away'],values
        print(json.dumps({'status':'passed','runs':len(self.rows),'report':str(self.root/'acceptance.json')}))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True);parser.add_argument('--java',required=True)
    parser.add_argument('--template',default=str(HERE/'.cache/server'))
    parser.add_argument('--control-jar',default=str(HERE/'build/libs/robot-spike.jar'))
    parser.add_argument('--cases',nargs='+')
    args=parser.parse_args();acceptance=PowerAcceptance(args)
    try:acceptance.execute()
    except BaseException:
        acceptance.save()
        if acceptance.jobs.exists():
            for job in acceptance.jobs.iterdir():
                if job.is_dir() and len(job.name)==32:
                    try:
                        acceptance.cli('cancel',job.name,'--jobs-root',acceptance.jobs)
                        acceptance.cli('wait',job.name,'--jobs-root',acceptance.jobs,'--timeout','15',timeout=20)
                    except (OSError,ValueError,subprocess.TimeoutExpired):pass
        raise

if __name__=='__main__':main()
