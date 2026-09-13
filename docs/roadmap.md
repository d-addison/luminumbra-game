# Coordinated delivery roadmap

Updated September 13, 2026. This is a delivery/status map with actionable issues in
both repositories. Engine, game and art-pack versions need not share tag numbers.
There are no assigned due dates or invented completion percentages.

## Current state

- **Integration baseline:** engine `devel` at `945ecd295835a838eed0169ff709e7aabc134fa1`
  and game `main` at `552a26684215542b327a842104864dda14e31652` (verified September 13).
- **Merged implementation:** repair PR [#56](https://github.com/d-addison/luminumbra/pull/56),
  accepted distance contract, hang instrumentation, reversed-Z depth, persisted clock,
  five-tier declaration, render measurements and simulation telemetry. The original
  Blender stack was superseded by merged [#155](https://github.com/d-addison/luminumbra/pull/155).
  These implementations still have the acceptance obligations listed below.
- **Recovery in progress:** UCRT SBOM repository-path failure, ambient SIMD determinism
  [#163](https://github.com/d-addison/luminumbra/issues/163), and the conflicted
  active-region [#161](https://github.com/d-addison/luminumbra/pull/161). The latest
  promotion UCRT job passed 2,245 of 2,250 cases at its recorded merge revision;
  its surface-loading guard and three render-process timeouts remain unresolved.
  Historical results do not qualify a new candidate; discover its tests again.
- **Verification:** later Debug/ASan and native records supersede the failed
  `ff0362b` baseline. Expanded integrated, native and packaged acceptance is
  outstanding; implementation, test evidence and merged state are distinct.
- **Accepted pre-release scope:** five volumetric tiers through 16,384 m, qualified
  within 32 km of the origin; per-system simulation policies over persistent active
  regions; Quality (1.0) and Performance (0.67) at 3840×1600 and 3440×1440.
  Both profiles require p99 frame time ≤16.67 ms; 120 fps remains the reported
  target. The accepted [distance contract](https://github.com/d-addison/luminumbra/blob/945ecd295835a838eed0169ff709e7aabc134fa1/docs/distant-world.md) governs every slice;
  its completed design interview is not a new implementation prerequisite.
- **Remaining runtime implementation:** the tier table alone does not render 16 km;
  the runtime still uses legacy far ranges and a 3,200 m far plane. Telemetry and
  a region ledger alone do not schedule distant simulation consumers.
- **Hang closure:** Windows reported the original `0xCFFFFFFF` application hang
  and the operator closed it. The underlying mechanism remains unproven.
  Instrumentation and successful non-reproductions do not close
  [#127](https://github.com/d-addison/luminumbra/issues/127); the server-load
  incident [#69](https://github.com/d-addison/luminumbra/issues/69) is separate.
- **Publication:** v0.3.0 remains unpublished and promotion
  [#55](https://github.com/d-addison/luminumbra/pull/55) is blocked. Strict promotion
  requires all 15 contexts after expanded acceptance, followed by signed source-only
  publication, independent artifact verification and a newly named private preview.
  Audio stays off; the delivered `5daeb03` preview stays unchanged.
- **Authoring ownership:** generic packages remain in the engine monorepo.
  [#162](https://github.com/d-addison/luminumbra/pull/162) is the Blender identity
  review/undo package; [#165](https://github.com/d-addison/luminumbra/pull/165) is
  optional compiled-prefab consumption. Their branch evidence must be refreshed
  and reviewed before landing. Headless consumption is not graphical qualification.
  Full installed SDK delivery and game extraction retain the post-release
  Foundations approval boundary.

An implementation is code present in a revision. Verification identifies the
tested revision, environment, scope and evidence. Merging integrates code into a
branch. Publication delivers artifacts with independently checked identities.

Engine [#141](https://github.com/d-addison/luminumbra/issues/141) owns budget enforcement and qualification mechanisms; game [#31](https://github.com/d-addison/luminumbra-game/issues/31) owns authored rates, activation data and populator policy. Game [#34](https://github.com/d-addison/luminumbra-game/issues/34) retains future content/data distribution and optional non-Steam loading. All v0.4 commitments remain assigned.

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

Full installed SDK delivery and game extraction in Foundations depend on
independently verified v0.3 publication **and** the single implementation-roadmap approval after refreshed source/SDK architecture
review with actual Astra/xhigh. Accepted ownership/authoring direction is recorded
in [Engine/game ownership](engine-game-boundary.md). Roadmap population does not
waive that implementation gate. The already-authorized bounded optional authoring
packages above may be refreshed and qualified before release. v0.7–v0.9 remain provisional.

The foundation precedes substantial v0.4 work and does not renumber or reduce its
commitments. Keep authoritative first-time joins, continuing reconnect, strict
two-established-peer lockstep reconnect, discovery/directory/browser, physical
generated avatars, ordinary-protocol AI clients and runnable previews after
completed slices. Public discovery does not itself provide NAT traversal or
imply host migration, matchmaking or private Steam relay availability.

## Limits and acceptance still tracked

- Current far rendering reaches approximately 3 km with a 3200 m camera far
  plane; world generation itself has no fixed edge. Pristine far tiles are
  heightfields; bounded authoritative SDF overlays can carry resident edits, but
  the far store is not attached to saves at runtime. The accepted v0.3 contract replaces this with a 16 km volumetric
  ladder over an unbounded world; until those slices land and are verified, the
  current limits stand.
- With `sim.active_regions` disabled, the simulation clock retains its legacy
  load-time reset; the landed enabled clock resumes the persisted absolute tick.
  Creature/plant distance scheduling, durable field pages and wildlife, and dirty
  eviction parking still require their consumer/residency slices. Wind/weather/aether
  remain anchored grids; a clock or ledger alone does not implement these policies.
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

