"""Build a reproducible first-party ZIP; no acquisition, compiler or server execution."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import stat
import sys
import time
import zipfile

from runtime_profile import PROFILE_ID
from supervisor import _no_link

HERE=Path(__file__).resolve().parent
MODULES=('bootstrap','runner','runner_jobs','runner_observations','runner_scenario',
         'runner_setup','runner_support','runner_viewer','runtime_profile','supervisor')
FILES=tuple(sorted([name+'.py' for name in MODULES]+[
    'viewer/viewer.html','viewer/viewer.css','viewer/viewer.js',
    'README.md','SCENARIO.md','THIRD_PARTY_NOTICES.md','LICENSE','CHANGELOG.md',
    'runtime-profile.json','robot-runner','robot-runner.cmd',
]+[f'examples/{example}/{name}' for example in ('mining','cross-chunk')
   for name in ('scenario.json','program/main.lua','program/miner.lua','program/distance.txt')]
   +[f'examples/mining/hardware/tier{tier}.json' for tier in (1,2,3)]
   +['examples/mining/hardware/creative.json']))
FILE_LIMIT=1024*1024
JAR_LIMIT=16*1024*1024
TOTAL_LIMIT=32*1024*1024
REQUIRED_MANIFEST='Manifest-Version: 1.0\nFMLCorePluginContainsFMLMod: true\nForceLoadAsMod: true\nFMLCorePlugin: ocelot.spike.PacingPlugin\n\n'


def _record(data):
    return {'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}


def _read(path,limit,check):
    check(); path=_no_link(path)
    if not path.is_file() or path.stat().st_size>limit: raise ValueError('package input byte/type bound: '+str(path))
    with path.open('rb') as stream: data=stream.read(limit+1)
    if len(data)>limit: raise ValueError('package input byte bound: '+str(path))
    check(); return data


def _jar(data,check):
    """This distribution ships ordinary first-party mod classes, never shaded dependencies."""
    with zipfile.ZipFile(io.BytesIO(data)) as jar:
        infos=jar.infolist(); names=set(); total=0
        if len(infos)>256: raise ValueError('control JAR entry bound')
        for entry in infos:
            check(); name=entry.filename
            if name in names: raise ValueError('duplicate control JAR entry')
            names.add(name)
            mode=stat.S_IFMT(entry.external_attr>>16)
            allowed_types=(0,stat.S_IFDIR) if entry.is_dir() else (0,stat.S_IFREG)
            if mode not in allowed_types or entry.flag_bits&1: raise ValueError('linked/encrypted or invalid control JAR entry type')
            if entry.is_dir():
                if name not in ('META-INF/','ocelot/','ocelot/spike/'): raise ValueError('unexpected control JAR directory')
                if entry.file_size!=0: raise ValueError('nonempty control JAR directory')
                if jar.read(entry)!=b'': raise ValueError('nonempty control JAR directory')  # Verify CRC too.
                continue
            if not (name in ('META-INF/MANIFEST.MF','robot.lua') or
                    re.fullmatch(r'ocelot/spike/[A-Za-z][A-Za-z0-9_$]*\.class',name)):
                raise ValueError('unexpected control JAR entry: '+name)
            total+=entry.file_size
            if entry.file_size>FILE_LIMIT or total>JAR_LIMIT: raise ValueError('expanded control JAR byte bound')
            content=jar.read(entry)  # CRC verification, including inputs not otherwise interpreted.
            if name.endswith('.class') and not content.startswith(b'\xca\xfe\xba\xbe'):
                raise ValueError('invalid control class')
        required={'META-INF/MANIFEST.MF','ocelot/spike/RobotSpike.class','ocelot/spike/PacingPlugin.class','robot.lua'}
        if not required<=names: raise ValueError('missing required control JAR entry')
        manifest=jar.read('META-INF/MANIFEST.MF').decode('utf-8').replace('\r','')
        for line in REQUIRED_MANIFEST.splitlines():
            if line and line not in manifest.splitlines(): raise ValueError('control manifest mismatch')


def build(root,control,output,version):
    if not isinstance(version,str) or not re.fullmatch(r'0\.1\.0(?:-rc\.[1-9][0-9]{0,2})?',version):
        raise ValueError('version must be 0.1.0 or 0.1.0-rc.N')
    deadline=time.monotonic()+30
    def check():
        if time.monotonic()>=deadline: raise TimeoutError('package deadline exceeded')
    root=_no_link(root); output=Path(output).absolute()
    if output.suffix!='.zip': raise ValueError('package output must end in .zip')
    _no_link(output.parent)  # Existing, nonlinked parent required; no implicit directory ownership.
    checksum=output.with_suffix('.zip.sha256')
    for path in (output,checksum):
        try: path.lstat()
        except FileNotFoundError: pass
        else: raise FileExistsError(str(path))
    payload={name:_read(root/name,FILE_LIMIT,check) for name in FILES}
    if json.loads(payload['runtime-profile.json']).get('profileId')!=PROFILE_ID:
        raise ValueError('package runtime profile mismatch')
    data=_read(control,JAR_LIMIT,check); _jar(data,check)
    payload['lib/robot-control.jar']=data
    records={name:_record(content) for name,content in sorted(payload.items())}
    release={'schemaVersion':1,'version':version,'profileId':PROFILE_ID,
             'controlJar':dict(path='lib/robot-control.jar',**records['lib/robot-control.jar']),
             'files':records}
    payload['release.json']=(json.dumps(release,sort_keys=True,indent=2)+'\n').encode('utf-8')
    if len(payload)>128 or sum(map(len,payload.values()))>TOTAL_LIMIT: raise ValueError('package total bound')
    created=[]
    try:
        with output.open('xb') as stream:
            created.append(output)
            with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_STORED) as archive:
                for name,content in sorted(payload.items()):
                    check()
                    entry=zipfile.ZipInfo(name,(1980,1,1,0,0,0)); entry.create_system=3
                    entry.external_attr=(stat.S_IFREG | (0o755 if name=='robot-runner' else 0o644))<<16
                    archive.writestr(entry,content)
                if stream.tell()>TOTAL_LIMIT: raise ValueError('package output byte bound')
        data=_read(output,TOTAL_LIMIT,check); digest=hashlib.sha256(data).hexdigest()
        with checksum.open('x',encoding='utf-8',newline='\n') as stream:
            created.append(checksum); stream.write(digest+'  '+output.name+'\n')
        return {'status':'packaged','version':version,'path':str(output),'sha256':digest,
                'size':len(data),'files':len(payload),'checksum':str(checksum)}
    except BaseException:
        for path in reversed(created): path.unlink(missing_ok=True)
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True); parser.add_argument('--version',required=True)
    parser.add_argument('--control-jar',default=str(HERE/'build/libs/robot-spike.jar'))
    args=parser.parse_args()
    try: result=build(HERE,args.control_jar,args.output,args.version)
    except (ValueError,OSError,TimeoutError,zipfile.BadZipFile) as exc:
        print(json.dumps({'status':'error','message':str(exc)})); return 1
    print(json.dumps(result,sort_keys=True)); return 0


if __name__=='__main__': sys.exit(main())
