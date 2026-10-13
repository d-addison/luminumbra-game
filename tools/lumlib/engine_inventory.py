"""Public authoring inventory and bounded captured-file reads; no engine checkout needed."""

import hashlib
import os
import re
import stat
from pathlib import Path

from lumlib.schema import SchemaError, check_keys, check_schema_id, load_json_bytes
from lumlib.species_identity import resolved_species

MAX_DOCUMENT_BYTES = 1048576
INVENTORY_SCHEMA = "luminumbra.game.engine-inventory.v1"
INVENTORY_PATH = "tools/lumlib/engine_inventory.json"
REVISION_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")


def read_captured(path, *, optional=False):
    """Read one regular, nonsymlink file once, bounded even if it grows.

    Only a clean missing leaf is optional. Errors and nonregular files refuse.
    """
    path = Path(path)
    try:
        status = path.lstat()
    except FileNotFoundError:
        if optional and path.parent.is_dir():
            return None
        raise SchemaError("%s: missing file" % path) from None
    if not stat.S_ISREG(status.st_mode):
        raise SchemaError("%s: not a regular file" % path)
    if status.st_size > MAX_DOCUMENT_BYTES:
        raise SchemaError("%s: exceeds byte limit" % path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        with os.fdopen(os.open(path, flags), "rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise SchemaError("%s: not a regular file" % path)
            raw = handle.read(MAX_DOCUMENT_BYTES + 1)
    except OSError as exc:
        raise SchemaError("%s: cannot read file: %s" % (path, exc)) from None
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise SchemaError("%s: exceeds byte limit" % path)
    return raw


def capture_source(root, relative):
    """Refuse symlink components in a fixed repo-relative source mapping."""
    path = Path(root)
    for part in relative.split("/"):
        path = path / part
        if path.is_symlink():
            raise SchemaError("%s: symlink refused" % relative)
    return read_captured(path)


def parse_author_bytes(raw, where):
    return load_json_bytes(raw, where, max_bytes=MAX_DOCUMENT_BYTES, final_lf=True)


def _source(row, expected):
    if row["source"] != expected:
        raise SchemaError("inventory: unexpected source path")
    if not isinstance(row["sha256"], str) or not SHA256_RE.fullmatch(row["sha256"]):
        raise SchemaError("inventory: invalid source SHA-256")


def validate_inventory(obj):
    """Resolve the whole pin before validating even an empty override document."""
    check_schema_id(obj, INVENTORY_SCHEMA, "inventory")
    check_keys(obj, {"schema", "engine_revision", "creatures", "plants", "biomes"}, set(), "inventory")
    if not isinstance(obj["engine_revision"], str) or not REVISION_RE.fullmatch(obj["engine_revision"]):
        raise SchemaError("inventory: invalid engine revision")
    for kind, directory in (("creatures", "creatures"), ("plants", "foliage")):
        rows = obj[kind]
        if not isinstance(rows, list) or not rows:
            raise SchemaError("inventory: %s must be a nonempty list" % kind)
        names = []
        for row in rows:
            check_keys(row, {"name", "source", "sha256", "species_id"}, set(), "inventory " + kind)
            if not isinstance(row["name"], str) or not re.fullmatch(r"[a-z0-9_]+", row["name"]):
                raise SchemaError("inventory: species name must match exact engine name syntax")
            names.append(row["name"])
        ids = resolved_species(names)
        if names != sorted(names):
            raise SchemaError("inventory: species must be sorted by exact name")
        for row in rows:
            _source(row, "data/common/%s/species/%s.json" % (directory, row["name"]))
            if type(row["species_id"]) is not int or row["species_id"] != ids[row["name"]]:
                raise SchemaError("inventory: species ID mismatch for '%s'" % row["name"])
    biomes = obj["biomes"]
    check_keys(biomes, {"source", "sha256", "entries"}, set(), "inventory biomes")
    _source(biomes, "data/common/biomes.json")
    if not isinstance(biomes["entries"], list) or not biomes["entries"]:
        raise SchemaError("inventory: biomes must be a nonempty list")
    names, ids = [], []
    for row in biomes["entries"]:
        check_keys(row, {"name", "id"}, set(), "inventory biome")
        if not isinstance(row["name"], str) or not row["name"] or "\0" in row["name"]:
            raise SchemaError("inventory: invalid biome name")
        if type(row["id"]) is not int or not 0 <= row["id"] <= 254:
            raise SchemaError("inventory: invalid biome ID")
        names.append(row["name"])
        ids.append(row["id"])
    if len(set(names)) != len(names) or len(set(ids)) != len(ids) or names != sorted(names):
        raise SchemaError("inventory: duplicate or unsorted biomes")
    return obj


def load_inventory(root):
    raw = capture_source(root, INVENTORY_PATH)
    return validate_inventory(parse_author_bytes(raw, INVENTORY_PATH))


def verify_engine_sources(inventory, engine_root):
    """Explicit read-only refresh check against ALL files in the named engine pin.

    Caller verifies checkout revision; this checks complete species sets, hashes,
    names/IDs and biome entries without trusting lenient engine registries.
    """
    validate_inventory(inventory)
    for kind, directory in (("creatures", "creatures"), ("plants", "foliage")):
        prefix = "data/common/%s/species" % directory
        actual = {p.name for p in (Path(engine_root) / prefix).iterdir()}
        expected = {row["name"] + ".json" for row in inventory[kind]}
        if actual != expected:
            raise SchemaError("inventory: complete %s file set changed" % kind)
        for row in inventory[kind]:
            raw = capture_source(engine_root, row["source"])
            if hashlib.sha256(raw).hexdigest() != row["sha256"]:
                raise SchemaError("inventory: source hash mismatch: " + row["source"])
            # Engine source data predates authoring final-LF requirements.
            obj = load_json_bytes(raw, row["source"])
            if obj.get("id") != row["name"]:
                raise SchemaError("inventory: source name mismatch")
    row = inventory["biomes"]
    raw = capture_source(engine_root, row["source"])
    if hashlib.sha256(raw).hexdigest() != row["sha256"]:
        raise SchemaError("inventory: biome source hash mismatch")
    entries = sorted(({"name": b["name"], "id": b["id"]}
                      for b in load_json_bytes(raw)["biomes"]), key=lambda b: b["name"])
    if entries != row["entries"]:
        raise SchemaError("inventory: biome entries mismatch")
