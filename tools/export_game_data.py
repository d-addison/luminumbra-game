#!/usr/bin/env python3
"""Export a captured H1/H2 bundle to a fresh destination; no engine writes or discovery.

Independent replacement for the deferred #40 exporter. A fresh output directory
is reserved exclusively; one fully staged bundle is then renamed into it.
Runtime bytes are at OUTPUT/bundle/runtime; receipt is outside that runtime tree.
"""

import hashlib
import os
import stat
import sys
import tempfile
from pathlib import Path

_TOOLS = str(Path(__file__).resolve().parent)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from lumlib.diagnostics import SingleLineParser, printable  # noqa: E402
from lumlib.engine_inventory import (INVENTORY_PATH, REVISION_RE, capture_source,
                                     parse_author_bytes, validate_inventory)  # noqa: E402
from lumlib.identity import canonical_bytes, semantic_identity  # noqa: E402
from validators.items import ITEMS_PATH, parse_items  # noqa: E402
from validators.simulation import (POLICY_PATH, POPULATION_PATH, parse_policy,
                                    parse_population)  # noqa: E402

MAPPINGS = ((POLICY_PATH, "data/common/sim/distant_policy.json", parse_policy),
            (POPULATION_PATH, "data/common/sim/region_population.json", parse_population),
            (ITEMS_PATH, "data/common/items/items.json", parse_items))
# Retain H1's receipt wire shape and identifier; file rows now also cover H2.
RECEIPT_SCHEMA = "luminumbra.game.h1-export-receipt.v1"
SEMANTIC_ENCODING = "canonical-integer-json-fnv1a64.v1"


class ExportError(ValueError):
    pass


def _revision(value, kind):
    if not isinstance(value, str) or not REVISION_RE.fullmatch(value):
        raise ExportError(kind + " revision must be independently supplied as 40 lowercase hex digits")


def _rollback_reservation(output, owned):
    """Remove only our same, still-empty reservation; preserve replaced/foreign paths."""
    try:
        current = output.lstat()
        if (stat.S_ISDIR(current.st_mode) and
                (current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino)):
            output.rmdir()  # atomic refusal if somebody added any content
    except OSError:
        pass


def export(root, output, *, engine_revision, game_revision):
    """Validate all captured sources/references before any output mutation."""
    _revision(engine_revision, "engine")
    _revision(game_revision, "game")
    output = Path(output).absolute()
    if os.path.lexists(output):
        raise ExportError("output destination already exists")
    if not output.parent.is_dir():
        raise ExportError("output parent must already be a directory")
    raw_inventory = capture_source(root, INVENTORY_PATH)
    inventory = validate_inventory(parse_author_bytes(raw_inventory, INVENTORY_PATH))
    if engine_revision != inventory["engine_revision"]:
        raise ExportError("engine revision differs from inventory pin; regenerate and review inventory first")
    captured, entries = [], []
    for source, destination, parser in MAPPINGS:
        raw = capture_source(root, source)
        obj = parser(raw, inventory)
        if source == POLICY_PATH and (obj["creature_species"] or obj["plant_species"]):
            raise ExportError("shipping policy overrides must remain empty until DS units/fallbacks are qualified")
        captured.append((destination, raw))
        entries.append({"source": source, "destination": destination, "bytes": len(raw),
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "semantic_identity": semantic_identity(obj)})
    receipt = {"schema": RECEIPT_SCHEMA, "engine_revision": engine_revision,
               "game_revision": game_revision,
               "inventory_sha256": hashlib.sha256(raw_inventory).hexdigest(),
               "semantic_encoding": SEMANTIC_ENCODING, "files": entries}
    # Sibling staging guarantees the final rename stays on the same filesystem.
    with tempfile.TemporaryDirectory(prefix=".h1-export-", dir=output.parent) as staging:
        bundle = Path(staging) / "bundle"
        runtime = bundle / "runtime"
        for destination, raw in captured:
            target = runtime / destination
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        (bundle / "export-receipt.json").write_bytes(canonical_bytes(receipt) + b"\n")
        # mkdir refuses files, directories, symlinks and competing exporters, including
        # a destination created after the initial check. No merge/replace mode exists.
        output.mkdir()
        owned = output.lstat()
        try:
            current = output.lstat()
            if (not stat.S_ISDIR(current.st_mode) or
                    (current.st_dev, current.st_ino) != (owned.st_dev, owned.st_ino) or
                    any(output.iterdir())):
                raise ExportError("output reservation changed before publication")
            os.rename(bundle, output / "bundle")
        except BaseException:
            _rollback_reservation(output, owned)
            raise
    return receipt


def main(argv=None):
    parser = SingleLineParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", required=True)
    parser.add_argument("--engine-revision", required=True)
    parser.add_argument("--game-revision", required=True)
    args = parser.parse_args(argv)
    try:
        receipt = export(args.root, args.output, engine_revision=args.engine_revision,
                         game_revision=args.game_revision)
    except (OSError, ValueError, RecursionError) as exc:
        print("error: " + printable(exc), file=sys.stderr)
        return 1
    print("exported %d files; runtime unqualified; receipt: %s" %
          (len(receipt["files"]), Path(args.output) / "bundle/export-receipt.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
