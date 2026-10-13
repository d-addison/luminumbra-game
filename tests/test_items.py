"""H2 authoring contracts and real hash refusals; runtime remains unqualified."""

import copy
import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from lumlib import identity  # noqa: E402
from lumlib.item_identity import item_id, resolved_items  # noqa: E402
from lumlib.schema import SchemaError  # noqa: E402
from validators import Context, discover  # noqa: E402
from validators import items  # noqa: E402
import validate_content  # noqa: E402

FIXTURES = ROOT / "tests/fixtures/items"
REFUSALS = {
    "invalid-collision.json": "identity collision",
    "invalid-zero-type.json": "identity is zero",
    "invalid-boolean.json": "requires integer",
    "invalid-decimal.json": "requires integer",
    "invalid-exponent.json": "exponent number",
    "invalid-duplicate-key.json": "duplicate key",
    "invalid-render-unpinned.json": "unpinned model/material reference",
}


def encoded(obj):
    return (json.dumps(obj) + "\n").encode("utf-8")


class ItemIdentityTests(unittest.TestCase):
    def test_binding_vectors_including_real_zero_and_collision(self):
        vectors = json.loads((FIXTURES / "item-vectors.json").read_bytes())["fnv1a32_vectors"]
        for row in vectors:
            name, expected = row["name"], row["type_id"]
            with self.subTest(name=name):
                # Independently recompute from the binding constants, including
                # wrapping after every byte, rather than mocking a zero hash.
                value = 2166136261
                for byte in name.encode("ascii"):
                    value = ((value ^ byte) * 16777619) % (1 << 32)
                self.assertEqual(value, expected)
                self.assertEqual(identity.fnv1a32(name.encode("ascii")), expected)
                if name and expected:
                    self.assertEqual(item_id(name), expected)
                else:
                    with self.assertRaises(SchemaError):
                        item_id(name)
        self.assertEqual(item_id("farming-seed"), 0x1ECC8557)
        for names in (["costarring", "liquid"], ["liquid", "costarring"]):
            with self.assertRaisesRegex(SchemaError, "identity collision"):
                resolved_items(names)
        with self.assertRaisesRegex(SchemaError, "identity is zero"):
            resolved_items(["a", "fxdsatwp"])
        with self.assertRaisesRegex(SchemaError, "duplicate item id"):
            resolved_items(["farming-seed", "farming-seed"])

    def test_exact_ascii_names_and_load_order_independence(self):
        for name in ("", "A", "a_b", "a--b", "-a", "a-", "a b", "é", "\ud800",
                     "a\0b", "a\nb", "a" * 65, None, True, 12, [], {}):
            with self.subTest(name=repr(name)):
                with self.assertRaisesRegex(SchemaError, "lowercase kebab-case"):
                    item_id(name)
        for name in ("a", "a" * 64, "seed-2", "123"):
            self.assertEqual(item_id(name), identity.fnv1a32(name.encode("ascii")))
        names = ["a", "farming-seed", "seed-2"]
        self.assertEqual(resolved_items(names), resolved_items(reversed(names)))
        # Catalogue identity, schema prefixes and durable object IDs are not types.
        self.assertNotEqual(item_id("farming-seed"),
                            identity.fnv1a32(b"luminumbra.game.items.v1:farming-seed"))


class ItemsTests(unittest.TestCase):
    def setUp(self):
        self.catalogue = json.loads((FIXTURES / "valid-items.json").read_bytes())

    def test_shipping_exact_first_item_and_dynamic_registry(self):
        schemas, _ = discover()
        self.assertIs(schemas[items.ITEMS_SCHEMA], items.validate_items)
        self.assertEqual(items.parse_items((ROOT / items.ITEMS_PATH).read_bytes()), self.catalogue)
        self.assertEqual(self.catalogue, {"schema": items.ITEMS_SCHEMA, "items": [
            {"id": "farming-seed", "despawn_after": 900, "payload": 0}]})
        ctx = Context(str(ROOT), True, False)
        self.assertEqual(items.validate_items(items.ITEMS_PATH, self.catalogue, ctx), [])
        self.assertIn("must live at", items.validate_items("content/other.json", self.catalogue, ctx)[0])
        self.assertEqual(validate_content.validate_tree(str(ROOT), True, False), [])

    def test_dedicated_fixtures_refuse_for_intended_reason_and_repair(self):
        self.assertEqual({p.name for p in FIXTURES.glob("invalid-*.json")}, set(REFUSALS))
        for name, diagnostic in REFUSALS.items():
            raw = (FIXTURES / name).read_bytes()
            with self.subTest(name=name):
                with self.assertRaisesRegex(SchemaError, diagnostic):
                    items.parse_items(raw)
                # Repair only the intended defect to ensure the fixture did not
                # accidentally refuse earlier for an unrelated constraint.
                if name == "invalid-duplicate-key.json":
                    raw = raw.replace(b'"payload": 0, "payload": 0', b'"payload": 0')
                    items.parse_items(raw)
                    continue
                obj = json.loads(raw)
                row = obj["items"][0]
                if name == "invalid-collision.json":
                    obj["items"].pop()
                elif name == "invalid-zero-type.json":
                    row["id"] = "a"
                elif name == "invalid-render-unpinned.json":
                    del row["render"]
                else:
                    row["despawn_after"] = 900
                items.parse_items(encoded(obj))

    def test_all_u32_boundaries_types_and_numeric_tokens(self):
        # A generic fixture tests the schema's full payload domain; the first
        # gameplay seed has the narrower payload-zero semantic contract.
        self.catalogue["items"][0]["id"] = "test-item"
        for field in ("despawn_after", "payload"):
            for value in (0, items.U32_MAX):
                obj = copy.deepcopy(self.catalogue)
                obj["items"][0][field] = value
                self.assertEqual(items.parse_items(encoded(obj)), obj)
            for value in (-1, items.U32_MAX + 1, True, False, None, "1", 1.0, Decimal("1.0"), [], {}):
                obj = copy.deepcopy(self.catalogue)
                obj["items"][0][field] = value
                with self.subTest(field=field, value=repr(value)):
                    with self.assertRaisesRegex(SchemaError, "requires integer"):
                        items.check_items(obj)
            for token in ("1.0", "1e0", "1E+0", "NaN", "Infinity", "-Infinity"):
                obj = copy.deepcopy(self.catalogue)
                obj["items"][0][field] = 123456
                raw = encoded(obj).replace(b"123456", token.encode())
                with self.subTest(field=field, token=token):
                    with self.assertRaises(SchemaError):
                        items.parse_items(raw)

    def test_seed_payload_is_generic_zero(self):
        for value in (1, 7403, items.U32_MAX):
            obj = copy.deepcopy(self.catalogue)
            obj["items"][0]["payload"] = value
            with self.assertRaisesRegex(SchemaError, "must be zero"):
                items.check_items(obj)

    def test_exact_root_and_item_keys_containers_and_schema(self):
        for key in self.catalogue:
            obj = copy.deepcopy(self.catalogue)
            del obj[key]
            with self.assertRaisesRegex(SchemaError, "missing key"):
                items.check_items(obj)
        for key in self.catalogue["items"][0]:
            obj = copy.deepcopy(self.catalogue)
            del obj["items"][0][key]
            with self.assertRaisesRegex(SchemaError, "missing key"):
                items.check_items(obj)
        for extra in ("type", "type_id", "persistent_id", "engine_revision", "status"):
            obj = copy.deepcopy(self.catalogue)
            obj["items"][0][extra] = 1
            with self.assertRaisesRegex(SchemaError, "unknown key"):
                items.check_items(obj)
        obj = dict(self.catalogue, extra=1)
        with self.assertRaisesRegex(SchemaError, "unknown key"):
            items.check_items(obj)
        for value in (None, True, 1, [], "items"):
            with self.assertRaises(SchemaError):
                items.check_items(value)
        for value in (None, {}, True, 1, "items"):
            with self.assertRaises(SchemaError):
                items.check_items(dict(self.catalogue, items=value))
            with self.assertRaises(SchemaError):
                items.check_items(dict(self.catalogue, items=[value]))
        for schema in (items.ITEMS_SCHEMA[:-1] + "2", "other", None, 1):
            with self.assertRaises(SchemaError):
                items.check_items(dict(self.catalogue, schema=schema))

    def test_duplicate_keys_at_root_item_and_render(self):
        raw = encoded(self.catalogue)
        for bad in (raw.replace(b'"items":', b'"schema": "duplicate", "items":'),
                    raw.replace(b'"payload": 0', b'"payload": 0, "payload": 0'),
                    raw.replace(b'"payload": 0', b'"payload": 0, "render": '
                                b'{"model_id": "a", "model_id": "b", "material_id": 2}')):
            with self.assertRaisesRegex(SchemaError, "duplicate key"):
                items.parse_items(bad)

    def test_sorted_unique_full_catalogue_and_definition_cap(self):
        row = self.catalogue["items"][0]
        ordered = dict(self.catalogue, items=[dict(row, id="a"), dict(row, id="b")])
        before = copy.deepcopy(ordered)
        items.check_items(ordered)
        self.assertEqual(ordered, before)
        with self.assertRaisesRegex(SchemaError, "sorted by ID"):
            items.check_items(dict(ordered, items=list(reversed(ordered["items"]))))
        with self.assertRaisesRegex(SchemaError, "duplicate item id"):
            items.check_items(dict(ordered, items=[row, row]))
        items.check_items(dict(ordered, items=[]))
        rows = [dict(row, id="item-%04d" % i) for i in range(items.MAX_ITEM_DEFINITIONS)]
        items.parse_items(encoded(dict(ordered, items=rows)))
        rows.append(dict(row, id="item-4096"))
        with self.assertRaisesRegex(SchemaError, "at most 4096"):
            items.check_items(dict(ordered, items=rows))
        # Collision refusal covers every definition, not just farming-seed.
        collision = [dict(row, id="a"), dict(row, id="costarring"),
                     row, dict(row, id="liquid")]
        with self.assertRaisesRegex(SchemaError, "identity collision"):
            items.check_items(dict(ordered, items=collision))

    def test_render_exact_shape_types_and_unresolved_references(self):
        def catalogue(render):
            obj = copy.deepcopy(self.catalogue)
            obj["items"][0]["render"] = render
            return obj
        for render in (None, [], True, {}, {"model_id": "farming-seed"},
                       {"material_id": 2}, {"model_id": "farming-seed", "material_id": 2, "extra": 0}):
            with self.assertRaises(SchemaError):
                items.check_items(catalogue(render))
        for model in (None, True, 2, "", "a\0b"):
            with self.assertRaisesRegex(SchemaError, "model reference"):
                items.check_items(catalogue({"model_id": model, "material_id": 2}))
        for material in (True, False, None, "2", 2.0, Decimal("2.0"), -1, items.U32_MAX + 1):
            with self.assertRaisesRegex(SchemaError, "requires integer"):
                items.check_items(catalogue({"model_id": "farming-seed", "material_id": material}))
        for model, material in (("farming-seed", 2), ("unknown", 2), ("farming-seed", 0),
                                ("farming-seed", items.U32_MAX)):
            with self.assertRaisesRegex(SchemaError, "unpinned model/material reference"):
                items.check_items(catalogue({"model_id": model, "material_id": material}))

    def test_strict_encoding_exact_byte_cap_and_previous_candidate_unchanged(self):
        raw = encoded(self.catalogue)
        previous = items.parse_items(raw)
        before = copy.deepcopy(previous)
        invalid = (b'broken\n', raw[:-1], raw.replace(b'\n', b'\r\n'),
                   b'\xef\xbb\xbf' + raw, b'\xff\n', raw + b' ' * items.MAX_ITEMS_BYTES,
                   raw.replace(b'farming-seed', b'farm\\u0000seed'),
                   raw.replace(b'farming-seed', b'farm\\ud800seed'))
        for bad in invalid:
            with self.assertRaises(SchemaError):
                previous = items.parse_items(bad)
            self.assertEqual(previous, before)
        exact = raw[:-1] + b' ' * (items.MAX_ITEMS_BYTES - len(raw)) + b'\n'
        self.assertEqual(len(exact), 1048576)
        self.assertEqual(items.parse_items(exact), self.catalogue)
        with self.assertRaisesRegex(SchemaError, "byte limit"):
            items.parse_items(exact + b'\n')

    def test_dispatch_uses_captured_bytes_and_reports_future_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / items.ITEMS_PATH
            path.parent.mkdir(parents=True)
            raw = encoded(self.catalogue)
            path.write_bytes(raw)
            captured = validate_content.read_captured
            def capture_once(full):
                result = captured(full)
                Path(full).write_bytes(b'changed after capture\n')
                return result
            with patch.object(validate_content, "read_captured", side_effect=capture_once) as capture:
                self.assertEqual(validate_content.validate_tree(str(root), True, False), [])
                self.assertEqual(capture.call_count, 1)
            for bad, diagnostic in ((raw[:-1], "final LF"),
                                    (raw + b' ' * items.MAX_ITEMS_BYTES, "byte limit"),
                                    (raw.replace(b'items.v1', b'items.v2'), "not registered")):
                path.write_bytes(bad)
                problems = validate_content.validate_tree(str(root), True, False)
                self.assertTrue(any(diagnostic in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
