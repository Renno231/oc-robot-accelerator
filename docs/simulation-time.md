# Simulation time and acceleration

OC Robot Accelerator executes the pinned Minecraft 1.12.2 / Forge 14.23.5.2860 / OpenComputers 1.8.9a runtime. It compresses idle host waiting while retaining native simulated work. Arbitrary-workload equivalence and deterministic whole-world replay are not established.

## Three clock responsibilities

1. **Simulation/environment time:** world tick deadlines, native worker-delay deadlines and selected guest-visible elapsed-time/metadata inputs.
2. **Active execution time:** time actually consumed by native Lua/native computation. Long worker passes remain asynchronous so native world ticks can occur during computation. CPU tiers do not define an invented Lua instructions-per-second rate.
3. **Host supervision time:** cancellation, wall budgets, CPU/I/O watchdogs, termination and cleanup use real host deadlines. They never jump with simulation time.

Schema 3 selects idle-compressed execution by default with the native 12 ms worker-delay setting. `baseline` is the native-speed reference; `paced` uses the coordinator without idle jumps. Selecting a zero worker delay changes the scheduling profile and is not required for acceleration.

## Ownership

- `src/main/java/ocelot/spike/RunnerScheduler.java` owns temporal accounting, native worker tickets, eligibility, reservations and idle-jump decisions.
- `RunnerAsyncWork.java` tracks native background work through admission/completion. Outstanding native file writes conservatively prevent jumps.
- `Pacing.java` and `PacingTransformer.java` connect that ownership to pinned engine clock/dispatch sites. Exact transformer hook counts are tested against the acquired binary classes.
- `RunnerRuntime.java` owns the concrete world/robot lifecycle. `RunnerHardware.java` uses native assembler validation.
- `RunnerObservations.java` samples immutable observations; it does not own time.
- Python scenario/jobs/supervisor modules own validated inputs, process admission, real-host limits and cleanup. Callers never coordinate individual worker passes.

The Java namespace, control-mod identifiers and legacy disk names remain stable compatibility identifiers; they do not introduce a dependency on another repository.

## Idle-jump rule

A jump is permitted only when tracked behavior-affecting participants are quiescent, no event is runnable, and the next relevant deadline is known. Enqueue/reservation and jump decisions share one temporal owner. A due task waiting for a host worker is runnable, not idle.

At the native server sleep boundary, skip only to the earlier of the next eligible worker deadline and the end of the requested idle interval. Credit the server accumulator with the skipped duration exactly once. World ticks, action pauses, power debits, charger updates and saves still execute.

Active Lua/native work or an unresolved asynchronous completion prevents an idle jump. Native world-tick opportunities remain available during a long worker pass. A zero-delay yield is runnable work; it cannot manufacture simulated time from an arbitrary resume quota.

Selected environment clocks share skipped-time accounting. CPU-active accounting and supervision clocks remain native. Clock hooks are selective: globally replacing every host clock would mix diagnostics, persistence, watchdog and guest responsibilities.

## Native facts and limits

OpenComputers source pin: `8ca336fbeb92d2a29f86f9a658bb9d6bd6f07dbb` (`1.12.2-forge/1.8.9a`). Relevant upstream paths are relative to that source tree:

| Mechanism | Native source | Consequence |
|---|---|---|
| Robot actions | `server/component/Robot.scala`, `Agent.scala` | Execute actual callbacks and resource effects. |
| Machine ticks and dispatch | `server/machine/Machine.scala` | Preserve uptime, direct-call budget reset, power debit, sleep, synchronized calls and asynchronous worker ordering. |
| CPU versus environment clocks | `server/machine/luac/OSAPI.scala`, `ComputerAPI.scala` | CPU time is host execution time; uptime/game date derive from ticks. |
| Worker delay | `src/main/resources/application.conf` | The default delay is 12 ms; scheduling is a minimum, not an OS dispatch guarantee. |
| Saves and file timestamps | `Machine.scala`, `server/fs/Buffered.scala`, `FileInputStreamFileSystem.scala` | Preserve native pause/locking and guest-visible environment timestamps. |
| Background persistence | `common/SaveHandler.scala`, Forge `ChunkIOExecutor`, Minecraft `ThreadedFileIOBase` | An idle Lua machine alone is insufficient to justify a jump. |
| Randomness | Native agent RNG and Lua/data-card facilities | A configured robot wear seed is not whole-world/Lua/random-state replay. |

The supported clock/async hooks and native restrictions define the demonstrated profile. Additional mods, unknown asynchronous participants and arbitrary copied-world behaviors do not inherit a universal fidelity claim.

## Equivalence obligations

For equivalent initial native state and the same relevant environment inputs, execution durations, permitted scheduling and random-state treatment, acceleration should preserve guest-observable action results, world state, signals, timestamps, energy, inventory, wear and files while reducing host waiting.

That argument requires complete work/deadline ownership, atomic quiescence decisions, relevant clock coverage, preserved native transition bodies/locks, and consistent event ordering. Matching example traces do not prove those premises for every workload. Cancellation or a resource-limit abort is an explicit supervisor outcome, never fabricated successful simulation.

## Verification boundaries

Tests cover enqueue/jump races, long worker passes spanning world ticks, zero-delay yields, signals versus sleep, native worker delay, autosave locking, guest clocks, asynchronous completion, cancellation and CPU/tick limits. Use deterministic inputs for algorithm tests and keep native cross-process comparisons separate from coordinator consistency tests.

The measured 48-block comparison matched all 144 action values, seeded wear, final observed blocks, inventory and pose while running faster. Exact timing and energy journals differed near autosave; the strict comparison failed. A native-only repeat also differed at that boundary. This does not explain every acceleration discrepancy or establish unrestricted equivalence. See `README.md` for measured behavior and limitations; detailed test evidence is retained locally.
