"""Fresh 26-case T10 regression sweep with explicit power-policy selection."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from build_machine_comparisons import prepare
from run_mes_scenarios import communicate
from supervisor import NO_WINDOW

CASES = {
    'drones': ('charge', 'error', 'link', 'sides', 'transfer', 'wake'),
    'logistics': ('blocked', 'blocked-held', 'fixes', 'full', 'furnace', 'held',
                  'names', 'obstacle-room', 'pair', 'power', 'security',
                  'shortfall', 'split', 'stack-capacity', 'steps',
                  'storage-room', 'transfer', 'wait'),
    'mapping': ('actions', 'service'),
}


def run(args):
    args.root.mkdir(parents=True, exist_ok=True)
    record = args.root / 'runs.json'
    rows = json.loads(record.read_text()) if record.exists() else []
    for family, names in CASES.items():
        for name in names:
            scenario = f'examples/{family}/{name}'
            existing = next((r for r in rows if r['scenario'] == scenario), None)
            if existing:
                if not existing['accepted']:
                    raise RuntimeError('Failed regression requires explicit fresh retry root')
                continue
            communicate(args)
            destination = args.root / 'fixtures' / family / name
            path = destination / 'scenario.json'
            if not path.exists():
                path = prepare(scenario, destination, 'coordinated')
                value = json.loads(path.read_text())
                if not args.preserve_power_contract:
                    value['execution']['infiniteEnergy'] = True
                path.write_text(json.dumps(value, indent=2) + '\n')
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
            expected_error = family == 'drones' and name == 'error'
            accepted = ((state['state'] == 'failed' and 'drone_error:0:' in state.get('reason', ''))
                        if expected_error else state['state'] == 'passed')
            row = {'scenario': scenario, 'mode': 'coordinated',
                   'powerPolicy': 'original' if args.preserve_power_contract else 'infiniteEnergy',
                   'jobId': state['jobId'], 'state': state['state'],
                   'expectedError': expected_error, 'accepted': accepted,
                   'wallSeconds': state['elapsedWallSeconds'], 'commandExit': process.returncode}
            rows.append(row)
            record.write_text(json.dumps(rows, indent=2) + '\n')
            print(json.dumps(row), flush=True)
            communicate(args)
            if not accepted:
                raise RuntimeError('Native regression failed: ' + str(row))
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.cache/T11-regression'))
    parser.add_argument('--installation', type=Path, default=Path('C:/or/drone-install-T11-runner-final'))
    parser.add_argument('--jobs-root', type=Path, default=Path('C:/or/drone-jobs-T11-regression'))
    parser.add_argument('--worker')
    parser.add_argument('--task')
    parser.add_argument('--dispatch')
    parser.add_argument('--preserve-power-contract', action='store_true',
                        help='Retain inherited finite-power assertions/settings unchanged')
    arguments = parser.parse_args()
    if arguments.worker and not (arguments.task and arguments.dispatch):
        parser.error('--worker requires --task and --dispatch')
    run(arguments)
