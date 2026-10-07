# Named drone logistics

Deploy the canonical `lib/`, `bin/`, and `drone/` files from this directory.
Nodes use integer block coordinates; a link declares the body's entire straight
flight between its endpoints clear. Mapping is a declaration, not a terrain sensor.

## Geometry and planning

`map.route(from, to, avoid)` remains graph A*. Additional mapping APIs:

- `map.buildClear(half)` configures the link-sweep box and returns `map.clear`.
  `half` is a scalar cube half-size or `{x, y, z, offsetY?}`. The latter shifts
  the box center vertically relative to the block center.
- `map.blockKey(x, y, z)` returns the numeric key of an in-bounds integer voxel.
  Keys belong to the current map geometry. Sparse numeric strides require the
  bounding-volume product to be less than `2^53`; oversized maps fail explicitly.
- `map.clearLine(p, q, half, avoid)` checks the query box against declared clear
  voxels. Points are node names or `{x, y, z}` block-coordinate records. Closed
  face/edge/corner contact counts as touching, with a conservative rounding margin.
  A larger query box does not enlarge the configured clear set. `avoid.blocks`
  holds numeric voxel keys that are unavailable for this query.
- `map.smooth(route, half, avoid)` performs a single forward anchor pass over
  graph-A* node names, emitting the last visible node when visibility fails.
- `map.theta(from, to, half, avoid)` expands graph neighbours and inherits the
  current node's parent whenever the parent's straight leg is clear.

The clear set is built lazily after a geometry edit (`add`, `remove`, `link`,
`unlink`, or `load`). Checks traverse a widened 3D grid with scalar slab tests,
numeric set lookups, and no voxel-table allocation. Storage is proportional to
clear voxels. Saving and storage-face naming do not change flight geometry.

Logistics dispatches **Theta\*** waypoints, planned per trip (a few ms on the
64-chest room, so nothing is cached).
`logistics.plan(from, to)` previews the same planner and returns fresh point
records. The mapping A* and smoothing APIs remain available independently.

## Native body and flight contract

At OC revision `8ca336fbeb92d2a29f86f9a658bb9d6bd6f07dbb`,
`common/entity/Drone.scala:80` sets width `12/16` and height `6/16`:
**0.75 × 0.375 × 0.75 blocks**. Forge **1.12.2-14.23.5.2860**
`net.minecraft.entity.Entity.setPosition` anchors its bounding box at `posY`,
with horizontal half-width and vertical extent `posY .. posY + height`.
Logistics therefore supplies `{x=.375, y=.1875, z=.375, offsetY=.1875}`.

The arrival rule is offset **< 0.02** and velocity **< 0.02**. The stall rule is
three seconds without an offset improvement exceeding 0.1. Flight checks sleep
0.1–1 seconds: they reserve braking/settling distance and use the native speed
bound and acceleration. The pinned OC entity source (`:74–78,430–457`) has
axis cap `.4` blocks/tick, acceleration `.1` blocks/tick², and drag `.8`.
`server/component/Drone.scala:102–110` exposes max velocity `8` and acceleration
`2`. Polling converts acceleration back to `40` blocks/s². From a confirmed hover,
the source recurrence `|v_next| <= .8*(|v|+.1)` bounds reported scalar velocity by
`8` blocks/s; axis clipping reduces that bound. The wait uses the already-read
offset (initially the declared leg length) and adds no polling callbacks.
These are bounds, not an arrival-time promise.

On a blocked leg the controller estimates the stop point from its target and
reported offset, marks the voxel ahead unavailable for that job, skips declared
links touching it, and plans another route. The drone first retraces to its last
confirmed waypoint. `blockedReports[].leg` identifies the attempted smoothed
leg; `link` and `links` identify affected declared links. Saved geometry is kept
intact. Numeric avoid keys are refreshed if the map is edited during that job.

## Native fixtures

`examples/logistics/storage-room` contains 64 inward-facing chests, a 1-wide
hallway, 32 hover nodes, neighbour links, and two external chargers. It exercises
corner and distant transfers, simultaneous drones, all storage faces, and a
native chest placement after mapping. Its player-action seam is scoped to this
scenario ID and the controller's `/home/storage-room-place-chest` marker.
`examples/logistics/obstacle-room` adds a grid surrounding a real stone pillar.

Regenerate fixture copies with:

```sh
python build_storage_room.py
python sync_logistics_fixtures.py
python examples/mapping/build_fixtures.py
```

`run_route_measurements.py` prepares immutable before/smoothing/Theta* variants.
Controller planning uses native OC `os.clock()` (`server/machine/luac/OSAPI.scala:
15–20`, backed by `Machine.cpuTime`). Flight instrumentation observes existing
checks and reuses the terminal report. A frozen `route-metrics-enabled` program
marker enables a bounded compact per-tick measurement stream independent of the
replay's observation prefix. Native measurements record wall time,
uptime, positions and successful machine/radio energy debits, including sleeping
costs and excluding recharge (`Machine.scala:526–540`,
`server/component/WirelessNetworkCard.scala:87–95`, at the pinned revision).

## Warehouse UI

Run `warehouse` (no arguments) or `warehouse ui` with
qmenu 1.1.0 installed as `/lib/qmenu.lua`. A GPU resolution of at least 50×16
is required. Left/Right switches Items, Storages, Machines and Jobs; Up/Down
selects, Enter acts, PageUp/PageDown pages, `/` searches (empty clears), and
Backspace or `q` goes back (`q` on a tab exits). Actions and errors appear in
the footer rather than modal messages. Inventory/job changes update live.

Items offers fetch with a destination, quantity (one observed stack by default,
or `all`) and confirmation. Storages offers scans, store-from, membership,
filter, priority and shared-inventory settings. Machines edits opaque typed
groups and roles (it does not process items); Jobs shows status and permits
only queued cancellations. All actions call the same public warehouse/logistics
APIs as the CLI. Reading any source learns its real stack limit; unknown limits
fail explicitly rather than assuming 64. Nonmembers may be scanned and viewed,
but never enter automatic stock selection. Configuration, catalogue and learned
limits persist in `/etc/warehouse.cfg`, `.db`, and `.stacks` respectively.
