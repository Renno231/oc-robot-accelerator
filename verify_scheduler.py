"""Bounded real-OpenOS temporal ownership checks; no fixed worker quantum or resume quota."""
import argparse
import json
import subprocess
from verify_runner import Acceptance,HERE
from verify_hardware import hardware

CLOCKS="""local c=require('computer');local fs=require('filesystem')
local t=c.uptime();local cpu=os.clock()
repeat until os.clock()-cpu>=.16
local elapsed=c.uptime()-t
assert(elapsed>=.10,'world ticks froze during Lua computation: '..elapsed)
print('active-cpu',os.clock()-cpu,elapsed)
local path='/home/clock-test';local f=assert(io.open(path,'w'));f:write('one');f:close()
local first=assert(fs.lastModified(path));local start=c.uptime()
os.sleep(2)
f=assert(io.open(path,'a'));f:write('two');f:close()
local delta=fs.lastModified(path)-first
assert(delta>=1900 and delta<=3000,'filesystem elapsed time: '..delta)
print('environment-clock',delta,c.uptime()-start)
"""

class SchedulerAcceptance(Acceptance):
    def scenario(self,label,program,**execution):
        def patch(s):
            s['schemaVersion']=3;s['robot']['hardware']=hardware(3,upgrades=['inventoryupgrade'])
            s['execution'].update(executionDelayMillis=12,maxTicks=1200,timeoutSeconds=60)
            s['execution'].update(execution)
        return self.case(label,program=program,patch=patch)
    def execute(self):
        def selected(name):return not self.args.cases or name in self.args.cases
        if selected('clocks'):
            runtime,row=self.run('clocks',self.scenario('clocks',CLOCKS),'passed')
            assert row['result']['runnerTiming']['workerScheduling']=='idle-compression',row
            assert row['result']['runnerTiming']['skippedIdleNanos']>0,row
            assert 'active-cpu' in (runtime/'program.log').read_text()
        if selected('zero-yield'):
            runtime,row=self.run('zero-yield',self.scenario('zero-yield',
                "local c=require('computer');local untilTime=c.uptime()+.2;local count=0;while c.uptime()<untilTime do c.pullSignal(0);count=count+1 end;assert(count>0);print('yielded',count,c.uptime())",executionDelayMillis=0),'passed')
            assert 'fairnessTicks' not in row['result']['runnerTiming'],row
            assert 'yielded' in (runtime/'program.log').read_text()
        if selected('virtual-delay'):
            runtime,row=self.run('virtual-delay',self.scenario('virtual-delay',
                "local c=require('computer');for i=1,32 do assert(c.pushSignal('check',i)) end;local n=0;while n<32 do local k,v=c.pullSignal(0);if k=='check' then n=n+1;assert(v==n) end end;print('received',n)"),'passed')
            assert 'received\t32' in (runtime/'program.log').read_text()
        if selected('cpu-deadline'):
            _,row=self.run('cpu-deadline',self.scenario('cpu-deadline','while true do end'),'failed')
            assert 'worker_progress_limit' in row['result']['reason'],row['result']
            assert row['supervisor']['elapsed_wall_seconds']<60,row
        if selected('yield-tick-limit'):
            _,row=self.run('yield-tick-limit',self.scenario('yield-tick-limit',
                "while true do require('computer').pullSignal(0) end",executionDelayMillis=0,maxTicks=400),'failed')
            assert row['result']['reason']=='tick_limit',row['result']
        if selected('cancel'):
            self.run('scheduler-cancel',self.scenario('scheduler-cancel',
                "while true do require('computer').pullSignal(1) end"),'cancelled',cancel=True)
        print(json.dumps({'status':'passed','runs':len(self.rows),'report':str(self.root/'acceptance.json')}))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);p.add_argument('--java',required=True)
    p.add_argument('--template',default=str(HERE/'.cache/server'));p.add_argument('--control-jar',default=str(HERE/'build/libs/robot-spike.jar'))
    p.add_argument('--cases',nargs='+',choices=['clocks','zero-yield','virtual-delay','cpu-deadline','yield-tick-limit','cancel'])
    test=SchedulerAcceptance(p.parse_args())
    try:test.execute()
    except BaseException:
        test.save()
        if test.jobs.exists():
            for job in test.jobs.iterdir():
                if job.is_dir() and len(job.name)==32:
                    try:
                        test.cli('cancel',job.name,'--jobs-root',test.jobs)
                        test.cli('wait',job.name,'--jobs-root',test.jobs,'--timeout','15',timeout=20)
                    except (OSError,ValueError,subprocess.TimeoutExpired):pass
        raise

if __name__=='__main__':main()
