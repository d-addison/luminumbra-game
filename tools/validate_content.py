#!/usr/bin/env python3
"""Validate the content tree under ROOT/content.

Every .json file is parsed with lumlib.schema.load_json_file. A JSON file whose
path matches a GLOBS pattern is handed to that glob validator and need not carry
a "schema" key. Any other JSON file must be an object whose "schema" key is a
registered schema id. Every non-JSON file must match a GLOBS pattern. Validator
registration lives in the tools/validators package; see its docstring.

Usage:
  python3 -I tools/validate_content.py --root . --allow-pending
  python3 -I tools/validate_content.py --root . --release

Without a flag, entries marked pending are refused. --allow-pending permits
them. --release refuses them and sets release=True in the validator context.

Exit codes: 0 ok or no content/ directory, 1 problems found, 2 usage error.
"""

import argparse
import fnmatch
import os
import sys

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from lumlib.schema import SchemaError, load_json_file  # noqa: E402
from validators import Context, RegistryError, discover  # noqa: E402


def _rel(root, full):
    return os.path.relpath(full, root).replace(os.sep, "/")


def _content_files(root):
    """Return the sorted posix paths of every file and symlink under ROOT/content."""
    found = []
    for dirpath, dirnames, filenames in os.walk(os.path.join(root, "content")):
        kept = []
        for name in sorted(dirnames):
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                found.append(_rel(root, full))
            else:
                kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            found.append(_rel(root, os.path.join(dirpath, name)))
    return sorted(found)


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
        return [f"{rel}: unknown schema {schema_id!r}"]
    return _call(fn, rel, obj, ctx)


def _check_entry(root, rel, schemas, globs, ctx):
    full = os.path.join(root, *rel.split("/"))
    if os.path.islink(full):
        return [f"{rel}: symlink refused"]

    is_json = rel.endswith(".json")
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
    except Exception as exc:
        return [f"{rel}: cannot load JSON: {exc}"]

    if glob_fn is not None:
        return _call(glob_fn, rel, text, ctx)
    return _check_schema(rel, obj, schemas, ctx)


def validate_tree(root, allow_pending, release, schemas=None, globs=None):
    """Return the problems found under ROOT/content.

    schemas and globs default to the discovered registry when both are None;
    when only one is None it is treated as empty. An absent content/ directory
    yields no problems.
    """
    if allow_pending and release:
        raise ValueError("allow_pending and release are mutually exclusive")
    if schemas is None and globs is None:
        schemas, globs = discover()
    schemas = {} if schemas is None else schemas
    globs = {} if globs is None else globs

    root = os.path.abspath(root)
    content = os.path.join(root, "content")
    if os.path.islink(content):
        return ["content: symlink refused"]
    if not os.path.isdir(content):
        return []

    ctx = Context(root=root, allow_pending=bool(allow_pending), release=bool(release))
    problems = []
    for rel in _content_files(root):
        problems.extend(_check_entry(root, rel, schemas, globs, ctx))
    return problems


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="validate_content.py",
        description="Validate the game content tree under ROOT/content.",
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
    if not os.path.isdir(os.path.join(root, "content")):
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
    )
    if problems:
        for line in sorted(problems):
            print(line)
        return 1
    print("content ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
