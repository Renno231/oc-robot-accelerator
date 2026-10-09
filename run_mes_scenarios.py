"""Run the headless manufacturing acceptance matrix through the public runner."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from build_machine_comparisons import prepare
from compare_machine_jobs import read_job
from supervisor import NO_WINDOW
T11_TORCH_MES_TRIPS = 24  # Preserved native jobs65-88; see T13-t11-trip-split.json.


def acceptance_error(row):
    """Compare actual MES job trips with the identically split T11 baseline."""
    if row['state'] != 'passed' or row.get('commandExit', 0) != 0:
        return 'native scenario failed'
    if row['case'] == 'torches16' and row['mode'] == 'coordinated':
        trips = row.get('mesTrips')
        if type(trips) is not int or trips < 0 or trips >= T11_TORCH_MES_TRIPS:
            return 'torches16 requires measured MES-run trips below T11\'s 24'
    if row['case'] == 'ocparts':
        exit_evidence = row.get('submitterExit')
        if not isinstance(exit_evidence, dict) or exit_evidence.get('returned') is not True or exit_evidence.get('statusAtReturn') != 'running':
            return 'ocparts requires a foreground submitter that exited mid-run'
        calls = row.get('componentCalls')
        if not isinstance(calls, dict) or calls.get('scope') != 'controller' or type(calls.get('total')) is not int or calls['total'] <= 0:
            return 'ocparts requires measured controller component calls'
        intervals = row.get('robotIntervals')
        if not isinstance(intervals, list) or len(intervals) < 4 or type(row.get('robotOverlap')) is not bool:
            return 'ocparts requires four answered robot jobs and measured overlap'
        payloads = row.get('craftPayloads')
        if not isinstance(payloads, list) or not payloads:
            return 'ocparts requires measured native craft payload sizes'
        for payload in payloads:
            size, limit = payload.get('packetBytes'), payload.get('packetLimit')
            if type(size) is not int or type(limit) is not int or size <= 0 or limit <= 0 or size > limit:
                return 'ocparts craft packet exceeds or lacks observed modem limit'
    return None


def summarize_job(state, command_exit, jobs_root, source, case, mode):
    """Summarize an explicitly inspected job without submitting another run."""
    row = {'case': case, 'mode': mode, 'jobId': state['jobId'],
           'fixtureSource': str(source), 'jobsRoot': str(jobs_root),
           'state': state['state'], 'wallSeconds': state.get('elapsedWallSeconds'),
           'commandExit': command_exit}
    try:
        _, _, evidence = read_job(jobs_root, row['jobId'])
        result = (evidence or {}).get('warehouse') or (evidence or {}).get('mesProgress') or {}
        for target, key in [('droneTrips', 'trips'), ('mesTrips', 'mesTrips'),
                            ('harnessTrips', 'harnessTrips'), ('mesTripWindow', 'mesTripWindow'),
                            ('droneBusy', 'droneBusy'), ('submitterExit', 'submitterExit'),
                            ('robotIntervals', 'robotIntervals'), ('robotOverlap', 'robotOverlap')]:
            row[target] = result.get(key)
        row['timing'] = result.get('timing') or (evidence or {}).get('mesFetchTimings')
        row['craftPayloads'] = (evidence or {}).get('craftPayloads', [])
        row['componentCalls'] = result.get('componentCalls') or (evidence or {}).get('componentCalls')
        if case == 'torches16':
            row['t11MesTrips'] = T11_TORCH_MES_TRIPS
        row['mesStatus'] = result.get('status') or (result.get('mes') or {}).get('status')
    except (ValueError, OSError, KeyError):
        pass
    error = acceptance_error(row)
    row['accepted'] = error is None
    if error:
        row['acceptanceError'] = error
    return row


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
            if acceptance_error(existing) is not None:
                raise RuntimeError('Failed attempt requires an explicit fresh retry root')
            continue
        communicate(args)
        source = getattr(args, 'fixture_root', Path('examples/mes')) / case
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
        row = summarize_job(state, process.returncode, args.jobs_root, source, case, mode)
        rows.append(row)
        record.write_text(json.dumps(rows, indent=2) + '\n')
        print(json.dumps(row), flush=True)
        communicate(args)
        if not row['accepted']:
            raise RuntimeError('MES acceptance failed: ' + str(row))
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.cache/T13-mes'))
    parser.add_argument('--installation', type=Path, default=Path('C:/or/drone-install-T11'))
    parser.add_argument('--jobs-root', type=Path, default=Path('C:/or/drone-jobs'))
    parser.add_argument('--fixture-root', type=Path, default=Path('examples/mes'))
    parser.add_argument('--cases', nargs='+', default=['torches16', 'bricks16', 'specific-group', 'shortfall', 'concurrent-fetch', 'ocparts'])
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--worker')
    parser.add_argument('--task')
    parser.add_argument('--dispatch')
    arguments = parser.parse_args()
    if arguments.worker and not (arguments.task and arguments.dispatch):
        parser.error('--worker requires --task and --dispatch')
    run(arguments)
