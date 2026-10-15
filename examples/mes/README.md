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
`C:/or/drone-install-MES-expansion`. `--installation <directory>` selects
another checked installation built from this checkout, including host modem
capture, 85-slot inventory assertions and deferred robot assembly. Use the
[repository setup instructions](../../README.md#quick-start) to build and
install the addon. This suite does not modify the installation.

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
| ocparts-repeat | Five memory components, then three additional components in the same live factory; reuse surplus intermediates, replenish burned fuel, and conserve stock |
| robot-parts | Thirteen successive orders manufacture a complete 85-slot crafting robot's parts, charger and buffer chest from raw stock |
| robot-expand | Manufacture those parts, deliver them for assembly, register the new robot, then make two RAM modules on it while both existing robots make chests |
| concurrent | simultaneous brick and torch requests; no same-robot overlap |

`robot-parts` orders a T3 case and CPU, two T3.5 RAM sticks, T3 HDD, T2
wireless card, crafting and inventory-controller upgrades, six inventory
upgrades, one T3 and two T2 upgrade containers, and a blank EEPROM. Three
inventory upgrades are built in; the other three occupy the containers.
This is the existing headless fixture robot: assembler complexity 31/32,
with 85 usable inventory slots. Charger and buffer chest complete the parts
order. Assembly, BIOS flashing, disk installation and adding the new robot
to the factory are separate steps, not proved by this case.

`robot-expand` continues those steps in the same server and world. Drones fetch
the manufactured parts into a pickup chest. Host staging consumes those exact
parts through OC's native assembler rules, flashes the EEPROM, installs the
canonical OpenOS/cproc disk, and places the robot, charger and buffer chest.
The new robot boots cproc through rc, announces and is paired through
`mes.registerRobot`. Three simultaneous MES requests exercise all three robots;
the new one makes two T3.5 RAM modules and each original robot makes one chest.
Acceptance checks sixteen completed orders, exact remaining material/fuel
counts, three empty 85-slot robots, and empty pickup/buffer inventories.
Assembly is player staging, not an automated MES assembly service.

`robot-parts.tsv` adds the required rows from the user's OC-Utilities recipe
database, with explicit native OC/vanilla ingredient choices. It shares the
existing OC-parts recipes and public PCB imports. Cutting wire is consumed
by the native diamond-chip recipe; it is not a reusable tool profile.

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
