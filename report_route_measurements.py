"""Render the complete T7 native measurement and equivalence report."""
import argparse
import json
from pathlib import Path
from summarize_route_measurements import summarize,write_tables


def report(root,sweep,jobs):
    data=summarize(root,jobs);assert len(data)==24
    comparisons=json.loads((sweep/'comparisons.json').read_text())
    assert len(comparisons)==26
    unexpected=sum(len(c[k]['unexpectedDifferences']) for c in comparisons for k in ('natural','accelerated'))
    assert unexpected==0, 'equivalence gate failed'
    write_tables(data,jobs)
    (jobs/'T7-comparisons.json').write_text(json.dumps(comparisons,indent=2)+'\n')
    (jobs/'T7-sweep-runs.json').write_bytes((sweep/'runs.json').read_bytes())
    out=['# T7 — native route smoothing and flight polling', '',
         '## Outcome', '',
         'Shipped one logistics planner: **Theta***. The required unchanged graph A* (`map.route`) and forward smoothing (`map.smooth`) remain mapping APIs. Storage-room reverse entry ties stops and reduces actual flown distance; its blocked reroute also removes a stop. Other sampled route geometries tie, with small native settling differences tabulated below. Native controller cold routes remain below the 50 ms gate.', '',
         'Sparse numeric clear voxels rebuild lazily only on geometry edits. Widened 3D DDA uses scalar conservative slab tests, O(1) numeric lookups, no per-block tables, and early rejection. Relative numeric strides require a bounding-volume product below `2^53`; oversized maps fail explicitly rather than aliasing positions. Logistics caches from/to waypoint names until map revision; job avoids bypass the cache. Blocked jobs retain voxel coordinates, rekey on edits, skip every original link sweeping the voxel, and retrace before replanning.', '',
         '## Source and measurement contract', '',
         '- OC pin: `8ca336fbeb92d2a29f86f9a658bb9d6bd6f07dbb`. `common/entity/Drone.scala:80` sets width 0.75 and height 0.375. Forge **1.12.2-14.23.5.2860**, mapped `Entity.setPosition`, anchors the AABB at posY. Supplied generic box: `{x=.375,y=.1875,z=.375,offsetY=.1875}`. Bytecode evidence: `.cache/t7-forge-entity-javap.txt:625–689`.',
         '- Pinned `Drone.scala:74–78,430–457` supplies acceleration .1 blocks/tick², axis cap .4/tick and drag .8; component API `server/component/Drone.scala:102–110` reports max velocity 8 and acceleration 2. From a confirmed hover, `|v_next| <= .8*(|v|+.1)` gives nominal reported-velocity bound 8 blocks/s; acceleration conversion is 40 blocks/s². Sleep clamps 0.1–1 s after reserving braking/settling distance; it reuses the existing offset read. Arrival predicates (offset <.02 and velocity <.02) and stall predicates (>0.1 improvement within 3 s) are unchanged.',
         '- Controller CPU seconds are native OC `os.clock`: pinned `server/machine/luac/OSAPI.scala:15–20`, backed by `Machine.cpuTime`. Cold includes actual logistics preview; cached includes fresh waypoint records. Storage and pillar use selected corner/home pairs; steps/split use all unordered node pairs. Complete raw routes/timings are in the JSON artifact.',
         '- Flight intervals start when the agent receives the trip and end when it prepares its terminal report. Wall time, actual travelled distance and energy come from native per-tick `route-observations.ndjson`, matched to the final agent uptime epoch after EEPROM reboot. Boundary uncertainty is at most one native tick; terminal report emission can fall outside the interval. Game ticks are agent interval seconds ×20. Native energy debits include successful machine awake/sleep and wireless costs, not charger gains: pinned `Machine.scala:526–540` and `WirelessNetworkCard.scala:87–95`.',
         '- Acceptance instrumentation observes existing getters and reuses the existing report, adding no component calls or radio sends. A frozen opt-in marker enables a compact bounded stream independent of the ordinary 32 MiB replay prefix. Before variants restore HEAD graph/agent/test polling. Measurement-only sorted fleet selection ensures the same home/routes across variants; production fleet policy is unchanged.', '',
         '## Layouts and judgment calls', '',
         'Storage room: 64 inward-facing physical chests, 32 hallway hover nodes, neighbour links, two external chargers. Native assertions exercise corner, reverse/distant, simultaneous 512-item work, every chest face, and a chest inserted at `(3,67,2)` after mapping; the horizontal row leg stalls, retraces, reroutes and delivers. The pillar layout has 46 linked grid nodes around three missing pillar positions. Explicit slot 27 keeps the all-face read sweep and final packet bounded; native reads assert inventory size >0.',
         'Finite capacitors supply the long reference runs; power is never ignored. An early reference exhausted an idle drone after 10030 ticks (`4e227455def84a8eb3f222ab60a864fc`, NoEnergy), so both planners/reference received the same larger finite supply. Ascending native trajectories could slide past an inserted chest (probes `e57818219b594480a57fe8d42d8f3df2` and `6f097a04142a4c0d82c8fe5ce6fa283b`); the separate horizontal insertion test forces an actual stall. An exhaustive 595-pair planning probe exceeded controller memory (`bf3f27f54dc74e4ca763e5a77f400444`), so corner/home selection bounds the large-map benchmark. A stopped replay-prefix probe was discarded (`134f30c91e904543952d54962ac5d582`); accepted measurements require complete compact coverage.', '',
         '## Planning and clear-set memory', '',
         '| Layout | Planner/mode | Clear blocks | Allocated bytes | Max cold ms | Max cached ms | Raw smooth max ms | Raw Theta max ms |',
         '|---|---|---:|---:|---:|---:|---:|---:|']
    for r in data:
        p=r['planning']
        if p:
            rows=p['routes'];cold=max(x['liveColdSeconds'] for x in rows);assert cold<.05
            out.append(f"| {r['case']} | {r['variant']}/{r['mode']} | {p['clearBlocks']} | {p['clearBytes']} | {cold*1000:.3f} | {max(x['liveCachedSeconds'] for x in rows)*1000:.3f} | {max(x['smoothSeconds'] for x in rows)*1000:.3f} | {max(x['thetaSeconds'] for x in rows)*1000:.3f} |")
    out += ['', 'Memory is native free-memory allocation delta around the one clear build; it includes model/stride bookkeeping. Stored set size is proportional to clear voxels.', '',
            '## Whole-run accelerated rate', '', '| Layout | Variant | Mode | Game ticks | Native elapsed s | Ticks/s |', '|---|---|---|---:|---:|---:|']
    for r in data:out.append(f"| {r['case']} | {r['variant']} | {r['mode']} | {r['ticks']} | {r['elapsedNanos']/1e9:.3f} | {r['rate']:.2f} |")
    out += ['', 'Rate is `result.json ticks / elapsedNanos × 1e9`, including boot and workload. Host setup time is excluded. Fewer workload ticks do not necessarily produce a higher whole-run ticks/s ratio; the observed per-trip wall times and native elapsed totals are reported separately.', '', '## Per-trip native measurements', '', '| Layout/variant/mode | Trip/drone | Wall s | Game ticks | Energy debits | Stops (+blocked) | Actual metres |', '|---|---|---:|---:|---:|---:|---:|']
    for r in data:
        for t in r['trips']:out.append(f"| {r['case']}/{r['variant']}/{r['mode']} | {t['trip']}/{t['drone']} | {t['wallSeconds']:.3f} | {t['gameTicks']} | {t['energyUsed']:.1f} | {t['stops']} (+{t['blockedStops']}) | {t['nativeDistance']:.3f} |")
    out += ['', '## Access-point accuracy', '', '| Layout/variant/mode | Access-point rows | Max arrival-check offset | Max arrival-check velocity |', '|---|---:|---:|---:|']
    for r in data:
        accesses=[a for t in r['trips'] for a in t['accesses']]
        out.append(f"| {r['case']}/{r['variant']}/{r['mode']} | {len(accesses)} | {max(a['offset'] for a in accesses):.8f} | {max(a['velocity'] for a in accesses):.8f} |")
    out += ['', 'Every recorded access satisfies the strict original offset and velocity rule. Each individual point, trip, coordinates, access count, offset and velocity is tabulated in [T7-accesses.csv](T7-accesses.csv). [T7-trips.csv](T7-trips.csv) preserves all per-trip values; [T7-measurements.json](T7-measurements.json) preserves job IDs, status, planned distances and full OC planning data.', '',
            '## Verification', '', 'Full T6 comparison tooling: 26 logistics/mapping/drones scenarios × baseline1/baseline2/coordinated = 78 native runs; **zero unexpected differences** in both natural-repeatability and accelerated comparisons. `drones/error` retains its intentional failure. Durable raw records: [T7-sweep-runs.json](T7-sweep-runs.json); comparison details: [T7-comparisons.json](T7-comparisons.json).',
            'Python: 215 tests run, one skipped, suite passed (`.cache/t7-python-final.log`). Java: 92 tests, `gradle test jar` passed (`.cache/t7-build8.log`). Fixture copies regenerated with `build_storage_room.py`, `sync_logistics_fixtures.py`, and `examples/mapping/build_fixtures.py`; `git diff --check` clean.', '',
            'Deferred: event-driven idle waiting/proactive recharge could reduce the independent idle-wakeup cost; this task preserves that policy.']
    (jobs/'T7-report.md').write_text('\n'.join(out)+'\n',encoding='utf-8')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--sweep',type=Path,required=True);p.add_argument('--jobs-root',type=Path,default=Path('C:/or/drone-jobs'))
    a=p.parse_args();report(a.root,a.sweep,a.jobs_root)
