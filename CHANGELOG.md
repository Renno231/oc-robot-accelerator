# Changelog

## Unreleased

- Split out of Ocelot Harness into its own repository. Nothing here depends on the harness, and existing scenarios and `robot-runner` commands keep working.
- Fixed a rounding bug when validating the maximum foreground run deadline.

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
