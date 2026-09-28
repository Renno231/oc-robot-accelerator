"""Opt-in real-server logging-profile and bounded-recording acceptance."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import runner_observations
import runtime_profile
from verify_runner import Acceptance, HERE


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True); parser.add_argument('--java',required=True)
    args=parser.parse_args()
    test=Acceptance(SimpleNamespace(output=args.output,java=args.java,
                    template=HERE/'.cache/server',control_jar=HERE/'build/libs/robot-spike.jar'))
    def public(spec):
        spec['schemaVersion']=2; spec['robot']['hardware']='tier3'
        spec['execution']['timeoutSeconds']=120
    def recording(spec):
        public(spec)
        spec['observations']={'everyTicks':1,'maxBytes':1048576,'onFull':'stop'}
    cases=[('logging-baseline','baseline',None,public,'passed'),
           ('logging-coordinated','coordinated',None,public,'passed'),
           ('logging-error','coordinated','error("expected profile failure")',public,'failed'),
           ('logging-shutdown','coordinated','require("computer").shutdown()',
            lambda s:(public(s),s['execution'].update(executionDelayMillis=0)),'failed'),
           ('recording-stop','coordinated','os.sleep(240); print("retention complete")',recording,'passed')]
    for label,mode,program,patch,expected in cases:
        runtime,row=test.run(label,test.case(label,mode=mode,program=program,patch=patch),expected)
        proof=runtime_profile.verify_proof(runtime)
        assert proof['profileId']==row['supervisor']['runtimeProfile']
        if label=='logging-error': assert row['result']['program']['status']=='error'
        if label=='logging-shutdown':
            assert row['result']['reason']=='program_not_returned',row['result']
            assert row['result']['robot']['state']=='Stopped',row['result']
        if label=='recording-stop':
            summary=runner_observations.reconstruct(runtime/'observations.ndjson')['summary']
            row['observationSummary']=summary
            assert summary['coverageStatus']=='consistent',summary
            assert summary['observationCoverage']['recordingStopped'] is True,summary
            assert summary['observationCoverage']['lastObservedTick']>summary['observationCoverage']['lastRecordedTick'],summary
            assert (runtime/'observations.ndjson').stat().st_size<=1048576
            assert row['result']['status']=='passed'
        test.save()
    print(json.dumps({'status':'passed','cases':len(test.rows),'report':str(test.root/'acceptance.json')}))


if __name__=='__main__': main()
