#!/usr/bin/env python3
"""Traversal workload tool: validate, emit, check, and identity.

Workload sources are content/workloads/<id>.json. A committed traversal is
content/workloads/traversal/<id>.traversal and must equal the emitted text of
its pinned, event-free source byte for byte.

Usage:
  python3 -I tools/traversal_tool.py validate [--root DIR] [--allow-pending]
  python3 -I tools/traversal_tool.py emit WORKLOAD_JSON [-o OUT]
  python3 -I tools/traversal_tool.py check [--root DIR]
  python3 -I tools/traversal_tool.py identity PRESET_JSON

Problems are printed as "PATH: reason". Exit codes: 0 ok, 1 invalid, 2 usage error.
"""

import argparse
import os
import sys

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from lumlib import identity  # noqa: E402
from lumlib.schema import SchemaError, load_json_file  # noqa: E402
from validators import workload  # noqa: E402


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="traversal_tool.py",
        description="Validate traversal workload sources and emit committed traversals.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="validate content/workloads")
    validate.add_argument("--root", default=".", help="repository root (default: current directory)")
    validate.add_argument(
        "--allow-pending", action="store_true", help="permit workloads marked pending-discovery"
    )
    validate.set_defaults(func=_cmd_validate)

    emit = sub.add_parser("emit", help="print the .traversal text for a pinned workload")
    emit.add_argument("workload", metavar="WORKLOAD_JSON", help="workload source file")
    emit.add_argument("-o", "--output", help="write to this file instead of stdout")
    emit.set_defaults(func=_cmd_emit)

    check = sub.add_parser("check", help="compare committed traversals with the emitter")
    check.add_argument("--root", default=".", help="repository root (default: current directory)")
    check.set_defaults(func=_cmd_check)

    ident = sub.add_parser("identity", help="print the preset identity of an engine preset file")
    ident.add_argument("preset", metavar="PRESET_JSON", help="engine-format preset file")
    ident.set_defaults(func=_cmd_identity)
    return parser


def _root_dir(value):
    root = os.path.abspath(value)
    if not os.path.isdir(root):
        print("%s: not a directory" % value, file=sys.stderr)
        return None
    return root


def _report(problems, ok_message):
    if problems:
        for line in sorted(problems):
            print(line)
        return 1
    print(ok_message)
    return 0


DEEP_JSON_REASON = "not valid JSON: nesting is too deep"


def _cmd_validate(args):
    root = _root_dir(args.root)
    if root is None:
        return 2
    if not os.path.isdir(os.path.join(root, "content", "workloads")):
        print("no content/workloads/ directory")
        return 0
    try:
        problems = workload.tree_problems(root, allow_pending=args.allow_pending)
    except RecursionError:
        print("%s: %s" % (root, DEEP_JSON_REASON))
        return 1
    return _report(problems, "workloads ok")


def _cmd_check(args):
    root = _root_dir(args.root)
    if root is None:
        return 2
    if not os.path.isdir(os.path.join(root, "content", "workloads")):
        print("no content/workloads/ directory")
        return 0
    try:
        problems = workload.tree_problems(root, allow_pending=True)
    except RecursionError:
        print("%s: %s" % (root, DEEP_JSON_REASON))
        return 1
    return _report(problems, "traversal ok")


def _write_stdout(text):
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(text)
        return
    sys.stdout.flush()
    buffer.write(text.encode("utf-8"))
    buffer.flush()


def _cmd_emit(args):
    path = args.workload
    name = os.path.basename(path)
    if not name.endswith(workload.JSON_SUFFIX):
        print("%s: workload file must end in .json" % path, file=sys.stderr)
        return 2
    stem = name[: -len(workload.JSON_SUFFIX)]
    try:
        obj = load_json_file(path)
    except OSError as exc:
        print("%s: cannot read file: %s" % (path, exc.strerror), file=sys.stderr)
        return 2
    except SchemaError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except RecursionError:
        print("%s: %s" % (path, DEEP_JSON_REASON), file=sys.stderr)
        return 1
    try:
        text = workload.emit_text(obj, stem, path)
    except SchemaError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except workload.WorkloadError as exc:
        print("%s: %s" % (path, exc), file=sys.stderr)
        return 1
    if args.output:
        try:
            with open(args.output, "wb") as handle:
                handle.write(text.encode("utf-8"))
        except OSError as exc:
            print("%s: cannot write file: %s" % (args.output, exc.strerror), file=sys.stderr)
            return 2
        return 0
    _write_stdout(text)
    return 0


def _cmd_identity(args):
    path = args.preset
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        print("%s: cannot read file: %s" % (path, exc.strerror), file=sys.stderr)
        return 2
    if b"\r" in data:
        print("%s: CR is not allowed; use LF newlines" % path)
        return 1
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        print("%s: file is not valid UTF-8" % path)
        return 1
    try:
        obj = identity.loads_strict(text)
    except ValueError as exc:
        print("%s: %s" % (path, exc))
        return 1
    except RecursionError:
        print("%s: %s" % (path, DEEP_JSON_REASON))
        return 1
    if not isinstance(obj, dict):
        print("%s: preset must be a JSON object" % path)
        return 1
    try:
        problems = identity.preset_restrictions(obj)
    except RecursionError:
        print("%s: %s" % (path, DEEP_JSON_REASON))
        return 1
    if problems:
        for problem in problems:
            print("%s: %s" % (path, problem))
        return 1
    print(identity.preset_identity(obj))
    return 0


def main(argv=None):
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
