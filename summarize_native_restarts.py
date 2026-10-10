"""Read-only R4 trip/read audit and native catalogue/physical-world comparison."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
from compare_machine_jobs import read_job


def entries(value):
    return value.items() if isinstance(value, dict) else []


def summarize(root):
    root = Path(root)
    run = json.loads((root / 'run.json').read_text())
    job_id = run['state']['jobId']
    state, native, evidence = read_job(root / 'jobs', job_id)
    runtime = root / 'jobs' / job_id / 'runtime'
    drive = next(runtime.glob('world/opencomputers/*/home/equivalence.json')).parent.parent
    archive = drive / 'home/r4-jobs.ndjson'
    jobs = {}
    if archive.exists():
        for line in archive.read_text().splitlines():
            row = json.loads(line)
            jobs[row['id']] = row
    for key, status in entries(evidence.get('jobs', {})):
        jobs.setdefault(int(key), {'id': int(key), 'status': status, 'boot': evidence['programStarts']})
    provenance = {}
    for stage in evidence.get('mesExecution', {}).get('stages', []):
        for physical in stage.get('physicalJobs', []):
            provenance[physical['job']] = f"MES stage {stage['index']} ({stage['kind']}): {physical['kind']}"
    first = min(provenance, default=65)
    last = max(provenance, default=64)
    reads, trips, oddities = [], [], []
    for id, row in sorted(jobs.items()):
        status = row['status']
        purpose = provenance.get(id)
        if purpose is None:
            purpose = ('initial warehouse catalogue scan' if id < first else
                       'post-completion physical verification' if id > last and evidence['returned'] else
                       'MES service inventory reconciliation')
        operations = [{k: step[k] for k in ('read', 'take', 'put', 'go', 'item', 'count') if k in step}
                      for step in status.get('steps', [])]
        for timing in status.get('tripTimings', []):
            trips.append({'job': id, 'bootObserved': row['boot'], 'reason': purpose,
                          'operations': operations, **timing})
        for index, step in enumerate(status.get('steps', []), 1):
            if 'read' not in step:
                continue
            confirmed = 'listing' in step and 'size' in step
            slots = step['read'].get('slots', list(range(1, step.get('size', 0) + 1)))
            reads.append({'job': id, 'step': index, 'reason': purpose,
                          'endpoint': step['read'], 'confirmed': confirmed,
                          'size': step.get('size'), 'slots': slots,
                          'listing': step.get('listing')})
        if status.get('reason'):
            oddities.append({'job': id, 'state': status['state'], 'reason': status['reason']})
        if status.get('trips', 0) > 1:
            oddities.append({'job': id, 'reason': 'multiple trips; inspect allocations before calling this a retry',
                             'trips': status['trips']})
    files = evidence['files']
    mapping = files['/etc/map.cfg']
    containers = {tuple(c['position']): c for c in native['containers']}
    delta = {0: (0, -1, 0), 1: (0, 1, 0), 2: (0, 0, -1),
             3: (0, 0, 1), 4: (-1, 0, 0), 5: (1, 0, 0)}
    differences = []
    compared = 0
    for name, record in entries(files.get('/etc/warehouse.db', {})):
        storage = mapping['storages'][name]
        node = mapping['nodes'][storage['node']]
        position = tuple(node[k] + d for k, d in zip(('x', 'y', 'z'), delta[storage['side']]))
        container = containers[position]
        actual = Counter()
        # Furnace records use role-relative slots; native inventory is input/fuel/output.
        role = name.rsplit('.', 1)[-1]
        selected = {'in': 1, 'fuel': 2, 'out': 3}.get(role) if container['block'] == 'minecraft:furnace' else None
        for slot in container['slots']:
            if selected is None or slot['slot'] == selected:
                actual[(slot['item'], slot.get('metadata', 0))] += slot['count']
        recorded = Counter()
        for _, item in entries(record['items']):
            if item['count']:
                recorded[(item['item']['name'], item['item'].get('damage', 0))] += item['count']
        compared += 1
        if actual != recorded:
            differences.append({'storage': name, 'position': position,
                'actual': [{'item': k[0], 'damage': k[1], 'count': v} for k, v in sorted(actual.items())],
                'recorded': [{'item': k[0], 'damage': k[1], 'count': v} for k, v in sorted(recorded.items())]})
    open_flights = files.get('/etc/warehouse.flight', {})
    cargo = [{'kind': kind, 'index': row['index'], 'inventory': row.get('inventory')}
             for kind in ('drones', 'robots') for row in native.get(kind, []) if row.get('inventory')]
    audit = {'case': run['case'], 'jobId': job_id, 'state': state['state'],
        'reason': state.get('reason'), 'programStarts': evidence['programStarts'],
        'MESStatus': evidence.get('mesExecution', {}).get('status'),
        'jobsObserved': len(jobs), 'tripCount': sum(row['status'].get('trips', 0) for row in jobs.values()),
        'listedTripCount': len(trips), 'readCount': len(reads),
        'confirmedReadCount': sum(read['confirmed'] for read in reads),
        'multipleTripJobs': sum(row['status'].get('trips', 0) > 1 for row in jobs.values()),
        'shortfalls': sum(row['status'].get('shortfalls', 0) for row in jobs.values()),
        'catalogueRecordsCompared': compared, 'catalogueDifferences': differences,
        'openFlights': open_flights, 'physicalCargo': cargo,
        'worldEqualsRecords': not differences and not open_flights and not cargo,
        'trips': trips, 'reads': reads, 'oddities': oddities,
        'evidenceDrive': str(drive), 'runtime': str(runtime)}
    clock = drive / 'home/r4-restart-window.lua'
    window = None
    if clock.exists():
        window = {key: float(number) for key, number in re.findall(
            r'([A-Za-z]\w*)=([-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)', clock.read_text())}
        window['navigationUnavailableSeconds'] = window['navigationReady'] - window['shutdown']
        window['MESUnavailableSeconds'] = window['serviceReady'] - window['shutdown']
    waits_path = drive / 'home/r4-route-waits.ndjson'
    waits = [json.loads(line) for line in waits_path.read_text().splitlines()] if waits_path.exists() else []
    waiting = {f'd{i}': 0.0 for i in range(1, 7)}
    if window:
        for row in waits:
            interval = row['wait']
            waiting[interval['drone']] += max(0, min(interval['finished'], window['navigationReady']) -
                                             max(interval['started'], window['shutdown']))
    audit['restartWindow'] = window
    audit['droneRouteWaitSecondsDuringRestart'] = waiting
    audit['routeWaitIntervals'] = waits
    audit['readReasons'] = dict(Counter(read['reason'] for read in reads))
    (root / 'trip-read-audit.json').write_text(json.dumps(audit, indent=2) + '\n')
    print(json.dumps({k: v for k, v in audit.items() if k not in ('trips', 'reads', 'reason', 'routeWaitIntervals')}))
    return audit


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    summarize(parser.parse_args().root)
