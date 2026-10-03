"""Export an inert-data, offline HTML replay of bounded recorded samples."""
import base64
import hashlib
import json
import os
from pathlib import Path
import time

import runner_jobs as jobs
import runner_observations as observations
import runner_scenario as scenario
import supervisor

MAX_RECORDS=100000
MAX_CELLS=500000
CONSOLE_BYTES=128*1024
OUTPUT_BYTES=64*1024*1024
TIMEOUT=30
ASSETS=Path(__file__).resolve().parent/'viewer'


def _optional_json(path, cap):
    try: return {'status':'available','value':scenario.read_json(path,cap)}
    except FileNotFoundError: return {'status':'missing','value':None}
    except (ValueError,OSError): return {'status':'invalid','value':None}


def export(root, jobid, output):
    deadline=time.monotonic()+TIMEOUT
    def check():
        if time.monotonic()>=deadline: raise TimeoutError('viewer export deadline exceeded')
    job=supervisor._no_link(jobs._job(root,jobid))
    output=Path(os.path.abspath(output))
    supervisor._no_link(output.parent)
    if scenario.overlap(output,jobs._root(root)):
        raise ValueError('viewer output must be outside the jobs root')
    records=[]; cells=0
    def retain(record):
        nonlocal cells
        check(); cells+=len(record['blocks'])
        positions=[record['robot']['position']]
        if not records: positions += [record['region']['min'],record['region']['max']]
        if (record['tick']>2**53-1 or any(not -2**31<=p[0]<2**31 or not 0<=p[1]<=255 or
                                       not -2**31<=p[2]<2**31 for p in positions)):
            raise ValueError('viewer coordinate/tick bound exceeded')
        if len(records)>=MAX_RECORDS or cells>MAX_CELLS: raise ValueError('viewer record/cell bound exceeded')
        records.append(record)
    state=observations.reconstruct(job/'runtime/observations.ndjson',on_record=retain)
    if not records: raise ValueError('no complete recorded samples available')
    check()
    console={'status':'missing','text':'','offset':0,'sourceSize':0,'truncated':False}
    try:
        path=supervisor._no_link(job/'runtime/program.log')
        with path.open('rb') as stream:
            size=os.fstat(stream.fileno()).st_size; offset=max(0,size-CONSOLE_BYTES)
            stream.seek(offset); data=stream.read(CONSOLE_BYTES)
        console=dict(status='available',text=data.decode('utf-8',errors='replace'),offset=offset,
                     sourceSize=size,truncated=offset>0 or len(data)!=size)
    except FileNotFoundError: pass
    payload={'schemaVersion':1,'jobId':jobid,'job':jobs.status(root,jobid),
             'summary':state['summary'],'records':records,'console':console,
             'result':_optional_json(job/'runtime/result.json',1024*1024),
             'warning':'This replay shows recorded samples, not a re-run. It can include console output and file paths, so check it before sharing.'}
    # Base64 keeps every untrusted string out of HTML syntax and executable code.
    raw=json.dumps(payload,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('utf-8')
    check()
    script=(ASSETS/'viewer.js').read_text(encoding='utf-8')
    style=(ASSETS/'viewer.css').read_text(encoding='utf-8')
    template=(ASSETS/'viewer.html').read_text(encoding='utf-8')
    digest=base64.b64encode(hashlib.sha256(script.encode('utf-8')).digest()).decode()
    html=(template.replace('__SCRIPT_HASH__',digest).replace('__STYLE__',style)
          .replace('__PAYLOAD__',base64.b64encode(raw).decode()).replace('__SCRIPT__',script)).encode('utf-8')
    if len(html)>OUTPUT_BYTES: raise ValueError('viewer output byte bound exceeded')
    check(); owned=False
    try:
        with output.open('xb') as dest:
            owned=True
            for offset in range(0,len(html),65536):
                check(); dest.write(html[offset:offset+65536])
    except BaseException:
        if owned: output.unlink(missing_ok=True)
        raise
    return {'jobId':jobid,'status':'exported','path':str(output),'bytes':len(html),
            'records':len(records),'firstTick':state['summary']['firstTick'],'lastTick':state['summary']['lastTick'],
            'finalRecorded':state['summary']['finalRecorded'],'coverageStatus':state['summary']['coverageStatus'],
            'warning':payload['warning']}
