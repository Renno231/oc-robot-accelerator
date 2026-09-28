# Changelog

## Standalone OC Robot Accelerator — unreleased

- Independent repository with source, tests, examples and build tooling at its root; no Harness checkout or runtime dependency.
- Existing `robot-runner` launchers and scenario/native identifiers remain compatible.
- Foreground maximum-deadline validation handles floating-point roundoff without increasing the 90,000-second limit.
- Standalone mining programs, worlds and raw evidence stay local; only small demonstration/test fixtures ship.
- Build and safe-use guidance are consolidated in README. Detailed test reports and raw evidence remain local.

## 0.1.0-rc.2 — local configurable accelerated candidate

Implementation, independent review and scoped Windows/Linux integration verification completed on 2026-09-27. Locally packaged; no corrected release has been published.

- Schema 3 defaults to accelerated idle compression with the native 12 ms worker-delay profile. Native world ticks, asynchronous Lua computation, action rules, autosave, power and durability remain active. Explicit native (`baseline`) and nonaccelerated coordinator (`paced`) references remain available.
- Real assembler-validated CPU, RAM, card, upgrade, container and HDD configuration; editable tier-1/2/3/creative presets and overrides. Runner boot media occupies actual hardware slots/capacity.
- Configurable experience-upgrade level/raw XP, native creative robots, and finite robots charging through native infinite creative sources.
- Optional robot RNG seed for controlled wear comparisons; not deterministic whole-world replay.
- `init` and both mining examples use schema 3. Existing schema-1/2 inputs retain their old hardware and execution defaults.
- Recording avoids rebuilding unchanged block JSON while preserving full sampling and coverage semantics.
- Windows subprocesses use explicit hidden/detached console policies, with captured build/runtime output preserved.

See [README](README.md) and [SCENARIO](SCENARIO.md) for the current contract and measured results. The earlier readiness claim is withdrawn; retained historical evidence is not relabeled as verification of these changes.

## 0.1.0-rc.1 — historical local candidate, readiness withdrawn

Extracted-package setup, real baseline robot execution, replay export, diagnostics and cleanup have passed on Windows and in a fresh nonroot Linux container. Native offline HTML viewing was checked in Chromium on Windows. This is a candidate for the declared single-robot profile, with experimental acceleration; no general parity certification.

- Scenario-driven actual Minecraft 1.12.2 / Forge 14.23.5.2860 / OpenComputers 1.8.9a robot execution with real OpenOS programs and file I/O.
- Version 2 baseline defaults, bounded longer jobs, explicit retained-prefix recording; version 1 scenario compatibility retained.
- Frozen inputs, foreground/background execution, cancellation, assertions, guarded recovery/cleanup and bounded diagnostic export.
- Prebuilt-package setup/doctor, exact runtime-library profile with verified Log4j 2.25.5 provenance, Windows/POSIX launchers.
- Self-contained offline sampled map/replay with height slices, timeline, robot state, console and coverage information.
- Small and cross-chunk mining examples; experimental coordinated acceleration with documented timing/resource divergences.

Public scope: trusted local inputs, one robot, fixed tier-3 preset, pinned base profile. No arbitrary modpack support, live viewer, deterministic world replay or universal accelerated-parity claim. See README for current platform/evidence status and safe-use limitations.
