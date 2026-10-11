# Content layout and repository checks

This page describes how game content is laid out in the repository, how the
registry and the public tree guard work, and how CI runs. It covers only the
checks in this repository; the engine lives elsewhere.

## Layout

```
content/
  presets/      engine-format generation presets (JSON, glob-validated)
  scenes/       scene definitions
  workloads/    workload definitions
  sim/          simulation parameters
  items/        item definitions
tools/
  lumlib/       stdlib-only helpers shared by the scripts (schema loading, identity, traversal)
  validators/   content validator registry (one module per content family)
  validate_public_tree.py
  validate_content.py
tests/
  fixtures/     small engine-format and .traversal samples used by the tests
```

Every JSON file under `content/` carries a top-level `schema` key unless a
registered glob pattern claims it. Schema ids follow the convention
`luminumbra.game.<kind>.v1`, for example `luminumbra.game.item.v1`. A new
incompatible shape gets a new suffix; the old id stays registered until its
files are migrated.

## Validator registry

`tools/validators/` is a package. Each module in it is discovered with
`pkgutil.iter_modules` and imported as `validators.<name>`. A module may define:

- `SCHEMAS`: maps a schema id to `fn(path, obj, ctx) -> list[str]`. Called for
  each JSON file whose `schema` key equals that id.
- `GLOBS`: maps an fnmatch pattern relative to the repository root (posix
  separators) to `fn(path, text, ctx) -> list[str]`. Used for files that cannot
  carry a `schema` key, such as engine-format presets and `.traversal` files.

`ctx` is a `Context(root, allow_pending, release)`. Problems are strings of the
form `PATH: reason`. Duplicate schema ids or glob patterns across modules are an
error, reported by `discover()`. A validator that raises is reported as a
problem and does not stop the run.

Later content families add a module to the package; the shared script does not
change.

## Content validation

`tools/validate_content.py --root DIR` walks `content/`:

- Every `.json` file is parsed with `lumlib.schema.load_json_file`. Parse errors
  and duplicate keys are problems.
- A JSON file matched by a glob pattern is handed to that glob validator and does
  not need a `schema` key.
- Any other JSON file must be an object whose `schema` is registered.
- Every non-JSON file must match a glob pattern, or it is reported as
  `unrecognised content file`.
- Symlinks under `content/` are refused.

If `content/` is absent, the script prints `no content/ directory` and exits 0.

## Pending entries: `--allow-pending` and `--release`

With no flag, entries marked pending are refused. `--allow-pending` permits them
during development. `--release` refuses them and sets `release=True` in the
validator context. The two flags are mutually exclusive.

## Public tree guard

`tools/validate_public_tree.py --root DIR` inspects the tracked files of the
repository (with `--worktree`, also untracked non-ignored files). Without git it
walks the tree and skips `.git`. For each file it refuses:

- symlinks;
- files larger than 1 MiB (1048576 bytes);
- forbidden extensions, matched case-insensitively: audio, archives,
  executables and libraries, saves and chunks, logs and dumps, SDK blobs;
- files whose first 16 bytes match a known container or executable signature;
- text-zone files (Markdown, JSON, Python, C/C++, YAML, text, `.traversal`,
  `.gitignore`, and files without an extension) that contain NUL bytes or are
  not valid UTF-8;
- in the strict zones `content/` and `docs/evidence/`: CR bytes, a UTF-8 BOM,
  a missing final LF, and `.json` files that do not parse;
- in every text file: absolute local path shapes and credential-shaped strings.

The guard is a tripwire, not a proof of absence. It catches what it knows how to
recognise. A clean run does not show that the repository is free of private
material, and a reviewer still reads the diff.

## Public and private boundary

The repository is public. Saves, logs, audio, SDK payloads, captures and reports
are private evidence. Only hashes and counts of such material may be committed,
never the material itself. `docs/evidence/` may hold verification records, but
those records must follow the strict-zone rules above.

## How CI runs

The workflow is `.github/workflows/ci.yml`. It runs on pushes to `main`, on pull
requests to `main`, and on manual dispatch.

- Matrix: `ubuntu-24.04` on push; `ubuntu-24.04` and `windows-2022` on pull
  requests.
- Steps: checkout (no persisted credentials), unit tests, the public tree guard,
  and content validation with `--allow-pending`.
- The scripts use the Python standard library only. Nothing is installed and
  there is no network access beyond checkout.
- Scripts run as `python -I -B`: `-B` disables bytecode writing and `-I` ignores PYTHONDONTWRITEBYTECODE.

## Local check policy

Local checks in this repository are limited to a syntax check that parses a
file's AST without executing it. Builds, game runs and test runs are not part of
the local policy for this workstream; CI runs the tests.

## Engine baseline

The engine baseline pin for this content is
`b56cdba12e425ed2786778d5b02c98ba61466584`. Content generated for a different
engine revision is not valid under this layout until it is re-validated against
the pin.
