"""Catalogue type identities; distinct from persistent object IDs and content checksums."""

from lumlib.identity import fnv1a32
from lumlib.schema import SchemaError, is_kebab

MAX_ITEM_ID_BYTES = 64


def item_id(name):
    """Hash the exact 1..64-byte lowercase kebab ID; refuse zero without remapping."""
    if not is_kebab(name) or not 1 <= len(name.encode("ascii")) <= MAX_ITEM_ID_BYTES:
        raise SchemaError("item id: requires lowercase kebab-case, 1..64 ASCII bytes")
    value = fnv1a32(name.encode("ascii"))
    if value == 0:
        raise SchemaError("item identity is zero: '%s'" % name)
    return value


def resolved_items(names):
    """Resolve the whole catalogue, refusing duplicate names and distinct-name collisions."""
    result, owners = {}, {}
    for name in names:
        value = item_id(name)
        if name in result:
            raise SchemaError("duplicate item id '%s'" % name)
        if value in owners:
            raise SchemaError("item identity collision: '%s' and '%s' -> %d" %
                              (owners[value], name, value))
        result[name] = value
        owners[value] = name
    return result
