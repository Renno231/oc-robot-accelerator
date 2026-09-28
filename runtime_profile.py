"""Pinned server-library profile; overlay only fresh execution copies, never templates.

Setup acquires the maintained logging pair. Jobs have no acquisition/network fallback.
The exact original library inventory and effective hashes remain distinct evidence.
"""
from pathlib import Path

import runner_scenario as scenario
import supervisor

HERE = Path(__file__).resolve().parent
PROFILE_ID = 'mc1.12.2-forge2860-oc1.8.9a-log4j2.25.5-v1'
TEMPLATE_JARS = scenario.read_json(HERE/'runtime-profile.json')['templateJars']
API = dict(name='log4j-api-2.25.5.jar', size=351427,
           sha256='64777f73ea0b3104c04eb82befbdccc30a425a19e83ad06cb2f93aa303511863',
           target='libraries/org/apache/logging/log4j/log4j-api/2.15.0/log4j-api-2.15.0.jar',
           url='https://repo.maven.apache.org/maven2/org/apache/logging/log4j/log4j-api/2.25.5/log4j-api-2.25.5.jar')
CORE = dict(name='log4j-core-2.25.5.jar', size=2020932,
            sha256='050c4f85deb48b055e9c041ac39043fbb79ce477841a11a1eb2969c86c6a0072',
            target='libraries/org/apache/logging/log4j/log4j-core/2.15.0/log4j-core-2.15.0.jar',
            url='https://repo.maven.apache.org/maven2/org/apache/logging/log4j/log4j-core/2.25.5/log4j-core-2.25.5.jar')
OVERLAYS = (API, CORE)
REQUIRED_CLASSES = ('org.apache.logging.log4j.LogManager', 'org.apache.logging.log4j.Logger',
                    'org.apache.logging.log4j.core.LoggerContext',
                    'org.apache.logging.log4j.core.config.Configuration',
                    'org.apache.logging.log4j.core.lookup.JndiLookup')


def _verify(path, expected, check):
    check()
    path=supervisor._no_link(path)
    if (not path.is_file() or path.stat().st_size != expected['size'] or
            supervisor._digest(path,float('inf'),check=check) != expected['sha256']):
        raise ValueError('runtime profile artifact mismatch: '+str(path))


def verify_template(root, check=lambda: None, *, control_installed=False):
    """Validate the pristine loader inventory for setup and execution-copy overlay."""
    root=supervisor._no_link(root)
    inventory=supervisor._inventory(root,supervisor.COPY_BYTES_LIMIT,supervisor.RUNTIME_FILES_LIMIT,check=check)
    # User program/world data is not a classpath extension; only loader locations count.
    found={path.as_posix() for path,size in inventory if path.suffix.lower()=='.jar' and
           (len(path.parts)==1 or path.parts[0] in ('libraries','mods'))}
    expected_jars = set(TEMPLATE_JARS) | ({'mods/robot-spike.jar'} if control_installed else set())
    if found != expected_jars:
        raise ValueError('runtime profile JAR inventory mismatch')
    for name,expected in TEMPLATE_JARS.items(): _verify(root/name,expected,check)


def apply(root, cache, check=lambda: None):
    """Preflight the entire pinned JAR set before replacing only its logging pair."""
    root,cache=supervisor._no_link(root),supervisor._no_link(cache)
    verify_template(root,check,control_installed=True)
    for artifact in OVERLAYS: _verify(cache/artifact['name'],artifact,check)
    hashes={}
    for artifact in OVERLAYS:
        check()
        # This target is an already-verified private execution copy, not a caller template.
        with (cache/artifact['name']).open('rb') as source, (root/artifact['target']).open('wb') as target:
            copied=0
            while True:
                check(); data=source.read(128*1024)
                if not data: break
                copied+=len(data)
                if copied > artifact['size']: raise ValueError('runtime overlay grew during copying')
                target.write(data)
        _verify(root/artifact['target'],artifact,check)
        hashes['runtime-profile/'+artifact['target']]=artifact['sha256']
    return hashes


def verify_proof(root):
    """Require actual selected API/Core/context/factory identity, not filenames alone."""
    value=scenario.read_json(Path(root)/'runtime-logging.json',64*1024)
    if (not isinstance(value,dict) or type(value.get('schemaVersion')) != int or value['schemaVersion'] != 1 or
            value.get('profileId') != PROFILE_ID or not isinstance(value.get('classes'),dict)):
        raise ValueError('runtime logging proof identity invalid')
    classes=value['classes']
    required=set(REQUIRED_CLASSES)
    for name in ('contextClass','factoryClass'):
        actual=value.get(name)
        if not isinstance(actual,str) or not actual.startswith('org.apache.logging.log4j.core.'):
            raise ValueError('runtime logging provider not Core')
        required.add(actual)
    if not required.issubset(classes) or len(classes)>32:
        raise ValueError('runtime logging class evidence missing or excessive')
    for name,record in classes.items():
        if not name.startswith('org.apache.logging.log4j.') or not isinstance(record,dict):
            raise ValueError('runtime logging class evidence invalid')
        artifact=CORE if name.startswith('org.apache.logging.log4j.core.') else API
        if (record.get('source') != artifact['target'] or record.get('version') != '2.25.5' or
                record.get('sha256') != artifact['sha256']):
            raise ValueError('runtime logging source/version/hash mismatch: '+name)
    return value
