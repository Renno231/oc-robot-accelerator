"""Build current MES source, run isolated native cases, and capture every trip."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

from examples.mes.build_fixtures import (ALL_CASES, OCPARTS_FINAL, OCPARTS_REPEAT_FINAL,
                                        ROBOT_PARTS, ROBOT_PARTS_FINAL, ROBOT_EXPAND_FINAL, build_native)
from native_store_evidence import LuaData, read_store
from supervisor import NO_WINDOW

ROOT = Path(__file__).resolve().parent


def rows(value):
    return list(value.values()) if isinstance(value, dict) else value


def verify_case(case, runtime):
    """Physical results and production ledgers, without guest-side observers."""
    runtime = Path(runtime)
    native = json.loads((runtime / 'result.json').read_text())
    assert native['status'] == 'passed', native.get('reason')
    assert len(native['drones']) == 6
    assert all(r['inventoryCapacity'] == 85 and not r['inventory'] for r in native['robots'])
    assert all(not d['inventory'] for d in native['drones'])
    totals = {}
    for chest in native['containers']:
        for stack in chest['slots']:
            id = stack['item'] + (':' + str(stack['metadata']) if stack.get('metadata') else '')
            totals[id] = totals.get(id, 0) + stack['count']
    if case == 'concurrent-fetch':
        for z in (7, 9):
            chest = next(c for c in native['containers'] if c['position'] == [10, 64, z])
            assert any(s['item'] == 'minecraft:clay_ball' and s['count'] == 64 for s in chest['slots'])
        return {'physicalCounts': totals}
    paths = list(runtime.glob('world/opencomputers/*/etc/mes.state'))
    assert len(paths) == 1, 'missing/ambiguous MES receipt store'
    runs = [v for k, v in read_store(paths[0]).items() if k.startswith('done_')]
    expected_runs = len(ROBOT_PARTS) if case == 'robot-parts' else 2 if case in ('concurrent', 'ocparts-repeat') else 1
    if case == 'robot-expand': expected_runs = len(ROBOT_PARTS) + 3
    assert len(runs) == expected_runs, 'missing completed run receipt'
    assert all(r['status'] == 'complete' for r in runs)
    stages = [s for r in runs for s in rows(r['stages'])]
    intervals = [dict(crafter=s['crafter'], start=s['craftStarted'], finish=s['craftFinished'])
                 for s in stages if s.get('craftStarted') is not None]
    for i, a in enumerate(intervals):
        for b in intervals[i+1:]:
            assert a['crafter'] != b['crafter'] or max(a['start'], b['start']) >= min(a['finish'], b['finish']), 'same robot overlap'
    if case == 'shortfall':
        assert intervals and totals.get('minecraft:brick_block') == 16
        assert not totals.get('minecraft:clay_ball', 0) and not totals.get('minecraft:brick', 0)
        machine = next(s for s in stages if s['kind'] == 'machine')
        assert sum(l['items'] for l in rows(machine['loadLedger'])) == 64, 'completed input repeated'
    elif case in ('robot-parts', 'robot-expand'):
        ordered = sorted(runs, key=lambda r: r['id'])
        parts = ordered[:len(ROBOT_PARTS)]
        assert [(r['item'], r['qty']) for r in parts] == list(ROBOT_PARTS.items()), 'wrong parts orders'
        assert all(a['finished'] <= b['started'] for a, b in zip(parts, parts[1:])), 'overlapping orders'
        assert totals == (ROBOT_EXPAND_FINAL if case == 'robot-expand' else ROBOT_PARTS_FINAL), totals
        if case == 'robot-expand':
            assert len(native['robots']) == 3
            later = ordered[len(ROBOT_PARTS):]
            assert [(r['item'], r['qty']) for r in later] == [('opencomputers:component:11', 2), ('minecraft:chest', 1), ('minecraft:chest', 1)]
            for run, cpu in zip(later, ('cpu3', 'cpu1', 'cpu2')):
                assert run['started'] >= parts[-1]['finished']
                assigned = [s['crafter'] for s in rows(run['stages']) if s['kind'] == 'robot']
                assert assigned and set(assigned) == {cpu}, 'new capacity not exercised'
            assert max(r['started'] for r in later) < min(r['finished'] for r in later), 'requests were not concurrent'
            for position in ([11, 65, 3], [12, 65, 1]):
                assert not next(c for c in native['containers'] if c['position'] == position)['slots']
    elif case == 'ocparts-repeat':
        first, second = sorted(runs, key=lambda r: r['id'])
        assert (first['qty'], second['qty']) == (5, 3)
        assert first['finished'] <= second['started'], 'second order did not follow the first'
        assert totals == OCPARTS_REPEAT_FINAL, totals
        later = rows(second['stages'])
        outputs = {o['item'] for s in later for o in rows(s['outputs'])}
        assert outputs == {'minecraft:iron_nugget', 'opencomputers:material:4', 'opencomputers:component:6'}, 'surplus intermediates were remade'
        loads = [l for s in later if s['kind'] == 'machine' for l in rows(s['loadLedger'])]
        assert sum(l['items'] for l in loads) == 3
    elif case == 'ocparts':
        assert len(intervals) >= 4 and {r['crafter'] for r in intervals} == {'cpu1', 'cpu2'}
        assert totals == {id: count for id, count in OCPARTS_FINAL.items() if count}, totals
        machines = [s for s in stages if s['kind'] == 'machine']
        assert len(machines) == 1 and machines[0]['state'] == 'done', 'missing completed PCB stage'
        loads = rows(machines[0]['loadLedger'])
        assert {l['group'] for l in loads} == {'furnaceA', 'furnaceB'}, 'wrong PCB groups'
        for name in ('furnaceA', 'furnaceB'):
            group = sorted((l for l in loads if l['group'] == name), key=lambda l: l['delivered'])
            assert len(group) == 2 and all(l['items'] == 16 for l in group), 'wrong PCB load split'
            assert group[1]['delivered'] < group[0]['collected'], 'PCB top-up waited for collection'
    else:
        expected = ({'minecraft:torch': 16, 'minecraft:log': 3, 'minecraft:planks': 2, 'minecraft:coal': 14}
                    if case == 'torches16' else {'minecraft:brick_block': 16})
        if case == 'concurrent':
            expected['minecraft:torch'] = 16
        for id, count in expected.items():
            assert totals.get(id, 0) == count, (id, totals.get(id, 0), count)
        if case == 'specific-group':
            assert all(rows(s['groups']) == ['furnaceA'] for s in stages if s['kind'] == 'machine')
        if case in ('bricks16', 'specific-group'):
            machine = next(s for s in stages if s['kind'] == 'machine')
            loads = {}
            for load in rows(machine['loadLedger']):
                loads[load['group']] = loads.get(load['group'], 0) + load['items']
            assert loads == ({'furnaceA': 64} if case == 'specific-group' else {'furnaceA': 32, 'furnaceB': 32}), loads
        if case == 'torches16':
            machine = next(s for s in stages if s['kind'] == 'machine')
            for name in ('furnaceA', 'furnaceB'):
                loads = [l for l in rows(machine['loadLedger']) if l['group'] == name]
                assert len(loads) == 2 and all(l['items'] == 1 for l in loads)
                assert loads[1]['delivered'] < loads[0]['collected'], 'top-up waited for output collection'
    return {'physicalCounts': totals, 'robotIntervals': intervals, 'runs': runs}


def trip_report(capture, runtime):
    """Join actual wire dispatches to native persisted receipts, on the host."""
    trips, summary, sequences = {}, None, []
    with Path(capture).open(encoding='utf8') as stream:
        for line in stream:
            frame = json.loads(line)
            if frame['kind'] == 'captureSummary':
                summary = frame
            if frame['kind'] != 'modemFrame':
                continue
            sequences.append(frame.get('sequence'))
            if frame.get('direction') != 'send' or frame.get('port') != 27103:
                continue
            parts = [base64.b64decode(v['base64'], validate=True).decode('utf8')
                     if isinstance(v, dict) and 'base64' in v else v for v in frame['parts']]
            if len(parts) < 4 or parts[1] not in ('trip', 'report') or not parts[2]:
                continue
            entry = trips.setdefault(str(parts[2]), {'dispatches': [], 'reports': [], 'receipts': []})
            entry['dispatches' if parts[1] == 'trip' else 'reports'].append(
                {'tick': frame['tick'], 'source': frame['source'], 'destination': frame.get('destination'),
                 'token': parts[0], 'data': LuaData(parts[3]).parse()})
    ledgers = list(Path(runtime).glob('world/opencomputers/*/etc/logistics.state'))
    if len(ledgers) != 1:
        raise ValueError('expected one controller logistics ledger')
    jobs = read_store(ledgers[0])
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        timings = job.get('tripTimings', {})
        for timing in timings.values() if isinstance(timings, dict) else timings:
            entry = trips.setdefault(str(timing['trip']), {'dispatches': [], 'reports': [], 'receipts': []})
            entry['receipts'].append({'job': job['id'], 'state': job['state'], 'reason': job.get('reason'),
                                      'steps': job.get('steps'), 'timing': timing})
    gaps = []
    for id, trip in trips.items():
        # Logistics intentionally retains only 32 completed jobs. Full wire
        # capture is the historical receipt source, not that bounded live view.
        if len(trip['dispatches']) != 1 or not any(r['data'].get('state') in
                ('idle', 'held', 'failed', 'partial', 'rejected', 'busy')
                and r['source'] == trip['dispatches'][0]['destination']
                and r['token'] == trip['dispatches'][0]['token'] for r in trip['reports']):
            gaps.append(id)
    complete = bool(summary and summary.get('streamComplete') and summary.get('decodeCoverageComplete')
                    and summary.get('frameObservations') == len(sequences)
                    and sequences == list(range(1, len(sequences) + 1)) and trips and not gaps)
    return {'coverageComplete': complete, 'coverageGaps': gaps, 'captureSummary': summary,
            'trips': trips, 'jobs': jobs,
            'review': 'Human trip walk required: purpose, routes, retries, and unused work.'}


def run_case(case, root, installation, mode='coordinated', seconds=10):
    directory = root / (case + '-' + mode)
    source, jobs = directory / 'fixture', directory / 'jobs'
    manifest = build_native(source, case, mode, seconds=seconds)
    capture = directory / 'host-capture.ndjson'
    env = dict(os.environ)
    env['JAVA_TOOL_OPTIONS'] = (env.get('JAVA_TOOL_OPTIONS', '') +
        ' -Drobotspike.hostCapture=true -Drobotspike.hostCaptureFile=' + capture.resolve().as_posix())
    command = [sys.executable, str(ROOT / 'runner.py'), 'run', str(manifest),
               '--installation', str(installation), '--jobs-root', str(jobs)]
    with (directory / 'native.log').open('w', encoding='utf8') as log:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                creationflags=NO_WINDOW)
    states = list(jobs.glob('*/job.json'))
    if len(states) != 1:
        raise RuntimeError('runner admission failed; see ' + str(directory / 'native.log'))
    state = json.loads(states[0].read_text())
    row = {'case': case, 'mode': mode, 'jobId': state['jobId'], 'state': state['state'],
           'commandExit': result.returncode, 'wallSeconds': state.get('elapsedWallSeconds'),
           'directory': str(directory), 'tripReview': 'pending'}
    try:
        trips = trip_report(capture, states[0].parent / 'runtime')
        (directory / 'trips.json').write_text(json.dumps(trips, indent=2) + '\n')
        row['tripCoverageComplete'] = trips['coverageComplete']
        row['trips'] = len(trips['trips'])
    except (OSError, ValueError, KeyError) as error:
        row['tripCoverageComplete'] = False
        row['tripReportError'] = str(error)
    row['nativePassed'] = result.returncode == 0 and state['state'] == 'passed'
    if row['nativePassed']:
        try:
            evidence = verify_case(case, states[0].parent / 'runtime')
            (directory / 'acceptance.json').write_text(json.dumps(evidence, indent=2) + '\n')
        except (AssertionError, OSError, ValueError, KeyError) as error:
            row['nativePassed'] = False
            row['acceptanceError'] = str(error)
    # Native PASS is not a trip-walk verdict. Never label unreviewed work accepted.
    row['accepted'] = False
    (directory / 'result.json').write_text(json.dumps(row, indent=2) + '\n')
    print(json.dumps(row), flush=True)
    return row


def run(args):
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    cases = [(case, 'coordinated') for case in args.cases]
    if args.baseline:
        cases.append(('torches16', 'baseline'))
    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = [pool.submit(run_case, case, root, args.installation.resolve(), mode,
                               args.machine_seconds) for case, mode in cases]
        rows = []
        for future, (case, mode) in zip(futures, cases):
            try:
                rows.append(future.result())
            except Exception as error:
                rows.append({'case': case, 'mode': mode, 'nativePassed': False, 'error': str(error)})
            (root / 'runs.json').write_text(json.dumps(rows, indent=2) + '\n')
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('C:/or/mes-native') / datetime.now().strftime('%Y%m%d-%H%M%S'))
    parser.add_argument('--installation', type=Path, default=Path('C:/or/drone-install-MES-expansion'))
    parser.add_argument('--cases', nargs='+', choices=ALL_CASES, default=list(ALL_CASES))
    parser.add_argument('--parallel', type=int, choices=range(1, 5), default=4)
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--machine-seconds', type=float, default=10,
                        help='fixture processing estimate, including deliberately underestimated cases')
    rows = run(parser.parse_args())
    sys.exit(0 if all(r.get('nativePassed') and r.get('tripCoverageComplete') for r in rows) else 1)
