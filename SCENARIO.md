# Scenario reference

A scenario is a `scenario.json` file that describes the world, the robot, the program to run, and what should be true when it finishes. Check one without starting a server:

```text
robot-runner validate PATH/scenario.json
```

(`robot-runner.cmd` on Windows, `sh ./robot-runner` on Linux.) Validation catches structural problems: duplicate or unknown keys, non-finite numbers, and booleans where integers belong. Whether blocks and items actually exist, and whether a robot recipe is legal, is checked later during server setup.

## Robot hardware (schema 3)

Schema 3 is what `init` and the examples use. It requires `robot.hardware`, either as a full recipe or as a reference to a preset. Execution is accelerated by default (`coordinated` mode, with OC's normal 12 ms worker delay). Schema 1 and 2 scenarios keep their old fixed loadout and defaults.

```json
"hardware": {
  "tier": 2,
  "cpu": "cpu2",
  "memory": ["ram3", "ram4"],
  "cards": ["redstonecard1"],
  "upgrades": ["inventoryupgrade", "craftingupgrade"],
  "containers": [{"item": "upgradecontainer1", "component": "inventoryupgrade"}],
  "storage": ["hdd2"],
  "bootDrive": 0
}
```

### Presets

`init` puts four editable recipes in the scenario's `hardware/` folder: `tier1.json`, `tier2.json`, `tier3.json`, and `creative.json`. Edit them, copy them, or write your own. To use one, optionally overriding some fields:

```json
"hardware": {
  "preset": "hardware/tier3.json",
  "overrides": {
    "memory": ["ram5", "ram6"],
    "cards": ["redstonecard1"],
    "upgrades": ["inventoryupgrade", "craftingupgrade"]
  }
}
```

Each override replaces the whole field (arrays aren't merged), and `[]` empties an optional list. A preset is a complete hardware object like the one above; presets can't reference other presets. The file must be a regular file (not a link) inside the scenario folder, at most 128 KiB.

Each job saves a copy of the preset and the final resolved hardware in its `inputs/` folder, so editing a preset later only affects new jobs. Presets go through exactly the same checks as a hand-written recipe.

### Recipe fields

Names are OpenComputers item names (`cpu3`, `ram6`), not Minecraft registry IDs. During setup, OC's own robot assembler checks slot types, tiers, compatibility, and complexity, exactly as in-game. The runner picks slots for you, including mixed tiers. `validate` only checks the shape of the recipe; the assembler decides whether it's legal.

- `tier`: 1, 2, 3, or `"creative"` (a real creative robot). Required.
- `cpu`: `cpu1`, `cpu2`, or `cpu3`. Required.
- `memory`: one or two modules, `ram1` to `ram6`. Required. Real capacities apply, so too little memory can fail OpenOS boot or your program.
- `cards`: up to three, such as `graphicscard1` or `redstonecard1`. Optional.
- `upgrades`: up to nine, such as `inventoryupgrade`, `inventorycontrollerupgrade`, `craftingupgrade`, or `batteryupgrade3`. Optional. The assembler decides which combinations fit.
- `containers`: up to three `{item, component?}` entries. The optional component goes into the container and has to fit it; for example, `cardcontainer1` can't hold an `inventoryupgrade`.
- `storage`: one or two HDDs, `hdd1` to `hdd3`. Required.
- `bootDrive`: index into `storage` (starting at 0) of the drive that gets OpenOS and your program. Required. Other drives start empty. Real capacity and speed apply.

The runner adds a BIOS EEPROM to the EEPROM slot and nothing else: no hidden CPU, RAM, upgrade, or disk. Inventory size follows the installed upgrades, up to 64 slots. Assembler warnings like "no screen" are fine for a headless robot. A legal recipe doesn't guarantee your program fits in it.

Starting energy can be up to 2,147,483,647, but setup rejects anything above the robot's actual capacity. The runner never tops up energy; only creative robots and chargers do.

### Experience upgrades

Use `"experienceupgrade"` for a fresh upgrade, or give it a starting level or exact XP, in `upgrades` or as a container's `component`:

```json
"upgrades": [
  "inventoryupgrade",
  {"item": "experienceupgrade", "level": 30}
]
```

Use either `level` (0–30) or `experience` (0–2,147,483,647, decimals allowed), not both. It's a tier-3 upgrade, so the slot or container has to support that. Presets and overrides accept the same objects.

Everything else is native OC: XP is gained from actions, levels change energy capacity, mining speed, and tool wear, and multiple upgrades stack as they normally would. XP above the level-30 threshold is kept. OC caps the effective level at 30, though Lua's `level()` can report a fraction above it.

Schema-3 replays record each robot's `energyCapacity`, `inventoryCapacity`, and every experience upgrade's level and raw XP.

### Creative robots and chargers

Set `tier` to `"creative"` (or use `hardware/creative.json`) for OC's real creative robot, which refills its own energy. Components are still configurable.

For a **finite robot that recharges**, use tier 1–3 and build a normal charger powered by an empty creative case. For a north-facing robot starting at `[0,65,0]`, add these to `world.blocks`, after any air-clearing volumes and inside `world.region`:

```json
[
  {"min":[1,65,0],"max":[1,65,0],"block":"opencomputers:charger"},
  {"min":[2,65,0],"max":[2,65,0],"block":"opencomputers:casecreative"},
  {"min":[1,64,0],"max":[1,64,0],"block":"minecraft:redstone_block"}
]
```

The creative case never runs out, but the charger behaves normally: it needs redstone, charges at its normal rate, and only reaches an adjacent robot. The robot spends its own energy while away and recharges when it comes back.

An empty creative case is the one exception to the "no other computers" rule, and only in schema 3. The runner checks every tick that it stays empty and switched off; putting anything in it fails the job. Copied worlds may contain such cases too.

## Drones and containers (schema 4)

Schema 4 uses either `robot`, or `drones` with an optional `computer` (never a robot
and computer together). A computer may have zero drones; without a computer,
`drones` must contain 1–16 entries (or may be empty when `robots` are present). Robot scenarios keep the schema-3
hardware, program, defaults and execution semantics. Drone scenarios omit `program`:
each drone boots its own EEPROM directly, without OpenOS or a disk.
Drone/computer scenarios accept `baseline` (the default) and `coordinated`;
`paced` is not accepted for these scenarios.

`drones` contains 1–16 entries:

```json
"drones": [{
  "position": [0,65,0], "eeprom": "eeprom.lua", "eepromData": "",
  "energy": 4000,
  "hardware": {"tier": 2, "cpu": "cpu1", "memory": ["ram2"],
               "cards": [], "upgrades": ["inventoryupgrade", "inventorycontrollerupgrade"]},
  "inventory": []
}]
```

Hardware names are OC item names. Tier is 1, 2, or `"creative"`; CPU and nonempty
memory are required. Memory is bounded to two modules, cards to three, upgrades to
nine; OC's **native drone assembler** decides which components actually fit each
tier and whether complexity is legal. No robot presets, storage or containers are
accepted in drone hardware. One inventory upgrade provides four drone slots;
two provide the native maximum of eight.

EEPROM paths are scenario-local regular `.lua` files with the same path/link rules
as other inputs, frozen with each job. Setup rejects code/data larger than OC's
configured EEPROM limits (UTF-8 bytes). Optional energy must be finite, positive
and no greater than the assembled native capacity; omission keeps OC's native
assembly energy. Optional inventory uses the robot item shape, with slots 1–8;
setup also checks the actual installed inventory capacity.

Placement uses OC's native entity initialization and world spawning, at
`[x+0.5,y,z+0.5]`. Native gravity and the native start target affect subsequent
positions; there is no teleport or position correction. Results report declared,
actual spawn, final exact and final block-containing positions. Drones finish when
all native machines reach `Stopped`; clean `computer.shutdown()` is success, while
any machine error or tick/time limit is failure.

Both kinds of v4 scenarios can declare up to 128 block inventories:

```json
"containers": [{"position": [0,64,0], "block": "minecraft:chest",
                "slots": [{"slot": 1, "item": "minecraft:iron_ingot", "count": 64}]}],
"expect": {
  "containers": [{"position": [0,64,0], "slots": [{"slot": 1, "count": 0}]}],
  "drones": [{"index": 0, "blockPosition": [6,65,0],
              "inventory": [{"slot": 1, "count": 0}]}]
}
```

Container positions must be unique and inside the region. Setup places the block,
using optional `properties` (for example, `{"facing":"south"}`),
clears its physical tile inventory and fills the listed slots (same metadata/NBT
shape as robot inventory). Slots are one-based, bounded to 64, and checked against
the native block inventory. Results include all declared containers' final contents.
Container expectations must reference a declared container. Listed expected slots
match item ID and count exactly; count 0 means empty, with or without an item ID.
A positive count requires an item ID. Unlisted slots are unconstrained.

`expect.drones` accepts up to 16 rows. Drone expectation indices are **zero-based**
and must reference a declared drone; inventory slots are **one-based**.
`blockPosition` and `inventory` are optional checks. Drone scenarios may also use
`expect.blocks`, but not robot-level `expect.position` or `expect.inventory`.
Failures identify the container/drone and the failing slot or position.
Periodic observations use the existing cadence and recording bounds, with drone
positions, energy and container contents. `observations` summaries support these
records; browser replay support for drones is not included.

### Multiple OpenOS robots (schema 4)

Drone/computer scenarios may also declare `robots`, with **1–4** entries. Each
requires `position`, a complete schema-3 `hardware` recipe, and `program` with a
scenario-local `directory` and optional Lua `entry` (default `main.lua`). Optional
`facing`, `inventory`, and `energy` follow schema-3 defaults and bounds. Hardware
can include native `craftingupgrade`, `inventorycontrollerupgrade`,
`inventoryupgrade`, and wireless cards. Native assembler rules still decide
whether the recipe fits. Robot cells must be air and robot positions unique.
An empty `drones: []` is allowed when robots are present, without a controller.

Each robot has its own native HDD/OpenOS instance. Program source directories
must not overlap other program or source-world directories; frozen/execution
copies are named `robot-program-0` through `robot-program-3`. Corresponding logs
are `robot-program-N.log`. Results and observations include indexed `robots`
states. Without a controller, all robot programs must return and stop cleanly.
With a controller, success waits for both declared controllers to return;
healthy robot services may remain running, like drone agents. Native robot errors
or program errors always fail, and robot inventory expectations still apply.
`expect.robots: [{"index": 0, "inventory": [{"slot": 12,
"count": 0}]}]` uses zero-based robot indices and the exact, one-based slot
checks described above; `inventory` is optional. Schema 2/3 behavior is unchanged.
See `examples/robots/crafting-smoke/` for two robots crafting tables from chests.

The final robot may be assembled later, after at least one existing robot, with
an optional `assembly` object:

```json
"assembly": {
  "source": [11, 65, 3],
  "blocks": [{"position": [12, 65, 1], "block": "minecraft:chest", "properties": {}}],
  "request": {"computer": 0, "marker": "home/assemble-robot", "signal": "robot_assembled"}
}
```

`source` must name a declared container. The selected controller writes the
marker relative to its OpenOS disk. The host consumes the robot's complete
hardware recipe, including a blank EEPROM, and one item per infrastructure
block from that container. Native OC rules validate the assembly; missing or
unused parts fail the case. The runner provisions the normal robot disk and
BIOS, places the robot and blocks in air cells, clears the consumed source,
then emits the requested signal. This stages player assembly and installation;
the robot's guest program owns subsequent networking and service startup.
`blocks` accepts `position`, `block`, and optional `properties`; energy seeding
is not part of assembly. Its inventory tiles can appear
in `expect.containers` and are included in physical results after placement.

### Explicit infinite energy and container removal (schema 4)

`execution.infiniteEnergy` is an optional boolean, default **false**. When true,
the runner enables OC's native global `ignorePower` setting for all declared
hosts. Reported energy may be zero under this native setting; it is not a
finite-energy measurement. Initial energy still obeys native capacity checks.
This option is independent of whether robots are present; schema 2/3 reject it.
Internet access remains disabled.

`containerEdits` declares up to 64 one-shot native stack removals, independent of
scenario ID. Targets must be declared containers. For example:

```json
"containerEdits": [
  {"position": [0,64,0], "slot": 1, "count": 2, "atTick": 100},
  {"position": [2,64,0], "slot": 1, "count": 20, "expectedCount": 50,
   "request": {"computer": 0, "marker": "home/warehouse-remove-items",
               "signal": "warehouse_items_removed"}}
]
```

Exactly one trigger is required: `atTick` (0 through `execution.maxTicks`, from
server startup), or `request`. Computer index 0 selects `computer`, 1 selects
`secondComputer`; that controller must exist. It requests removal by creating
the relative `marker` file on its OpenOS disk (the example is
`/home/warehouse-remove-items`). The runner signals the named event after removal.
`slot` is 1–64, `count` is 1–64, and optional `expectedCount` is `count`–64.
Insufficient items, an expected-count mismatch, or exceeding native slot capacity
fails the run. No stack is removed twice. Reload capture/resume explicitly rejects
scenarios with robots or nonempty container edits; their reload state is not yet
supported.

Native examples: `examples/drones/sides` proves absolute side numbering,
`examples/drones/transfer` carries 64 iron ingots six blocks, and
`examples/drones/error` intentionally fails with `boom`.

### OpenOS controller, wireless and finite power

A schema-4 `computer` has a position, a native case recipe and its own program tree:

```json
"computer": {
  "position": [-3,65,2],
  "hardware": {"tier": 3, "cpu": "cpu3", "memory": ["ram6"],
               "cards": ["wlancard2"], "storage": ["hdd3"], "bootDrive": 0},
  "program": {"directory": "program", "entry": "main.lua"}
},
"blocks": [{"position": [-4,65,2], "block": "opencomputers:capacitor", "energy": 1600}]
```

Case tier is 1–3 (finite power only), memory is 1–2 modules, cards up to three,
storage is 1–2 HDDs, and `bootDrive` is a zero-based storage index. CPU, memory,
storage and bootDrive are required. The case's own host-aware native slot validator
checks component kinds/tiers; the real machine checks CPU, RAM and component limits.
No upgrades, robot containers, presets or creative power case are added for computers.
The pinned BIOS/OpenOS, frozen program paths and entry wrapper are exactly the robot
program mechanism, including `require`, console capture, return/error status and
shutdown. Program remains nested inside `computer`; there is no root-level `program`
in a computer/drone scenario.

In coordinated mode the scheduler owns every scenario drone and both computers;
an unexpected OC machine fails the run rather than using an untracked scheduler.
With a computer present, the run
ends as soon as its entry returns successfully or reports an error; drones need not
stop. Final assertions still apply, and any drone error observed during the run is
latched even if a later native wake clears that machine's last error. Results contain
`computer` position/state/error/network energy and program status, root `program`
status as with robots, and `program.log`. Samples also include the computer's state.
Without a computer, the existing all-drones-stopped completion rule is unchanged.

An optional `secondComputer` uses the same recipe and native power/boot/observation
checks as `computer`. It requires a primary computer and a different position.
Give it a separate scenario-local program directory (for example `client`);
the two program sources and any source world must not overlap. Each program tree
has the usual 4 MiB/256-entry/1 MiB-per-file bounds and is frozen independently.
The second source is normalized to `second-program`; on each independent native
HDD its entry still runs from `/home/program`. With two computers, success waits
for **both** entries to return; an error on either fails the run. Results and samples
include `secondComputer`, including its program status; its host console and input
manifest are `second-program.log` and `second-program-inputs.json`.
`examples/mapping/service` and `examples/mapping/actions` exercise this layout.

Top-level `blocks` is separate from `world.blocks` volumes: up to 128 single-block
placements `{position,block,properties?,energy?}` inside the region, applied after
world volumes and before containers/hosts. Duplicate positions within this list are
rejected. Properties use the existing bounded block-state shape. This new placement
field supports coordinated mode as well as baseline. Scenarios using this field
default to `baseline`; an explicit `execution.mode` overrides that default.

Optional `energy` is a finite number from 0 to 2,147,483,647, checked against the
native **local connector capacity** after native network initialization. Only native
non-machine OC connector blocks can receive it; a normal block or case cannot. The
runner fills the connector once during setup through OC's own buffer API, never
refills it, and never disables power costs. Capacitor capacity depends on native
adjacency, so adding energy greater than its real capacity fails setup. A standalone
capacitor's default capacity is 1600. Cases, chargers and cables connect and draw power
through the real network; wireless traffic uses real OC cards and their power costs.

Drone expectations additionally accept `minEnergy` (finite, nonnegative) and
`running` (boolean, native `machine.isRunning()`, not a particular transient scheduler
state). `lastError` and latched `observedError` are reported for each drone. Clean wake
and shutdown remain native operations, without harness restarts or state persistence.

Native examples: `link` pairs a wireless OpenOS controller and drone for a directed
64-iron transfer and return; `wake` proves wrong-token rejection and native directed
wake, recording whether the waking packet is visible after boot; `charge` fills one
capacitor once and observes a real redstone-enabled charger raising drone energy from
500 to at least 2000. All three use the standard tier-2 drone recipe with CPU1, RAM1,
WLAN2, inventory controller and inventory upgrade. The wake example stores the
controller address alongside its six-character token in native EEPROM data during
the run, solely to direct the reboot's reply when the waking packet is not visible.

## A minimal scenario

```json
{
  "schemaVersion": 3,
  "id": "my-robot",
  "program": {"directory": "program", "entry": "main.lua"},
  "world": {
    "region": {"min": [-2,64,-6], "max": [2,67,2]},
    "blocks": [
      {"min": [-2,64,-6], "max": [2,64,2], "block": "minecraft:stone"},
      {"min": [-2,65,-6], "max": [2,67,2], "block": "minecraft:air"}
    ]
  },
  "robot": {
    "position": [0,65,0], "facing": "north", "energy": 20000,
    "hardware": {
      "tier": 3, "cpu": "cpu3", "memory": ["ram6"],
      "upgrades": ["inventoryupgrade"], "storage": ["hdd3"], "bootDrive": 0
    }
  },
  "execution": {"mode": "coordinated", "maxTicks": 10000, "timeoutSeconds": 600},
  "observations": {"everyTicks": 20, "maxBytes": 33554432, "onFull": "stop"}
}
```

Put your program in `program/main.lua`. It runs on normal OpenOS, and `require` finds sibling files in `/home/program`. Returning from the file means success. Calling `computer.shutdown()` before returning, a Lua error, or hitting a limit all count as failure. The runner works on a copy, so your original files are never changed.

## Fields

| Field | Meaning |
|---|---|
| `schemaVersion` | 1–4. Required. Use 3 for robots or 4 for drones/declared containers. |
| `id` | Scenario name matching `[a-z][a-z0-9-]{0,62}`. Required. Each job also gets its own generated ID. |
| `program.directory` | Folder with your Lua program, inside the scenario folder. Required. |
| `program.entry` | `.lua` file to run, relative to that folder. Default `main.lua`. |
| `world.region` | Box (`min`/`max`, inclusive) that's set up and recorded. Required. X and Z within ±1,000,000, Y from 1 to 254. At most 32,768 blocks and 64 chunks. |
| `world.source` | Optional folder with a world (`level.dat`) to start from. It's copied first. Omit to start from a fresh world. |
| `world.blocks` | Up to 128 `{min,max,block,properties?}` fills inside the region, applied in order. |
| `robot.position` | Starting position inside the region. Must be air after setup. Required. |
| `robot.facing` | `north` (default), `south`, `east`, or `west`. |
| `robot.hardware` | Schema 3: the recipe described above. Required. Schema 1/2: only `tier3`, a fixed CPU3, RAM6, inventory upgrade, and OpenOS floppy. |
| `robot.energy` | Starting energy. Default 20,000. Max 2,147,483,647 in schema 3 and 50,000 in schema 1/2, and never above the robot's real capacity (20,500 for the schema 1/2 robot). |
| `robot.randomSeed` | Schema 3 only. Optional 0–2,147,483,647. Seeds the robot's RNG for repeatable tool wear. Doesn't seed the world or Lua. |
| `robot.tool` | `{item,metadata?,nbt?}`. Default: a diamond pickaxe. |
| `robot.inventory` | `{slot,item,count,metadata?,nbt?}` entries, one per slot, count 1–64. Schema 3: up to 64 entries in slots 1–64, but only slots the robot actually has. Schema 1/2: up to 16. |
| `expect.position` | Optional final position the robot must be at. |
| `expect.blocks` | Up to 256 `{position,block}` checks on final blocks. |
| `expect.inventory` | Up to 64 `{item,minCount}` checks on final inventory totals (minCount 0–1024). |

Registry IDs are up to 128 bytes, and item metadata is 0–32767. NBT is SNBT text, up to 4,096 bytes and 16 levels deep. Block `properties` is up to 16 name/value pairs, such as `{"facing":"north"}`. Block checks compare IDs only, not properties or NBT. Inventory checks add up all stacks of an item regardless of metadata or NBT.

### Paths and sizes

Paths use `/`, stay inside the scenario folder, and can't be links, absolute paths, `..`, Windows reserved names, or names that differ only by case. The program, world, and output folders can't overlap.

- Scenario file: 128 KiB, both as written and after the runner normalizes it.
- Program folder: 4 MiB total, 256 entries, 1 MiB per file. Empty folders are kept.
- Source world: 256 MiB, 10,000 entries.

Only use worlds you trust; the runner doesn't defend against malicious world files. Loaded computers, racks, and drones in the world fail setup, apart from the empty creative cases above. Schema 1/2 reserve the world path `opencomputers/robot-runner-disk`. Schema 3 always creates a fresh HDD.

## Execution

| Field | Schema 3 | Schema 2 | Schema 1 |
|---|---|---|---|
| `execution.mode` | `coordinated` (default), `baseline`, or `paced` | `baseline` (default) or `coordinated` | `coordinated` (default, old version) or `baseline` |
| `execution.maxTicks` | Default 10,000, max 1,728,000 (24 hours) | Same as 3 | Max 10,000 |
| `execution.timeoutSeconds` | Default 600, max 90,000 | Same as 3 | Default 120, max 600 |
| `execution.executionDelayMillis` | 12 (default) or 0 | Same | Same |
| `execution.stallTicks` | 0 (off) to 1,728,000 | Same as 3 | Up to 10,000 |

`coordinated` skips idle time; see [how acceleration works](docs/simulation-time.md). `baseline` is plain native speed, and `paced` uses the accelerator's scheduling without skipping, for debugging. Schema 1's `coordinated` is an older, experimental version.

The time limit starts before input copying, and the tick limit includes server setup and boot, so neither measures just your program. Copying inputs and starting the worker have their own 30-second limit, and cleanup gets its own grace period. `wait --timeout` defaults to 600 seconds, accepts up to 90,000, and doesn't cancel the job when it runs out.

`stallTicks` fails the job if nothing visible changes for that many ticks: blocks in the region, or the robot's position, facing, energy, or inventory. It's off by default. Energy changes count as activity, and a sleeping program isn't necessarily stuck, so prefer final assertions for real checks.

`executionDelayMillis: 0` changes how OC schedules Lua and isn't needed for acceleration. When comparing runs, keep it and the hardware the same, and expect some natural variation between runs. See [How accurate is it?](README.md#how-accurate-is-it).

## Recording and replay

- `observations.everyTicks`: how often to sample, 1–200 ticks. Default 20.
- `observations.maxBytes` (schema 2/3): recording size limit, 1–32 MiB. Default 32 MiB.
- `observations.onFull` (schema 2/3): `stop` (default) keeps what was recorded and lets the job continue; `fail` fails the job with `observation_limit`. Schema 1 always fails at 32 MiB.

The first record holds the whole region plus the robot's state; later ones hold only changes. Once recording stops, it never restarts, so the replay never skips over missing time. A first record that's too big, any single record over 8 MiB, or a disk error fails the job either way. Stall detection keeps working after recording stops.

`observations-status.json` is a progress summary that may lag behind the recording itself; CLI summaries label it `missing`, `invalid`, `stale`, `consistent`, or `ahead`. The recording is the source of truth, and an incomplete last line is ignored. Results include the final `observationCoverage`.

The replay viewer shows only what was recorded. It handles up to 100,000 records and 500,000 block changes, writes at most 64 MiB, and gives up after 30 seconds. It keeps the last 128 KiB of console output. Samples come from the server thread, so they don't include entities, block-entity NBT, anything between samples, or anything outside the region. The region doesn't limit where the robot can go.

Other limits: runtime folder 2 GiB and 20,000 entries; two process logs at 8 MiB each; program console and result 1 MiB each; 2,048 loaded chunks; diagnostics input 40 MiB; and cleanup deletes at most 4 GiB and 40,000 entries. These limits are checked periodically; they aren't enforced by the OS. Failed runs keep their files for you to inspect.
