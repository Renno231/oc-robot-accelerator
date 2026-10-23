"""Evidence-backed closeout for the native warehouse furnace acceptance."""
import argparse
import json
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET
from compare_machine_jobs import compare
from summarize_furnace_cycles import summarize


def write(root,jobs,regression,regression_jobs,profile_job,output):
    rows=summarize(root,jobs)
    comparisons=json.loads((root/'comparisons.json').read_text())
    assert len(comparisons)==3 and not any(c['unexpectedDifferences'] for c in comparisons)
    current=json.loads((regression/'runs.json').read_text())
    reference=json.loads((output/'T8-regression-runs.json').read_text())
    assert len(current)==26
    regressions=[]
    for run in current:
        assert run['state']==('failed' if run['scenario']=='examples/drones/error' else 'passed')
        entry={'scenario':run['scenario']}
        for variant in ('baseline1','baseline2'):
            old=next(r for r in reference if r['scenario']==run['scenario'] and r['variant']==variant)
            entry[variant]=compare(regression_jobs,old['jobId'],run['jobId'],output)
            assert not entry[variant]['unexpectedDifferences'],(run['scenario'],variant)
        regressions.append(entry)
    profile_runtime=jobs/profile_job/'runtime'
    profile=json.loads(next(profile_runtime.glob('world/opencomputers/*/home/equivalence.json')).read_text())['warehouseMemory']
    assert profile['profileOnly'] and profile['allocationProfile']
    python_log=Path('.cache/t10-python-final2.log').read_text()
    assert re.search(r'^OK \(skipped=1\)$',python_log,re.M)
    python_tests=int(re.search(r'Ran (\d+) tests',python_log).group(1))
    suites=[ET.parse(p).getroot().attrib for p in Path('build/test-results/test').glob('TEST-*.xml')]
    java={k:sum(int(s.get(k,0)) for s in suites) for k in ('tests','failures','errors','skipped')}
    assert java=={'tests':92,'failures':0,'errors':0,'skipped':0}
    output.mkdir(parents=True,exist_ok=True)
    def save(name,data): (output/name).write_text(json.dumps(data,indent=2)+'\n')
    save('T10-measurements.json',rows)
    save('T10-cycle-runs.json',{'jobsRoot':str(jobs),'runs':json.loads((root/'runs.json').read_text())})
    save('T10-cycle-comparisons.json',comparisons)
    save('T10-failed-attempts.json',json.loads((root/'failed-attempts.json').read_text()))
    save('T10-superseded-shortfall.json',json.loads((root/'superseded-shortfall.json').read_text()))
    shutil.copyfile('.cache/t10-failed-power.json',output/'T10-failed-native-power.json')
    save('T10-regression-runs.json',{'jobsRoot':str(regression_jobs),'referenceRoot':str(output),'runs':current})
    save('T10-regression-comparisons.json',regressions)
    save('T10-ui-allocation-profile.json',{'jobsRoot':str(jobs),'jobId':profile_job,'measurement':profile})
    source=Path('.cache/t10-furnace-source')
    shutil.copyfile(source/'generated/TileEntityFurnace.java',output/'T10-TileEntityFurnace.java')
    shutil.copyfile(source/'provenance.json',output/'T10-furnace-source-provenance.json')
    normal=[r for r in rows if r['case']!='concurrent-probe']
    measured=next(r for r in normal if r['case']=='128' and r['mode']=='coordinated')
    no_ui=measured['memory']['withoutUI'];ui=measured['memory']['withUI']
    low=min(r['memory']['withUI']['minimum'] for r in normal if r['memory']['total']==1048576)
    ram2=next(r for r in normal if r['case']=='ram2')
    probe=next(r for r in rows if r['case']=='concurrent-probe')
    state_table=[];metrics_table=[];memory_table=[];identity_table=[]
    for r in normal:
        label=r['case']+' / '+r['mode'];w=r['cycle'];m=r['memory'];f=w['furnaces']
        state_table.append(f"| {label} | {w['afterScan']['brick']} | {w['stock']['filtered']} + {w['stock']['priority1']} | 0 / 4 | {f['furnaceA']['fuel']} + {f['furnaceB']['fuel']} | {w['doneJobs']} done, {w['partialJobs']} partial |")
        metrics_table.append(f"| {label} | {r['wholeGameSeconds']:.2f} | {r['wallSeconds']:.3f} | {r['trips']} | {r['stops']} | {r['droneEnergyConsumed']:.1f} | {r['flightSeconds']:.2f} | {r['outputFaceStationarySeconds']:.2f} | 0 |")
        memory_table.append(f"| {label} | {m['total']:,} | {m['withoutUI']['steady']:,} / {m['withoutUI']['minimum']:,} | {m['withUI']['steady']:,} / {m['withUI']['minimum']:,} |")
        identity_table.append(f"| {label} | `{r['jobId']}` |")
    phase_table=[]
    for name,phase in profile['allocationProfile'].items():
        phase_table.append(f"| `{name}` | {phase['calls']} | {phase['allocated']:,} | {phase['max']:,} | {phase['gcReturns']} |")
    sizes=measured['memory']['codeBytes']
    text=f'''# T10 — warehouse-fed native furnace cycle

## Outcome and API finding

The generated `examples/warehouse/furnace-cycle` proves real 64-chest stock,
two drones, neighbouring-node mapping/Theta* routing and two vanilla furnaces
through the public warehouse/logistics APIs. The 128, 100 and native shortfall
cycles pass in baseline and coordinated mode: **three comparisons, zero
unexpected differences**, including native chest inventories and catalogue
state. The fresh **26-scenario regression / both T8 baselines** also passes:
**52 comparisons, zero unexpected differences**. Python: **{python_tests} tests,
one skipped**; fresh Java: **92 tests, no failures/errors/skips**.

### Finite power admission and preserved failed attempt

Initial shortfall baseline `137be99068824bb582d05a11e3b23e31` hit 36,000
ticks / 1,813.437 wall seconds after depositing the correct 108 bricks.
It is **not accepted** and remains in `T10-failed-attempts.json` with its
original native runtime. One final North scan retained only its initial
327.35-second timestamp; South completed at 1442.25. Native saved tile NBT
shows the second charger and its neighbouring positive-z capacitors at zero,
the first charger at only 432.4 energy, and drones at 648.4 / 1014.8 energy.
Furnaces were empty except for two unburned coal in A. This is evidence of
inadequate finite charger supply, not proof of a lost radio packet.

The generated fixture now adds six initially charged 1,600-energy capacitors
in loaded positive-z cells (9,600 finite energy total); **no runtime topups**
or library charging-policy changes were made. The accepted shortfall baseline
and coordinated retry share that amended power bank and test-only bounded
public-state diagnostics. The original 128/100 comparison pairs and RAM
samples used the original bank; power does not change their final stock.
The retry observer writes progress/error evidence through public APIs and
uses a 600-second per-job test guard inside a 42,000-tick engine bound.

Raw differences retain clock leaves and completed-stock-scan history eviction
differences. The latter are classified only for whole missing `done` one-trip
stock-read records, with both histories still containing 32 entries, equal
finished/partial/trip totals, and the present read's positive item/stack-limit
and free-slot data matching its side's final catalogue. Transfer/machine reads,
partial/failed states, changed record bodies and all stock remain strict.

**Concurrent fetch is not reservation-aware.** A separate native probe submits
two 64-clay fetches against the same scanned 128-clay catalogue. It produces
**64 done + 14 partial**, leaving **50 clay in stock**, with **78 clay in the
two furnace input faces**; a real read reconciles 78 + 50 = 128. Both requests
choose the nearest 50-clay source plus 14 from the other 50-clay source, because
pending allocations do not reduce candidate counts. Probe job:
`{probe['jobId']}`. This is an API finding, not a successful fully concurrent
64+64 loading claim.

The complete cycles use the closest safe API-only schedule: clay + coal fetch
jobs run together on the two drones for furnace A, then clay + coal for furnace
B after the first clay job's finished signal updates the catalogue. Both
furnaces smelt concurrently after loading; simultaneous clay-fetch submission
requires pending-stock reservations or an explicit disjoint-source selection
interface, neither of which the public warehouse API supplies. No such policy
was added. `warehouse.store` **does accept `wait`**, forwarding it to
`logistics.job`; collection uses a finite timeout. Store submissions are also
sequenced so destination capacity reflects the preceding finished delivery.

## World, cycle and strict inventories

The room uses alternating vanilla normal/trapped chests so all 64 members
expose independent 27-slot inventories. Clay is split **50 + 50 + 28** across
different heights/walls; the 100-seed variant uses **50 + 50**. Stock coal is
20; unrelated stock is 17 iron ingots and 26 stacks of stone. The filtered
priority-5 brick chest has exactly one free stack; the unfiltered priority-1
chest is empty. Other settings are unset. The furnaces at (10,64,7)/(10,64,9)
have `furnA.in/.fuel/.out`, `furnB.in/.fuel/.out` and named `furnace` groups.
Every explicit map link joins nodes exactly one block apart; Theta* plans the
remaining flight geometry. Power is finite charged native capacitors, with no
running top-ups or creative power.

1. Scan all 64 stock members and assert clay/coal/brick seed counts.
2. Fetch the per-furnace clay allocation and eight coal through group roles.
3. Only the test sleeps for the pinned source-derived smelt time; the
   controller libraries remain event-driven. Read real output faces to count
   the bricks, then call `warehouse.store` without
   choosing a destination chest, with `wait = {{timeout = allocation*10+60}}`.
4. Assert filtered/priority placement and catalogue totals **before** the final
   native stock scan, then assert that scan agrees. Real machine input/output
   reads are empty; remaining fuel is read through bottom face slot 2. Native
   final drone inventories are empty and both drones return to their chargers.
5. The shortfall seam removes 20 clay from the real (7,68,3) source after scan,
   using native `IInventory.decrStackSize`, then signals the controller. The
   first fetch requests 64, moves 44 and reports partial; stock is corrected
   before the second 64-clay fetch. Completion is 108 bricks, shortage 20.

| Run | Stock bricks | Filtered + priority-1 | Stock clay / coal | Fuel A + B | Job outcomes |
|---|---:|---:|---:|---:|---|
{chr(10).join(state_table)}

All final stock catalogues agree with the real final scans. All furnace input
and brick-output counts are zero. The 100 cycle loads 50+50, consumes seven
coal per furnace and leaves one each; shortfall loads 44+64, consumes six+eight
and leaves two+zero. Stock coal is always **20 - 16 = 4**. The deliberate partial
fetch is the only nondone job in shortfall; normal cycles have all 138 jobs
done. Logistics retains its most recent 32 completed jobs; the test counts
every finished signal before older records are evicted. Group roles remain
non-stock, and their contents are last-known observations rather than automatic
machine-processing accounting. Fuel figures above are real bottom-face reads.

## Pinned smelting/fuel source

`T10-TileEntityFurnace.java` is generated Java source from the pinned Forge
**1.12.2-14.23.5.2860**, **stable_39-1.12** mapped class, decompiled locally with
ForgeFlower 1.0.342.8. Its exact archive/class SHA-256 identities are recorded
in `T10-furnace-source-provenance.json`; it is not an unrelated online mirror.

- `update`, lines **153–197**: burn ticks decrement, fuel is consumed on burn
  start, cook ticks increment and `smeltItem` runs at `totalCookTime`.
- `getCookTime`, lines **206–208**: returns **200 ticks/item**.
- `getItemBurnTime`, lines **252–287**: Forge's optional burn-time hook precedes
  the vanilla `Items.COAL` branch, which returns **1600 ticks/coal**. The native
  fixture uses the vanilla clay-to-brick recipe with no fuel override.
- The pinned Forge source archive's
  `patches/net/minecraft/tileentity/TileEntityFurnace.java.patch` supplies the
  sided inventory capability wrappers and hook; the measured T4 face facts
  are top/input slot 1, side/fuel slot 1, bottom/output slot 1 + fuel slot 2.

At 20 TPS this is **10 seconds/item**, **80 seconds/coal**, and **eight items
per coal**. 64 items require **12,800 ticks / 640 seconds / eight coal**;
50 require **10,000 ticks / 500 seconds**, using seven coal. The shortfall
44-item furnace needs **8,800 ticks / 440 seconds**, using six coal. Its cycle
still sleeps the requested 64-item duration to cover the other furnace.

## Native timing, trips, stops and energy

| Run | Game seconds | Wall seconds | Trips | Stops | Drone energy consumed | Flying seconds | Output-face stationary seconds | Smelting-wait seconds |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(metrics_table)}

Game seconds above are the complete native job (`ticks/20`); controller-only
cycle durations are preserved separately in `T10-measurements.json`. Wall time
is the runner's complete submit-to-completion measurement, including startup.
Flying/output figures sum both drones' game-time intervals, not wall time.
The opt-in existing Java observer records every native tick's position, target,
velocity and successful energy debit counter. Flying means offset or speed is
at least 0.02; a stop is a changed native target subsequently reached below
both production thresholds. Every commanded flight reaches its target. Stops
include routed intermediate waypoints and return/charge flights. Energy is
successful native drone machine/radio energy debits, including idle/sleeping
cost, excluding recharge; it is not just final buffer loss or controller energy.
The observer adds no synchronized drone callbacks or firmware instrumentation.

All output reads already contain the full loaded batch. No smelting remainder
exists when store takes begin, so **smelting wait is zero**. The small stationary
output time includes real read/take calls and callback latency; it is not
mislabeled as waiting for bricks. Waiting does **not** dominate flying. The
cheapest existing-API alternative to early face waiting is already used here:
submit collection near the source-derived expected completion time, and keep
a bounded `wait` for timing slippage. No scheduling library was built for this.

## Controller deployment memory — bytes free

The same catalogue, groups and 32 retained finished jobs are present. The
160×50 GPU stub returns immediately and owns **no character, colour or row
buffer**. The driver is compiled before baseline sampling. All four tabs and
Item/Storage/Machine/Job details are rendered and sampled after every frame.
The test uses bounded zero-time yields before steady samples to permit the
existing OpenOS kernel GC; production UI code is unchanged and has no GC/polling
timer. These are native controller Lua heap samples, not JVM RSS or guaranteed
transient peak bounds. Compiled test/observer code is already present in both
baselines and is not charged as a UI delta; no fake framebuffer is retained.

| Run | Total RAM | Without UI: steady / minimum | With UI: steady / minimum |
|---|---:|---:|---:|
{chr(10).join(memory_table)}

The one-stick observed minimum is **{low:,} bytes**, below 64 KB. In the 128
coordinated run, no-UI steady free is **{no_ui['steady']:,}**, post-load free is
**{measured['memory']['afterLoad']:,}**, open-UI steady free is **{ui['steady']:,}**
and render minimum is **{ui['minimum']:,}**. Loading costs roughly
**{no_ui['steady']-measured['memory']['afterLoad']:,} bytes**, open steady state
adds about **{no_ui['steady']-ui['steady']:,} bytes**, but rendering can transiently
consume much more. Two sticks provide **2,097,152 bytes**; the independent
128-item two-stick case has **{ram2['memory']['withUI']['steady']:,} steady free**
and **{ram2['memory']['withUI']['minimum']:,} minimum free**. Larger heaps may
defer GC longer, so minimum free does not simply rise by exactly one megabyte.

### Where the UI memory goes

Deployed source sizes: view **{sizes['/usr/lib/logistics/warehouse/view.lua']:,}**, UI
**{sizes['/usr/lib/logistics/warehouse/ui.lua']:,}**, unmodified qmenu
**{sizes['/lib/qmenu.lua']:,}** bytes (combined **39,122**). OpenOS term is
**{sizes['/lib/term.lua']:,}**, tty **{sizes['/lib/tty.lua']:,}**, cursor
**{sizes['/lib/core/cursor.lua']:,}**, full_cursor
**{sizes['/lib/core/full_cursor.lua']:,}**, keyboard
**{sizes['/lib/keyboard.lua']:,}** bytes. Text size is not compiled heap size,
and some OpenOS modules are already loaded before UI entry.
The independent probe confirms keyboard and tty were already loaded before
UI entry; term was not. Source-file existence is not a claim of heap ownership.

A separate two-stick diagnostic (`{profile_job}`) samples freeMemory around
transparent public API calls, pure view building and qmenu drawing. Its
baseline preloads view/qmenu for wrapping and is **excluded** from deployment
comparisons. Positive free-memory losses, maximum per call and GC-return calls
are reported; these are net heap deltas rather than an allocation trace.
They include small wrapper/packed-return overhead and any GC occurring inside
a call; they are attribution evidence, not exact ownership accounting.

| Phase | Calls | Sum positive loss | Maximum call loss | GC-return calls |
|---|---:|---:|---:|---:|
{chr(10).join(phase_table)}

`ui.snapshot` rebuilds copies of members/groups/storages, compact jobs/drones
and every named storage's contents on each dirty navigation frame. Public
copy isolation uses serialization/unserialization; repeating those snapshots
creates temporary tables, strings and compiled unserialization chunks. View
row/model rebuilding adds transient allocation; qmenu retains only options
and draw state, and this GPU has no Lua framebuffer. The load/steady deltas
and phase samples distinguish code footprint from repeated render churn.

**Proposed cheapest reduction (not built): cache public warehouse contents
across navigation-only renders, invalidating them on the existing warehouse
change signal, and cache compact jobs until logistics work/finished signals;
continue refreshing map metadata and selected job detail through public APIs.**
This preserves public API isolation, qmenu and event-driven drawing, and avoids
re-copying all 64 inventories simply to enter/back out of a detail screen.
Recommended controller RAM for this deployment: **two ram6 sticks (2 MB)**.

## Artifacts, verification and boundaries

All new cycles use `C:/or/drone-install-T10`, freshly built from this source.
Only generated acceptance programs, measurement/comparison helpers and the
fixture-scoped native 20-item player-action seam changed. Canonical
`drone-logistics/usr/lib/logistics/*`, loader and agent are unchanged and byte-identical in
generated deployments; qmenu remains unmodified. The controller test drives
processing; opaque machine groups do not automate smelting.

| Run | Job ID |
|---|---|
{chr(10).join(identity_table)}

Artifacts beside this report: `T10-cycle-{{runs,comparisons}}.json`,
`T10-measurements.json`, `T10-regression-{{runs,comparisons}}.json`,
`T10-ui-allocation-profile.json`, `T10-TileEntityFurnace.java`, and
`T10-furnace-source-provenance.json`.
The preserved failed/superseded attempts and saved power NBT are in
`T10-failed-attempts.json`, `T10-superseded-shortfall.json`, and
`T10-failed-native-power.json`.
Raw native runtime directories contain
`route-observations.ndjson`, `result.json`, console logs and the controller's
`home/equivalence.json`. Regression artifacts preserve both native root paths.
Logs: `.cache/t10-cycles.log`, `.cache/t10-regression.log`,
`.cache/t10-memory-profile.log`, `.cache/t10-python-final2.log`,
`.cache/t10-java.log`. Fresh Java command: `gradle test --rerun-tasks` with the
pinned Java 8 / Gradle 4.9 installation. Fixture/source copies and Python tests
are green; `git diff --check` is clean.

Superseded development probes are not acceptance runs: the first exposed
status-before-finished-signal ordering; later probes corrected compact-job
trip counters and UI key/acknowledgement sequencing. These were test harness
fixes, not library changes. A successful early 128-item probe measured 130,850
minimum free bytes; the fresh matrix's 9,761-byte render sample demonstrates
why that single earlier minimum is not a safe deployment recommendation.

Remaining boundaries: real GPU/keyboard text-entry smoke testing is outside
this headless native runner; sampled memory minima are not a peak bound.
The furnace cycle does not exercise an actually still-smelting store remainder
because its source-derived sleep covers the full batch; the existing native
logistics wait regression covers delayed source availability/timeouts. Fully
concurrent automatic fetch/store selection remains an explicit API limitation.
'''
    (output/'T10-report.md').write_text(text,encoding='utf-8')
    return output/'T10-report.md'


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path('.cache/t10-cycles'))
    p.add_argument('--jobs-root',type=Path,default=Path('C:/or/drone-jobs'));p.add_argument('--regression',type=Path,default=Path('.cache/t10-regression'))
    p.add_argument('--regression-jobs',type=Path,default=Path('C:/or/drone-jobs-T10-regression'));p.add_argument('--profile-job',required=True)
    p.add_argument('--output',type=Path,default=Path('C:/or/drone-jobs'));a=p.parse_args()
    print(write(a.root,a.jobs_root,a.regression,a.regression_jobs,a.profile_job,a.output))
