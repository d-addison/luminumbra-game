"""Validator for the JSON records under docs/evidence/.

The game-pack download verification record is checked against its full shape.
Every object must have exactly its listed keys: a missing key and an unknown
extra key are both refused, at every level. Values must have the exact JSON
type, so a bool is never accepted where an integer is expected. Hash fields are
64 lowercase hex digits, dates are YYYY-MM-DD, and each members array is a
non-empty array of objects with a path, a byte count and a sha256.

The layout matches docs/evidence/tree-small-02-download-verification.json.
Only the first problem found in a record is reported.
"""

import os
import re
import sys

_TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from lumlib.schema import SchemaError, check_keys  # noqa: E402

SCHEMA_ID = "luminumbra.game-pack-download-verification.v1"

HEX64 = re.compile(r"[0-9a-f]{64}")
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

ROOT_KEYS = frozenset(
    ["schema", "verified_on", "method", "source", "runtime", "acquisition", "scope_limit"]
)
SOURCE_KEYS = frozenset(
    [
        "tag",
        "archive_bytes",
        "archive_sha256",
        "members",
        "all_member_hashes_match",
        "companion_checksum_matches",
        "tag_target",
    ]
)
RUNTIME_KEYS = frozenset(
    [
        "schema",
        "release_tag",
        "game_revision",
        "archive_bytes",
        "archive_sha256",
        "downloaded_with",
        "companion_manifest_matches_engine",
        "companion_receipt_matches_archive",
        "source_manifest_matches_game_revision",
        "members",
        "conversion_input_source_hashes_match",
        "conversion_outputs_match_manifest",
    ]
)
MEMBER_KEYS = frozenset(["path", "bytes", "sha256"])
ACQUISITION_KEYS = frozenset(
    ["linux_tests", "windows_tests", "clean_https", "verified_offline", "script_sha256"]
)
TEST_COUNT_KEYS = frozenset(["passed", "skipped"])
SCRIPT_HASH_KEYS = frozenset(["acquire.py", "test_acquire.py"])


def _str(where, obj, key, pattern=None):
    value = obj[key]
    if not isinstance(value, str):
        raise SchemaError(f"{where}: key '{key}' must be a string")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise SchemaError(f"{where}: key '{key}' has the wrong format")


def _int(where, obj, key, minimum=None):
    value = obj[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise SchemaError(f"{where}: key '{key}' must be an integer")
    if minimum is not None and value < minimum:
        raise SchemaError(f"{where}: key '{key}' must be at least {minimum}")


def _bool(where, obj, key):
    if not isinstance(obj[key], bool):
        raise SchemaError(f"{where}: key '{key}' must be a boolean")


def _section(where, obj, key, keys):
    """Check that obj[key] is an object with exactly KEYS; return its location and value."""
    here = f"{where}: {key}"
    check_keys(obj[key], keys, set(), here)
    return here, obj[key]


def _members(where, obj, key):
    here = f"{where}: {key}"
    value = obj[key]
    if not isinstance(value, list) or not value:
        raise SchemaError(f"{here}: must be a non-empty array")
    for index, member in enumerate(value):
        item = f"{here}[{index}]"
        check_keys(member, MEMBER_KEYS, set(), item)
        _str(item, member, "path")
        _int(item, member, "bytes", 0)
        _str(item, member, "sha256", HEX64)


def _check_record(where, obj):
    check_keys(obj, ROOT_KEYS, set(), where)
    _str(where, obj, "schema")
    _str(where, obj, "verified_on", DATE)
    _str(where, obj, "method")

    here, source = _section(where, obj, "source", SOURCE_KEYS)
    _str(here, source, "tag")
    _int(here, source, "archive_bytes", 0)
    _str(here, source, "archive_sha256", HEX64)
    _members(here, source, "members")
    _bool(here, source, "all_member_hashes_match")
    _bool(here, source, "companion_checksum_matches")
    _str(here, source, "tag_target")

    here, runtime = _section(where, obj, "runtime", RUNTIME_KEYS)
    _str(here, runtime, "schema")
    _str(here, runtime, "release_tag")
    _str(here, runtime, "game_revision")
    _int(here, runtime, "archive_bytes")
    _str(here, runtime, "archive_sha256", HEX64)
    _str(here, runtime, "downloaded_with")
    _bool(here, runtime, "companion_manifest_matches_engine")
    _bool(here, runtime, "companion_receipt_matches_archive")
    _bool(here, runtime, "source_manifest_matches_game_revision")
    _members(here, runtime, "members")
    _bool(here, runtime, "conversion_input_source_hashes_match")
    _bool(here, runtime, "conversion_outputs_match_manifest")

    here, acquisition = _section(where, obj, "acquisition", ACQUISITION_KEYS)
    for name in ("linux_tests", "windows_tests"):
        counts_here, counts = _section(here, acquisition, name, TEST_COUNT_KEYS)
        _int(counts_here, counts, "passed")
        _int(counts_here, counts, "skipped")
    _str(here, acquisition, "clean_https")
    _str(here, acquisition, "verified_offline")
    hashes_here, hashes = _section(here, acquisition, "script_sha256", SCRIPT_HASH_KEYS)
    _str(hashes_here, hashes, "acquire.py", HEX64)
    _str(hashes_here, hashes, "test_acquire.py", HEX64)

    _str(where, obj, "scope_limit")


def check_download_verification(path, obj, ctx):
    try:
        _check_record(path, obj)
    except SchemaError as exc:
        return [str(exc)]
    return []


SCHEMAS = {SCHEMA_ID: check_download_verification}
