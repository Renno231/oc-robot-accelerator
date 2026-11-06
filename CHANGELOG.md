# Changelog

## Unreleased

- Split out of Ocelot Harness into its own repository. Nothing here depends on the harness, and existing scenarios and `robot-runner` commands keep working.
- Fixed a rounding bug when validating the maximum foreground run deadline.
- Up to eight robots in a schema-4 scenario (was four).
- Robot upgrades from other mods by registry name (`modid:item[:metadata]`), such as Computronics' chat upgrade, with the mod supplied through `ROBOT_RUNNER_EXTRA_MODS`.
- A schema-4 controller case can be creative (`"tier": "creative"`), OC's self-powered case.
- Scenario files up to 512 KiB (was 128 KiB), enough for the supply chests of a big drone build. A program file may take the whole 4 MiB of its folder (was 1 MiB), as a big model file does.
- Regions of any size (was at most 32,768 blocks and 64 chunks). Chunks are forced 16 to a Forge ticket, since Forge drops the first chunks forced past 25 on one ticket.
- No size limits on the observation log, its records or the runtime folder, no 2,048 loaded-chunk limit, and samples can be any number of ticks apart (was 32 MiB, 8 MiB, 2 GiB and at most 200 ticks). `observations.maxBytes` is now optional and sets a limit only when given.
- Drones are sent to players as far as the server sends chunks (OC registers them for 80 blocks), so a camera farther out sees them.
- Background chunk reads and OC saves are never refused. A cap of 4,096 used to kick a viewer that rejoined at view distance 32 ("Internal server error") and could leave a chunk loading forever.

## 0.1.0-rc.2 (not published)

- Acceleration is on by default for schema-3 scenarios. `baseline` (native speed) and `paced` remain available for comparison.
- Configurable robot hardware: CPU, memory, cards, upgrades, containers, and HDDs, checked by OpenComputers' own assembler. Editable tier 1/2/3/creative presets.
- Experience upgrades with a starting level or raw XP, creative robots, and chargers for finite-power robots.
- Optional robot RNG seed for repeatable tool-wear comparisons.
- `init` and the mining examples use schema 3. Schema 1 and 2 scenarios behave as before.
- Faster recording of unchanged blocks.
- No more console windows popping up on Windows.

## 0.1.0-rc.1 (not published)

- First version: runs real OpenOS robot programs on a Minecraft 1.12.2 / Forge / OpenComputers 1.8.9a server, from a scenario file.
- Foreground and background jobs, cancellation, final assertions, recovery, and cleanup.
- Offline HTML replay with height slices, timeline, robot state, and console.
- Small and cross-chunk mining examples, and experimental acceleration.
