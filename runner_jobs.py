"""Filesystem job ownership; supervisor remains the sole Java process owner."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import uuid

import runner_scenario as scenario
import supervisor

HERE = Path(__file__).resolve().parent
TERMINAL = {'passed', 'failed', 'cancelled'}
STATES = TERMINAL | {'launching', 'running'}
META_LIMIT = 64 * 1024
HEARTBEAT_SECONDS = 5


class SubmissionInterrupted(KeyboardInterrupt):
    """Preserve the admitted job identity across foreground ownership transfer."""
    def __init__(self, jobid):
        super().__init__('submission interrupted; cancellation requested')
        self.jobid = jobid


def _atomic(path, value):
    data = (json.dumps(value, sort_keys=True, allow_nan=False) + '\n').encode('utf-8')
    if len(data) > META_LIMIT: raise ValueError('job metadata byte bound exceeded')
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('xb') as out: out.write(data)
        retry_until = time.monotonic() + 1
        while True:
            try:
                os.replace(temp, path)
                break
            except PermissionError:
                # Windows readers can briefly deny deletion of the old metadata inode.
                if time.monotonic() >= retry_until: raise
                time.sleep(.01)
    finally:
        temp.unlink(missing_ok=True)


def _root(path, create=False):
    root = Path(os.path.abspath(path))
    if create:
        ancestor = root
        while not ancestor.exists(): ancestor = ancestor.parent
        supervisor._no_link(ancestor)
        root.mkdir(parents=True, exist_ok=True)
    root = supervisor._no_link(root)
    if not root.is_dir(): raise ValueError('jobs root must be a directory')
    return root


def _job(root, jobid):
    if not isinstance(jobid,str) or not re.fullmatch('[0-9a-f]{32}',jobid):
        raise ValueError('invalid job ID')
    return _root(root) / jobid


def _owns(root, jobid, token):
    try:
        value = scenario.read_json(root / '.owner' / 'owner.json',META_LIMIT)
        return value == {'jobId':jobid,'token':token}
    except (OSError, ValueError): return False


def _release(root, jobid, token):
    if not _owns(root,jobid,token): raise ValueError('admission ownership lost; refusing release')
    (root / '.owner' / 'owner.json').unlink()
    (root / '.owner').rmdir()


def status(root, jobid):
    job = _job(root,jobid)
    try:
        for attempt in range(3):
            try:
                value = scenario.read_json(job / 'job.json', META_LIMIT)
                break
            except PermissionError:
                if attempt == 2: raise
                time.sleep(.025)  # Windows atomic replacement can briefly deny a concurrent reader.
        def timestamp(name):
            number=value.get(name)
            return type(number) in (int,float) and 0 <= number <= 1e12 and math.isfinite(number)
        if (not isinstance(value,dict) or type(value.get('schemaVersion')) != int or value['schemaVersion'] != 1 or
                value.get('jobId') != jobid or not isinstance(value.get('state'),str) or value['state'] not in STATES or
                not timestamp('heartbeat') or not timestamp('created') or
                type(value.get('acknowledged')) != bool or not isinstance(value.get('scenarioId'),str) or
                not isinstance(value.get('reason'),str)):
            raise ValueError('invalid metadata')
        if value['state'] in TERMINAL and (value.get('cleanupOk') is not True or not timestamp('completed')):
            raise ValueError('terminal metadata lacks completion/cleanup evidence')
    except (OSError, ValueError) as exc:
        return {'schemaVersion':1,'jobId':jobid,'state':'unavailable',
                'reason':'missing, partial or invalid job metadata; not a completion result',
                'metadataError':(type(exc).__name__+': '+str(exc))[:512]}
    value = dict(value)
    if value['state'] not in TERMINAL and time.time() - value['heartbeat'] > HEARTBEAT_SECONDS:
        value['recordedState'] = value['state']; value['state'] = 'unavailable'
        value['reason'] = 'owner unresponsive; admission retained until verified operator cleanup'
    return value


def cancel(root, jobid):
    value = status(root,jobid)
    if value['state'] in TERMINAL: return value
    job = supervisor._no_link(_job(root,jobid))
    try:
        with (job / 'cancel').open('xb') as out: out.write(b'cancel\n')
    except FileExistsError: pass
    return status(root,jobid)


def _wait(root, jobid, deadline, stop_unavailable=False):
    while True:
        value = status(root,jobid)
        if value['state'] in TERMINAL or (stop_unavailable and value['state']=='unavailable'): return value
        now = time.monotonic()
        if now >= deadline: raise TimeoutError('wait timeout; job not cancelled')
        time.sleep(min(.1,deadline-now))


def wait(root, jobid, timeout=600):
    if type(timeout) not in (int,float) or not 0 < timeout <= scenario.MAX_TIMEOUT_SECONDS:
        raise ValueError('wait timeout must be in (0,%d]' % scenario.MAX_TIMEOUT_SECONDS)
    return _wait(root,jobid,time.monotonic()+timeout)


def wait_foreground(root, jobid):
    """Wait through this job's existing deadline plus bounded cleanup grace.

    An unavailable owner is returned for explicit inspection, never auto-reclaimed.
    The caller retains Ctrl+C cancellation ownership throughout a long healthy job.
    """
    launch = scenario.read_json(_job(root,jobid)/'launch.json',META_LIMIT)
    if not isinstance(launch,dict) or launch.get('jobId')!=jobid:
        raise ValueError('invalid foreground launch identity')
    start, deadline = launch.get('start'), launch.get('deadline')
    if (type(start) not in (int,float) or type(deadline) not in (int,float) or
            not math.isfinite(start) or not math.isfinite(deadline) or
            not start < deadline <= start + scenario.MAX_TIMEOUT_SECONDS):
        raise ValueError('invalid foreground launch deadline')
    limit = min(deadline,time.monotonic()+scenario.MAX_TIMEOUT_SECONDS)+10
    return _wait(root,jobid,limit,stop_unavailable=True)


def submit(manifest, root, java, template, control_jar, *, runtime_libraries=None, control_identity=None, worker_command=None, ack_timeout=30):
    """Freeze then transfer reservation to a detached owner. No automatic stale reclaim.

    worker_command is a private process-boundary test seam, not a CLI option.
    """
    start = time.monotonic()
    deadline = start + 600
    job = None; value = None; last_write = start
    def check():
        nonlocal last_write
        if job is not None and (job/'cancel').exists(): raise supervisor.Cancelled('cancellation requested during preparation')
        if time.monotonic() >= deadline: raise TimeoutError('wall timeout during scenario preparation')
        if time.monotonic() >= start + ack_timeout:
            raise TimeoutError('worker acknowledgement timeout during input preparation')
        if job is not None and value is not None and time.monotonic()-last_write >= .5:
            value['heartbeat']=time.time(); _atomic(job/'job.json',value); last_write=time.monotonic()
    template = supervisor._no_link(template)
    control_jar = supervisor._no_link(control_jar)
    root = Path(os.path.abspath(root))
    if scenario.overlap(root,template): raise ValueError('jobs/template roots overlap')
    forbidden=[root,template]
    if runtime_libraries is not None:
        if control_identity is None: raise ValueError('installed runtime requires selected control identity')
        runtime_libraries=supervisor._no_link(runtime_libraries)
        if scenario.overlap(root,runtime_libraries.parent): raise ValueError('jobs/installation payload roots overlap')
        forbidden.append(runtime_libraries.parent)
    def set_budget(normalized):
        nonlocal deadline
        deadline = start + normalized['execution']['timeoutSeconds']
    spec = scenario.load(manifest,tuple(forbidden),check,on_normalized=set_budget)
    check()
    root = _root(root,create=True)
    jobid, token = uuid.uuid4().hex, uuid.uuid4().hex
    admission = root / '.owner'
    try: admission.mkdir()
    except FileExistsError as exc:
        raise ValueError('jobs root admission held by an active or unavailable owner; no automatic reclaim') from exc
    job = root / jobid
    launched = False
    value = {'schemaVersion':1,'jobId':jobid,'scenarioId':spec.normalized['id'],'state':'launching',
             'reason':'freezing inputs','heartbeat':time.time(),'acknowledged':False,'created':time.time(),
             'submitPid':os.getpid()}
    try:
        _atomic(admission / 'owner.json',{'jobId':jobid,'token':token})
        job.mkdir()
        _atomic(job / 'job.json',value)
        scenario.freeze(spec,job/'inputs',check)
        launch = {'jobId':jobid,'token':token,'start':start,'deadline':deadline,'java':str(java),
                  'template':str(template),'controlJar':str(control_jar),'execution':spec.normalized['execution'],
                  'scenarioId':spec.normalized['id']}
        if runtime_libraries is not None:
            launch['runtimeLibraries']=str(runtime_libraries)
            launch['controlIdentity']=dict(control_identity)
        _atomic(job/'launch.json',launch)
        check()
        command = list(worker_command or [sys.executable,str(HERE/'runner_jobs.py')])
        command += ['_worker','--jobs-root',str(root),'--job',jobid,'--token',token]
        flags = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS) if os.name=='nt' else 0
        process = subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                   creationflags=flags,start_new_session=os.name!='nt',close_fds=True)
        launched = True
        # Reap while this client is alive; daemon ownership does not tie job lifetime to the CLI.
        threading.Thread(target=process.wait,daemon=True).start()
        acknowledge_by = min(deadline,start+ack_timeout)
        while True:
            value = status(root,jobid)
            if value.get('acknowledged') or value['state'] in TERMINAL: return value
            if time.monotonic() >= acknowledge_by or process.poll() is not None:
                # A very short failing job may publish its terminal record between read and poll.
                value = status(root,jobid)
                if value.get('acknowledged') or value['state'] in TERMINAL: return value
                cancel(root,jobid)
                raise TimeoutError('worker acknowledgement unavailable; cancellation requested and admission retained')
            time.sleep(.02)
    except BaseException as exc:
        if not launched:
            if job.exists():
                value.update(state='cancelled' if isinstance(exc,(KeyboardInterrupt,supervisor.Cancelled)) else 'failed',
                             reason=str(exc)[:2048],heartbeat=time.time(),completed=time.time(),cleanupOk=True)
                _atomic(job/'job.json',value)
            _release(root,jobid,token)
        else:
            cancel(root,jobid)
        if isinstance(exc,KeyboardInterrupt): raise SubmissionInterrupted(jobid) from exc
        if isinstance(exc,supervisor.Cancelled) and not launched: return value
        raise


def _install(inputs, root, execution, check):
    """Install execution copies; frozen evidence is never a writable server filesystem."""
    normalized = scenario.read_json(inputs/'runner-scenario.json')
    hashes = {}
    # Revalidate stored engine JSON through the same public shape owner.
    if scenario.normalize(normalized) != normalized: raise ValueError('frozen normalized scenario drift')
    data = (inputs/'runner-scenario.json').read_bytes()
    check(); (root/'runner-scenario.json').write_bytes(data)
    hashes['runner/runner-scenario.json'] = supervisor._digest(root/'runner-scenario.json',float('inf'),check)
    for name, cap, entries in [('program',scenario.PROGRAM_BYTES,scenario.PROGRAM_ENTRIES),
                               ('world',scenario.WORLD_BYTES,scenario.WORLD_ENTRIES)]:
        source = inputs/name
        if source.exists():
            listing = scenario._scan(source,cap,entries,check)
            hashes.update({'runner/'+name+'/'+rel:sha for rel,sha in
                           scenario.copy_tree(source,root/name,listing,check).items()})
    expected = scenario.read_json(inputs/'sha256.json',4*1024*1024)
    actual_inputs = {name.removeprefix('runner/'):digest for name,digest in hashes.items()}
    preset = inputs/'hardware-preset.json'
    if preset.exists():
        actual_inputs['hardware-preset.json'] = hashlib.sha256(scenario._json_bytes(preset,scenario.MANIFEST_BYTES)).hexdigest()
    if not isinstance(expected,dict) or {k:v for k,v in expected.items() if k!='scenario.json'} != actual_inputs:
        raise ValueError('frozen input hash drift')
    settings = ('opencomputers {\n version="1.8.9a"\n computer { executionDelay=%d }\n'
                ' power { ignorePower=false }\n internet { enableHttp=false, enableTcp=false }\n}\n' % execution['executionDelayMillis'])
    (root/'config/opencomputers/settings.conf').write_text(settings,encoding='utf-8')
    hashes['generated/config/opencomputers/settings.conf'] = supervisor._digest(
        root/'config/opencomputers/settings.conf',float('inf'),check)
    return hashes


def worker(root, jobid, token):
    root = _root(root); job = supervisor._no_link(_job(root,jobid))
    if not _owns(root,jobid,token): raise ValueError('worker does not own admission')
    launch = scenario.read_json(job/'launch.json',META_LIMIT)
    if launch['jobId'] != jobid or launch['token'] != token: raise ValueError('worker launch identity mismatch')
    value = scenario.read_json(job/'job.json',META_LIMIT)
    value.update(acknowledged=True,workerPid=os.getpid(),heartbeat=time.time(),reason='worker owns frozen inputs')
    _atomic(job/'job.json',value)
    last_write = time.monotonic()
    def check():
        nonlocal last_write
        if (job/'cancel').exists(): raise supervisor.Cancelled('cancellation requested')
        if time.monotonic() >= launch['deadline']: raise TimeoutError('wall timeout including preparation/startup')
        if time.monotonic()-last_write >= .5:
            value['heartbeat']=time.time(); _atomic(job/'job.json',value); last_write=time.monotonic()
    def on_launch(pid):
        value.update(state='running',serverPid=pid,reason='server running',heartbeat=time.time())
        _atomic(job/'job.json',value)
    execution = launch['execution']
    args = SimpleNamespace(output_root=str(job),template=launch['template'],control_jar=launch['controlJar'],
                           java=launch['java'],mode=execution['mode'],ticks=execution['maxTicks'],
                           timeout=execution['timeoutSeconds'],runtime_libraries=launch.get('runtimeLibraries'),
                           control_identity=launch.get('controlIdentity'))
    cleanup_ok = False
    try:
        outcome = supervisor.execute(args,root=job/'runtime',start=launch['start'],deadline=launch['deadline'],
                                     check=check,prepare=lambda runtime,hook:_install(job/'inputs',runtime,execution,hook),
                                     scenario_id=launch['scenarioId'],on_launch=on_launch)
        report = outcome['report']; cleanup_ok = report['cleanup_ok']
        state = 'cancelled' if report['cancelled'] else report['status']
        value.update(state=state,reason=report['reason'][:2048],runtime='runtime',
                     elapsedWallSeconds=report['elapsed_wall_seconds'],cleanupOk=cleanup_ok)
        if not cleanup_ok:
            value.update(state='running',reason='cleanup unresolved; admission retained: '+value['reason'])
    except Exception as exc:
        # Unexpected errors cannot establish process cleanup; fail closed, never release admission.
        value.update(state='running',reason='worker failed; cleanup unverified: '+str(exc)[:2048])
    value.update(heartbeat=time.time())
    if cleanup_ok: value['completed']=time.time()
    _atomic(job/'job.json',value)
    if cleanup_ok: _release(root,jobid,token)
    return 0 if value['state']=='passed' else 1


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['_worker']); parser.add_argument('--jobs-root',required=True)
    parser.add_argument('--job',required=True); parser.add_argument('--token',required=True)
    args=parser.parse_args(argv)
    try:
        return worker(args.jobs_root,args.job,args.token)
    except Exception as exc:
        # Preserve a bounded diagnostic even if initial acknowledgement/metadata publication failed.
        job = _job(args.jobs_root,args.job)
        try: _atomic(job/'worker-error.json',{'error':type(exc).__name__,'message':str(exc)[:4096]})
        except (OSError,ValueError): pass
        return 1


if __name__=='__main__': sys.exit(main())
