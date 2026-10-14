# Craft system v3

OpenComputers/OpenOS recipe planning and verified execution on one crafting robot.

## Requirements and installation

- Select **Lua 5.3** architecture. `lzss.lua` uses bitwise operators and `string.pack`/`string.unpack`; Lua 5.2 is unsupported.
- Interactive client: GPU/screen, transposer, modem, OpenOS, and the external `qmenu` library (not included). An 80x25 or larger screen is recommended. `craft.lua` requires `qmenu`, including its argument mode.
- Headless libraries and purpose binaries need no GPU or `qmenu`. Execution needs a modem and ready processor. New calculations, refreshed accounting, and default stock checks also need a transposer/storage view; saved execution without a stock condition does not.
- Processor: robot, modem, inventory-controller upgrade, crafting upgrade, and adequate inventory capacity.
- Deploy **all** of this project's `usr/bin` and `usr/lib` together into their corresponding OpenOS directories, including `stockkeeper.lua`, the `craft_*` modules and `recipes/build.lua`. Use the v3 inventory/recipe modules rather than mixing older copies. The robot receives captured tool rules and needs no user registry or recipe lookup to execute.
- Put compressed recipe archives in `/usr/lib/recipes/` and `oredict.dblz` in `/usr/lib/oredict/`.
- The client's source inventory and the robot's source/return inventory must access the same storage. Default client storage side: down (0); output side: south (3). Default robot storage side: front (3).
- Port 5990 is reserved for this service. Clients discover `craftServer` through Gatenet. The protocol has no authentication; use a trusted local network.

## Commands

```text
cproc --side=3
craft mc:planks 64 --storage-side=0 --output-side=3
craft mc:planks 64 --connect-timeout=10 --idle-timeout=60 --job-timeout=300
craft
crafttools --interactive
crafttools set mod:hammer --durability=100 --wear=1
craftplan create "Iron gears" mod:gear 16
craftplan run "Iron gears" --accounting=refresh
craftplan preview "Iron gears"
craftplan edit "Iron gears" --node=mod:part --stock=false
craftplan status ROBOT_ADDRESS JOB_ID
craftkit create "T3 computer" "T3 Case" "T3 CPU" "T3 Memory" --binding=live
craftkit add "T3 computer" "T3 GPU" --binding=pinned
craftkit set "T3 computer" --mode=merged --accounting=refresh
craftkit run "T3 computer" --mode=separate --accounting=saved
stockkeeper --interactive
stockkeeper create "Keep gears" --plan="Iron gears" --item=mod:gear --quantity=64 --interval=30
stockkeeper enable "Keep gears"
stockkeeper start
```

`craft` with no arguments opens the menu. `-q` enables interactive planning with arguments. `-f` bypasses the initial prompt to export an already-stocked target. Quantities are rounded up to whole items. The planner normally uses stocked dependencies but produces the requested target anew unless you choose the initial export/skip option.

Timeouts are separate:
- discovery: 15 seconds;
- connection handshake: 10 seconds by default;
- inactivity: 60 seconds by default, renewed by server updates;
- total job deadline: 300 seconds by default. `--job-timeout=0` disables the absolute deadline; the inactivity timeout remains active.

Press `q` to cancel a planning selection. Ctrl+C ends the client connection; the server checks cancellation at execution boundaries and attempts to return held items. Cancellation is not transactional rollback: already-crafted intermediates remain crafted. A timeout/disconnect may leave the final outcome unknown if its completion packet was lost; check storage before retrying.

`craft` includes Tools, Craft Plans, Craft Kits, and Stockkeeper. These open the independently callable `crafttools`, `craftplan`, `craftkit`, and `stockkeeper` interactive flows through `shell.execute()` and restore the parent menu afterward. Each binary also accepts `--interactive` directly.

Tools supports manual item entry or storage selection, profile editing, and removal. Craft Plans supports creation, save-only/save-and-run/run-without-saving, paged explanations, captured-choice editing with reviewed save, robot receipt queries, copying, deletion, and saved/refreshed execution. Its recipe chooser offers an explicit external-material leaf; stock policy can force manufacture of an intermediate. Craft Kits supports ordered entries, visible live/pinned bindings, replacement/rebinding/reordering, default edits, and one-run execution/accounting overrides.

`list`, `show LABEL`, `copy LABEL NEWLABEL`, and `remove LABEL` are available for plans/kits. Kit editing also offers `add LABEL PLAN --binding=live|pinned`, `bind LABEL INDEX live|pinned [--plan=LABEL]`, and `remove-entry LABEL INDEX`. Removing the last entry is rejected. `crafttools` offers `list`, `set`, and `remove`. Use `--help` for command syntax.

Headless plan creation chooses the first recipe and default concrete substitution. `--leaf=mod:raw,mod:other` sets explicit external leaves; `--make=mod:part` forces manufacture rather than stock use. Use the interactive chooser or the calculation callback for other choices. Label writes replace the corresponding file; commands do not prompt.

Purpose binaries return numeric codes: **0** completed/skipped or management success, **1** crafting failure, **2** command/preparation error, **3** unknown execution. OpenOS `shell.execute()` reports process success rather than the structured crafting result; call the libraries for detailed outcomes. Closing an interactive menu successfully is not evidence that a craft completed.

## Saved plans and automation

`craft_plans` is the shared Lua library for UI and unattended callers. Each label has its own `/usr/craftplans/<label>.plan` file. New plans retain both their **chosen blueprint** and their **calculated execution result**. The label is its stable lookup name; spaces are allowed, but blank labels, slashes, control characters, `.`/`..`, and labels over 120 bytes are rejected. Saving an existing label replaces only that file. Writes are direct, not atomic; a failed/interrupted overwrite may require resaving it.

`list()` uses `filesystem.list()` to enumerate filename stems. **It never opens, decodes or stats individual plan files**, and there is no manifest/index to read. Invalid contents are reported only when that particular plan is loaded/run. Old finalized `.plan` files remain readable.

| API | Return / behavior |
| --- | --- |
| `plans.list()` | Sorted label array, or `nil, error`. Directory enumeration only. |
| `plans.save(label, finalizedPlan)` | `true`, or `nil, error`. Writes sanitized blueprint/execution data, not coroutines/caches/functions. |
| `plans.load(label)` | Validated fixed plan, or `nil, error`. Opens only the selected file. |
| `plans.run(label, options)` | Blocking, prompt-free execution; returns a result table. Reads only that plan file. |
| `plans.run(finalizedPlan, options)` | Same execution directly from a table, with no plan-file I/O. |
| `plans.refresh(labelOrPlan, options)` | New calculated plan within captured choices, or `nil, error`; does not overwrite the file. |
| `plans.prepare(plan)` / `plans.payload(plan)` | Sanitized copies; payload excludes the full blueprint. |
| `plans.remove(label)` | Removes only that plan file. |
| `plans.preview(labelOrPlan)` | Structured explanation of the recorded snapshot; no recalculation or recipe lookup. |
| `plans.edit(labelOrPlan, change, options, selectChoice)` | Recalculated candidate and diff lines, or `nil, error`; never saves or executes. |
| `plans.query(robotAddress, jobId, options)` | Queries that robot's RAM receipt; never submits a craft. |

`require("craft_commands").calculatePlan(item, quantity, options, selectChoice)` returns a finalized plan without saving. `createPlan(label, item, quantity, options, selectChoice)` also saves it. The optional callback receives the planner's selection yield and returns the chosen recipe/material/policy. A recipe result of `false` creates an external leaf; `nil` chooses the default. Throwing from the callback cancels without saving/submitting.

After creating a plan through the UI, an unattended OpenOS Lua caller can run it:

```lua
local plans = require("craft_plans")
local result = plans.run("Iron gears", {
    stockAtLeast = 64, -- omit this to always attempt the saved batch
    storageSide = 0,  -- stock-check inventory; robot side is configured by cproc
    accounting = "saved", -- or "refresh", constrained to the saved blueprint
    onSuccess = function(r) print("Batch completed: " .. r.quantity) end,
    onFailure = function(r) print(r.status .. ": " .. r.message) end,
    onSkip = function(r) print("Enough stock: " .. r.stockCount) end,
})
if result.hookError then print("Hook failed: " .. result.hookError) end
if result.cleanupError then print("Client cleanup failed: " .. result.cleanupError) end
```

Use `plans.save("Another label", plan)` to save a finalized calculation result or duplicate a loaded plan; `plans.list()` discovers available labels without loading them.

- `stockAtLeast` is a finite nonnegative integer. Stock at/above it skips the entire job; below it executes the **whole requested batch**, even if this overshoots the threshold. There is no deficit scaling, export, or automatic retry. Saved accounting without a threshold has no client stock read/transposer requirement.
- Stock checks create a fresh inventory snapshot using `options.transposer` (default `component.transposer`) and `storageSide` (default down/0). Alternatively supply `countStock(itemID)` returning a finite nonnegative integer, e.g. from your stock keeper. A failed check fails the attempt before network submission. The check is a condition, not a stock reservation; other actors can change inventory afterward.
- `accounting="saved"` (default) replays recorded tasks/withdrawals. Missing stocked intermediates fail safely. `accounting="refresh"` recalculates stock, amounts, wear and replacement manufacture inside captured choices, including permitted routes for previously stocked intermediates. It does not consult current recipes/ore dictionaries, change material substitutions, or overwrite the saved plan. Missing allowed terminal materials still fail. Legacy execution-only files remain runnable, but cannot refresh until choices are explicitly captured.
- Results have `status` (`complete`, `failed`, `skipped`, or `unknown`), `success` (true only for verified completion), and `message`. Named runs include `name`/`label`; valid plans include `item`/`quantity` and the full canonical `outputs` map; checked runs include `stockCount`/`stockAtLeast`.
- `unknown` means a craft submission was attempted but no terminal outcome was confirmed, e.g. timeout/disconnect/cancellation. `onFailure` receives both `failed` and `unknown`; check storage before retrying. Even a confirmed failure may have crafted intermediates/partial output. `mayHaveExecuted` conservatively records submission attempts, not delivery proof.
- `onSuccess`, `onFailure`, and `onSkip` are caller-provided Lua functions, not serialized hooks or saved commands. Exactly one applicable hook is called per returned attempt, after client cleanup is attempted. It receives a result copy; mutating it cannot change the returned job status. Exceptions are recorded as `hookError`, never retried or converted into another crafting attempt. These hooks are not durable across process crashes.
- A verified `COMPLETE` remains success even if later local cleanup fails; that separate error appears in `cleanupError`. Do not recraft a confirmed completed batch because its logging/hook/cleanup failed.
- Network options (`connectTimeout`, `idleTimeout`, `jobTimeout`, `discoveryTimeout`, `service`, `port`, `onMessage`, and `shouldContinue`) pass through to `craft_client`. Output remains in source/return storage. Actual execution still requires a modem and a ready crafting robot.

## Inventory handoff, preview and editing

The repository's `inv.lua` keeps its `shell.execute()` composition. Shift+C reads
a positive whole quantity for the selected item, including its damage variant;
C preserves typed item/quantity/`-q` input. Detected storage/output sides are
forwarded to `craft`. On return, storage and output snapshots are refreshed and
the inventory menu is redrawn even after an error or a partial/unknown attempt.

`craft_handoff` is a shared, short-lived Lua module: `begin()` allocates a ticket,
`report(id, result)` records a copied outcome, `finish(id)` consumes the summary,
and `release(id)` discards it. Pass `--result-id=ID` through shell commands.
The caller retains the module and owns ticket cleanup. Counts cover all outcomes;
only the latest 32 detailed results are retained. Closing a menu without an
outcome is **not** proof of crafting success. Export status is separate from
verified craft status. Persistent Stockkeeper timers retain no GUI result ticket.

`craftplan preview LABEL`, the saved-plan **Explain recorded plan** action, and
the new-craft confirmation's **Explain this plan** show requested output, rounded
manufacturing batches, withdrawals, surplus, captured ingredient routes and stock
policies, and tool wear/stock/manufacture. Long interactive explanations wrap and
page through `qmenu`. Viewing reads only the selected snapshot: it does not
consult current recipes or change costs. Legacy snapshots show their known
execution facts without claiming to know missing choices. Remaining balances
subtract ordinary ingredients; tool damage/breakage needs physical verification.

**Edit choices / recalculate / review** works on an in-memory draft. Select a
captured branch and edit its stock policy, replace its recipe, or change an
allowed ingredient material. A shared branch changes all its references;
independent branches keep their choices. Recipe replacement explicitly captures
the replacement's dependencies. Existing tool families keep saved rules; newly
introduced families use current registry rules. Recalculation uses current stock.
Review shows before/after costs and routes. Only a confirmed final save overwrites
the label; leaving the editor discards the draft.

New captures retain each slot's ingredient source so material changes can be
checked against its ore/wildcard/exact alternatives. Older blueprints without
that information can still edit stock/recipes; explicitly recapture a recipe
before editing its material alternatives. Execution-only legacy plans need a new
explicit choice capture before editing. Missing inputs/cycles reject candidates.

```lua
local plans = require("craft_plans")
local candidate, diff = plans.edit("Iron gears", {
    kind = "stock", node = "mod:part", useStock = false,
}, {storageSide = 0})
assert(candidate, diff)
for _, line in ipairs(diff) do print(line) end
-- Explicit caller approval; candidate creation does not write anything:
assert(plans.save("Reviewed gears", candidate))
```

Other changes are `{kind="recipe", node=ID, recipe=recipeTable}` (or `false`
for an external leaf) and `{kind="material", node=ID, slot=N, item=ITEM}`.
The optional selection callback chooses new dependency routes/materials/policies.
`craft_preview.describe/lines/diff` exposes the same explanations programmatically.
CLI `craftplan edit LABEL --node=ID --stock=true|false`, `--recipe=N`, or
`--slot=N --material=ID` prints a candidate diff. It writes only with explicit
`--save`; `--to=LABEL` selects another destination. Headless new dependency choices
use planner defaults; use the UI/callback to guide them. Use one edit kind at a time.

## Memory-only robot job receipts

Each submission gets a unique execution ID, distinct from its saved label.
Results include `jobId` and `serverAddress` once a robot is selected. Separate
kit entries retain their individual IDs in `result.entries`; commands display
receipt-query commands for their submitted entries.

`cproc` records a running job **before inventory movement** and stores its
verified terminal outcome **before sending the final reply**. The same retained
ID/sender/request returns its recorded state without another execution. A changed
request or sender using that ID is rejected. Receipt-control connections can
query/replay existing IDs while busy; they cannot admit new crafts. Normal
crafting remains single-job, with no queue.

```lua
local plans = require("craft_plans")
local result = plans.run("Iron gears")
if result.status == "unknown" and result.serverAddress then
    local receipt = plans.query(result.serverAddress, result.jobId)
    print(receipt.status, receipt.message)
end
```

Use `craftplan status ROBOT_ADDRESS JOB_ID` or the saved-plan **Query a robot job
receipt** action. Queries return `complete`, `failed`, `running`, `not_found`, or
transport-uncertain `unknown`; `success` means confirmed completion, not just a
successful query. Querying never runs a craft, resumes Stockkeeper, or counts as
a new inventory-UI execution. Nonterminal/missing/unknown CLI queries return code 3.

Receipts live **only in the running server's memory**. Defaults retain up to 16
terminal receipts within a 32 KiB request/message byte budget, with messages
capped at 2 KiB. Active jobs are never evicted; Lua table overhead is additional.
Restart or eviction can erase a receipt. `not_found` is not proof that nothing
executed: inspect storage before deciding on another attempt. No restart recovery,
disk journal, automatic retry, rollback, or physical job resumption is provided.
Supplying a previous `jobId` to `plans.run`/`craft_client.runDetailed` also requires
its original `serverAddress` and is **retry-only**: an absent ID returns uncertainty
rather than admitting fresh work. Automatic Stockkeeper checks use fresh IDs and
retain their existing unknown-outcome pause behavior.

## Craft kits

Each kit is one `/usr/craftkits/<label>.kit` data file. Discovery uses directory enumeration only, including corrupt filenames; only the selected kit and its live references are decoded. A repeated live reference is loaded once per preparation. There is no manifest or per-file scan.

```lua
local kits = require("craft_kits")
assert(kits.save("T3 computer", {
    executionMode = "separate", accounting = "saved",
    entries = {
        {binding = "live", planName = "T3 Case"},
        assert(kits.pin("T3 CPU")), -- embedded copy, survives source edits/deletion
        {binding = "live", planName = "T3 Memory"},
    },
}))
local result = kits.run("T3 computer", {
    executionMode = "merged", accounting = "refresh", -- one run only
    onSuccess = function(r) print("Kit completed") end,
    onFailure = function(r) print(r.status .. ": " .. r.message) end,
})
```

`kits.list/save/load/remove/pin/prepare/run` return data/errors similarly to plans. `prepare(labelOrKit, options)` resolves bindings and returns `entries`, effective modes, and a combined `plan` for merged execution. Pinned copies keep captured rules; live references follow source-file edits. Missing live files fail before any component is submitted. Defaults change only through an explicit save/edit.

| Execution | Saved accounting | Refreshed accounting |
| --- | --- | --- |
| Separate | Replay each component's recorded operations/withdrawals in order. | Recalculate each component immediately before its job, within its locked blueprint. |
| Merged | One multi-output job with recorded operations and additive prerequisites; no shared batch-cost optimization. | Merge structurally compatible chosen branches, then account once, sharing compatible batches and wear. |

Different descendant recipes/materials/stock policies remain distinct even if item names match. Conflicting captured tool profiles reject merged mode; choose separate execution or explicitly edit the profiles. There is no silent fallback between modes.

Every requested kit output is protected. Separate execution reserves completed components by exact item/damage count so subsequent jobs cannot consume them; refresh excludes those reserved counts from its storage view. The robot enforces reservations live and verifies all earlier plus current outputs in return storage. These are count constraints, not locks against players or other storage users. Optional library `externalReserved={['mod:item']=quantity}` applies the same constraint to a caller's existing stock; runtime reservations are not saved in plan files.

Kits return ordered `entries`, `outputs`, `completedEntries`, `partial`, effective modes, and overall status. Merged execution has one submission result. Separate execution stops at the first failure/unknown outcome and keeps completed components; there is no rollback/retry. Overall hooks fire once, not once per child. Kit `stockAtLeast` is rejected: callers manage their own conditions; Stockkeeper watches one selected output of the whole supplying kit.

## Stockkeeper

Stockkeeper maintains labelled stock rules using **OpenOS `event.timer` callbacks**. Each rule is one `/usr/stockkeeper/<label>.rule` file. `list()` enumerates directory entries without opening individual rules or plans. New rules are disabled until explicitly enabled.

Each rule watches one exact output item and names a supplying saved plan or kit. The source defines the full replenishment increment; Stockkeeper never resizes it. Increment accounting includes recipe rounding and subtracts ordinary consumption of the watched item inside the source.

- **Replacement** (default command trigger): run when `quantity - currentStock >= increment`. With target 64 and increment 16, stock 55 waits; stock 48 runs a full batch.
- **Level**: run when `currentStock <= quantity`. This catches counts that jump below the configured level.
- Without `useExisting`, replay the source **as written**, including a kit whose stored accounting default is refresh. A kit's separate/merged execution default still applies.
- `useExisting=true` enables stock reuse within captured blueprint choices. Single plans and merged kits are accounted once against the check's snapshot and that exact result is submitted. Separate reuse kits refresh children at their live turn. A multi-entry separate reuse kit may not also consume/use its watched output: select merged mode or a dedicated producer for a reliable increment forecast.
- Watched outputs must be declared by the source and have a positive net increment. A watched output also used as a wearing tool is rejected because exact-damage stock gain is not reliably inferred; use a dedicated producer. Other tool usage and zero-wear tools remain supported.

```lua
local keeper = require("stockkeeper")
assert(keeper.save("Keep gears", {
    item = "mod:gear", quantity = 64, trigger = "replacement", interval = 30,
    source = {kind = "plan", name = "Iron gears"}, -- or kind="kit"
    storageSide = 0,
    -- useExisting = true, -- optional; absent means execute as written
}))
assert(keeper.enable("Keep gears", {
    onSuccess = function(r) print("Batch completed: " .. r.name) end,
    onFailure = function(r) print(r.status .. ": " .. tostring(r.message)) end,
}))
```

| Library API | Behavior |
| --- | --- |
| `list()` / `load(label)` | Discover labels / read one validated rule; `nil, error` on failure. |
| `save(label, rule, options)` | Persist configuration; enabled edits update the in-memory rule/timer. |
| `enable(label, options)` / `disable(label)` | Persist desired state and enable/disable checks. |
| `check(label, options)` | Check once, including a disabled rule; may execute the full source. Returns the crafting outcome. |
| `status(label)` | Copy of configuration, enabled/paused/busy state and last result. |
| `resume(label, options)` | Explicit acknowledgement after inspection; clear unknown hold and enable checks. |
| `remove(label)` | Delete that rule; source plan/kit files remain untouched. |
| `start(options)` | Restore saved enabled rules; returns `started`, `alreadyRunning`, and per-label `errors`. |
| `stop()` | Disable rules loaded in this runtime; returns success plus per-label errors. |

The standalone command supports `list`, `show`, `create`, `set`, `enable`, `disable`, `resume`, `check`, `status`, `remove`, `start`, and `stop`. Creation/editing accepts `--plan=LABEL` or `--kit=LABEL`, `--item=ID`, `--quantity=N`, `--interval=SECONDS`, `--trigger=level|replacement`, `--use-existing[=true|false]`, and the usual storage/network settings. Default interval is 60 seconds. Rule files retain scalar storage/timeouts/port settings; callbacks and hardware proxies are runtime-only. `stockkeeper check LABEL` is an explicit one-shot attempt, not a read-only inspection; use `status` for inspection.

**Restart:** invoke `stockkeeper start` from your OpenOS startup script after hardware and the crafting service are available, or call `require("stockkeeper").start(options)`. It reads saved rule configurations, registers enabled rules, leaves already-running rules alone, and leaves unknown-paused rules paused. It does not open source plans or run crafting during restoration. Requiring the library alone starts nothing. Reattach programmatic hooks through `start(options)`/`enable(label, options)` after reboot; functions are not serialized.

Timers remain registered after a command or menu returns to the OpenOS shell. Closing the UI does not disable enabled rules. Disabled/deleted/replaced callbacks check shared in-memory state and **return `false` on their next invocation**, letting OpenOS remove them. No timer IDs are stored. Interval edits register a replacement; stale callbacks retire the same way. Enabling starts checks at the next interval, not an immediate crafting attempt.

Each tick attempts at most one complete source batch. A shared reentrancy guard skips nested/overlapping Stockkeeper checks while a blocking craft pulls events; another rule waits for its next native tick. Confirmed failures remain enabled and recheck actual stock next tick. Unknown outcomes persist a pause and stop checks until storage inspection and explicit `resume`. A separate kit's partial result is retained; restarting its whole source is not rollback or component-job resumption. Disabling future checks does not cancel an already-submitted job.

Stockkeeper is quiet unless callers supply hooks. `onSuccess`, `onFailure`, `onSkip`, `countStock`, hardware proxies, and execution options work headlessly; results include watched `item`, `source`, `stockCount`, computed `increment` when evaluated, accounting and execution outcome. Hooks run once for the whole action with isolated result data; hook errors do not change verified success. UI lifetime callbacks are not attached to persistent timers.

Checks are snapshots, not inventory locks. Other storage users can change counts after checking. Configuration writes are direct, like plan/kit writes. Failed disable/unknown-pause persistence keeps checks stopped in memory and reports `persistenceError`; repair the file before reboot/restoration because an unsaved safety state cannot survive a power loss. Reboot resets native timers/runtime results, not saved configuration.


## Build recipe databases

Paths are used as supplied; no machine-specific mount IDs are assumed:

```text
build_database /path/shaped.csv /path/shapeless.csv /path/ore.csv
build_database /path/shaped.csv /path/shapeless.csv /path/ore.csv /path/stacks.csv /path/output
build_database /path/shaped.csv /path/shapeless.csv /path/ore.csv "" /path/output
compressdbs /path/raw /path/compressed
```

The default builder output directory is `recipe_db`, with `raw/` and `compressed/` subdirectories. An empty fourth argument omits optional item-stack data when providing an output directory. The builder supports `--e=mod1,mod2` exclusions. Copy recipe `.dblz` files to the recipe directory and the ore-dictionary archive to its separate directory. Failed builds/compression can leave partial output files; rebuild successfully before deployment.

### Compile the runtime database

`build_database` produces the source archives from CSV exports. After installing those archives in `/usr/lib/recipes/`, `build_db` compiles them into the runtime representation:

```text
build_db
build_db --load
```

| Entry point | Default behavior |
| --- | --- |
| First crafting recipe lookup | Load `/usr/lib/recipes/compiled.cb` once if present. |
| Compiled file missing | Build from installed `.dblz` files, save, and use the built table directly. |
| `build_db` | Force rebuild and overwrite `/usr/lib/recipes/compiled.cb`. |
| `build_db --load` | Rebuild/save and install that same table in the running `recipes` library. |

The compiled file stores the already-compressed per-item dictionaries. Loading it does not reparse source recipes or recompress them. Requiring `recipes` does not load/build the crafting database until its first lookup. A processing-only lookup can use the separate `/usr/lib/recipes/process.cb` without loading the crafting database.

`--load` clears the decoded recipe cache and replaces the active database directly, with no readback of the newly saved file. It populates only the same Lua environment; another computer/runtime loads the file normally. Existing processing registrations are preserved. `require("recipes").reload()` explicitly reloads the compiled file and clears the decoded cache; a plain `build_db` does not replace an already-loaded library's database.

Source changes require an explicit `build_db`; normal lookups do not scan for changes. There is one compiled file, with no versioned snapshots. An unreadable/invalid existing file reports an error directing you to rebuild it. If automatic construction succeeds but saving fails, the library warns and continues using that built table for the current runtime. Explicit `build_db` reports save failure and does not claim success or install the table. Writes are not atomic; an interrupted write may require running `build_db` again.

## Runtime responsibilities

- `recipes/build.lua`: shared source compiler and compiled-file I/O; `recipes/init.lua`: lazy loading, direct installation, cache invalidation and independent processing-recipe persistence.
- `craftingv4_4.lua`: coroutine-driven route/material/stock-policy capture. `craft_blueprint.lua`: pure validation, constrained accounting, cycle checks and structural composition. Explicit zero metadata (`item:0`) shares inventory identity with the base item; raw recipe lookup IDs are preserved.
- `craft_plan.lua`: hardware-free fixed-plan validation shared by client persistence and robot execution.
- `craft_plans.lua`, `craft_kits.lua`, `craft_store.lua`: per-label data, directory-only discovery, explicit accounting/bindings/modes, stock conditions and hooks.
- `stockkeeper.lua`: persistent replenishment rules, native self-retiring timers, explicit reboot restoration, whole-source checks, outcome holds and headless control.
- `craft_tool_rules.lua`, `craft_tools.lua`, `craft_tool_budget.lua`: pure rules, lazy user registry, scoped/global reservations and forward wear budgets with normal replacement dependencies.
- `craft_commands.lua`, `craft_management_ui.lua`: headless purpose adapters and explicitly interactive management; `craft` wraps purpose binaries through OpenOS shell execution.
- `craft_client.lua`: one job's discovery, connection, progress, deadlines, interruption and cleanup. `runDetailed` distinguishes confirmed completion/failure from unknown execution; legacy `run` retains its two-return interface.
- `cproc.lua`: network request validation, single-job ownership and truthful terminal status.
- `craft_executor.lua`, `craft_resources.lua`: live gathering, branch/tool ownership, grid loading, physical wear/output verification and checked return-storage counts.
- `robinv.lua`: robot inventory operations and cache synchronization. `component.robot.count()` is tick-free; empty-slot checks use it without stack-detail reads. Affected occupied slots are read back for identity after transfers/crafts.

`COMPLETE` means that the robot verified **every** requested output, returned its inventory, and read back sufficient outputs/reservations in storage. A short transfer, wrong/partial output, invalid plan, cancellation, missing storage or blocked return produces failure. Cleanup failure messages identify items that may remain on the robot.

### MES machine recovery

Machine admission follows inventory and job events. Output collections use
configured or learned processing times; partial output updates the remaining
work's schedule. There is no fixed grace period or exponential retry timer.

An empty collection triggers one read of the machine's roles to refresh its
inventory view and timing, then one collection retry. Continued output permits
continued work. A failed retry quarantines unresolved loads and fails work
queued for that machine; a later request must reconcile those materials before
reusing it. A fully refused input with no owned load to wait for uses the
existing read/empty recovery once before retrying admission.

Recovery attempts and remaining due times survive MES restarts. An unknown or
badly underestimated slow machine can fail before its first output; provide a
processing-time estimate before retrying it. Recovery preserves material
ownership, but cannot repair a machine's power or external configuration.

## Tool and container semantics

Successful crafting does **not** imply an empty grid. All nine slots are checked after crafting, and retained items are read back and moved to the buffer before the next batch. This preserves tools, changed stack identities, returned containers and unconsumed inputs in inventory bookkeeping.

`maxSize == 1` is only a candidate-tool hint: armor, buckets and consumed ingredients may also be nonstackable. `maxDamage > 0` is evidence of durability, not a recipe consumption rule. Item-stack metadata does not currently change ingredient costs automatically.

Register a family through Tools, `crafttools set`, or `require("craft_tools").set(item, durability, wear)`. The lazy registry is `/usr/lib/craft_tools.cb`; `get/list` return copies and `remove/reload` manage it. Profiles charge wear per recipe operation **per tool slot**, not per output item. Zero wear means unlimited reuse. Capacity is conservatively `floor((durability-damage)/wear)`; two simultaneous slots require two distinct units.

The planner budgets stocked wear and manufactures fresh replacements through their captured recipes/material dependencies. Replacement manufacture may itself require tools. Captured profiles survive registry changes. The robot selects by family/capacity, observes actual wear and breakage, and fails on unexpected identity, consumption or excessive wear. Stock grants are finite and allocation-ordered; fresh selection favors greater remaining capacity. Budgeting is conservative, not a globally minimal-tool optimization. Tools requested as products stay fresh/protected.

Unflagged ingredients remain conservatively consumed; a retained unflagged tool with changed damage may fail later exact matching. NBT/enchantments, non-wear metadata variants, actual mod break thresholds and stochastic wear need explicit in-game verification; registration does not solve those distinctions.

## Current boundaries

- Machine-processing recipes can be represented/planned, but the 3x3 executor rejects them before moving inventory. `machines.lua` and `logistics.lua` are scaffolding, not an integrated distributed scheduler.
- Prerequisites and intermediates must fit the robot buffer (slots 13 through inventory size). A default 16-slot robot has only four buffer slots. There is no streaming/offloading scheduler; insufficient capacity is an explicit failure.
- Default recipe selection takes the first available recipe. A cyclic choice is rejected; automatic alternative-recipe backtracking and cost optimization are not implemented.
- Ore/wildcard resolution chooses concrete substitutions; mixing several variants to satisfy one ingredient is not optimized.
- Plans must fit one modem packet. Oversized plans fail explicitly; fragmentation, automatic retries and physical job resumption are not implemented. RAM receipt replay/query returns known state without repeating a craft.
- Automated tests mock hardware, OpenOS buffering and menu boundaries. They establish regressions, not in-game certification.

## Regression tests

From the repository root, with Python and `lupa` installed:

```text
python -m pip install -r craftsystemv3/tests/requirements.txt
python -B -m unittest discover -s craftsystemv3/tests -v
```

Tests run Lua 5.3 through Lupa and cover planning, database loading/building, archive transport, robot inventory, execution, server outcomes, network/client lifecycles and menu wiring. Tests require no Minecraft instance and do not modify production recipe databases.

## In-game verification checklist

1. Craft a multi-output recipe such as planks, a sparse shaped recipe, and a chain with a shared intermediate. Verify quantities and returned surplus.
2. Test partial pulls, several source stacks and Storage Drawers slot reindexing. Remove an ingredient after planning and verify failure/cleanup.
3. Craft a nonstackable output. Exercise a retained tool, durability-changing tool, and returned container; confirm physical slots and cached names/counts agree.
4. Fill storage so final return is blocked. The client must never receive `COMPLETE` while output remains on the robot.
5. Cancel during planning and execution, run a job longer than 30 seconds, stop the server mid-job, and trigger idle/total deadlines. Check robot/storage state before retrying.
6. Test actual OpenOS archive buffering with valid, truncated and unwritable archives; verify files/ports/listeners close on failure.
7. Run consecutive jobs and two clients. Verify busy rejection, terminal status, saved-plan execution and screen/viewport restoration with the installed `qmenu` version.
8. Save a labelled batch without executing, execute it from Craft Plans, and run it from a headless OpenOS Lua script. Check threshold skip/full-batch behavior, success/failure/skip hooks, and timeout handling without blind retries. Confirm listing many plans does not open their files.
9. Compile installed recipes, restart/reload the library and compare startup time and lookup results. Remove `compiled.cb` to verify automatic build/save, then change a source archive and run `build_db --load`; verify the updated in-memory result without a second compilation or file read in the same OpenOS environment.
10. Register a worn tool and exercise replacement manufacture, simultaneous slots, zero wear, real breakage, and a fresh tool requested as a kit product. Compare configured versus observed wear.
11. Run all four kit modes, shared batch recipes and distinct material branches. Verify every output, earlier-component protection, pinned/live edits/deletion, defaults/overrides and partial/unknown outcomes. List many kits/plans without opening each file. Verify actual purpose-binary exit codes, parent-menu restoration and installed `qmenu` behavior.
12. Enable Stockkeeper rules, close the menu/return to the shell, and verify native ticks keep checking. Test replacement and level boundaries, stock reuse, timer interval edits, disable/delete self-retirement, confirmed failure's next-tick recheck, unknown pause/resume, and reboot followed by `stockkeeper start`. Repeating `start` must not duplicate timers. Test failed safety-state writes before trusting unattended restart.
13. From `inv.lua`, Shift+C a damage variant with a quantity, then verify forwarded sides, refresh/redraw and accurate complete/failed/unknown summaries. Check export failure separately from verified completion. Confirm actual OpenOS shell children share the result-ticket module.
14. Page a long plan explanation. Edit stock, recipe and ore-material choices; inspect costs before/after, cancel without changing the file, then confirm a save. Verify other independent branches and pinned kit copies remain unchanged.
15. Query a running/completed/failed robot ID while busy. Simulate a lost final reply and repeat its ID: no second inventory movement. Reject changed payloads/senders; test eviction/restart returning missing/unknown and verify queries never automatically recraft or resume Stockkeeper.
