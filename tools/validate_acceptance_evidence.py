#!/usr/bin/env python3
"""Validate an acceptance evidence bundle (luminumbra.game.acceptance-evidence.v1).

Usage:
  python3 -I -B tools/validate_acceptance_evidence.py BUNDLE.json --structure-only
  python3 -I -B tools/validate_acceptance_evidence.py BUNDLE.json --artifact-root DIR --audio-off-marker TEXT
  python3 -I -B tools/validate_acceptance_evidence.py BUNDLE.json --artifact-root DIR --audio-off-marker TEXT --release

Exactly one of --structure-only or --artifact-root DIR is required. --structure-only
checks the bundle without the artifact store and says so on its last line.
--artifact-root DIR also recomputes every hash the bundle names against
DIR/sha256/<hex> and checks that each audio-off journal contains the marker the
operator supplies with --audio-off-marker TEXT. The marker is required with
--artifact-root and refused with --structure-only. --release adds the release
gate (open defects and open blocking limitations are refused) and requires
--artifact-root.

Exit codes: 0 ok, 1 invalid, 2 usage error. Problems are printed one per line
as PATH: reason, at most 50 lines. Control characters in a printed diagnostic
are backslash-escaped (\\n, \\r, \\t, \\xNN) so that each problem stays on one line.
"""

import argparse
import os
import re
import sys

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from lumlib.schema import SchemaError, load_json_file  # noqa: E402
from validators.acceptance import (  # noqa: E402
    artifact_count,
    marker_problem,
    validate_bundle,
    verify_artifacts,
)

MAX_PROBLEMS = 50
STRUCTURE_ONLY_LINE = "structure-only: artifacts NOT verified"
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_NAMED_ESCAPES = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _escape_control(match):
    char = match.group(0)
    return _NAMED_ESCAPES.get(char) or "\\x%02x" % ord(char)


def _printable(text):
    """Return TEXT with control characters backslash-escaped, so one diagnostic is one line."""
    return _CONTROL.sub(_escape_control, str(text))


def _say(text, stream=None):
    print(_printable(text), file=stream)


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="validate_acceptance_evidence.py",
        description="Validate an acceptance evidence bundle; hashes and counts only.",
    )
    parser.add_argument("bundle", help="evidence bundle JSON file")
    parser.add_argument(
        "--structure-only",
        action="store_true",
        help="validate the bundle structure without checking artifacts",
    )
    parser.add_argument(
        "--artifact-root",
        metavar="DIR",
        help="content-addressed artifact store (DIR/sha256/<hex>) to verify against",
    )
    parser.add_argument(
        "--audio-off-marker",
        metavar="TEXT",
        help="audio-off marker that every audio-off journal must contain; required with --artifact-root",
    )
    parser.add_argument(
        "--release",
        action="store_true",
        help="release gate; requires --artifact-root",
    )
    return parser


def _usage(message):
    _say(message, sys.stderr)
    return 2


def _run(argv):
    args = _build_parser().parse_args(argv)
    if args.release and args.artifact_root is None:
        return _usage("release requires --artifact-root")
    if args.structure_only and args.artifact_root is not None:
        return _usage("--structure-only and --artifact-root are mutually exclusive")
    if not args.structure_only and args.artifact_root is None:
        return _usage("one of --structure-only or --artifact-root DIR is required")
    if args.structure_only and args.audio_off_marker is not None:
        return _usage("--audio-off-marker is not used with --structure-only")
    if args.artifact_root is not None:
        if args.audio_off_marker is None:
            return _usage("--artifact-root requires --audio-off-marker")
        reason = marker_problem(args.audio_off_marker)
        if reason is not None:
            return _usage("--audio-off-marker: %s" % reason)

    try:
        doc = load_json_file(args.bundle)
    except SchemaError as exc:
        _say(exc)
        return 1
    except OSError as exc:
        _say("%s: cannot read file: %s" % (args.bundle, exc.strerror))
        return 1

    problems = validate_bundle(doc, release=args.release)
    if not problems and args.artifact_root is not None:
        problems = verify_artifacts(doc, args.artifact_root, args.audio_off_marker)
    if problems:
        for line in problems[:MAX_PROBLEMS]:
            _say(line)
        return 1
    if args.structure_only:
        print(STRUCTURE_ONLY_LINE)
        return 0
    print("artifacts verified: %d" % artifact_count(doc))
    return 0


def main(argv=None):
    try:
        return _run(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    except Exception as exc:  # never print a traceback for a bundle or store problem
        _say("internal error: %s: %s" % (type(exc).__name__, exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
