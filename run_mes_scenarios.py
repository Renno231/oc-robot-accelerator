"""Run the headless manufacturing acceptance matrix through the public runner."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from build_machine_comparisons import prepare
from compare_machine_jobs import read_job
from supervisor import NO_WINDOW


def communicate(args):
    if not args.worker:
        return
    subprocess.run(['cmd.exe', '/d', '/c', 'orca', 'orchestration', 'send',
                    '--from', args.worker, '--type', 'heartbeat', '--subject', 'alive',
                    '--task-id', args.task, '--dispatch-id', args.dispatch,
                    '--phase', 'verifying'], check=True, creationflags=NO_WINDOW)
    result = subprocess.run(['cmd.exe', '/d', '/c', 'orca', 'orchestration', 'check',
                             '--terminal', args.worker, '--json'], capture_output=True,
                            text=True, check=True, creationflags=NO_WINDOW)
    value = json.loads(result.stdout)
    if value.get('result', {}).get('count', 0) and not value['result'].get('replayed', False):
        print(result.stdout, flush=True)
        raise RuntimeError('Coordinator follow-up: pause acceptance matrix')


def run(args):
    args.root.mkdir(parents=True, exist_ok=True)
    record = args.root / 'runs.json'
    rows = json.loads(record.read_text()) if record.exists() else []
    cases = [(case, 'coordinated') for case in args.cases]
    if args.baseline:
        cases.append(('torches16', 'baseline'))
    for case, mode in cases:
        existing = next((r for r in rows if r['case'] == case and r['mode'] == mode), None)
        if existing:
            if existing['state'] != 'passed':
                raise RuntimeError('Failed attempt requires an explicit fresh retry root')
            continue
        communicate(args)
        source = Path('examples/mes') / case
        destination = args.root / 'fixtures' / case / mode
        path = destination / 'scenario.json'
        if not path.exists():
            path = prepare(source, destination, mode)
        value = json.loads(path.read_text())
        if not value['execution'].get('infiniteEnergy'):
            raise ValueError('MES acceptance requires explicit infiniteEnergy')
        process = subprocess.Popen([sys.executable, 'runner.py', 'run', str(path),
                                    '--installation', str(args.installation),
                                    '--jobs-root', str(args.jobs_root)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, creationflags=NO_WINDOW)
        while True:
            try:
                stdout, stderr = process.communicate(timeout=240)
                break
            except subprocess.TimeoutExpired:
                communicate(args)
        (destination / 'native-command.log').write_text(stdout + '\n' + stderr)
        state = json.loads(stdout.strip().splitlines()[-1])
        if 'jobId' not in state:
            raise RuntimeError('Runner admission failed before job creation: ' + json.dumps(state))
        row = {'case': case, 'mode': mode, 'jobId': state['jobId'],
               'jobsRoot': str(args.jobs_root),
               'state': state['state'], 'wallSeconds': state['elapsedWallSeconds'],
               'commandExit': process.returncode}
        try:
            _, _, evidence = read_job(args.jobs_root, row['jobId'])
            result = evidence.get('warehouse', {})
            row['droneTrips'] = result.get('trips')
            row['mesStatus'] = result.get('status') or result.get('mes', {}).get('status')
        except (ValueError, OSError, KeyError):
            pass
        rows.append(row)
        record.write_text(json.dumps(rows, indent=2) + '\n')
        print(json.dumps(row), flush=True)
        communicate(args)
        if row['state'] != 'passed':
            raise RuntimeError('MES acceptance failed: ' + str(row))
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.cache/T11-mes'))
    parser.add_argument('--installation', type=Path, default=Path('C:/or/drone-install-T11'))
    parser.add_argument('--jobs-root', type=Path, default=Path('C:/or/drone-jobs'))
    parser.add_argument('--cases', nargs='+', default=['torches16', 'bricks16', 'specific-group', 'shortfall', 'concurrent-fetch'])
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--worker')
    parser.add_argument('--task')
    parser.add_argument('--dispatch')
    arguments = parser.parse_args()
    if arguments.worker and not (arguments.task and arguments.dispatch):
        parser.error('--worker requires --task and --dispatch')
    run(arguments)
