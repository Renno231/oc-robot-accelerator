# Full-build simulation fixtures

Use a version-3 `world.fullBuild` fixture for a complete construction workload.
Construction bounds are separate from `world.region`, which controls sampled
observations. A small observation region does not crop the construction or its
final verification. The explicit execution tick budget can exceed the legacy
24-hour ceiling; its representation is a positive Java integer.

```json
{
  "min": [0, 65, 0],
  "max": [203, 137, 199],
  "expected": "expected-world.bin.gz",
  "palette": ["minecraft:air", "minecraft:stone"],
  "chest": [-2, 65, -3],
  "materials": [{"item": "minecraft:stone", "count": 1013113}]
}
```

This abbreviated palette illustrates the interface, not the island's material
mapping. Put the object under `world.fullBuild`. Declare the chest as a normal
`minecraft:chest` setup block within the observation region. The expected file
is a scenario-program-relative gzip stream of unsigned one-byte palette IDs in
Y/Z/X order, X fastest, with exactly one byte per construction-volume cell.
Prepare it independently from the source schematic, retaining source and artifact
hashes. Final native verification streams every byte and compares the actual
Minecraft block registry ID, including expected air. Current verification covers
registry IDs; oriented/block-state properties require a richer expected encoding.

Workspace setup clears the construction volume and one-block exterior, including
the bounding envelope to the declared observation/service region, and supplies a
floor immediately below its base. Setup is incremental across server ticks so
large volumes do not monopolize a tick or trip Minecraft's watchdog. Source blocks
are not pre-placed. Construction and service chunks remain forced using multiple
native Forge tickets. Forge's actual ticket policy still governs available tickets.

The bulk fixture is finite backing for a real 27-slot chest. Each material has an
explicit total count; available native stacks remain within ordinary item limits.
Refilling transfers material from that budget into chest slots. Robots withdraw
through the ordinary OC inventory controller; robot inventory and energy are not
injected or enlarged. The backing budget persists for the lifetime of one run.
Saved-world recovery reconciles it against independently verified construction.

Declare `returnSlots: 1` inside `world.fullBuild` to reserve one of the real
chest's 27 slots as a return bay. Ordinary native inventory-controller transfers
can return surplus materials there. The fixture removes those actual stacks into
the finite backing budget before refilling supply slots; it does not duplicate
items or enlarge inventories. Only declared materials with matching metadata are
accepted. The default of zero preserves supply-only fixture behavior. Normal
storage without available return space must report that it is full.

## Builder hardware

Select `"robot": {"hardware": "builder-max", ...}` for builder workloads.
The survival recipe uses a tier-3 CPU, two RAM6 modules, HDD3, four inventory
upgrades, inventory controller, Angel, Hover2, level-30 experience, and two tier-3
batteries (one in a tier-3 upgrade container). Native assembly validates slot
compatibility and complexity before creating the robot. The pinned configuration
uses 31/32 complexity, exposes 64 inventory slots, and has 210,500 energy capacity.
The remaining complexity point cannot accommodate another upgrade container.

`hardware-preflight.json` records native validation, the resolved recipe, creative
robot status, complexity budget, inventory capacity, and energy capacity before
boot. Standard builder components also receive an early host complexity check.
Custom components/settings remain subject to the native assembler; survival
assembly limits have no bypass. Creative robot hardware requires the explicit
`tier: "creative"` setting. Label constrained hardware tests by purpose.

Keep actual OC constraints visible. Default robots have an eight-block flight
height; native hover upgrades extend it to 64/256 blocks. The 73-layer island's
overhead service route uses `hoverupgrade2`, while retaining tier-3 RAM and a finite
battery charged by a real OC charger. Inspect native failures before substituting
hardware or changing movement behavior.

The island fixture's native charger is powered by an explicitly declared empty
creative case. This is a supplied-power test fixture: the robot itself has normal
survival assembly limits, finite batteries, and ordinary charging/movement costs.

## Saved-world recovery

Declare `world.source` and add an explicit recovery description:

```json
"resume": {"robot": [151, 78, 43], "builtBlocks": 367543}
```

Put this object inside `world.fullBuild`. The source world is copied into an owned
run. The fixture requires an actual native OC robot at the declared replacement
position, reclaims its carried materials and chest stock, and removes that proxy.
Construction blocks remain untouched. Incremental native verification checks every
source-volume cell, rejects foreign blocks, verifies the declared construction
count, and subtracts existing construction from the original finite material
budget. `full-build-recovery.json` records preserved construction and reclaimed
stock. Resident stock must fit within the remaining original material budget.

Prepare a source-verified work-prefix cursor before resuming the guest. A saved
checkpoint can lag already-built geometry; account for those blocks as verified
existing construction. Verify that the recovery stance is clear. A full-build
robot may start within its construction bounds plus the one-block working exterior;
that permission leaves the observation region unchanged. The independent final
full-volume verifier remains mandatory for recovered runs.

Evidence is `full-build-verification.json` in the native runtime directory. Passing
requires zero mismatches across the complete volume, along with the scenario's
ordinary final assertions. Retain failed attempts, program progress/checkpoints,
and hardware recipes. Region observations alone do not establish full construction.

The island driver runs until the selected catalog finishes and accounts for
1,013,113 source blocks as placements plus verified existing construction before
returning home. Record each generated bundle and native job ID with its evidence.
`private/island8/prepare_full_island.py` freezes source provenance,
the compact robot input, finite supply counts, and independent expected geometry.
