# Drone logistics — design

## Status (2026-10-07)

Built and verified in the accelerator (T1–T9): mapping, logistics, the drone
loader and program, the map service and tablet client, straight-line routing.
Warehouse library, CLI and qmenu UI are built, including persistent opt-in stock,
groups, shared inventories and event-derived counts. 29 native scenarios
(18 logistics, 2 mapping, 6 drone, 3 warehouse) have normal-speed and accelerated
proofs. The T9 warehouse comparisons and refreshed 26-scenario regression match
their baselines in job results, inventories, positions and configuration;
clocks, CPU, memory and UI draw totals are measured separately. Not yet
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

### MES service and transport ownership

- MES is one installed, long-running service, guarded by `package.loaded`.
  Installation initializes mapping, logistics and warehouse, shared listeners
  and polling timers, and one API proxy plus pubsub client per paired robot.
  The service owns these resources across foreground commands and UI lifetimes.
- Manufacturing uses plain state machines: `update(run, what, data)` records a
  fact, then `advance(run)` starts every ready action. Decisions stay in this
  state machine; transport callbacks and polling only enqueue facts.
- `advance` never blocks and is never re-entered. One guarded `pump()` drains
  the fact queue; nested callbacks during connection setup only add to it.
  Robots use public `proxy:async(cb)` calls, drone actions are non-blocking, and
  the service tick supplies machine observations. Each outstanding RPC has a
  service-owned deadline because API async timeout is silent. A missed reply
  means unknown until an async status query reconciles it, never assumed idle
  or successful.
- The only blocking network call is public `api.connect`, during installation
  or service-owned reconnection. Reconnection restores subscriptions and queries
  status; it never blindly repeats a craft request. The service uses the frozen
  public networking libraries.
- Several runs are active at once. Robots, buffers, machine groups and tool
  reservations live in one shared world state. A machine group's loads may come
  from different runs, and each load's failure stops only its own run. Facts
  reach their run by run id, robot token or job id; the rest are world facts.
  The least recently served run decides first, and a run that just released a
  robot leaves it to a waiting run. Raw stock a run will take stays claimed in
  the MES until it is fetched or the run ends; planning sees stock minus other
  runs' claims. The warehouse stays physical.
- There are no OpenOS threads or process-internal registration pinning in the
  controller. The planner's plain coroutines retain their existing behavior.
  Foreground `mes.wait(runId)` may pull events; closing that caller does not stop
  the service or its run. Per-job cleanup removes only that job's subscription.
- Apply job-topic progress and terminal receipts only after admission or an
  owner-scoped status RPC confirms that the job belongs to this controller.
  If the admission reply is lost, retain the candidate receipt and reconcile
  through status; a shared pubsub topic is not ownership proof.
- Native evidence writes full execution and timing ledgers to separate files.
  Serialize compact frontend summaries that reference those files so T3 memory
  is not spent duplicating receipts in one aggregate string. Public MES status
  and receipt shapes remain complete. The OpenComputers sandbox does not expose
  `collectgarbage`; keep instrumentation bounded using ordinary supported APIs.

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
  recoil, then still; detection fired at 3.0 s (T4). On a blocked shortcut the
  controller marks the block ahead of the stop point as not clear for that job
  and reroutes. In flight the drone sleeps 0.1–1 s between checks depending on
  remaining distance; arrival and blocked rules are unchanged (T7).
- Item matching: name and damage required, label optional. Source-confirmed
  (`integration/minecraft/ConverterItemStack.scala:55-61`): a drone sees name,
  damage, maxDamage, size, maxSize, hasTag, label (plus enchantments/lore);
  raw NBT only if `allowItemStackNBTTags` (default false). `maxSize` gives the
  real stack size at pickup.
- The optional warehouse layer remembers reported per-item stack sizes.
  Combining separate logistics requests into one trip remains deferred.
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
- Node and storage names share one namespace (a name can't be both).
  `map.place(name)` → the node for a node or storage name; anywhere logistics
  takes a node (`go`, `plan`, `scan`, `test`) a storage name means its node.
- `map.link(a, b)` / `map.unlink(a, b)`: declares the straight flight between
  two nodes clear. Links are the only paths drones fly.
- `map.route(a, b, avoid)` → list of node names (A*, straight-line distance),
  or nil. `avoid` is an optional set of links to skip.
- `map.save()`, `map.load()`. Mapping knows nothing about items or drones.
- Straight-line shortcuts (T7): a link declares the drone body's whole straight
  flight clear, so every block it sweeps is known clear air. `map.clearLine`
  checks that a straight flight between any two points sweeps only known-clear
  blocks (3D grid walk, cost proportional to length; clear set rebuilt only
  after a map edit). Logistics plans with `map.theta` (any-angle A* using that
  check); `map.route` and `map.smooth` (A* plus a forward shortcut pass) remain.
  Theta* was chosen by measurement: equal or fewer stops and shorter flights
  than A* plus smoothing, at most 6.7 ms controller time per route. On the
  64-chest storage room a corner trip went from 22 stops to 4, 39 s to 11 s,
  and 316 to 102 energy. Drone body (source): 0.75 × 0.375 × 0.75.

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

### Warehouse (decided 2026-10-07)

An optional OpenOS library on the logistics computer: `require("warehouse")`.
It uses mapping and logistics and adds nothing to them, except that
`logistics.status` exposes each job's item and endpoints so any program can
see what a job moved where.

Storage names belong to the map. The warehouse keeps notes keyed by those
names; it never stores positions or sides.

- Membership is opt-in: `warehouse.add(storage, settings)`,
  `warehouse.remove(storage)`, `warehouse.members()`. Only members are stock:
  fetch takes from them, store puts into them. Settings (all optional):
  - `filter`: list of items the storage is for;
  - `priority`: number, higher first; unset counts as 0;
  - `inventory`: shared key for storages that are the same physical inventory
    (e.g. one chest reached from two nodes). Default: the storage name. The
    catalogue counts one entry per inventory, never twice.
- Groups: `warehouse.group(name, type, {role = storage, ...})`,
  `warehouse.ungroup(name)`, `warehouse.groups(type?)`. A group is one machine
  whose faces are storages (e.g. a furnace: input, fuel, output). `type` is an
  opaque label; the warehouse gives it no meaning. Group storages are not stock.
- Catalogue, per inventory: item counts, slot count, free slots, `maxSize` per
  item seen, time of last read. Counts are last-known, not guarantees. It is
  learned from:
  1. `warehouse.scan(storages?)`: explicit one-face read jobs, returning their
     job ids (one per distinct inventory); explicit names can be nonmembers;
  2. every finished logistics job touching a named storage (from `logistics.status`
     on the `logistics` event), whoever submitted it;
  3. shortfalls: a take that found less than expected sets that item's count
     in that storage to what the drone actually found.
  No periodic sweeps.
  Mutations estimate slot occupancy from the counted items and reported stack sizes;
  a full-face short sets the count to observed remaining stock (zero if exhausted,
  possibly nonzero for unmergeable NBT cargo), and a refused put marks it full until a later read. Only explicit reads survey inventories.
- Queries: `find(item)` → `{{storage, count}}`, `count(item)`,
  `contents(storage)`, `stackSize(item)`. Contents of observed nonmembers remain
  available; automatic stock counts and selection use distinct member inventories.
- `fetch(item, n, to, opts)` → logistics job id. Sources: largest count
  first, route distance breaking ties; one step-list job. Route-check only the
  inventories needed and equal-count candidates at the cut-off, with unreachable
  sources skipped. Store route-checks candidates in tier/priority order until full.
- `store(item, n, from, opts)` → logistics job id. Destination tiers: (1)
  members whose filter accepts the item, (2) members already holding it with
  room, (3) empty members. Within a tier, higher `priority` first. Members
  with a filter that rejects the item are never used.
- Items match by name and damage, label optional, as in logistics. Items that
  differ only in NBT are merged (OC hides NBT by default).
- Persistent: `/etc/warehouse.cfg` (members, groups), `/etc/warehouse.db`
  (catalogue), `/etc/warehouse.stacks` (limits learned from every listing and
  reported maxSize, at member and nonmember endpoints). Unknown limits report
  the item and requested/capacity numbers; reading the source teaches them.
  Memory proportional to inventories × item types.
- No reservations: two fetches may target the same items; the second gets
  the normal logistics partial/failed result. No keep-stocked policies yet.
- CLI `bin/warehouse.lua`: no arguments or `ui` opens the qmenu 1.1.0 UI.
  `lib/warehouse/view.lua` owns pure screen rows, actions, sorting, substring
  search, display-width/UTF-8 fitting and paging; `ui.lua` renders dirty qmenu
  options and waits on events. Tabs: Items, Storages, Machines, Jobs. Actions use
  public APIs, including `logistics.jobs(true)` for compact recent summaries and
  `logistics.status(id)` for full detail (`jobs()` also supports full enumeration).
  Logical selection survives live updates; messages temporarily replace the
  footer. Viewport and foreground/background (including palette mode) restore
  on normal exit, interruption and error.
- `event.push("warehouse", "changed")`: once per finished handler that changed
  catalogue knowledge, and after add/remove/group/ungroup configuration edits.
  The UI has no timed polling; its only timer expires footer messages.

## MES (manufacturing execution)

Decided with the user 2026-10-05 to 2026-10-08. Sources: the user's notes ("current thoughts on the
autocrafting system": craft-manager, cprocs, stockkeeper) and the design conversation. A
simplification of anything here is a proof of concept only and needs the user's permission to ship.

**Layers.** Map: where things are. Logistics: moving items. Warehouse: what is stored where,
reservations, machine and crafter groups. The user's `recipes` library: recipe storage and recipe
import. MES (`craftsystem/usr/lib/mes.lua`, CLI `usr/bin/mes.lua`): turns requests into work over
those layers; it reads recipes and never writes them. UI (`mes_ui`): over all of them.

**Requests and plans.** A request is one or more goal items (plans can be merged, e.g. a batch of
OpenComputers parts). The user's planner produces a dependency graph; the MES executes the graph,
not a flattened list. Several requests run at the same time, each with its own graph and
reservations.

**Execution is event-driven.** A step is ready when all its inputs are available to it. Completion
of drone jobs, cproc jobs and machine output are events; each one updates its step, and a finished
step triggers its dependants to check readiness and start. Replies are routed to the step that
issued the work. No straight-line walking and no global stage barrier.

**Crafting CPUs.** A crafting robot running `cproc` is a CPU with its own buffer chest (one buffer per
robot). Like an AE2 CPU it works one job at a time: one cproc job (a chain of robot tasks) per
robot. Ready robot steps from any request or branch go to whichever robot is free (or the one chosen
for the step). Drones deliver inputs, the MES confirms delivery, submits the job, relays cproc's
progress, and on completion collects the buffer.

**Machines.** A machine type is a pool of machine groups (one group = one machine: roles to storages,
with the slots each role's face exposes). A processing step uses any group of the type (split), one
group, or a chosen set. Machines are scheduled per load, not owned per step. Admission follows AE2
blocking mode: non-blocking types (a vanilla furnace) take loads while input room allows; blocking
types (multi-input, e.g. copper + tin) take a load only when their inputs are empty or hold the same
recipe. Output never gates admission; it is collected continuously and attributed to loads FIFO by
item. Fuel, batch and timing come from the type; output is read when due, not blindly polled.

**Hand-off and intermediates.** An output whose consuming step already has its robot or machine
(with room) goes there directly (furnace output to `cpu1` buffer). Otherwise it waits in an
**intermediate storage**: a warehouse storage the user marks `intermediate`. Intermediate storages
are not stock (hidden from the Stock tab, fetch, stockkeeper and planning); the MES records which
request owns which items in them (several requests may share one) and returns leftovers to stock
when a request ends, fails or is cancelled. Intermediates never go into ordinary stock. If no
intermediate space is available, the request **stalls** rather than failing: other steps continue,
the waiting step reports "intermediate space full", the MES pushes `("mes","stalled",request,
reason)` and the UI alerts on every tab; it resumes by itself when space frees. Planning warns when a
plan needs more intermediate space than exists.

**Live state.** Every crafter and machine has a state (idle, busy with which request/step/loads,
unknown). Unknown robots stay unavailable until confirmed idle.

**Failure.** On a failed step the MES re-reads the affected storages, reconciles its ledger with what
is actually there, re-plans the remaining work from that state, and retries up to a limit; then the
request fails and reports where its items are.

**Cancel.** Start no new work; in-flight drone, robot and machine work finishes its current unit;
buffer, machine and drone contents are returned to stock.

**Reboot.** Requests persist. On boot the MES reconciles with real storage contents and robot
receipts, then continues.

**Stockkeeper.** The user's stockkeeper rules (stock conditions linked to saved plans) submit MES
requests.

**Integration with the crafting system.** The user's system is the simple baseline (one robot,
transposer storage, one user at a time) and keeps working standalone; the MES is what that setup
grows into, as a second mode of the same libraries chosen by the controller's configuration.
Growing up loses nothing: saved plans, kits, tool rules, stockkeeper rules and recipes carry over
unchanged.

- Stock source: `craft_plans.inventory` reads the warehouse catalogue on an MES controller, so
  planning in `craft.lua`, `stockkeeper` checks and `count` see warehouse stock.
- Execution: `craft_plans.run` / `craft_kits.run` either run directly on one robot (today) or
  submit an MES request; `stockkeeper`, `craftplan`, `craftkit` and `craft.lua` use the MES through
  them without rewrites.
- UIs: `mes_ui` is the controller UI and opens the user's `craft_management_ui` for plans, kits,
  tools and stockkeeper rather than duplicating them. `inv.lua` stays the single-storage browser;
  on an MES controller the Stock tab covers it.
- `cproc` is unchanged; on an MES station it serves its buffer side and receives inputs by drone.

**Scaling.** The system grows by adding hardware as need grows: more drones, more crafting robots
(CPUs), more machine groups, more storages. None of these is a fixed quantity; the MES, warehouse and
logistics use whatever is registered, and throughput should rise as hardware is added. Tests use
realistic counts (6+ drones) unless the test is specifically about scarcity.

**Distribution.** Calls and events between layers carry plain data only (no functions, no live
shared tables), so any layer boundary can later become a network link and layers can move to their
own computers or servers. Logistics, warehouse and map stay together (logistics node); MES and the
recipe database/planner stay together (production node); UIs and robots may be anywhere.

**Component-call budget.** The controller's own component calls (GPU, modem, filesystem, transposer)
are bounded per tick and indirect calls cost a tick each. Event bursts are coalesced: UI redraws are
rate-limited and partial, persistence is written on a short timer, and nothing polls. Native runs
measure controller calls per component per tick and per second (mean, peak, budget exhaustion).

**Fleet board.** A Fleet tab shows drones and robot CPUs as a departure board, one row per unit:
status (colour-coded), job and request, current task, from and to (last known place, no live
tracking), progress, and last update time; plus each fleet's busy share over a recent window and a
bottleneck line ("drones 83% busy; 3 steps waiting for a drone") that says what to add next. Actions:
take a unit out of service and back (it finishes current work, then gets none; used to change
hardware while running), recall a drone home after its job, and re-check a unit (re-query cproc,
ping a drone; clears UNKNOWN). Logistics and the MES keep the needed data: per-unit task,
destination, last update and a rolling utilization record; cproc status includes robot energy.

**Hardware.** The controller is a tier-3 computer with a tier-3 screen; UI designed at 160x50.

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
