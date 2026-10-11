#!/usr/bin/env python3
"""Export game content to the engine's worlds/ layout.

Usage:
  python3 -I tools/export_engine_content.py                   print the manifest only
  python3 -I tools/export_engine_content.py --out DIR         write mapped files under DIR
  python3 -I tools/export_engine_content.py --check ENGINE_ROOT
                                                              compare with an engine tree

The only mapping at v0.3 is content/presets/<name>.json to
worlds/atlas/presets/<name>.json. Identity sidecars (*.identity.json) are not
exported. Every source is run through validators.scene.check_preset_file first,
and any problem refuses the export.

Manifest lines are "sha256  mapped/path" (two spaces), sorted by mapped path.
Files are copied as exact bytes. This tool never writes into an engine tree:
--out and --check are mutually exclusive.

Exit codes: 0 ok, 1 invalid content or differing engine copy, 2 usage error.
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


class ExportError(Exception):
    """A source or path problem; the message is one 'PATH: reason' line."""


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
        if name.endswith(scene.IDENTITY_SUFFIX) or not name.endswith(".json"):
            continue
        rel = source_dir + "/" + name
        if os.path.islink(_abs(root, rel)):
            raise ExportError("%s: symlink refused" % rel)
        stem = name[: -len(".json")]
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


def load_files(root, pairs):
    """Return sorted (mapped, sha256 hex, bytes) triples after the preset validator passes."""
    ctx = Context(root=root, allow_pending=False, release=False)
    problems = []
    files = []
    for source, mapped in pairs:
        data = _read_bytes(source, _abs(root, source))
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            problems.append("%s: not valid UTF-8" % source)
            continue
        problems.extend(scene.check_preset_file(source, text, ctx))
        files.append((mapped, hashlib.sha256(data).hexdigest(), data))
    if problems:
        raise ExportError("\n".join(problems))
    return sorted(files, key=lambda item: item[0])


def manifest_lines(files):
    return ["%s  %s" % (digest, mapped) for mapped, digest, _ in files]


def _git_component_refused(path):
    return ".git" in re.split(r"[\\/]", path)


def write_out(files, out):
    """Write the mapped files under OUT; OUT must be absent or an empty directory."""
    absolute = os.path.abspath(out)
    if _git_component_refused(absolute):
        raise ExportError("%s: refuses to write inside a path with a .git component" % out)
    if os.path.exists(absolute):
        if not os.path.isdir(absolute):
            raise ExportError("%s: not a directory" % out)
        if os.listdir(absolute):
            raise ExportError("%s: output directory is not empty" % out)
    for mapped, _, data in files:
        target = _abs(absolute, mapped)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(data)


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
    if args.check is not None and not os.path.isdir(os.path.abspath(args.check)):
        print("%s: not a directory" % args.check, file=sys.stderr)
        return 2
    if args.out is not None and _git_component_refused(os.path.abspath(args.out)):
        print("%s: refuses to write inside a path with a .git component" % args.out, file=sys.stderr)
        return 2

    try:
        files = load_files(root, collect_sources(root))
    except ExportError as exc:
        print(str(exc))
        return 1

    if args.check is not None:
        problems = check_engine(files, os.path.abspath(args.check))
        for line in problems:
            print(line)
        return 1 if problems else 0

    if args.out is not None:
        try:
            write_out(files, args.out)
        except ExportError as exc:
            print(str(exc), file=sys.stderr)
            return 2

    for line in manifest_lines(files):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
