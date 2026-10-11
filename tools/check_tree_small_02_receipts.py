#!/usr/bin/env python3
"""Check the Tree Small 02 conversion receipt and derive its resource accounting.

The receipt lists the 18 conversion outputs (9 .lmesh and 9 .ltex). The runtime
manifest lists those 18 archive members plus CONVERSION.md, LICENSE.txt,
conversion-receipt.json and source-manifest.json. Every output must appear in
the manifest with the same size and sha256.

All quantities are file and payload sizes derived from the receipt. They are
estimates, not GPU allocations.

Exit status: 0 when everything passes, 1 when a check fails, 2 for usage errors
(bad arguments or unreadable inputs). Problems are printed to stderr as
"PATH: reason" lines.
"""

import argparse
import hashlib
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

_TOOLS_DIR = str(Path(__file__).resolve().parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from lumlib import schema  # noqa: E402
from lumlib.schema import SchemaError  # noqa: E402
from validators import resource_accounting  # noqa: E402

RECEIPT_SCHEMA = "luminumbra.game.asset-conversion.v1"
ACCOUNTING_SCHEMA = resource_accounting.SCHEMA
ENGINE_REVISION = "f18098d72077a4682dae1df96915a4d0c95b6889"
ASSET = "tree-small-02"
SCOPE = "tree-small-02 pack only; file and payload sizes, not GPU allocations"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "assets" / "tree-small-02" / "runtime-manifest.json"

MESH_DIR = "data/models/trees/"
TEXTURE_DIR = "data/textures/models/"
PARTS = ("branches", "leaves", "trunk")
TEXTURE_PARTS = ("branch", "leaves", "trunk")
TEXTURE_KINDS = ("albedo", "arm", "normal")
LODS = (0, 1, 2)

MESH_HEADER = 28
VERTEX_BYTES = 32
INDEX_BYTES = 12
TEXTURE_HEADER = 17
TEXTURE_PAYLOAD = sum(max(1, 512 >> m) ** 2 * 4 for m in range(10))
TEXTURE_FILE = TEXTURE_HEADER + TEXTURE_PAYLOAD

LEAF_SURFACES = 30250
LEAF_TRIANGLES = 60500
LEAF_VERTICES = 121000
RESIDUAL_BOUND = Decimal("0.20")

RECEIPT_FILE_COUNT = 18
MANIFEST_FILE_COUNT = 22
MANIFEST_MEMBERS = ("CONVERSION.md", "LICENSE.txt", "conversion-receipt.json", "source-manifest.json")
RECEIPT_MANIFEST_NAME = "conversion-receipt.json"

ROOT_KEYS = {
    "schema",
    "trimmed",
    "asset",
    "license",
    "engine_revision",
    "processor",
    "source_manifest",
    "converter_script",
    "leaf_fitter",
    "command_roots",
    "commands",
    "files",
}
ROOT_TRIMMED_REQUIRED = {"schema", "trimmed", "asset", "engine_revision", "leaf_fitter", "files"}
LEAF_FITTER_KEYS = {"size", "sha256", "source", "result", "command", "lod_policy"}
RESULT_KEYS = {"leaf_surfaces", "triangles", "maximum_relative_fit_error"}

BEGIN_MARKER = "<!-- accounting:begin -->"
END_MARKER = "<!-- accounting:end -->"

_MESH_RE = re.compile(r"data/models/trees/tree_small_02_(branches|leaves|trunk)(?:\.lod([12]))?\.lmesh")
_SHA_RE = re.compile(r"[0-9a-f]{64}")


def _mesh_path(part, lod):
    suffix = "" if lod == 0 else ".lod%d" % lod
    return "%stree_small_02_%s%s.lmesh" % (MESH_DIR, part, suffix)


def _texture_path(part, kind):
    return "%stree_%s_%s_512.ltex" % (TEXTURE_DIR, part, kind)


EXPECTED_MESHES = {_mesh_path(part, lod) for part in PARTS for lod in LODS}
EXPECTED_TEXTURES = {_texture_path(part, kind) for part in TEXTURE_PARTS for kind in TEXTURE_KINDS}
EXPECTED_OUTPUTS = EXPECTED_MESHES | EXPECTED_TEXTURES

NOTES = (
    "Sizes are file and payload byte counts derived from the conversion receipt, not GPU allocations.",
    "Excluded: texture-array padding, driver and API overhead, separate LOD buffers and other GPU-side "
    "allocations. Measured VRAM is a native item.",
    "Engine-side estimates (static-model textures, impostor textures, forest resource estimates) are in "
    "the engine's docs/v0.3-acceptance.md and are not duplicated here.",
)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _as_decimal(value):
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        return None
    return Decimal(value)


def _mesh_identity(path):
    """Return (part, lod) for an expected mesh path, or None."""
    match = _MESH_RE.fullmatch(path)
    if match is None:
        return None
    return match.group(1), int(match.group(2) or 0)


def _parse_entry(label, index, entry, problems):
    where = "%s: files[%d]" % (label, index)
    try:
        schema.check_keys(entry, {"path", "size", "sha256"}, {"vertices", "triangles", "bounding_sphere"}, where)
    except SchemaError as exc:
        problems.append(str(exc))
        return None
    path = entry["path"]
    if not isinstance(path, str):
        problems.append("%s: path must be a string" % where)
        return None
    if not _is_int(entry["size"]) or entry["size"] < 0:
        problems.append("%s: size must be a non-negative integer" % path)
        return None
    if not isinstance(entry["sha256"], str) or _SHA_RE.fullmatch(entry["sha256"]) is None:
        problems.append("%s: sha256 must be 64 lowercase hex digits" % path)
        return None
    if path.endswith(".lmesh"):
        for key in ("vertices", "triangles"):
            if not _is_int(entry.get(key)) or entry[key] < 0:
                problems.append("%s: %s must be a non-negative integer" % (path, key))
                return None
    return entry


def _check_mesh(path, entry, problems):
    vertices = entry["vertices"]
    triangles = entry["triangles"]
    expected = MESH_HEADER + VERTEX_BYTES * vertices + INDEX_BYTES * triangles
    if entry["size"] != expected:
        problems.append(
            "%s: size %d != %d + %d*%d + %d*%d = %d"
            % (path, entry["size"], MESH_HEADER, VERTEX_BYTES, vertices, INDEX_BYTES, triangles, expected)
        )
    identity = _mesh_identity(path)
    if identity is not None and identity[0] == "leaves":
        if triangles != LEAF_TRIANGLES:
            problems.append("%s: triangles %d, expected %d" % (path, triangles, LEAF_TRIANGLES))
        if vertices != LEAF_VERTICES:
            problems.append("%s: vertices %d, expected %d" % (path, vertices, LEAF_VERTICES))


def _check_root_keys(label, receipt, trimmed, problems):
    required = ROOT_TRIMMED_REQUIRED if trimmed else ROOT_KEYS - {"trimmed"}
    try:
        schema.check_keys(receipt, required, ROOT_KEYS - required, label)
    except SchemaError as exc:
        problems.append(str(exc))


def _check_leaf_fitter(label, receipt, problems):
    if "leaf_fitter" not in receipt:
        return
    leaf = receipt["leaf_fitter"]
    where = "%s: leaf_fitter" % label
    if not isinstance(leaf, dict):
        problems.append("%s: not an object" % where)
        return
    try:
        schema.check_keys(leaf, {"result"}, LEAF_FITTER_KEYS - {"result"}, where)
    except SchemaError as exc:
        problems.append(str(exc))
    if "result" not in leaf:
        return
    result = leaf["result"]
    if not isinstance(result, dict):
        problems.append("%s.result: not an object" % where)
        return
    try:
        schema.check_keys(result, RESULT_KEYS, set(), where + ".result")
    except SchemaError as exc:
        problems.append(str(exc))
        return
    for key, expected in (("leaf_surfaces", LEAF_SURFACES), ("triangles", LEAF_TRIANGLES)):
        value = result[key]
        if not _is_int(value):
            problems.append("%s: leaf_fitter.result.%s must be an integer" % (label, key))
        elif value != expected:
            problems.append("%s: leaf_fitter.result.%s %d, expected %d" % (label, key, value, expected))
    residual = _as_decimal(result["maximum_relative_fit_error"])
    if residual is None:
        problems.append("%s: leaf_fitter.result.maximum_relative_fit_error must be a number" % label)
    elif residual > RESIDUAL_BOUND:
        problems.append(
            "%s: leaf_fitter.result.maximum_relative_fit_error %s exceeds bound %s"
            % (label, result["maximum_relative_fit_error"], RESIDUAL_BOUND)
        )


def _check_manifest(manifest_label, manifest, problems):
    """Return a path -> entry map for the manifest, reporting structural problems."""
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(files, list):
        problems.append("%s: files must be a list" % manifest_label)
        return {}
    if len(files) != MANIFEST_FILE_COUNT:
        problems.append("%s: files has %d entries, expected %d" % (manifest_label, len(files), MANIFEST_FILE_COUNT))
    entries = {}
    for index, entry in enumerate(files):
        path = entry.get("path") if isinstance(entry, dict) else None
        if not isinstance(path, str):
            problems.append("%s: files[%d] has no string path" % (manifest_label, index))
            continue
        if path in entries:
            problems.append("%s: duplicate manifest path %s" % (manifest_label, path))
            continue
        entries[path] = entry
    expected = EXPECTED_OUTPUTS | set(MANIFEST_MEMBERS)
    missing = sorted(expected - set(entries))
    unexpected = sorted(set(entries) - expected)
    if missing:
        problems.append("%s: manifest is missing %s" % (manifest_label, ", ".join(missing)))
    if unexpected:
        problems.append("%s: manifest has unexpected %s" % (manifest_label, ", ".join(unexpected)))
    return entries


def validate(receipt_label, receipt, receipt_bytes, manifest_label, manifest):
    """Return every "PATH: reason" problem for a receipt checked against a manifest.

    Untrimmed receipts are always compared byte-for-byte (size and sha256) with
    the manifest conversion-receipt.json entry. Trimmed receipts are exempt.
    """
    problems = []
    try:
        schema.check_schema_id(receipt, RECEIPT_SCHEMA, receipt_label)
    except SchemaError as exc:
        return [str(exc)]

    trimmed = receipt.get("trimmed", False)
    if not isinstance(trimmed, bool):
        problems.append("%s: trimmed must be a boolean" % receipt_label)
        trimmed = False
    _check_root_keys(receipt_label, receipt, trimmed, problems)
    if receipt.get("engine_revision") != ENGINE_REVISION:
        problems.append(
            "%s: engine_revision %s does not match pinned %s"
            % (receipt_label, receipt.get("engine_revision"), ENGINE_REVISION)
        )

    files = receipt.get("files")
    if not isinstance(files, list):
        problems.append("%s: files must be a list" % receipt_label)
        files = []
    elif len(files) != RECEIPT_FILE_COUNT:
        problems.append("%s: files has %d entries, expected %d" % (receipt_label, len(files), RECEIPT_FILE_COUNT))

    rows = []
    seen = set()
    for index, entry in enumerate(files):
        row = _parse_entry(receipt_label, index, entry, problems)
        if row is None:
            continue
        path = row["path"]
        if path in seen:
            problems.append("%s: duplicate path" % path)
        seen.add(path)
        rows.append(row)

    got = {row["path"] for row in rows}
    missing = sorted(EXPECTED_OUTPUTS - got)
    unexpected = sorted(got - EXPECTED_OUTPUTS)
    if missing or unexpected:
        problems.append(
            "%s: output set mismatch; missing [%s], unexpected [%s]"
            % (receipt_label, ", ".join(missing), ", ".join(unexpected))
        )

    for row in rows:
        path = row["path"]
        if path.endswith(".lmesh") and path in EXPECTED_MESHES:
            _check_mesh(path, row, problems)
        elif path.endswith(".ltex") and path in EXPECTED_TEXTURES:
            if row["size"] != TEXTURE_FILE:
                problems.append("%s: size %d, expected %d" % (path, row["size"], TEXTURE_FILE))

    _check_leaf_fitter(receipt_label, receipt, problems)

    entries = _check_manifest(manifest_label, manifest, problems)
    for row in rows:
        path = row["path"]
        member = entries.get(path)
        if member is None:
            problems.append("%s: not in manifest" % path)
            continue
        if member.get("size") != row["size"]:
            problems.append("%s: size %d does not match manifest %s" % (path, row["size"], member.get("size")))
        if member.get("sha256") != row["sha256"]:
            problems.append("%s: sha256 does not match manifest" % path)
        if path.endswith(".lmesh"):
            for key in ("vertices", "triangles"):
                if member.get(key) != row[key]:
                    problems.append(
                        "%s: %s %d does not match manifest %s" % (path, key, row[key], member.get(key))
                    )

    if not trimmed:
        member = entries.get(RECEIPT_MANIFEST_NAME)
        if member is None:
            problems.append("%s: not in manifest" % RECEIPT_MANIFEST_NAME)
        else:
            if member.get("size") != len(receipt_bytes):
                problems.append(
                    "%s: receipt size %d does not match manifest %s"
                    % (receipt_label, len(receipt_bytes), member.get("size"))
                )
            if member.get("sha256") != hashlib.sha256(receipt_bytes).hexdigest():
                problems.append("%s: receipt sha256 does not match manifest entry" % receipt_label)
    return problems


def build_accounting(receipt, receipt_bytes):
    """Build the resource-accounting object from a receipt that passed validate()."""
    trimmed = receipt.get("trimmed", False) is True
    source_sha = None if trimmed else hashlib.sha256(receipt_bytes).hexdigest()
    meshes = []
    textures = []
    for entry in receipt["files"]:
        path = entry["path"]
        if path.endswith(".lmesh"):
            part, lod = _mesh_identity(path)
            vertices = entry["vertices"]
            triangles = entry["triangles"]
            meshes.append(
                {
                    "path": path,
                    "lod": lod,
                    "part": part,
                    "vertices": vertices,
                    "triangles": triangles,
                    "vertex_bytes": VERTEX_BYTES * vertices,
                    "index_bytes": INDEX_BYTES * triangles,
                    "header_bytes": MESH_HEADER,
                    "file_bytes": entry["size"],
                    "basis": "estimated",
                }
            )
        elif path.endswith(".ltex"):
            textures.append(
                {
                    "path": path,
                    "file_bytes": entry["size"],
                    "header_bytes": TEXTURE_HEADER,
                    "payload_bytes": TEXTURE_PAYLOAD,
                    "basis": "estimated",
                }
            )
    meshes.sort(key=lambda row: (PARTS.index(row["part"]), row["lod"]))
    textures.sort(key=lambda row: row["path"])
    result = receipt["leaf_fitter"]["result"]
    residual = result["maximum_relative_fit_error"]
    return {
        "schema": ACCOUNTING_SCHEMA,
        "asset": ASSET,
        "scope": SCOPE,
        "engine_revision": ENGINE_REVISION,
        "source_receipt": {"schema": RECEIPT_SCHEMA, "sha256": source_sha},
        "meshes": meshes,
        "textures": textures,
        "totals": {
            "mesh_file_bytes": sum(row["file_bytes"] for row in meshes),
            "mesh_triangles_by_lod": {
                "lod%d" % lod: sum(row["triangles"] for row in meshes if row["lod"] == lod) for lod in LODS
            },
            "texture_file_bytes": sum(row["file_bytes"] for row in textures),
            "texture_payload_bytes": sum(row["payload_bytes"] for row in textures),
            "leaf_surfaces": result["leaf_surfaces"],
        },
        "measured": [],
        "notes": list(NOTES)
        + ["Leaf fitter maximum relative fit error %s of the leaf bounding-box diagonal (refusal bound 0.20)." % residual],
    }


def render_json(accounting):
    return json.dumps(accounting, indent=2) + "\n"


def render_doc_table(accounting):
    lines = [
        "| Part | LOD | Vertices | Triangles | File bytes |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in accounting["meshes"]:
        lines.append(
            "| %s | %d | %d | %d | %d |"
            % (row["part"], row["lod"], row["vertices"], row["triangles"], row["file_bytes"])
        )
    return "\n".join(lines) + "\n"


def check_json(path, text):
    """Require the file at path to equal the regenerated JSON and to pass the accounting validator."""
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        return ["%s: cannot read (%s)" % (path, exc.strerror)]
    try:
        committed = schema.load_json_file(path)
    except SchemaError as exc:
        return [str(exc)]
    problems = []
    if data != text.encode("utf-8"):
        problems.append("%s: does not match the regenerated accounting JSON" % path)
    try:
        problems.extend(resource_accounting.validate(str(path), committed))
    except Exception as exc:  # malformed input must become a controlled problem, never a traceback
        problems.append("%s: malformed resource accounting (%s)" % (path, exc.__class__.__name__))
    return problems


def check_doc(path, table):
    """Require the single accounting block in the document to equal the generated table."""
    try:
        text = Path(path).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return ["%s: cannot read as UTF-8 (%s)" % (path, exc)]
    lines = text.split("\n")
    begins = [index for index, line in enumerate(lines) if line == BEGIN_MARKER]
    ends = [index for index, line in enumerate(lines) if line == END_MARKER]
    if len(begins) != 1 or len(ends) != 1:
        return ["%s: expected exactly one %s and one %s marker" % (path, BEGIN_MARKER, END_MARKER)]
    begin, end = begins[0], ends[0]
    if end <= begin:
        return ["%s: end marker precedes begin marker" % path]
    block = "\n".join(lines[begin + 1 : end]) + "\n"
    if block != table:
        return ["%s: accounting block does not match the generated table (regenerate with --emit-doc-table)" % path]
    return []


def _build_parser():
    parser = argparse.ArgumentParser(
        description="Check the Tree Small 02 conversion receipt and derive its resource accounting."
    )
    parser.add_argument("--receipt", required=True, help="conversion receipt JSON")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="runtime manifest JSON")
    parser.add_argument(
        "--full",
        action="store_true",
        help="accepted for compatibility; untrimmed receipts are always checked against the "
        "manifest conversion-receipt.json entry",
    )
    parser.add_argument("--emit-json", metavar="PATH", help="write the resource accounting JSON to PATH")
    parser.add_argument(
        "--check-json", metavar="PATH", help="require PATH to equal the regenerated accounting JSON byte for byte"
    )
    parser.add_argument("--emit-doc-table", action="store_true", help="print the generated markdown table")
    parser.add_argument(
        "--check-doc", metavar="PATH", help="require the accounting block in PATH to equal the generated table"
    )
    return parser


def _report(problems):
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1


def main(argv=None):
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    receipt_path = Path(args.receipt)
    manifest_path = Path(args.manifest)
    try:
        receipt_bytes = receipt_path.read_bytes()
    except OSError as exc:
        print("%s: cannot read (%s)" % (receipt_path, exc.strerror), file=sys.stderr)
        return 2
    try:
        manifest_path.read_bytes()
    except OSError as exc:
        print("%s: cannot read (%s)" % (manifest_path, exc.strerror), file=sys.stderr)
        return 2
    try:
        receipt = schema.load_json_file(receipt_path)
        manifest = schema.load_json_file(manifest_path)
    except SchemaError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    problems = validate(str(receipt_path), receipt, receipt_bytes, str(manifest_path), manifest)
    if problems:
        return _report(problems)

    accounting = build_accounting(receipt, receipt_bytes)
    text = render_json(accounting)
    table = render_doc_table(accounting)

    if args.emit_json:
        Path(args.emit_json).write_bytes(text.encode("utf-8"))
    if args.check_json:
        problems = check_json(args.check_json, text)
        if problems:
            return _report(problems)
    if args.emit_doc_table:
        sys.stdout.flush()
        sys.stdout.buffer.write(table.encode("utf-8"))
        sys.stdout.buffer.flush()
    if args.check_doc:
        problems = check_doc(args.check_doc, table)
        if problems:
            return _report(problems)
    return 0


if __name__ == "__main__":
    sys.exit(main())
