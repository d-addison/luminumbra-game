import contextlib
import copy
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_TOOLS = _REPO / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import traversal_tool  # noqa: E402
import validate_content  # noqa: E402
from lumlib.schema import SchemaError  # noqa: E402
from validators import workload  # noqa: E402

_FIXTURES = _REPO / "tests" / "fixtures"
_FIXTURE_BYTES = (_FIXTURES / "engine-surface-flight.traversal").read_bytes()
_WORKLOAD_PATH = "content/workloads/surface-flight.json"
_TRAVERSAL_PATH = "content/workloads/traversal/surface-flight.traversal"
_RECEIPT_PATH = "content/receipts/receipt-01.json"
_CAVERNS_PATH = _FIXTURES / "engine-caverns-preset-rev6.json"


def _surface_flight():
    return {
        "schema": workload.WORKLOAD_SCHEMA,
        "id": "surface-flight",
        "kind": "camera-traversal",
        "description": "Engine reference surface flight, 60 s at 30 Hz along +X",
        "preset": "default",
        "seed": 424242,
        "duration_seconds": 60,
        "tick_rate": 30,
        "speed_mps": 8,
        "pins": {
            "preset_identity": "026f24207a8ffc7e",
            "content_identity": "16636010052247870746",
        },
        "status": "pinned",
        "points": [[8, 80, 8, 0, -6], [248, 80, 8, 0, -6], [488, 80, 8, 0, -6]],
        "events": [],
        "native": {"commands": "docs/performance-workloads.md", "receipt": None},
    }


def _pending():
    obj = _surface_flight()
    obj["id"] = "cave-walk"
    obj["preset"] = "caverns"
    obj["speed_mps"] = 4
    obj["pins"] = {"preset_identity": "ebf1507e76482151", "content_identity": None}
    obj["status"] = "pending-discovery"
    obj["points"] = None
    return obj


def _edit(event_id, tick, radius=6, mode="fill"):
    return {
        "id": event_id,
        "tick": tick,
        "kind": "edit",
        "x": None,
        "y": None,
        "z": None,
        "radius_m": radius,
        "mode": mode,
    }


def _snapshot(event_id, tick):
    return {"id": event_id, "tick": tick, "kind": "snapshot"}


def _problems(obj, stem="surface-flight", allow_pending=False, release=False):
    return workload.workload_problems(obj, stem, _WORKLOAD_PATH, allow_pending, release)


def _run(*argv):
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = traversal_tool.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def _write_tree(root, files):
    for rel, data in files.items():
        path = Path(root, *rel.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, str):
            data = data.encode("utf-8")
        path.write_bytes(data)


def _json_bytes(obj):
    return (json.dumps(obj, indent=2) + "\n").encode("utf-8")


def _receipt(traversal_sha=None):
    return {
        "schema": workload.RECEIPT_SCHEMA,
        "workload": "surface-flight",
        "cell_id": "cell-01",
        "profile": "quality",
        "display": "3840x1600",
        "report_sha256": "a" * 64,
        "verdict": "pass",
        "verdict_sha256": "b" * 64,
        "traversal_sha256": traversal_sha or hashlib.sha256(_FIXTURE_BYTES).hexdigest(),
        "preset_identity": "026f24207a8ffc7e",
        "content_identity": "16636010052247870746",
        "adapter": "NVIDIA GeForce RTX 5070 Ti",
        "engine_revision": "b56cdba12e425ed2786778d5b02c98ba61466584",
        "game_revision": "c" * 40,
    }


def _good_tree(receipt=None):
    """Return the files of a valid tree; a receipt binds the workload to _RECEIPT_PATH."""
    obj = _surface_flight()
    files = {_TRAVERSAL_PATH: _FIXTURE_BYTES}
    if receipt is not None:
        obj["native"]["receipt"] = _RECEIPT_PATH
        files[_RECEIPT_PATH] = _json_bytes(receipt)
    files[_WORKLOAD_PATH] = _json_bytes(obj)
    return files


def _tree_problems(files, release=False, allow_pending=False):
    with tempfile.TemporaryDirectory() as tmp:
        _write_tree(tmp, files)
        return validate_content.validate_tree(tmp, allow_pending=allow_pending, release=release)


def _source_bytes(duration_text, speed_text):
    """Return the surface-flight source with the given duration and speed number tokens."""
    text = json.dumps(_surface_flight())
    text = text.replace('"duration_seconds": 60', '"duration_seconds": ' + duration_text, 1)
    text = text.replace('"speed_mps": 8', '"speed_mps": ' + speed_text, 1)
    return text.encode("utf-8")


class CommittedWorkloadTests(unittest.TestCase):
    def test_committed_content_validates_with_allow_pending(self):
        self.assertEqual(validate_content.validate_tree(str(_REPO), allow_pending=True, release=False), [])

    def test_committed_pending_workloads_are_refused_without_flag(self):
        problems = validate_content.validate_tree(str(_REPO), allow_pending=False, release=False)
        self.assertTrue(any("cave-walk.json" in p and "pending-discovery" in p for p in problems))
        self.assertTrue(any("edited-world-tour.json" in p for p in problems))

    def test_check_passes_on_repo_root(self):
        code, out, _ = _run("check", "--root", str(_REPO))
        self.assertEqual(code, 0, out)
        self.assertIn("traversal ok", out)

    def test_surface_flight_base_is_valid(self):
        self.assertEqual(_problems(_surface_flight()), [])

    def test_emit_surface_flight_matches_fixture(self):
        code, out, err = _run("emit", str(_REPO / "content" / "workloads" / "surface-flight.json"))
        self.assertEqual(code, 0, err)
        self.assertEqual(out.encode("utf-8"), _FIXTURE_BYTES)

    def test_emit_output_file_matches_fixture_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp, "out.traversal")
            code, _, err = _run(
                "emit", str(_REPO / "content" / "workloads" / "surface-flight.json"), "-o", str(target)
            )
            self.assertEqual(code, 0, err)
            self.assertEqual(target.read_bytes(), _FIXTURE_BYTES)

    def test_pending_cave_walk_is_valid_with_allow_pending(self):
        self.assertEqual(_problems(_pending(), stem="cave-walk", allow_pending=True), [])

    def test_identity_prints_cave_walk_pin(self):
        code, out, err = _run("identity", str(_CAVERNS_PATH))
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "ebf1507e76482151")


class WorkloadSourceTests(unittest.TestCase):
    def assertProblem(self, problems, fragment):
        self.assertTrue(problems, "expected a problem containing %r" % fragment)
        self.assertTrue(any(fragment in p for p in problems), "%r not in %r" % (fragment, problems))

    def test_unknown_key(self):
        obj = _surface_flight()
        obj["extra"] = 1
        self.assertProblem(_problems(obj), "unknown key 'extra'")

    def test_future_schema_is_refused(self):
        obj = _surface_flight()
        obj["schema"] = "luminumbra.game.workload.v2"
        with self.assertRaises(SchemaError) as ctx:
            workload.check_workload(obj, "surface-flight", _WORKLOAD_PATH, False, False)
        self.assertIn("future schema version", str(ctx.exception))

    def test_id_must_equal_stem(self):
        self.assertProblem(_problems(_surface_flight(), stem="cave-walk"), "id must equal the file stem")

    def test_id_must_be_kebab(self):
        obj = _surface_flight()
        obj["id"] = "Surface_Flight"
        self.assertProblem(_problems(obj, stem="Surface_Flight"), "lowercase kebab-case")

    def test_tick_rate_must_be_30(self):
        obj = _surface_flight()
        obj["tick_rate"] = 60
        self.assertProblem(_problems(obj), "tick_rate must be 30")

    def test_tick_rate_float_is_refused(self):
        obj = _surface_flight()
        obj["tick_rate"] = Decimal("30.0")
        self.assertProblem(_problems(obj), "tick_rate must be 30")

    def test_duration_times_rate_must_be_integer(self):
        obj = _surface_flight()
        obj["duration_seconds"] = Decimal("0.05")
        self.assertProblem(_problems(obj), "must be an integer")

    def test_ticks_over_cap_are_refused(self):
        obj = _surface_flight()
        obj["duration_seconds"] = Decimal("600.1")
        self.assertProblem(_problems(obj), "must be in [1, 18000]")

    def test_ticks_at_cap_are_accepted_when_pending(self):
        obj = _pending()
        obj["duration_seconds"] = 600
        self.assertEqual(_problems(obj, stem="cave-walk", allow_pending=True), [])

    def test_preset_identity_must_be_lowercase_hex(self):
        obj = _surface_flight()
        obj["pins"]["preset_identity"] = "026F24207A8FFC7E"
        self.assertProblem(_problems(obj), "pins.preset_identity must be")

    def test_content_identity_must_be_digits(self):
        obj = _surface_flight()
        obj["pins"]["content_identity"] = "abc"
        self.assertProblem(_problems(obj), "pins.content_identity must be")

    def test_content_identity_longer_than_20_digits_is_refused(self):
        obj = _surface_flight()
        obj["pins"]["content_identity"] = "1" * 21
        self.assertProblem(_problems(obj), "pins.content_identity must be")

    def test_pins_must_have_both_keys(self):
        obj = _surface_flight()
        del obj["pins"]["content_identity"]
        self.assertProblem(_problems(obj), "missing key 'content_identity'")

    def test_pinned_with_null_pins_is_refused(self):
        obj = _surface_flight()
        obj["pins"]["preset_identity"] = None
        self.assertProblem(_problems(obj), "pinned workload needs both pins")

    def test_pinned_with_null_points_is_refused(self):
        obj = _surface_flight()
        obj["points"] = None
        self.assertProblem(_problems(obj), "pinned workload needs points")

    def test_pending_without_allow_pending_is_refused(self):
        self.assertProblem(
            _problems(_pending(), stem="cave-walk"), "status pending-discovery is not allowed in this mode"
        )

    def test_release_with_pending_is_refused(self):
        self.assertProblem(
            _problems(_pending(), stem="cave-walk", allow_pending=True, release=True),
            "release mode requires status 'pinned'",
        )

    def test_release_refuses_null_event_coordinates(self):
        obj = _surface_flight()
        obj["events"] = [_edit("edit-1", 300)]
        self.assertProblem(_problems(obj, release=True), "null coordinates are refused in release mode")

    def test_pinned_edit_with_null_coordinates_is_refused(self):
        obj = _surface_flight()
        obj["events"] = [_edit("edit-1", 300)]
        self.assertProblem(_problems(obj), "null coordinates are refused for a pinned workload")

    def test_pinned_edit_with_coordinates_is_accepted(self):
        obj = _surface_flight()
        event = _edit("edit-1", 300)
        event.update({"x": 100, "y": 80, "z": 100})
        obj["events"] = [event]
        self.assertEqual(_problems(obj), [])

    def test_pending_edit_with_null_coordinates_is_accepted(self):
        obj = _pending()
        obj["events"] = [_edit("edit-1", 300)]
        self.assertEqual(_problems(obj, stem="cave-walk", allow_pending=True), [])

    def test_pending_with_empty_points_array_is_refused(self):
        obj = _pending()
        obj["points"] = []
        self.assertProblem(
            _problems(obj, stem="cave-walk", allow_pending=True), "pending-discovery workload must have points null"
        )

    def test_pending_with_points_array_is_refused(self):
        obj = _pending()
        obj["points"] = [[8, 80, 8, 0, -6], [248, 80, 8, 0, -6]]
        self.assertProblem(
            _problems(obj, stem="cave-walk", allow_pending=True), "pending-discovery workload must have points null"
        )

    def test_release_requires_native_receipt(self):
        self.assertProblem(_problems(_surface_flight(), release=True), "native.receipt must be set in release mode")

    def test_release_with_receipt_file_is_clean(self):
        self.assertEqual(_tree_problems(_good_tree(_receipt()), release=True), [])

    def test_release_receipt_missing_file_is_refused(self):
        files = _good_tree(_receipt())
        del files[_RECEIPT_PATH]
        problems = _tree_problems(files, release=True)
        expected = "%s: native.receipt '%s' does not exist" % (_WORKLOAD_PATH, _RECEIPT_PATH)
        self.assertIn(expected, problems)

    def test_release_receipt_naming_other_workload_is_refused(self):
        receipt = _receipt()
        receipt["workload"] = "other"
        problems = _tree_problems(_good_tree(receipt), release=True)
        expected = "%s: native.receipt '%s' names workload 'other'" % (_WORKLOAD_PATH, _RECEIPT_PATH)
        self.assertIn(expected, problems)

    def test_release_receipt_with_fail_verdict_is_refused(self):
        receipt = _receipt()
        receipt["verdict"] = "fail"
        problems = _tree_problems(_good_tree(receipt), release=True)
        expected = (
            "%s: native.receipt '%s' fails release validation: verdict must be pass in release mode"
            % (_WORKLOAD_PATH, _RECEIPT_PATH)
        )
        self.assertIn(expected, problems)
        self.assertEqual(_tree_problems(_good_tree(receipt)), [])

    def test_release_receipt_symlink_outside_root_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp, "root")
            outside = Path(tmp, "outside.json")
            outside.write_bytes(_json_bytes(_receipt()))
            files = _good_tree(_receipt())
            del files[_RECEIPT_PATH]
            _write_tree(str(root), files)
            link = Path(root, *_RECEIPT_PATH.split("/"))
            link.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.symlink(str(outside), str(link))
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are not available on this platform")
            problems = validate_content.validate_tree(str(root), allow_pending=False, release=True)
        expected = "%s: native.receipt '%s' resolves outside content/receipts/" % (_WORKLOAD_PATH, _RECEIPT_PATH)
        self.assertIn(expected, problems)

    def test_committed_surface_flight_is_clean_without_release(self):
        problems = workload.tree_problems(str(_REPO), allow_pending=False, release=False)
        self.assertEqual([p for p in problems if "surface-flight" in p], [])

    def test_receipt_path_with_drive_colon_is_refused(self):
        obj = _surface_flight()
        obj["native"]["receipt"] = "content/receipts/C:/outside.json"
        self.assertProblem(_problems(obj), "native.receipt must be")

    def test_zero_length_segment(self):
        obj = _surface_flight()
        obj["points"] = [[8, 80, 8, 0, -6], [8, 80, 8, 0, -6], [488, 80, 8, 0, -6]]
        self.assertProblem(_problems(obj), "zero length")

    def test_source_file_with_exponent_token_is_refused_at_load(self):
        text = json.dumps(_surface_flight()).replace("[[8, 80", "[[8e0, 80")
        self.assertIn("8e0", text)
        problems = _tree_problems({_WORKLOAD_PATH: text.encode("utf-8")})
        self.assertTrue(any(_WORKLOAD_PATH in p and "exponent" in p for p in problems), problems)

    def test_fixed_point_radius_keeps_all_digits(self):
        self.assertEqual(workload._number_text(Decimal("0.00000001"), "radius"), "0.00000001")

    def test_source_file_with_fixed_point_radius_is_accepted(self):
        obj = _pending()
        obj["events"] = [_edit("edit-1", 10)]
        text = json.dumps(obj).replace('"radius_m": 6', '"radius_m": 0.00000001')
        self.assertIn('"radius_m": 0.00000001', text)
        self.assertEqual(_tree_problems({"content/workloads/cave-walk.json": text.encode("utf-8")}, allow_pending=True), [])

    def test_point_must_have_five_fields(self):
        obj = _surface_flight()
        obj["points"][1] = [248, 80, 8, 0]
        self.assertProblem(_problems(obj), "points[1] must be")

    def test_seed_out_of_range(self):
        obj = _surface_flight()
        obj["seed"] = 4294967296
        self.assertProblem(_problems(obj), "seed must be an integer")

    def test_native_commands_are_fixed(self):
        obj = _surface_flight()
        obj["native"]["commands"] = "docs/other.md"
        self.assertProblem(_problems(obj), "native.commands must be")

    def test_native_receipt_must_be_under_receipts(self):
        obj = _surface_flight()
        obj["native"]["receipt"] = "content/workloads/receipt.json"
        self.assertProblem(_problems(obj), "native.receipt must be")

    def test_too_many_events(self):
        obj = _pending()
        obj["events"] = [_snapshot("snap-%d" % tick, tick) for tick in range(1, 18)]
        self.assertProblem(_problems(obj, stem="cave-walk", allow_pending=True), "at most 16")

    def test_events_must_ascend(self):
        obj = _pending()
        obj["events"] = [_edit("edit-1", 600), _snapshot("snap-1", 300)]
        self.assertProblem(
            _problems(obj, stem="cave-walk", allow_pending=True), "strictly ascending"
        )

    def test_event_tick_zero_is_refused(self):
        obj = _pending()
        obj["events"] = [_snapshot("snap-1", 0)]
        self.assertProblem(_problems(obj, stem="cave-walk", allow_pending=True), "tick must be an integer in [1, 1800]")

    def test_event_tick_past_expected_is_refused(self):
        obj = _pending()
        obj["events"] = [_snapshot("snap-1", 1801)]
        self.assertProblem(_problems(obj, stem="cave-walk", allow_pending=True), "tick must be an integer in [1, 1800]")

    def test_unknown_event_kind_is_refused(self):
        obj = _pending()
        obj["events"] = [{"id": "replay-1", "tick": 10, "kind": "replay"}]
        self.assertProblem(_problems(obj, stem="cave-walk", allow_pending=True), "kind must be 'edit' or 'snapshot'")

    def test_bake_kind_is_refused(self):
        obj = _pending()
        obj["events"] = [{"id": "bake-1", "tick": 10, "kind": "bake"}]
        self.assertProblem(_problems(obj, stem="cave-walk", allow_pending=True), "kind must be 'edit' or 'snapshot'")

    def test_material_key_is_refused(self):
        obj = _pending()
        event = _edit("edit-1", 10)
        event["material"] = "stone"
        obj["events"] = [event]
        self.assertProblem(_problems(obj, stem="cave-walk", allow_pending=True), "unknown key 'material'")

    def test_edit_missing_radius_is_refused(self):
        obj = _pending()
        event = _edit("edit-1", 10)
        del event["radius_m"]
        obj["events"] = [event]
        self.assertProblem(_problems(obj, stem="cave-walk", allow_pending=True), "missing key 'radius_m'")

    def test_duplicate_event_ids_are_refused(self):
        obj = _pending()
        obj["events"] = [_snapshot("same", 10), _snapshot("same", 20)]
        self.assertProblem(_problems(obj, stem="cave-walk", allow_pending=True), "is duplicated")

    def test_edited_tour_events_are_accepted_as_source(self):
        obj = _pending()
        obj["id"] = "edited-world-tour"
        obj["preset"] = "default"
        obj["speed_mps"] = 8
        obj["pins"] = {"preset_identity": "026f24207a8ffc7e", "content_identity": None}
        obj["events"] = [
            _edit("edit-fill-above-pristine", 300),
            _snapshot("snapshot-1", 600),
            _edit("edit-dig-1", 900, radius=4, mode="dig"),
            _snapshot("snapshot-2", 1200),
        ]
        self.assertEqual(_problems(obj, stem="edited-world-tour", allow_pending=True), [])


class EmitTests(unittest.TestCase):
    def _emit_file(self, obj, name="surface-flight.json"):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, name)
            path.write_bytes(_json_bytes(obj))
            return _run("emit", str(path))

    def test_emit_refuses_pending(self):
        code, _, err = self._emit_file(_pending(), name="cave-walk.json")
        self.assertEqual(code, 1)
        self.assertIn("emit refuses pending workloads", err)

    def test_emit_refuses_events(self):
        obj = _surface_flight()
        obj["events"] = [_snapshot("snap-1", 600)]
        code, _, err = self._emit_file(obj)
        self.assertEqual(code, 1)
        self.assertIn("events require traversal v2", err)


class ValidateCommandTests(unittest.TestCase):
    def test_validate_pending_needs_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp, {"content/workloads/cave-walk.json": _json_bytes(_pending())})
            code, out, _ = _run("validate", "--root", tmp)
            self.assertEqual(code, 1)
            self.assertIn("pending-discovery", out)
            code, out, _ = _run("validate", "--root", tmp, "--allow-pending")
            self.assertEqual(code, 0, out)

    def test_check_flags_missing_committed_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp, {_WORKLOAD_PATH: _json_bytes(_surface_flight())})
            code, out, _ = _run("check", "--root", tmp)
            self.assertEqual(code, 1)
            self.assertIn("missing committed traversal", out)

    def test_check_flags_golden_mismatch(self):
        altered = _FIXTURE_BYTES.replace(b"point 488 80 8 0 -6", b"point 488 80 8 1 -6")
        self.assertNotEqual(altered, _FIXTURE_BYTES)
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp, {_WORKLOAD_PATH: _json_bytes(_surface_flight()), _TRAVERSAL_PATH: altered})
            code, out, _ = _run("check", "--root", tmp)
            self.assertEqual(code, 1)
            self.assertIn("does not match the emitted source", out)


class TraversalFileTests(unittest.TestCase):
    def test_committed_traversal_without_source_is_refused(self):
        problems = _tree_problems({_TRAVERSAL_PATH: _FIXTURE_BYTES})
        self.assertTrue(any("no source workload" in p for p in problems), problems)

    def test_golden_mismatch_through_registry(self):
        altered = _FIXTURE_BYTES.replace(b"point 488 80 8 0 -6", b"point 488 80 8 1 -6")
        problems = _tree_problems({_WORKLOAD_PATH: _json_bytes(_surface_flight()), _TRAVERSAL_PATH: altered})
        self.assertTrue(any("does not match the emitted source" in p for p in problems), problems)

    def test_pinned_source_with_matching_traversal_is_clean(self):
        self.assertEqual(_tree_problems(_good_tree()), [])

    def test_expected_ticks_over_cap_is_refused_by_registry_and_check(self):
        lines = [
            "luminumbra.traversal.v1",
            "duration_seconds 600.0333333333333",
            "tick_rate 30",
            "speed_mps 1",
            "seed 424242",
            "preset default",
            "preset_revision 6",
            "preset_identity 026f24207a8ffc7e",
            "content_identity 16636010052247870746",
            "expected_ticks 18001",
            "cold_cache true",
            "points 2",
            "point 0 0 0 0 0",
            "point 1000 0 0 0 0",
        ]
        text = "\n".join(lines) + "\n"
        rel = "content/workloads/traversal/edge-cap.traversal"
        problems = _tree_problems({rel: text.encode("utf-8")})
        self.assertTrue(any(p == rel + ": expected_ticks must be in [1, 18000]" for p in problems), problems)
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp, {rel: text.encode("utf-8")})
            code, out, _ = _run("check", "--root", tmp)
        self.assertEqual(code, 1)
        self.assertIn("expected_ticks must be in [1, 18000]", out)

    def test_expected_ticks_over_cap_is_refused_by_lumlib_validate(self):
        from lumlib import traversal as lum_traversal

        t = lum_traversal.Traversal(
            duration="600.0333333333333",
            tick_rate=30,
            speed="1",
            seed=424242,
            preset="default",
            preset_revision=6,
            preset_identity="026f24207a8ffc7e",
            content_identity="16636010052247870746",
            expected_ticks=18001,
            points=(("0", "0", "0", "0", "0"), ("1000", "0", "0", "0", "0")),
        )
        with self.assertRaises(lum_traversal.TraversalError) as ctx:
            lum_traversal.validate(t)
        self.assertIn("expected_ticks must be in [1, 18000]", str(ctx.exception))


class ReceiptTests(unittest.TestCase):
    def _problems_for(self, receipt, release=False):
        return _tree_problems(_good_tree(receipt), release=release)

    def assertReceiptProblem(self, receipt, fragment, release=False):
        problems = self._problems_for(receipt, release=release)
        self.assertTrue(any(fragment in p for p in problems), "%r not in %r" % (fragment, problems))

    def test_valid_receipt_is_clean_in_both_modes(self):
        self.assertEqual(self._problems_for(_receipt()), [])
        self.assertEqual(self._problems_for(_receipt(), release=True), [])

    def test_unknown_workload(self):
        receipt = _receipt()
        receipt["workload"] = "nope"
        self.assertReceiptProblem(receipt, "unknown workload 'nope'")

    def test_unknown_key(self):
        receipt = _receipt()
        receipt["extra"] = 1
        self.assertReceiptProblem(receipt, "unknown key 'extra'")

    def test_identity_mismatch(self):
        receipt = _receipt()
        receipt["preset_identity"] = "0000000000000000"
        self.assertReceiptProblem(receipt, "preset_identity does not match")

    def test_bad_hash_format(self):
        receipt = _receipt()
        receipt["traversal_sha256"] = "ABC"
        self.assertReceiptProblem(receipt, "traversal_sha256 must be")

    def test_adapter_mismatch(self):
        receipt = _receipt()
        receipt["adapter"] = "NVIDIA GeForce RTX 4090"
        self.assertReceiptProblem(receipt, "adapter must name the qualified renderer")

    def test_traversal_hash_mismatch(self):
        receipt = _receipt(traversal_sha="0" * 64)
        self.assertReceiptProblem(receipt, "traversal_sha256 does not match")

    def test_release_needs_pass(self):
        receipt = _receipt()
        receipt["verdict"] = "unevaluated"
        self.assertEqual(self._problems_for(receipt), [])
        self.assertReceiptProblem(receipt, "verdict must be pass in release mode", release=True)

    def test_receipt_outside_receipts_dir_is_refused(self):
        problems = _tree_problems({"content/elsewhere.json": _json_bytes(_receipt())})
        self.assertEqual(problems, ["content/elsewhere.json: receipts must live under content/receipts/"])


class MissingTraversalTests(unittest.TestCase):
    def test_release_refuses_missing_committed_traversal(self):
        files = _good_tree(_receipt())
        del files[_TRAVERSAL_PATH]
        problems = _tree_problems(files, release=True)
        expected = "%s: missing committed traversal %s" % (_WORKLOAD_PATH, _TRAVERSAL_PATH)
        self.assertEqual(problems.count(expected), 1, problems)

    def test_allow_pending_refuses_missing_committed_traversal(self):
        files = _good_tree(_receipt())
        del files[_TRAVERSAL_PATH]
        problems = _tree_problems(files, allow_pending=True)
        expected = "%s: missing committed traversal %s" % (_WORKLOAD_PATH, _TRAVERSAL_PATH)
        self.assertEqual(problems.count(expected), 1, problems)

    def test_normal_mode_refuses_missing_committed_traversal_once(self):
        files = _good_tree()
        del files[_TRAVERSAL_PATH]
        problems = _tree_problems(files)
        expected = "%s: missing committed traversal %s" % (_WORKLOAD_PATH, _TRAVERSAL_PATH)
        self.assertEqual(problems, [expected])


class DurationToleranceTests(unittest.TestCase):
    def test_one_tick_duration_is_accepted_and_emitted(self):
        source = _source_bytes("0.03333333333333333", "0.001")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "surface-flight.json")
            path.write_bytes(source)
            code, out, err = _run("emit", str(path))
        self.assertEqual(code, 0, err)
        self.assertIn("duration_seconds 0.03333333333333333\n", out)
        self.assertIn("expected_ticks 1\n", out)
        self.assertEqual(_tree_problems({_WORKLOAD_PATH: source, _TRAVERSAL_PATH: out.encode("utf-8")}), [])

    def test_one_tick_duration_passes_lumlib_validate(self):
        from lumlib import traversal as lum_traversal

        source = _source_bytes("0.03333333333333333", "0.001")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "surface-flight.json")
            path.write_bytes(source)
            code, out, err = _run("emit", str(path))
        self.assertEqual(code, 0, err)
        traversal_obj = lum_traversal.parse(out)
        self.assertEqual(traversal_obj.expected_ticks, 1)
        lum_traversal.validate(traversal_obj)

    def test_duration_off_the_tick_grid_is_refused(self):
        obj = _surface_flight()
        obj["duration_seconds"] = Decimal("0.0333334")
        problems = _problems(obj)
        self.assertTrue(
            any("duration_seconds * tick_rate must be an integer" in p for p in problems), problems
        )

    def test_just_inside_the_tolerance_is_accepted_by_pending_and_pinned(self):
        # 0.10000000003333333 s * 30 is within 1e-9 of three ticks in both the exact and the float product.
        for text in ("0.10000000003333333",):
            obj = _pending()
            obj["duration_seconds"] = Decimal(text)
            problems = _problems(obj, stem="cave-walk", allow_pending=True)
            self.assertFalse(any("tick_rate must be an integer" in p for p in problems), problems)

    def test_exact_inside_but_float_outside_the_tolerance_is_refused(self):
        # The exact tick error is 9.999998e-10 but the engine's binary float error is about 1.00000008e-9.
        text = Decimal("0.13333333336666666")
        pinned = _surface_flight()
        pinned["duration_seconds"] = text
        pinned_problems = _problems(pinned)
        self.assertTrue(any("tick_rate must be an integer" in p for p in pinned_problems), pinned_problems)
        pending = _pending()
        pending["duration_seconds"] = text
        pending_problems = _problems(pending, stem="cave-walk", allow_pending=True)
        self.assertTrue(any("tick_rate must be an integer" in p for p in pending_problems), pending_problems)

    def test_just_outside_the_tolerance_is_refused(self):
        obj = _pending()
        obj["duration_seconds"] = Decimal("0.1000000002")
        problems = _problems(obj, stem="cave-walk", allow_pending=True)
        self.assertTrue(any("tick_rate must be an integer" in p for p in problems), problems)

    def test_float_tick_boundary_accepts_one_tick_duration(self):
        obj = _pending()
        obj["duration_seconds"] = Decimal("0.03333333333333333")
        self.assertEqual(_problems(obj, stem="cave-walk", allow_pending=True), [])


class UnreadableFileTests(unittest.TestCase):
    """Files that cannot be read are refused with one-line PATH: cannot read: reason rows."""

    _LINK = "content/workloads/x.json"

    def _dangling_tree(self, tmp):
        Path(tmp, "content", "workloads").mkdir(parents=True)
        try:
            os.symlink(str(Path(tmp, "missing-target.json")), str(Path(tmp, *self._LINK.split("/"))))
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available on this platform")

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are not available on this platform")
    def test_dangling_symlink_is_refused_by_tree_problems(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._dangling_tree(tmp)
            problems = workload.tree_problems(tmp, allow_pending=False)
        self.assertEqual(len(problems), 1, problems)
        self.assertTrue(problems[0].startswith(self._LINK + ": cannot read: "), problems)
        self.assertNotIn("Traceback", problems[0])

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are not available on this platform")
    def test_dangling_symlink_fails_cli_validate_with_rc_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._dangling_tree(tmp)
            code, out, err = _run("validate", "--root", tmp)
        self.assertEqual(code, 1, err)
        lines = out.splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith(self._LINK + ": cannot read: "), lines)
        self.assertNotIn("Traceback", err)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are not available on this platform")
    def test_dangling_symlink_fails_cli_check_with_rc_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._dangling_tree(tmp)
            code, out, err = _run("check", "--root", tmp)
        self.assertEqual(code, 1, err)
        lines = out.splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith(self._LINK + ": cannot read: "), lines)
        self.assertNotIn("Traceback", err)


class DeepJsonTests(unittest.TestCase):
    _DEEP = ("[" * 200000 + "]" * 200000).encode("utf-8")
    _REASON = "not valid JSON: nesting is too deep"

    def test_emit_refuses_deep_json_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "surface-flight.json")
            path.write_bytes(self._DEEP)
            code, out, err = _run("emit", str(path))
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(err.splitlines(), ["%s: %s" % (path, self._REASON)])

    def test_validate_refuses_deep_workload_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp, {_WORKLOAD_PATH: self._DEEP})
            code, out, err = _run("validate", "--root", tmp)
        self.assertEqual(code, 1, err)
        self.assertEqual(out.splitlines(), ["%s: %s" % (_WORKLOAD_PATH, self._REASON)])
        self.assertNotIn("Traceback", err)

    def test_check_refuses_deep_workload_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_tree(tmp, {_WORKLOAD_PATH: self._DEEP})
            code, out, err = _run("check", "--root", tmp)
        self.assertEqual(code, 1, err)
        self.assertEqual(out.splitlines(), ["%s: %s" % (_WORKLOAD_PATH, self._REASON)])
        self.assertNotIn("Traceback", err)

    def test_identity_refuses_deep_preset_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "preset.json")
            path.write_bytes(self._DEEP)
            code, out, err = _run("identity", str(path))
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines(), ["%s: %s" % (path, self._REASON)])
        self.assertNotIn("Traceback", err)


if __name__ == "__main__":
    unittest.main()
