# Coordinated delivery roadmap

Updated September 8, 2026. This is a delivery/status map with actionable issues in
both repositories. Engine, game and art-pack versions need not share tag numbers.
There are no assigned due dates or invented completion percentages.

## Current state

- **Released:** engine v0.2.1; separate game Tree Small 02 source/runtime packs
  `tree-small-02-source-v1.0.0` and `tree-small-02-runtime-v1.0.0`.
- **Implemented, awaiting final integration/acceptance:** candidate `2c32211`
  (repair branch, PR #56) contains devel `fdb16a8` plus asynchronous catalog
  validation, saved-world selection/loading, content acquisition, culling/no-UI and
  rendering repairs, the local-player feet-origin correction, explicit MSVC terrain
  arithmetic, validated source-release inventory, the benchmark camera/time
  ordering fix, the audio-off default and the refreshed public asset inventory.
  Game source and runtime pack tags target `9f3a66d` and `addab429`. None is a
  final verified engine v0.3 release.
- **Merged:** format retirement and optional Blender authoring fixtures/service mock
  are in `devel` (`fdb16a8`). Rendering/integration PR
  [#56](https://github.com/d-addison/luminumbra/pull/56) and promotion PR
  [#55](https://github.com/d-addison/luminumbra/pull/55) remain open at this update;
  #55 is blocked until the expanded scope below is accepted.
- **Verified in a bounded scope:** at `2c32211`, local Debug and ASan each pass all
  1,987 named tests with zero failures/errors/skips; format, public-tree and
  asset-inventory checks pass; the exact source-release rehearsal passes with a
  byte-reproducible SPDX inventory. Published source/runtime pack downloads match
  their pinned archives. Independent Astra/xhigh reviews accepted the bounded
  source corrections. Final native, packaged and integrated checks remain distinct.
- **Expanded before release (owner decision, 2026-09-08):** an unbounded world with a
  16 km view radius including distant cave interiors and edits, distant simulation
  over persistent active regions decided system by system, a measured 60 fps floor on
  two profiles and two displays, and causal closure of the native client hang. The
  accepted contract is [Distant world and distant simulation](distant-world.md);
  its work packages are the new v0.3.0 issues below and are gated by one bounded
  design review, not by the post-release Foundations approval.
- **Not released:** engine v0.3.0. Signed publication, independent release download
  verification and a newly named private preview remain outstanding. Preserve the
  delivered `5daeb03` preview unchanged.
- **Planned:** installed engine SDK, real game extraction and the shared
  UI/tooling/authoring foundation. Game code currently remains in the engine
  repository; the game repository initially supplies content and conversion tools.

An implementation is code present in a revision. Verification identifies the
tested revision, environment, scope and evidence. Merging integrates code into a
branch. Release means published artifacts with independently checked identities.
None of these states substitutes for the next.

## Milestones and ownership

| Coordinated milestone | This repository | Counterpart repository |
|---|---|---|
| [v0.3.0 — Acceptance and release](https://github.com/d-addison/luminumbra-game/milestone/1) | Source/runtime art-pack verification, final canopy conversion/provenance, distant-world scenes, game distant-simulation data and packaged content/save/visual acceptance with audio off. | [Final saved-world/render/content correctness; the expanded pre-release scope (16 km unbounded world with distant cave interiors and edits, persistent-active-region distant simulation, measured 60 fps floor on two profiles, client-hang closure); native/CI acceptance, signed source release, independent verification and new private preview.](https://github.com/d-addison/luminumbra/milestone/1) |
| [Foundations — Engine/game separation and tooling](https://github.com/d-addison/luminumbra-game/milestone/2) | Populated compatibility fixtures; mechanics/state/content extraction; pinned standalone launchers; script/data composition; screens/HUD/diagnostics/tests. | [Installed SDK; lifecycle/schedule/state registration; optional field/behavior modules; script/component authoring; input, commands, inspection/profiling; dependency enforcement.](https://github.com/d-addison/luminumbra/milestone/2) |
| [v0.4.0 — Continuing-world multiplayer](https://github.com/d-addison/luminumbra-game/milestone/3) | Real host/join/reconnect flows; LAN/public/direct/favorites/recent browser; generated animated physical avatars; network AI clients; composed previews and process acceptance. | [Checkpoints/catch-up; first-time authoritative admission; returning-identity and two-established-peer lockstep reconnect; physical avatars; LAN/directory and live transport/fault/load qualification.](https://github.com/d-addison/luminumbra/milestone/3) |
| [v0.5.0 — Environmental audio](https://github.com/d-addison/luminumbra-game/milestone/4) | Soundscape/event integration, authored acoustic tuning and audible packaged acceptance. | [Diffuse RT60 DSP, weather-loop lifecycle, thunder propagation and device-independent decoding/graph acceptance.](https://github.com/d-addison/luminumbra/milestone/4) |
| [v0.6.0 — Dynamic motion history](https://github.com/d-addison/luminumbra-game/milestone/5) | Animated avatar/wildlife fixtures and real gameplay/world-transition history acceptance. | [Previous rendered transforms/bones, history validity, depth disocclusion and reset/resource/performance qualification.](https://github.com/d-addison/luminumbra/milestone/5) |
| [v0.7.0 — Rendering foundation — provisional](https://github.com/d-addison/luminumbra-game/milestone/6) | Composed scene/UI parity, terrain/material/weather/water/long-view acceptance and scalable settings. | [Production backend/capability settings, residual longer-view scope beyond the 16 km v0.3 contract and native Windows/Linux/Proton/hardware qualification.](https://github.com/d-addison/luminumbra/milestone/6) |
| [v0.8.0 — Reconstruction and latency — provisional](https://github.com/d-addison/luminumbra-game/milestone/7) | Effective player settings and representative visual/input workloads. | [Qualified reconstruction, dynamic resolution, latency and prerequisite-gated optional frame generation.](https://github.com/d-addison/luminumbra/milestone/7) |
| [v0.9.0 — Lighting and effects — provisional](https://github.com/d-addison/luminumbra-game/milestone/8) | Game lighting integration and proposed aether visuals, provisionally placed pending architecture review. | [Improved raster lighting, optional hybrid RT/denoising and reusable field-effect interfaces.](https://github.com/d-addison/luminumbra/milestone/8) |

Foundations is dependent on independently verified v0.3 publication **and** the
single implementation-roadmap approval after refreshed source/SDK architecture
review with actual Astra/xhigh. Accepted ownership/authoring direction is recorded
in [Engine/game ownership](engine-game-boundary.md). Roadmap population does not
waive that implementation gate. v0.7–v0.9 remain provisional.

The foundation precedes substantial v0.4 work and does not renumber or reduce its
commitments. Keep authoritative first-time joins, continuing reconnect, strict
two-established-peer lockstep reconnect, discovery/directory/browser, physical
generated avatars, ordinary-protocol AI clients and runnable previews after
completed slices. Public discovery does not itself provide NAT traversal or
imply host migration, matchmaking or private Steam relay availability.

## Limits and acceptance still tracked

- Today surface terrain is finite (approximately 3 km and a 3200 m camera far
  plane), local full-SDF cave residency is bounded (128 m horizontal/64 m vertical),
  far tiles omit caves and player edits, and far-tile persistence is never attached
  at runtime. The accepted v0.3 contract replaces this with a 16 km volumetric
  ladder over an unbounded world; until those slices land and are verified, the
  current limits stand.
- Simulation today ticks every creature and plant regardless of distance, restarts
  the simulation clock at zero on load, anchors weather/wind/aether on the spawn
  point, does not persist creatures and drops dirty chunks on eviction. The accepted
  contract replaces this with persistent active regions, a persisted clock and
  per-system distant policies; until those slices land, the current behaviour stands.
- The native client exit 0xCFFFFFFF (PID 66604, package 2871c72) was a Windows
  Application Hang closed by the operator, not a crash; the hang mechanism is not yet
  established and its closure is a release gate.
- White ground patches, purple shadows and visible stars in the settled
  Default/424242/FOV 110° native capture have separate investigation issues.
  Their causes remain unconfirmed. Tree-only tests do not close whole-scene
  appearance reports. Culling and no-UI fixes retain their separate causal evidence.
- Audio is disabled for v0.3 and its private preview by owner direction; audible
  quality and event coverage are future v0.5 work in a separate workstream. Dynamic-body
  acoustic material classification currently uses Stone.
- GNS compilation does not establish live-peer behavior. Steam private SDK/live
  service and broad NVIDIA/AMD/Intel hardware qualification remain explicit gaps.
  Native Windows, native Linux and Proton require separate results. Resource
  estimates must not be presented as measured total VRAM.
- The intermittent server-load crash retains unresolved cause status. The proven
  Jolt exception-configuration cause of the MSVC catalog failure does not prove a
  shared server-crash cause. The UCRT64 120-second guard stays unchanged.

Software releases remain source-only. Art packs are separately versioned game
content. Private recordings, Steam payloads and private previews remain outside
public packs. Preset revision 6, LMR1 v2, FSD2 payload v3, canonical in-memory
serialization, terrain-quality assertions and default-off policies are preserved;
obsolete-world migration and legacy loading are not planned.

## Work-package index

Each issue records owner, recovery state, remaining changes, dependencies,
acceptance and evidence required for closure. Capability and game-integration
issues link to one another; closing a counterpart does not automatically close
its integration. Visual reports retain reproduction context, expected/observed
behavior, revision/evidence identities, cause status, fix revision and packaged
verification.

### v0.3.0 — Acceptance and release

- [Independently verify the published Tree Small 02 source pack](https://github.com/d-addison/luminumbra-game/issues/1)
- [Independently verify the published Tree Small 02 runtime pack](https://github.com/d-addison/luminumbra-game/issues/2)
- [Document reproducible final canopy conversion and resource costs](https://github.com/d-addison/luminumbra-game/issues/3)
- [Complete packaged content, saved-world and audio-off game acceptance](https://github.com/d-addison/luminumbra-game/issues/4)
- [Compose distant-world acceptance scenes, presets and the edited-world tour](https://github.com/d-addison/luminumbra-game/issues/30)
- [Define game distant-simulation rates, activation data and the region populator](https://github.com/d-addison/luminumbra-game/issues/31)
- [Author performance traversal workloads and profile evidence](https://github.com/d-addison/luminumbra-game/issues/32)
- [Define game item identities for ground objects](https://github.com/d-addison/luminumbra-game/issues/33)

### Foundations — Engine/game separation and tooling

- [Capture populated game compatibility fixtures before extraction](https://github.com/d-addison/luminumbra-game/issues/5)
- [Extract game mechanics, authoritative components and composition](https://github.com/d-addison/luminumbra-game/issues/6)
- [Register game configuration, save/hash/checkpoint and replay/network state](https://github.com/d-addison/luminumbra-game/issues/7)
- [Move authored content and game render/audio integration into the package](https://github.com/d-addison/luminumbra-game/issues/8)
- [Build standalone client/server launchers against a pinned installed engine](https://github.com/d-addison/luminumbra-game/issues/9)
- [Port functional game screens/HUD through shared UI services](https://github.com/d-addison/luminumbra-game/issues/10)
- [Register game commands, inspectors, tests and capture context](https://github.com/d-addison/luminumbra-game/issues/11)
- [Compose game rules and content through supported scripts and components](https://github.com/d-addison/luminumbra-game/issues/29)
- [Distribute content and data packs through approved interfaces](https://github.com/d-addison/luminumbra-game/issues/34)

### v0.4.0 — Continuing-world multiplayer

- [Implement real host, first-time join and reconnect UI flows](https://github.com/d-addison/luminumbra-game/issues/12)
- [Implement LAN/public browser and direct/favorites/recent connections](https://github.com/d-addison/luminumbra-game/issues/13)
- [Generate visible animated player avatars and compose physical movement](https://github.com/d-addison/luminumbra-game/issues/14)
- [Implement seeded network AI-player clients using ordinary admission and inputs](https://github.com/d-addison/luminumbra-game/issues/15)
- [Deliver composed multiplayer slices and end-to-end fault/load previews](https://github.com/d-addison/luminumbra-game/issues/16)

### v0.5.0 — Environmental audio

- [Integrate environmental soundscape and weather/thunder events](https://github.com/d-addison/luminumbra-game/issues/17)
- [Author and validate environmental reverb and soundscape tuning](https://github.com/d-addison/luminumbra-game/issues/18)
- [Verify audible packaged output and event coverage](https://github.com/d-addison/luminumbra-game/issues/19)

### v0.6.0 — Dynamic motion history

- [Supply animated avatar/wildlife motion-history fixtures](https://github.com/d-addison/luminumbra-game/issues/20)
- [Qualify gameplay visibility, teleport and world-transition history resets](https://github.com/d-addison/luminumbra-game/issues/21)

### v0.7.0 — Rendering foundation — provisional

- [Qualify composed scene and UI parity on production backends](https://github.com/d-addison/luminumbra-game/issues/22)
- [Accept material, weather, water and long-view game scenes](https://github.com/d-addison/luminumbra-game/issues/23)
- [Integrate scalable and effective game graphics settings](https://github.com/d-addison/luminumbra-game/issues/24)

### v0.8.0 — Reconstruction and latency — provisional

- [Expose effective reconstruction, resolution and latency choices](https://github.com/d-addison/luminumbra-game/issues/25)
- [Qualify representative game visual quality and input responsiveness](https://github.com/d-addison/luminumbra-game/issues/26)

### v0.9.0 — Lighting and effects — provisional

- [Integrate scalable raster and optional hybrid-RT game lighting](https://github.com/d-addison/luminumbra-game/issues/27)
- [Design and qualify proposed aether motes, currents and crystal effects](https://github.com/d-addison/luminumbra-game/issues/28)

