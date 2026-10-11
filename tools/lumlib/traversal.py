"""Reader and writer for the luminumbra.traversal.v1 text format.

The engine parser is whitespace-token based. This module is stricter: it
accepts only the canonical layout (one record per line, LF newlines, no
blank lines, a single final LF) and only plain decimal number tokens.
"""

import math
import re
from dataclasses import dataclass

HEADER = "luminumbra.traversal.v1"
MAX_BYTES = 1048576
MIN_POINTS = 2
MAX_POINTS = 1024
REQUIRED_TICK_RATE = 30
REQUIRED_PRESET_REVISION = 6
MAX_EXPECTED_TICKS = 18000
MAX_SEED = 4294967295
MAX_COORDINATE = 32000.0
MAX_PITCH = 90.0
TICK_TOLERANCE = 1e-9
LENGTH_TOLERANCE = 1e-9

_NUM_RE = re.compile(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?")
_INT_RE = re.compile(r"-?[0-9]+")
_IDENTITY_RE = re.compile(r"[0-9a-f]{16}")
_CONTENT_RE = re.compile(r"[0-9]{1,20}")
_PRESET_RE = re.compile(r"[a-z0-9_-]+")

# Header keys after the format line, in the required order.
_HEADER_KEYS = (
    "duration_seconds",
    "tick_rate",
    "speed_mps",
    "seed",
    "preset",
    "preset_revision",
    "preset_identity",
    "content_identity",
    "expected_ticks",
    "cold_cache",
    "points",
)


class TraversalError(ValueError):
    """Raised when traversal text or a Traversal value is invalid."""


@dataclass(frozen=True)
class Traversal:
    duration: str
    tick_rate: int
    speed: str
    seed: int
    preset: str
    preset_revision: int
    preset_identity: str
    content_identity: str
    expected_ticks: int
    points: tuple


def _is_num(token) -> bool:
    return isinstance(token, str) and _NUM_RE.fullmatch(token) is not None


def _as_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise TraversalError("non-finite number token '%s'" % token)
    return value


def _distance(a, b) -> float:
    total = 0.0
    for axis in range(3):
        delta = float(a[axis]) - float(b[axis])
        total += delta * delta
    return math.sqrt(total)


def path_length(t: Traversal) -> float:
    """Return the total Euclidean length of the position polyline."""
    total = 0.0
    for previous, current in zip(t.points, t.points[1:]):
        total += _distance(previous[:3], current[:3])
    return total


def validate(t: Traversal) -> None:
    """Raise TraversalError unless ``t`` satisfies every engine and policy rule."""
    if t.tick_rate != REQUIRED_TICK_RATE:
        raise TraversalError("tick_rate must be %d" % REQUIRED_TICK_RATE)
    if t.preset_revision != REQUIRED_PRESET_REVISION:
        raise TraversalError("preset_revision must be %d" % REQUIRED_PRESET_REVISION)
    if not isinstance(t.preset_identity, str) or _IDENTITY_RE.fullmatch(t.preset_identity) is None:
        raise TraversalError("preset_identity must be 16 lowercase hex digits")
    if not isinstance(t.content_identity, str) or _CONTENT_RE.fullmatch(t.content_identity) is None:
        raise TraversalError("content_identity must be 1 to 20 decimal digits")
    if not isinstance(t.seed, int) or isinstance(t.seed, bool) or not 0 <= t.seed <= MAX_SEED:
        raise TraversalError("seed must be an integer in [0, 4294967295]")
    if not isinstance(t.expected_ticks, int) or isinstance(t.expected_ticks, bool):
        raise TraversalError("expected_ticks must be an integer")
    if not 1 <= t.expected_ticks <= MAX_EXPECTED_TICKS:
        raise TraversalError("expected_ticks must be in [1, 18000]")
    if not isinstance(t.preset, str) or _PRESET_RE.fullmatch(t.preset) is None:
        raise TraversalError("preset must be non-empty and use only [a-z0-9_-]")
    if not _is_num(t.duration):
        raise TraversalError("duration_seconds must be a plain decimal number")
    if not _is_num(t.speed):
        raise TraversalError("speed_mps must be a plain decimal number")
    duration = _as_float(t.duration)
    speed = _as_float(t.speed)
    if duration <= 0.0:
        raise TraversalError("duration_seconds must be greater than 0")
    if speed <= 0.0:
        raise TraversalError("speed_mps must be greater than 0")
    if abs(duration * t.tick_rate - t.expected_ticks) > TICK_TOLERANCE:
        raise TraversalError("expected_ticks does not match duration_seconds * tick_rate")

    if not isinstance(t.points, tuple):
        raise TraversalError("points must be a tuple")
    if not MIN_POINTS <= len(t.points) <= MAX_POINTS:
        raise TraversalError("points count must be in [2, 1024]")
    for index, point in enumerate(t.points):
        if not isinstance(point, tuple) or len(point) != 5:
            raise TraversalError("point %d must have 5 fields" % index)
        if not all(_is_num(token) for token in point):
            raise TraversalError("point %d has a non-plain number token" % index)
        values = [_as_float(token) for token in point]
        if any(abs(value) > MAX_COORDINATE for value in values[:3]):
            raise TraversalError("point %d coordinate exceeds 32000" % index)
        if abs(values[4]) >= MAX_PITCH:
            raise TraversalError("point %d pitch must satisfy abs(pitch) < 90" % index)

    for index, (previous, current) in enumerate(zip(t.points, t.points[1:])):
        if _distance(previous[:3], current[:3]) <= 0.0:
            raise TraversalError("segment %d has zero length" % (index + 1))

    if path_length(t) + LENGTH_TOLERANCE < duration * speed:
        raise TraversalError("path length is shorter than duration_seconds * speed_mps")


def parse(text: str) -> Traversal:
    """Parse canonical traversal text and validate the result."""
    if not isinstance(text, str):
        raise TraversalError("text must be a str")
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError:
        raise TraversalError("text is not valid UTF-8") from None
    if len(encoded) > MAX_BYTES:
        raise TraversalError("file exceeds 1 MiB")
    if text.startswith("\ufeff"):
        raise TraversalError("byte order mark is not allowed")
    if "\r" in text:
        raise TraversalError("CR is not allowed; use LF newlines")
    if not text.endswith("\n"):
        raise TraversalError("missing final LF")

    lines = text[:-1].split("\n")
    if any(line == "" for line in lines):
        raise TraversalError("blank lines are not allowed")
    if len(lines) < 1 + len(_HEADER_KEYS):
        raise TraversalError("missing header fields")
    if lines[0] != HEADER:
        raise TraversalError("first line must be '%s'" % HEADER)

    values = {}
    for offset, key in enumerate(_HEADER_KEYS):
        parts = lines[1 + offset].split(" ")
        if len(parts) != 2 or parts[0] != key:
            raise TraversalError("line %d must be '%s <value>'" % (offset + 2, key))
        values[key] = parts[1]

    if values["cold_cache"] != "true":
        raise TraversalError("cold_cache must be true")
    for key in ("tick_rate", "seed", "preset_revision", "expected_ticks", "points"):
        if _INT_RE.fullmatch(values[key]) is None:
            raise TraversalError("%s must be an integer token" % key)
    if not _is_num(values["duration_seconds"]):
        raise TraversalError("duration_seconds must be a plain decimal number")
    if not _is_num(values["speed_mps"]):
        raise TraversalError("speed_mps must be a plain decimal number")

    point_count = int(values["points"])
    point_lines = lines[1 + len(_HEADER_KEYS):]
    if len(point_lines) != point_count:
        raise TraversalError("points count does not match the number of point lines")
    points = []
    for line in point_lines:
        parts = line.split(" ")
        if len(parts) != 6 or parts[0] != "point":
            raise TraversalError("expected 'point X Y Z yaw pitch' line")
        for token in parts[1:]:
            if not _is_num(token):
                raise TraversalError("point has a non-plain number token")
        points.append(tuple(parts[1:]))

    traversal = Traversal(
        duration=values["duration_seconds"],
        tick_rate=int(values["tick_rate"]),
        speed=values["speed_mps"],
        seed=int(values["seed"]),
        preset=values["preset"],
        preset_revision=int(values["preset_revision"]),
        preset_identity=values["preset_identity"],
        content_identity=values["content_identity"],
        expected_ticks=int(values["expected_ticks"]),
        points=tuple(points),
    )
    validate(traversal)
    return traversal


def emit(t: Traversal) -> str:
    """Return the canonical traversal text for a validated Traversal."""
    validate(t)
    lines = [
        HEADER,
        "duration_seconds %s" % t.duration,
        "tick_rate %d" % t.tick_rate,
        "speed_mps %s" % t.speed,
        "seed %d" % t.seed,
        "preset %s" % t.preset,
        "preset_revision %d" % t.preset_revision,
        "preset_identity %s" % t.preset_identity,
        "content_identity %s" % t.content_identity,
        "expected_ticks %d" % t.expected_ticks,
        "cold_cache true",
        "points %d" % len(t.points),
    ]
    for point in t.points:
        lines.append("point %s" % " ".join(point))
    return "\n".join(lines) + "\n"
