"""Summarize a completed native survey and walk every frozen trip packet."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from lupa.lua53 import LuaRuntime


def load_table(path):
    lua = LuaRuntime()
    lua.globals().DATA = path.read_text()
    result = lua.eval("assert(load('return '..DATA))()")

    def plain(value):
        if not hasattr(value, 'items'):
            return value
        entries = dict(value.items())
        if set(entries) == set(range(1, len(entries) + 1)):
            return [plain(entries[i]) for i in range(1, len(entries) + 1)]
        return {str(k): plain(v) for k, v in entries.items()}

    return plain(result)


def report(jobs_root, output):
    job_file = next(jobs_root.glob('*/job.json'))
    job = json.loads(job_file.read_text())
    home = next(job_file.parent.glob('runtime/world/opencomputers/*/home/survey-results.lua')).parent
    result = load_table(home / 'survey-results.lua')
    packets = {v['trip']: v for v in (load_table(p) for p in home.glob('survey-trip-*.lua'))}
    jobs = result['jobs']
    jobs = dict(enumerate(jobs, 1)) if isinstance(jobs, list) else {int(k): v for k, v in jobs.items()}
    survey_trips = {v['job']: v for v in result['record']['trips']}
    retained = {t['trip']: (job_id, value, t) for job_id, value in jobs.items()
                for t in value['tripTimings']}
    fleet = {d['address']: d['name'] for d in result['fleet']}
    rows = []
    recovered = 0
    for trip, packet in sorted(packets.items()):
        task = packet['task']; action = task.get('action', {})
        if trip in retained:
            job_id, value, timing = retained[trip]
            seconds = timing['finishedAt']-timing['startedAt']
        else:
            # Logistics intentionally retains only 32 finished jobs. Survey
            # records append a diagnostic only after that command is done.
            assert action['kind'] == 'survey', 'unretained non-survey trip needs another receipt'
            s = next(s for s in survey_trips.values() if s['command'] == action['command'])
            job_id, value, seconds = s['job'], {'state': 'done'}, None
            timing = {'trip': trip, 'drone': fleet[packet['address']]}
            recovered += 1
        s = survey_trips.get(job_id, {})
        row = {'job': job_id, 'trip': trip, 'drone': timing['drone'],
               'kind': action.get('kind', 'inventory'), 'state': value['state'],
               'test': value.get('test'), 'seconds': seconds,
               'routes': json.dumps(task.get('routes', {}), separators=(',', ':')),
               'steps': json.dumps(task.get('steps', []), separators=(',', ':')),
               'command': json.dumps(action.get('command', {}), separators=(',', ':'))}
        row.update(s.get('metrics', {})); rows.append(row)
    with output.with_suffix('.csv').open('w', newline='') as stream:
        columns = ['job', 'trip', 'drone', 'kind', 'state', 'test', 'seconds',
                   'scans', 'hops', 'analyzes', 'energy', 'tripEnergy', 'routes', 'command', 'steps']
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader(); writer.writerows(rows)
    sources = {}
    for path in sorted(home.glob('program/lib/*.lua')):
        canonical = Path('drone-logistics/lib') / path.name
        if canonical.exists():
            sources[str(canonical)] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'matchesCurrent': path.read_bytes() == canonical.read_bytes()}
    for path in sorted(home.glob('program/drone/*.lua')):
        canonical = Path('drone-logistics/drone') / path.name
        if canonical.exists():
            sources[str(canonical)] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'matchesCurrent': path.read_bytes() == canonical.read_bytes()}
    native = json.loads((job_file.parent / 'runtime/result.json').read_text())
    summary = {'job': job, 'case': result['case'], 'metrics': result['record']['metrics'],
        'controllerMemory': result['controllerMemory'], 'carrier': result['carrier'],
        'stockBefore': result['before'], 'stockAfter': result['after'],
        'stationKinds': [s['kind'] for s in result['stations'].values()],
        'tripCount': len(rows), 'tests': sum(bool(v.get('test')) for v in jobs.values()),
        'inventoryReads': sum(bool(s.get('read')) for v in jobs.values() for s in v.get('steps', [])),
        'packetCount': len(packets), 'recoveredOldSurveyTrips': recovered,
        'sources': sources, 'home': str(home),
        'nativeDroneEnergy': [{'index': d['index'], 'consumed': d['energyConsumed'],
                              'remaining': d['energy']} for d in native['drones']]}
    output.with_suffix('.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jobs-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); report(args.jobs_root, args.output)
