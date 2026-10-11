import dataclasses
import sys
import unittest
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from lumlib import traversal  # noqa: E402
from lumlib.traversal import Traversal, TraversalError  # noqa: E402

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_FIXTURE_TEXT = (_FIXTURES / "engine-surface-flight.traversal").read_bytes().decode("utf-8")


def _lines():
    return _FIXTURE_TEXT.split("\n")


def _join(lines):
    return "\n".join(lines)


def _with_line(index, new_line):
    lines = _lines()
    lines[index] = new_line
    return _join(lines)


class RoundTripTests(unittest.TestCase):
    def test_parse_fixture_fields(self):
        t = traversal.parse(_FIXTURE_TEXT)
        self.assertEqual(t.duration, "60")
        self.assertEqual(t.tick_rate, 30)
        self.assertEqual(t.speed, "8")
        self.assertEqual(t.seed, 424242)
        self.assertEqual(t.preset, "default")
        self.assertEqual(t.preset_revision, 6)
        self.assertEqual(t.preset_identity, "026f24207a8ffc7e")
        self.assertEqual(t.content_identity, "16636010052247870746")
        self.assertEqual(t.expected_ticks, 1800)
        self.assertEqual(len(t.points), 3)
        self.assertEqual(t.points[0], ("8", "80", "8", "0", "-6"))

    def test_emit_round_trips_fixture(self):
        self.assertEqual(traversal.emit(traversal.parse(_FIXTURE_TEXT)), _FIXTURE_TEXT)

    def test_path_length_of_fixture(self):
        t = traversal.parse(_FIXTURE_TEXT)
        self.assertAlmostEqual(traversal.path_length(t), 480.0)

    def test_traversal_is_frozen(self):
        t = traversal.parse(_FIXTURE_TEXT)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            t.seed = 1


class NegativeParseTests(unittest.TestCase):
    def assertRejects(self, text, fragment=None):
        with self.assertRaises(TraversalError) as ctx:
            traversal.parse(text)
        if fragment is not None:
            self.assertIn(fragment, str(ctx.exception))

    def test_wrong_header(self):
        self.assertRejects(_with_line(0, "luminumbra.traversal.v2"), "first line")

    def test_field_order_swapped(self):
        lines = _lines()
        lines[1], lines[2] = lines[2], lines[1]
        self.assertRejects(_join(lines), "duration_seconds")

    def test_tick_rate_60(self):
        self.assertRejects(_with_line(2, "tick_rate 60"), "tick_rate must be 30")

    def test_revision_5(self):
        self.assertRejects(_with_line(6, "preset_revision 5"), "preset_revision must be 6")

    def test_identity_too_short(self):
        self.assertRejects(_with_line(7, "preset_identity 026f24207a8ffc7"), "preset_identity")

    def test_identity_uppercase(self):
        self.assertRejects(_with_line(7, "preset_identity 026F24207A8FFC7E"), "preset_identity")

    def test_identity_non_hex(self):
        self.assertRejects(_with_line(7, "preset_identity 026f24207a8ffc7g"), "preset_identity")

    def test_content_identity_empty(self):
        self.assertRejects(_with_line(8, "content_identity "), "content_identity")

    def test_content_identity_too_long(self):
        self.assertRejects(_with_line(8, "content_identity " + "1" * 21), "content_identity")

    def test_content_identity_non_digit(self):
        self.assertRejects(_with_line(8, "content_identity 1663601005224787074a"), "content_identity")

    def test_cold_cache_false(self):
        self.assertRejects(_with_line(10, "cold_cache false"), "cold_cache must be true")

    def test_negative_seed(self):
        self.assertRejects(_with_line(4, "seed -1"), "seed must be")

    def test_seed_above_uint32(self):
        self.assertRejects(_with_line(4, "seed 4294967296"), "seed must be")

    def test_expected_ticks_mismatch(self):
        self.assertRejects(_with_line(9, "expected_ticks 1799"), "expected_ticks does not match")

    def test_expected_ticks_above_limit(self):
        lines = _lines()
        lines[1] = "duration_seconds 600.0333333333333"
        lines[9] = "expected_ticks 18001"
        self.assertRejects(_join(lines), "expected_ticks must be in")

    def test_single_point(self):
        lines = _lines()
        text = _join(lines[:11] + ["points 1", lines[12]]) + "\n"
        self.assertRejects(text, "points count must be")

    def test_too_many_points(self):
        header = _lines()[:11]
        points = ["point %d 80 8 0 -6" % i for i in range(1025)]
        text = _join(header + ["points 1025"] + points) + "\n"
        self.assertRejects(text, "points count must be")

    def test_zero_length_segment(self):
        self.assertRejects(_with_line(13, "point 8 80 8 10 -6"), "zero length")

    def test_coordinate_above_limit(self):
        self.assertRejects(_with_line(12, "point 32000.5 80 8 0 -6"), "coordinate exceeds")

    def test_pitch_of_ninety(self):
        self.assertRejects(_with_line(12, "point 8 80 8 0 90"), "pitch")

    def test_exponent_token(self):
        self.assertRejects(_with_line(1, "duration_seconds 6e1"), "duration_seconds")

    def test_crlf(self):
        self.assertRejects(_FIXTURE_TEXT.replace("\n", "\r\n"), "CR")

    def test_bom(self):
        self.assertRejects("\ufeff" + _FIXTURE_TEXT, "byte order mark")

    def test_missing_final_lf(self):
        self.assertRejects(_FIXTURE_TEXT.rstrip("\n"), "final LF")

    def test_double_final_lf_is_blank_line(self):
        self.assertRejects(_FIXTURE_TEXT + "\n", "blank lines")

    def test_trailing_token(self):
        self.assertRejects(_with_line(14, "point 488 80 8 0 -6 7"), "expected 'point")

    def test_trailing_line(self):
        self.assertRejects(_FIXTURE_TEXT + "extra\n", "points count")

    def test_path_too_short(self):
        self.assertRejects(_with_line(3, "speed_mps 9"), "path length")

    def test_oversize_file(self):
        text = _FIXTURE_TEXT + "#" * 1048576
        self.assertRejects(text, "1 MiB")

    def test_bad_preset_characters(self):
        self.assertRejects(_with_line(5, "preset Default"), "preset must be")

    def test_empty_preset(self):
        self.assertRejects(_with_line(5, "preset "), "preset must be")


class ValidateTests(unittest.TestCase):
    def _good(self, **overrides):
        base = traversal.parse(_FIXTURE_TEXT)
        return dataclasses.replace(base, **overrides)

    def test_good_value_validates(self):
        traversal.validate(self._good())

    def test_validate_rejects_bad_points_type(self):
        t = self._good(points=list(self._good().points))
        with self.assertRaises(TraversalError):
            traversal.validate(t)

    def test_validate_rejects_expected_ticks_bool(self):
        with self.assertRaises(TraversalError):
            traversal.validate(self._good(expected_ticks=True))

    def test_emit_refuses_invalid_value(self):
        with self.assertRaises(TraversalError):
            traversal.emit(self._good(tick_rate=60))

    def test_emit_refuses_text_over_one_mib(self):
        # The yaw field is only checked as a plain number token, so a long
        # fractional token keeps the value valid while the text grows past 1 MiB.
        big = "0." + "0" * 1100000 + "1"
        self.assertIsNotNone(traversal._NUM_RE.fullmatch(big))
        base = traversal.parse(_FIXTURE_TEXT)
        t = dataclasses.replace(base, points=(("8", "80", "8", big, "-6"),) + base.points[1:])
        traversal.validate(t)
        with self.assertRaisesRegex(TraversalError, "traversal exceeds 1 MiB"):
            traversal.emit(t)


if __name__ == "__main__":
    unittest.main()
