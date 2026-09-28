"""Explicit, fail-closed job recovery and bounded local diagnostic artifacts.

Never kills processes or infers task success from a dead owner. Process snapshots
are a guard, not proof about arbitrary descendants; recovery also requires the
operator's explicit confirmation that owned processes and descendants have ended.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time
import zipfile

import runner_jobs as jobs
import runner_scenario as scenario
import supervisor

TIMEOUT = 30
SCAN_BYTES = 512 * 1024
ARCHIVE_BYTES = 40 * 1024 * 1024
# Exact allowlist: no launch/owner tokens, Lua sources, world data or game binaries.
ARTIFACTS = {
    'job.json': jobs.META_LIMIT, 'worker-error.json': jobs.META_LIMIT,
    'recovery.json': jobs.META_LIMIT, 'cleanup.json': jobs.META_LIMIT,
    'runtime/result.json': 1024 * 1024, 'runtime/supervisor.json': 1024 * 1024,
    'runtime/runtime-logging.json': 64 * 1024,
    'runtime/observations-status.json': 64 * 1024,
    'runtime/program.log': 1024 * 1024,
    'runtime/stdout.log': 128 * 1024, 'runtime/stderr.log': 128 * 1024,
}


def _check(deadline):
    if time.monotonic() >= deadline: raise TimeoutError('job support operation deadline exceeded')


def _processes(pids, deadline):
    """Bounded local snapshots. No PID is killed, including a reused PID."""
    _check(deadline)
    if os.name == 'nt':
        # Local CIM supplies command lines including Java's explicit owned root.
        # Bound serialization in the trusted query itself, not after a huge pipe.
        script = ("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new(); "
                  "$p=@(Get-CimInstance Win32_Process); if($p.Count -gt 32768){throw 'process count bound'}; "
                  "$r=@($p | ForEach-Object { $c=$_.CommandLine; "
                  "if($c -and $c.Length -gt 16384){$c=$null}; "
                  "@{pid=[int]$_.ProcessId;name=$_.Name;command=$c} }); "
                  "$j=ConvertTo-Json -InputObject $r -Compress -Depth 3; "
                  "if([Text.Encoding]::UTF8.GetByteCount($j) -gt 524288){throw 'process snapshot byte bound'}; "
                  "[Console]::Write($j)")
        result = subprocess.run(['powershell.exe','-NoLogo','-NoProfile','-NonInteractive','-Command',script],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=min(10, max(.01,deadline-time.monotonic())), creationflags=supervisor.NO_WINDOW)
        if result.returncode or len(result.stdout)>SCAN_BYTES or len(result.stderr)>SCAN_BYTES:
            raise ValueError('process inspection unavailable; recovery refused')
        try: values=json.loads(result.stdout.decode('utf-8-sig'))
        except (ValueError,UnicodeError) as exc: raise ValueError('invalid process snapshot') from exc
        if not isinstance(values,list): raise ValueError('invalid process snapshot')
        return values
    if not Path('/proc').is_dir():
        raise ValueError('process inspection currently supports Windows and Linux only')
    values=[]; total=0
    for entry in Path('/proc').iterdir():
        _check(deadline)
        if not entry.name.isdigit(): continue
        if len(values)>=32768: raise ValueError('process count bound exceeded')
        try:
            name=(entry/'comm').read_text()[:256].strip()
            with (entry/'cmdline').open('rb') as stream: raw=stream.read(16385)
            command=raw.replace(b'\0',b' ').decode('utf-8',errors='replace') if len(raw)<=16384 else None
        except FileNotFoundError: continue  # exited during read, not an invisible running owner
        except PermissionError:
            name='unknown'; command=None
        total+=len(command.encode('utf-8')) if command else 0
        if total>SCAN_BYTES: raise ValueError('process snapshot byte bound exceeded')
        values.append({'pid':int(entry.name),'name':name,'command':command})
    return values


def _metadata(root, jobid):
    job=supervisor._no_link(jobs._job(root,jobid))
    value=jobs.status(root,jobid)
    if value.get('metadataError'): raise ValueError('valid job metadata required for recovery/cleanup')
    pids=set()
    for key in ('submitPid','workerPid','serverPid'):
        pid=value.get(key)
        if pid is not None:
            if type(pid)!=int or not 0<pid<2**31: raise ValueError('invalid recorded process identity')
            pids.add(pid)
    if not pids: raise ValueError('job metadata has no process identities; manual inspection required')
    return job,value,pids


def _activity(job, jobid, pids, deadline):
    relevant=[]
    marker=str(job).replace('\\','/').lower()
    selected=None
    try: launch=scenario.read_json(job/'launch.json',jobs.META_LIMIT)
    except FileNotFoundError: pass  # Submission may have died before publishing launch inputs.
    else:
        if not isinstance(launch,dict) or not isinstance(launch.get('java'),str) or not launch['java']:
            raise ValueError('invalid selected runtime metadata; manual inspection required')
        selected=launch['java'].replace('\\','/').rsplit('/',1)[-1].lower()
    for process in _processes(pids,deadline):
        pid=process.get('pid'); name=process.get('name'); command=process.get('command')
        if type(pid)!=int or not isinstance(name,str) or (command is not None and not isinstance(command,str)):
            raise ValueError('invalid process snapshot entry')
        if pid==os.getpid() and pid not in pids: continue  # Exempt incidental self matching, never a reused recorded PID.
        possible=(name.lower()==selected or bool(re.match(r'^(java|javaw|python|py(?:\.exe)?$)',name.lower())))
        text=(command or '').replace('\\','/').lower()
        matching=(jobid in text or marker in text) and (possible or '_worker' in text or '-drobotspike.root=' in text)
        if pid in pids or matching:
            relevant.append({'pid':pid,'name':name,'reason':'live recorded or matching process'})
        elif command is None and (possible or name=='unknown'):
            relevant.append({'pid':pid,'name':name,'reason':'uncertain process visibility'})
    return relevant


def inspect(root, jobid):
    deadline=time.monotonic()+TIMEOUT
    job,value,pids=_metadata(root,jobid)
    activity=_activity(job,jobid,pids,deadline)
    owner=_admission(root)
    return {'job':value,'admissionHeldForJob':owner is not None and owner['jobId']==jobid,
            'processes':activity,'processSnapshotOnly':True,
            'guidance':'Cancel live jobs. For abandoned ownership, independently verify all owned processes and descendants have ended before explicit recover. No automatic PID killing or success inference.'}


def _admission(root):
    owner=jobs._root(root)/'.owner'
    if not owner.exists(): return None
    supervisor._no_link(owner)
    value=scenario.read_json(owner/'owner.json',jobs.META_LIMIT)
    if (not isinstance(value,dict) or set(value)!={'jobId','token'} or
            not all(isinstance(value[k],str) and re.fullmatch('[0-9a-f]{32}',value[k]) for k in value)):
        raise ValueError('invalid admission identity; manual inspection required')
    return value


@contextmanager
def _maintenance(root):
    lock=jobs._root(root)/'.maintenance'
    try: lock.mkdir()
    except FileExistsError as exc: raise ValueError('maintenance already held; inspect before manual recovery') from exc
    try: yield
    finally: lock.rmdir()


def _inactive(root, jobid, deadline):
    job,value,pids=_metadata(root,jobid)
    if value['state'] not in jobs.TERMINAL and value['state']!='unavailable':
        raise ValueError('owner still responsive; cancel and wait instead')
    activity=_activity(job,jobid,pids,deadline)
    if activity: raise ValueError('live or uncertain processes; refusing mutation: '+str(activity)[:2048])
    return job,value


def recover(root, jobid, *, confirm_stopped=False):
    if not confirm_stopped: raise ValueError('explicit --confirm-processes-stopped required, including descendants')
    deadline=time.monotonic()+TIMEOUT
    with _maintenance(root):
        owner=_admission(root)
        if owner is None or owner['jobId']!=jobid: raise ValueError('admission does not belong to this job')
        job,value=_inactive(root,jobid,deadline)
        if (job/'recovered-owner').exists(): raise ValueError('prior recovery evidence exists; inspect manually')
        _inactive(root,jobid,deadline)  # second snapshot immediately before release
        if _admission(root)!=owner: raise ValueError('admission changed; refusing recovery')
        record={'schemaVersion':1,'jobId':jobid,'status':'prepared','time':time.time(),
                'operatorConfirmedProcessesStopped':True,'originalState':value['state'],
                'warning':'Ownership recovery is not successful program completion or exact process-tree proof.'}
        jobs._atomic(job/'recovery.json',record)
        # Admission evidence is retained intact, not deleted. New submissions can
        # proceed only after this atomic rename; no other job directory is touched.
        (jobs._root(root)/'.owner').rename(job/'recovered-owner')
        record['status']='released'; jobs._atomic(job/'recovery.json',record)
        return record


def cleanup(root, jobid, *, confirm_delete_runtime=False):
    if not confirm_delete_runtime: raise ValueError('explicit --confirm-delete-runtime required; export evidence first')
    deadline=time.monotonic()+TIMEOUT
    with _maintenance(root):
        owner=_admission(root)
        if owner is not None and owner['jobId']==jobid: raise ValueError('admission still held; recover or finish first')
        job,value=_inactive(root,jobid,deadline)
        if value['state'] not in jobs.TERMINAL:
            record=scenario.read_json(job/'recovery.json',jobs.META_LIMIT) if (job/'recovery.json').exists() else {}
            if record.get('status')!='released' or record.get('jobId')!=jobid:
                raise ValueError('terminal cleanup or explicit released recovery required')
        runtime=job/'runtime'
        if not runtime.exists(): return {'jobId':jobid,'status':'absent'}
        # Check the entire delete set first. Never follow links or silently sweep
        # inputs/caches; oversized/unreadable trees require deliberate inspection.
        supervisor._no_link(runtime)
        supervisor._inventory(runtime,4*1024**3,40000,deadline)
        _inactive(root,jobid,deadline)
        record={'schemaVersion':1,'jobId':jobid,'status':'removing','time':time.time(),
                'target':'runtime','preserved':['inputs','job.json','recovery.json']}
        jobs._atomic(job/'cleanup.json',record)
        def remove(path):
            _check(deadline)
            supervisor._no_link(path)
            if path.is_dir():
                for child in path.iterdir(): remove(child)
                path.rmdir()
            else: path.unlink()
        remove(runtime)
        record['status']='removed'; jobs._atomic(job/'cleanup.json',record)
        return record


def diagnostics(root, jobid, output, *, include_observations=False):
    deadline=time.monotonic()+TIMEOUT
    job=supervisor._no_link(jobs._job(root,jobid))
    output=Path(os.path.abspath(output))
    supervisor._no_link(output.parent)
    if scenario.overlap(output,job): raise ValueError('diagnostic output must be outside the job directory')
    artifacts=dict(ARTIFACTS)
    if include_observations: artifacts['runtime/observations.ndjson']=32*1024*1024
    manifest={'schemaVersion':1,'jobId':jobid,'created':time.time(),'files':{},'missing':[],
              'warning':'Logs and metadata may contain sensitive program output and local paths. Review before sharing. Files sampled independently; not an atomic runtime snapshot. Observation gaps/partial final lines remain visible.'}
    owned=False; total=0
    try:
        with output.open('xb') as target:
            owned=True
            with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
                for name,cap in artifacts.items():
                    _check(deadline); source=job/name
                    try: supervisor._no_link(source)
                    except FileNotFoundError:
                        manifest['missing'].append(name); continue
                    if not stat.S_ISREG(source.stat().st_mode): raise ValueError('diagnostic source must be a regular file')
                    with source.open('rb') as stream:
                        size=os.fstat(stream.fileno()).st_size
                        # Logs retain a tail; observations retain the initial reconstructable prefix.
                        offset=max(0,size-cap) if name.endswith(('stdout.log','stderr.log')) else 0
                        stream.seek(offset); remaining=min(size-offset,cap); digest=hashlib.sha256(); copied=0
                        with archive.open(name,'w') as dest:
                            while remaining:
                                _check(deadline); data=stream.read(min(65536,remaining))
                                if not data: break
                                copied+=len(data); remaining-=len(data); total+=len(data)
                                if total>ARCHIVE_BYTES: raise ValueError('diagnostic aggregate byte bound exceeded')
                                dest.write(data); digest.update(data)
                    manifest['files'][name]={'size':copied,'sourceSize':size,'offset':offset,
                                              'truncated':copied!=size,'sha256':digest.hexdigest()}
                archive.writestr('diagnostics.json',json.dumps(manifest,sort_keys=True,allow_nan=False)+'\n')
        return {'jobId':jobid,'status':'exported','path':str(output),'files':len(manifest['files']),
                'bytesIncluded':total,'warning':manifest['warning']}
    except BaseException:
        if owned: output.unlink(missing_ok=True)
        raise
