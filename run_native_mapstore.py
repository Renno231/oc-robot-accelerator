"""MAPSTORE's three native cases, with separate roots and overlapping lifetimes."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import time

from build_machine_comparisons import prepare
from build_native_io_flow import build as build_io
from build_native_stations import build as build_stations
from supervisor import NO_WINDOW


def run(root, case, installation):
    root = root / case
    if case == 'warehouse-slots':
        scenario = prepare('examples/warehouse/slots', root / 'fixture', 'coordinated')
    else:
        scenario = (build_io if case == 'io-flow' else build_stations)(root)
    command = [sys.executable, 'runner.py', 'run', str(scenario), '--installation',
               str(installation), '--jobs-root', str(root / 'jobs')]
    started = time.time()
    with (root / 'native-command.log').open('w') as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                creationflags=NO_WINDOW)
    evidence = dict(case=case, started=started, finished=time.time(),
                    command=command, exit=result.returncode)
    (root / 'run.json').write_text(json.dumps(evidence, indent=2))
    return evidence


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--installation', type=Path, default=Path('C:/or/drone-install-IO1'))
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda case: run(args.root, case, args.installation),
                                ('warehouse-slots', 'io-flow', 'stations')))
    overlap = min(r['finished'] for r in results) - max(r['started'] for r in results)
    summary = dict(overlapSeconds=overlap, cases=results)
    (args.root / 'results.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    sys.exit(any(r['exit'] for r in results))
