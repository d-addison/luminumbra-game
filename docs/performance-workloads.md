# Performance workloads

This page describes the camera traversal workloads used for render and streaming
benchmarks, how their sources are validated, and what the native qualification
still has to do. The engine baseline for this content is
`b56cdba12e425ed2786778d5b02c98ba61466584`.

## Purpose

A workload is a scripted camera path with a fixed seed, preset and duration. The
game repository keeps the workload source as JSON under `content/workloads/`.
For a pinned workload with no events, the source emits a canonical
`luminumbra.traversal.v1` text file under `content/workloads/traversal/`, which
the engine client replays during a render benchmark.

Only the source and the committed traversal are public. Render reports are
private. A receipt under `content/receipts/` records hashes and verdicts of a
native run, never the report itself.

## The three workloads

| Workload | Preset | Status | Traversal file | Notes |
| --- | --- | --- | --- | --- |
| `surface-flight` | `default` | pinned | committed | Engine reference surface flight, 60 s at 30 Hz along +X. |
| `cave-walk` | `caverns` | pending-discovery | not yet | Camera benchmark through a cave (render and streaming cost). Not a walking simulation. |
| `edited-world-tour` | `default` | pending-discovery | not yet | Scripted edits and snapshots; needs the engine traversal v2 event grammar. |

`surface-flight` pins the preset identity `026f24207a8ffc7e` and the content
identity `16636010052247870746`. Its emitted text equals the committed
`content/workloads/traversal/surface-flight.traversal` and the engine fixture
byte for byte.

`cave-walk` pins the preset identity `ebf1507e76482151`, computed offline from the
engine caverns preset. The native identity echo is the final check of that
value. Its content identity is not yet known. Its path is recorded natively from
discovered cave openings, so its points are null until that discovery runs.
It does not exercise activation or persistent wildlife.

`edited-world-tour` pins the default preset identity and has four scripted
events: a fill above a tile's pristine maximum height at tick 300, a snapshot at
tick 600, a dig at tick 900, and a snapshot at tick 1200. Its coordinates are
chosen natively. Because the events need the engine traversal v2 grammar, the
emitter refuses them.

## Workload source rules (`luminumbra.game.workload.v1`)

- Required keys: `schema`, `id`, `kind`, `description`, `preset`, `seed`,
  `duration_seconds`, `tick_rate`, `speed_mps`, `pins`, `status`, `points`,
  `events`, `native`. Unknown keys are refused.
- `id` is lowercase kebab-case and equals the file stem. `kind` is
  `camera-traversal`. `preset` uses `[a-z0-9_-]+`.
- `seed` is an integer in `[0, 4294967295]`. `tick_rate` is 30.
- `duration_seconds * tick_rate` must be an exact integer in `[1, 18000]`. The
  check uses exact decimal arithmetic.
- `speed_mps` is greater than 0. Exponent number tokens (`8e0`, `1E-8`) are refused
  when the file is parsed, so no validator sees them. Numbers are rendered in
  fixed-point form, so `0.00000001` stays `0.00000001`.
- `pins.preset_identity` is null or 16 lowercase hex digits.
  `pins.content_identity` is null or 1 to 20 decimal digits.
- `status` is `pinned` or `pending-discovery`.
- `points` must be null while `status` is `pending-discovery`; an array, even an
  empty one, is refused. A pinned workload needs both pins and an array of 2 to
  1024 `[x, y, z, yaw, pitch]` rows.
- `events` holds at most 16 entries. Ticks are integers in `[1, expected_ticks]`
  and strictly ascending. Event ids are kebab-case and unique. An `edit` event
  has `x`, `y`, `z` (numbers; null only while the workload is pending), `radius_m`
  (greater than 0), and `mode` (`fill` or `dig`). A pinned workload's edits need
  coordinates, so null coordinates are refused with `events[i] null coordinates
  are refused for a pinned workload`. A `snapshot` event has no other keys. No
  other kinds exist, and there is no material field.
- `native.commands` is `docs/performance-workloads.md`. `native.receipt` is null
  or a `.json` path under `content/receipts/`. No component of that path may
  contain `:`, so Windows drive syntax is refused. In release mode the receipt
  must be set (`native.receipt must be set in release mode`).

A pinned workload is also validated with the strict v1 traversal rules:

- 2 to 1024 points; 18000-tick cap; tick rate 30; preset revision 6;
  `cold_cache true`.
- No zero-length segments.
- Path length is at least `duration_seconds * speed_mps`.
- Coordinates have absolute value at most 32000. Pitch satisfies
  `abs(pitch) < 90`.
- Traversal text is LF only, with a single final LF, no blank lines and no BOM.

## Pending semantics

- `pending-discovery` workloads are refused by default. They are accepted only
  with `--allow-pending`.
- The release gate (`tools/validate_content.py --release`) refuses any workload
  that is not `pinned`, any workload with null pins, any workload whose
  `native.receipt` is null, and any event with null coordinates.
- `emit` refuses pending workloads and workloads with events.
- A pinned workload with events is valid as a source. It has no emitted
  traversal until the engine traversal v2 grammar exists.

## Commands

```
python3 -I tools/traversal_tool.py validate --root . [--allow-pending]
python3 -I tools/traversal_tool.py emit content/workloads/surface-flight.json [-o OUT]
python3 -I tools/traversal_tool.py check --root .
python3 -I tools/traversal_tool.py identity PRESET_JSON
```

- `validate` checks every file under `content/workloads/`.
- `emit` prints (or writes) the canonical traversal for a pinned, event-free source.
- `check` confirms that each pinned, event-free workload has a committed
  `.traversal` file equal to its emitted text, and that each committed
  `.traversal` has an emittable source. It is `validate --allow-pending`.
- `identity` prints the preset identity of an engine-format preset file. It
  refuses values outside the preset value space.

## Traversal receipts (`luminumbra.game.traversal-receipt.v1`)

A receipt must live at `content/receipts/<name>.json`; any other location is
refused with `receipts must live under content/receipts/`. It records one native
benchmark cell.
Its keys are `schema`, `workload`, `cell_id`, `profile` (`quality` or
`performance`), `display` (`3840x1600` or `3440x1440`), `report_sha256`,
`verdict` (`pass`, `fail`, or `unevaluated`), `verdict_sha256`,
`traversal_sha256`, `preset_identity`, `content_identity`, `adapter` (containing
`RTX 5070 Ti`), `engine_revision` and `game_revision` (40 lowercase hex digits
each).

The validator checks that the workload exists and that its non-null pins equal
the receipt's identities. When `content/workloads/traversal/<workload>.traversal`
exists, `traversal_sha256` must equal its SHA-256. In release mode the verdict
must be `pass`. No receipts are committed yet.

## Qualification (owned by engine acceptance work)

The render floor and the qualification matrix belong to the engine acceptance
work, not to this repository. The matrix is `tools/perf/qualification/matrix.json`
in the engine tree. The floor check is `validate_render_capture.py --enforce-floor`.

- Each traversal needs 4 reports: 2 profiles (quality, performance) by 2 displays
  (3840x1600, 3440x1440). Three traversals need 12 reports in total.
- The qualification matrix defines 36 cells, which include the six fixed views.
- A successful run of the capture checker on its own is not qualification. The
  floor verdict and the matrix cells must both be satisfied.

Native commands for one cell use the client flags from the engine
`docs/render-benchmark.md`:

```
luminumbra_client_app --no-audio --render-benchmark OUT.json --render-benchmark-schema v3 --capture-size 3840x1600 --perf-profile quality --traversal content/workloads/traversal/<id>.traversal
luminumbra_client_app --no-audio --render-benchmark OUT.json --render-benchmark-schema v3 --capture-size 3440x1440 --perf-profile performance --traversal content/workloads/traversal/<id>.traversal
python3 tools/perf/validate_render_capture.py OUT.json --qualified-renderer 'NVIDIA GeForce RTX 5070 Ti' --traversal content/workloads/traversal/<id>.traversal --enforce-floor
```

The reports (`OUT.json`) stay private. Only `report_sha256` and
`verdict_sha256` go into a receipt.

## Native handoff

Everything in this table is execution-bound and has not been run.

| Item | Status | Owner | Candidate identity | Commands | Receipts to produce | Completion |
| --- | --- | --- | --- | --- | --- | --- |
| Qualified benchmark runs for `surface-flight` (4 cells) | NEEDS-NATIVE-RUN | Operator on the qualified machine | Release candidate git SHA plus archive SHA-256 | Native commands above, `<id>` = `surface-flight` | 4 traversal receipts, verdict `pass` | 4 receipts with verdict pass |
| Qualified benchmark runs for `cave-walk` (4 cells) | NEEDS-NATIVE-RUN | Operator on the qualified machine | Release candidate git SHA plus archive SHA-256 | Discovery of cave openings, then native commands, `<id>` = `cave-walk` | 4 traversal receipts, verdict `pass` | 4 receipts with verdict pass |
| Qualified benchmark runs for `edited-world-tour` (4 cells) | NEEDS-NATIVE-RUN | Operator on the qualified machine | Release candidate git SHA plus archive SHA-256 | Needs engine traversal v2 events, then native commands, `<id>` = `edited-world-tour` | 4 traversal receipts, verdict `pass` | 4 receipts with verdict pass |
| Pin `cave-walk` content identity and points | NEEDS-NATIVE-RUN | Operator on the qualified machine | Engine baseline `b56cdba12e425ed2786778d5b02c98ba61466584` | Native identity echo and path discovery | Source update in `content/workloads/cave-walk.json` | Status moves to pinned with both pins |
| Traversal v2 event grammar for `edited-world-tour` | NEEDS-NATIVE-RUN | Engine acceptance workstream | Engine baseline `b56cdba12e425ed2786778d5b02c98ba61466584` | Engine side, not in this repository | Emitter update for events | Emitter accepts events |

Completion of the workload qualification is 12 traversal receipts with verdict
`pass`, one per cell of the three traversals' 4-cell sets.
