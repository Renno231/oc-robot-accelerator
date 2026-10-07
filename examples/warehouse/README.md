# Native warehouse acceptance

Run these controller programs in the pinned Minecraft 1.12.2 / Forge
14.23.5.2860 / OpenComputers 1.8.9a runtime. They use real inventories and drones.

## Furnace cycle

`furnace-cycle/scenario.json` contains the 64-chest warehouse, two furnaces and
two drones. Generate its deployment copies and finite-power world with:

```sh
python examples/warehouse/build_fixtures.py
python runner.py run examples/warehouse/furnace-cycle/scenario.json --installation PATH --jobs-root PATH
```

`furnace-cycle.lua` drives public warehouse/logistics APIs. Each furnace gets
64 clay and eight coal. Clay and fuel jobs run concurrently on the two drones;
the second furnace's clay fetch is submitted after the first completes, so
selection uses the corrected catalogue. Automatic fetch/store selection uses
last-known stock/capacity and provides no pending-job reservations. The separate
`concurrent-probe` matrix case demonstrates overlapping source selection.

The test sleeps using `TileEntityFurnace.getCookTime` (200 ticks/item) and
`getItemBurnTime` (1600 ticks/coal), reads output to learn the brick stack limit,
then calls `warehouse.store` with a bounded `wait`. Store destination selection
is automatic: the filtered priority-5 chest has one free stack, then the empty
priority-1 chest receives the remainder. The controller remains event-driven.

Run the complete 128/100/native-shortfall baseline/coordinated matrix and the
two-ram6 deployment-memory case with:

```sh
python run_furnace_cycles.py --installation PATH --jobs-root PATH
python summarize_furnace_cycles.py --jobs-root PATH --output PATH
```

The shortfall fixture removes 20 clay through the fixture-scoped native player
action seam after scanning. It records the partial fetch, corrected catalogue
and 108-brick completion. All generated deployments copy canonical libraries
unchanged; the controller test owns the cycle and the sleep.

The fixture includes a finite charger bank sized for two complete scans and
the smelting interval; it never tops up running machines. Optional
`cycle-diagnostics.lua` records public job/fleet state and bounds each test
wait at 600 seconds for acceptance troubleshooting, without changing libraries.

`deployment-memory.lua` samples the finished controller with a non-recording
160x50 GPU stub, traversing all tabs and Item/Storage/Machine/Job details. The
driver is compiled before the no-UI sample. Its stub owns no framebuffer.
`profile-ui-memory.lua` is a separate public-API allocation diagnostic, not a
deployment baseline. The full UI can approach the one-ram6 heap limit during
render bursts; two ram6 sticks are recommended for this 64-member controller.

Native measurements include per-tick positions, targets, velocity and consumed
energy, plus final chest inventories and controller acceptance records.
Output-face stationary time includes inventory actions/callback latency and is
reported separately from smelting wait and flying time.
