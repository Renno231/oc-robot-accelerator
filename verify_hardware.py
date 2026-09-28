"""Real-server configurable hardware acceptance using OC's native assembler and drivers."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
from verify_runner import Acceptance, HERE


def hardware(tier, *, cpu=None, memory=None, upgrades=None, cards=None, storage=None, containers=None, boot=0):
    return {'tier': tier, 'cpu': cpu or 'cpu'+str(tier), 'memory': memory or ['ram'+str(tier*2)],
            'upgrades': [] if upgrades is None else upgrades, 'cards': [] if cards is None else cards,
            'storage': storage or ['hdd'+str(tier)], 'bootDrive': boot,
            'containers': [] if containers is None else containers}


class HardwareAcceptance(Acceptance):
    def execute(self):
        recipes = {
            'tier1-no-inventory': (hardware(1), 0, False, False),
            'tier2-components': (hardware(2, memory=['ram3', 'ram4'], cards=['redstonecard1'],
                upgrades=['inventoryupgrade', 'craftingupgrade']), 16, True, True),
            'tier3-64-slots': (hardware(3, upgrades=['inventoryupgrade']*4,
                storage=['hdd3', 'hdd2']), 64, False, False),
            'tier1-container': (hardware(1, containers=[{'item':'upgradecontainer1','component':'inventoryupgrade'}]),16,False,False),
            'mixed-tier-cards': (hardware(3, cards=['graphicscard1','graphicscard3','graphicscard2'],
                memory=['ram1','ram6']),0,False,False),
            'second-boot-drive': (hardware(3, storage=['hdd3','hdd1'],boot=1),0,False,False),
            'battery-capacity': (hardware(3, upgrades=['batteryupgrade3']*3),0,False,False),
        }
        invalid = {
            'cpu-too-high': (hardware(1,cpu='cpu3'), 'native assembler slots/tier'),
            'ram-too-high': (hardware(1,memory=['ram6']), 'native assembler slots/tier'),
            'unknown-component': (hardware(1,cpu='inventedcpu'), 'unknown OC hardware component'),
            'wrong-component-kind': (hardware(1,cpu='hdd1'), 'is not a robot cpu'),
            'container-mismatch': (hardware(1,containers=[{'item':'cardcontainer1','component':'inventoryupgrade'}]), 'rejects inventoryupgrade'),
            'upgrade-too-high': (hardware(1,upgrades=['angelupgrade']), 'native assembler slots/tier'),
            'complexity-limit': (hardware(3,cpu='cpu1',upgrades=['inventoryupgrade'],containers=[
                {'item':'upgradecontainer3'},{'item':'upgradecontainer2'},{'item':'upgradecontainer2'}]), 'invalid native robot assembly'),
        }
        rows={}
        for label,(recipe,slots,redstone,crafting) in recipes.items():
            if self.args.cases and label not in self.args.cases: continue
            def patch(s):
                s['schemaVersion']=3; s['robot']['hardware']=copy.deepcopy(recipe)
                s['robot']['inventory']=([{'slot':slots,'item':'minecraft:stone','count':3}] if slots else [])
                s['execution'].update(executionDelayMillis=0,maxTicks=5000)
                if label=='battery-capacity': s['robot']['energy']=80000
            program='''local r=require('robot')
local c=require('computer')
local component=require('component')
local fs=require('filesystem')
assert(r.inventorySize()==%d, 'inventory capacity '..r.inventorySize())
assert(component.isAvailable('redstone')==%s, 'redstone loadout')
assert(component.isAvailable('crafting')==%s, 'crafting loadout')
assert(r.turnRight()); assert(r.turnLeft())
local f=assert(io.open('hardware-write.txt','w')); f:write('native writable storage'); f:close()
local f=assert(io.open('hardware-write.txt','r')); assert(f:read('*a')=='native writable storage'); f:close()
print('memory',c.totalMemory())
print('capacity',fs.get('/').spaceTotal())
print('hardware passed')
''' % (slots,str(redstone).lower(),str(crafting).lower())
            runtime,row=self.run(label,self.case(label,program=program,patch=patch),'passed')
            log=(runtime/'program.log').read_text()
            assert 'hardware passed' in log,(label,log)
            rows[label]={line.split('\t')[0]:float(line.split('\t')[1]) for line in log.splitlines() if line.startswith(('memory\t','capacity\t'))}
            row['hardwareObserved']=rows[label]; self.save()
            if label=='second-boot-drive': assert rows[label]['capacity']==1048576,rows[label]
            if label=='battery-capacity':
                initial=json.loads((runtime/'observations.ndjson').open(encoding='utf-8').readline())
                assert initial['robot']['energy']==80000,initial
        if all(label in rows for label in ['tier1-no-inventory','tier2-components','tier3-64-slots']):
            assert rows['tier1-no-inventory']['memory'] < rows['tier2-components']['memory'] < rows['tier3-64-slots']['memory'],rows
            assert rows['tier1-no-inventory']['capacity'] < rows['tier2-components']['capacity'] < rows['tier3-64-slots']['capacity'],rows
        for label,(recipe,reason) in invalid.items():
            if self.args.cases and label not in self.args.cases: continue
            def patch(s): s.update(schemaVersion=3); s['robot']['hardware']=copy.deepcopy(recipe)
            _,row=self.run(label,self.case(label,program='error("invalid hardware was booted")',patch=patch),'failed')
            assert reason in row['result']['reason'],(label,row['result'])
        if not self.args.cases or 'inventory-capacity' in self.args.cases:
            def patch(s):
                s.update(schemaVersion=3);s['robot']['hardware']=hardware(1)
                s['robot']['inventory']=[{'slot':1,'item':'minecraft:stone','count':1}]
            _,row=self.run('inventory-capacity',self.case('inventory-capacity',program='return',patch=patch),'failed')
            assert 'inventory capacity' in row['result']['reason'],row['result']
        if not self.args.cases or 'native-storage-full' in self.args.cases:
            def patch(s):
                s.update(schemaVersion=3);s['robot']['hardware']=hardware(1,memory=['ram2','ram2'])
                s['execution'].update(executionDelayMillis=0,maxTicks=5000)
            program='''local f=assert(io.open('fill','w')); f:setvbuf('no')
local block=string.rep('x',4096)
local count=0
for i=1,512 do if not f:write(block) then break end; count=count+1 end
assert(count<256,'native HDD capacity was bypassed')
f:close(); os.remove('fill'); print('capacity enforced',count)
'''
            runtime,_=self.run('native-storage-full',self.case('native-storage-full',program=program,patch=patch),'passed')
            assert 'capacity enforced' in (runtime/'program.log').read_text()
        for tier in (1,2,3):
            label='preset-tier'+str(tier)
            if self.args.cases and label not in self.args.cases: continue
            def patch(s):
                s.update(schemaVersion=3)
                s['robot']['hardware']={'preset':'hardware/tier'+str(tier)+'.json'}
                if tier==3: s['robot']['hardware']['overrides']={'memory':['ram5'], 'cards':['redstonecard1']}
                s['execution'].update(executionDelayMillis=0,maxTicks=5000)
            runtime,row=self.run(label,self.case(label,patch=patch),'passed')
            assert 'Mining complete' in (runtime/'program.log').read_text()
            frozen=runtime.parent/'inputs'
            resolved=json.loads((frozen/'runner-scenario.json').read_text())['robot']['hardware']
            preset=json.loads((frozen/'hardware-preset.json').read_text())
            assert resolved['tier']==tier
            if tier==3:
                assert resolved['memory']==['ram5'] and preset['memory']==['ram6']
                assert resolved['cards']==['redstonecard1'] and preset['cards']==[]
        print(json.dumps({'status':'passed','runs':len(self.rows),'report':str(self.root/'acceptance.json')}))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    parser.add_argument('--java',required=True)
    parser.add_argument('--template',default=str(HERE/'.cache/server'))
    parser.add_argument('--control-jar',default=str(HERE/'build/libs/robot-spike.jar'))
    parser.add_argument('--cases',nargs='+')
    args=parser.parse_args(); acceptance=HardwareAcceptance(args)
    try: acceptance.execute()
    except BaseException:
        acceptance.save()
        if acceptance.jobs.exists():
            for job in acceptance.jobs.iterdir():
                if job.is_dir() and len(job.name)==32:
                    try:
                        acceptance.cli('cancel',job.name,'--jobs-root',acceptance.jobs)
                        acceptance.cli('wait',job.name,'--jobs-root',acceptance.jobs,'--timeout','15',timeout=20)
                    except (OSError,ValueError,subprocess.TimeoutExpired): pass
        raise


if __name__=='__main__': main()
