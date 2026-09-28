"""Checked local bootstrap/build for the isolated Minecraft 1.12.2 experiment."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import zipfile

from supervisor import NO_WINDOW

ARTIFACTS = [
    dict(name='gradle-4.9-bin.zip', url='https://services.gradle.org/distributions/gradle-4.9-bin.zip',
         sha256='e66e69dce8173dd2004b39ba93586a184628bc6c28461bc771d6835f7f9b0d28'),
    dict(name='forge-installer.jar', url='https://maven.minecraftforge.net/net/minecraftforge/forge/1.12.2-14.23.5.2860/forge-1.12.2-14.23.5.2860-installer.jar',
         sha256='ea7c33ba95e3993a98d0e9e38168c0759ec323a18675a71d938e1f3f70e6e8e7'),
    dict(name='OpenComputers-1.8.9a.jar', url='https://github.com/MightyPirates/OpenComputers/releases/download/1.12.2-forge/1.8.9a/OpenComputers-MC1.12.2-1.8.9a%2B8ca336f.jar',
         sha256='82723dd69fea7496e7dc448aa97f48295efb642547d3e66de45263e9b9063d72'),
]
CONFIG = '''opencomputers {
  version = "1.8.9a"
  internet { enableHttp = false, enableTcp = false }
  power.ignorePower = false
  computer.executionDelay = 12
}
'''


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def acquire(path, url, expected, *, run=None, headers=()):
    from supervisor import _no_link
    path = Path(os.path.abspath(path))
    ancestor = path
    while True:
        try:
            ancestor.lstat()
            break
        except FileNotFoundError:
            ancestor = ancestor.parent
    _no_link(ancestor)  # Includes a nested cache junction before hashing, mkdir or download.
    if path.exists():
        if not path.is_file() or path.stat().st_size > 128 * 1024 * 1024 or sha256(path) != expected:
            raise ValueError('Cached artifact hash mismatch (preserved): ' + str(path))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    _no_link(path.parent)
    partial = path.with_suffix(path.suffix + '.partial')
    try:
        partial.lstat()
    except FileNotFoundError:
        pass
    else:
        raise ValueError('Previous partial download exists (inspect before removal): ' + str(partial))
    try:
        command = ['curl', '--fail', '--location', '--proto', '=https', '--proto-redir', '=https',
                   '--max-time', '180', '--max-filesize', str(128 * 1024 * 1024)]
        for header in headers: command += ['--header', header]
        command += ['--output', str(partial), url]
        (run or run_checked)(command, timeout=190)
        _no_link(partial)
        if not partial.is_file() or partial.stat().st_size > 128 * 1024 * 1024 or sha256(partial) != expected:
            raise ValueError('Downloaded artifact hash mismatch: ' + url)
        partial.replace(path)
    finally:
        if partial.exists(): partial.unlink()


def unpack(archive, target, limit=512 * 1024 * 1024):
    target = Path(target)
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        if len(infos) > 10000 or sum(i.file_size for i in infos) > limit:
            raise ValueError('Archive expansion bound')
        for info in infos:
            name = PurePosixPath(info.filename)
            if name.is_absolute() or '..' in name.parts or ':' in info.filename or '\\' in info.filename:
                raise ValueError('Unsafe archive path: ' + info.filename)
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Archive symlink forbidden')
            destination = target / info.filename
            for parent in (destination, *destination.parents):
                if parent.is_symlink() or (hasattr(parent, 'is_junction') and parent.is_junction()):
                    raise ValueError('Extraction link forbidden')
        target.mkdir(parents=True, exist_ok=True)
        z.extractall(target)
    launcher = target / 'gradle-4.9/bin/gradle'
    if launcher.exists(): launcher.chmod(0o755)


def verify_distribution(archive, target):
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            if info.is_dir(): continue
            file = Path(target) / info.filename
            if file.is_symlink() or any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in file.parents):
                raise ValueError('Extracted distribution link forbidden')
            if file.stat().st_size != info.file_size or sha256(file) != hashlib.sha256(z.read(info)).hexdigest():
                raise ValueError('Extracted distribution mismatch (preserved): ' + str(file))


def run_checked(command, timeout, **kwargs):
    # Reuse the experiment's process cleanup owner for build-tool descendants too.
    from supervisor import _stop_tree
    # A hidden Windows child needs explicit handles to preserve redirected logs.
    kwargs.setdefault('stdout', sys.stdout)
    kwargs.setdefault('stderr', sys.stderr)
    process = subprocess.Popen(command, start_new_session=os.name != 'nt',
                               creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | NO_WINDOW) if os.name == 'nt' else 0, **kwargs)
    try:
        code = process.wait(timeout=timeout)
        if code: raise subprocess.CalledProcessError(code, command)
    finally:
        _stop_tree(process)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java-home', default=os.environ.get('JAVA_HOME'))
    parser.add_argument('--prepare-server', action='store_true', help='Install the isolated local server template; does not launch it')
    args = parser.parse_args()
    if not args.java_home: parser.error('Provide Java 8 JDK --java-home')
    root = Path(__file__).resolve().parent
    cache = root / '.cache'; cache.mkdir(exist_ok=True)
    from supervisor import _no_link, _inventory, COPY_BYTES_LIMIT, COPY_FILES_LIMIT
    _no_link(cache)
    home = Path(args.java_home).resolve()
    java = home / 'bin' / ('java.exe' if os.name == 'nt' else 'java')
    javac = home / 'bin' / ('javac.exe' if os.name == 'nt' else 'javac')
    version = subprocess.run([str(javac), '-version'], capture_output=True, text=True, timeout=10, check=True, creationflags=NO_WINDOW)
    if 'javac 1.8.' not in version.stdout + version.stderr:
        raise ValueError('Java 8 JDK required')
    for artifact in ARTIFACTS:
        acquire(cache / artifact['name'], artifact['url'], artifact['sha256'])
    distribution = cache / 'distribution'
    if not (distribution / 'gradle-4.9/lib/gradle-launcher-4.9.jar').exists():
        unpack(cache / ARTIFACTS[0]['name'], distribution)
    verify_distribution(cache / ARTIFACTS[0]['name'], distribution)
    env = dict(os.environ, JAVA_HOME=str(home))
    env['PATH'] = str(home / 'bin') + os.pathsep + env.get('PATH', '')
    # Invoke Gradle's checked distribution directly, avoiding shell quoting and wrapper binaries.
    command = [str(java), '-classpath', str(distribution / 'gradle-4.9/lib/gradle-launcher-4.9.jar'),
               'org.gradle.launcher.GradleMain', '--no-daemon', '--gradle-user-home', str(cache / 'gradle'), 'test', 'build']
    run_checked(command, cwd=root, env=env, timeout=900)
    if args.prepare_server:
        from runtime_profile import OVERLAYS
        for artifact in OVERLAYS:
            acquire(cache / 'runtime-libraries' / artifact['name'], artifact['url'], artifact['sha256'])
        server = cache / 'server'; server.mkdir(exist_ok=True)
        _no_link(server)
        _inventory(server, COPY_BYTES_LIMIT, COPY_FILES_LIMIT)
        forge = server / 'forge-1.12.2-14.23.5.2860.jar'
        if not forge.exists():
            run_checked([str(java), '-jar', str(cache / 'forge-installer.jar'), '--installServer'],
                        cwd=server, env=env, timeout=600)
        (server / 'mods').mkdir(exist_ok=True)
        oc = server / 'mods/OpenComputers.jar'
        if not oc.exists(): shutil.copyfile(cache / 'OpenComputers-1.8.9a.jar', oc)
        settings = server / 'config/opencomputers/settings.conf'
        settings.parent.mkdir(parents=True, exist_ok=True)
        if not settings.exists(): settings.write_text(CONFIG, encoding='utf-8')
        acceptance = server / 'eula.txt'
        if not acceptance.exists(): acceptance.write_text('eula=true\n', encoding='ascii')
        from supervisor import PINNED
        for relative, expected in PINNED.items():
            if sha256(server / relative.removeprefix('template/')) != expected:
                raise ValueError('Server base artifact hash mismatch: ' + relative)
        print(json.dumps({'template': str(server), 'control_jar': str(root / 'build/libs/robot-spike.jar')}))


if __name__ == '__main__':
    main()
