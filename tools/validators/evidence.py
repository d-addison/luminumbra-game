"""Validator for the JSON records under docs/evidence/.

Only the shape of the game-pack download verification record is checked here:
its top-level keys must be present and non-null. The values are not checked.
The key list matches the top level of docs/evidence/tree-small-02-download-verification.json.
"""

SCHEMA_ID = "luminumbra.game-pack-download-verification.v1"

REQUIRED_KEYS = (
    "schema",
    "verified_on",
    "method",
    "source",
    "runtime",
    "acquisition",
    "scope_limit",
)


def check_download_verification(path, obj, ctx):
    problems = []
    for key in REQUIRED_KEYS:
        if key not in obj:
            problems.append(f"{path}: missing key '{key}'")
        elif obj[key] is None:
            problems.append(f"{path}: key '{key}' is null")
    return problems


SCHEMAS = {SCHEMA_ID: check_download_verification}
