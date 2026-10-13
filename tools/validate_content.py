#!/usr/bin/env python3
"""Validate the content tree under ROOT/content and the JSON files under ROOT/docs/evidence.

Every .json file is parsed with lumlib.schema.load_json_file. A JSON file whose
path matches a GLOBS pattern is handed to that glob validator and need not carry
a "schema" key. Any other JSON file, in either zone, must be an object whose
"schema" key is a registered schema id; an unregistered or future schema id is
reported as "schema 'X' is not registered". Every non-JSON file under content/
must match a GLOBS pattern. Non-JSON files under docs/evidence/ are not handled
here; validate_public_tree.py checks them. Validator registration lives in the
tools/validators package; see its docstring.

Usage:
  python3 -I tools/validate_content.py --root . --allow-pending
  python3 -I tools/validate_content.py --root . --release \
    --expected-engine-revision ENGINE_SHA --expected-game-revision MEASURED_GAME_SHA \
    --artifact-root CAPTURE_ROOT

Without a flag, entries marked pending are refused. --allow-pending permits
them. --release refuses them and sets release=True in the validator context.

Scene release validators require explicit candidate pins (40 lowercase hex) and
a capture store at CAPTURE_ROOT/sha256/<capture_sha256>. Other release schemas
need no scene flags. Malformed supplied flags are usage errors in every mode;
missing scene release context is a validation problem.

Exit codes: 0 ok or nothing to validate, 1 problems found, 2 usage error.
"""

import argparse
import fnmatch
import os
import re
import sys

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from lumlib.schema import SchemaError, load_json_file  # noqa: E402
from validators import Context, RegistryError, discover  # noqa: E402


CONTENT_DIR = "content"
EVIDENCE_DIR = "docs/evidence"
CONTENT_ROOT_REFUSAL = "content: symlink or non-directory is not allowed"
EVIDENCE_ROOT_REFUSAL = "docs/evidence: symlink or non-directory is not allowed"


def _root_refused(path):
    """Return True when PATH is a symlink (dangling included) or exists but is not a directory."""
    if os.path.islink(path):
        return True
    return os.path.exists(path) and not os.path.isdir(path)


def _zone_refusals(root):
    """Return the refusal lines for a zone root that is a symlink or a non-directory."""
    problems = []
    if _root_refused(os.path.join(root, *CONTENT_DIR.split("/"))):
        problems.append(CONTENT_ROOT_REFUSAL)
    if _root_refused(os.path.join(root, *EVIDENCE_DIR.split("/"))):
        problems.append(EVIDENCE_ROOT_REFUSAL)
    return problems


def _is_json_name(name):
    """Return True when the file name ends in .json in any letter case."""
    return name.lower().endswith(".json")


def _rel(root, full):
    return os.path.relpath(full, root).replace(os.sep, "/")


def _zone_files(root, zone, json_only):
    """Return the sorted posix paths of files and symlinks under ROOT/ZONE.

    With json_only, regular files whose names do not end in .json are skipped.
    Symlinks are always kept so that they are refused.
    """
    found = []
    for dirpath, dirnames, filenames in os.walk(os.path.join(root, *zone.split("/"))):
        kept = []
        for name in sorted(dirnames):
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                found.append(_rel(root, full))
            else:
                kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            full = os.path.join(dirpath, name)
            if json_only and not _is_json_name(name) and not os.path.islink(full):
                continue
            found.append(_rel(root, full))
    return sorted(found)


def _all_files(root):
    """Return the sorted posix paths to validate in content/ and docs/evidence/."""
    files = []
    if os.path.isdir(os.path.join(root, *CONTENT_DIR.split("/"))):
        files.extend(_zone_files(root, CONTENT_DIR, json_only=False))
    if os.path.isdir(os.path.join(root, *EVIDENCE_DIR.split("/"))):
        files.extend(_zone_files(root, EVIDENCE_DIR, json_only=True))
    return sorted(files)


def _find_glob(rel, globs):
    for pattern in sorted(globs):
        if fnmatch.fnmatchcase(rel, pattern):
            return globs[pattern]
    return None


def _call(fn, rel, *args):
    """Run a validator; a raised exception becomes a problem instead of a crash."""
    try:
        result = fn(rel, *args)
    except Exception as exc:
        return [f"{rel}: validator raised {type(exc).__name__}: {exc}"]
    if result is None:
        return []
    if not isinstance(result, list):
        return [f"{rel}: validator returned {type(result).__name__}, expected list"]
    return [str(item) for item in result]


def _check_schema(rel, obj, schemas, ctx):
    if not isinstance(obj, dict):
        return [f"{rel}: top level must be a JSON object"]
    if "schema" not in obj:
        return [f"{rel}: missing schema key"]
    schema_id = obj["schema"]
    if not isinstance(schema_id, str):
        return [f"{rel}: schema key must be a string"]
    fn = schemas.get(schema_id)
    if fn is None:
        return [f"{rel}: schema '{schema_id}' is not registered"]
    return _call(fn, rel, obj, ctx)


def _check_entry(root, rel, schemas, globs, ctx):
    full = os.path.join(root, *rel.split("/"))
    if os.path.islink(full):
        return [f"{rel}: symlink refused"]

    is_json = _is_json_name(rel)
    glob_fn = _find_glob(rel, globs)
    if not is_json and glob_fn is None:
        return [f"{rel}: unrecognised content file"]

    try:
        with open(full, "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        return [f"{rel}: cannot read file: {exc.strerror}"]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [f"{rel}: not valid UTF-8 (byte {exc.start})"]

    if not is_json:
        return _call(glob_fn, rel, text, ctx)

    try:
        obj = load_json_file(full)
    except SchemaError as exc:
        return [f"{rel}: {exc}"]
    except RecursionError:
        return [f"{rel}: json nesting is too deep"]
    except Exception as exc:
        return [f"{rel}: cannot load JSON: {exc}"]

    if glob_fn is not None:
        return _call(glob_fn, rel, text, ctx)
    return _check_schema(rel, obj, schemas, ctx)


def validate_tree(root, allow_pending, release, schemas=None, globs=None, *,
                  expected_engine_revision=None, expected_game_revision=None, artifact_root=None):
    """Return the problems found under ROOT/content and ROOT/docs/evidence.

    schemas and globs default to the discovered registry when both are None;
    when only one is None it is treated as empty. Absent zone directories yield
    no problems. A zone root that is a symlink or a non-directory is refused.
    Supplied context is checked even on an empty tree; only scene release
    validators require the optional pins and artifact root to be present.
    """
    if allow_pending and release:
        raise ValueError("allow_pending and release are mutually exclusive")
    problems = _supplied_context_problems(expected_engine_revision, expected_game_revision, artifact_root)
    if problems:
        return problems
    if schemas is None and globs is None:
        schemas, globs = discover()
    schemas = {} if schemas is None else schemas
    globs = {} if globs is None else globs

    root = os.path.abspath(root)
    refusals = _zone_refusals(root)
    if refusals:
        return refusals

    ctx = Context(root=root, allow_pending=bool(allow_pending), release=bool(release),
                  expected_engine_revision=expected_engine_revision,
                  expected_game_revision=expected_game_revision, artifact_root=artifact_root)
    problems = []
    for rel in _all_files(root):
        problems.extend(_check_entry(root, rel, schemas, globs, ctx))
    return problems


def _supplied_context_problems(engine, game, artifact_root):
    problems = []
    for field, value in (("expected_engine_revision", engine), ("expected_game_revision", game)):
        if value is not None and (not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None):
            problems.append("context: %s must be 40 lowercase hex digits" % field)
    if artifact_root is not None:
        try:
            valid = (isinstance(artifact_root, (str, os.PathLike)) and
                     isinstance(os.fspath(artifact_root), str) and bool(os.fspath(artifact_root)) and
                     os.path.isdir(artifact_root))
        except (TypeError, ValueError, OSError):
            valid = False
        if not valid:
            problems.append("context: artifact_root must be a nonempty existing directory")
    return problems


def _revision_arg(value):
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise argparse.ArgumentTypeError("revision must be 40 lowercase hex digits")
    return value


def _artifact_root_arg(value):
    if not value or not os.path.isdir(value):
        raise argparse.ArgumentTypeError("artifact root must be a nonempty existing directory")
    return os.path.abspath(value)


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="validate_content.py",
        description="Validate the game content tree under ROOT/content and the JSON under ROOT/docs/evidence.",
    )
    parser.add_argument(
        "--root", default=".", help="repository root (default: current directory)"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--allow-pending", action="store_true", help="permit entries marked pending"
    )
    mode.add_argument(
        "--release",
        action="store_true",
        help="release gate: refuse pending entries and set release=True for validators",
    )
    parser.add_argument("--expected-engine-revision", type=_revision_arg)
    parser.add_argument("--expected-game-revision", type=_revision_arg)
    parser.add_argument("--artifact-root", type=_artifact_root_arg,
                        help="capture store containing sha256/<capture_sha256>")
    return parser


def main(argv=None):
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"{args.root}: not a directory", file=sys.stderr)
        return 2
    refusals = _zone_refusals(root)
    if refusals:
        for line in refusals:
            print(line)
        return 1
    if not os.path.isdir(os.path.join(root, *CONTENT_DIR.split("/"))) and not _all_files(root):
        print("no content/ directory")
        return 0

    try:
        schemas, globs = discover()
    except RegistryError as exc:
        print(f"validators: {exc}")
        return 1

    problems = validate_tree(
        root,
        allow_pending=args.allow_pending,
        release=args.release,
        schemas=schemas,
        globs=globs,
        expected_engine_revision=args.expected_engine_revision,
        expected_game_revision=args.expected_game_revision,
        artifact_root=args.artifact_root,
    )
    if problems:
        for line in sorted(problems):
            print(line)
        return 1
    print("content ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
