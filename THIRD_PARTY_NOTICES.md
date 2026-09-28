# Robot Runner third-party notices

## What the public package contains

The runner's Python CLI, viewer, examples and compiled `ocelot.spike` control mod are first-party Ocelot Harness code under the repository's MIT license. The control mod links to Forge/OpenComputers APIs; it is not a shaded distribution of those libraries. The release packager must verify the JAR entry allowlist and include `LICENSE`. The viewer uses browser APIs without a third-party JavaScript library. Python uses the standard library.

The package does **not** include Minecraft, Forge, OpenComputers, OpenOS, Java, Python, curl, Gradle, native Lua libraries, game assets, MCP mappings, saved worlds or dependency caches. Setup acquires the pinned runtime from its upstream distribution locations. OpenOS and robot-component files are seeded from the acquired OC artifact at runtime, not copied into this package. Do not redistribute generated installations or job runtime trees as if they were this MIT-licensed tool.

## Separately acquired runtime

Upstream terms continue to apply to downloaded software and its embedded components. The following identifies principal components, not a replacement for their license texts:

| Component | Version/profile | License/source basis |
|---|---|---|
| Minecraft dedicated server | 1.12.2 | Proprietary Mojang/Microsoft software; [Minecraft terms](https://www.minecraft.net/en-us/terms). Not redistributed. |
| Minecraft Forge / FML | 14.23.5.2860 | LGPL-2.1 except components identified in the acquired JAR's `LICENSE.txt`. That text explicitly permits ordinary Java mod linkage without applying Forge's license to the mod. MCP data has separate non-transitive distribution restrictions. [Source](https://github.com/MinecraftForge/MinecraftForge/tree/1.12.x). |
| OpenComputers / OpenOS | 1.8.9a, source `8ca336fbeb92d2a29f86f9a658bb9d6bd6f07dbb` | MIT for principal code; acquired JAR's `LICENSE` and separate embedded notices govern bundled JNLua/LuaJ/native Lua/fonts/other components. [Source](https://github.com/MightyPirates/OpenComputers/tree/8ca336fbeb92d2a29f86f9a658bb9d6bd6f07dbb). |
| Log4j API / Core | Effective 2.25.5 | Apache-2.0, declared in exact Maven POMs and acquired JAR notices. Replaces the two Forge-manifest-selected 2.15.0 files **only in owned execution copies**. [Project](https://logging.apache.org/log4j/2.x/). |
| Akka actor / Typesafe Config | 2.3.3 / 1.2.1 | Apache-2.0, exact POM declarations. |
| Guava / Gson | Minecraft metadata: 21.0 / 2.8.0; classes embedded in server | Apache-2.0, exact release POM declarations. |
| Netty | Embedded metadata 4.1.9.Final | Apache-2.0, exact Netty-all POM declaration; bundled native/components have their own notices. |
| Commons IO / Commons Lang | Minecraft metadata: 2.5 / 3.5; classes embedded in server | Apache-2.0, exact POM/parent declarations. |
| Maven Artifact | 3.5.3 | Apache-2.0, POM/parent and JAR notices. |
| jopt-simple | 5.0.3 | MIT, exact POM declaration. |
| Trove4j | 3.0.3 | LGPL-2.1, exact POM declaration. |
| JLine | 3.5.1 | BSD as declared in exact POM. |
| Scala family, ASM, LaunchWrapper, LZMA, vecmath | Exact versions in `runtime-profile.json` | Acquired upstream libraries; licensing details are not fully resolved by POM metadata. Preserve their embedded notices and upstream distribution context. Not bundled in this package; no independent redistribution grant is asserted. |

`runtime-profile.json` records exact pristine artifact sizes, SHA-256s and acquisition origins. Effective logging artifacts are pinned in `runtime_profile.py`; job reports distinguish original from effective identities. Exact versions are compatibility inputs, not statements that a dependency is maintained or vulnerability-free. See the safe-use notes in `README.md`.

## Developer-only dependencies

Source builds additionally use Gradle 4.9, ForgeGradle 3.0.197, Artifactural 1.0.13, legacydev 0.2.3.1, MCP stable39-1.12 and JUnit 4.13.2, with Forge's legacy development graph. They are not necessary to run a prebuilt package and are not included in it. Source builders obtain them through their upstream repositories under the applicable terms. This runtime/package review is not an exhaustive security or licensing certification of the developer build graph.
