"""H2 catalogue authoring; rendering references await the slice-8 public pin."""

from lumlib.engine_inventory import MAX_DOCUMENT_BYTES, parse_author_bytes
from lumlib.item_identity import resolved_items
from lumlib.schema import SchemaError, check_keys, check_schema_id

ITEMS_SCHEMA = "luminumbra.game.items.v1"
ITEMS_PATH = "content/items/items.json"
MAX_ITEMS_BYTES = MAX_DOCUMENT_BYTES
MAX_ITEM_DEFINITIONS = 4096
U32_MAX = 4294967295


def _u32(value, where):
    if type(value) is not int or not 0 <= value <= U32_MAX:
        raise SchemaError("%s: requires integer in 0..%d" % (where, U32_MAX))


def check_items(obj):
    """Validate a candidate without mutating or deriving fields into its runtime document."""
    check_schema_id(obj, ITEMS_SCHEMA, "items")
    check_keys(obj, {"schema", "items"}, set(), "items")
    rows = obj["items"]
    if not isinstance(rows, list) or len(rows) > MAX_ITEM_DEFINITIONS:
        raise SchemaError("items: requires a list of at most %d definitions" % MAX_ITEM_DEFINITIONS)
    names = []
    for row in rows:
        check_keys(row, {"id", "despawn_after", "payload"}, {"render"}, "item")
        names.append(row["id"])
        for field in ("despawn_after", "payload"):
            _u32(row[field], "item." + field)
        if row["id"] == "farming-seed" and row["payload"] != 0:
            raise SchemaError("farming-seed.payload: must be zero (one generic seed)")
        if "render" in row:
            render = row["render"]
            check_keys(render, {"model_id", "material_id"}, set(), "item.render")
            if not isinstance(render["model_id"], str) or not render["model_id"] or "\0" in render["model_id"]:
                raise SchemaError("item.render.model_id: requires a nonempty model reference")
            _u32(render["material_id"], "item.render.material_id")
            # StaticMeshComponent is not a public model registry. No rendering
            # reference can resolve until slice 8 pins the reviewed slice-7 surface.
            raise SchemaError("item.render: unpinned model/material reference; omit render until slice 8")
    resolved_items(names)
    if names != sorted(names):
        raise SchemaError("items: must be sorted by ID")
    return obj


def parse_items(raw, inventory=None):
    """Parse captured author bytes; H1's inventory parameter is unused for this family."""
    return check_items(parse_author_bytes(raw, "items"))


def validate_items(path, obj, ctx):
    try:
        if path != ITEMS_PATH:
            raise SchemaError("must live at " + ITEMS_PATH)
        if ctx.raw is not None:
            parse_author_bytes(ctx.raw, path)
        check_items(obj)
    except (SchemaError, ValueError, RecursionError) as exc:
        return ["%s: %s" % (path, exc)]
    return []


SCHEMAS = {ITEMS_SCHEMA: validate_items}
