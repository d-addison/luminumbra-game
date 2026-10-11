import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from lumlib import schema  # noqa: E402
from lumlib.schema import SchemaError  # noqa: E402

_EXPECTED = "luminumbra.traversal.v1"


class LoadJsonFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _write(self, data: bytes) -> Path:
        path = self.dir / "doc.json"
        path.write_bytes(data)
        return path

    def test_loads_object(self):
        path = self._write(b'{"a": [1, "x", true, null]}')
        self.assertEqual(schema.load_json_file(path), {"a": [1, "x", True, None]})

    def test_accepts_path_string(self):
        path = self._write(b"[]")
        self.assertEqual(schema.load_json_file(str(path)), [])

    def test_decimal_preserves_source_text(self):
        path = self._write(b'{"x": 1.50, "n": 7}')
        loaded = schema.load_json_file(path)
        self.assertEqual(loaded["x"], Decimal("1.50"))
        self.assertIsInstance(loaded["x"], Decimal)
        self.assertEqual(str(loaded["x"]), "1.50")
        self.assertEqual(loaded["n"], 7)
        self.assertIsInstance(loaded["n"], int)

    def test_rejects_bom(self):
        path = self._write(b"\xef\xbb\xbf{}")
        with self.assertRaisesRegex(SchemaError, "byte order mark"):
            schema.load_json_file(path)

    def test_rejects_cr(self):
        path = self._write(b'{\r\n"a": 1}\r\n')
        with self.assertRaisesRegex(SchemaError, "CR"):
            schema.load_json_file(path)

    def test_rejects_invalid_utf8(self):
        path = self._write(b'{"a": "\xff"}')
        with self.assertRaisesRegex(SchemaError, "UTF-8"):
            schema.load_json_file(path)

    def test_rejects_duplicate_keys(self):
        path = self._write(b'{"a": 1, "a": 2}')
        with self.assertRaisesRegex(SchemaError, "duplicate key 'a'"):
            schema.load_json_file(path)

    def test_rejects_nan(self):
        path = self._write(b'{"a": NaN}')
        with self.assertRaisesRegex(SchemaError, "non-finite"):
            schema.load_json_file(path)

    def test_rejects_infinity(self):
        path = self._write(b'[Infinity]')
        with self.assertRaises(SchemaError):
            schema.load_json_file(path)

    def test_rejects_negative_infinity(self):
        path = self._write(b'[-Infinity]')
        with self.assertRaises(SchemaError):
            schema.load_json_file(path)

    def test_rejects_malformed_json_with_path(self):
        path = self._write(b'{"a": }')
        with self.assertRaises(SchemaError) as ctx:
            schema.load_json_file(path)
        self.assertIn(str(path), str(ctx.exception))


class CheckKeysTests(unittest.TestCase):
    def test_accepts_required_and_optional(self):
        schema.check_keys({"a": 1, "b": 2}, {"a"}, {"b"}, "doc")

    def test_accepts_only_required(self):
        schema.check_keys({"a": 1}, {"a"}, set(), "doc")

    def test_missing_key(self):
        with self.assertRaisesRegex(SchemaError, r"^doc: missing key 'a'$"):
            schema.check_keys({}, {"a"}, set(), "doc")

    def test_unknown_key(self):
        with self.assertRaisesRegex(SchemaError, r"^doc: unknown key 'z'$"):
            schema.check_keys({"a": 1, "z": 2}, {"a"}, set(), "doc")

    def test_not_an_object(self):
        with self.assertRaisesRegex(SchemaError, r"^doc: not an object$"):
            schema.check_keys([1], {"a"}, set(), "doc")

    def test_not_an_object_string(self):
        with self.assertRaises(SchemaError):
            schema.check_keys("a", {"a"}, set(), "doc")


class CheckSchemaIdTests(unittest.TestCase):
    def test_exact_match_passes(self):
        schema.check_schema_id({"schema": _EXPECTED}, _EXPECTED, "doc")

    def test_missing_schema_key(self):
        with self.assertRaisesRegex(SchemaError, r"^doc: missing key 'schema'$"):
            schema.check_schema_id({}, _EXPECTED, "doc")

    def test_future_version_is_reported_as_future(self):
        with self.assertRaisesRegex(SchemaError, r"^doc: future schema version$"):
            schema.check_schema_id({"schema": "luminumbra.traversal.v2"}, _EXPECTED, "doc")

    def test_future_version_with_larger_number(self):
        with self.assertRaisesRegex(SchemaError, "future schema version"):
            schema.check_schema_id({"schema": "luminumbra.traversal.v10"}, _EXPECTED, "doc")

    def test_older_version_is_unknown(self):
        with self.assertRaisesRegex(SchemaError, r"^doc: unknown schema$"):
            schema.check_schema_id({"schema": "luminumbra.traversal.v0"}, "luminumbra.traversal.v1", "doc")

    def test_different_stem_is_unknown(self):
        with self.assertRaisesRegex(SchemaError, r"^doc: unknown schema$"):
            schema.check_schema_id({"schema": "luminumbra.preset.v2"}, _EXPECTED, "doc")

    def test_unrelated_string_is_unknown(self):
        with self.assertRaisesRegex(SchemaError, r"^doc: unknown schema$"):
            schema.check_schema_id({"schema": "other"}, _EXPECTED, "doc")

    def test_non_string_schema_is_unknown(self):
        with self.assertRaisesRegex(SchemaError, r"^doc: unknown schema$"):
            schema.check_schema_id({"schema": 1}, _EXPECTED, "doc")

    def test_not_an_object(self):
        with self.assertRaisesRegex(SchemaError, r"^doc: not an object$"):
            schema.check_schema_id(["x"], _EXPECTED, "doc")


class IsKebabTests(unittest.TestCase):
    def test_valid_kebab(self):
        for value in ("a", "abc", "a-b", "v0-3-pre-2", "123", "a1-b2"):
            self.assertTrue(schema.is_kebab(value), value)

    def test_invalid_kebab(self):
        for value in ("", "-a", "a-", "a--b", "A", "a_b", "a b", "a.b", "\u00e9", "a\n"):
            self.assertFalse(schema.is_kebab(value), repr(value))

    def test_non_string(self):
        self.assertFalse(schema.is_kebab(None))
        self.assertFalse(schema.is_kebab(3))


if __name__ == "__main__":
    unittest.main()
