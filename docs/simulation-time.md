# How acceleration works

A normal Minecraft server spends most of its time sleeping: it runs a tick, then waits until 50 ms have passed before running the next one. OpenComputers adds its own waits on top of that, resuming each Lua coroutine no sooner than 12 ms after it yields. For a robot program, most real time goes to those waits, not to actual work.

The accelerator removes the waiting and keeps the work. Every world tick still runs, in order. Action delays, power use, charging, tool wear, and autosaves all happen exactly as natively. The difference is that when nothing is ready to run, the clock jumps ahead to the next thing that is, instead of sleeping until then.

## Three clocks

The runner keeps three kinds of time separate:

1. **Simulation time**: world ticks, OC's worker-delay deadlines, and the clocks Lua can see (`computer.uptime()`, `os.time()`, file timestamps). This is the clock that jumps.
2. **CPU time**: how long Lua and native code actually take to run. This never jumps. Long Lua work stays asynchronous, so world ticks keep happening during it, just like in the real game.
3. **Host time**: real wall-clock time, used for cancellation, timeouts, watchdogs, and cleanup. This never jumps either.

Mixing these up would break things. For example, a global fake clock would make OC's watchdog think code ran instantly.

## When the clock is allowed to jump

Only when everything is idle: no Lua is running or due to run, no tracked background work (like a pending file write) is outstanding, and the next deadline is known. A task that's due but waiting for a worker thread counts as busy, not idle.

When it jumps, it skips to the earlier of the next worker deadline and the end of the server's sleep, and credits the skipped time exactly once. A Lua coroutine that yields with zero delay counts as runnable, so it can't be used to manufacture free time.

## Modes

Schema-3 scenarios default to `coordinated` (accelerated), with OC's normal 12 ms worker delay. `baseline` runs at native speed for comparison. `paced` uses the accelerator's scheduling without the jumps, which is useful for debugging. Setting the worker delay to 0 is allowed but changes OC's behavior, and it isn't needed for acceleration.

## Where the code lives

All under `src/main/java/ocelot/spike/`:

- `RunnerScheduler.java`: owns the time accounting and decides when a jump is safe.
- `RunnerAsyncWork.java`: tracks background work. Pending native file writes block jumps.
- `Pacing.java` and `PacingTransformer.java`: hook the scheduler into the server's clock and OC's dispatch. Tests check the hook counts against the real downloaded classes.
- `RunnerRuntime.java`: world and robot lifecycle. `RunnerHardware.java` builds robots through OC's native assembler.
- `RunnerObservations.java`: samples state for the replay. It doesn't touch time.

The Python side (scenario, jobs, supervisor) handles input validation, process ownership, real-time limits, and cleanup.

The Java package is still named `ocelot.spike` for compatibility. It doesn't depend on any other repository.

## The relevant OpenComputers code

From OC source `8ca336fbeb92d2a29f86f9a658bb9d6bd6f07dbb` (`1.12.2-forge/1.8.9a`):

| What | Where | Why it matters |
|---|---|---|
| Robot actions | `server/component/Robot.scala`, `Agent.scala` | Real callbacks with real costs |
| Machine ticks | `server/machine/Machine.scala` | Uptime, call budgets, power use, sleep, and synchronized calls |
| CPU vs. game clocks | `server/machine/luac/OSAPI.scala`, `ComputerAPI.scala` | CPU time is real time; uptime and game date come from ticks |
| Worker delay | `src/main/resources/application.conf` | 12 ms by default, and only a minimum |
| Saves and file timestamps | `Machine.scala`, `server/fs/Buffered.scala`, `FileInputStreamFileSystem.scala` | Save locking and timestamps Lua can see |
| Background saving | `common/SaveHandler.scala`, Forge `ChunkIOExecutor`, Minecraft `ThreadedFileIOBase` | Why an idle Lua machine alone isn't enough to allow a jump |
| Randomness | Robot RNG, Lua and data-card randomness | The robot seed only covers tool wear, not the whole world |

## How close is it to native?

If everything above holds, an accelerated run should produce the same action results, world state, energy, inventory, tool wear, and files as a native one, just faster.

In the 48-block mining comparison, all 144 action results matched, along with tool wear, the final blocks, inventory, and robot position. Exact timing and energy differed slightly around an autosave, but two plain native runs also differ from each other there. Programs that depend on precise timing or randomness should still be checked against a `baseline` run.

Tests cover the tricky cases: races between scheduling and jumping, long Lua work spanning world ticks, zero-delay yields, signals vs. sleep, autosave locking, guest clocks, background work, cancellation, and limits.

Other mods may add background work the scheduler doesn't know about, so this only covers the supported Minecraft/Forge/OC versions.
