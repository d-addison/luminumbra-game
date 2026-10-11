"""Canonical JSON, FNV-1a hashing, and preset identity tokens.

The preset identity is the 16-hex-digit FNV-1a 64-bit hash of the canonical
JSON encoding of a preset object. Presets are restricted to a value space
where the canonical encoding is unambiguous across Python and the engine.
"""

import json
import math

FNV64_OFFSET = 14695981039346656037
FNV64_PRIME = 1099511628211
FNV32_OFFSET = 2166136261
FNV32_PRIME = 16777619

_MASK64 = (1 << 64) - 1
_MASK32 = (1 << 32) - 1
_MAX_SAFE_INT = 2 ** 53
_MIN_ABS_FLOAT = 1e-4
_MAX_ABS_FLOAT = 1e15


def fnv1a64(data: bytes) -> int:
    """Return the 64-bit FNV-1a hash of ``data``."""
    value = FNV64_OFFSET
    for byte in data:
        value ^= byte
        value = (value * FNV64_PRIME) & _MASK64
    return value


def fnv1a32(data: bytes) -> int:
    """Return the 32-bit FNV-1a hash of ``data``."""
    value = FNV32_OFFSET
    for byte in data:
        value ^= byte
        value = (value * FNV32_PRIME) & _MASK32
    return value


def canonical_json(obj) -> str:
    """Return the canonical JSON text: sorted keys, compact separators, raw UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_bytes(obj) -> bytes:
    """Return the canonical JSON text encoded as UTF-8."""
    return canonical_json(obj).encode("utf-8")


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key '%s'" % key)
        result[key] = value
    return result


def _reject_constant(name):
    raise ValueError("non-finite number '%s' is not allowed" % name)


def _parse_float(token):
    # Exponent tokens are refused at parse time, including integers written with an
    # exponent (1e0), because the json module sends them to parse_float.
    if "e" in token or "E" in token:
        raise ValueError("exponent number '%s' is not allowed" % token)
    return float(token)


def loads_strict(text: str):
    """Parse JSON text, rejecting duplicate keys, NaN/Infinity, exponent tokens, and a leading BOM."""
    if text.startswith("\ufeff"):
        raise ValueError("byte order mark is not allowed")
    return json.loads(
        text,
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_constant,
        parse_float=_parse_float,
    )


def preset_restrictions(obj) -> list:
    """Return ``path: reason`` problems for values outside the preset value space."""
    problems = []
    _walk(obj, "$", problems)
    return problems


def _walk(value, path, problems):
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        _check_text(value, path, "string", problems)
        return
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = "%s.%s" % (path, key)
            _check_text(key, child_path, "key", problems)
            _walk(child, child_path, problems)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _walk(child, "%s[%d]" % (path, index), problems)
        return
    if isinstance(value, float):
        _check_float(value, path, problems)
        return
    if isinstance(value, int):
        if abs(value) > _MAX_SAFE_INT:
            problems.append("%s: integer outside +-2**53" % path)
        return
    problems.append("%s: unsupported type %s" % (path, type(value).__name__))


def _check_text(text, path, what, problems):
    # Non-ASCII text is written raw (UTF-8) by both dumpers; control characters
    # and surrogates are where escaping rules could differ, so they are refused.
    for char in text:
        code = ord(char)
        if code < 0x20 or code == 0x7F or 0xD800 <= code <= 0xDFFF:
            problems.append("%s: %s contains a control or surrogate character" % (path, what))
            return


def _check_float(value, path, problems):
    if not math.isfinite(value):
        problems.append("%s: float is not finite" % path)
        return
    if value == 0.0 and math.copysign(1.0, value) < 0:
        problems.append("%s: negative zero" % path)
        return
    if "e" in repr(value) or "E" in repr(value):
        problems.append("%s: float uses exponent notation" % path)
        return
    magnitude = abs(value)
    if magnitude != 0.0 and (magnitude < _MIN_ABS_FLOAT or magnitude >= _MAX_ABS_FLOAT):
        problems.append("%s: float magnitude outside [1e-4, 1e15)" % path)


def preset_identity(obj) -> str:
    """Return the 16-hex-digit identity token for a preset object."""
    problems = preset_restrictions(obj)
    if problems:
        raise ValueError("; ".join(problems))
    return "%016x" % fnv1a64(canonical_bytes(obj))
