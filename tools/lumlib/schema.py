"""JSON loading and schema-identifier helpers shared by the validators.

Numbers are parsed so that the source text is preserved: floats become
Decimal, integers stay int. Duplicate keys, NaN, Infinity, exponent number
tokens, a leading BOM, carriage returns, and invalid UTF-8 are all rejected.
"""

import json
import re
from decimal import Decimal
from pathlib import Path


class SchemaError(ValueError):
    """Raised when a document does not match the expected schema or encoding."""


_KEBAB_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
_VERSIONED_RE = re.compile(r"(.+)\.v([0-9]+)")
_UTF8_BOM = b"\xef\xbb\xbf"


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key '%s'" % key)
        result[key] = value
    return result


def _reject_constant(name):
    raise ValueError("non-finite number '%s' is not allowed" % name)


def _parse_decimal(token):
    # The json module hands every token with a fraction or exponent to parse_float,
    # so an integer written with an exponent (1e0) is caught here as well.
    if "e" in token or "E" in token:
        raise ValueError("exponent number '%s' is not allowed" % token)
    return Decimal(token)


def loads_document(text):
    """Parse JSON text with duplicate-key, NaN/Infinity and exponent refusal; floats are Decimal.

    Raises ValueError (a SchemaError for load_json_file) on any refusal.
    """
    return json.loads(
        text,
        parse_float=_parse_decimal,
        parse_int=int,
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_constant,
    )


def load_json_file(path):
    """Load a JSON file with strict encoding rules and Decimal floats."""
    data = Path(path).read_bytes()
    if data.startswith(_UTF8_BOM):
        raise SchemaError("%s: byte order mark is not allowed" % path)
    if b"\r" in data:
        raise SchemaError("%s: CR is not allowed; use LF newlines" % path)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise SchemaError("%s: file is not valid UTF-8" % path) from None
    try:
        return loads_document(text)
    except ValueError as exc:
        raise SchemaError("%s: %s" % (path, exc)) from None


def check_keys(obj, required: set, optional: set, where: str) -> None:
    """Require ``obj`` to be a dict whose keys are all in required | optional."""
    if not isinstance(obj, dict):
        raise SchemaError("%s: not an object" % where)
    for key in sorted(required):
        if key not in obj:
            raise SchemaError("%s: missing key '%s'" % (where, key))
    allowed = set(required) | set(optional)
    for key in sorted(obj):
        if key not in allowed:
            raise SchemaError("%s: unknown key '%s'" % (where, key))


def check_schema_id(obj, expected: str, where: str) -> None:
    """Require ``obj["schema"]`` to equal ``expected``, reporting newer versions distinctly."""
    if not isinstance(obj, dict):
        raise SchemaError("%s: not an object" % where)
    if "schema" not in obj:
        raise SchemaError("%s: missing key 'schema'" % where)
    value = obj["schema"]
    if isinstance(value, str) and value == expected:
        return
    expected_match = _VERSIONED_RE.fullmatch(expected)
    if isinstance(value, str) and expected_match is not None:
        value_match = _VERSIONED_RE.fullmatch(value)
        if value_match is not None and value_match.group(1) == expected_match.group(1):
            if int(value_match.group(2)) > int(expected_match.group(2)):
                raise SchemaError("%s: future schema version" % where)
    raise SchemaError("%s: unknown schema" % where)


def is_kebab(s) -> bool:
    """Return True when ``s`` is lowercase kebab-case: ``[a-z0-9]+(-[a-z0-9]+)*``."""
    return isinstance(s, str) and _KEBAB_RE.fullmatch(s) is not None
