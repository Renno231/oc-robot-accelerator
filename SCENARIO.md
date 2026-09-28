# Robot scenario reference

Use `robot-runner validate PATH/scenario.json` (Windows: `robot-runner.cmd`; POSIX: `sh ./robot-runner`) before a run. JSON rejects duplicate/unknown keys, nonfinite numbers, and booleans where integers are required. Registry existence, block properties, stack capacity and legal Minecraft states are checked during server setup. Validation never boots a server.

## Configurable hardware (schema version 3)

Version 3 is the default for `init` and the bundled examples. It requires `robot.hardware`: either a complete custom recipe or an explicit editable preset reference. It does not select a hidden preset. Execution defaults to accelerated `coordinated` mode with the native 12 ms worker-delay profile. Versions 1 and 2 keep their original loadout and defaults. Release verification is tracked separately from this contract.

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

### Editable presets and overrides

`init` copies four editable starting recipes into the new scenario's `hardware/` directory: `tier1.json`, `tier2.json`, `tier3.json`, and `creative.json`. You can edit them, copy them under new names, or create your own complete recipe. To select one:

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

`overrides` is optional. Each supplied field replaces that entire field; arrays are replaced, not appended. `[]` removes optional cards/upgrades/containers. Presets use the same complete hardware object shown above; they cannot refer to further presets. A preset must be a regular, nonlinked JSON file beneath the scenario directory, at most 128 KiB, with no duplicate or unknown keys. Paths outside the scenario are not allowed.

Each job freezes the original preset bytes as `inputs/hardware-preset.json` and the fully resolved hardware in `inputs/runner-scenario.json`, both hashed. Later edits affect new jobs only. Presets, overrides and direct custom configuration all use the same native assembly validation; presets do not bypass restrictions or hide additional equipment.

### Native recipe fields

Hardware names are pinned OC item-descriptor names, not Minecraft registry IDs. The native OC robot assembler and component drivers validate slot type, tier, host compatibility and total complexity during setup. The runner allocates compatible slots automatically, including mixed-tier combinations; callers do not supply engine slot indices. `validate` checks structure without starting Minecraft; it does not certify a legal native recipe.

- `tier`: required 1, 2, 3 or `"creative"` (native creative robot). `cpu`: required processor name (`cpu1`/`cpu2`/`cpu3`, subject to native compatibility).
- `memory`: required one or two modules (`ram1` through `ram6`). Their real capacities remain in effect; insufficient memory can fail OpenOS boot or the program.
- `cards`: zero to three names; `upgrades`: zero to nine built-in upgrades. Omitted lists are empty. Examples include `graphicscard1`, `redstonecard1`, `inventoryupgrade`, `inventorycontrollerupgrade`, `craftingupgrade` and `batteryupgrade3`; native tier/slot/complexity rules determine legal combinations, not these shape maxima.
- `containers`: zero to three `{item, component?}` entries. The container is installed by the assembler; its optional removable component must fit the resulting robot's actual equipment slot. For example, `cardcontainer1` cannot hold an `inventoryupgrade`.
- `storage`: required one or two native HDD names (`hdd1`/`hdd2`/`hdd3`). `bootDrive`: required zero-based index **into this list**, selecting where to install OpenOS and the copied program. Other configured drives start empty. Native capacity, access costs and buffering remain intact; the boot drive is not a hidden 32 MiB floppy.
- One runner-managed BIOS EEPROM occupies the native EEPROM slot and participates in assembly. No extra CPU, RAM, inventory upgrade or disk is injected.
- Inventory capacity follows the installed upgrades, from zero to the native 64-slot maximum. Version 3 accepts initial payload slots 1–64 but rejects slots beyond the assembled robot's capacity at setup. Initial energy may be up to 2,147,483,647 in the manifest but cannot exceed the actual connected capacity; battery upgrades are real components, not permission to ignore capacity. The runner never refunds energy. Native creative hardware and world chargers can replenish it as described below.

Program/world paths, trust requirements, recording limits and finite execution budgets remain as below. Native assembly warnings such as a missing screen do not prevent a valid headless recipe. A valid recipe is not a promise that every possible program fits its resources.

### Experience upgrade state

Use `"experienceupgrade"` for a fresh zero-XP upgrade, or configure its initial state in either `upgrades` or a container's `component`:

```json
"upgrades": [
  "inventoryupgrade",
  {"item": "experienceupgrade", "level": 30}
]
```

Alternatively use `{"item":"experienceupgrade","experience":400.5}` for exact raw XP. Specify exactly one of `level` (integer 0–30) or `experience` (finite number 0–2,147,483,647). These same objects work in editable presets and overrides. This is a native tier-3 upgrade: the selected built-in slot or removable upgrade container must support it.

The runner uses OC's own XP conversion and persisted component state before boot. It does not implement a replacement XP curve or modify the effects: native actions/consumption gain XP, native level changes resize energy capacity, and native handlers alter block-breaking time and tool damage. Multiple installed upgrades retain OC's native stacking behavior. Raw XP is preserved, including values above the level-30 threshold that can occur through overshoot; OC caps the effective integer level at 30, although its Lua `level()` callback can report a fractional value above 30 for that state.

Version-3 observations include `energyCapacity`, `inventoryCapacity` and `experienceUpgrades` (each installed upgrade's effective integer `level` and raw `experience`). These are sampled native state, not estimates. Initial energy is separately configured and must fit the resulting capacity; it is not automatically filled or refunded when XP grows.

### Creative robots and infinite-source chargers

Set `hardware.tier` to `"creative"`, or select `{"preset":"hardware/creative.json"}`. This uses OC's actual creative assembler template and robot, including native creative slots and periodic self-replenishment. Components remain configurable; initial energy must still fit native capacity. This does not enable global `ignorePower` or turn finite robots into creative robots.

For a **finite robot that must return to charge**, use ordinary tier 1–3 hardware and place a normal OC charger connected to an empty creative case. For a north-facing robot initially at `[0,65,0]`, include these volumes inside `world.region` (after any air-clearing volumes):

```json
[
  {"min":[1,65,0],"max":[1,65,0],"block":"opencomputers:charger"},
  {"min":[2,65,0],"max":[2,65,0],"block":"opencomputers:casecreative"},
  {"min":[1,64,0],"max":[1,64,0],"block":"minecraft:redstone_block"}
]
```

The creative case supplies energy indefinitely; the charger still uses native redstone control, adjacency, update timing and finite transfer rate. Removing the redstone signal stops charging. Moving away consumes the finite robot's own energy; returning allows it to recharge. Native connector-facing rules still apply if you rotate the blocks.

Only version 3 permits an **empty, nonrunning creative case** as a power source. Every tick checks that it remains empty and nonrunning; adding any component revokes the exception. Other loaded computers, racks and drones remain rejected. Trusted copied worlds may also contain these empty creative power cases.

## Minimal version 3 scenario

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

Create `program/main.lua` alongside the scenario. Ordinary OpenOS libraries are available; sibling `require` resolves from `/home/program`. Return from the entry file to complete. An explicit `computer.shutdown()` before return, Lua error or exhausted limit fails the job. Inputs are frozen; runtime file writes affect only the owned copy. Use the included examples for mining and assertions.

## Fields and defaults

| Field | Contract |
|---|---|
| `schemaVersion` | Required integer 1, 2 or 3. Use 3 for new scenarios; 1/2 remain compatible. |
| `id` | Required `[a-z][a-z0-9-]{0,62}`. Logical scenario label; jobs have independent generated IDs. |
| `program.directory` | Required scenario-local directory. |
| `program.entry` | Relative `.lua` file beneath that directory; default `main.lua`. |
| `world.region` | Required inclusive `min`/`max` coordinate box. Each position is `[x,y,z]`, X/Z between -1,000,000 and 1,000,000, Y between 1 and 254. At most 32,768 cells and 64 intersected horizontal chunks. |
| `world.source` | Optional scenario-local directory containing `level.dat`. Trusted closed compatible Minecraft world; copied before mutation. Omit for fresh world setup. |
| `world.blocks` | Up to 128 inclusive `{min,max,block,properties?}` volumes, wholly within region. Applied in order; later writes win. Default empty. |
| `robot.position` | Required position inside region; must be air after setup. |
| `robot.facing` | `north` (default), `south`, `east`, or `west`. |
| `robot.hardware` | Versions 1/2: only `tier3` (default); CPU3, RAM6, inventory upgrade, generated EEPROM and OpenOS floppy. Version 3: required native recipe object above. |
| `robot.energy` | Finite positive number, default 20,000. Version 3 ceiling 2,147,483,647; versions 1/2 ceiling 50,000. Setup rejects energy above actual capacity (legacy preset: 20,500). Supplied before boot, never refunded by the runner. Native creative power and charging remain active. |
| `robot.randomSeed` | Version 3 only: optional integer 0–2,147,483,647, seeds the native robot player's RNG once at setup for reproducible probabilistic wear comparisons. Not a whole-world or Lua RNG seed; omission leaves native randomness. |
| `robot.tool` | `{item,metadata?,nbt?}`; default diamond pickaxe, metadata 0, NBT `{}`. |
| `robot.inventory` | `{slot,item,count,metadata?,nbt?}` entries with unique payload slots. Version 3: up to 64 entries, slots 1–64; versions 1/2: up to 16, slots 1–16. Count 1–64; default empty. Native inventory capacity and item stack bounds also apply. |
| `expect.position` | Optional exact final position inside region. |
| `expect.blocks` | Up to 256 `{position,block}` final registry-ID assertions inside region. Default empty. |
| `expect.inventory` | Up to 64 `{item,minCount}` aggregate payload-count assertions, minimum 0–1024. Default empty. |

Registry IDs are at most 128 UTF-8 bytes. Item metadata is 0–32767. SNBT must be a balanced compound, at most 4,096 UTF-8 bytes and 16 nesting levels; Minecraft performs full syntax/registry interpretation. Block `properties` maps at most 16 names to string values (each at most 64 bytes), for example `{"facing":"north"}`. Final block assertions check IDs, not complete NBT/property equivalence. Item assertions aggregate IDs, not per-stack metadata/NBT.

All relative input paths use `/`, stay within the scenario directory, and reject links/reparse points, traversal, absolute paths, Windows reserved names and case-ambiguous entries. Program/world/output/template roots cannot overlap. Original and normalized manifests are each at most 128 KiB. Program tree: 4 MiB/256 entries, at most 1 MiB per file; empty directories are retained and bounded. World source: 256 MiB/10,000 entries. Copied worlds are **not an untrusted compressed-chunk sandbox**. Other machines in unloaded chunks are unsupported; loaded other OC computers, racks and drones fail setup/inspection, except version-3 empty nonrunning creative power cases described above. Versions 1/2 reserve `opencomputers/robot-runner-disk` and reject an imported world containing that path. Version 3 uses a fresh native HDD address and never reuses imported media for runner outcomes.

## Execution

| Field | Version 3 | Version 2 compatibility | Version 1 compatibility |
|---|---|---|---|
| `execution.mode` | `coordinated` default; `baseline` or `paced` explicit references | `baseline` default; legacy `coordinated` accepted | Legacy `coordinated` default; `baseline` accepted |
| `execution.maxTicks` | Default 10,000; 1–1,728,000 | Same as v3 | Default/max 10,000 |
| `execution.timeoutSeconds` | Default 600; integer 1–90,000 | Same as v3 | Default 120; 1–600 |
| `execution.executionDelayMillis` | 12 default; only 0 or 12 | Same | Same |
| `execution.stallTicks` | 0 disabled; 0–1,728,000 | Same as v3 | 0–10,000 |

In version 3, `coordinated` compresses globally idle waiting up to the next known native event. It retains world ticks, action delays, saves, power rules and world progress while Lua actively computes. Guest environment clocks include skipped time; CPU accounting and host watchdog/deadline clocks do not. Unknown or outstanding tracked background work prevents an idle jump. `baseline` retains the native scheduler and Minecraft pacing; `paced` uses the same worker-ownership machinery as `coordinated` but without idle jumps, for diagnostics. Neither reference is the default. Legacy coordinated execution remains a compatibility path, not the version-3 timing model.

Wall budget starts before input preparation. Tick budget includes engine setup/boot/program/closure; neither represents pure user-code CPU time. Input freezing and worker acknowledgement also have a 30-second bound; cleanup has a separate bounded grace. Choosing maximum tick and wall budgets does not guarantee reaching both. Foreground `run` waits against its job's deadline; explicit `wait --timeout` defaults to 600, accepts up to 90,000, and does not cancel the job on timeout.

`stallTicks` counts absence of changes in sampled region/robot position, facing, energy or inventory. It is opt-in and continues observing even if recording stops. Energy changes may prevent it from firing while Lua does no useful work; sleeping is not inherently stuck. Use final assertions and program-aware checks for stronger requirements.

`executionDelayMillis:0` explicitly changes OC worker scheduling configuration; it is not required for acceleration. Comparisons should match that setting and hardware, and account for random state and native cross-run scheduling variation. Native callbacks and world simulation execute unchanged; exact replay of arbitrary programs, CPU timings or stochastic worlds is not promised. See [README](README.md#fidelity-and-performance) for measured results and boundaries.

## Recording and playback

`observations.everyTicks`: integer 1–200, default 20. Versions 2/3 also accept `maxBytes` (1,048,576–33,554,432, default upper bound) and `onFull` (`stop` default or `fail`). Version 1 rejects these two extra keys and fails on its 32 MiB recording cap.

The first NDJSON record contains the complete observed block region plus robot state. Later samples contain changed cells and the selected robot state. `stop` retains a complete prefix and continues the simulation without further records; capture never resumes with deltas across an omitted interval. `fail` fails with `observation_limit`. Initial-record overflow, a record exceeding 8 MiB, or filesystem errors fail under either policy. Region sampling for stall detection continues after recording stops.

`observations-status.json` is a bounded atomic checkpoint with policy, byte/record counters, last recorded/observed ticks, stop reason and final-record flag. It can lag a growing stream. CLI summaries classify it as `missing`, `invalid`, `stale`, `consistent` or `ahead`; validated NDJSON remains authoritative, and an incomplete last line is excluded. Missing final data is not automatically success, failure or an active job. Results retain final available `observationCoverage`.

The offline viewer displays only retained samples. It additionally bounds input to 100,000 records/500,000 cell updates, output to 64 MiB, and export to 30 seconds. Console is a 128 KiB tail; trail dots may be thinned on screen while all retained states remain on the timeline. These are sampled server-thread observations, not atomic snapshots of every worker, and omit entities, block-entity NBT, transients between samples and state outside the region. Region is not a robot movement cage.

Other resource caps: runtime 2 GiB/20,000 entries, two process logs 8 MiB each, program console/result 1 MiB each, coverage and runtime-logging metadata 64 KiB each, at most 2,048 loaded chunks. Diagnostic input 40 MiB; explicit cleanup delete-set 4 GiB/40,000 entries. Polling bounds are not kernel quotas. Interrupted/failed runs retain available artifacts for inspection; the tool does not silently remove failure evidence.
