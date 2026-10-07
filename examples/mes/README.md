# MES acceptance fixtures

Generate canonical copies: `python examples/mes/build_fixtures.py`.
Focused contracts: `python -B -m unittest test_mes_fixtures`.

The five coordinated worlds preserve the T10 stock room, add two furnaces,
two drones and a stationary crafting CPU. Every scenario sets
`execution.infiniteEnergy=true`; power is not under test. The robot installs
unchanged craftsystem sources and executes `cproc --side=3` facing its buffer.
The controller compiles the four required crafting recipes using the original
`liblz16` writer and `recipes.build`, and registers furnace recipes through the
original processing API. No UI is started.

| Case | Acceptance |
| --- | --- |
| torches16 | robot → machine → robot; 16 torches, logs 3, coal 14, planks 2, sticks 0 |
| bricks16 | 64 clay split 32/32, then 16 brick blocks; coal 8 |
| specific-group | all 64 clay through furnaceA; furnaceB untouched |
| shortfall | remove 16 clay after planning; failed machine stage, explicit remaining locations, no blocks |
| concurrent-fetch | submit two 64-item fetches before waiting; both complete from 128 stock |

The user's planner orders the torch's independent branches charcoal first.
The fixture records this raw order, then legally interleaves the planks/sticks
branch before charcoal to exercise the requested three-stage topology without
changing planner code or arithmetic. The plan is serialized and passed as a
saved `.plan` path to `mes.run`.

Lua acceptance checks read back stock, station and furnace inventories, verify
robot receipts, exact machine splits and empty drone inventories. Furnace face
reads expose the entire furnace inventory: only metadata-0 fuel coal may remain
when asserting processing input/output empty. Failures do not drain machines.
Results are written to `/home/warehouse-results.lua` and `/home/mes-results.lua`
with stage outcomes, receipts, raw/executed task order, moved items, trips and
game seconds. Native runner wall time comes from its job/result metadata.

For the main-case native baseline, call the generator's
`build(target, 'torches16', 'baseline')`. Native runs and full regression suites
are coordinated by the parent; Python fixture tests are not native evidence.
