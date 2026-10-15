# AGENTS.md

Read this before any work in this repository. It applies to every agent:
the coordinator (Claude) and every worker (pi/GPT).

## What we are building
A playable MES in OpenComputers. It plans with craftsystemv3 and runs the
plan end to end with drones (logistics), robots (crafting) and machines,
on the user's real builds:
- a fully stacked T3 server (4x T3.5 RAM, no creative parts), a T3 screen and
  GPU, UI designed at 160x50;
- robots at OC's maximum inventory (85 slots, two RAM sticks); a fixture with
  less is a fixture bug;
- 6 or more drones; drones, robots, machines and storages scale with need.

It runs on the user's own libraries, stays lean and true to OC, and grows
in-world. Everything serves that end-to-end MES. Nothing is polished in
isolation.

## The first rule
Hold everything against this intent: every report, failure, question, idea
and line of code. Never go along with a framing because it was presented.
Before answering a question, proposing a change or claiming a cause, answer:
1. **What is it for?** Which part of the playable MES does it serve, and is it
   needed at all?
2. **Is the premise true?** Read the code path (or the OC source) first. Say
   what is verified and what is assumed. Never state an assumption as fact.
3. **What is the simplest version that uses what exists?** User libraries,
   one push, one heartbeat.

If you cannot answer all three, do not ask, answer or claim yet. Go and check.

## How the user thinks (decide as they would)
The user thinks from the player standing in front of the build, not from the
code. Every question is about what they would physically do and see:
- which blocks they place;
- what goes on each disk at assembly;
- what they type at the prompt;
- which screen they open and which keys they press;
- what each device then does on its own.

They carry the real lifecycle of every device in their head:
- a tablet gets put away and switches off;
- a robot reboots and loses its RAM;
- a server restarts, and its services must come back through rc;
- drones sit on chargers and announce themselves.

A test exists to exercise the MES. Whatever the MES itself does must run
for real in the test: pairing, announces, rc restarts, pushed state, and
mapping and survey. A harness stand-in there (harness-only messages, direct
library calls, pre-filled address books) proves nothing. Everything around
the MES is staging, and the harness should do it the cheapest way: placing
blocks, building the world, powering it, laying out the stock wall, typing
at a keyboard. Do not spend effort making staging look in-world. A case
that is mostly re-enacting the player has stopped testing the MES.

Their conventions are the same across everything they build. Extend them
without being told:
- everything installs under /usr, the way OpenOS packages do;
- services start from rc scripts;
- devices pair with their pair/hosts libraries and talk over tnet, api and
  pubsub;
- persistence is their store and CBOR;
- no module invents its own way of doing what another module already does.

Most of the existing code, READMEs and fixtures were written by agents, even
under the user's git name. They are not the user's decisions. Where they
deviate from these conventions (drone-logistics once installed to /lib), the
code is wrong; do not adopt it.

In the user's words: "I need you to think like me... make educated guesses."
Do not hand decisions back to the user. Do not adopt the framing of
agent-written code or reports either. Reason out what the user would decide,
decide it, and state the guess with its reasoning so it can be corrected. Ask
only when that reasoning gives no answer. Keep their reasoning in full when
you record or pass it on: "I wouldn't reduce the language because that could
reduce the thinking."

## Design rules
- **Push state, never poll.** Devices publish their state over pubsub. The MES
  reads a device only when something is new or a report disagrees with what it
  expected. There is no read before acting.
- **A heartbeat is a tiny alive message on a fixed rate**, nothing more.
  Anything bigger is slop.
- **No polling loops and no repeating retry timers.** Connect once, when the
  device announces itself. Timers are one-shot, armed for when something is
  actually due.
- **A mismatch is reported, read once, fixed, and retried, then it fails.**
  Logistics, mapping and inventory stay independent.
- **Fix at the cause.** Find the line of our code that triggers a failure
  before touching any library. Fix our usage first.
- **No defensive filler**: no guessed deadlines, caps, extra checks or
  "just in case" retries. Build only for stated, proven requirements, and
  invent no scenarios.
- **No silent reductions.** A simplification is a proof of concept only,
  unless the user allows it.
- **Persistence**: the user's CBOR library; designed state tables; minimal
  filesystem calls; write on transitions only.
- **Use what exists first**: tnet (`setTimeout`, `onError`, `onClose`), api
  (async, keys), pubsub, hosts, pair, store, cbor.
- **No layout defaults.** Never pre-fill faces, directions or counts in the
  user's world.
- **Drones have no collision box.** Read the OC source before claiming any
  physical cause.

## Ownership
- **OC application sources** live in OC-Utilities: `craftsystemv4_mes/` and
  `drone-logistics/`. This checkout's `craftsystem/` and `drone-logistics/` are
  local directory links created by `python bind_oc_sources.py /path/to/OC-Utilities`.
  Commit application changes in OC-Utilities; native harness changes belong here.
- **User libraries** (tnet, api, pubsub, hosts, pair, store, cbor): never edit
  them without asking. The source of truth for tnet and api is
  `C:/Users/Conner/Documents/GitHub/Renno-Programs/tnet`. Copies here are
  byte-synced from it (`craftsystem/tnet-provenance.json`).
- **`craftsystem/usr/lib/mes_ui/` and `ui-lab/`**: Claude only, through the
  `mes-ui-coder` agent. No GPT model touches them.
- **Production fixes from an audit**: the coordinator writes them. Workers
  test, report and fix tests and fixtures.
- **Commits**: only when the user asks.

## Pace
The whole MES should take days, not weeks. Spend time on the MES, not on
ceremony around it.
- A failed native step does not send the run back to step 1. Fix the cause
  and resume from that step, or from staged state just before it.
- A step that has passed is not proved again on every run.
- Prefer several small focused cases run in parallel over one long serial
  case.
- Drive setup through the MES's own API, the calls the UI makes. The UI is
  proved in the ui-lab. Key-driving screens natively is for the few things
  only a screen shows.
- Specs and reports stay short: what changed, what passed, what failed and
  where (file:line).

## Testing and reporting
- **Unit tests** check the contract, not the old mechanism. When a test asserts
  removed behaviour, rewrite it or delete it, and name it in the report.
- **Native runs**: each independent case gets its own headless Minecraft/Forge
  server process, world and `--root`/`--jobs-root`, about 4 cases in parallel.
  Share immutable installation files and dependencies; keep worlds and MES
  state isolated. Keep the same server through a case's steps, with controlled
  restarts only where the case requires them. Use `python run_mes_scenarios.py`
  for the MES manufacturing suite; it stages current canonical source.
  Walk every trip log for senseless trips, retries and unused features before
  calling anything passed. Consider shared-server execution only if measured
  startup or memory costs justify its reset and failure-isolation complexity.
- **Diagnostics** live on the host side: accelerator and runner addons, and
  harness capture. They never run on the OC computers.
- **Reports** say what was verified, what was assumed, and which file:line is
  the evidence. A question to the coordinator states what it is for and what
  the code shows.
