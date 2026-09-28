"""Native experience-upgrade configuration, progression and effective mechanics checks."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
from verify_runner import Acceptance, HERE
from verify_hardware import hardware

PROGRAM='''local r=require('robot')
local c=require('computer')
local component=require('component')
local e=assert(component.experience)
print('levelBefore',e.level())
print('capacity',c.maxEnergy())
local start=c.uptime()
assert(r.swing())
print('swingTicks',(c.uptime()-start)*20)
assert(r.forward())
for i=2,16 do assert(r.swing()); assert(r.forward()) end
print('levelAfter',e.level())
print('experience passed')
'''


class ExperienceAcceptance(Acceptance):
    def execute(self):
        level30={'item':'experienceupgrade','level':30}
        recipes={
            'experience-zero': hardware(3,upgrades=['inventoryupgrade','experienceupgrade']),
            'experience-thirty': hardware(3,upgrades=['inventoryupgrade',level30]),
            'experience-raw': hardware(3,upgrades=['inventoryupgrade',{'item':'experienceupgrade','experience':400.5}]),
            'experience-level-up': hardware(3,upgrades=['inventoryupgrade',{'item':'experienceupgrade','experience':113.99}]),
            'experience-raw-over-cap': hardware(3,upgrades=['inventoryupgrade',{'item':'experienceupgrade','experience':60000}]),
            'experience-container': hardware(3,upgrades=['inventoryupgrade'],containers=[{'item':'upgradecontainer3','component':level30}]),
            'experience-stacked': hardware(3,upgrades=['inventoryupgrade']+[level30]*3,
                containers=[{'item':'upgradecontainer3','component':level30}]),
            'experience-preset': hardware(3,upgrades=['inventoryupgrade',{'item':'experienceupgrade','level':10}]),
        }
        observed={}
        for label,recipe in recipes.items():
            if self.args.cases and label not in self.args.cases: continue
            def patch(s):
                s.update(schemaVersion=3)
                s['robot']['hardware']=copy.deepcopy(recipe)
                s['execution'].update(executionDelayMillis=0,maxTicks=5000)
                s['world']={'region':{'min':[-1,64,-17],'max':[1,67,1]},'blocks':[
                    {'min':[-1,64,-17],'max':[1,64,1],'block':'minecraft:stone'},
                    {'min':[-1,65,-17],'max':[1,67,1],'block':'minecraft:air'},
                    {'min':[0,65,-16],'max':[0,65,-1],'block':'minecraft:stone'}]}
                if label=='experience-thirty': s['robot']['energy']=160000
            manifest=self.case(label,program=PROGRAM,patch=patch)
            if label=='experience-preset':
                preset=manifest.parent/'hardware/xp.json'; base=copy.deepcopy(recipe)
                base['upgrades']=['inventoryupgrade',{'item':'experienceupgrade','level':0}]
                preset.write_text(json.dumps(base))
                s=json.loads(manifest.read_text());s['robot']['hardware']={'preset':'hardware/xp.json','overrides':{'upgrades':recipe['upgrades']}}
                manifest.write_text(json.dumps(s))
            runtime,row=self.run(label,manifest,'passed')
            log=(runtime/'program.log').read_text(); assert 'experience passed' in log,log
            values={line.split('\t')[0]:float(line.split('\t')[1]) for line in log.splitlines() if line.startswith(('levelBefore\t','levelAfter\t','capacity\t','swingTicks\t'))}
            observed[label]=values; row['experienceObserved']=values
            initial=json.loads((runtime/'observations.ndjson').open(encoding='utf-8').readline())['robot']
            final=row['result']['robot']; row['initialExperience']=initial['experienceUpgrades'];self.save()
            if label=='experience-zero':
                assert values['levelBefore']==0 and values['levelAfter']>0,values
                assert final['experienceUpgrades'][0]['experience']>0,final
            if label in ('experience-thirty','experience-container'):
                assert values['levelBefore']==30 and values['levelAfter']==30,values
                assert values['capacity']==170500,values
                assert initial['experienceUpgrades']==[{'level':30,'experience':57650}],initial
            if label=='experience-raw':
                assert initial['experienceUpgrades']==[{'level':2,'experience':400.5}],initial
                assert values['levelAfter']>values['levelBefore']>2,values
            if label=='experience-level-up':
                assert values['levelBefore']<1<values['levelAfter'],values
                assert initial['energyCapacity']==20500 and final['energyCapacity']==25500,(initial,final)
                assert initial['experienceUpgrades'][0]['level']==0 and final['experienceUpgrades'][0]['level']==1,(initial,final)
            if label=='experience-raw-over-cap':
                assert initial['experienceUpgrades']==[{'level':30,'experience':60000}],initial
                assert final['experienceUpgrades']==initial['experienceUpgrades'],final
                assert values['capacity']==170500 and values['levelBefore']>30,values
            if label=='experience-stacked':
                assert len(initial['experienceUpgrades'])==4,initial
                assert values['capacity']==620500,values
                # Native handler sums levels: >=100 makes ComputeDamageRate exactly zero.
                # This is not a random-wear comparison between independently seeded worlds.
                assert final['tool']['metadata']==0,final
                assert final['inventory'][0]['count']==16,final
            if label=='experience-preset':
                assert values['levelBefore']==10 and values['levelAfter']>10,values
        if 'experience-zero' in observed and 'experience-thirty' in observed:
            assert observed['experience-thirty']['swingTicks']<observed['experience-zero']['swingTicks'],observed
        for label,recipe,reason in [
            ('experience-tier-rejected',hardware(1,upgrades=['experienceupgrade']),'native assembler slots/tier')]:
            if self.args.cases and label not in self.args.cases: continue
            def patch(s):s.update(schemaVersion=3);s['robot']['hardware']=recipe
            _,row=self.run(label,self.case(label,program='error("invalid experience config booted")',patch=patch),'failed')
            assert reason in row['result']['reason'],row['result']
        print(json.dumps({'status':'passed','runs':len(self.rows),'report':str(self.root/'acceptance.json')}))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True);parser.add_argument('--java',required=True)
    parser.add_argument('--template',default=str(HERE/'.cache/server'))
    parser.add_argument('--control-jar',default=str(HERE/'build/libs/robot-spike.jar'))
    parser.add_argument('--cases',nargs='+')
    args=parser.parse_args();acceptance=ExperienceAcceptance(args)
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
