# Pinned E1 contract fixture

These files are unmodified copies from `d-addison/luminumbra` commit
`75a5a9ad82c8441fd3f138b186bb46280cfc22eb` (E1 meshgen contracts).
`inventory.json` records the source directory and SHA-256 of every copied file;
`LICENSE` retains the engine's MIT notice. The game tests verify the inventory
before importing any copied code. Missing or changed files fail discovery;
there is no engine-checkout skip or network fallback.

Engine PR #291 is merged at this revision, including quarantine-intent recovery
(`4bed032b`) and legacy-mutex coordination with bounded recovery retries
(`832e36ef`). All inventoried members come from this revision; `LICENSE` comes
from the repository root rather than the service directory.

The snapshot includes the service modules needed by the real `check-config`
CLI, its trusted launcher, and all packaged meshgen schemas/defaults. It is a
test fixture, not a game runtime service or a fork of the engine contracts.
Its bounded E1 inventory does not include the newer full engine meshgen service.
Use the installed engine service for authoring. Existing game tests similarly
use committed engine preset/traversal fixtures. Portable fixture checks do not
qualify native Windows behavior; that remains separate, unclaimed work.

An intentional E1 update copies exact reviewed bytes, updates this revision,
the per-file digests and the inventory digest in `test_meshgen_project.py`, then
runs the portable suite. Never edit the copied resolver or schema to make a
game configuration pass. All executable companion scripts remain game-owned
under `authoring/meshgen/`; no script or generated evidence is added to this
engine snapshot.
