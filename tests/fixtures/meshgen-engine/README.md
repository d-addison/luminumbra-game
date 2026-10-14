# Pinned E1 contract fixture

These files are unmodified copies from `d-addison/luminumbra` commit
`4a01f6d46a83c0e59503c3cb388ec3fbb04dc52a` (E1 meshgen contracts).
`inventory.json` records the source directory and SHA-256 of every copied file;
`LICENSE` retains the engine's MIT notice. The game tests verify the inventory
before importing any copied code. Missing or changed files fail discovery;
there is no engine-checkout skip or network fallback.

The snapshot includes the service modules needed by the real `check-config`
CLI, its trusted launcher, and all packaged meshgen schemas/defaults. It is a
test fixture, not a game runtime service or a fork of the engine contracts.
Use the installed engine service for authoring. Existing game tests similarly
use committed engine preset/traversal fixtures; this branch has no
`tools/lumlib/engine_inventory.json`.

An intentional E1 update copies exact reviewed bytes, updates this revision,
the per-file digests and the inventory digest in `test_meshgen_project.py`, then
runs the portable suite. Never edit the copied resolver or schema to make a
game configuration pass. All executable companion scripts remain game-owned
under `authoring/meshgen/`; no script or generated evidence is added to this
engine snapshot.
