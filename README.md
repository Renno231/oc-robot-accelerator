# OC Robot Accelerator

Run OpenComputers robot programs faster than real time in actual Minecraft 1.12.2 worlds, inspect their results, and replay sampled world changes in a browser. Acceleration removes idle host waiting while native world ticks, robot actions, power and durability still execute.

This is an independent project. [Ocelot Harness](https://github.com/Renno231/ocelot-harness) controls the separate Ocelot Brain emulator; it is not a dependency. The command-line launcher is `robot-runner` (`robot-runner.cmd` on Windows).

**Configurable accelerated simulation — local candidate `0.1.0-rc.2`.** New scenarios use schema version 3 and accelerated execution by default. Hardware is a native assembler-validated recipe, supplied directly or through editable presets. The corrected runtime has passed source, real-server and extracted-package checks on the profiles below. This is a locally packaged candidate; no public release has been uploaded.

## Requirements and supported scope

- Python **3.11 or newer**, `curl` on PATH, and a current maintained **64-bit Java 8** runtime. Public-package setup does not require a JDK, Gradle, SBT, Minecraft client, or graphical desktop.
- Internet access during setup for pinned upstream dependencies; jobs disable OC HTTP/TCP and bind game networking to loopback only. A job permits up to a 2 GiB Java heap, plus Python, native/runtime and file-cache overhead.
- Minecraft **1.12.2**, Forge **14.23.5.2860**, OpenComputers **1.8.9a**. Effective logging profile uses verified Log4j API/Core **2.25.5**. Setup checks exact artifact hashes; this is a supported-profile boundary, not a general modpack loader.
- One robot with configurable tier (1–3 or creative), CPU, memory, cards, upgrades, containers and native HDDs. Editable presets are starting points, not restrictions. Experience upgrades support initial level or raw XP. Position, facing, tool, inventory and energy are configurable. Finite robots can recharge through native chargers connected to empty creative power cases. Additional gameplay mods, multiple robots and other loaded OC hosts are unsupported; racks (even empty) and drones are rejected.
- Use trusted local Lua programs and closed world copies under an ordinary nonprivileged account. This old game runtime is **not an OS sandbox**. See the safe-use notes below and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

### Safe local use

Run under an ordinary nonprivileged account with maintained Java/Python, trusted Lua programs and trusted closed world copies. Do not expose this as a public or multi-tenant execution service, share writable installations/jobs with untrusted users, or add arbitrary mods/JVM debug options and assume the supported profile still applies. Jobs inherit your account's permissions. Loopback binding is not OS-level network isolation.

Path checks, immutable input copies, hashes and finite budgets protect lifecycle and integrity; they are not a sandbox, compressed-world decompression defense, or hard memory/disk quota. Review diagnostics/replays before sharing: they can contain program output, local paths and inventory data. Hashes detect drift, not the trustworthiness of an unknown download.

The execution profile overlays Log4j API/Core 2.25.5 in owned runtime copies. The acquired upstream template retains older dependencies: do not launch that template directly and treat it as a hardened server. Other old libraries and native code remain. A point-in-time dependency review is not a guarantee against undiscovered or future vulnerabilities; reassess the exact profile before a public release. Report problems with a minimal reproduction, without posting private worlds, credentials or sensitive logs.

### Verified package environments

The engine's pre-extraction candidate completed setup, doctor, initialization, an accelerated schema-3 robot run, replay export, diagnostics and guarded cleanup on both profiles. These are historical platform results, not a fresh standalone release certification.

| Environment | Evidence and scope |
|---|---|
| Windows 10 x64, Python 3.12.2, Temurin 8u382 Java executable | Fresh package/installation on an existing host, using Java from a JDK installation; setup used no compiler, Gradle or source dependency caches |
| Linux x64, Debian/glibc 2.41, Python 3.12.14, Temurin 8u502 | Fresh nonroot container with no source/dependency caches; no display or published ports |
| Offline viewer | Current Node interaction regressions and replay export on both platforms; native Chromium 153 `file://` checks were performed during the earlier candidate, with unchanged viewer assets |

These checks do not establish every OS distribution/browser, a clean Windows machine, or macOS support. Other environments are unverified.

## Quick start from an extracted package

Verify the ZIP against its adjacent `.sha256` file, then extract it. Keep the package, installation, scenario and jobs directories separate. Use new directories you own. **On Windows use a short jobs path**, such as `C:/or/jobs`, because Java 8 libraries can encounter legacy path-length limits.

Windows PowerShell, from the extracted directory:

```powershell
.\robot-runner.cmd setup --installation C:/or/install --java "C:/path/to/java8/bin/java.exe" --accept-eula
.\robot-runner.cmd doctor --installation C:/or/install
.\robot-runner.cmd init C:/or/mining
.\robot-runner.cmd validate C:/or/mining/scenario.json
.\robot-runner.cmd run C:/or/mining/scenario.json --installation C:/or/install --jobs-root C:/or/jobs
```

POSIX shell:

```sh
sh ./robot-runner setup --installation "$HOME/or/install" --java /path/to/java8/bin/java --accept-eula
sh ./robot-runner doctor --installation "$HOME/or/install"
sh ./robot-runner init "$HOME/or/mining"
sh ./robot-runner validate "$HOME/or/mining/scenario.json"
sh ./robot-runner run "$HOME/or/mining/scenario.json" --installation "$HOME/or/install" --jobs-root "$HOME/or/jobs"
```

Replace the Java placeholder with the actual Java 8 executable. `--accept-eula` records your acceptance of the applicable Minecraft EULA for the local server installation. Setup acquires upstream runtime artifacts locally; this package contains only first-party tool code and its control mod. The launchers use `python` on Windows and `python3` on POSIX. Set `ROBOT_RUNNER_PYTHON` to a specific Python executable when necessary, or use `python runner.py ...` directly.

Setup defaults to a 900-second limit (`--timeout` accepts 30–1800). It publishes readiness only after verification. An intact ready installation is reusable; an incomplete or modified installation is preserved and refused. Inspect `installation.json` and `setup.log`; retry into a new owned directory after diagnosing the problem. `doctor` is read-only: it checks Java and artifacts without downloads or a server boot. Upstream download failures are errors, never silently accepted substitutions.

`init` requires a new directory and copies the accelerated mining example plus four editable hardware presets (`tier1`, `tier2`, `tier3`, `creative`). Its `scenario.json` explicitly selects `hardware/tier3.json`; edit that file, choose another, add overrides, or supply a complete hardware recipe. See [hardware configuration](SCENARIO.md#configurable-hardware-schema-version-3), [experience upgrades](SCENARIO.md#experience-upgrade-state) and [infinite-source chargers](SCENARIO.md#creative-robots-and-infinite-source-chargers).

The example mines four stone blocks, returns home, prints progress, and writes `report.txt`. The sibling `miner.lua` module and `distance.txt` demonstrate ordinary OpenOS `require` and file I/O. Edit the program and [scenario](SCENARIO.md), including its final expectations, for your own work. A larger 48-block, multi-chunk example is included at `examples/cross-chunk/`; copy its entire directory to a new scenario location before editing.

## Programs and completion

The Lua entry file runs on actual OpenOS with working directory `/home/program`. Its directory is copied onto a writable emulated disk; reads/writes do not mutate the original input files. Returning from the entry file records completion and shuts down the robot. Success requires the machine to be actually stopped, final assertions to pass, and the server process to exit with successful supervisor cleanup. A Lua error, resource limit, or explicit computer shutdown before returning is not a successful return. Infinite/service programs need deliberate limits or cancellation.

Every job freezes input copies and hashes before launch, then uses a separate writable runtime. Repeating a scenario creates fresh setup or a fresh copy of `world.source`; previous runtime changes are not reused automatically. This restores declared inputs, **not exact RNG/worker state** and not an in-place rewind.

## Foreground and background jobs

Successful commands emit one bounded JSON value on stdout; runtime logs stay in files. Nonzero exit means a command/runtime failure, cancellation, or unavailable status. `--help` prints usage. Use the returned 32-character hexadecimal `jobId` in subsequent commands:

```text
robot-runner.cmd run C:/or/mining/scenario.json --installation C:/or/install --jobs-root C:/or/jobs --detach
robot-runner.cmd status JOB_ID --jobs-root C:/or/jobs
robot-runner.cmd wait JOB_ID --jobs-root C:/or/jobs --timeout 600
robot-runner.cmd cancel JOB_ID --jobs-root C:/or/jobs
robot-runner.cmd inspect JOB_ID --jobs-root C:/or/jobs
```

On POSIX substitute `sh ./robot-runner`. Detached jobs are owned by an independent worker, not the agent or shell that requested them. Detach returns after worker acknowledgement. Foreground Ctrl+C requests cancellation and waits boundedly for status; `wait` timeout alone does **not** cancel. One jobs root admits one server; separate roots are independent and consume separate resources.

Unavailable metadata or a missed heartbeat is **not proof that Java stopped**. A crashed worker deliberately retains admission; see recovery below. No automatic stale-PID killing occurs.

## Observe and replay

```text
robot-runner.cmd observations JOB_ID --jobs-root C:/or/jobs
robot-runner.cmd view JOB_ID --jobs-root C:/or/jobs --output C:/or/replay.html
robot-runner.cmd diagnostics JOB_ID --jobs-root C:/or/jobs --output C:/or/diagnostics.zip --include-observations
```

Open the new HTML file in a modern browser. It is self-contained and offline: top-down height slices, changed blocks, robot path/orientation, energy/inventory, scrub/step and 1/10/100× playback. Opening or playing it cannot change simulation behavior. Console is a labeled tail and final results are separate from the sampled timeline. This increment exports recordings; it has no live viewer.

Recordings include an initial region snapshot and sampled deltas, not every event, entity, block-entity NBT, or transient change. Scenarios v2/v3 default to retaining a complete prefix when the byte budget fills while simulation continues. The viewer ends at the last retained sample; it never extends that state across missing time. Missing final samples, coverage status, sampling cadence and display-only trail thinning are explicit. Viewer reconstruction has additional finite record/cell bounds and can refuse a large recording even if it fits the recording's byte budget. See [SCENARIO.md](SCENARIO.md).

HTML/diagnostic files may contain console output, inventory or local paths. Review before sharing. Diagnostic archives exclude program source, worlds, binaries and ownership tokens; logs are **not automatically secret-redacted**.

## Inspect, recover and clean up

`inspect` is read-only. After a worker crash, independently verify that its worker, Java server and descendants have ended. Only then request guarded recovery:

```text
robot-runner.cmd recover JOB_ID --jobs-root C:/or/jobs --confirm-processes-stopped
robot-runner.cmd cleanup JOB_ID --jobs-root C:/or/jobs --confirm-delete-runtime
```

Recovery additionally requires valid ownership metadata and two local process checks. Live/reused PIDs or uncertain process visibility are refused; it never kills a PID or rewrites an original failure as success. A failed maintenance operation leaves a visible `.maintenance` marker for manual inspection, not automatic reclaim. Operator confirmation remains necessary because snapshots cannot prove arbitrary descendant absence. Run recovery/cleanup directly from your shell: a still-running Python/Java wrapper whose command line includes the job ID or job directory can conservatively count as a matching process and block mutation. Inspect the reported process before retrying; do not bypass the ownership guard.

Export useful results first. Cleanup removes only that inactive job's writable `runtime/`, preserves frozen inputs/metadata/installation, and refuses links or unsafe ownership. Interrupted deletion leaves an explicit `cleanup.json` state. Run directories are retained until explicit cleanup; installations and shared caches are never silently deleted.

## Files and limits

A job directory contains `inputs/` (pristine scenario/program/world), `job.json`, owned launch metadata and `runtime/`. Runtime artifacts include `result.json`, `supervisor.json`, `runtime-logging.json`, `observations.ndjson`, `observations-status.json`, `program.log`, stdout/stderr and hashes of seeded files. With version 3, user-created disk files reside under the copied world's `opencomputers/<native-boot-drive-address>/home/program/`; the address is generated for each job. Versions 1/2 use `opencomputers/robot-runner-disk/home/program/`. Buffered native HDD files are persisted by native save/close; inspect them after the job ends.

Scenarios v2/v3 support up to 1,728,000 ticks (24 simulated hours) and 90,000 wall seconds, with smaller defaults. These are ceilings, **not evidence of 24-hour parity or throughput**. Programs/worlds, setup, logs, recording, exports and process cleanup have separate caps. Limits are polling bounds, not OS quotas. The observed region bounds setup/capture, not robot movement or an execution cage.

## Fidelity and performance

Version-3 `coordinated` execution removes idle wall-clock waiting, not native simulated work. It preserves complete world ticks, autosave, action delays, power and wear rules. Native workers run asynchronously: Lua computation does not freeze world time. Tracked background work prevents an unsafe idle jump, and guest environment clocks include skipped waiting. The native 12 ms scheduling profile remains the default; selecting 0 changes that profile and is not necessary for acceleration. `baseline` is the explicit native-speed reference; `paced` is the coordinator without idle jumps.

A current seeded 48-block, three-chunk-boundary mining comparison took **94.58 s native versus 18.49 s accelerated** during fixture execution (**5.1×**), and **111.70 s versus 35.75 s** for complete jobs (**3.1×**). All 144 action return values, seeded wear, final observed blocks, inventory and pose matched. Exact action timing and energy did not (2.5 energy difference at work completion). A matched native-only repeat also differed in timing/energy around autosave: exact journal equality is not inherently guaranteed by native scheduling. These records do not establish that every discrepancy is explained, nor a universal parity or speed guarantee.

Configured hardware, XP effects, creative robots and finite-robot charging use native engine behavior. Your own CPU-heavy, random or timing-sensitive workload needs measurement; arbitrary modpacks and external inputs are unsupported. Strict startup/progress watchdogs can also abort a job before its program runs; inspect the reported outcome rather than treating every stopped job as completion. Detailed test runs and diagnostic reports remain local.

## Development and evidence

Source checkout: build the first-party control mod with a Java 8 **JDK** before using source-mode setup:

```text
python verify.py --checks source --java-home "C:/path/to/jdk8" --output PATH_TO_NEW_EVIDENCE
python package_release.py --version 0.1.0-rc.2 --output PATH_TO_NEW_ZIP
```

The output's parent must already exist. Packaging is offline, allowlisted and deterministic for identical inputs; it includes a per-file `release.json` and adjacent SHA-256 checksum. It does not run Gradle or copy game dependencies. `bootstrap.py --prepare-server` and developer `run --template/--control-jar/--java` remain available; public usage should prefer verified installations.

The developer-only `verify.py` is the canonical runner verification entrypoint. Its default `source` profile runs Python tests, Java tests/build, viewer interaction tests and deterministic packaging. It requires Node as well as the Java 8 JDK. Explicit `runtime`, `package` and `viewer` profiles run the existing real-server suite, fresh extracted-package workflow and browser suite respectively; use `--help` for required inputs. Verification writes commands, bounded-time step outcomes and logs into a new evidence directory. Runtime checks retain worlds for inspection; export evidence before explicit cleanup. All commands run from this repository root; no Harness checkout is required.

Raw evidence archives, saved worlds and standalone user mining programs remain local and excluded from Git/packages. Only small accelerator demonstration/test programs are included. Read [CHANGELOG.md](CHANGELOG.md) for release status. The timing architecture is documented in `docs/simulation-time.md`. Keep changes covered by behavior-level tests, preserve native timing/resource/security bounds, and inspect staged files and release ZIPs for private inputs before publishing.
