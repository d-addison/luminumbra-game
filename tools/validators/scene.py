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


def _check_features(path, name, features):
    label = "generation_params.features"
    if not isinstance(features, dict):
        _fail(path, "%s must be an object" % label)
    for key in FEATURE_KEYS:
        if not _is_number(features.get(key)):
            _fail(path, "%s.%s must be a number" % (label, key))
    threshold = features["cave_threshold"]
    if not 0 < threshold < 1:
        _fail(path, "%s.cave_threshold must be in (0, 1)" % label)
    density = features["surface_break_density"]
    if not 0 <= density <= 1:
        _fail(path, "%s.surface_break_density must be in [0, 1]" % label)
    if not features["max_feature_radius"] < features["feature_cell_size"]:
        _fail(
            path,
            "%s.max_feature_radius must be less than feature_cell_size (the loader clamps otherwise)" % label,
        )
    if name == CAVE_DENSE:
        for key, expected in CAVE_DENSE_FEATURES.items():
            if features[key] != expected:
                _fail(path, "%s.%s must be %s for cave_dense" % (label, key, expected))


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
    if not _is_int(obj.get("schema_rev")) or obj["schema_rev"] != PRESET_REV:
        _fail(path, "schema_rev must be 6")
    for key in ("name", "description"):
        if not _is_text(obj.get(key)):
            _fail(path, "%s must be a non-empty string" % key)
    sidecar = PRESET_DIR + "/" + name + IDENTITY_SUFFIX
    if not os.path.isfile(_abs(ctx.root, sidecar)):
        _fail(path, "missing identity sidecar %s" % sidecar)
    params = obj.get("generation_params")
    if not isinstance(params, dict):
        _fail(path, "generation_params must be an object")
    if "features" in params:
        _check_features(path, name, params["features"])


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
    return row["status"]


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


def _check_release(path, obj):
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
        _check_release(path, obj)


def check_scene_set(path, obj, ctx):
    """Validator for luminumbra.game.scene-set.v1 files."""
    try:
        _check_scene_set(path, obj, ctx)
    except (SceneError, SchemaError) as exc:
        return [str(exc)]
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


def check_scene_receipt(path, obj, ctx):
    """Validator for luminumbra.game.scene-receipt.v1 files."""
    try:
        _check_receipt(path, obj, ctx)
    except (SceneError, SchemaError) as exc:
        return [str(exc)]
    return []


SCHEMAS = {
    SCENE_SET_SCHEMA: check_scene_set,
    SCENE_RECEIPT_SCHEMA: check_scene_receipt,
}

GLOBS = {
    PRESET_DIR + "/*" + JSON_SUFFIX: check_preset_file,
}
