"""Validators for distant-world presets, the scene set, and scene receipts.

Presets are engine-format files in content/presets/<name>.json (schema_rev 6,
no added keys). Each preset has a sidecar content/presets/<name>.identity.json
(luminumbra.game.preset-identity.v1) that holds the sha256 of the preset bytes
and the preset identity token. The presets glob owns every file in
content/presets/, sidecars included.

The scene set content/scenes/distant-world.json (luminumbra.game.scene-set.v1)
lists four distance stations, two control fixtures and three far-horizon
coverage rows. A scene receipt (luminumbra.game.scene-receipt.v1) lives in
content/receipts/scene-*.json and binds one native run to one row of the set.

The qualification thresholds are constants copied from the engine contract,
docs/distant-world.md at baseline b56cdba12e425ed2786778d5b02c98ba61466584
(far horizon gate and control fixtures, lines 474-512).

Each checker reports the first rule it finds broken as "PATH: reason".
"""

import hashlib
import json
import math
import os
import posixpath
import re
import struct
from decimal import Decimal

from lumlib import identity, schema
from lumlib.schema import SchemaError

PRESET_DIR = "content/presets"
JSON_SUFFIX = ".json"
IDENTITY_SUFFIX = ".identity.json"
PRESET_REV = 6
IDENTITY_SCHEMA = "luminumbra.game.preset-identity.v1"
IDENTITY_KEYS = frozenset(("schema", "preset", "file_sha256", "preset_identity"))
ENGINE_PRESETS = frozenset(("default", "caverns", "mountains", "archipelago"))
CAVE_DENSE = "cave_dense"
CAVE_DENSE_FEATURES = {"cave_threshold": 0.54, "surface_break_density": 0.55, "max_feature_radius": 52}
FEATURE_KEYS = ("cave_threshold", "surface_break_density", "max_feature_radius", "feature_cell_size")
# Engine defaults (systems/SHIELD_WorldSystem.h) used by the loader when an optional key is omitted.
ENGINE_FEATURE_CELL_SIZE = 128.0
ENGINE_MAX_FEATURE_RADIUS = 60.0
# Keys the engine loader (world/TerrainPresetLoader.cpp) refuses a preset without.
MANDATORY_TERRAIN_KEYS = ("base_frequency", "base_amplitude", "octaves", "persistence", "lacunarity", "height_offset")
MANDATORY_FEATURE_KEYS = ("caves_enabled", "cave_frequency")
# Top-level preset keys: the union of the top-level keys of tests/fixtures/engine-caverns-preset.json
# and tests/fixtures/engine-default-preset.json. Every preset must have exactly these keys.
PRESET_KEYS = frozenset(("name", "description", "schema_rev", "generation_params"))
# Shape of generation_params, written by hand from the two engine fixtures
# tests/fixtures/engine-caverns-preset.json and tests/fixtures/engine-default-preset.json.
# Every key that appears at a path in either fixture is allowed there, with the leaf type the
# fixture gives it. A nested dict is an object with exactly the keys listed. _PAIRS is an array
# of [number, number] pairs. Presets other than cave_dense may omit keys (the engine fills them
# in) but may not add keys or use another leaf type.
_NUMBER = "number"
_INTEGER = "integer"
_BOOL = "bool"
_TEXT = "text"
_PAIRS = "pairs"
PRESET_SHAPE = {
    "terrain": {
        "base_frequency": _NUMBER,
        "base_amplitude": _NUMBER,
        "octaves": _INTEGER,
        "persistence": _NUMBER,
        "lacunarity": _NUMBER,
        "height_offset": _NUMBER,
        "island_mask_enabled": _BOOL,
        "shaping": {
            "continentalness_frequency": _NUMBER,
            "erosion_frequency": _NUMBER,
            "peaks_frequency": _NUMBER,
            "peaks_amplitude": _NUMBER,
            "domain_warp_amplitude": _NUMBER,
            "domain_warp_frequency": _NUMBER,
            "continental_spline": _PAIRS,
            "erosion_spline": _PAIRS,
            "peaks_spline": _PAIRS,
        },
        "hydro": {
            "enabled": _BOOL,
            "iterations": _INTEGER,
            "cell_size_m": _NUMBER,
            "talus_height": _NUMBER,
            "thermal_rate": _NUMBER,
            "solubility": _NUMBER,
            "deposition": _NUMBER,
            "sediment_capacity": _NUMBER,
            "max_offset": _NUMBER,
        },
    },
    "biomes": {
        "table": _TEXT,
        "temperature_frequency": _NUMBER,
        "humidity_frequency": _NUMBER,
        "relief_enabled": _BOOL,
        "relief_strength": _NUMBER,
    },
    "features": {
        "caves_enabled": _BOOL,
        "cave_frequency": _NUMBER,
        "cave_threshold": _NUMBER,
        "cave_carve_value": _NUMBER,
        "spaghetti_frequency": _NUMBER,
        "spaghetti_thickness": _NUMBER,
        "surface_breaks_enabled": _BOOL,
        "surface_break_density": _NUMBER,
        "feature_cell_size": _NUMBER,
        "max_feature_radius": _NUMBER,
        "carve_smoothness": _NUMBER,
        "entrance_min_cap": _NUMBER,
        "rivers_enabled": _BOOL,
        "river_frequency": _NUMBER,
        "river_depth": _NUMBER,
        "river_pv_min": _NUMBER,
        "river_pv_max": _NUMBER,
        "river_max_carve": _NUMBER,
        "lakes_enabled": _BOOL,
        "lake_frequency": _NUMBER,
        "lake_threshold": _NUMBER,
        "lake_depth": _NUMBER,
        "lake_max_carve": _NUMBER,
        "lake_bank_offset": _NUMBER,
        "cliffs_enabled": _BOOL,
        "cliff_frequency": _NUMBER,
        "cliff_threshold": _NUMBER,
        "cliff_step": _NUMBER,
        "structures_enabled": _BOOL,
    },
}
# The exact key set of cave_dense at each object path (dotted from the root), taken from the
# caverns fixture. cave_dense must have these keys and no others at every listed path.
CAVE_DENSE_KEYS = {
    "generation_params": frozenset(("terrain", "biomes", "features")),
    "generation_params.terrain": frozenset(
        (
            "base_frequency",
            "base_amplitude",
            "octaves",
            "persistence",
            "lacunarity",
            "height_offset",
            "shaping",
            "island_mask_enabled",
            "hydro",
        )
    ),
    "generation_params.terrain.shaping": frozenset(
        (
            "continentalness_frequency",
            "erosion_frequency",
            "peaks_frequency",
            "peaks_amplitude",
            "domain_warp_amplitude",
            "domain_warp_frequency",
            "continental_spline",
            "erosion_spline",
            "peaks_spline",
        )
    ),
    "generation_params.terrain.hydro": frozenset(
        (
            "enabled",
            "iterations",
            "cell_size_m",
            "talus_height",
            "thermal_rate",
            "solubility",
            "deposition",
            "sediment_capacity",
            "max_offset",
        )
    ),
    "generation_params.biomes": frozenset(("table", "temperature_frequency", "humidity_frequency", "relief_enabled")),
    "generation_params.features": frozenset(
        (
            "caves_enabled",
            "cave_frequency",
            "cave_threshold",
            "cave_carve_value",
            "spaghetti_frequency",
            "spaghetti_thickness",
            "surface_breaks_enabled",
            "surface_break_density",
            "feature_cell_size",
            "max_feature_radius",
            "carve_smoothness",
            "entrance_min_cap",
            "rivers_enabled",
            "river_frequency",
            "river_depth",
            "river_pv_min",
            "river_pv_max",
            "river_max_carve",
            "lakes_enabled",
            "cliffs_enabled",
            "structures_enabled",
        )
    ),
}

SCENE_DIR = "content/scenes"
SCENE_SET_ID = "distant-world"
SCENE_SET_SCHEMA = "luminumbra.game.scene-set.v1"
SCENE_RECEIPT_SCHEMA = "luminumbra.game.scene-receipt.v1"
RECEIPT_DIR = "content/receipts"
RECEIPT_PREFIX = "scene-"
NATIVE_COMMANDS = "docs/distant-world-scenes.md"
SETTLE_LIMIT_SECONDS = 90
PROFILES = ("quality", "performance")
DISPLAYS = ("3840x1600", "3440x1440")
STATUS_PENDING = "pending-native-discovery"
STATUS_DISCOVERED = "discovered"
STATUS_VALUES = (STATUS_PENDING, STATUS_DISCOVERED)
VERDICTS = ("accepted", "defect-open", "defect-fixed", "waived-with-reason")
RELEASE_VERDICTS = ("accepted", "waived-with-reason")
UNQUALIFIED_VERDICTS = ("defect-open", "waived-with-reason")
ADAPTER_MARK = "RTX 5070 Ti"
SEED = 424242
REQUIREMENTS = {
    "below_horizon_sky_percent_max": 2,
    "seam_bands": 0,
    "outer_edge": False,
    "tiers_complete": True,
}
STATIONS = (
    ("tunnel-interior", "cave_dense", 0),
    ("cave-mouth-2km", "cave_dense", 2000),
    ("arch-8km", "caverns", 8000),
    ("horizon-16km", "default", 16000),
)
CONTROLS = (
    ("empty-tile", "default"),
    ("cave-opening", "cave_dense"),
)
COVERAGE = (
    ("default", "default"),
    ("mountains", "mountains"),
    ("archipelago", "archipelago"),
)

SCENE_SET_KEYS = frozenset(
    (
        "schema",
        "id",
        "description",
        "settle_limit_seconds",
        "profiles",
        "displays",
        "status",
        "stations",
        "coverage",
        "controls",
        "native",
        "discovery_notes",
    )
)
STATION_KEYS = frozenset(
    (
        "id",
        "preset",
        "seed",
        "intent",
        "expected_features",
        "distance_m",
        "pose",
        "status",
        "qualification",
        "dispositions",
    )
)
ROW_KEYS = frozenset(("id", "preset", "seed", "intent", "pose", "status", "qualification", "dispositions"))
POSE_KEYS = frozenset(("x", "y", "z", "yaw", "pitch"))
QUALIFICATION_KEYS = frozenset(("wanted_set_sha256", "coverage_sha256", "tiers", "requirements"))
REQUIREMENT_KEYS = frozenset(REQUIREMENTS)
TIER_KEYS = frozenset(("tier", "complete"))
DISPOSITION_KEYS = frozenset(("verdict", "note"))
DISPOSITION_PROFILE_KEYS = frozenset(PROFILES)
NATIVE_KEYS = frozenset(("commands", "discovery_probe"))
RECEIPT_KEYS = frozenset(
    (
        "schema",
        "scene_set",
        "station",
        "profile",
        "display",
        "settled",
        "settle_seconds",
        "wanted_set_sha256",
        "coverage_sha256",
        "tiers",
        "below_horizon_sky_percent",
        "seam_bands",
        "outer_edge",
        "capture_sha256",
        "scene_identity",
        "preset_identity",
        "content_identity",
        "adapter",
        "engine_revision",
        "game_revision",
        "disposition",
    )
)

_PRESET_NAME_RE = re.compile(r"[a-z0-9_-]+")
_PRESET_IDENTITY_RE = re.compile(r"[0-9a-f]{16}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_REVISION_RE = re.compile(r"[0-9a-f]{40}")
_CONTENT_RE = re.compile(r"[0-9]{1,20}")
_SCENE_IDENTITY_RE = re.compile(r"[A-Za-z0-9._:-]{1,64}")


class SceneError(ValueError):
    """A preset, scene set or receipt rule is broken; the message is 'PATH: reason'."""


def _fail(where, reason):
    raise SceneError("%s: %s" % (where, reason))


def _abs(root, rel):
    return os.path.join(root, *rel.split("/"))


def _stem(path, suffix):
    return posixpath.basename(path)[: -len(suffix)]


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, Decimal):
        return value.is_finite()
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def _is_text(value):
    return isinstance(value, str) and value.strip() != ""


def _matches(pattern, value):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _nullable_hash(value):
    return value is None or _matches(_SHA256_RE, value)


def _reason(exc, full):
    """Strip the 'FULL: ' prefix that lumlib.schema puts on its messages."""
    text = str(exc)
    prefix = full + ": "
    return text[len(prefix):] if text.startswith(prefix) else text


def _load_committed(where, root, rel):
    """Load a committed JSON file under ROOT; a failure is reported against WHERE."""
    full = _abs(root, rel)
    if not os.path.isfile(full):
        _fail(where, "missing %s" % rel)
    try:
        return schema.load_json_file(full)
    except SchemaError as exc:
        _fail(where, "%s is not valid JSON: %s" % (rel, _reason(exc, full)))


# ---------------------------------------------------------------------------
# Presets and identity sidecars (GLOBS content/presets/*.json)
# ---------------------------------------------------------------------------


def _text_rules(where, text):
    if text.startswith("﻿"):
        _fail(where, "byte order mark is not allowed")
    if "\r" in text:
        _fail(where, "CR is not allowed; use LF newlines")


def _as_float32(value, path):
    """Round VALUE through float32 the way the engine stores it; out-of-range values are refused."""
    try:
        return struct.unpack("<f", struct.pack("<f", float(value)))[0]
    except OverflowError:
        _fail(path, "generation_params.features value %s is out of float32 range" % value)


def _check_mandatory(path, params):
    """Refuse a preset the engine loader rejects: the terrain and features objects and their required keys."""
    if "terrain" not in params:
        _fail(path, "generation_params.terrain is required")
    if not isinstance(params["terrain"], dict):
        _fail(path, "generation_params.terrain must be an object")
    for key in MANDATORY_TERRAIN_KEYS:
        if key not in params["terrain"]:
            _fail(path, "generation_params.terrain.%s is required" % key)
    if "features" not in params:
        _fail(path, "generation_params.features is required")
    if not isinstance(params["features"], dict):
        _fail(path, "generation_params.features must be an object")
    for key in MANDATORY_FEATURE_KEYS:
        if key not in params["features"]:
            _fail(path, "generation_params.features.%s is required" % key)


def _check_features(path, name, features):
    label = "generation_params.features"
    if not isinstance(features, dict):
        _fail(path, "%s must be an object" % label)
    if name == CAVE_DENSE:
        for key in CAVE_DENSE_FEATURES:
            if key not in features:
                _fail(path, "%s.%s is missing for cave_dense" % (label, key))
    for key in FEATURE_KEYS:
        if key in features and not _is_number(features[key]):
            _fail(path, "%s.%s must be a number" % (label, key))
    threshold = features.get("cave_threshold")
    if threshold is not None and not 0 < threshold < 1:
        _fail(path, "%s.cave_threshold must be in (0, 1)" % label)
    density = features.get("surface_break_density")
    if density is not None and not 0 <= density <= 1:
        _fail(path, "%s.surface_break_density must be in [0, 1]" % label)
    # The loader clamps when the effective radius is not below the effective cell size, after
    # the values are stored as float32. Omitted keys take the engine defaults.
    radius = _as_float32(features.get("max_feature_radius", ENGINE_MAX_FEATURE_RADIUS), path)
    cell = _as_float32(features.get("feature_cell_size", ENGINE_FEATURE_CELL_SIZE), path)
    if not radius < cell:
        _fail(
            path,
            "%s.max_feature_radius must be less than feature_cell_size (effective values after engine "
            "defaults and float32 conversion; the loader clamps otherwise)" % label,
        )
    if name == CAVE_DENSE:
        for key, expected in CAVE_DENSE_FEATURES.items():
            if features[key] != expected:
                _fail(path, "%s.%s must be %s for cave_dense" % (label, key, expected))


_LEAF_CHECKS = {
    _NUMBER: (_is_number, "a number"),
    _INTEGER: (_is_int, "an integer"),
    _BOOL: (lambda value: isinstance(value, bool), "true or false"),
    _TEXT: (_is_text, "a non-empty string"),
}


def _check_shape(path, label, value, node):
    """Compare VALUE with NODE for every preset: unknown keys, wrong nesting and wrong leaf types fail."""
    if node == _PAIRS:
        if not isinstance(value, list):
            _fail(path, "%s must be an array of [x, y] pairs" % label)
        for index, pair in enumerate(value):
            if not isinstance(pair, list) or len(pair) != 2 or not all(_is_number(item) for item in pair):
                _fail(path, "%s[%d] must be a pair of two numbers" % (label, index))
        return
    if isinstance(node, dict):
        if not isinstance(value, dict):
            _fail(path, "%s must be an object" % label)
        for key in sorted(value):
            if key not in node:
                _fail(path, "%s has unknown key '%s'" % (label, key))
        for key in sorted(value):
            _check_shape(path, label + "." + key, value[key], node[key])
        return
    check, noun = _LEAF_CHECKS[node]
    if not check(value):
        _fail(path, "%s must be %s" % (label, noun))


def _check_cave_dense_keys(path, params):
    """cave_dense must have exactly the caverns key set at every object path it shares with caverns."""
    for dotted, keys in CAVE_DENSE_KEYS.items():
        node = params
        for part in dotted.split(".")[1:]:
            if not isinstance(node.get(part), dict):
                node = None
                break
            node = node[part]
        if node is None:
            continue
        for key in sorted(keys - set(node)):
            _fail(path, "%s is missing key '%s'" % (dotted, key))
        for key in sorted(set(node) - keys):
            _fail(path, "%s has unknown key '%s'" % (dotted, key))


def _check_preset(path, text, ctx):
    _text_rules(path, text)
    try:
        obj = identity.loads_strict(text)
    except ValueError as exc:
        _fail(path, "not valid JSON: %s" % exc)
    if not isinstance(obj, dict):
        _fail(path, "top level must be a JSON object")
    restrictions = identity.preset_restrictions(obj)
    if restrictions:
        _fail(path, "; ".join(restrictions))
    name = _stem(path, JSON_SUFFIX)
    if not _matches(_PRESET_NAME_RE, name):
        _fail(path, "file name must match [a-z0-9_-]+")
    schema.check_keys(obj, PRESET_KEYS, set(), path)
    if not _is_int(obj["schema_rev"]) or obj["schema_rev"] != PRESET_REV:
        _fail(path, "schema_rev must be 6")
    for key in ("name", "description"):
        if not _is_text(obj[key]):
            _fail(path, "%s must be a non-empty string" % key)
    params = obj["generation_params"]
    if not isinstance(params, dict) or not params:
        _fail(path, "generation_params must be a non-empty object")
    _check_mandatory(path, params)
    _check_features(path, name, params["features"])
    _check_shape(path, "generation_params", params, PRESET_SHAPE)
    if name == CAVE_DENSE:
        _check_cave_dense_keys(path, params)
    sidecar = PRESET_DIR + "/" + name + IDENTITY_SUFFIX
    if not os.path.isfile(_abs(ctx.root, sidecar)):
        _fail(path, "missing identity sidecar %s" % sidecar)


def _check_sidecar(path, text, ctx):
    _text_rules(path, text)
    try:
        obj = schema.loads_document(text)
    except ValueError as exc:
        _fail(path, "not valid JSON: %s" % exc)
    schema.check_schema_id(obj, IDENTITY_SCHEMA, path)
    schema.check_keys(obj, IDENTITY_KEYS, set(), path)
    stem = _stem(path, IDENTITY_SUFFIX)
    if not _matches(_PRESET_NAME_RE, stem) or obj["preset"] != stem:
        _fail(path, "preset must equal the file stem '%s'" % stem)
    sibling = PRESET_DIR + "/" + obj["preset"] + JSON_SUFFIX
    sibling_full = _abs(ctx.root, sibling)
    if not os.path.isfile(sibling_full):
        _fail(path, "missing sibling preset %s" % sibling)
    try:
        with open(sibling_full, "rb") as handle:
            raw = handle.read()
    except OSError:
        _fail(path, "cannot read sibling preset %s" % sibling)
    if not _matches(_SHA256_RE, obj["file_sha256"]):
        _fail(path, "file_sha256 must be 64 lowercase hex digits")
    if obj["file_sha256"] != hashlib.sha256(raw).hexdigest():
        _fail(path, "file_sha256 does not match the bytes of %s" % sibling)
    try:
        sibling_text = raw.decode("utf-8")
    except UnicodeDecodeError:
        _fail(path, "sibling preset %s is not valid UTF-8" % sibling)
    try:
        expected = identity.preset_identity(identity.loads_strict(sibling_text))
    except ValueError as exc:
        _fail(path, "sibling preset %s is not a valid preset: %s" % (sibling, exc))
    if not _matches(_PRESET_IDENTITY_RE, obj["preset_identity"]):
        _fail(path, "preset_identity must be 16 lowercase hex digits")
    if obj["preset_identity"] != expected:
        _fail(path, "preset_identity does not match the sibling preset %s" % sibling)


def check_preset_file(path, text, ctx):
    """Validator for content/presets/*.json: presets and their .identity.json sidecars."""
    try:
        if posixpath.dirname(path) != PRESET_DIR:
            _fail(path, "preset files must live in content/presets/")
        if path.endswith(IDENTITY_SUFFIX):
            _check_sidecar(path, text, ctx)
        else:
            _check_preset(path, text, ctx)
    except (SceneError, SchemaError) as exc:
        return [str(exc)]
    except RecursionError:
        return ["%s: json nesting is too deep" % path]
    return []


# ---------------------------------------------------------------------------
# Scene set (content/scenes/<id>.json)
# ---------------------------------------------------------------------------


def _check_status(where, status, ctx):
    if status not in STATUS_VALUES:
        _fail(where, "status must be 'pending-native-discovery' or 'discovered'")
    if status == STATUS_PENDING and not ctx.allow_pending:
        _fail(where, "status pending-native-discovery is not allowed in this mode")


def _check_pose(where, pose, status):
    if status == STATUS_PENDING:
        if pose is not None:
            _fail(where, "pose must be null while status is pending-native-discovery")
        return
    if pose is None:
        _fail(where, "status discovered requires a non-null pose")
    schema.check_keys(pose, POSE_KEYS, set(), where + ": pose")
    for axis in sorted(POSE_KEYS):
        if not _is_number(pose[axis]):
            _fail(where, "pose.%s must be a number" % axis)


def _check_tiers(where, tiers, label):
    if not isinstance(tiers, list):
        _fail(where, "%s must be an array" % label)
    previous = None
    for index, item in enumerate(tiers):
        item_where = "%s: %s[%d]" % (where, label, index)
        schema.check_keys(item, TIER_KEYS, set(), item_where)
        tier = item["tier"]
        if not _is_int(tier) or tier < 0:
            _fail(item_where, "tier must be an integer >= 0")
        if not isinstance(item["complete"], bool):
            _fail(item_where, "complete must be true or false")
        if previous is not None and tier <= previous:
            _fail(where, "%s must be unique and ascending" % label)
        previous = tier


def _check_requirements(where, requirements):
    schema.check_keys(requirements, REQUIREMENT_KEYS, set(), where + ": qualification.requirements")
    for key, expected in REQUIREMENTS.items():
        actual = requirements[key]
        if isinstance(expected, bool):
            ok = actual is expected
        else:
            ok = _is_int(actual) and actual == expected
        if not ok:
            _fail(where, "qualification.requirements.%s must be %s" % (key, json.dumps(expected)))


def _check_qualification(where, qualification):
    schema.check_keys(qualification, QUALIFICATION_KEYS, set(), where + ": qualification")
    for key in ("wanted_set_sha256", "coverage_sha256"):
        if not _nullable_hash(qualification[key]):
            _fail(where, "qualification.%s must be null or 64 lowercase hex digits" % key)
    _check_tiers(where, qualification["tiers"], "qualification.tiers")
    _check_requirements(where, qualification["requirements"])


def _check_disposition(where, label, value):
    schema.check_keys(value, DISPOSITION_KEYS, set(), "%s: %s" % (where, label))
    if value["verdict"] not in VERDICTS:
        _fail(where, "%s.verdict must be one of %s" % (label, ", ".join(VERDICTS)))
    if not _is_text(value["note"]):
        _fail(where, "%s.note must be a non-empty string" % label)


def _check_dispositions(where, dispositions):
    schema.check_keys(dispositions, DISPOSITION_PROFILE_KEYS, set(), where + ": dispositions")
    for profile in PROFILES:
        value = dispositions[profile]
        if value is not None:
            _check_disposition(where, "dispositions.%s" % profile, value)


def _check_row(where, row, keys, row_id, preset, ctx):
    """Check the fields shared by stations, controls and coverage rows; return the status."""
    schema.check_keys(row, keys, set(), where)
    if row["id"] != row_id:
        _fail(where, "id must be '%s'" % row_id)
    if row["preset"] != preset:
        _fail(where, "preset must be '%s'" % preset)
    if not _is_int(row["seed"]) or row["seed"] != SEED:
        _fail(where, "seed must be %d" % SEED)
    if not _is_text(row["intent"]):
        _fail(where, "intent must be a non-empty string")
    _check_status(where, row["status"], ctx)
    _check_pose(where, row["pose"], row["status"])
    _check_qualification(where, row["qualification"])
    _check_dispositions(where, row["dispositions"])
    if row["status"] == STATUS_PENDING:
        _check_pending_evidence(where, row)
    return row["status"]


def _check_pending_evidence(where, row):
    """A pending row carries no native evidence: null hashes, no tiers, null dispositions."""
    qualification = row["qualification"]
    for key in ("wanted_set_sha256", "coverage_sha256"):
        if qualification[key] is not None:
            _fail(where, "qualification.%s must be null while status is pending-native-discovery" % key)
    if qualification["tiers"]:
        _fail(where, "qualification.tiers must be empty while status is pending-native-discovery")
    for profile in PROFILES:
        if row["dispositions"][profile] is not None:
            _fail(where, "dispositions.%s must be null while status is pending-native-discovery" % profile)


def _check_station(where, row, spec, ctx):
    row_id, preset, distance = spec
    status = _check_row(where, row, STATION_KEYS, row_id, preset, ctx)
    if not _is_number(row["distance_m"]) or row["distance_m"] != distance:
        _fail(where, "distance_m must be %d" % distance)
    features = row["expected_features"]
    if not isinstance(features, list) or not features:
        _fail(where, "expected_features must be a non-empty array")
    for index, feature in enumerate(features):
        if not _is_text(feature):
            _fail(where, "expected_features[%d] must be a non-empty string" % index)
    return status


def _check_plain_row(where, row, spec, ctx):
    row_id, preset = spec
    return _check_row(where, row, ROW_KEYS, row_id, preset, ctx)


def _check_group(path, label, rows, expected, ctx, check_row):
    if not isinstance(rows, list):
        _fail(path, "%s must be an array" % label)
    ids = [row.get("id") if isinstance(row, dict) else None for row in rows]
    if len({repr(item) for item in ids}) != len(ids):
        _fail(path, "%s contain a duplicate id" % label)
    if len(rows) != len(expected):
        _fail(path, "%s must contain exactly %d entries" % (label, len(expected)))
    if ids != [spec[0] for spec in expected]:
        _fail(path, "%s must be %s in that order" % (label, ", ".join(spec[0] for spec in expected)))
    statuses = []
    for index, row in enumerate(rows):
        statuses.append(check_row("%s: %s[%d]" % (path, label, index), row, expected[index], ctx))
    return statuses


def _check_notes(path, notes):
    if not isinstance(notes, list) or not notes:
        _fail(path, "discovery_notes must be a non-empty array")
    for index, note in enumerate(notes):
        if not _is_text(note):
            _fail(path, "discovery_notes[%d] must be a non-empty string" % index)
    first = notes[0].lower()
    if "cave opening" not in first or "4 km" not in first:
        _fail(
            path,
            "the first discovery note must state that discovery also records a cave opening "
            "beyond the 4 km noise-cave cutoff",
        )


def _check_release(path, obj, ctx):
    if obj["status"] != STATUS_DISCOVERED:
        _fail(path, "release requires status discovered")
    for label in ("stations", "controls", "coverage"):
        for index, row in enumerate(obj[label]):
            where = "%s: %s[%d]" % (path, label, index)
            if row["pose"] is None:
                _fail(where, "release requires a non-null pose")
            qualification = row["qualification"]
            if qualification["wanted_set_sha256"] is None or qualification["coverage_sha256"] is None:
                _fail(where, "release requires non-null wanted_set_sha256 and coverage_sha256")
            tiers = qualification["tiers"]
            if not tiers:
                _fail(where, "release requires at least one tier")
            if any(not tier["complete"] for tier in tiers):
                _fail(where, "release requires every tier complete")
            for profile in PROFILES:
                disposition = row["dispositions"][profile]
                if disposition is None:
                    _fail(where, "release requires a disposition for %s" % profile)
                if disposition["verdict"] not in RELEASE_VERDICTS:
                    _fail(where, "release refuses verdict '%s' for %s" % (disposition["verdict"], profile))
    _check_native_evidence(path, obj, ctx)


def _check_scene_set(path, obj, ctx):
    schema.check_schema_id(obj, SCENE_SET_SCHEMA, path)
    schema.check_keys(obj, SCENE_SET_KEYS, set(), path)
    if posixpath.dirname(path) != SCENE_DIR or not path.endswith(JSON_SUFFIX):
        _fail(path, "scene sets must live in content/scenes/<id>.json")
    stem = _stem(path, JSON_SUFFIX)
    if not schema.is_kebab(obj["id"]):
        _fail(path, "id must be lowercase kebab-case")
    if obj["id"] != stem:
        _fail(path, "id must equal the file stem '%s'" % stem)
    if obj["id"] != SCENE_SET_ID:
        _fail(path, "id must be '%s'" % SCENE_SET_ID)
    if not _is_text(obj["description"]):
        _fail(path, "description must be a non-empty string")
    if not _is_int(obj["settle_limit_seconds"]) or obj["settle_limit_seconds"] != SETTLE_LIMIT_SECONDS:
        _fail(path, "settle_limit_seconds must be %d" % SETTLE_LIMIT_SECONDS)
    if obj["profiles"] != list(PROFILES):
        _fail(path, "profiles must be exactly [\"quality\", \"performance\"]")
    if obj["displays"] != list(DISPLAYS):
        _fail(path, "displays must be exactly [\"3840x1600\", \"3440x1440\"]")
    _check_status(path, obj["status"], ctx)
    _check_notes(path, obj["discovery_notes"])
    schema.check_keys(obj["native"], NATIVE_KEYS, set(), path + ": native")
    if obj["native"]["commands"] != NATIVE_COMMANDS or obj["native"]["discovery_probe"] != NATIVE_COMMANDS:
        _fail(path, "native.commands and native.discovery_probe must be '%s'" % NATIVE_COMMANDS)

    statuses = []
    statuses += _check_group(path, "stations", obj["stations"], STATIONS, ctx, _check_station)
    statuses += _check_group(path, "controls", obj["controls"], CONTROLS, ctx, _check_plain_row)
    statuses += _check_group(path, "coverage", obj["coverage"], COVERAGE, ctx, _check_plain_row)
    if obj["status"] == STATUS_DISCOVERED and any(status != STATUS_DISCOVERED for status in statuses):
        _fail(path, "status discovered requires every station, control and coverage row to be discovered")
    if ctx.release:
        _check_release(path, obj, ctx)


def check_scene_set(path, obj, ctx):
    """Validator for luminumbra.game.scene-set.v1 files."""
    try:
        _check_scene_set(path, obj, ctx)
    except (SceneError, SchemaError) as exc:
        return [str(exc)]
    except RecursionError:
        return ["%s: json nesting is too deep" % path]
    return []


# ---------------------------------------------------------------------------
# Scene receipts (content/receipts/scene-*.json)
# ---------------------------------------------------------------------------


def _check_receipt_tiers(where, tiers):
    if not isinstance(tiers, list) or not tiers:
        _fail(where, "tiers must be a non-empty array")
    _check_tiers(where, tiers, "tiers")


def _failing_quantities(obj):
    """Return the names of the qualification quantities that fail; empty means qualified."""
    failing = []
    if obj["settled"] is not True:
        failing.append("settled is false")
    for item in obj["tiers"]:
        if item["complete"] is not True:
            failing.append("tier %d is incomplete" % item["tier"])
    sky_max = REQUIREMENTS["below_horizon_sky_percent_max"]
    if obj["below_horizon_sky_percent"] > sky_max:
        failing.append("below_horizon_sky_percent %s exceeds %d" % (obj["below_horizon_sky_percent"], sky_max))
    if obj["seam_bands"] != 0:
        failing.append("seam_bands %d is not 0" % obj["seam_bands"])
    if obj["outer_edge"] is not False:
        failing.append("outer_edge is true")
    return failing


def _check_receipt(path, obj, ctx):
    base = posixpath.basename(path)
    if posixpath.dirname(path) != RECEIPT_DIR or not base.startswith(RECEIPT_PREFIX) or not base.endswith(JSON_SUFFIX):
        _fail(path, "scene receipts must be content/receipts/scene-*.json")
    schema.check_schema_id(obj, SCENE_RECEIPT_SCHEMA, path)
    schema.check_keys(obj, RECEIPT_KEYS, set(), path)
    if obj["scene_set"] != SCENE_SET_ID:
        _fail(path, "scene_set must be '%s'" % SCENE_SET_ID)

    scene_set = _load_committed(path, ctx.root, SCENE_DIR + "/" + SCENE_SET_ID + JSON_SUFFIX)
    presets = {}
    for label in ("stations", "controls", "coverage"):
        rows = scene_set.get(label) if isinstance(scene_set, dict) else None
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict):
                presets[row.get("id")] = row.get("preset")
    station = obj["station"]
    if not isinstance(station, str) or station not in presets:
        _fail(path, "unknown station '%s'" % (station,))

    if obj["profile"] not in PROFILES:
        _fail(path, "profile must be 'quality' or 'performance'")
    if obj["display"] not in DISPLAYS:
        _fail(path, "display must be '3840x1600' or '3440x1440'")
    if not isinstance(obj["settled"], bool):
        _fail(path, "settled must be true or false")
    settle = obj["settle_seconds"]
    if not _is_number(settle) or settle <= 0:
        _fail(path, "settle_seconds must be a number greater than 0")
    if obj["settled"] and settle > SETTLE_LIMIT_SECONDS:
        _fail(path, "settle_seconds must be at most %d when settled" % SETTLE_LIMIT_SECONDS)
    for key in ("wanted_set_sha256", "coverage_sha256", "capture_sha256"):
        if not _matches(_SHA256_RE, obj[key]):
            _fail(path, "%s must be 64 lowercase hex digits" % key)
    _check_receipt_tiers(path, obj["tiers"])
    sky = obj["below_horizon_sky_percent"]
    if not _is_number(sky) or not 0 <= sky <= 100:
        _fail(path, "below_horizon_sky_percent must be a number from 0 to 100")
    if not _is_int(obj["seam_bands"]) or obj["seam_bands"] < 0:
        _fail(path, "seam_bands must be an integer >= 0")
    if not isinstance(obj["outer_edge"], bool):
        _fail(path, "outer_edge must be true or false")
    if not _matches(_SCENE_IDENTITY_RE, obj["scene_identity"]):
        _fail(path, "scene_identity must be 1 to 64 characters from A-Z a-z 0-9 . _ : -")
    if not _matches(_PRESET_IDENTITY_RE, obj["preset_identity"]):
        _fail(path, "preset_identity must be 16 lowercase hex digits")
    if not _matches(_CONTENT_RE, obj["content_identity"]):
        _fail(path, "content_identity must be 1 to 20 decimal digits")
    if not isinstance(obj["adapter"], str) or ADAPTER_MARK not in obj["adapter"]:
        _fail(path, "adapter must name the qualified renderer '%s'" % ADAPTER_MARK)
    for key in ("engine_revision", "game_revision"):
        if not _matches(_REVISION_RE, obj[key]):
            _fail(path, "%s must be 40 lowercase hex digits" % key)
    _check_disposition(path, "disposition", obj["disposition"])

    preset = presets[station]
    if preset not in ENGINE_PRESETS:
        sidecar = PRESET_DIR + "/" + preset + IDENTITY_SUFFIX
        sidecar_data = _load_committed(path, ctx.root, sidecar)
        if not isinstance(sidecar_data, dict) or not _matches(
            _PRESET_IDENTITY_RE, sidecar_data.get("preset_identity")
        ):
            _fail(path, "identity sidecar %s has no valid preset_identity" % sidecar)
        if obj["preset_identity"] != sidecar_data["preset_identity"]:
            _fail(path, "preset_identity does not match the identity sidecar of preset '%s'" % preset)

    failing = _failing_quantities(obj)
    verdict = obj["disposition"]["verdict"]
    if verdict == "accepted" and failing:
        _fail(path, "disposition accepted requires a qualified receipt; failing: %s" % "; ".join(failing))
    if failing and verdict not in UNQUALIFIED_VERDICTS:
        _fail(path, "a receipt that is not qualified must have disposition defect-open or waived-with-reason")
    if ctx.release:
        if failing:
            _fail(path, "release requires a qualified receipt; failing: %s" % "; ".join(failing))
        if verdict not in RELEASE_VERDICTS:
            _fail(path, "release requires disposition accepted or waived-with-reason")


def _receipt_files(ctx):
    full = _abs(ctx.root, RECEIPT_DIR)
    if not os.path.isdir(full):
        return []
    return sorted(
        name for name in os.listdir(full) if name.startswith(RECEIPT_PREFIX) and name.endswith(JSON_SUFFIX)
    )


def _tier_pairs(tiers):
    return [(item["tier"], item["complete"]) for item in tiers]


def _load_receipts(ctx):
    """Check every committed receipt as a release receipt and index it by (station, profile, display)."""
    index = {}
    for name in _receipt_files(ctx):
        rel = RECEIPT_DIR + "/" + name
        try:
            data = _load_committed(rel, ctx.root, rel)
        except RecursionError:
            _fail(rel, "json nesting is too deep")
        _check_receipt(rel, data, ctx)
        key = (data["station"], data["profile"], data["display"])
        if key in index:
            _fail(
                rel,
                "duplicate scene receipt for station '%s' profile '%s' display '%s', also in %s"
                % (key[0], key[1], key[2], index[key][0]),
            )
        index[key] = (rel, data)
    return index


def _check_native_evidence(path, obj, ctx):
    """Release: every row needs one qualified receipt per profile and display, matching the row."""
    receipts = _load_receipts(ctx)
    for label in ("stations", "controls", "coverage"):
        for row in obj[label]:
            row_id = row["id"]
            qualification = row["qualification"]
            identities = {}
            for profile in PROFILES:
                values = set()
                for display in DISPLAYS:
                    key = (row_id, profile, display)
                    if key not in receipts:
                        _fail(
                            path,
                            "release requires a scene receipt for station '%s' profile '%s' display '%s'" % key,
                        )
                    rel, receipt = receipts[key]
                    if receipt["wanted_set_sha256"] != qualification["wanted_set_sha256"]:
                        _fail(rel, "wanted_set_sha256 does not match the scene set row '%s'" % row_id)
                    if receipt["coverage_sha256"] != qualification["coverage_sha256"]:
                        _fail(rel, "coverage_sha256 does not match the scene set row '%s'" % row_id)
                    if _tier_pairs(receipt["tiers"]) != _tier_pairs(qualification["tiers"]):
                        _fail(rel, "tiers do not match the scene set row '%s'" % row_id)
                    values.add(receipt["scene_identity"])
                if len(values) != 1:
                    _fail(
                        path,
                        "release requires one scene_identity for station '%s' profile '%s' across both displays"
                        % (row_id, profile),
                    )
                identities[profile] = values.pop()
            if identities[PROFILES[0]] == identities[PROFILES[1]]:
                _fail(path, "scene_identity must differ between profiles for station '%s'" % row_id)


def check_scene_receipt(path, obj, ctx):
    """Validator for luminumbra.game.scene-receipt.v1 files."""
    try:
        _check_receipt(path, obj, ctx)
    except (SceneError, SchemaError) as exc:
        return [str(exc)]
    except RecursionError:
        return ["%s: json nesting is too deep" % path]
    return []


SCHEMAS = {
    SCENE_SET_SCHEMA: check_scene_set,
    SCENE_RECEIPT_SCHEMA: check_scene_receipt,
}

GLOBS = {
    PRESET_DIR + "/*" + JSON_SUFFIX: check_preset_file,
}
