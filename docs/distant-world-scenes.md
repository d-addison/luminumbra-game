# Distant-world scenes and the cave-dense preset

This page covers issue 30 in the game repository: the `cave_dense` preset, the
distant-world scene set, the scene receipt schema, and the exporter that
prepares preset files for the engine. The engine contract is
`docs/distant-world.md` in the engine repository at baseline
`b56cdba12e425ed2786778d5b02c98ba61466584`.

Status: the files and validators are committed. Nothing on this page has been
verified natively. Every execution-bound step is marked NEEDS-NATIVE-RUN.

## Purpose

The far-horizon gate needs scenes that exercise deep cave interiors, cave
mouths beyond the 4 km noise-cave cutoff, and the far ladder out to 16 km. The
`caverns` preset carries too few cave openings for that, so `cave_dense` derives
from it with three numeric changes. The scene set names the stations where the
native run measures the gate, and the receipt schema binds each native result
to its station.

## The cave_dense preset

`content/presets/cave_dense.json` is an engine-format preset at `schema_rev` 6.
It has the same key set as `caverns`, with no added keys. Only these values
differ from `caverns`, apart from `name` and `description`:

| Key (generation_params.features) | caverns | cave_dense | Loader semantics |
|---|---|---|---|
| `cave_threshold` | 0.62 | 0.54 | Cave noise is carved where the noise exceeds the threshold, so a lower threshold carves more volume. Must be in (0, 1). |
| `surface_break_density` | 0.28 | 0.55 | Bernoulli accept probability for each surface break. Must be in [0, 1]. |
| `max_feature_radius` | 46 | 52 | Must stay below `feature_cell_size` (110). At or above that the loader clamps it to 0.49 times `feature_cell_size`. |

The validator (`tools/validators/scene.py`) refuses any preset whose features
the loader would clamp, and requires these three values exactly for
`cave_dense`. A test compares the preset with the real caverns fixture and
checks that the differences are exactly these three values plus `name` and
`description`.

### Identity sidecar

The preset identity is the 16-hex-digit FNV-1a 64-bit hash of the canonical
JSON of the preset object. It is not stored inside the preset file. It lives in
`content/presets/cave_dense.identity.json`
(`luminumbra.game.preset-identity.v1`) with three keys:

- `preset`: the preset name, which must equal the file stem;
- `file_sha256`: the sha256 of the preset file bytes;
- `preset_identity`: the identity token of the parsed preset.

To recompute the identity of the preset file, run from the repository root:

```
python3 -I tools/traversal_tool.py identity content/presets/cave_dense.json
```

Then update both sidecar fields to match. The validator recomputes both and
fails when either differs.

## The scene set

`content/scenes/distant-world.json` (`luminumbra.game.scene-set.v1`) holds:

- Four stations, in this order, all with seed 424242 and a 90 s settle limit:
  - `tunnel-interior` on `cave_dense`, distance 0 m (deep interior);
  - `cave-mouth-2km` on `cave_dense`, distance 2000 m;
  - `arch-8km` on `caverns`, distance 8000 m (beyond the 4 km cutoff);
  - `horizon-16km` on `default`, distance 16000 m (beyond the 4 km cutoff).
- Two controls from the engine's control fixtures: `empty-tile` (default
  preset) and `cave-opening` (cave_dense preset).
- Three far-horizon coverage rows: `default`, `mountains`, `archipelago`.

Each row has a `pose` (null until discovery), a `status`, a `qualification`
object and per-profile `dispositions` (`quality` and `performance`). The
`discovery_notes` first state that discovery also records a cave opening beyond
the 4 km noise-cave cutoff (Q-24).

### Numeric qualification

The `qualification.requirements` object is fixed in the validator and copied
from the engine contract (`docs/distant-world.md`, far horizon gate, lines
474-486 at the baseline above):

- below-horizon sky at most 2 percent;
- no seam band at any tier radius (`seam_bands` 0);
- no edge at the outer radius (`outer_edge` false);
- every tier complete.

A scene receipt is `qualified` only when `settled` is true, every tier is
complete, `below_horizon_sky_percent` is at most 2, `seam_bands` is 0, and
`outer_edge` is false. A boolean `settled` alone is never sufficient.

### Pending and release

- `pending-native-discovery` is the committed state. Every pose, hash and tier
  list is null or empty, and both dispositions are null. The validator accepts
  pending content only with `--allow-pending`. Without that flag it reports
  `status pending-native-discovery is not allowed in this mode`.
- `--release` refuses pending content. It also requires, for every row, a
  discovered status, a non-null pose, non-null `wanted_set_sha256` and
  `coverage_sha256`, at least one tier with every tier complete, and a
  disposition for both profiles whose verdict is `accepted` or
  `waived-with-reason`. A `defect-open` verdict is always refused in release.

## Discovery oracle (NATIVE)

The oracle is a native measurement, not an offline claim. NEEDS-NATIVE-RUN: on
the qualified machine, count cave openings in a fixed probe window for
`cave_dense` and for `caverns`, and compare the two counts. The threshold is
recorded in the scene set when the native run supplies it. Nothing in this
repository asserts that `cave_dense` has more openings than `caverns`.

The deep interior (`tunnel-interior`) and a mouth beyond the 4 km noise-cave
cutoff (`arch-8km`, `horizon-16km`) are part of the probe, not only the 2 km
mouth.

## Scene receipts

`luminumbra.game.scene-receipt.v1` files live at
`content/receipts/scene-*.json`. The validator checks:

- `scene_set` is `distant-world`, and `station` names a station, control or
  coverage row of the committed scene set;
- `preset_identity` equals the identity sidecar of the station's preset (engine
  presets `default`, `caverns`, `mountains` and `archipelago` have no sidecar and
  are skipped);
- the numeric fields and the qualification rules above;
- a receipt with disposition `accepted` must be qualified, and a receipt that is
  not qualified may only carry `defect-open` or `waived-with-reason`. The
  problem names each failing quantity.

No receipt is committed. Receipts are produced by the native run.

## Exporter and status

`tools/export_engine_content.py` maps `content/presets/<name>.json` to
`worlds/atlas/presets/<name>.json` in the engine layout. Sidecars are not
exported.

- With no option it prints the manifest, one `sha256  mapped/path` line per
  file.
- `--out DIR` writes the mapped files, byte for byte, under `DIR`. `DIR` must be
  absent or empty, and it must not contain a `.git` component.
- `--check ENGINE_ROOT` compares each mapped file with the engine copy and
  prints one `PATH: differs` or `PATH: missing` line for each mismatch. It exits
  0 only when every file matches.
- `--out` and `--check` are mutually exclusive (exit 2). An invalid preset
  refuses the export (exit 1).

Delivery to the runtime is PENDING. Copying the exported file into the engine
tree is an engine pull request owned by the coordinator. Package inclusion is
out of scope for this page.

## Scene receipt fields

| Field | Rule |
|---|---|
| `schema`, `scene_set`, `station` | fixed schema id; `distant-world`; a row id of the committed set |
| `profile`, `display` | `quality` or `performance`; `3840x1600` or `3440x1440` |
| `settled`, `settle_seconds` | boolean; number greater than 0, at most 90 when settled |
| `wanted_set_sha256`, `coverage_sha256`, `capture_sha256` | 64 lowercase hex digits |
| `tiers` | non-empty, unique ascending tier numbers, each with `complete` |
| `below_horizon_sky_percent` | number from 0 to 100; qualified at 2 or below |
| `seam_bands` | integer 0 or more; qualified at 0 |
| `outer_edge` | boolean; qualified at false |
| `scene_identity` | 1 to 64 characters from `A-Z a-z 0-9 . _ : -` |
| `preset_identity` | 16 lowercase hex digits; checked against the sidecar |
| `content_identity` | 1 to 20 decimal digits |
| `adapter` | contains the qualified renderer name `RTX 5070 Ti` |
| `engine_revision`, `game_revision` | 40 lowercase hex digits |
| `disposition` | `verdict` (`accepted`, `defect-open`, `defect-fixed`, `waived-with-reason`) and a non-empty `note` |

## Native handoff

| Step | Owner | Commands | Receipts or output | Completion criteria | Status |
|---|---|---|---|---|---|
| Discovery of station and control poses | operator on the qualified machine | the engine's distant-world discovery probe (named in `native.discovery_probe`) | pose per row, cave-opening count per preset in the probe window | every row has a pose and status discovered; the arch-8km and horizon-16km cases are recorded | NEEDS-NATIVE-RUN |
| Cave-count oracle | operator on the qualified machine | the same probe, `cave_dense` against `caverns` | cave-opening counts and the threshold written into the scene set | threshold recorded; no offline claim | NEEDS-NATIVE-RUN |
| Qualification of each row and profile | operator on the qualified machine | the far horizon gate in the engine (`FarLodHorizon`) for each display and profile | one scene receipt per row, profile and display | each receipt qualified, or carries an allowed non-accepted disposition | NEEDS-NATIVE-RUN |
| Identity echo for cave_dense | operator on the qualified machine | the engine preset identity echo; a mismatch makes the engine refuse with exit 2 | identity echo output | echo equals the sidecar `preset_identity` | NEEDS-NATIVE-RUN |
| Engine copy of the preset | coordinator, engine pull request | `tools/export_engine_content.py --out DIR`, then the engine copy, then `--check ENGINE_ROOT` | exported manifest and check output | `--check` exits 0 against the engine tree | PENDING engine pull request |
| Release gate | coordinator | `tools/validate_content.py --release` | validator output | exits 0 with no scene problems; all rows discovered and qualified | blocked until the rows above are complete |
