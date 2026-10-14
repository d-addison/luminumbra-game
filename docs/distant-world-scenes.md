# Distant-world scenes and the cave-dense preset

This page covers issue 30 in the game repository: the `cave_dense` preset, the
distant-world scene set, the scene receipt schema, and the exporter that
prepares preset files for the engine. The engine contract is
`docs/distant-world.md` in the engine repository at baseline
`b56cdba12e425ed2786778d5b02c98ba61466584`.

Status: the files and validators are committed. Nothing on this page has been
verified natively. Every execution-bound step is marked NEEDS-NATIVE-RUN, and
the steps that need engine instrumentation not yet available are marked
BLOCKED.

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
`cave_dense`.

Every exported preset must have exactly the four top-level keys `name`,
`description`, `schema_rev` and `generation_params`, with a non-empty
`generation_params`. Under `generation_params` the validator checks a shape table
(`PRESET_SHAPE` in `tools/validators/scene.py`) written from the two engine
fixtures, `tests/fixtures/engine-caverns-preset.json` and
`tests/fixtures/engine-default-preset.json`. A key outside the union of the two
fixtures at its path is refused, and so is a value of the wrong type: numbers
(an integer is accepted for a float field, a boolean is not), integers for
`octaves` and `iterations`, booleans, a non-empty string for `biomes.table`, and
arrays of `[number, number]` pairs for the splines. A nested object where a leaf
is expected is refused.

`cave_dense` must also have exactly the caverns key set at each object path
it shares with caverns, so a missing key or a key that only the default preset
has is refused. Other presets may omit optional keys: the engine fills those in
with its own defaults. The keys the engine loader refuses a preset without are
mandatory for every preset, and the validator refuses a preset missing any of
them with `PATH: generation_params.<path>.<key> is required`:

- `generation_params.terrain` (object) with the numbers `base_frequency`,
  `base_amplitude`, `octaves`, `persistence`, `lacunarity` and `height_offset`;
- `generation_params.features` (object) with the boolean `caves_enabled` and the
  number `cave_frequency`.

The loader clamps `max_feature_radius` to 0.49 times `feature_cell_size` when the
radius is not below the cell size. The validator refuses that case instead, using
the effective values: an omitted `feature_cell_size` is 128 and an omitted
`max_feature_radius` is 60, both compared after float32 conversion.

A test checks that the real caverns and default fixtures validate clean, and
another checks that the differences between the preset and the caverns fixture
are exactly these three values plus `name` and `description`.

### Identity sidecar

The preset identity is the 16-hex-digit FNV-1a 64-bit hash of the canonical
JSON of the preset object. It is not stored inside the preset file. It lives in
`content/presets/cave_dense.identity.json`
(`luminumbra.game.preset-identity.v1`) with four keys:

- `schema`: the schema id;
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
- `--release` also requires native evidence. For every row, both profiles and
  both displays there must be exactly one scene receipt in `content/receipts/`
  with the matching `station`, `profile` and `display`. Each such receipt must
  be a qualified receipt that passes the receipt rules, whose disposition
  verdict is `accepted` or `waived-with-reason`. Its `wanted_set_sha256`, `coverage_sha256` and `tiers` must equal
  the row's recorded values. The entire `disposition` object must equal
  the row's `dispositions[profile]`, including exact verdict and note without
  trimming or normalization. Both displays agree with that profile's authored
  disposition. A matching waiver cannot bypass any numeric qualification gate.
  Nested receipt validation uses the same validated scene-set snapshot; direct
  receipt validation loads its row context once without recursively scanning
  receipts or requiring unrelated rows to be released. Missing, duplicate and inconsistent receipts are
  refused. The `scene_identity` of a profile must be the same on both of its
  displays and must differ between `quality` and `performance` for the same row.
  Every receipt must match the independently supplied
  `--expected-game-revision` and `--expected-engine-revision` (each exactly 40
  lowercase hex digits). Uniformly stale receipts and mixed candidate revisions
  are refused. Neither pin is inferred from receipts, git HEAD or the engine
  baseline. A receipt evidence commit may follow measurement: the explicit
  measured game pin stays fixed, and owner review binds that measured candidate
  to the package. Committing evidence must never silently advance that pin.
  The four receipts of one station (both profiles and both displays) must also carry one `preset_identity` and one `content_identity`;
  a mismatch is refused with `release requires one preset_identity for station 'ID' across its receipts`
  (or `content_identity`). Different stations may carry different values. The
  committed JSON does not carry the identities; they are taken from the receipts. Pending mode (`--allow-pending`) does not require
  receipts.

Scene release validation also requires `--artifact-root CAPTURE_ROOT`. For each
receipt, the only capture locator is
`CAPTURE_ROOT/sha256/<capture_sha256>`. A bare digest file or a `.json` alias
cannot satisfy it; unrelated aliases are ignored. The unchanged
`scene-receipt.v1` schema carries no extra artifact path or authentication field.
The validator streams exact binary bytes in bounded chunks, with no arbitrary
total-size cap, and compares their SHA-256. Missing, unreadable, symlink,
nonregular and observable Windows reparse artifacts are refused, as are unsafe
root/store/ancestor directories. Pre/open/post metadata checks include the
opened file identity, size and modification metadata and detect observable
replacement, truncation or modification. These checks establish byte integrity;
they do not authenticate native execution, parse capture metrics or exclude
every hostile filesystem race. Synthetic CI captures test format and integrity
only and do not qualify native runs.

All three context flags are optional for authoring and unrelated release
schemas. When supplied, malformed revisions and empty, missing or non-directory
artifact roots are usage errors (exit 2), even on an empty tree or outside release.
Missing context for either direct scene release validator is a validation refusal
(exit 1). The Python `validate_tree` API preserves its five positional arguments
and adds these three options as keyword-only arguments; the corresponding
`Context` fields default to `None`.

## Discovery oracle (NATIVE)

The oracle is a native measurement, not an offline claim. Nothing in this
repository asserts that `cave_dense` has more surface cave openings than
`caverns`, and no threshold below has been measured.

### Support at the baseline

- Supported today: the engine's `FarLodHorizon` gate, run through
  `validate-engine-frontier` at the baseline above. Its complete baseline
  invocation is given under "Native handoff" below. It covers three engine
  presets (`mountains`, `default` and `archipelago`), and it does not run
  `cave_dense`. It does not compute an independent wanted set. Its parameters
  are `-Mode` (`FarLodHorizon`), `-BuildPreset` (default `debug`) and
  `-SmokeSeconds` (default 30; the baseline run uses 50).
- BLOCKED: per-row, per-profile and per-display qualification evidence for the
  scene set. It needs engine instrumentation that is not yet available, and it
  depends on the engine acceptance workstream. Until that instrumentation exists,
  no receipt for a scene-set row can be produced from a supported command.
- BLOCKED: counting surface cave openings. No command or instrument that counts
  them is named at the baseline. The counting step of the procedure below uses
  that instrumentation and cannot run until it exists.

### Discovery probe (fixed procedure, NEEDS-NATIVE-RUN)

1. Set the probe window to a 4096 m by 4096 m square centered on the world
   origin, with seed 424242.
2. Using the same window and seed, count the surface cave openings for the
   `caverns` preset. Record the count as C.
3. Using the same window and seed, count the surface cave openings for the
   `cave_dense` preset. Record the count as D.
4. Record C and D together with the engine revision, the game revision and the
   release-candidate git SHA the counts were taken on.
5. Apply the proposed rule: D must be at least 1.25 times C. Because a C of 0
   makes that rule vacuous, D must also be at least 1. Both thresholds are
   PROPOSED values. They are recorded here only as proposals and were never
   measured. Recording measured cave-count thresholds requires a separate
   schema decision: the current strict scene-set schema has no fields for those
   counts or thresholds. This repair does not resolve that gap.
6. The probe also has to record a cave opening beyond the 4 km noise-cave cutoff.
   The `arch-8km` and `horizon-16km` stations are the beyond-4 km cases.

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
exported, but each preset and its sibling `.identity.json` are validated before
any output against the exact captured preset bytes. Capture loading is separate
from pure pair validation: no validation reread, missing-snapshot fallback or
silent retry can certify preset A using sidecar B. A consistent captured pair
remains the exported snapshot if disk changes afterward. Manifest, output and
`--check` use those same preset bytes. The exporter independently refuses
missing sidecars, symlink/nonregular/reparse sources and observable unsafe
ancestors; it does not assume the tree validator ran first. UTF-8, BOM/CR,
strict JSON, filename/device, preset shape and identity rules still apply.
A stale hash, wrong identity or malformed sidecar refuses the export.

- With no option it prints the manifest, one `sha256  mapped/path` line per
  file.
- `--out DIR` writes the mapped files, byte for byte, under `DIR`. `DIR` must be
  absent or empty. Before any creation or write, the longest existing ancestor
  is strictly resolved, expanding symlinks, junctions and Windows short names;
  the missing tail is checked and appended afterward. The repository root and
  `content/` directory resolve the same way before containment is compared.
  A failed strict resolution or lost absolute anchor is refused (exit 2).
  Literal and resolved `.git` components in any letter case, and destinations
  inside the resolved `content/` tree, are refused (exit 2). Short-name aliases,
  including administrator-assigned names without `~`, are resolved rather than
  recognized by spelling (#46); ordinary names containing `~` are accepted.
  On Windows, missing components with trailing spaces or dots are refused,
  since creation can trim them into protected names such as `content` or
  `.git`. Missing device names (including names with extensions) and path
  components with colons such as `::$DATA` stream suffixes are also refused
  (exit 2). POSIX keeps spaces, dots, colons and device-like names literal,
  while still enforcing
  `.git` and content containment. Ordinary drive paths, extended drive paths
  (`\\?\D:\out\export`), UNC shares, `.github/x` and `x.git/y` are accepted.
  Complete output is written and closed in a uniquely owned sibling stage on
  the destination filesystem first. Publication
  uses exclusive directory and file creates, never replacement or overwrite.
  A preexisting empty destination keeps its directory identity on success and
  every failure; validation, staging and prepublication failures leave it
  untouched. Actual commit/rollback writes may change its mtime.
- Ordinary export failure rolls back only unchanged paths created by that
  invocation. With no external mutation, the destination returns to absent or
  its original empty directory, permitting retry. Newly created parents are
  removed only if still owned and empty. Zero mapped files may create an absent
  destination or preserve an existing empty one.
- Restriction, ancestor and destination identity checks repeat before commit
  and each write. Observed disappearance, replacement, new population or a
  newly appeared empty destination is refused. Exclusive creates protect
  occupied leaves. Race failure preserves external files and directories, so
  the destination may remain nonempty. Cleanup checks identity and ownership,
  never recursively deletes the destination or unknown stage content, and
  refuses success with retained paths and staging location when cleanup fails
  or ownership is uncertain.
- Publication has no whole-tree atomic visibility guarantee; readers may see
  partial output during commit. The checks address ordinary failures and
  observable cooperative writer races, without promising complete hostile
  namespace race exclusion or persistence after a crash or power loss.
- `--check ENGINE_ROOT` compares each mapped file with the engine copy and
  prints one `PATH: differs` or `PATH: missing` line for each mismatch. It exits
  0 only when every file matches.
- An I/O failure (for example, an output path whose parent is a file, or an
  engine root that is a file) prints one `PATH: reason` line and exits 1. A
  missing `--check` root is a usage error and exits 2.
- A preset or sidecar nested too deeply to parse prints
  `PATH: json nesting is too deep` and exits 1.
- `--out` and `--check` are mutually exclusive (exit 2). An invalid preset
  refuses the export (exit 1).
- A preset or sidecar file stem that is a Windows device name (`con`, `prn`,
  `aux`, `nul`, `com1` to `com9`, `lpt1` to `lpt9`, in any letter case) is
  refused, because such a file cannot be an ordinary file on Windows.

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
| `engine_revision`, `game_revision` | 40 lowercase hex digits; `game_revision` is the measured game candidate SHA; every release receipt matches both explicit expected pins |
| `disposition` | `verdict` (`accepted`, `defect-open`, `defect-fixed`, `waived-with-reason`) and a non-empty `note`; release requires exact equality with the matching row/profile object |

## Native handoff

Owner for every row is the operator on the qualified machine, except the
engine copy and the release gate, which the coordinator owns. A row whose
command is not named at the baseline has no command and stays open.

| Step | Commands | Receipts or output | Completion criteria | Status |
|---|---|---|---|---|
| Release-candidate git SHA | record the SHA of the release candidate that the run uses | the SHA in the handoff record; every receipt's `game_revision` equals it | the SHA is recorded and matches every receipt | NEEDS-NATIVE-RUN |
| Archive sha256 | record the sha256 of the release archive the run uses | the sha256 in the handoff record, next to the SHA | the sha256 is recorded with the RC SHA; no receipt field carries it yet | NEEDS-NATIVE-RUN |
| Engine gate at baseline | From the engine repository root on the Windows machine: `powershell -File tools/gates/validate-engine-frontier.ps1 -Mode FarLodHorizon -BuildPreset debug -SmokeSeconds 50` | the gate runs presets `mountains`, `default` and `archipelago`; artifacts are written under `build/debug/test-artifacts/runtime/farlod-horizon-<preset>` | output recorded for the three presets; no wanted set is claimed from it; `cave_dense` is not run by this gate | NEEDS-NATIVE-RUN |
| Station and control poses | no command named at the baseline | a pose per row | every row has a pose and status discovered; the arch-8km and horizon-16km cases are recorded | NEEDS-NATIVE-RUN (no command yet) |
| Cave-count oracle | the discovery probe above, `caverns` and `cave_dense` in the fixed window | counts C and D, the rule outcome | both counts recorded; recording thresholds in the strict scene schema remains a separate unresolved decision | BLOCKED (counting instrument not available) |
| Qualification of each row, profile and display | `FarLodHorizon` per-row evidence is not available | one scene receipt per row, profile and display | each receipt numerically qualified and carries an exact matching accepted or waived-with-reason disposition | BLOCKED (engine instrumentation; engine acceptance workstream) |
| Identity echo for cave_dense | no command named at the baseline | the engine's reported identity for `cave_dense` | the reported identity equals the sidecar `preset_identity` | NEEDS-NATIVE-RUN (no command yet) |
| Engine copy of the preset | `python3 -I tools/export_engine_content.py --out DIR`, then the engine copy, then `python3 -I tools/export_engine_content.py --check ENGINE_ROOT` | exported manifest and check output | `--check` exits 0 against the engine tree | PENDING engine pull request |
| Release gate | `python3 -I tools/validate_content.py --root . --release --expected-engine-revision ENGINE_SHA --expected-game-revision MEASURED_GAME_SHA --artifact-root CAPTURE_ROOT` | validator output | exits 0 with no scene problems; all rows discovered and qualified | blocked until the rows above are complete |

Replace `ENGINE_SHA` and `MEASURED_GAME_SHA` with the independently recorded
40-lowercase-hex revisions and `CAPTURE_ROOT` with the safe existing capture
store directory. Native measurement authentication and cave-count schema
recording remain unresolved separately. Every native row remains pending; no
fabricated native receipt is committed by this source repair.
