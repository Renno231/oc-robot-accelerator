# Native MES manufacturing suite

From the repository root:

```sh
python run_mes_scenarios.py
```

The command generates fresh fixtures from this checkout's canonical
`craftsystem/` and `drone-logistics/` sources. Four cases run concurrently;
each has its own fixture and jobs directory under `C:/or/mes-native/<timestamp>`.
Use `--root <fresh-directory>`, `--cases <names...>` or `--parallel 1` to narrow
a run. Existing roots are retained as evidence and cannot be overwritten.
Use `--machine-seconds 1 --cases bricks16` to exercise an underestimated
processing time through the same runner and acceptance checks.

The default installed native addon is
`C:/or/drone-install-MES-E2E-finalization`. `--installation <directory>` selects
another checked installation; it must support host modem capture and 85-slot
robot inventory assertions. This suite does not modify the installation.

## What runs

`build_fixtures.build_native()` builds the physical layouts and assembly disks.
`native.lua` installs under `/usr`, starts MES through rc, registers the six
announcing drones and pairs the unpaired robots through `mes.registerRobot`.
Robots start canonical cproc through rc. Registration readiness comes from the
MES's cached resource state. No host address books are prefilled.

Hardware: a fully populated T3 rack server, T3 screen/GPU, six drones, and
85-slot robots with two RAM sticks. Fixtures provide infinite power; finite
power behavior is outside these manufacturing cases.

| Case | Native acceptance |
| --- | --- |
| torches16 | 16 torches; same-recipe furnace top-ups precede collection |
| bricks16 | 64 clay becomes 16 brick blocks |
| specific-group | furnaceA selected; furnaceB unused |
| shortfall | remove 16 clay after planning; report failure without crafting blocks; conserve 48 clay/brick |
| concurrent-fetch | two independent 64-item deliveries from 128 stock |
| ocparts | 64 memory components; two robots; foreground submitter exits while the rc service continues |
| concurrent | simultaneous brick and torch requests; no same-robot overlap |

The layout's 64 stock inventories are surveyed by an initial warehouse scan.
These cases stage the map through its public library. They do **not** establish
tablet pairing, geolyzer survey, service restart recovery, or UI acceptance.

## Evidence and acceptance

Each case writes host-side `native.log`, `result.json`, `acceptance.json`,
`host-capture.ndjson`, `trips.json`, and frozen `fixture/source-hashes.json`.
The matrix writes `runs.json`. Physical native inventories and persisted MES
receipts supply acceptance checks; diagnostic wrappers do not run on OC.

`nativePassed` means the native case and physical/receipt checks passed.
`tripCoverageComplete` additionally requires every captured dispatch to have
a terminal wire report and a complete capture stream. The MES retains only
32 completed logistics jobs, so historical trip coverage comes from the wire
capture, with persisted receipts attached where retained.

Walk every trip before accepting a run: explain its purpose, check source and
destination, examine refusals, returns, shortfalls and repeated work. The command
leaves `tripReview: pending` and `accepted: false`; native success alone is not
a review verdict. Exit status is nonzero if any native case or capture fails.

Build a fixture on demand without running it:

```sh
python examples/mes/build_fixtures.py --root <directory> --case <name>
```

Keep generated case trees outside source control. Specialized MES cases reuse
the same assembly and registration bootstrap.

Focused checks:

```sh
python -m pytest test_mes_acceptance_gate.py test_mes_fixtures.py test_native_store_evidence.py -q
```
