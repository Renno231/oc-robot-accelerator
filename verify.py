"""Canonical developer verification; explicit profiles preserve proportional evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from bootstrap import run_checked

HERE = Path(__file__).resolve().parent


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--checks', nargs='+', choices=['source', 'runtime', 'package', 'viewer'], default=['source'])
    p.add_argument('--output', required=True, help='New evidence directory; use a short path for runtime checks')
    p.add_argument('--java-home', help='Java 8 JDK for source/build verification')
    p.add_argument('--java', help='Java 8 executable for runtime/package checks')
    p.add_argument('--archive', help='Checksummed release ZIP for fresh package setup/run verification')
    p.add_argument('--jobs-root', help='Existing recording for viewer verification')
    p.add_argument('--job', help='Existing recorded job ID for viewer verification')
    p.add_argument('--version', default='0.1.0-rc.2')
    return p


def steps(args, output):
    result = []
    py = sys.executable
    java = args.java
    if not java and args.java_home:
        java = str(Path(args.java_home).resolve() / 'bin' / ('java.exe' if os.name == 'nt' else 'java'))
    for check in dict.fromkeys(args.checks):
        if check == 'source':
            if not args.java_home:
                raise ValueError('source checks require --java-home (Java 8 JDK)')
            result.extend([
                ('python', [py, '-m', 'unittest', 'discover', '-p', 'test_*.py', '-v'], 240),
                ('java-build', [py, str(HERE / 'bootstrap.py'), '--java-home', args.java_home], 1200),
                ('viewer-unit', ['node', str(HERE / 'viewer/test-interactions.js')], 30),
                ('package', [py, str(HERE / 'package_release.py'), '--version', args.version,
                             '--output', str(output / 'release.zip')], 60),
                ('package-repeat', [py, str(HERE / 'package_release.py'), '--version', args.version,
                                    '--output', str(output / 'repeat.zip')], 60),
            ])
        elif check == 'runtime':
            if not java:
                raise ValueError('runtime checks require --java or --java-home')
            result.append(('runtime', [py, str(HERE / 'verify_runner.py'), '--output', str(output / 'runtime'),
                                       '--java', java], 1800))
        elif check == 'package':
            if not java or not args.archive:
                raise ValueError('package checks require --java (or --java-home) and --archive')
            result.append(('installed-package', [py, str(HERE / 'verify_package.py'), '--archive',
                str(Path(args.archive).resolve()), '--root', str(output / 'installed'), '--java', java], 1800))
        else:
            if not args.jobs_root or not args.job:
                raise ValueError('viewer checks require --jobs-root and --job')
            result.append(('browser', [py, str(HERE / 'verify_viewer.py'), '--output', str(output / 'browser'),
                '--jobs-root', str(Path(args.jobs_root).resolve()), '--job', args.job], 300))
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    output = Path(args.output).absolute()
    commands = steps(args, output)  # Validate all options before creating evidence.
    output.mkdir(parents=True, exist_ok=False)
    report = {'schemaVersion': 1, 'status': 'running', 'cwd': str(HERE), 'steps': []}
    def save():
        (output / 'verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    save()
    try:
        for name, command, timeout in commands:
            row = {'name': name, 'command': command, 'timeoutSeconds': timeout, 'log': name + '.log', 'status': 'running'}
            report['steps'].append(row)
            save()
            started = time.monotonic()
            try:
                with (output / row['log']).open('xb') as log:
                    run_checked(command, cwd=HERE, stdout=log, stderr=log, timeout=timeout)
                row['status'] = 'passed'
            except BaseException:
                row['status'] = 'failed'
                raise
            finally:
                row['elapsedSeconds'] = time.monotonic() - started
                save()
            print('PASS: ' + name, flush=True)
        if 'source' in args.checks:
            digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            first = digest(output / 'release.zip')
            if first != digest(output / 'repeat.zip'):
                raise ValueError('Package rebuild is not byte-identical')
            report['packageSha256'] = first
            report['packageDeterministic'] = True
        report['status'] = 'passed'
    except BaseException as exc:
        report.update(status='failed', error=repr(exc))
        print('FAIL: ' + repr(exc), file=sys.stderr)
    finally:
        save()
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
