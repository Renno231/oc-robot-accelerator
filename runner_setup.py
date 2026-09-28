"""Install one pinned runtime without Gradle; publish readiness only after verification."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid

import bootstrap
import runner_scenario as scenario
import runtime_profile as profile
import supervisor

HERE=Path(__file__).resolve().parent
META_LIMIT=128*1024
OC_API='https://api.github.com/repos/MightyPirates/OpenComputers/releases/assets/260264311'


def _path(path):
    path=Path(os.path.abspath(path))
    ancestor=path
    while True:
        try: ancestor.lstat(); break
        except FileNotFoundError: ancestor=ancestor.parent
    supervisor._no_link(ancestor)
    return path


def _record(root,value):
    data=(json.dumps(value,sort_keys=True,allow_nan=False)+'\n').encode()
    if len(data)>META_LIMIT: raise ValueError('installation metadata bound exceeded')
    temp=root/('.installation-'+uuid.uuid4().hex+'.tmp')
    try:
        with temp.open('xb') as stream: stream.write(data)
        deadline=time.monotonic()+1
        while True:
            try: os.replace(temp,root/'installation.json'); break
            except PermissionError:
                if time.monotonic()>=deadline: raise
                time.sleep(.025)
    finally: temp.unlink(missing_ok=True)


def java_check(java,timeout=10):
    """Bound the trusted Java version probe; do not require a development JDK."""
    java=Path(java).resolve(strict=True)
    if not java.is_file(): raise ValueError('Java executable required')
    with tempfile.TemporaryFile() as output:
        process=subprocess.Popen([str(java),'-version'],stdin=subprocess.DEVNULL,
                                 stdout=output,stderr=output,start_new_session=os.name!='nt',
                                 creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | supervisor.NO_WINDOW) if os.name=='nt' else 0)
        deadline=time.monotonic()+min(10,timeout)
        try:
            while process.poll() is None:
                if time.monotonic()>=deadline: raise TimeoutError('Java version probe timeout')
                if os.fstat(output.fileno()).st_size>64*1024: raise ValueError('Java version output bound')
                time.sleep(.025)
            if process.returncode: raise ValueError('Java version probe failed')
            output.seek(0); data=output.read(64*1024+1)
            if len(data)>64*1024: raise ValueError('Java version output bound')
        finally: supervisor._stop_tree(process)
    text=data.decode('utf-8','replace')
    match=re.search(r'(?:java|openjdk) version "(1\.8\.[^"\r\n]+)"',text)
    if not match: raise ValueError('Java 8 required; select its java executable')
    return {'path':str(java),'version':match.group(1)}


def _control():
    release=HERE/'release.json'
    if release.exists():
        data=scenario.read_json(release,META_LIMIT)
        if (not isinstance(data,dict) or type(data.get('schemaVersion')) is not int or data['schemaVersion']!=1 or
                data.get('profileId')!=profile.PROFILE_ID or not isinstance(data.get('controlJar'),dict) or
                data['controlJar'].get('path')!='lib/robot-control.jar'):
            raise ValueError('invalid package release manifest; no source-build fallback')
        record=data['controlJar']; path=supervisor._no_link(HERE/record['path'])
        if (type(record.get('size')) is not int or not 0<record['size']<=16*1024*1024 or
                not isinstance(record.get('sha256'),str) or not re.fullmatch('[0-9a-f]{64}',record['sha256'])):
            raise ValueError('invalid packaged control identity')
        profile._verify(path,record,lambda:None)
        return path,'package',{'size':record['size'],'sha256':record['sha256']}
    path=supervisor._no_link(HERE/'build/libs/robot-spike.jar')
    if not path.is_file() or not 0<path.stat().st_size<=16*1024*1024:
        raise ValueError('Build the source control JAR first, or use a published package')
    return path,'source-build',{'size':path.stat().st_size,'sha256':bootstrap.sha256(path)}


class _Owner:
    """Own setup child cleanup, total time, logs and directory bounds together."""
    def __init__(self,root,deadline): self.root=root; self.deadline=deadline

    def check(self):
        if time.monotonic()>=self.deadline: raise TimeoutError('setup deadline exceeded')
        log=self.root/'setup.log'
        if log.exists() and log.stat().st_size>supervisor.LOG_LIMIT: raise ValueError('setup log bound exceeded')

    def scan(self):
        self.check()
        supervisor._inventory(self.root,supervisor.COPY_BYTES_LIMIT,supervisor.COPY_FILES_LIMIT,
                              deadline=self.deadline,live=True,check=self.check)

    def run(self,command,timeout,**kwargs):
        self.scan()
        stop=min(self.deadline,time.monotonic()+timeout)
        path=self.root/'setup.log'
        header=(json.dumps({'command':command},ensure_ascii=True)+'\n').encode()
        with path.open('ab') as log:
            if log.tell()+len(header)>supervisor.LOG_LIMIT: raise ValueError('setup log bound exceeded')
            log.write(header)
        overflow=threading.Event()
        process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                 start_new_session=os.name!='nt',
                                 creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | supervisor.NO_WINDOW) if os.name=='nt' else 0,**kwargs)
        def drain():
            try:
                with path.open('ab') as log, process.stdout as pipe:
                    used=log.tell()
                    while True:
                        data=pipe.read1(65536)
                        if not data: break
                        available=max(0,supervisor.LOG_LIMIT-used)
                        log.write(data[:available]); log.flush(); used+=len(data)
                        if used>supervisor.LOG_LIMIT: overflow.set()
            except OSError: overflow.set()
        reader=threading.Thread(target=drain,daemon=True); reader.start()
        try:
            while process.poll() is None:
                self.scan()
                if overflow.is_set(): raise ValueError('setup log bound or output I/O failure')
                if time.monotonic()>=stop: raise TimeoutError('setup command timeout')
                time.sleep(.05)
        finally:
            supervisor._stop_tree(process); reader.join(timeout=3)
            if reader.is_alive(): raise RuntimeError('setup output cleanup unresolved')
        self.scan()
        if overflow.is_set(): raise ValueError('setup log bound or output I/O failure')
        if process.returncode: raise subprocess.CalledProcessError(process.returncode,command)


def _acquire(path,artifact,owner):
    try:
        bootstrap.acquire(path,artifact['url'],artifact['sha256'],run=owner.run)
    except subprocess.CalledProcessError:
        # One official release endpoint fallback, never a hash-mismatch fallback.
        if not artifact['name'].startswith('OpenComputers'): raise
        owner.check()
        bootstrap.acquire(path,OC_API,artifact['sha256'],run=owner.run,
                          headers=('Accept: application/octet-stream','X-GitHub-Api-Version: 2022-11-28'))
    owner.scan()
    if 'size' in artifact and path.stat().st_size!=artifact['size']: raise ValueError('setup artifact size mismatch')


def _install_forge(java,installer,server,owner):
    server.mkdir()
    owner.run([str(java),'-jar',str(installer),'--installServer'],timeout=600,cwd=server)


def _inventory(root,check=lambda:None):
    entries=supervisor._inventory(root,supervisor.COPY_BYTES_LIMIT,supervisor.COPY_FILES_LIMIT,check=check)
    return {rel.as_posix():{'size':size,'sha256':supervisor._digest(root/rel,float('inf'),check)}
            for rel,size in entries}


def _ready(root,record,java=None):
    deadline=time.monotonic()+30
    def check():
        if time.monotonic()>=deadline: raise TimeoutError('installation verification deadline exceeded')
    if (not isinstance(record,dict) or type(record.get('schemaVersion')) is not int or record['schemaVersion']!=1 or
            record.get('state')!='ready' or record.get('profileId')!=profile.PROFILE_ID or
            record.get('origin') not in ('package','source-build') or record.get('eulaAccepted') is not True or
            not isinstance(record.get('control'),dict) or not isinstance(record.get('files'),dict) or
            not isinstance(record.get('java'),dict) or not isinstance(record['java'].get('path'),str)):
        raise ValueError('installation identity invalid')
    payload=supervisor._no_link(root/'payload')
    if record['files']!=_inventory(payload,check): raise ValueError('installation payload changed; preserved for inspection')
    profile.verify_template(payload/'server',check)
    for artifact in profile.OVERLAYS: profile._verify(payload/'runtime-libraries'/artifact['name'],artifact,check)
    control=payload/'control.jar'
    if not control.is_file() or not 0<control.stat().st_size<=16*1024*1024: raise ValueError('installation control JAR missing')
    if record['control']!=record['files'].get('control.jar'): raise ValueError('installation control identity differs')
    check(); selected=java_check(java or record['java']['path'],timeout=deadline-time.monotonic()); check()
    return {'template':payload/'server','control_jar':control,
            'runtime_libraries':payload/'runtime-libraries','java':selected['path'],
            'control_identity':dict(record['control'])}


def doctor(installation,java=None):
    """Read-only/no network; inspect installed bytes rather than believing a marker."""
    root=_path(installation)
    value={'status':'absent','installation':str(root),'profileId':profile.PROFILE_ID}
    if not root.exists(): return dict(value,message='Run setup with a new installation directory')
    try:
        supervisor._no_link(root)
        if not root.is_dir(): raise ValueError('installation path is not a directory')
        if not (root/'installation.json').exists():
            return dict(value,status='incomplete',message='Existing directory has no installation record; preserved')
        record=scenario.read_json(root/'installation.json',META_LIMIT)
        if isinstance(record,dict) and record.get('state') in ('installing','failed'):
            return dict(value,status='incomplete',message=str(record.get('error','Setup did not publish readiness'))[:2048])
        paths=_ready(root,record,java)
        return dict(value,status='ready',origin=record['origin'],java=paths['java'],
                    message='Pinned installed files verified; no server was started')
    except (OSError,ValueError,TypeError,TimeoutError,RecursionError) as exc:
        return dict(value,status='incompatible',message=str(exc)[:2048])


def resolve(installation,java=None):
    root=supervisor._no_link(installation)
    return _ready(root,scenario.read_json(root/'installation.json',META_LIMIT),java)


def install(installation,java,timeout=900,*,accept_eula=False):
    if type(timeout) not in (int,float) or not 30<=timeout<=1800: raise ValueError('setup timeout must be in [30,1800]')
    deadline=time.monotonic()+timeout
    root=_path(installation)
    if root.exists():
        value=doctor(root,java)
        if value['status']=='ready': return value
        raise ValueError('Existing installation is '+value['status']+'; inspect it or choose a new directory')
    if accept_eula is not True: raise ValueError('New public installation requires explicit --accept-eula')
    if sys.version_info<(3,11): raise ValueError('Python 3.11 or newer required')
    if not shutil.which('curl'): raise ValueError('curl is required for checked HTTPS acquisition')
    selected=java_check(java,timeout=deadline-time.monotonic()); control,origin,control_pin=_control()
    if time.monotonic()>=deadline: raise TimeoutError('setup deadline exceeded before ownership')
    if scenario.overlap(root,HERE): raise ValueError('installation must be separate from the tool directory')
    root.parent.mkdir(parents=True,exist_ok=True); supervisor._no_link(root.parent)
    root.mkdir()  # Exclusive ownership; an incomplete directory is never implicitly reclaimed.
    record={'schemaVersion':1,'state':'installing','profileId':profile.PROFILE_ID,
            'origin':origin,'java':selected,'created':time.time(),'eulaAccepted':True,'control':control_pin}
    owner=_Owner(root,deadline)
    try:
        _record(root,record)
        stage=root/'.stage'; stage.mkdir(); acquired=root/'acquired'; acquired.mkdir()
        installer,oc=bootstrap.ARTIFACTS[1:]
        for artifact in (installer,oc): _acquire(acquired/artifact['name'],artifact,owner)
        libraries=stage/'runtime-libraries'; libraries.mkdir()
        for artifact in profile.OVERLAYS: _acquire(libraries/artifact['name'],artifact,owner)
        _install_forge(selected['path'],acquired/installer['name'],stage/'server',owner)
        server=stage/'server'; (server/'mods').mkdir(exist_ok=True)
        shutil.copyfile(acquired/oc['name'],server/'mods/OpenComputers.jar')
        settings=server/'config/opencomputers/settings.conf'; settings.parent.mkdir(parents=True)
        settings.write_text(bootstrap.CONFIG,encoding='utf-8')
        (server/'eula.txt').write_text('eula=true\n',encoding='ascii')
        with supervisor._no_link(control).open('rb') as source, (stage/'control.jar').open('xb') as target:
            copied=0
            while True:
                owner.check(); data=source.read(128*1024)
                if not data: break
                copied+=len(data)
                if copied>control_pin['size']: raise ValueError('selected control changed during setup')
                target.write(data)
        profile._verify(stage/'control.jar',control_pin,owner.check)
        profile.verify_template(server,owner.check)
        for artifact in profile.OVERLAYS: profile._verify(libraries/artifact['name'],artifact,owner.check)
        record['files']=_inventory(stage,owner.check)
        owner.scan(); stage.rename(root/'payload')
        record.update(state='ready',completed=time.time())
        _record(root,record)
    except BaseException as exc:
        record.update(state='failed',error=(type(exc).__name__+': '+str(exc))[:2048])
        _record(root,record)
        raise
    return {'status':'ready','installation':str(root),'profileId':profile.PROFILE_ID,
            'origin':origin,'java':selected['path'],'message':'Pinned installation verified; no server was started'}
