# MES consolidation

A GPT agent reviewed the crafting system and drone logistics for places where the MES does one job two ways. Claude then reviewed that work against the code and the user's intent and rejected most of it. This file keeps only what survived, plus the rejections, so they are not raised again.

## Workspaces

Both repositories have a `mes-consolidation` branch. Nothing is committed.

| Repository | Worktree | Base |
|---|---|---|
| Accelerator / native harness | `oc-robot-accelerator/.worktrees/mes-consolidation` | `4407205` |
| OC applications | `OC-Utilities/.worktrees/mes-consolidation` | `a951b44` |

`craftsystem/` and `drone-logistics/` in the accelerator worktree are links into the OC-Utilities worktree. The uncommitted changes to `mes.lua`, `mes_state.lua`, `warehouse.lua`, their tests and the shortfall fixture are inherited from the earlier work, not part of this pass. The inherited patches are under each repository's `.git/worktrees/mes-consolidation/`.

## Real problems

1. **Saving plans is broken.** The MES plan screen saves through `craft_plans.save`, which runs the robot-only check: a plan with a machine step is refused with "Machine processing is not supported by this robot executor" (`mes_ui/plan.lua:89`, `craft_plan.lua:161`). `prepare` also drops `stages`, so the robot chosen for each step is lost (`craft_plans.lua:31–67`).
2. **A machine type can't be created from its screen.** The form never asks for role slots or blocking (`mes_ui/flows.lua:103–148`); the backend requires both (`mes_config.lua:73,91`, `mes.lua:461`).
3. **The ore choice is dropped.** The recipe editor sets `ore` on the input (`recipe_edit.lua:156`), but `recipes/management.lua:136–175` saves only the exact item, for crafting and processing.
4. **Robot jobs over five minutes are marked failed.** `craft_client` had a default 300 s total deadline that progress did not renew. The MES path inherited it, because rc starts the MES with no options. Fixed, see below.
5. **Stockkeeper.** It checks on a repeating timer (`stockkeeper.lua:74`), and reads stock from side 0 when no side is set (`craft_plans.lua:177`). Its rules do not come back after a restart unless `stockkeeper start` is run.
6. **Two Run paths.** Saved plans and kits run from the Manage tab go straight to a robot through `craft_client.runDetailed` (`craft_plans.lua:268`, `craft_management_ui.lua:173,235,347`), bypassing the warehouse and drones. `mes.run` already accepts a saved plan by name (`mes.lua:593`).

## Rejected

- **"A failed save can lose the old file."** It needs a write to fail midway, which nobody observed. The temporary-file saving the agent added was reverted, and its test removed.
- **"Persistence is duplicated."** Several small save functions; nothing a player sees. `store.lua` is agent-written (`960743f`), not a user library.
- **Robot and drone boot retries** (`cproc.lua:71–80`, `drone/loader.lua:25–30`). The user allowed them explicitly.
- **Idle drones should send a heartbeat.** No case has shown the MES needs one.
- **dataio.lua, unused inventory/oredict functions, overlapping old screens and build commands.** Housekeeping, not problems. The old screens only matter through problem 6.
- **Library line endings.** The pinned-byte test fails on this branch, but OC does not care about line endings and neither does the user.
- **The agent's sections defending "complexity with a demonstrated purpose" and drone navigation.** Nobody attacked either.

## Changes made

- **Five-minute limit removed** (`craft_client.lua`, `usr/bin/craft.lua`). An explicitly supplied deadline still applies; idle detection and receipt reconciliation are unchanged.
- **gatenet removed** from the MES: `usr/lib/gatenet.lua` deleted, and its stale `package.loaded` line removed from `usr/bin/craft.lua`. OC-Utilities' top-level `bin/craft.lua` and `bin/gnt1.lua` are a separate, older app and still use it.
- **Robot disks carry only the robot program.** `examples/mes/build_fixtures.py` gives robots `cproc.lua` and the twelve libraries it requires; the server gets the full tree. `test_mes_fixtures.py` checks that closure. This fixed no observed problem; it simply matches what a player would put on a robot disk.
- **Plans save with their machine steps and stage choices** (problem 1). `craft_plan.validate(plan,{machines=true})` admits machine tasks for saved MES plans; robots still refuse them. `craft_plans.prepare` keeps `isProcessing`, `machineType`, input quantities, byproducts and each stage's crafter/groups.
- **Machine-type form asks for Slots and Blocking** (problem 2, `mes_ui/flows.lua` `F.editType`, by mes-ui-coder). Nothing pre-filled; Save refuses until every role has slots and blocking is chosen. Checked in the ui-lab; the form's output matches `mes_config.lua:73,89–97` by reading, not by running it.
- **Ore choice saved** (problem 3, `recipes/management.lua` `M.save`) as `ore:<name>` for crafting and processing inputs.
- **One Run path** (problems 5, 6). `craft_plans.run` submits through `mes.run` and waits with `mes.wait`; `craft_client` is no longer used by plans, kits or stock rules. Stock is `mes.inventory()`, the warehouse minus what runs have claimed; a chest is read only when a caller names its side. Earlier kit outputs stay reserved: an input they share must come from other stock, the same rule the robot applies (`craft_executor.lua:89`).
- **Stock rules come back with the MES**: `etc/rc.d/mes.lua` starts `stockkeeper` after `mes`.
- **Temporary-file saving reverted** in `craft_store.lua`, `craft_plans.lua`, `craft_tools.lua`, `recipes/init.lua` and `test_ui.py`.
- **Merged kits accept machine plans with their actual input quantities.** `craft_plan.validateFlow` admits machines only when explicitly requested by MES plan/kit editing; robot validation still refuses them. Conservation accounts for quantity per operation. `craft_plans.prepare` captures those quantities from the blueprint before a merge renames its nodes, so execution cannot silently fall back to one input per operation. Machine tasks cannot claim reusable robot-tool slots.
- **Stockkeeper follows warehouse changes, not a clock** (`stockkeeper.lua:74–106`). Enabling/restoring a rule queues one initial check; stock pushes coalesce while a batch is running. Checks remain serialized. A failed batch does not retry from its own stock movements; unknown outcomes still require explicit resume. If a notification arrives inside the MES pump, the check waits for its ready signal (`mes_service.lua:34,194`). The interval prompt and flag were removed; old saved interval fields are discarded. Net replenishment also accounts for machine input quantities (`stockkeeper.lua:229`).
- **Equipment choices survive plan composition.** `craft_plans.lua:86` captures stage task identities and places selections on tasks/blueprint nodes. `craft_blueprint.lua:15,35,231` preserves them through recalculation and merging. Shared recipes with incompatible crafters or disjoint machine choices fail with an explanation; overlapping machine sets use their intersection. Saved accounting keeps independent tasks and choices. Robot chains with different selected crafters remain separate execution stages. Legacy files lacking task identities remain directly runnable but require fresh selection before reshaping, rather than silently losing equipment choices.
- **Unused per-plan connection settings are rejected.** `craft_plans.checkOptions` applies to saved-plan/kit/stock-rule execution and commands. The legacy craft menu no longer manufactures or forwards obsolete timeout defaults. Old saved stock-rule connection fields are discarded on load. MES service policy is passed to robot jobs (`mes_service.lua:75`). Direct robot receipt queries retain connection options because they actually use them; no second configuration system was added.
- **Order controls use the MES ID.** Plans and Kits menus offer progress and an explicit, confirmed Stop for the whole order (`craft_management_ui.lua:124`). `mes runs`, `mes status ID` and `mes stop ID` provide the same control at the prompt (`usr/bin/mes.lua:22`). Status includes materials left outside stock. Robot receipts remain diagnostics; local-chest recipe import is unchanged.
- **Leaving a view does not stop manufacturing.** `mes_service.wait` forwards matching pushed order snapshots (`mes_service.lua:350`). If the foreground wait is interrupted, saved-plan execution reports the actual MES status, not a false failure (`craft_plans.lua:345`). Stockkeeper pauses on a still-running result, saves its order ID, and refuses resume until that order is terminal (`stockkeeper.lua:162`). It cannot automatically submit a duplicate batch from subsequent stock pushes.
- **MES persistence survives temporary commands.** The native Stop case exposed a real file-ownership bug: log compaction reopened the state file inside the command process; command exit closed it, preventing later completion writes. `mes_persist.lua:241` now retains handles opened by its persistence operations in OpenOS's root process, using `process.removeHandle/addHandle`. Existing command-owned handles are left alone. The shared `store` library was not changed.

## Tests

Latest focused run: **648 tests and 361 subtests passed**:

```sh
python -m pytest -q craftsystem/tests test_mes_fixtures.py test_mes_acceptance_gate.py test_mes_ocparts_plan.py test_mes_service_cli.py test_mes_restart.py test_mes_timing.py --tb=short
```

Plan, kit and stock-rule tests use a fake MES (`FAKE_MES` in `tests/test_database.py`) whose runs are carried out by the robot fake. The new mixed-kit test in `test_mes_graph.py` instead runs `craft_kits.run` through the real MES scheduler with simulated hardware: four ore are consumed for two machine outputs, plus a separate robot output, in one MES run. Additional tests reject invalid machine quantities, reject insufficient merged inputs, retain robot-only validation and exercise machine-plan editing.

Removed or rewritten because they asserted the old robot-direct path: `test_client.py` plan-hook/subscription test (deleted); client timeout/cleanup options in `test_plans.py`; the `external_reserved` payload fields in `test_plans.py`, `test_kits.py`, `test_captured_executor.py`.

**Native saved mixed-kit case passed.** `run_mes_scenarios.py --cases merged-kit --parallel 1` built an isolated world from current sources, saved a live brick plan and a pinned torch plan in a kit, then executed it through the MES. One completed run produced 16 brick blocks and 16 torches. All 78 trips were inspected: 64 initial stock-wall scans and 14 production trips; no duplicate dispatch, shortfall, refused/returned cargo or unrelated housekeeping trips. Each requested transfer quantity moved. Capture coverage was complete. Wall time was 62.063 seconds.

Evidence: `C:/or/mes-consolidation-merged-kit-20261017-0446/merged-kit-coordinated/`, including `trip-review.md`, `trips.json`, `acceptance.json` and the staged source hashes. The case used cpu1 for robot work; it does not prove parallel crafter use, restart recovery, stockkeeper triggers or rendered UI behavior.

**Native stockkeeper case passed:** one saved eight-block plan replenished sixteen brick blocks in two serialized MES runs, driven by stock receipts. All 76 trips were checked: 64 initial catalogue reads and 12 production trips, exact quantities, no repeated dispatch or leftover drone cargo. Evidence: `C:/or/mes-consolidation-stockkeeper-20261017-0456/stockkeeper-coordinated/`. Wall time: 52 seconds. The rule was disabled at target; idle-at-target behavior and failure/resume paths were tested in Lua. Restart recovery was not tested natively.

Stockkeeper timer-specific tests in `test_stockkeeper.py`, `test_stockkeeper_commands.py` and `test_stockkeeper_ui.py` now assert pushed-stock behavior instead of repeated timer callbacks. Added coverage for coalescing, nested MES-pump notifications, reaching the target, replacing a rule during a failed check, stock changes during a skip hook, and machine quantities in net replenishment. The final rule-replacement fix was tested after the native run; it does not affect the native success path.

**Native selected-equipment kit passed:** saved brick and torch plans were combined with refreshed accounting. The brick stages used furnaceA/cpu2; charcoal used furnaceB and stick/torch stages used cpu1. One run produced sixteen brick blocks and sixteen torches. All 74 trips were checked: 64 initial catalogue reads and 10 production trips, exact quantities, no duplicate dispatch or retained cargo. Evidence: `C:/or/mes-consolidation-selected-kit-20261017-0520/selected-kit-coordinated/`. Wall time: 62.672 seconds. Conflict handling, malformed/legacy task identities and custom service policy are Lua coverage. Final validation and policy-forwarding changes were made after the native run; staged source hashes identify its tested version.

Additional regressions cover equipment choices through saved/refreshed kit modes, stock-policy edits, shared-recipe conflicts, overlapping machine sets, robot-chain separation, obsolete command/API options, stock-rule migration, and actual MES service policy forwarding. The graph hardware fake now copies its options before annotating them; it previously mutated shared policy and misattributed concurrent robot results.

**Native order controls passed:** real `mes runs/status/stop` commands stopped a queued stick order while another order used its selected robot. The other order produced sixteen planks; both outcomes were persisted. All 66 trips were checked: 64 distinct catalogue reads, four logs delivered to cpu1, then sixteen planks returned to stock. No duplicate dispatch, retries, refused/returned cargo or leftover drone/robot inventory. Evidence: `C:/or/mes-consolidation-order-control-fixed-20261017-0605/order-control-coordinated/`, including `trip-review.md`. Wall time: 52.578 seconds. The preceding failed run at `C:/or/mes-consolidation-order-control-20261017-0600/` retains the missing-completion-receipt evidence; it was not accepted.

Additional Lua coverage checks matching-order progress signals, copied snapshots, observer errors, leaving a view without cancellation, explicit Stop, settling an in-flight delivery with its remaining material reported, interrupted separate-kit execution, paused stock rules across reload, and state-log compaction followed by command exit. No old behavior tests were deleted for this order-control change.

## Verification limits

- The full root test suite was not run; the known library byte-provenance/line-ending mismatch was not changed.
- Native restart recovery and rendered UI behavior were not re-proved in these cases.
- `plans.query` remains a low-level robot receipt diagnostic exposed by the legacy management screen and `craftplan status`. MES run inspection uses `mes.status(runId)`; these are different objects, not duplicate execution paths.
- The protected production `mes_ui` run screen is unchanged; the new controls are in the legacy Plans/Kits menus and CLI.
- Separate kits still submit components from the foreground caller. Interrupting that wait leaves the current order running but does not submit later components; the result says so. Merged kits are one service-owned order. No background separate-kit queue was added.
- Native Stop coverage is for an order waiting for its selected robot. In-flight delivery settlement is Lua coverage, not a claim that native machine cancellation was proved.
