# Third-party notices

## What this package contains

The Python runner, the replay viewer, the examples, and the compiled control mod are all MIT-licensed code from this repository. The control mod calls Forge and OpenComputers APIs but doesn't bundle them. The viewer and Python code use no third-party libraries.

The package does **not** include Minecraft, Forge, OpenComputers, OpenOS, Java, Python, curl, Gradle, native Lua libraries, game assets, MCP mappings, or saved worlds. `setup` downloads those from their official sources, and OpenOS is copied out of the downloaded OpenComputers jar at runtime. Don't redistribute an installation or a job folder as if it were covered by this project's MIT license.

## Downloaded at setup

These keep their own licenses. This table is a summary, not a replacement for their license texts:

| Component | Version | License |
|---|---|---|
| Minecraft dedicated server | 1.12.2 | Proprietary Mojang/Microsoft software; [Minecraft terms](https://www.minecraft.net/en-us/terms). Not redistributed. |
| Minecraft Forge / FML | 14.23.5.2860 | LGPL-2.1, except components listed in the jar's `LICENSE.txt`, which explicitly allows mods to link against it. MCP data has separate distribution restrictions. [Source](https://github.com/MinecraftForge/MinecraftForge/tree/1.12.x) |
| OpenComputers / OpenOS | 1.8.9a, source `8ca336fbeb92d2a29f86f9a658bb9d6bd6f07dbb` | MIT; the jar's `LICENSE` and embedded notices cover bundled JNLua, LuaJ, native Lua, and fonts. [Source](https://github.com/MightyPirates/OpenComputers/tree/8ca336fbeb92d2a29f86f9a658bb9d6bd6f07dbb) |
| Log4j API / Core | 2.25.5 | Apache-2.0. Replaces Forge's vulnerable 2.15.0 in the runner's own server copy. [Project](https://logging.apache.org/log4j/2.x/) |
| Akka actor / Typesafe Config | 2.3.3 / 1.2.1 | Apache-2.0 |
| Guava / Gson | 21.0 / 2.8.0 | Apache-2.0 |
| Netty | 4.1.9.Final | Apache-2.0 |
| Commons IO / Commons Lang | 2.5 / 3.5 | Apache-2.0 |
| Maven Artifact | 3.5.3 | Apache-2.0 |
| jopt-simple | 5.0.3 | MIT |
| Trove4j | 3.0.3 | LGPL-2.1 |
| JLine | 3.5.1 | BSD |
| Scala, ASM, LaunchWrapper, LZMA, vecmath | see `runtime-profile.json` | Their own embedded notices |

`runtime-profile.json` records the exact files, sizes, hashes, and download sources.

## Build-only dependencies

Building from source also uses Gradle 4.9, ForgeGradle 3.0.197, Artifactural 1.0.13, legacydev 0.2.3.1, MCP stable39-1.12, and JUnit 4.13.2. None of them ship in the package.
