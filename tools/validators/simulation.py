"""H1 authoring contracts, independent of runtime G2/S8 adoption."""

from lumlib.engine_inventory import (MAX_DOCUMENT_BYTES, load_inventory,
                                     parse_author_bytes, read_captured, validate_inventory)
from lumlib.identity import canonical_bytes, fnv1a64
from lumlib.schema import SchemaError, check_keys, check_schema_id, is_kebab

POLICY_SCHEMA = "luminumbra.distant_policy.v1"
POPULATION_SCHEMA = "luminumbra.game.region-population.v1"
POLICY_PATH = "content/sim/distant_policy.json"
POPULATION_PATH = "content/sim/region_population.json"
MAX_POLICY_BYTES = MAX_DOCUMENT_BYTES
MAX_POPULATION_BYTES = MAX_DOCUMENT_BYTES
MAX_POPULATION_RULES = 32
MAX_POPULATION_COUNT = 8
MAX_POPULATION_ATTEMPTS = 128
MAX_POPULATION_TOTAL = 64
MAX_RULE_ID_BYTES = 64
U32_MAX = 4294967295
U16_MAX = 65535
CREATURE_FIELDS = {
    "coarse_need_rate_ppm": (0, U32_MAX),
    "coarse_travel_m_per_cadence": (0, U32_MAX),
    "promote_distance_m": (0, U16_MAX),
    "lifespan_cadences": (0, U32_MAX),
    "reproduce_cadences": (0, U32_MAX),
}
PLANT_FIELDS = {"max_cadence_shift": (1, 8), "resume_cap_ticks": (0, 36000)}


def empty_policy():
    return {"schema": POLICY_SCHEMA, "creature_species": {}, "plant_species": {}}


def _integer(value, low, high, where):
    if type(value) is not int or not low <= value <= high:
        raise SchemaError("%s: requires integer in %d..%d" % (where, low, high))


def check_policy(obj, inventory):
    """Validate candidate only; never mutate a previous parsed policy."""
    validate_inventory(inventory)
    check_schema_id(obj, POLICY_SCHEMA, "policy")
    check_keys(obj, {"schema", "creature_species", "plant_species"}, set(), "policy")
    for key, kind, fields in (("creature_species", "creatures", CREATURE_FIELDS),
                               ("plant_species", "plants", PLANT_FIELDS)):
        collection = obj[key]
        if not isinstance(collection, dict):
            raise SchemaError("%s: requires an object" % key)
        known = {row["name"] for row in inventory[kind]}
        if len(collection) > len(known):
            raise SchemaError("%s: exceeds complete inventory entry limit" % key)
        for name, block in collection.items():
            if name not in known:
                raise SchemaError("%s: unknown species '%s'" % (key, name))
            check_keys(block, set(fields), set(), key + "." + name)
            for field, (low, high) in fields.items():
                _integer(block[field], low, high, name + "." + field)
    return obj


def check_population(obj, inventory):
    validate_inventory(inventory)
    check_schema_id(obj, POPULATION_SCHEMA, "population")
    check_keys(obj, {"schema", "rules"}, set(), "population")
    rules = obj["rules"]
    if not isinstance(rules, list) or len(rules) > MAX_POPULATION_RULES:
        raise SchemaError("rules: requires a list of at most %d rules" % MAX_POPULATION_RULES)
    creatures = {row["name"] for row in inventory["creatures"]}
    biomes = {row["name"] for row in inventory["biomes"]["entries"]}
    ids, total = [], 0
    for row in rules:
        check_keys(row, {"id", "species", "biomes", "count", "max_attempts"}, set(), "rule")
        name = row["id"]
        if not is_kebab(name) or not 1 <= len(name.encode("ascii")) <= MAX_RULE_ID_BYTES:
            raise SchemaError("rule id: requires lowercase kebab-case, 1..64 ASCII bytes")
        if name in ids:
            raise SchemaError("rule id: duplicate '%s'" % name)
        ids.append(name)
        if not isinstance(row["species"], str) or row["species"] not in creatures:
            raise SchemaError("%s: unknown creature species" % name)
        names = row["biomes"]
        if not isinstance(names, list) or not names or len(names) > len(biomes):
            raise SchemaError("%s: biomes requires a nonempty unique list" % name)
        seen = set()
        for biome in names:
            if not isinstance(biome, str) or biome not in biomes:
                raise SchemaError("%s: unknown biome" % name)
            if biome in seen:
                raise SchemaError("%s: duplicate biome" % name)
            seen.add(biome)
        _integer(row["count"], 1, MAX_POPULATION_COUNT, name + ".count")
        _integer(row["max_attempts"], row["count"], MAX_POPULATION_ATTEMPTS, name + ".max_attempts")
        total += row["count"]
    if ids != sorted(ids):
        raise SchemaError("rules: must be sorted by ID (deterministic consumer order)")
    if total > MAX_POPULATION_TOTAL:
        raise SchemaError("rules: requested population exceeds per-region staging cap %d" % MAX_POPULATION_TOTAL)
    return obj


def parse_policy(raw, inventory):
    return check_policy(parse_author_bytes(raw, "policy"), inventory)


def parse_population(raw, inventory):
    return check_population(parse_author_bytes(raw, "population"), inventory)


def load_policy(path, inventory):
    """Author-side optional policy load: only clean absence means empty overrides."""
    raw = read_captured(path, optional=True)
    return check_policy(empty_policy(), inventory) if raw is None else parse_policy(raw, inventory)


def semantic_identity(obj):
    """Authoring integer-JSON checksum v1, not an ARL5 compatibility claim."""
    return "%016x" % fnv1a64(canonical_bytes(obj))


def _registered(path, obj, ctx, expected, checker):
    try:
        if path != expected:
            raise SchemaError("must live at " + expected)
        # validate_content supplies the same bytes it parsed, avoiding a second read.
        if ctx.raw is not None:
            parse_author_bytes(ctx.raw, path)
        checker(obj, load_inventory(ctx.root))
        if expected == POLICY_PATH and (obj["creature_species"] or obj["plant_species"]):
            raise SchemaError("shipping policy overrides must remain empty until DS units/fallbacks are qualified; use fixtures")
    except (SchemaError, OSError, ValueError, RecursionError) as exc:
        return ["%s: %s" % (path, exc)]
    return []


def validate_policy(path, obj, ctx):
    return _registered(path, obj, ctx, POLICY_PATH, check_policy)


def validate_population(path, obj, ctx):
    return _registered(path, obj, ctx, POPULATION_PATH, check_population)


SCHEMAS = {POLICY_SCHEMA: validate_policy, POPULATION_SCHEMA: validate_population}
