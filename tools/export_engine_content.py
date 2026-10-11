#!/usr/bin/env python3
"""Export game content to the engine's worlds/ layout.

Usage:
  python3 -I tools/export_engine_content.py                   print the manifest only
  python3 -I tools/export_engine_content.py --out DIR         write mapped files under DIR
  python3 -I tools/export_engine_content.py --check ENGINE_ROOT
                                                              compare with an engine tree

The only mapping at v0.3 is content/presets/<name>.json to
worlds/atlas/presets/<name>.json. Identity sidecars (*.identity.json) are not
exported, but each preset and its sibling sidecar are validated before anything
else happens; any problem refuses the export. The --out destination is resolved
(symlinks included) and refused when the resolved path has a .git component in
any letter case, or lies inside the content/ tree.

Manifest lines are "sha256  mapped/path" (two spaces), sorted by mapped path.
Files are copied as exact bytes. This tool never writes into an engine tree:
--out and --check are mutually exclusive.

Exit codes: 0 ok; 1 invalid content, a differing or missing engine copy, or an
I/O failure; 2 usage error (bad arguments, a refused --out destination, or a
--check root that does not exist). Failures print one "PATH: reason" line.
"""

import argparse
import hashlib
import os
import re
import sys

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from validators import Context  # noqa: E402
from validators import scene  # noqa: E402

REPO_ROOT = os.path.dirname(_TOOLS_DIR)
MAPPINGS = {"content/presets/{name}.json": "worlds/atlas/presets/{name}.json"}
_NAME_RE = re.compile(r"[a-z0-9_-]+")
_SEPARATORS = re.compile(r"[\\/]")
_GIT_DIR = ".git"
_JSON_SUFFIX = ".json"


class ExportError(Exception):
    """A source, destination or I/O problem; the message is one 'PATH: reason' line."""


def _abs(root, rel):
    return os.path.join(root, *rel.split("/"))


def collect_sources(root):
    """Return sorted (source, mapped) pairs for every non-sidecar preset file under ROOT."""
    source_template, mapped_template = next(iter(MAPPINGS.items()))
    source_dir = os.path.dirname(source_template.format(name="x")).replace(os.sep, "/")
    full_dir = _abs(root, source_dir)
    if not os.path.isdir(full_dir):
        return []
    pairs = []
    for name in sorted(os.listdir(full_dir)):
        if name.endswith(scene.IDENTITY_SUFFIX) or not name.endswith(_JSON_SUFFIX):
            continue
        rel = source_dir + "/" + name
        if os.path.islink(_abs(root, rel)):
            raise ExportError("%s: symlink refused" % rel)
        stem = name[: -len(_JSON_SUFFIX)]
        if not _NAME_RE.fullmatch(stem):
            raise ExportError("%s: file name must match [a-z0-9_-]+" % rel)
        pairs.append((rel, mapped_template.format(name=stem)))
    return pairs


def _read_bytes(rel, full):
    try:
        with open(full, "rb") as handle:
            return handle.read()
    except OSError:
        raise ExportError("%s: cannot read file" % rel) from None


def _sidecar_of(source):
    return source[: -len(_JSON_SUFFIX)] + scene.IDENTITY_SUFFIX


def _validate_text(rel, data, ctx):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return ["%s: not valid UTF-8" % rel]
    return scene.check_preset_file(rel, text, ctx)


def load_files(root, pairs):
    """Return sorted (mapped, sha256 hex, bytes) triples after the preset and sidecar validators pass."""
    ctx = Context(root=root, allow_pending=False, release=False)
    problems = []
    files = []
    for source, mapped in pairs:
        data = _read_bytes(source, _abs(root, source))
        problems.extend(_validate_text(source, data, ctx))
        sidecar = _sidecar_of(source)
        if os.path.isfile(_abs(root, sidecar)):
            problems.extend(_validate_text(sidecar, _read_bytes(sidecar, _abs(root, sidecar)), ctx))
        files.append((mapped, hashlib.sha256(data).hexdigest(), data))
    if problems:
        raise ExportError("\n".join(problems))
    return sorted(files, key=lambda item: item[0])


def manifest_lines(files):
    return ["%s  %s" % (digest, mapped) for mapped, digest, _ in files]


def _key(path):
    """Comparison key: the path normalised for the platform and case-folded."""
    return os.path.normcase(path).casefold()


def _has_git_component(path):
    return any(_key(part) == _GIT_DIR for part in _SEPARATORS.split(path))


def _is_within(path, base):
    inside = _key(path)
    outside = _key(base)
    return inside == outside or inside.startswith(outside.rstrip(os.sep) + os.sep)


def check_destination(out, root):
    """Return the resolved --out path; raise ExportError when the destination is refused.

    The destination is resolved with os.path.realpath, so a symlink that points into a
    .git directory or into content/ is judged by its target, and every component of the
    resolved path is checked, not only the path as typed.
    """
    resolved = os.path.realpath(os.path.abspath(out))
    if _has_git_component(resolved):
        raise ExportError("%s: refuses to write inside a path with a .git component" % out)
    content = os.path.realpath(_abs(root, "content"))
    if _is_within(resolved, content):
        raise ExportError("%s: refuses to write inside the content tree" % out)
    if os.path.exists(resolved):
        if not os.path.isdir(resolved):
            raise ExportError("%s: not a directory" % out)
        if os.listdir(resolved):
            raise ExportError("%s: output directory is not empty" % out)
    return resolved


def write_out(files, destination, label):
    """Write the mapped files under DESTINATION (as resolved by check_destination)."""
    try:
        os.makedirs(destination, exist_ok=True)
        for mapped, _, data in files:
            target = _abs(destination, mapped)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as handle:
                handle.write(data)
    except OSError as exc:
        raise ExportError("%s: cannot write output: %s" % (label, exc.strerror or exc)) from None


def check_engine(files, engine_root):
    """Return one 'PATH: differs|missing' line per mapped file that does not match ENGINE_ROOT."""
    problems = []
    for mapped, _, data in files:
        target = _abs(engine_root, mapped)
        if not os.path.isfile(target):
            problems.append("%s: missing" % mapped)
        elif _read_bytes(mapped, target) != data:
            problems.append("%s: differs" % mapped)
    return problems


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="export_engine_content.py",
        description="Print the engine export manifest, write it to a directory, or check an engine tree.",
    )
    parser.add_argument("--root", default=REPO_ROOT, help="repository root (default: this repository)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--out", metavar="DIR", help="write the mapped files under DIR (must be absent or empty)")
    mode.add_argument("--check", metavar="ENGINE_ROOT", help="compare the mapped files with an engine tree")
    return parser


def main(argv=None):
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print("%s: not a directory" % args.root, file=sys.stderr)
        return 2
    if args.check is not None and not os.path.exists(os.path.abspath(args.check)):
        print("%s: not a directory" % args.check, file=sys.stderr)
        return 2

    destination = None
    if args.out is not None:
        try:
            destination = check_destination(args.out, root)
        except ExportError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        except OSError as exc:
            print("%s: cannot inspect destination: %s" % (args.out, exc.strerror or exc))
            return 1

    try:
        files = load_files(root, collect_sources(root))
    except ExportError as exc:
        print(str(exc))
        return 1
    except OSError as exc:
        print("%s: cannot read content: %s" % (scene.PRESET_DIR, exc.strerror or exc))
        return 1

    if args.check is not None:
        engine = os.path.abspath(args.check)
        if not os.path.isdir(engine):
            print("%s: not a directory" % args.check)
            return 1
        try:
            problems = check_engine(files, engine)
        except ExportError as exc:
            print(str(exc))
            return 1
        except OSError as exc:
            print("%s: cannot compare with engine tree: %s" % (args.check, exc.strerror or exc))
            return 1
        for line in problems:
            print(line)
        return 1 if problems else 0

    if destination is not None:
        try:
            write_out(files, destination, args.out)
        except ExportError as exc:
            print(str(exc))
            return 1

    for line in manifest_lines(files):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
