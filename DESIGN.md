# Drone logistics — design

## Status (2026-10-06)

Built and verified in the accelerator (T1–T6): mapping, logistics, the drone
loader and program, the map service and tablet client. 24 native scenarios
(16 logistics, 2 mapping, 6 drone) pass at normal speed and accelerated, with
no differences in job results, inventories, positions or files (T6). Not yet
done: a hand test on a real tablet with the player's GPS, and an install
procedure.

This document is the design of record. Older documents from the discarded first
attempt have been removed.

## Decisions

### Systems and dependencies

- **Mapping** stands alone. **Logistics** requires mapping. **Warehouse** (the
  optional inventory-management system, formerly "inventory management") may use
  mapping and logistics. Logistics never depends on warehouse.
- Logistics is an OpenOS library: `require` returns its API table. The
  controller (fleet state, drone registry, pairing, scheduling) is internal to
  it. One instance per computer, shared by every program that requires it.
- Logistics receives drone messages through OpenOS `event.listen` handlers, so it
  runs without a dedicated foreground program. Handlers run inside whichever
  process calls `event.pull`; they must be short and never block. Natively
  confirmed (T3).

### Map access geometry

A drone accesses storage through absolute sides. Source-confirmed at the pinned
commit: the drone's `toGlobal` is identity (`common/entity/Drone.scala:235-239`)
and its inventory controller accepts any side (`checkSideAny`), acting on the
block adjacent to the drone's own block. A map node is therefore a block
position plus the absolute faces (0 down, 1 up, 2 north, 3 south, 4 west,
5 east) that have storage. Natively confirmed (T1, T4).

The side is the direction from the drone to the block; the block is accessed
through its opposite face (`WorldInventoryAnalytics.scala:129-136`). Sided
blocks show only that face's slots, renumbered from 1. Measured on a vanilla
furnace (T4): from above (side 0) slot 1 = input; from a side, slot 1 = fuel;
from below (side 1) slot 1 = output, slot 2 = fuel.

### Requests

- Callers may pass optional per-request settings: a retry count and a wait
  condition (until the requested amount is present, or a fixed time) with a
  timeout. Default: no wait; check once.
- On a mismatch (e.g. 48 present when 64 expected) the drone reports to the
  controller. The controller retries up to the configured count, then ends the
  job: `partial` if some items were delivered, `failed` if none were (or the
  request was invalid / unroutable). Logistics does nothing beyond that. Items
  left on a drone are reported in the job's `held` list, whatever the state.
- When waiting, the drone stays at the site and keeps checking, enforcing the
  timeout itself. It leaves only to recharge.
- First come, first served. No reservations, no priority. Several drones may
  use the same storage face concurrently.
- Endpoints are map node + absolute face + optional slots; the map may name
  them. A job is either a simple transfer or an ordered step list (take/put
  steps with a count or "all"/"rest") run as written. Drones
  execute the code they are sent, so the same mechanism serves transfers,
  inventory reads, and other programs' tasks (e.g. fly to a coordinate).
- Work too large for one trip is split. Options: `drones = N` (max drones in
  parallel; 1 = repeat trips by one drone; default: any free drone) and
  `split = false` (must fit one trip, else fail with actual numbers). Pieces
  are sized assuming 64 per stack; the drone takes what actually fits and
  reports it, and the controller reissues the remainder. A split step list
  is repeated until its counts are met; counts apply to the job total.
- Destination full or partial: leftovers return to where they were taken,
  or to an optional `overflow` endpoint. If that also refuses, the drone goes
  home holding them and the job reports what is held where. Items are never
  dropped into the world.
- Route blocked: the drone reports where it stopped; the controller asks
  mapping for a route avoiding that leg; if none, the job fails and the drone
  returns the way it came with its cargo. Blocked means the remaining offset
  has not shrunk by more than 0.1 blocks in 3 s (drones wobble, so small
  movement does not count as progress). Measured at a wall: 0.209-block
  recoil, then still; detection fired at 3.0 s (T4).
- Item matching: name and damage required, label optional. Source-confirmed
  (`integration/minecraft/ConverterItemStack.scala:55-61`): a drone sees name,
  damage, maxDamage, size, maxSize, hasTag, label (plus enchantments/lore);
  raw NBT only if `allowItemStackNBTTags` (default false). `maxSize` gives the
  real stack size at pickup.
- Deferred: the controller remembering reported stack sizes per item type, and
  automatically combining separate requests into one trip.
- Drone cargo capacity (source): 4 slots per inventory upgrade
  (`entity/Drone.scala:255-257`), max 8 (`Drone.scala:79`). A tier-2 drone has
  3 upgrade slots (`template/DroneTemplate.scala:87-89`), so 8 slots is
  reachable with two inventory upgrades plus the inventory controller.
- Drone complexity (source, `template/Template.scala:104-117`,
  `DroneTemplate.scala:137-140`): each part costs 1 + tier (CPU free), cap 5
  for tier 1, 8 for tier 2. Standard logistics drone: tier 2, wlancard2 (2),
  inventory controller (2), one or two inventory upgrades (1 each), one ram1
  (1) = 7 of 8. Tier 1 can't carry a 400-block wireless card plus cargo.
- Chargers charge drones near them only while they have network power and a
  redstone signal (`tileentity/Charger.scala:229-251`).
- Native proofs (T1): absolute drone sides 0-5 confirmed in-game;
  64-item A→B transfer with `getOffset()` arrival confirmed.
- Native proofs (T2): standard drone build (tier 2, cpu1, ram1, wlancard2,
  inventory controller, one inventory upgrade) assembles at complexity 6/8.
  A wrong first part does not wake a drone; its token does. **The woken
  program does not see the waking packet** (ports close and signals clear on
  start: `NetworkCard.scala:137-151`, `Machine.scala:900-903`), so a booting
  drone must contact the controller itself (the `"boot"` message). Chargers
  deliver in 10-tick batches at up to 100 energy/tick, limited by supply.

### Drones, pairing, and power

- Every drone runs the same small universal EEPROM loader. Drones have no
  filesystem: on every boot the loader downloads the program from the
  controller (packets of at most 8 parts / 8,192 bytes) and runs it with
  `load()` in RAM. No live code updates.
- Onboarding: an unpaired drone on its charger broadcasts about once per second.
  The controller's CLI lists announcing drones; registering one names it and
  sends its token by direct modem send. The drone writes its pairing record
  (short random token, controller address, name) into the EEPROM's 256-byte data
  area and restarts paired.
- At boot the drone sets its token as the modem wake message (fuzzy), and
  ignores any modem message whose first data part is not its token.
- Drones must never run out of power. One configured energy reserve: below it,
  the drone goes to its charger. No elaborate power measurement or budgeting.
  Source facts (`application.conf`): a running drone costs 0.4/tick, ×0.1
  while sleeping (`sleepFactor`); there is no drone movement cost; buffer
  5,000. So fly with long sleeps; energy goes to ticks awake and component
  calls. Idle drones back off their sleep up to 0.5 s on the charger.
- A booting drone resends `"boot"` every 5 s until the controller answers.
- A drone that restarts while idle at home resumes there. One that restarts
  while away (mid-trip) is marked `lost`: its trip ends by the normal rules,
  it gets no position and no work until a player puts it back on its charger
  and runs `logistics.found(name)`. No position guessing. While lost it
  turns its light red, shows `LOST` on its status text (2 lines of 10 chars,
  `entity/Drone.scala:342`) and waits in 60 s `pullSignal` loops.
- The controller persists only its drone registry, map and saved routes.
  World save/load relies on OC's native persistence of running machines:
  natively confirmed (T6) with a drone mid-flight carrying cargo; the
  controller's Lua state, the trip and a queued signal all resumed without a
  reboot. Nothing else is built for restarts.

### Layout, API and protocol

Files (OpenOS paths in parentheses):
- `drone-logistics/lib/map.lua` (`/lib/map.lua`): mapping, standalone.
- `drone-logistics/lib/logistics.lua` (`/lib/logistics.lua`): logistics library.
- `drone-logistics/drone/loader.lua`: universal drone EEPROM (≤ 4,096 bytes).
- `drone-logistics/drone/agent.lua` (`/lib/logistics/agent.lua`): drone
  program, sent by the controller at every drone boot, run from RAM.
- `drone-logistics/bin/logistics.lua` (`/bin/logistics.lua`): CLI.
- `drone-logistics/bin/mapd.lua` (`/bin/mapd.lua`): map service, controller.
- `drone-logistics/lib/mapclient.lua`, `drone-logistics/bin/mapclient.lua`:
  tablet map editor.

Mapping (`require("map")`, one shared instance, file `/etc/map.cfg`):
- `map.add(name, x, y, z, {faces = {[side] = true, ...}, charger = bool})`,
  `map.remove(name)`, `map.node(name)`, `map.nodes()`. Each node records its
  creation time (kept when the node is re-added) for newest-first listing.
- Named storages: `map.name(storage, node, side)`, `map.unname(storage)`,
  `map.storage(storage)` → `{node, side}`, `map.storages()`. Users and programs
  address storages by name; a node is the hover point and may serve up to 5.
- `map.link(a, b)` / `map.unlink(a, b)`: declares the straight flight between
  two nodes clear. Links are the only paths drones fly.
- `map.route(a, b, avoid)` → list of node names (A*, straight-line distance),
  or nil. `avoid` is an optional set of links to skip.
- `map.save()`, `map.load()`. Mapping knows nothing about items or drones.

Map editing: `mapd` serves the map over wireless (port 27104) to holders of the
key in `/etc/mapd.cfg`; wrong keys get no reply. Every edit saves the map.
The tablet client (`/etc/mapclient.cfg`: `key`, optional
`position = function() return x, y, z end` for the player's GPS, manual entry
otherwise) offers: here, position, nudge, add (asks whether it is a charger),
pick (search or newest-first), link, unlink, test, faces, scan, name, unname,
remove. `scan` and `test` need logistics loaded on the controller; a tested
link is saved only after the player confirms.

Logistics (`require("logistics")`):
- Endpoint: a storage name, or `{node = "name", side = 0..5}`; either may add
  `slots = {..}` (table form `{storage = "name", slots = {..}}`).
- Item: `{name = "minecraft:iron_ingot", damage = n?, label = s?}`.
- `logistics.transfer(item, count, from, to, opts)` → job id.
- `logistics.job(steps, opts)` → job id. Steps:
  `{take = endpoint, item = item, count = n | "all"}`,
  `{put = endpoint, item = item, count = n | rest = true}`,
  `{go = "node"}`, `{read = endpoint}` (listing in the job status). Counts are
  job totals; the list repeats until they are met.
- Saved routes (`/etc/logistics.routes`): `logistics.route(name, steps)`,
  `logistics.routes()`, `logistics.run(name, opts)`.
- `opts`: `retries`, `wait = {timeout = s}`, `drones = N`, `split = false`,
  `overflow = endpoint`.
- `logistics.status(id)` → state (`queued`, `active`, `done`, `partial`,
  `failed`), requested, moved, remaining, reason, held, trips, per-step counts,
  blocked reports. `logistics.cancel(id)` (queued jobs only).
- Finished jobs push `event.push("logistics", id, state)`; the last 32 finished
  jobs are kept.
- Drones: `logistics.drones()`, `logistics.pending()`,
  `logistics.register(address, name, homeNode)` (home must be a charger node),
  `logistics.forget(name)`, `logistics.release(name)` (held drone: reports its
  cargo, idle once empty), `logistics.found(name)` (lost drone back on its
  charger).
- Map actions: `logistics.scan(node)`, `logistics.test(a, b)`; ordinary jobs.
- Config `/etc/logistics.cfg`: `reserve` (energy, default 1000), `retries`
  (default 2). Port is fixed at 27103. Registry: `/etc/logistics.drones`.
- CLI: `logistics pending | register addr name home | forget name |
  release name | found name | drones | routes | run route | status id |
  transfer item count from to [damage [retries [drones]]]`.

Protocol (port 27103; every packet's first part is the drone's token, except
an unpaired drone's `"lgx_hello"` broadcast and the controller's `"lgx_pair"`
reply):
- Boot: drone → `token, "boot"` (resent every 5 s); controller →
  `token, "code", i, n, chunk` (≤ 2,048 bytes each), then
  `token, "start", x, y, z` with the home position, or `start` with no
  position for a lost drone.
- Work: controller → `token, "trip", tripId, serializedTask`; drone →
  `token, "report", tripId, serializedResult` (progress, charging, blocked,
  final). Navigation for step lists and reroutes: `"navigate"` /
  `"navigation"`. Held and lost drones: `"release"` / `"cargo"`, `"found"`.
- Drones parse data with `load("return " .. s, "=d", "t", {})`; no OpenOS on
  drones.

## Agnostic means compatible by construction

The basic request is: move this item, this amount, from A to B. Logistics
neither knows nor cares whether an endpoint is a chest, a machine or anything
else with an inventory face; it has no container-type branches. Machines are
named storages per face (e.g. a furnace's input, fuel and output).

Logistics needs no inventory catalogue and makes no survey trips. The drone
checks locally at the source, takes what is there, and reports actual counts.
Whole-inventory listings happen only through an explicit `read`.

The optional warehouse layer owns stock knowledge, source discovery and
policies (e.g. keep a destination stocked) and calls logistics with concrete
transfers. Mapping owns locations, faces, chargers, links, persistence and
routing, and knows nothing about items or drones.

## Mechanics evidence

OpenComputers source commit `8ca336fbeb92d2a29f86f9a658bb9d6bd6f07dbb`
(1.12.2-forge/1.8.9a), Forge 1.12.2-14.23.5.2860. Claims cite that source or a
native measurement. Worker reports with job IDs and full evidence:
`C:/or/drone-jobs/T1-report.md` to `T6-report.md`.
