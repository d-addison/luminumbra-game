"""Validators for camera traversal workloads and traversal receipts.

Workload sources live in content/workloads/<id>.json (schema
luminumbra.game.workload.v1). A committed traversal lives in
content/workloads/traversal/<id>.traversal and must equal the emitter output of
its pinned, event-free source byte for byte. Receipts live in
content/receipts/*.json (schema luminumbra.game.traversal-receipt.v1).

Each checker reports the first rule it finds broken. Problems are returned as
"PATH: reason" lines.
"""

import hashlib
import os
import posixpath
import re
from decimal import ROUND_HALF_EVEN, Context, Decimal

from lumlib import schema, traversal
from lumlib.schema import SchemaError

WORKLOAD_SCHEMA = "luminumbra.game.workload.v1"
RECEIPT_SCHEMA = "luminumbra.game.traversal-receipt.v1"

WORKLOAD_DIR = "content/workloads"
TRAVERSAL_DIR = "content/workloads/traversal"
RECEIPT_DIR = "content/receipts/"
TRAVERSAL_SUFFIX = ".traversal"
JSON_SUFFIX = ".json"

KIND = "camera-traversal"
NATIVE_COMMANDS = "docs/performance-workloads.md"
STATUS_PINNED = "pinned"
STATUS_PENDING = "pending-discovery"
EVENT_KINDS = ("edit", "snapshot")
EDIT_MODES = ("fill", "dig")
MAX_EVENTS = 16
EVENTS_REFUSAL = "events require traversal v2 (owned by the engine acceptance workstream)"
PENDING_EMIT_REFUSAL = "emit refuses pending workloads"

PROFILES = ("quality", "performance")
DISPLAYS = ("3840x1600", "3440x1440")
VERDICTS = ("pass", "fail", "unevaluated")
ADAPTER_MARK = "RTX 5070 Ti"

WORKLOAD_KEYS = frozenset(
    (
        "schema",
        "id",
        "kind",
        "description",
        "preset",
        "seed",
        "duration_seconds",
        "tick_rate",
        "speed_mps",
        "pins",
        "status",
        "points",
        "events",
        "native",
    )
)
PIN_KEYS = frozenset(("preset_identity", "content_identity"))
EDIT_KEYS = frozenset(("id", "tick", "kind", "x", "y", "z", "radius_m", "mode"))
SNAPSHOT_KEYS = frozenset(("id", "tick", "kind"))
NATIVE_KEYS = frozenset(("commands", "receipt"))
RECEIPT_KEYS = frozenset(
    (
        "schema",
        "workload",
        "cell_id",
        "profile",
        "display",
        "report_sha256",
        "verdict",
        "verdict_sha256",
        "traversal_sha256",
        "preset_identity",
        "content_identity",
        "adapter",
        "engine_revision",
        "game_revision",
    )
)

_PRESET_RE = re.compile(r"[a-z0-9_-]+")
_PRESET_IDENTITY_RE = re.compile(r"[0-9a-f]{16}")
_CONTENT_RE = re.compile(r"[0-9]{1,20}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_REVISION_RE = re.compile(r"[0-9a-f]{40}")

# Exact decimal arithmetic for duration * tick_rate; 400 digits covers any
# duration token accepted by _duration (at most 100 characters).
_EXACT = Context(prec=400)
_MAX_DURATION_CHARS = 100
# Same tolerance as traversal.TICK_TOLERANCE (1e-9 ticks), built from a string so
# that no exponent token appears in the source text.
_TICK_SLACK = Decimal("0.000000001")


class WorkloadError(ValueError):
    """A workload or receipt rule is broken; the message is the reason only."""


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _number_text(value, where: str) -> str:
    """Return the plain fixed-point text of a JSON number, refusing bools.

    Exponent tokens never reach this function: lumlib.schema refuses them at parse
    time. Decimals are rendered with format(value, "f") so that 0.00000001 stays
    0.00000001 and is not written as 1E-8.
    """
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise WorkloadError("%s must be a JSON number" % where)
    if isinstance(value, int):
        return str(value)
    return format(value, "f")


def _match(value, pattern, key: str, shape: str) -> None:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise WorkloadError("%s must be %s" % (key, shape))


def _duration(value):
    """Return (source text, expected tick count) for duration_seconds.

    The exact product duration * tick_rate must lie within the engine tolerance of
    an integer count in [1, 18000]; the count is the nearest integer to the product.
    The engine evaluates the same product in binary floating point, so the float
    result must also lie within traversal.TICK_TOLERANCE of that count. Both checks
    run here so that pending and pinned workloads refuse exactly what the engine refuses.
    """
    text = _number_text(value, "duration_seconds")
    if len(text) > _MAX_DURATION_CHARS:
        raise WorkloadError("duration_seconds has too many digits")
    seconds = Decimal(text)
    if seconds <= 0:
        raise WorkloadError("duration_seconds must be greater than 0")
    product = _EXACT.multiply(seconds, Decimal(traversal.REQUIRED_TICK_RATE))
    count = int(product.to_integral_value(rounding=ROUND_HALF_EVEN))
    if not 1 <= count <= traversal.MAX_EXPECTED_TICKS:
        raise WorkloadError("duration_seconds * tick_rate must be in [1, 18000]")
    if abs(_EXACT.subtract(product, Decimal(count))) > _TICK_SLACK:
        raise WorkloadError("duration_seconds * tick_rate must be an integer")
    if abs(float(text) * traversal.REQUIRED_TICK_RATE - count) > traversal.TICK_TOLERANCE:
        raise WorkloadError("duration_seconds * tick_rate must be an integer")
    return text, count


def _point_tokens(row, index: int):
    label = "points[%d]" % index
    if not isinstance(row, list) or len(row) != 5:
        raise WorkloadError("%s must be [x, y, z, yaw, pitch]" % label)
    return tuple(_number_text(value, label) for value in row)


def _check_pins(pins, status: str, where: str) -> None:
    schema.check_keys(pins, PIN_KEYS, set(), "%s: pins" % where)
    preset_identity = pins["preset_identity"]
    content_identity = pins["content_identity"]
    if preset_identity is not None:
        _match(preset_identity, _PRESET_IDENTITY_RE, "pins.preset_identity", "null or 16 lowercase hex digits")
    if content_identity is not None:
        _match(content_identity, _CONTENT_RE, "pins.content_identity", "null or 1 to 20 decimal digits")
    if status == STATUS_PINNED and (preset_identity is None or content_identity is None):
        raise WorkloadError("pinned workload needs both pins")


def _check_points(points, status: str):
    """Return the point rows (None when points is null)."""
    if status == STATUS_PENDING:
        if points is not None:
            raise WorkloadError("pending-discovery workload must have points null")
        return None
    if points is None:
        raise WorkloadError("pinned workload needs points")
    if not isinstance(points, list):
        raise WorkloadError("points must be null or an array")
    if len(points) > traversal.MAX_POINTS:
        raise WorkloadError("points may contain at most 1024 entries")
    if status == STATUS_PINNED and len(points) < traversal.MIN_POINTS:
        raise WorkloadError("pinned workload needs 2 to 1024 points")
    return [_point_tokens(row, index) for index, row in enumerate(points)]


def _check_events(events, expected_ticks: int, status: str, release: bool, where: str) -> None:
    if not isinstance(events, list):
        raise WorkloadError("events must be an array")
    if len(events) > MAX_EVENTS:
        raise WorkloadError("events may contain at most 16 entries")
    seen = set()
    last_tick = 0
    for index, event in enumerate(events):
        label = "%s: events[%d]" % (where, index)
        if not isinstance(event, dict):
            raise WorkloadError("events[%d] must be an object" % index)
        kind = event.get("kind")
        if kind not in EVENT_KINDS:
            raise WorkloadError("events[%d] kind must be 'edit' or 'snapshot'" % index)
        schema.check_keys(event, EDIT_KEYS if kind == "edit" else SNAPSHOT_KEYS, set(), label)
        event_id = event["id"]
        if not schema.is_kebab(event_id):
            raise WorkloadError("events[%d] id must be lowercase kebab-case" % index)
        if event_id in seen:
            raise WorkloadError("events[%d] id '%s' is duplicated" % (index, event_id))
        seen.add(event_id)
        tick = event["tick"]
        if not _is_int(tick) or not 1 <= tick <= expected_ticks:
            raise WorkloadError("events[%d] tick must be an integer in [1, %d]" % (index, expected_ticks))
        if tick <= last_tick:
            raise WorkloadError("events[%d] ticks must be strictly ascending" % index)
        last_tick = tick
        if kind == "edit":
            for axis in ("x", "y", "z"):
                value = event[axis]
                if value is None:
                    if release:
                        raise WorkloadError("events[%d] null coordinates are refused in release mode" % index)
                    if status == STATUS_PINNED:
                        raise WorkloadError("events[%d] null coordinates are refused for a pinned workload" % index)
                else:
                    _number_text(value, "events[%d].%s" % (index, axis))
            radius = _number_text(event["radius_m"], "events[%d].radius_m" % index)
            if Decimal(radius) <= 0:
                raise WorkloadError("events[%d] radius_m must be greater than 0" % index)
            if event["mode"] not in EDIT_MODES:
                raise WorkloadError("events[%d] mode must be 'fill' or 'dig'" % index)


def _receipt_path_ok(value) -> bool:
    if not isinstance(value, str) or not value.startswith(RECEIPT_DIR) or not value.endswith(JSON_SUFFIX):
        return False
    if "\\" in value or value.startswith("/"):
        return False
    parts = value.split("/")
    if any(":" in part for part in parts):
        return False
    return all(part not in ("", ".", "..") for part in parts)


def _check_native(native, where: str, release: bool) -> None:
    schema.check_keys(native, NATIVE_KEYS, set(), "%s: native" % where)
    if native["commands"] != NATIVE_COMMANDS:
        raise WorkloadError("native.commands must be '%s'" % NATIVE_COMMANDS)
    if native["receipt"] is None:
        if release:
            raise WorkloadError("native.receipt must be set in release mode")
    elif not _receipt_path_ok(native["receipt"]):
        raise WorkloadError("native.receipt must be null or a .json path under content/receipts/")


def _point_rows(obj):
    return tuple(_point_tokens(row, index) for index, row in enumerate(obj["points"]))


def _traversal_of(obj) -> traversal.Traversal:
    """Build the lumlib Traversal for a pinned workload source that passed the checks."""
    duration_text, expected_ticks = _duration(obj["duration_seconds"])
    return traversal.Traversal(
        duration=duration_text,
        tick_rate=traversal.REQUIRED_TICK_RATE,
        speed=_number_text(obj["speed_mps"], "speed_mps"),
        seed=obj["seed"],
        preset=obj["preset"],
        preset_revision=traversal.REQUIRED_PRESET_REVISION,
        preset_identity=obj["pins"]["preset_identity"],
        content_identity=obj["pins"]["content_identity"],
        expected_ticks=expected_ticks,
        points=_point_rows(obj),
    )


def _check_release_receipt(rel: str, workload_id: str, root) -> None:
    """Refuse a release-mode receipt that is not a bound, valid file under content/receipts/.

    The receipt must be a direct child of content/receipts/, must resolve (following
    symlinks) to a file inside that directory, must parse strictly, must name this
    workload, and must pass the receipt validator in release mode.
    """
    if root is None:
        raise WorkloadError("native.receipt cannot be resolved without a content root")
    shown = "native.receipt '%s'" % rel
    if posixpath.dirname(rel) != RECEIPT_DIR.rstrip("/"):
        raise WorkloadError("%s must name a file directly under content/receipts/" % shown)
    receipts_abs = os.path.realpath(os.path.join(root, *RECEIPT_DIR.rstrip("/").split("/")))
    full = os.path.join(root, *rel.split("/"))
    real = os.path.realpath(full)
    if not real.startswith(receipts_abs + os.sep):
        raise WorkloadError("%s resolves outside content/receipts/" % shown)
    if not os.path.isfile(real):
        raise WorkloadError("%s does not exist" % shown)
    try:
        receipt = _read_json(real, rel)
    except WorkloadError as exc:
        raise WorkloadError("%s %s" % (shown, exc)) from None
    try:
        schema.check_schema_id(receipt, RECEIPT_SCHEMA, rel)
    except SchemaError as exc:
        raise WorkloadError("%s fails release validation: %s" % (shown, exc)) from None
    if receipt.get("workload") != workload_id:
        raise WorkloadError("%s names workload '%s'" % (shown, receipt.get("workload")))
    try:
        _check_receipt(rel, receipt, root, True)
    except (SchemaError, WorkloadError) as exc:
        raise WorkloadError("%s fails release validation: %s" % (shown, exc)) from None


def check_workload(obj, stem: str, where: str, allow_pending: bool, release: bool, root=None) -> None:
    """Raise SchemaError or WorkloadError for the first rule a workload source breaks.

    ROOT is the content root; release mode needs it to resolve native.receipt.
    """
    schema.check_schema_id(obj, WORKLOAD_SCHEMA, where)
    schema.check_keys(obj, WORKLOAD_KEYS, set(), where)

    if not schema.is_kebab(obj["id"]):
        raise WorkloadError("id must be lowercase kebab-case")
    if obj["id"] != stem:
        raise WorkloadError("id must equal the file stem '%s'" % stem)
    if obj["kind"] != KIND:
        raise WorkloadError("kind must be 'camera-traversal'")
    if not isinstance(obj["description"], str) or not obj["description"].strip():
        raise WorkloadError("description must be a non-empty string")
    if not isinstance(obj["preset"], str) or _PRESET_RE.fullmatch(obj["preset"]) is None:
        raise WorkloadError("preset must be non-empty and use only [a-z0-9_-]")
    seed = obj["seed"]
    if not _is_int(seed) or not 0 <= seed <= traversal.MAX_SEED:
        raise WorkloadError("seed must be an integer in [0, 4294967295]")
    if not _is_int(obj["tick_rate"]) or obj["tick_rate"] != traversal.REQUIRED_TICK_RATE:
        raise WorkloadError("tick_rate must be 30")
    _, expected_ticks = _duration(obj["duration_seconds"])
    speed_text = _number_text(obj["speed_mps"], "speed_mps")
    if Decimal(speed_text) <= 0:
        raise WorkloadError("speed_mps must be greater than 0")

    status = obj["status"]
    if status not in (STATUS_PINNED, STATUS_PENDING):
        raise WorkloadError("status must be 'pinned' or 'pending-discovery'")
    if release and status != STATUS_PINNED:
        raise WorkloadError("release mode requires status 'pinned'")
    if status == STATUS_PENDING and not allow_pending:
        raise WorkloadError("status pending-discovery is not allowed in this mode")

    _check_pins(obj["pins"], status, where)
    _check_points(obj["points"], status)
    _check_events(obj["events"], expected_ticks, status, release, where)
    _check_native(obj["native"], where, release)
    if release and obj["native"]["receipt"] is not None:
        _check_release_receipt(obj["native"]["receipt"], obj["id"], root)

    if status == STATUS_PINNED:
        try:
            traversal.validate(_traversal_of(obj))
        except traversal.TraversalError as exc:
            raise WorkloadError(str(exc)) from None


def _missing_traversal_problem(obj, stem: str, where: str, root):
    """Return the problem line when a pinned, event-free source has no committed traversal.

    Needs ROOT; without a content root (unit-level checks) the file cannot be looked
    up, so no problem is reported. The check applies in every mode.
    """
    if root is None or not isinstance(obj, dict):
        return None
    if obj.get("status") != STATUS_PINNED or obj.get("events"):
        return None
    trav_rel = TRAVERSAL_DIR + "/" + stem + TRAVERSAL_SUFFIX
    if os.path.isfile(os.path.join(root, *trav_rel.split("/"))):
        return None
    return "%s: missing committed traversal %s" % (where, trav_rel)


def workload_problems(obj, stem: str, where: str, allow_pending: bool, release: bool, root=None) -> list:
    """Return the problem lines for a workload source (an empty list when valid).

    This is the single place that reports a missing committed traversal, so the
    registered validator and tree_problems never report it twice.
    """
    problems = []
    try:
        check_workload(obj, stem, where, allow_pending, release, root)
    except SchemaError as exc:
        problems.append(str(exc))
    except WorkloadError as exc:
        problems.append("%s: %s" % (where, exc))
    missing = _missing_traversal_problem(obj, stem, where, root)
    if missing is not None:
        problems.append(missing)
    return problems


def emit_text(obj, stem: str, where: str) -> str:
    """Return the canonical .traversal text for a pinned, event-free workload source."""
    if isinstance(obj, dict) and obj.get("status") == STATUS_PENDING:
        raise WorkloadError(PENDING_EMIT_REFUSAL)
    check_workload(obj, stem, where, allow_pending=False, release=False)
    if obj["events"]:
        raise WorkloadError(EVENTS_REFUSAL)
    try:
        return traversal.emit(_traversal_of(obj))
    except traversal.TraversalError as exc:
        raise WorkloadError(str(exc)) from None


def _os_reason(exc: OSError) -> str:
    """Return a one-line reason for a failed file read (the OS message when present)."""
    return exc.strerror or type(exc).__name__


def _read_json(full: str, rel: str):
    """Load a JSON source; the failure is a WorkloadError whose reason omits the path."""
    try:
        return schema.load_json_file(full)
    except OSError as exc:
        raise WorkloadError("cannot read: %s" % _os_reason(exc)) from None
    except SchemaError as exc:
        text = str(exc)
        prefix = full + ": "
        reason = text[len(prefix):] if text.startswith(prefix) else text
        raise WorkloadError("not valid JSON: %s" % reason) from None
    except RecursionError:
        raise WorkloadError("not valid JSON: nesting is too deep") from None


def traversal_text_problems(rel: str, text: str, root: str) -> list:
    """Return problems for a committed .traversal file at posix path rel."""
    try:
        traversal.parse(text)
    except traversal.TraversalError as exc:
        return ["%s: %s" % (rel, exc)]
    stem = posixpath.basename(rel)[: -len(TRAVERSAL_SUFFIX)]
    source_rel = WORKLOAD_DIR + "/" + stem + JSON_SUFFIX
    source_abs = os.path.join(root, *source_rel.split("/"))
    if not schema.is_kebab(stem) or not os.path.isfile(source_abs):
        return ["%s: no source workload %s" % (rel, source_rel)]
    try:
        source = _read_json(source_abs, source_rel)
        expected = emit_text(source, stem, source_rel)
    except WorkloadError as exc:
        return ["%s: %s" % (source_rel, exc)]
    except SchemaError as exc:
        return [str(exc)]
    if expected != text:
        return ["%s: does not match the emitted source %s" % (rel, source_rel)]
    return []


def tree_problems(root: str, allow_pending: bool, release: bool = False) -> list:
    """Return problems for every workload source and committed traversal under ROOT."""
    problems = []
    workload_dir = os.path.join(root, *WORKLOAD_DIR.split("/"))
    if not os.path.isdir(workload_dir):
        return problems
    try:
        workload_names = sorted(os.listdir(workload_dir))
    except OSError as exc:
        workload_names = []
        problems.append("%s: cannot read: %s" % (WORKLOAD_DIR, _os_reason(exc)))
    for name in workload_names:
        full = os.path.join(workload_dir, name)
        rel = WORKLOAD_DIR + "/" + name
        if name == "traversal" and os.path.isdir(full):
            continue
        if os.path.isdir(full) or not name.endswith(JSON_SUFFIX):
            problems.append("%s: unrecognised workload file" % rel)
            continue
        stem = name[: -len(JSON_SUFFIX)]
        try:
            obj = _read_json(full, rel)
        except WorkloadError as exc:
            problems.append("%s: %s" % (rel, exc))
            continue
        problems.extend(workload_problems(obj, stem, rel, allow_pending, release, root))

    traversal_dir = os.path.join(root, *TRAVERSAL_DIR.split("/"))
    if os.path.isdir(traversal_dir):
        try:
            traversal_names = sorted(os.listdir(traversal_dir))
        except OSError as exc:
            traversal_names = []
            problems.append("%s: cannot read: %s" % (TRAVERSAL_DIR, _os_reason(exc)))
        for name in traversal_names:
            rel = TRAVERSAL_DIR + "/" + name
            full = os.path.join(traversal_dir, name)
            if os.path.isdir(full) or not name.endswith(TRAVERSAL_SUFFIX):
                problems.append("%s: unrecognised traversal file" % rel)
                continue
            try:
                with open(full, "rb") as handle:
                    text = handle.read().decode("utf-8")
            except UnicodeDecodeError:
                problems.append("%s: not valid UTF-8" % rel)
                continue
            except OSError as exc:
                problems.append("%s: cannot read: %s" % (rel, _os_reason(exc)))
                continue
            problems.extend(traversal_text_problems(rel, text, root))
    return problems


def _check_receipt(path: str, obj, root: str, release: bool) -> None:
    schema.check_schema_id(obj, RECEIPT_SCHEMA, path)
    schema.check_keys(obj, RECEIPT_KEYS, set(), path)

    workload_id = obj["workload"]
    if not schema.is_kebab(workload_id):
        raise WorkloadError("workload must be a kebab-case workload id")
    source_abs = os.path.join(root, *(WORKLOAD_DIR + "/" + workload_id + JSON_SUFFIX).split("/"))
    if not os.path.isfile(source_abs):
        raise WorkloadError("unknown workload '%s'" % workload_id)
    source = _read_json(source_abs, WORKLOAD_DIR + "/" + workload_id + JSON_SUFFIX)
    pins = source.get("pins") if isinstance(source, dict) else None
    if not isinstance(pins, dict):
        raise WorkloadError("workload '%s' has no pins object" % workload_id)

    if not isinstance(obj["cell_id"], str) or not obj["cell_id"]:
        raise WorkloadError("cell_id must be a non-empty string")
    if obj["profile"] not in PROFILES:
        raise WorkloadError("profile must be 'quality' or 'performance'")
    if obj["display"] not in DISPLAYS:
        raise WorkloadError("display must be '3840x1600' or '3440x1440'")
    for key in ("report_sha256", "verdict_sha256", "traversal_sha256"):
        _match(obj[key], _SHA256_RE, key, "64 lowercase hex digits")
    if obj["verdict"] not in VERDICTS:
        raise WorkloadError("verdict must be pass, fail, or unevaluated")
    if release and obj["verdict"] != "pass":
        raise WorkloadError("verdict must be pass in release mode")
    _match(obj["preset_identity"], _PRESET_IDENTITY_RE, "preset_identity", "16 lowercase hex digits")
    _match(obj["content_identity"], _CONTENT_RE, "content_identity", "1 to 20 decimal digits")
    if not isinstance(obj["adapter"], str) or ADAPTER_MARK not in obj["adapter"]:
        raise WorkloadError("adapter must name the qualified renderer '%s'" % ADAPTER_MARK)
    _match(obj["engine_revision"], _REVISION_RE, "engine_revision", "40 lowercase hex digits")
    _match(obj["game_revision"], _REVISION_RE, "game_revision", "40 lowercase hex digits")

    for key in ("preset_identity", "content_identity"):
        pin = pins.get(key)
        if pin is not None and obj[key] != pin:
            raise WorkloadError("%s does not match the pin of workload '%s'" % (key, workload_id))

    trav_rel = TRAVERSAL_DIR + "/" + workload_id + TRAVERSAL_SUFFIX
    trav_abs = os.path.join(root, *trav_rel.split("/"))
    if os.path.isfile(trav_abs):
        try:
            with open(trav_abs, "rb") as handle:
                digest = hashlib.sha256(handle.read()).hexdigest()
        except OSError as exc:
            raise WorkloadError("cannot read: %s: %s" % (trav_rel, _os_reason(exc))) from None
        if digest != obj["traversal_sha256"]:
            raise WorkloadError("traversal_sha256 does not match the committed traversal of '%s'" % workload_id)
    elif release:
        raise WorkloadError(
            "traversal_sha256 cannot be checked: missing committed traversal %s"
            % (TRAVERSAL_DIR + "/" + workload_id + TRAVERSAL_SUFFIX)
        )


def check_receipt(path, obj, ctx):
    """Validator for luminumbra.game.traversal-receipt.v1 files."""
    if posixpath.dirname(path) != RECEIPT_DIR.rstrip("/"):
        return ["%s: receipts must live under content/receipts/" % path]
    try:
        _check_receipt(path, obj, ctx.root, ctx.release)
    except SchemaError as exc:
        return [str(exc)]
    except WorkloadError as exc:
        return ["%s: %s" % (path, exc)]
    return []


def check_workload_source(path, obj, ctx):
    """Validator for luminumbra.game.workload.v1 files under content/workloads/."""
    if posixpath.dirname(path) != WORKLOAD_DIR:
        return ["%s: workload sources must live in %s/" % (path, WORKLOAD_DIR)]
    stem = posixpath.basename(path)[: -len(JSON_SUFFIX)]
    return workload_problems(obj, stem, path, ctx.allow_pending, ctx.release, ctx.root)


def check_traversal_file(path, text, ctx):
    """Validator for committed .traversal files under content/workloads/traversal/."""
    return traversal_text_problems(path, text, ctx.root)


SCHEMAS = {
    WORKLOAD_SCHEMA: check_workload_source,
    RECEIPT_SCHEMA: check_receipt,
}

GLOBS = {
    TRAVERSAL_DIR + "/*" + TRAVERSAL_SUFFIX: check_traversal_file,
}
