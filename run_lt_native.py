"""Two independent RR native furnace estimates, concurrently, with full receipt logs."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import shutil
import sys
import time
import re
from build_native_robot_register import build


def summarize(root, output):
    lines = ['# LT native trip walk', '', 'One row per physical trip, including setup/read trips.', '']
    summaries = []
    for estimate in (5, 20):
        case = root / f'seconds-{estimate}'
        run = json.loads((case / 'run.json').read_text())
        home = next(case.glob('jobs/*/runtime/world/opencomputers/*/home/r4-jobs.ndjson')).parent
        jobs = {row['id']: row['status'] for row in
                map(json.loads, (home / 'r4-jobs.ndjson').read_text().splitlines())}
        observations = [json.loads(re.sub(r':inf(?=[,}])', ':Infinity', row))
                        for row in (home / 'lt-observations.ndjson').read_text().splitlines()]
        latest = {row['group']: row for row in observations}
        collections = [s for s in jobs.values() if any(
            step.get('take', {}).get('node') in ('10:63:7', '10:63:9') for step in s.get('steps', []))]
        trips = sum(s.get('trips', 0) for s in jobs.values())
        summary = dict(estimate=estimate, run=run, trips=trips,
                       furnaceCollections=sum(s.get('trips', 0) for s in collections),
                       extraCollectionTrips=sum(s.get('trips', 0) for s in collections)-2,
                       machines=latest)
        summaries.append(summary)
        lines += [f'## Estimate {estimate}', '',
                  f'Exit {run["exit"]}; {trips} total trips; {summary["furnaceCollections"]} furnace collection trips; '
                  f'{summary["extraCollectionTrips"]} extra versus one collection per furnace.', '',
                  '| Job/trip | Drone | Start–finish | Steps in execution order (requested → moved) | State |',
                  '|---|---|---|---|---|']
        for job, status in sorted(jobs.items()):
            steps = []
            for step in status.get('steps', []):
                kind = next((k for k in ('take', 'put', 'read') if k in step), '?')
                endpoint = step.get(kind, {})
                item = step.get('item', {})
                name = item.get('name', '?') if isinstance(item, dict) else str(item)
                steps.append(f'{kind} {endpoint.get("node", "?")}:{endpoint.get("side", "?")} '
                             f'{name} {step.get("count", "*")}→{step.get("moved", 0)}')
            for trip in status.get('tripTimings', []):
                lines.append(f'| {job}/{trip.get("trip")} | {trip.get("drone")} | '
                             f'{trip.get("startedAt")}–{trip.get("finishedAt")} | '
                             f'{"; ".join(steps)} | {status.get("state")} |')
        lines.append('')
    overlap = min(s['run']['finished'] for s in summaries) - max(s['run']['started'] for s in summaries)
    lines += ['## Concurrency', '', f'Both cases overlapped for {overlap:.3f} wall seconds; roots/jobs-roots were distinct.', '']
    output.write_text('\n'.join(lines), encoding='utf-8')
    output.with_suffix('.json').write_text(json.dumps(dict(overlapSeconds=overlap, cases=summaries), indent=2))
    return summaries


def run(root, estimate, installation):
    root = root / f'seconds-{estimate}'
    scenario = build(root, 'robot-register')
    for program in ('program', 'robot-program', 'robot2-program'):
        shutil.copytree('craftsystem/usr', scenario.parent / program / 'usr', dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('mes_ui', 'mesui.lua'))
    shutil.copytree('drone-logistics/lib', scenario.parent / 'program/lib', dirs_exist_ok=True)
    main = scenario.parent / 'program/native-main.lua'
    source = main.read_text().replace('batch=64,seconds=10,blocking=false',
                                      f'batch=64,seconds={estimate},blocking=false')
    source = source.replace("'logistics','warehouse'", "'logistics','warehouse','stations'", 1)
    source = source.replace("result.second=second;", """
  save('/home/lt-bounds.lua',mes.resources())
  result.second=second;""")
    main.write_text(source)
    # Record learned bounds and exclusions at MES stage events, before ephemeral groups clear.
    observer = scenario.parent / 'program/main.lua'
    source = observer.read_text().replace("local ok,err=xpcall", """
local timing=assert(loadfile('/home/program/usr/lib/mes_timing.lua'))()
package.loaded.mes_timing=timing
local observe=timing.observe
timing.observe=function(w,g,c,err)
  observe(w,g,c,err)
  local f=assert(io.open('/home/lt-observations.ndjson','a'))
  json(f,{group=g.name,now=w.now,timing=w.timing[g.name],excluded=g.timingExcluded,
    epoch=g.epoch,submitted=c.bundle.action.submittedAt});f:write('\\n');f:close()
end
local ok,err=xpcall""", 1)
    observer.write_text(source)
    command = [sys.executable, 'runner.py', 'run', str(scenario), '--installation',
               str(installation), '--jobs-root', str(root / 'jobs')]
    started = time.time()
    with (root / 'native-command.log').open('w') as output:
        result = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT)
    summary = dict(estimate=estimate, started=started, finished=time.time(),
                   command=command, exit=result.returncode)
    (root / 'run.json').write_text(json.dumps(summary, indent=2))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--installation', type=Path, default=Path('C:/or/drone-install-T11'))
    parser.add_argument('--summarize', type=Path)
    args = parser.parse_args()
    if args.summarize:
        print(json.dumps(summarize(args.root, args.summarize), indent=2))
        sys.exit(0)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda n: run(args.root, n, args.installation), (5, 20)))
    print(json.dumps(results, indent=2))
    sys.exit(any(r['exit'] for r in results))
