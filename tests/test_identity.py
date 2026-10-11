import sys
import unittest
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from lumlib import identity, traversal  # noqa: E402

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_DEFAULT_PRESET_PIN = "026f24207a8ffc7e"


def _read_fixture(name):
    return (_FIXTURES / name).read_bytes().decode("utf-8")


class Fnv1aVectorTests(unittest.TestCase):
    def test_fnv1a32_known_vectors(self):
        self.assertEqual(identity.fnv1a32(b""), 0x811C9DC5)
        self.assertEqual(identity.fnv1a32(b"a"), 0xE40C292C)
        self.assertEqual(identity.fnv1a32(b"foobar"), 0xBF9CF968)

    def test_fnv1a64_known_vectors(self):
        self.assertEqual(identity.fnv1a64(b""), 0xCBF29CE484222325)
        self.assertEqual(identity.fnv1a64(b"a"), 0xAF63DC4C8601EC8C)

    def test_constants(self):
        self.assertEqual(identity.FNV64_OFFSET, 14695981039346656037)
        self.assertEqual(identity.FNV64_PRIME, 1099511628211)
        self.assertEqual(identity.FNV32_OFFSET, 2166136261)
        self.assertEqual(identity.FNV32_PRIME, 16777619)


class CanonicalJsonTests(unittest.TestCase):
    def test_sorted_compact_utf8(self):
        obj = {"b": 1, "a": ["x", True, None]}
        self.assertEqual(identity.canonical_json(obj), '{"a":["x",true,null],"b":1}')
        self.assertEqual(identity.canonical_bytes(obj), '{"a":["x",true,null],"b":1}'.encode("utf-8"))

    def test_non_ascii_is_not_escaped(self):
        self.assertEqual(identity.canonical_json({"k": "\u00e9"}), '{"k":"\u00e9"}')


class LoadsStrictTests(unittest.TestCase):
    def test_parses_plain_json(self):
        self.assertEqual(identity.loads_strict('{"a": [1, 2.5]}'), {"a": [1, 2.5]})

    def test_rejects_duplicate_keys(self):
        with self.assertRaisesRegex(ValueError, "duplicate key 'a'"):
            identity.loads_strict('{"a": 1, "a": 2}')

    def test_rejects_nan(self):
        with self.assertRaises(ValueError):
            identity.loads_strict('{"a": NaN}')

    def test_rejects_infinity(self):
        with self.assertRaises(ValueError):
            identity.loads_strict('{"a": Infinity}')

    def test_rejects_negative_infinity(self):
        with self.assertRaises(ValueError):
            identity.loads_strict('{"a": -Infinity}')

    def test_rejects_bom(self):
        with self.assertRaisesRegex(ValueError, "byte order mark"):
            identity.loads_strict("\ufeff{}")

    def test_rejects_exponent_tokens(self):
        for text in ('{"a": 1e0}', '{"a": 6.0e1}', '{"a": 1E+2}'):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, "exponent number"):
                    identity.loads_strict(text)

    def test_plain_decimal_tokens_still_parse(self):
        self.assertEqual(identity.loads_strict("[0.5, -12, 60.0]"), [0.5, -12, 60.0])


class PresetRestrictionTests(unittest.TestCase):
    def test_allowed_values_produce_no_problems(self):
        obj = {"a": True, "b": None, "c": [1, 2.5, -0.0001234], "d": {"e": "ok"}}
        self.assertEqual(identity.preset_restrictions(obj), [])

    def test_exponent_float_is_rejected(self):
        problems = identity.preset_restrictions({"x": 1e-5})
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("$.x:"))
        with self.assertRaises(ValueError):
            identity.preset_identity({"x": 1e-5})

    def test_large_exponent_float_is_rejected(self):
        self.assertTrue(identity.preset_restrictions({"x": 1e20}))

    def test_negative_zero_is_rejected(self):
        self.assertTrue(identity.preset_restrictions({"x": -0.0}))
        with self.assertRaises(ValueError):
            identity.preset_identity({"x": -0.0})

    def test_positive_zero_is_allowed(self):
        self.assertEqual(identity.preset_restrictions({"x": 0.0}), [])

    def test_non_ascii_text_is_allowed(self):
        self.assertEqual(identity.preset_restrictions({"name": "caf\u00e9", "caf\u00e9": 1}), [])

    def test_control_character_in_value_is_rejected(self):
        problems = identity.preset_restrictions({"name": "a\nb"})
        self.assertEqual(len(problems), 1)
        self.assertIn("control or surrogate", problems[0])
        with self.assertRaises(ValueError):
            identity.preset_identity({"name": "a\nb"})

    def test_control_character_in_key_is_rejected(self):
        problems = identity.preset_restrictions({"a\tb": 1})
        self.assertEqual(len(problems), 1)
        self.assertIn("key contains a control", problems[0])

    def test_surrogate_is_rejected(self):
        self.assertEqual(len(identity.preset_restrictions({"name": "\ud800"})), 1)

    def test_engine_caverns_preset_is_identifiable(self):
        text = _read_fixture("engine-caverns-preset.json")
        value = identity.preset_identity(identity.loads_strict(text))
        self.assertRegex(value, r"^[0-9a-f]{16}$")

    def test_nan_is_rejected(self):
        self.assertTrue(identity.preset_restrictions({"x": float("nan")}))

    def test_infinity_is_rejected(self):
        self.assertTrue(identity.preset_restrictions({"x": float("inf")}))
        self.assertTrue(identity.preset_restrictions({"x": float("-inf")}))

    def test_float_below_minimum_magnitude_is_rejected(self):
        self.assertTrue(identity.preset_restrictions({"x": 0.00005}))

    def test_float_at_or_above_maximum_magnitude_is_rejected(self):
        self.assertTrue(identity.preset_restrictions({"x": 1234567890123456.0}))

    def test_float_just_inside_range_is_allowed(self):
        self.assertEqual(identity.preset_restrictions({"x": 0.0001}), [])
        self.assertEqual(identity.preset_restrictions({"x": 123456789012345.0}), [])

    def test_integer_outside_safe_range_is_rejected(self):
        self.assertTrue(identity.preset_restrictions({"x": 2 ** 53 + 1}))
        self.assertTrue(identity.preset_restrictions({"x": -(2 ** 53) - 1}))

    def test_integer_at_safe_bound_is_allowed(self):
        self.assertEqual(identity.preset_restrictions({"x": 2 ** 53}), [])
        self.assertEqual(identity.preset_restrictions({"x": -(2 ** 53)}), [])

    def test_bool_is_not_treated_as_integer(self):
        self.assertEqual(identity.preset_restrictions({"x": True}), [])


class PresetIdentityTests(unittest.TestCase):
    def test_default_preset_pin(self):
        preset = identity.loads_strict(_read_fixture("engine-default-preset.json"))
        self.assertEqual(identity.preset_identity(preset), _DEFAULT_PRESET_PIN)

    def test_pin_matches_engine_traversal_token(self):
        preset = identity.loads_strict(_read_fixture("engine-default-preset.json"))
        engine = traversal.parse(_read_fixture("engine-surface-flight.traversal"))
        self.assertEqual(engine.preset_identity, _DEFAULT_PRESET_PIN)
        self.assertEqual(identity.preset_identity(preset), engine.preset_identity)

    def test_key_order_does_not_change_identity(self):
        first = identity.loads_strict('{"a": 1, "b": {"c": 2, "d": 3}}')
        second = identity.loads_strict('{"b": {"d": 3, "c": 2}, "a": 1}')
        self.assertEqual(identity.preset_identity(first), identity.preset_identity(second))

    def test_int_and_float_tokens_differ(self):
        self.assertEqual(identity.canonical_json({"x": 1}), '{"x":1}')
        self.assertEqual(identity.canonical_json({"x": 1.0}), '{"x":1.0}')
        self.assertNotEqual(identity.preset_identity({"x": 1}), identity.preset_identity({"x": 1.0}))

    def test_identity_is_sixteen_lowercase_hex_digits(self):
        token = identity.preset_identity({"x": 1})
        self.assertEqual(len(token), 16)
        self.assertEqual(token, token.lower())
        int(token, 16)


if __name__ == "__main__":
    unittest.main()
