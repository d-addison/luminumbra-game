# Meshgen project configuration (MG2 G1)

G1 supplies committed project values and an inert game-owned companion extension
skeleton. It does not generate, finish, import or promote meshes. No Blender,
GPU, backend, model acquisition or native qualification has been performed.
The finisher follows in G2; the panel/import/lineage adapter and paired engine
lifecycle integration follow in G3. Native acceptance remains pending on the
user's Windows Blender 5.1.0 machine; G1 is not P1 acceptance.

## Configuration and policy

[`meshgen.config.json`](../authoring/meshgen/meshgen.config.json) is L1, validated
against the engine's `luminumbra.authoring.meshgen.config.v1` registry and packaged
schema. L0 comes from the engine. L2 explicitly selects a committed asset-class
profile; L3 is the ignored `authoring/meshgen/meshgen.local.json`; L4 is a bounded
request override. Objects merge recursively; arrays and scalars replace.
Profiles have one parent, no cycles or missing parents, and at most three
profiles in a resolved chain including the selected profile.

| Profile | Provisional final triangles | Maximum bounds in metres (X/Y/Z) |
|---|---:|---|
| default | 8,000 | 8 / 8 / 8 |
| prop | 8,000 | 8 / 8 / 8 |
| rock | 6,000 | 8 / 8 / 8 |
| foliage | 4,000 | 8 / 8 / 8 |
| tree | 20,000 | 30 / 30 / 40 |

These are uncalibrated internal mock baselines, not approved shipping budgets.
P2 calibration and the user's approval determine final budgets. Profiles may
establish different baselines within L1 bounds; L3/L4 tightening is compared
against the selected profile, not the default class. For example, rock resolves
to 6,000, accepts a 4,000 request cap and refuses 9,000. The tree baseline of
20,000 and foliage Hausdorff tolerance of 0.02 remain valid examples.
`budgets.max_tris_final` is authoritative: absent `finish.decimate.max_tris`
is derived from it; an explicit smaller target is permitted. Final exported
counts require a separate check and subsequent builds must carry the selected
cap as `settings.max_tris` once the service advertises `max_tris_setting`.

Only the synthetic `mock` backend is enabled. The disabled `direct3d_s2` entry
has empty pins and no licence clearance. Other real backends are undeclared.
Enabling a real backend needs a reviewed L1 change, actual revision/weight pins,
complete executed-component/dataset inventory and verified policy records.
L3 cannot enable a disabled backend. No acknowledgements, counsel notes or
dataset waivers have been recorded; all prerequisite attestations are false.
Stability internal use remains subject to its verified prerequisites and counsel
for shipping; Hunyuan output remains non-shippable. Nothing in G1 clears either.

The licence allow-list stays `shippable`. The pinned synthetic mock card may
pass the pure licence gate, but the trusted parent must independently force
`shippable=false` and `origin=backend:mock`. G1 declares that policy conjunction;
the E3 broker implements and tests it. Arbitrary backends cannot self-declare
mock status. Choosing the internal validation profile does not grant shipping
eligibility or relax licence admission.

Finisher defaults come from E1: the fixed 11-step order, Blender collapse,
smart-project UV, thin-shell guard, keep disconnected parts, no hole filling,
neutral material and over-budget refusal. Typed ops, raw bpy, colliders, LOD
chains, textures, rigging, animation and experimental execution are disabled.
Manual one-candidate selection and digest-only prompt retention are selected.
Existing compiler `emit_lods` behavior belongs to the engine's separate build
contract. GC remains manual.

## Read-only check

Use an installed E1-or-later service or its reviewed source launcher. The
supported Python version is 3.11+. Both global arguments remain required:

```sh
python -I -S -B "$ENGINE/tools/blender/authoring/service/launch.py" \
  --project "$GAME" --toolchain "$TOOLCHAIN" \
  meshgen check-config --profile rock --print-effective
```

`ENGINE`, `GAME` and `TOOLCHAIN` are caller-supplied absolute paths. An installed
archive replaces the launcher path with the installed `luminumbra-author.pyz`.
Equivalent module syntax in an already isolated installed environment is
`python -m luminumbra_author --project ROOT --toolchain MANIFEST meshgen
check-config --profile CLASS [--print-effective]`. Use the trusted launcher for
source execution to keep project modules out of the service import path.

The check reports sources, differences from L0, the canonical effective digest,
uncalibrated budgets and unavailable live backend evidence. Failure returns
structured findings and a nonzero exit. It creates no state/session lock,
contacts no backend, reads no secret values and launches no Blender. This is a
configuration planning check, not a licence or backend qualification receipt.
`sources` is outside effective configuration identity. Stored effective JSON
bytes have a separate hash; token rotation does not change the config digest,
but a changed token reference or worker location does.

An optional local file may set existing worker executable paths,
`backends.<id>.token_source`, disable a backend or tighten its timeouts. Endpoint
and policy changes are refused. Worker paths must point to actual regular files.
For example, this is the entire local override for a mock token file:

```json
{"backends":{"mock":{"token_source":{"file":"authoring/meshgen/tokens/mock"}}}}
```

Keep token bytes in that ignored file or the named environment variable.
Do not store secrets in JSON, pins, notes or evidence. Local config, `token.*`,
`tokens/`, `toolchain.local.json`, `.luminumbra-author/`,
`.luminumbra-author-recipes/`, `authoring/meshgen/generated/` and
`authoring/meshgen/native/evidence/` are ignored. Generated art and native
observations belong in these local areas, outside the public tree. Reviewed
policy notes and future native probe source are not broadly ignored.

## Companion and script ownership

The companion source is [`authoring/meshgen/companion`](../authoring/meshgen/companion/__init__.py).
Its Blender manifest declares 5.1.0 only (exclusive maximum 5.1.1). Registration
and unregistration are inert. No UI, bpy imports, handlers, timers or executable
generation features are installed in G1. Installation and actual bpy behavior
are native acceptance obligations for the later slices.

[`script-inventory.json`](../authoring/meshgen/script-inventory.json) distinguishes
the present companion skeleton from planned finisher, generate, import and
lineage roles. Planned paths have no files or pins and cannot be executed.
[`script-pins.json`](../authoring/meshgen/script-pins.json) is an exact `scripts`
fragment for the engine's local toolchain manifest, not a complete toolchain.
It pins the initializer and its bootstrap helper, including every current
companion Python module. Merge that fragment into a trusted local manifest with
the actual installed compiler/library hashes. It is not a finisher execution
entry: `companion` describes extension source, while `finisher` stays unavailable
until G2 supplies the implementation and its reviewed pins. Never invent a
compiler hash or select a script via a request.

Consumers must negotiate `features.meshgen_script_pins` and
`features.meshgen_configuration` in existing service capabilities. A missing
feature is unsupported; older services reject the extended manifest. Old
compiler-only toolchains remain usable for ordinary builds, while MG2 refuses
missing script roles. Before execution the engine verifies project-relative
paths, every transitive companion module and SHA-256, rechecking on use. The
trusted source launcher/runtime guard is the execution boundary; hashes alone
do not qualify a Blender lane. Source edits require regenerated, reviewed pins.
Research metrics, ML adapters, reference fetchers and texture scripts are not
copied into or imported by this skeleton.

[`bootstrap.py`](../authoring/meshgen/companion/bootstrap.py) declares future
host integration points. They are not existing engine APIs or installed hooks:

- Invalidate pending import plans on edit, undo, redo, load, unload, scope,
  config, project or session changes. Scene edits do not cancel inference;
  document/project/session changes prevent staging. The owning engine broker
  handles cancellation, EOF, shutdown, deadlines and child termination.
- Review the complete sealed candidate and fresh context before import; apply
  synchronously on Blender's main thread in one undoable operator, with intents,
  replay and reverse rollback supplied by G3/E4.
- Propagate candidate-origin unions through supported derivations. Mark and
  Build validate declared origins from durable provenance, not eligibility
  booleans on scene tags. Policy tags stay in sidecars and are stripped from
  compiler-bound GLB extras. No asset ID or automatic promotion at import.

The existing engine extension stays in place. The paired G3 engine change will
connect only lifecycle and Mark/Build seams; finisher/importer implementation
stays game-owned. G1 does not claim those hooks are implemented.

## Portable verification

[`test_meshgen_project.py`](../tests/test_meshgen_project.py) is discovered by the
existing Linux/Windows stdlib CI lane. It consumes an exact, hash-pinned E1
fixture from engine commit `4a01f6d46a83c0e59503c3cb388ec3fbb04dc52a`, including
the packaged schemas/defaults, resolver and real `check-config` CLI. See the
[fixture provenance](../tests/fixtures/meshgen-engine/README.md). Missing or
changed fixture bytes fail before import; no engine checkout, network or skip
is required. The snapshot is test-only; the engine remains authoritative.

The repository's schema validator registry covers `content/` and
`docs/evidence/`. G1 files live under `authoring/` and ordinary docs, so the new
test explicitly validates them; no registry entry or CI workflow edit is needed.
The existing public-tree guard remains unchanged and must also pass with
`--worktree` to inspect newly added files.

Run tests with a clone-local temporary directory and no bytecode, then remove
the directory and any bytecode created by tooling:

```sh
mkdir .test-tmp
TMPDIR="$PWD/.test-tmp" TEMP="$PWD/.test-tmp" TMP="$PWD/.test-tmp" \
  python -I -B -m unittest discover -s tests -v
python -I -B tools/validate_public_tree.py --root . --worktree
python -I -B tools/validate_content.py --root . --allow-pending
rm -r .test-tmp
```

Portable checks establish configuration, source integrity and declared seams.
They do not establish real Blender geometry, installed-extension behavior,
undo/redo, licence clearance, promotion enforcement or completion of P1.
