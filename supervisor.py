"""Bounded, isolated Minecraft 1.12.2 robot spike process supervisor (stdlib only)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time

# Detached workers have no console; every child they launch must keep that property.
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

COPY_BYTES_LIMIT = 1024 * 1024 * 1024
COPY_FILES_LIMIT = 10000
RUNTIME_BYTES_LIMIT = 2 * 1024 * 1024 * 1024
RUNTIME_FILES_LIMIT = 20000
TRACE_LIMIT = 32 * 1024 * 1024
LOG_LIMIT = 8 * 1024 * 1024
RESULT_LIMIT = 1024 * 1024
FORGE_JAR = 'forge-1.12.2-14.23.5.2860.jar'
REQUIRED = (FORGE_JAR, 'minecraft_server.1.12.2.jar', 'mods/OpenComputers.jar',
            'config/opencomputers/settings.conf', 'eula.txt')
PINNED = {
    'template/' + FORGE_JAR: 'cd3fbf85d7ca744507fd6a37a41b90122d43e616a4f8962332b1b658655e8a64',
    'template/minecraft_server.1.12.2.jar': 'fe1f9274e6dad9191bf6e6e8e36ee6ebc737f373603df0946aafcded0d53167e',
    'template/mods/OpenComputers.jar': '82723dd69fea7496e7dc448aa97f48295efb642547d3e66de45263e9b9063d72',
}
PROPERTIES = '''server-ip=127.0.0.1
server-port=0
enable-rcon=false
enable-query=false
online-mode=true
snooper-enabled=false
level-type=FLAT
level-seed=robot-spike-1122
generate-structures=false
difficulty=0
gamemode=0
spawn-monsters=false
spawn-animals=false
'''


def _no_link(path):
    """Reject symlinks and Windows reparse points, including ancestor directories."""
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError('link/reparse path forbidden: ' + str(part))
    return path


def _inventory(root, byte_limit, file_limit, deadline=None, live=False, check=None):
    entries = []
    total = 0
    directory_count = 0
    def scan_error(exc):
        if live and isinstance(exc,FileNotFoundError): return
        raise exc
    for parent, dirs, files in os.walk(root, followlinks=False, onerror=scan_error):
        if check is not None:
            check()
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError('wall timeout during directory scan')
        directory_count += len(dirs)
        if directory_count + len(entries) + len(files) > file_limit:
            raise ValueError('directory entry bound exceeded')
        for name in dirs + files:
            path = Path(parent) / name
            try:
                info = path.lstat()
            except FileNotFoundError:
                if live:  # Server atomically replaces world files while we inspect them.
                    continue
                raise
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError('link/reparse entry forbidden: ' + str(path))
            if name in files:
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError('non-regular entry forbidden: ' + str(path))
                total += info.st_size
                entries.append((path.relative_to(root), info.st_size))
                if total > byte_limit or len(entries) > file_limit:
                    raise ValueError('directory byte/file bound exceeded')
    return entries


def _digest(path, deadline, check=None):
    hash_value = hashlib.sha256()
    with path.open('rb') as source:
        while True:
            if check is not None:
                check()
            if time.monotonic() >= deadline:
                raise TimeoutError('wall timeout during hash')
            chunk = source.read(1024 * 1024)
            if not chunk:
                return hash_value.hexdigest()
            hash_value.update(chunk)


class Cancelled(Exception):
    """Cooperative caller cancellation, handled by the process owner."""


def _prepare(template, jar, root, deadline, check=lambda: None, runner=False):
    template = _no_link(template)
    jar = _no_link(jar)
    if not template.is_dir() or not jar.is_file():
        raise ValueError('template directory and control jar file required')
    entries = _inventory(template, COPY_BYTES_LIMIT, COPY_FILES_LIMIT, deadline, check=check)
    names = {str(relative).replace('\\', '/') for relative, _ in entries}
    if os.name == 'nt' and any(len(str(root / rel)) >= 260 for rel, _ in entries):
        raise ValueError('Windows Java 8 path limit: use a shorter output/jobs root')
    if runner:
        reserved = ('world', 'program', 'runner-scenario.json', 'observations.ndjson',
                    'program-inputs.json', 'program.log', 'observations-status.json',
                    '.observations-status.json.tmp', 'runtime-logging.json')
        if any((template / name).exists() for name in reserved):
            raise ValueError('runner template contains reserved scenario/output path')
        if any(name.startswith('mods/') and name != 'mods/OpenComputers.jar' for name in names):
            raise ValueError('runner requires pinned base mod profile')
        entries = [(rel, size) for rel, size in entries if rel.as_posix() not in ('scenario.json', 'tool.json')]
    if not set(REQUIRED).issubset(names) or not any(name.startswith('libraries/') for name in names):
        raise ValueError('incomplete prepared server template')
    if (template / 'eula.txt').stat().st_size > 65536:
        raise ValueError('eula.txt byte bound exceeded')
    eula = (template / 'eula.txt').read_text(encoding='utf-8')
    if {'result.json', 'supervisor.json', 'stdout.log', 'stderr.log', 'trace.ndjson',
        'mods/robot-spike.jar'} & names:
        raise ValueError('template contains reserved output/control file')
    if not any(line.strip().lower() == 'eula=true' for line in eula.splitlines()):
        raise ValueError('eula.txt must already contain eula=true')
    jar_size = jar.stat().st_size
    template_bytes = sum(size for _, size in entries)
    if jar_size + template_bytes > COPY_BYTES_LIMIT:
        raise ValueError('copy byte bound exceeded')
    hashes = {}
    for relative, expected_size in entries:
        check()
        if str(relative).replace('\\', '/') == 'server.properties':
            continue  # generated properties always override template
        source = template / relative
        dest = root / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        _no_link(source)  # recheck at use time
        with source.open('rb') as inp, dest.open('xb') as out:
            copied = 0
            while True:
                check()
                if time.monotonic() >= deadline:
                    raise TimeoutError('wall timeout during copy')
                chunk = inp.read(1024 * 1024)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > expected_size or copied > COPY_BYTES_LIMIT:
                    raise ValueError('source changed during copy')
                out.write(chunk)
        if copied != expected_size:
            raise ValueError('source changed during copy')
        hashes['template/' + relative.as_posix()] = _digest(dest, deadline, check)
    control = root / 'mods' / 'robot-spike.jar'
    if control.exists():
        raise ValueError('template already includes robot-spike.jar')
    with jar.open('rb') as inp, control.open('xb') as out:
        copied = 0
        while True:
            check()
            if time.monotonic() >= deadline:
                raise TimeoutError('wall timeout during control copy')
            chunk = inp.read(1024 * 1024)
            if not chunk:
                break
            copied += len(chunk)
            if copied > jar_size or copied + template_bytes > COPY_BYTES_LIMIT:
                raise ValueError('control jar changed or copy bound exceeded')
            out.write(chunk)
    if copied != jar_size:
        raise ValueError('control jar changed during copy')
    hashes['control/robot-spike.jar'] = _digest(control, deadline, check)
    (root / 'server.properties').write_text(PROPERTIES, encoding='ascii')
    hashes['generated/server.properties'] = _digest(root / 'server.properties', deadline, check)
    return hashes


def _drain(pipe, destination, overflow):
    used = 0
    try:
        with destination.open('wb') as log, pipe:
            while True:
                data = pipe.read(65536)
                if not data:
                    break
                available = max(0, LOG_LIMIT - used)
                log.write(data[:available])
                used += len(data)
                if used > LOG_LIMIT:
                    overflow.set()
    except OSError:
        overflow.set()


def _stop_tree(process):
    if os.name == 'nt':
        # An exited direct process may have descendants, but its PID can be reused.
        if process.poll() is None:
            try:
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=False,
                               creationflags=NO_WINDOW)
            except (OSError, subprocess.TimeoutExpired):
                if process.poll() is None:
                    process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def _result(root, mode, ticks, scenario_id=None):
    path = root / 'result.json'
    _no_link(path)
    if path.stat().st_size > RESULT_LIMIT:
        raise ValueError('result.json exceeds 1MiB')
    with path.open('rb') as source:
        payload = source.read(RESULT_LIMIT + 1)
    if len(payload) > RESULT_LIMIT:
        raise ValueError('result.json exceeds 1MiB')
    value = json.loads(payload)
    if not isinstance(value, dict) or value.get('status') != 'passed':
        reason = value.get('reason', '') if isinstance(value, dict) else 'invalid result object'
        raise ValueError('result status not passed: ' + str(reason)[:2048])
    if value.get('mode') != mode or type(value.get('ticks')) is not int or not 0 <= value['ticks'] <= ticks:
        raise ValueError('result mode/tick bound invalid')
    if type(value.get('elapsedNanos')) is not int or value['elapsedNanos'] < 0:
        raise ValueError('result elapsedNanos invalid')
    if scenario_id is not None:
        if (value.get('runnerSchemaVersion') != 1 or value.get('scenarioId') != scenario_id or
                not isinstance(value.get('program'), dict) or value['program'].get('status') != 'returned'):
            raise ValueError('runner result identity/program completion invalid')
    return value


def execute(args, *, root=None, start=None, deadline=None, check=lambda: None,
            prepare=None, scenario_id=None, on_launch=lambda pid: None):
    """Structured process owner. Caller preparation shares the same budget and cancellation.

    ``prepare`` only installs already-frozen scenario inputs; it does not own a process.
    Cleanup is always attempted, with separate bounded grace after deadline/cancellation.
    """
    start = time.monotonic() if start is None else start
    deadline = start + args.timeout if deadline is None else deadline
    output = _no_link(args.output_root)
    template = _no_link(args.template)
    if not output.is_dir() or output == template or output in template.parents or template in output.parents:
        raise ValueError('output-root must be an existing dedicated directory outside template')
    if root is None:
        import tempfile
        root = Path(tempfile.mkdtemp(prefix='robot-', dir=output))
    else:
        root = Path(root)
        if root.parent != output or root.exists():
            raise ValueError('runtime must be a fresh direct output child')
        root.mkdir()
    report = {'status': 'failed', 'reason': '', 'return_code': None, 'elapsed_wall_seconds': 0,
              'sha256': {}, 'command': [], 'cleanup_ok': True, 'cancelled': False}
    process = None
    threads = []
    overflow = threading.Event()
    try:
        check()
        report['sha256'] = _prepare(args.template, args.control_jar, root, deadline, check, scenario_id is not None)
        identity = getattr(args,'control_identity',None)
        if getattr(args,'runtime_libraries',None) is not None:
            if (not isinstance(identity,dict) or type(identity.get('size')) is not int or
                    not 0 < identity['size'] <= 16*1024*1024 or
                    identity.get('size') != (root/'mods/robot-spike.jar').stat().st_size or
                    identity.get('sha256') != report['sha256']['control/robot-spike.jar']):
                raise ValueError('selected control identity changed before execution')
        for name, expected in PINNED.items():
            if report['sha256'].get(name) != expected:
                raise ValueError('base artifact SHA-256 mismatch: ' + name)
        report['profile'] = ('extended' if any(name.startswith('template/mods/') and
                            name != 'template/mods/OpenComputers.jar' for name in report['sha256'])
                             else 'base')
        if prepare is not None:
            report['sha256'].update(prepare(root, check))
        if scenario_id is not None:
            import runtime_profile
            report['runtimeProfile'] = runtime_profile.PROFILE_ID
            libraries = getattr(args,'runtime_libraries',None) or Path(__file__).resolve().parent / '.cache/runtime-libraries'
            report['sha256'].update(runtime_profile.apply(root, libraries, check))
        _inventory(root, COPY_BYTES_LIMIT, RUNTIME_FILES_LIMIT, deadline, check=check)
        java_path = shutil.which(args.java)
        if java_path is None:
            raise ValueError('java executable not found')
        java_executable = _no_link(java_path)
        report['sha256']['runtime/java'] = _digest(java_executable, deadline, check)
        command = [str(java_executable), '-Xmx2G', '-Dfml.disableVersionCheck=true',
                   '-Drobotspike.root=' + str(root.resolve()),
                   '-Drobotspike.mode=' + args.mode, '-Drobotspike.maxTicks=' + str(args.ticks),
                   '-Drobotspike.timeoutSeconds=' + str(args.timeout)]
        if scenario_id is not None:
            command.append('-Drobotrunner.runtimeProfile=' + runtime_profile.PROFILE_ID)
        command += ['-jar', FORGE_JAR, 'nogui']
        report['command'] = command
        check()
        if time.monotonic() >= deadline:
            raise TimeoutError('wall timeout before launch')
        flags = (subprocess.CREATE_NEW_PROCESS_GROUP | NO_WINDOW) if os.name == 'nt' else 0
        process = subprocess.Popen(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=flags, start_new_session=os.name != 'nt', stdin=subprocess.DEVNULL)
        on_launch(process.pid)
        for pipe, filename in ((process.stdout, 'stdout.log'), (process.stderr, 'stderr.log')):
            thread = threading.Thread(target=_drain, args=(pipe, root / filename, overflow), daemon=True)
            thread.start()
            threads.append(thread)
        while True:
            check()
            if overflow.is_set():
                raise ValueError('output log byte bound exceeded')
            _inventory(root, RUNTIME_BYTES_LIMIT, RUNTIME_FILES_LIMIT, deadline, live=True, check=check)
            for name, cap in (('trace.ndjson', TRACE_LIMIT), ('observations.ndjson', 32 * 1024 * 1024),
                              ('program.log', RESULT_LIMIT), ('program-inputs.json', RESULT_LIMIT),
                              ('observations-status.json', 64 * 1024), ('.observations-status.json.tmp', 64 * 1024),
                              ('runtime-logging.json', 64 * 1024)):
                artifact = root / name
                try:
                    size = artifact.stat().st_size
                except FileNotFoundError:
                    continue  # In particular, atomic status publication consumes its temporary file.
                if size > cap:
                    raise ValueError(name + ' byte bound exceeded')
            if time.monotonic() >= deadline:
                raise TimeoutError('wall timeout including startup')
            if process.poll() is not None:
                break
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        for thread in threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in threads) or overflow.is_set():
            raise ValueError('output drain incomplete or output byte bound exceeded')
        report['return_code'] = process.returncode
        if process.returncode != 0:
            raise ValueError('server nonzero exit: ' + str(process.returncode))
        _result(root, args.mode, args.ticks, scenario_id)
        if scenario_id is not None:
            report['runtimeLogging'] = runtime_profile.verify_proof(root)
        check()
        if time.monotonic() >= deadline:
            raise TimeoutError('wall timeout including result validation')
        report['status'], report['reason'] = 'passed', 'result passed and process exited zero'
    except (KeyboardInterrupt, Cancelled) as exc:
        report['reason'] = str(exc) or 'cancelled by KeyboardInterrupt'
        report['cancelled'] = True
    except (OSError, ValueError, TimeoutError, json.JSONDecodeError) as exc:
        report['reason'] = str(exc) or type(exc).__name__
    finally:
        if process is not None:
            try:
                _stop_tree(process)
            except (OSError, subprocess.TimeoutExpired) as exc:
                report['status'], report['reason'] = 'failed', 'process cleanup failed: ' + str(exc)
                report['cleanup_ok'] = False
            report['return_code'] = process.poll()
        for thread in threads:
            thread.join(timeout=1)
        if any(thread.is_alive() for thread in threads):
            report['cleanup_ok'] = False
            report['status'], report['reason'] = 'failed', 'output cleanup incomplete'
        report['deadline_overrun_seconds'] = round(max(0, time.monotonic() - deadline), 3)
        if time.monotonic() >= deadline and report['status'] == 'passed':
            report['status'], report['reason'] = 'failed', 'wall timeout including cleanup'
        report['elapsed_wall_seconds'] = round(time.monotonic() - start, 3)
        (root / 'supervisor.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return {'run_directory': str(root), 'report': report}


def run(args):
    outcome = execute(args)
    report = outcome['report']
    print(json.dumps({'run_directory': outcome['run_directory'], 'status': report['status'], 'reason': report['reason']}))
    return 0 if report['status'] == 'passed' else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--template', required=True)
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--control-jar', required=True)
    parser.add_argument('--java', required=True)
    parser.add_argument('--mode', required=True, choices=('baseline', 'unpaced', 'coordinated', 'paced'))
    parser.add_argument('--ticks', type=int, default=10000)
    parser.add_argument('--timeout', type=int)
    args = parser.parse_args(argv)
    if args.timeout is None:
        args.timeout = 600 if args.mode in ('baseline', 'paced') else 120
    if not 1 <= args.ticks <= 10000 or not 1 <= args.timeout <= 600:
        parser.error('ticks must be 1..10000 and timeout 1..600')
    try:
        return run(args)
    except (OSError, ValueError) as exc:
        print(json.dumps({'run_directory': None, 'status': 'failed', 'reason': str(exc)}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
