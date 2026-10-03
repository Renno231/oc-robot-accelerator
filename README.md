# OC Robot Accelerator

Run your OpenComputers robot programs in a real Minecraft 1.12.2 world, several times faster than real time, then watch a replay of what the robot did in your browser.

## Why?

Testing robot programs is slow. A mining script that runs for an hour in-game takes an hour to try, and you have to sit in a world watching it. Emulators like [Ocelot](https://gitlab.com/cc-ru/ocelot) don't help here: they emulate the computer, but a robot needs a world to move through, blocks to dig, tools that wear out, and power to run on.

OC Robot Accelerator runs your program on a real Forge server with real OpenComputers, so mining, movement, inventory, power, and durability all behave natively. Most of a robot's time is spent waiting on action delays and idle ticks. The accelerator skips that waiting without skipping any world ticks.

In one test, a 48-block mining run across three chunk boundaries took **94.6 s natively and 18.5 s accelerated (5.1×)**. All 144 robot actions returned the same results, and the final blocks, inventory, and position matched exactly.

## What you get

- **Real robots**: tier 1–3 or creative, with your choice of CPU, memory, cards, upgrades, containers, and HDDs, validated the same way the in-game assembler would. Editable presets for each tier are included.
- **Real OpenOS**: your Lua program runs as `/home/program` with `require` and file I/O working normally.
- **Configurable start state**: position, facing, tool, inventory, energy, experience level, and chargers for finite-power robots.
- **Background jobs**: start a run, check on it, wait for it, or cancel it from the command line. Output is JSON, so scripts and AI agents can drive it too.
- **Browser replay**: export a self-contained HTML file showing the robot's path, changed blocks, energy, and inventory, with scrubbing and 1/10/100× playback.
- **Clean inputs**: every run starts from a fresh copy of your world and program, so the originals are never modified.

## Status

Release candidate `0.1.0-rc.2`. Verified on Windows 10 and Debian Linux. There's no published download yet, so build from source for now (see below).

Supported profile: Minecraft **1.12.2**, Forge **14.23.5.2860**, OpenComputers **1.8.9a**, one robot per run. Other mods, multiple robots, drones, and racks aren't supported.

## Requirements

- Python 3.11+ and `curl`
- Java 8 (a JDK to build from source)
- Internet access during setup, which downloads the pinned server files and checks their hashes

## Quick start

Build the control mod, then install a local server. Setup downloads Forge and OpenComputers; `--accept-eula` records that you accept the Minecraft EULA for it.

```powershell
python bootstrap.py --java-home "C:/path/to/jdk8"
.\robot-runner.cmd setup --installation C:/or/install --java "C:/path/to/jdk8/bin/java.exe" --accept-eula
.\robot-runner.cmd doctor --installation C:/or/install
```

Create the example scenario and run it:

```powershell
.\robot-runner.cmd init C:/or/mining
.\robot-runner.cmd run C:/or/mining/scenario.json --installation C:/or/install --jobs-root C:/or/jobs
```

On Linux, use `sh ./robot-runner` in place of `.\robot-runner.cmd`. On Windows, keep the jobs path short (like `C:/or/jobs`), because Java 8 struggles with long paths.

The example robot mines four stone blocks, returns home, and writes `report.txt`. Edit `miner.lua`, `scenario.json`, or the hardware preset in `hardware/` to make it your own. There's a bigger 48-block example in `examples/cross-chunk/`. Everything a scenario can configure is in [SCENARIO.md](SCENARIO.md).

## Running jobs

Add `--detach` to run in the background. Each command prints a `jobId` to use with the others:

```text
robot-runner run SCENARIO --installation DIR --jobs-root DIR --detach
robot-runner status JOB_ID --jobs-root DIR
robot-runner wait JOB_ID --jobs-root DIR --timeout 600
robot-runner cancel JOB_ID --jobs-root DIR
```

A run succeeds when your program returns, the robot shuts down cleanly, and the scenario's final checks pass. A Lua error or hitting a limit counts as a failure. Runs are capped at 24 simulated hours.

## Watching the replay

```text
robot-runner view JOB_ID --jobs-root DIR --output replay.html
robot-runner observations JOB_ID --jobs-root DIR
robot-runner diagnostics JOB_ID --jobs-root DIR --output diagnostics.zip
```

Open `replay.html` in any modern browser; it works offline. Replays are sampled, not a recording of every tick, and the viewer marks any gaps. Replays and diagnostics can contain your program's output and local file paths, so look them over before sharing.

## Cleaning up

Each job keeps its runtime folder until you remove it:

```text
robot-runner cleanup JOB_ID --jobs-root DIR --confirm-delete-runtime
```

If a job's worker crashed, check that its Java process is really gone, then run `recover JOB_ID --confirm-processes-stopped` first. The runner never kills processes on its own.

## How accurate is it?

Acceleration skips idle waiting, not game logic. World ticks, autosave, action delays, power, and tool wear all still run natively. Lua keeps running asynchronously, just as in the real game.

Action results, blocks, inventory, and position matched in testing. Exact action timing and energy can differ slightly (2.5 energy over the 48-block run). Two plain native runs also differ from each other around autosave, so treat exact timing as approximate either way. If your program depends on precise timing or randomness, compare against a `baseline` run, which is native speed, no acceleration. [docs/simulation-time.md](docs/simulation-time.md) explains the design.

## A note on safety

Runs execute under your own user account with a real Minecraft server. Only run Lua programs and worlds you trust.

## Development

`python verify.py --checks source --java-home JDK8 --output NEW_DIR` runs the test suite and packaging checks. It needs a Java 8 JDK and Node.js; see `--help` for the runtime, package, and viewer profiles. `python package_release.py --version VERSION --output ZIP` builds a release package. See [CHANGELOG.md](CHANGELOG.md) for history.

## Related

[Ocelot Harness](https://github.com/Renno231/ocelot-harness) does the same kind of scriptable control for OC *computers*, using the Ocelot emulator with no Minecraft needed. The two projects are independent.

## License

MIT. See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
