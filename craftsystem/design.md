# Craft system v3: tools, constrained plans, and craft kits

## Status and working contract

This document defines the implemented tool, constrained-plan, kit, Stockkeeper,
inventory handoff, reviewed-editing and memory-only receipt contracts.
The implementation is regression-tested with mocked OpenOS/hardware; deployment
acceptance requires the in-game checklist in `README.md`.

Work exclusively in:

```text
C:/Users/Conner/Documents/GitHub/OC-Utilities/.worktrees/craftsystemv2-stabilization
branch: fix/craftsystemv2-stabilization
project: craftsystemv3/
```

Preserve all existing stabilization and compiled-database changes. The main
checkout at `C:/Users/Conner/Documents/GitHub/OC-Utilities` has unrelated modified,
deleted, and untracked files; leave those untouched. Changes remain uncommitted.
Staging, committing, merging, and deploying require further user instruction.

Implementation and review are performed personally by the main assistant, as
requested. The user declined context checkpoints for this session. Preserve that
choice on resume. For maintenance, read current source/tests and this contract;
give progress updates tied to actual edits and verification.

## 1. Goals

1. Let users explicitly register reusable tools and their durability rules.
2. Account for wear and replacement-tool manufacture through normal crafting
   dependencies, including its material costs.
3. Preserve user-selected recipes, material substitutions, and tool choices in
   saved plans, with controlled accounting refresh.
4. Define a craft kit as an editable, labelled collection of component plans.
5. Offer separate or merged execution, with saved defaults and one-run overrides.
6. Support pinned and live bindings independently for each kit entry.
7. Keep `craft` as the unified UI, backed by independently callable purpose
   binaries and shared Lua libraries.
8. Preserve fast filesystem discovery: enumerate names rather than opening every
   saved plan or kit.

The guiding principle is explicit optionality: accounting and execution can be
powerful without silently changing the user's chosen crafting routes.

## 2. Layers and responsibilities

### Shared Lua libraries

Libraries own domain behavior: profile persistence, recipe selection,
dependency accounting, blueprint preparation, plan/kit persistence, composition,
execution, and structured outcomes. A library is what was meant by “API” in the
discussion: ordinary functions reached with `require(...)`, not a web service.

Headless callers must be able to use these capabilities without GPU or `qmenu`.
Lua callbacks belong to the caller and are never serialized into saved data.

### Purpose-specific binaries

Each purpose binary is independently callable from the shell and through
`shell.execute()`, without `craft` already running. It wraps the same libraries
used by interactive and programmatic callers. Noninteractive commands must have
predictable arguments/results and no unexpected confirmation prompts.

The commands are `crafttools`, `craftplan`, `craftkit`, and `stockkeeper`. Example operations:

```text
crafttools list
crafttools set mod:hammer --durability=100 --wear=1
craftplan run "Iron gears" --accounting=refresh
craftkit run "Full T3 Computer" --mode=merged
stockkeeper start
```

### Unified `craft` UI

Tools, Craft Plans, Craft Kits, and Stockkeeper share the `craft` system.
`craft` orchestrates purpose-binary interactive flows using
`shell.execute()` and resumes/redraws its menu afterward. The purpose binaries
may also expose their interactive flows directly.

Each child flow must release temporary UI listeners and per-job network/timer
resources and restore terminal/viewport state. Enabled Stockkeeper rule timers
retain their independent lifetime after menu exit. OpenOS `shell.execute()` reduces ordinary command returns
to process status. Binaries use codes 0 (complete/skipped/management success),
1 (craft failure), 2 (command/preparation error), and 3 (unknown). Interactive menu
exit success is not craft completion; structured library results carry outcomes.

## 3. Tool profiles and accounting

### Explicit registration

A user can select or enter an item name, then enter its maximum durability and
durability consumed per crafting operation. The profile is persisted and can be
managed through both the UI and the library/purpose binary.

Profile shape:

```lua
{durability = 100, durabilityPerUse = 1}
```

The registry stores profiles by item family in
`/usr/lib/craft_tools.cb`. A registered family's damage field is interpreted as
wear; current damage is read from each actual inventory stack. Zero wear denotes
a reusable item with no wear charge. Numeric input must be finite and valid.

Registration is authoritative. Stack size and `maxDamage` can assist user entry
or future detection but do not prove that an ingredient is reusable. Unregistered
items retain ordinary conservative consumption accounting. NBT-dependent
identity and arbitrary non-wear metadata variants are not automatically solved
by registering an item family.

### Tools are ordinary dependencies

A tool has special consumption behavior, not a separate availability gate:

1. Calculate the operations and simultaneous tool slots required by the chosen
   recipes.
2. Budget usable durability from eligible tools already in storage.
3. Calculate how many fresh tools are required for the remaining work.
4. Resolve those tools' chosen recipes and their ingredients through the normal
   dependency graph.
5. Report the normal missing terminal materials if production cannot be supplied.

When a tool recipe exists, the planner must manufacture replacements rather than
merely returning “insufficient tools.” A tool with no permitted manufacturing
route is an externally supplied terminal dependency, just like another item with
no permitted recipe.

Wear is charged per recipe operation and per tool slot. If one operation produces
four outputs, it does not charge four uses. Two simultaneous hammer slots need
two distinct units; total pooled durability alone is insufficient. Shared
consumers and increased demand must share one coherent wear/resource ledger.

Illustrative conservative capacity:

```text
usable operations = floor((configured durability - current damage) / wear per use)
```

Actual game/mod break thresholds and stochastic wear must be verified. The
implementation must distinguish a configured budget from observed physical
behavior rather than blindly predicting destruction.

Replacement manufacture participates in normal ordering and cycle detection.
Tools requested as outputs remain products; they cannot be silently used up as
another task's tool when the output must still be delivered.

### Captured rules and robot execution

The prepared execution plan carries the applicable tool profiles, tool-slot
bindings, and resource/wear requirements. The robot must be able to execute from
that payload without consulting a separately installed user tool registry.

The robot must:

- Select eligible units by family and sufficient remaining wear budget, rather
  than rejecting a retained tool solely because its damage changed.
- Distinguish simultaneous units and preserve current identity/count bookkeeping.
- Handle retained tools, planned breakage, and replacements while following the
  prepared dependency order.
- Read back actual grid contents and wear after crafting; unexpected consumption,
  identity changes, or excessive wear fail safely with physical cleanup.
- Continue to verify output quantities and successful return to storage before
  reporting completion.

Captured profile changes are deliberate. Editing the global registry must not
silently rewrite a pinned plan's rules.

## 4. Saved plans: blueprint and execution result

A saved plan needs two distinct representations:

1. **Chosen dependency blueprint:** the authorized recipes, concrete ingredient
   substitutions/tool choices, output quantities, and inventory-use policies.
2. **Calculated execution result:** the actual tasks, material withdrawals,
   tool allocations, and ordering produced for a particular accounting run.

New plans persist both representations. Legacy execution-only plans retain fixed
replay compatibility.

### Blueprint completeness

Capture the permitted routes needed to refresh accounting, including manufacture
of tools and intermediates that happened to be stocked during the initial run.
Preserve user-approved terminal-material boundaries; do not recursively capture
every alternative recipe in the database.

A refresh cannot invent a new route for an intermediate that has become absent.
If its permitted route was not captured, require an explicit plan edit/capture.
Recipe database edits do not automatically substitute a new route into a saved
blueprint.

Record whether each relevant intermediate may be taken from stock or must be
manufactured. Stocked intermediates do not establish which historical materials
were used to make them; users needing source-material control must be able to
choose manufacture rather than unknowingly accept unknown provenance.

### Accounting choices

- **Saved accounting:** use the captured execution assumptions/result, subject
  to live prerequisite and output verification.
- **Refreshed accounting:** recalculate amounts, stock use, tool wear and
  replacements, but only inside the saved blueprint and its constraints.

Refreshing quantities does not grant permission to change recipes, material
substitutions, tool types, or approved leaf boundaries. If the allowed resources
cannot supply the request, report the missing allowed inputs even if an unrelated
recipe route could succeed.

Legacy finalized `.plan` files remain executable as fixed results. Refreshing
them requires capturing a blueprint; silently reconstructing recipe choices from
the current database would violate the user's control.

## 5. Kit definition and filesystem

A saved kit is a labelled collection of component plans. It can be prepared as
separate jobs or as a combined multi-output execution plan.

```text
/usr/craftplans/
    T3 Case.plan
    T3 CPU.plan
    T3 Memory.plan
    T3 GPU.plan

/usr/craftkits/
    Full T3 Computer.kit
    Mining Robot.kit
```

One file per kit contains its defaults and ordered entries. Conceptual data:

```lua
{
    executionMode = "separate", -- or "merged"
    accounting = "saved", -- or "refresh"
    entries = {
        {binding = "live", planName = "T3 Case"},
        {
            binding = "pinned",
            sourceName = "T3 CPU",
            plan = {...}, -- captured plan/blueprint data
        },
        {binding = "live", planName = "T3 Memory"},
        {binding = "live", planName = "T3 GPU"},
    },
}
```

These are serialized data files, not executable scripts. The execution/blueprint
schema is defined in section 8 and validated by the shared libraries.

### Per-entry bindings

- **Pinned copy:** embeds the captured plan in the kit file. The original plan
  file is unnecessary; updating the pinned entry is explicit.
- **Live reference:** stores a saved plan lookup name and resolves that plan at
  execution. Later source-plan edits apply because the user chose a live binding.

Show bindings clearly in the UI. Switching execution mode or applying a one-run
override does not alter bindings. A missing live reference must be reported,
without silently replacing it with another plan. Resolve and validate the
selected kit's entries before physical work begins where possible.

### Defaults and one-run overrides

The kit stores its default `executionMode`. Manual execution preselects the
default and lets the user override it. Programmatic/unattended execution uses
the saved default unless the caller supplies an override, conceptually:

```lua
kits.run("Full T3 Computer", {executionMode = "merged"})
```

A one-run override leaves the saved file unchanged. Persisting a new default
requires an explicit edit/save. `accounting` defaults to `saved`; `refresh` is an
explicit choice. Both controls are available at manual execution and in libraries.

### Fast discovery

List `.plan` or `.kit` filename stems using `filesystem.list()`. Discovery and UI
pagination must not open/read/stat individual data files or referenced plans.
No separate manifest/index database is needed.

Opening/preparing one selected kit reads that kit and only its live references.
Pinned entry data comes from the kit file. Directory navigation can use the
already-enumerated names in memory.

## 6. Separate and merged execution

### Separate

Run the component plans in the kit's order, honoring each binding and the selected
accounting policy. Preserve per-entry results and an overall result. Stop on a
failed/unknown stage; do not automatically retry a possibly submitted job.

Separate jobs can leave completed components in storage when a later job fails.
Kit execution is not transactional rollback.

Completed outputs are accumulated as exact-item count reservations for later
jobs. Refreshed views exclude those counts; robot pulls and return verification
enforce them live. Thus a later component cannot consume an earlier kit output
as its prerequisite. Concurrent external storage changes can still cause failure;
these constraints are not transactional locks.

### Merged

Prepare one multi-output execution plan from the selected entries. All declared
kit outputs must be accounted for and verified, including quantities retained
at the end rather than consumed as another component's ingredients.

Merging must:

- Share compatible intermediate batches, surplus, material reservations, and
  wear accounting where the chosen accounting policy permits it.
- Preserve distinct branches when their recipes, concrete inputs, inventory-use
  policies, or tool rules differ. Equal item names alone do not prove equivalent
  branches; descendant constraints matter too.
- Preserve user choices. Combining plans does not authorize searching for another
  dependency graph or substituting cheaper/available materials.
- Use a coherent resource ledger so two source plans cannot reserve the same
  physical input/tool independently and both assume ownership.
- Verify every required final output; one successful target is not kit success.

Saved merging preserves recorded operations and additive withdrawals, remapping
component branch identities into one job. It verifies branch conservation,
distinct units, wear grants, and protected outputs before submission. It does
not optimize shared batch costs. Refreshed merging combines compatible captured
blueprints and recalculates once. Separate saved replay and separate per-stage
refresh complete the four explicit combinations. A conflict reports an error;
there is no silent mode/accounting fallback.

For a refreshed merged plan, recompute combined demand inside the locked
blueprints. Simply concatenating tasks and adding snapshots is not sufficient
for shared batch rounding, wear, resource ownership, or protected outputs.

Conflicting pinned/live profile versions must remain visible. They cannot be
resolved by silently overwriting one profile with the other.

## 7. Outcomes, stock keeping, and hooks

Retain the shared library's result distinctions:

- `complete`: verified requested output and successful physical return.
- `failed`: confirmed failure or a pre-submission preparation failure.
- `skipped`: an explicit stock condition already met.
- `unknown`: submission was attempted but terminal outcome was not confirmed.

Confirmed failures can still have made partial physical progress. Unknown
outcomes require checking storage before retrying. Hook/logging/local cleanup
errors cannot convert confirmed completion into a reason to craft again.

Lua callers supply success/failure/skip hooks. Call the applicable overall hook
once per returned attempt, after cleanup attempts; preserve per-entry information
for kits. Functions and shell command hooks are not stored in kit/plan files.
Callback delivery is not guaranteed across process crashes.

The existing single-plan `stockAtLeast` condition is optional: omit it to attempt
the saved batch; reaching it skips the batch. A threshold check is a condition,
not an inventory reservation. Freshened accounting must still obey locked
choices. Kit-level stock metrics/repetition controls require an explicit design
if introduced; do not invent “one kit available” by counting only one component.

## 8. Current implementation inventory

Implemented modules under `usr/lib/`:

- `craftingv4_4.lua`: coroutine route/material/stock-policy capture; optional sixth
  argument `{toolProfiles=...}`; recipe selection `false` means external leaf.
- `craft_blueprint.lua`: hardware/file/recipe-independent `validate`, `copy`,
  `calculate`, `merge`. Full permitted DAG, iterative cycle checks, scoped demands,
  typed structural signatures, compatible sharing and profile-conflict errors.
- `craft_tools.lua`, `craft_tool_rules.lua`, `craft_tool_budget.lua`: lazy profile
  persistence, pure rules, global stock ownership and execution-order wear budgets.
  Replacement demands converge within the captured DAG. Large unused stocks are
  represented by cohorts; fresh demand is arithmetic rather than per-use loops.
- `craft_plan.lua`: pure execution/metadata validation and fixed-flow proof.
- `craft_plans.lua`, `craft_store.lua`, `craft_kits.lua`: sanitized per-label data,
  filename-only discovery, pinned/live resolution, four modes, runtime reservations,
  stock conditions, per-entry outcomes and isolated Lua hooks.
- `craft_executor.lua`, `craft_execution.lua`, `craft_resources.lua`: measured
  physical transfers, branch/tool ownership, wear readback, protected outputs and
  returned-storage count verification. Registry/recipe-independent robot execution.
- `craft_client.lua`: discovery, separate deadlines, cancellation/cleanup and
  complete/failed/unknown outcomes; full blueprints are excluded from modem packets.
- `craft_commands.lua`, `craft_management_ui.lua`: headless command adapters and
  explicit GPU/qmenu flows. `usr/bin/crafttools.lua`, `craftplan.lua`, `craftkit.lua`
  are independently callable; `craft.lua` wraps their management flows.

Compiled database loading/building and prior robot/network stabilization remain
part of this worktree. Deploy the project's `usr/bin` and `usr/lib` together.

### Execution and blueprint data

Legacy `requestItem`, `requestQuantity`, `inventory_needed`, `tasks` remain valid.
Additive execution fields:

```lua
requestOutputs = {['mod:item'] = quantity}
tools = {['mod:hammer'] = {durability=100, durabilityPerUse=1}}
tool_stock = {['mod:hammer'] = {minimumUsesForUnit1, minimumUsesForUnit2}}
node_items = {nodeId = 'mod:item'}
stock_nodes = {nodeId = quantity}
request_nodes = {nodeId = quantity}
tool_stock_nodes = {['mod:hammer'] = {'nodeId', 'nodeId'}}
-- Task additions: node, input_nodes[slot], tool_slots[slot].
-- Runtime only: external_reserved = {['mod:item'] = quantity}.
```

Ordinary withdrawals and tool-unit withdrawals are separate. Finite minimum-use
grants bind stocked units to scopes; fresh units come from preceding tasks.
Stock grants are allocation-ordered, fresh selection favors remaining capacity.
Requested outputs agree with the legacy first target and are all verified.
Runtime reservations/callbacks/coroutines are excluded from persisted plans.

```lua
blueprint = {
    roots = {{node='root', quantity=1}},
    nodes = {
        root = {item='mod:product', useStock=true, recipeOutput=1,
            recipe={'mod:raw'}, deps={'raw'}, tool_slots={}},
        raw = {item='mod:raw', useStock=true}, -- terminal leaf
    },
    tools = {},
}
```

Nodes may carry processing metadata for planning; robot execution still rejects
machines. Root production is forced new; intermediate `useStock=false` forces its
chosen manufacture. The full blueprint stays in the saved file/client environment.

Tests use Lua 5.3 through Lupa with mocked hardware/OpenOS/menu boundaries. Actual
OpenOS buffering/serialization, installed `qmenu`, shell composition, and mod wear
behavior require deployment verification. See `README.md` for the command/API and
in-game checklist.

## 9. Verification and maintenance acceptance

Run from the worktree root:

```text
python -B -m unittest discover -s craftsystemv3/tests
git diff --check
```

The suite includes project-wide Lua 5.3 syntax checks, pure accounting, seeded
mixed-width grant simulations, persistence/failure paths, command/menu wiring,
and physical mocked robot kit execution. Review changes against these contracts
personally and report exact verification plus remaining real-hardware boundaries.

Required regression cases include:

- Worn/no stocked tools; craftable replacements; missing replacement materials.
- Multi-output recipes, shared consumers, increased demand, simultaneous tool
  slots, zero wear, cycles, breakage and unexpected physical wear/consumption.
- Captured profiles/recipes unchanged by registry/database edits.
- Currently stocked intermediates becoming absent during permitted refresh;
  missing captured routes cannot trigger automatic alternative selection.
- User-forced manufacture versus approved stock use.
- Blueprint/snapshot roundtrip and legacy fixed-result compatibility.
- Pinned entries surviving source edits/deletion; live entries reflecting edits.
- Kit defaults versus one-run overrides, and overrides leaving files unchanged.
- Separate partial failure/unknown outcome and one overall hook.
- Merged output verification, shared batch rounding/resource ownership, conflicting
  choices, protected outputs that are also dependencies, separate-stage reservations,
  and final dumps that lose output outside storage.
- Zero per-file opens during discovery/paging; only selected files/references read.
- Direct purpose-binary calls, headless operation, `shell.execute()` domain result
  propagation, cancellation/cleanup and return to the parent menu.

Existing boundaries remain unless explicitly extended: one modem packet per
plan, finite robot buffer capacity, no integrated machine/drone execution, no
automatic recipe backtracking, and no NBT identity model. Detect violations
explicitly rather than promising successful execution outside those boundaries.

## 10. Stockkeeper operating contract

`usr/lib/stockkeeper.lua` supplies headless control; `usr/bin/stockkeeper.lua`
adapts the shared command layer. The `craft` menu opens its `qmenu` management
view through `shell.execute("stockkeeper", nil, "--interactive", ...)`.

Rules are labelled `/usr/stockkeeper/<label>.rule` files containing an exact
watched output item, quantity, level/replacement trigger, source plan/kit label,
positive interval, enabled preference and optional `useExisting=true`.
Persisted scalar storage/network settings accompany the rule. Directory listing
discovers names; selected actions read the selected rule/source. Startup reads
rule configurations to restore enabled preferences, without opening source plans.

Native OpenOS repeating timers use `math.huge` executions. Each callback captures
its rule state and checks the shared current state before work. Disabled, deleted,
paused and replaced callbacks return `false`, allowing native self-retirement;
timer IDs are not tracked or persisted. A module-wide check guard prevents nested
crafts while blocking clients pull events. Ordinary failure does not return false.

Replacement triggers at `quantity - stock >= increment`; level triggers at
`stock <= quantity`. Source tasks retain full output quantities. Net increment
accounts for whole recipe batches and ordinary watched-item consumption. The
watched item must be a declared output with positive net replenishment.

Default execution replays saved tasks regardless of a kit's accounting default.
Optional stock reuse preserves captured choices. Single/merged refreshes forecast
once and submit that exact calculated result. Separate refreshes calculate each
child at its live turn; multi-entry separate reuse kits cannot use the watched
output as an ingredient/tool because subsequent net output would be variable.
Use merged mode or a dedicated producer for that case. Watched wearing-tool
outputs are rejected; other tool budgeting remains delegated to crafting modules.

Complete keeps checks active. Confirmed failure rechecks stock at the next native
tick. Unknown outcome records a persistent pause until inspection and explicit
resume. Disabling future checks leaves an already-submitted job to finish. Failed
disable/hold writes still stop checks in memory and report persistence errors;
repair persistent configuration before restarting the computer. Source snapshots
freeze checked labels/bindings, but stock checks remain snapshots, not locks.

`stockkeeper start` / `keeper.start(options)` explicitly restores saved enabled
rules after reboot and skips already-running/unknown-paused rules. Requiring the
library starts nothing. Menu exit leaves deliberately enabled timers running.
Hook functions, injected proxies, busy state, timers and last results are runtime
data. Reattach hooks on startup. Tests must cover directory-only discovery,
restart/idempotence, self-retirement, stale callbacks, reentrancy, rounding/net
increments, reuse boundaries, confirmed/unknown outcomes, safety-write failures,
standalone commands and actual `qmenu` flow wiring.

## 10.1. Inventory handoff, explanations and reviewed editing

`inv.lua` continues calling `craft` through the OpenOS shell. It forwards detected
storage/output sides, reads Shift+C quantity, refreshes both inventory snapshots
and restores/redraws its menu after every return path. `craft_handoff` provides
caller-owned in-memory result tickets passed with `--result-id`; purpose binaries
report actual manual execution outcomes, not menu-exit process success. Keep
unknown/failed counts across multiple child actions. Retain at most 32 detailed
outcomes per ticket and release/consume it after the shell call. Export failure
does not change a verified craft result. Persistent timers retain no UI ticket.

`craft_preview` reads the finalized snapshot and its captured blueprint. Explain
requests, rounded batches, withdrawals, remaining balances/surplus, routes, stock
policy and tool budgets without querying recipes or recalculating. Root outputs
always require new manufacture. Legacy snapshots expose only known execution
facts. Tool wear is reported separately from ordinary-input conservation.
Interactive long explanations wrap/page through `qmenu`; the CLI and library
use the same explanation data.

`craft_edit.candidate` / `craft_plans.edit` return a new calculated candidate and
before/after lines. Stock-policy changes require no recipe lookup. Explicit
recipe replacement captures its new dependency subtree; material substitution
must satisfy the slot's captured ingredient source. New captures persist those
sources; older blueprints require recipe recapture for material-alternative edits.
Preserve unaffected independent branches and requested roots. Shared-node edits
affect its shared references. Saved tool rules remain fixed; new tool families
introduced by an explicit route edit use the current registry. Recalculate on a
fresh stock snapshot and reject missing inputs/cycles. Candidate creation performs
no file write or execution. UI save requires final review/confirmation; CLI save
requires `--save`, optionally with another `--to` destination. Plain legacy
execution snapshots require a fresh explicit capture before editing.

## 10.2. Memory-only robot job receipts

Use unique IDs per execution attempt, with returned `jobId` and `serverAddress`.
`cproc` registers running state before moving items and terminal verified state
before replying. A retained duplicate with matching sender and canonical request
returns state without crafting again; mismatched request/sender is rejected.
Receipt queries and existing-ID replay remain available while busy. Control
connections cannot admit new work; preserve normal single-job admission.

The pure `craft_receipts` registry is RAM-only. Default terminal retention is 16
results within a 32 KiB encoded-request/message budget, plus table overhead;
messages are limited to 2 KiB. Active jobs are never evicted. Queries address the
original robot, never a newly discovered substitute. Return complete/failed,
running, missing or transport-unknown state. Missing/expired/restarted records
are not proof of no execution. Explicit old-ID submissions require the original
address and refuse new work if the receipt is absent. Queries do not change saved
plans, count as new crafts, or automatically resume Stockkeeper. Its ticks create
fresh IDs and preserve unknown-outcome pauses. Physical restart recovery and
durable job records are outside this contract.

Verify shell handoff/cleanup, paged previews, no-write cancelled drafts,
stock/material/recipe edits and isolated branch preservation, new-route tools,
busy status queries, duplicate/conflicting IDs, terminal-before-reply recording,
retention bounds, and missing-receipt retry refusal with regressions. Actual
OpenOS shared require cache, shell behavior, installed menus and hardware remain
deployment checks listed in `README.md`.

## 11. Changes outside this contract

Packet fragmentation, machine/drone scheduling, streaming/offloading, alternate
recipe backtracking, globally minimal tool scheduling, NBT/enchantment identity,
atomic file replacement and durable job/hook delivery remain separate work.
Obtain explicit approval before extending these boundaries or changing the user's
route/material/accounting/binding controls. Preserve the isolated worktree and
uncommitted state until the user requests integration or deployment.

### Future crafting stations and drone logistics — on hold

The intended future architecture gives each crafting robot a local buffer
inventory at its station. Drone logistics delivers inputs and removes outputs;
the robot executes ready crafting steps using that buffer. Planning retains
recipe/material choices and dependency accounting, while logistics handles
transport. This separates the station's working capacity from the inventory
needed for an entire job.

This architecture is not implemented. Drone dispatch, transfer protocols,
station allocation and incremental execution remain on hold pending explicit
implementation approval. Current execution still gathers prerequisites into
the robot's own buffer. Future incremental execution should fit the station
model and retain branch/tool ownership and protected output accounting.
