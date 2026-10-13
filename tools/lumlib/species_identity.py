"""Engine species-name identity; intentionally distinct from preset/content FNV."""

from lumlib.schema import SchemaError

SPECIES_OFFSET = 1469598103934665603
SPECIES_PRIME = 1099511628211
MASK64 = (1 << 64) - 1


def species_id(name):
    """Hash exact UTF-8 name, fold to u16, then map zero to one (Q8)."""
    if not isinstance(name, str) or not name or "\0" in name:
        raise SchemaError("species name must be nonempty and contain no NUL")
    try:
        raw = name.encode("utf-8")
    except UnicodeEncodeError:
        raise SchemaError("species name must be valid UTF-8") from None
    value = SPECIES_OFFSET
    for byte in raw:
        value = ((value ^ byte) * SPECIES_PRIME) & MASK64
    folded = (value ^ (value >> 32)) & 65535
    return folded or 1


def resolved_species(names):
    """Resolve a complete registry, rejecting duplicates and post-remap collisions."""
    result, owners = {}, {}
    for name in names:
        value = species_id(name)
        if name in result:
            raise SchemaError("duplicate species name '%s'" % name)
        if value in owners:
            raise SchemaError("species identity collision: '%s' and '%s' -> %d" %
                              (owners[value], name, value))
        result[name] = value
        owners[value] = name
    return result
