import copy
import hashlib
import json
import os
from dataclasses import replace
from types import SimpleNamespace
from unittest import mock
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_TOOLS = _REPO / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from lumlib import identity, schema  # noqa: E402
from validators import Context, scene  # noqa: E402

_CAPTURE = b"synthetic CI capture bytes; not a native measurement\x00\xff"
_CAPTURE_HASH = hashlib.sha256(_CAPTURE).hexdigest()
_ENGINE = "1" * 40
_GAME = "2" * 40

_SET_PATH = "content/scenes/distant-world.json"
_PRESET_PATH = "content/presets/cave_dense.json"
_SIDECAR_PATH = "content/presets/cave_dense.identity.json"
_RECEIPT_PATH = "content/receipts/scene-cave-mouth-2km-quality.json"
_CAVERNS_FIXTURE = _REPO / "tests" / "fixtures" / "engine-caverns-preset.json"
_DEFAULT_FIXTURE = _REPO / "tests" / "fixtures" / "engine-default-preset.json"
_PRESET_FILE = _REPO / "content" / "presets" / "cave_dense.json"
_SIDECAR_FILE = _REPO / "content" / "presets" / "cave_dense.identity.json"
_SCENE_FILE = _REPO / "content" / "scenes" / "distant-world.json"


def _ctx(allow_pending=False, release=False):
    return Context(root=str(_REPO), allow_pending=allow_pending, release=release,
                   expected_engine_revision=_ENGINE if release else None,
                   expected_game_revision=_GAME if release else None,
                   artifact_root=str(_REPO) if release else None)


def _scene_set():
    return schema.load_json_file(_SCENE_FILE)


def _rows(obj):
    return obj["stations"] + obj["controls"] + obj["coverage"]


def _discovered_set():
    obj = _scene_set()
    obj["status"] = "discovered"
    accepted = {"verdict": "accepted", "note": "qualified on the native run"}
    for row in _rows(obj):
        row["status"] = "discovered"
        row["pose"] = {"x": 1, "y": 2, "z": 3, "yaw": 0, "pitch": 0}
        row["qualification"]["wanted_set_sha256"] = "a" * 64
        row["qualification"]["coverage_sha256"] = "b" * 64
        row["qualification"]["tiers"] = [{"tier": 0, "complete": True}]
        row["dispositions"] = {"quality": dict(accepted), "performance": dict(accepted)}
    return obj


def _set_problems(obj, allow_pending=True, release=False):
    return scene.check_scene_set(_SET_PATH, obj, _ctx(allow_pending=allow_pending, release=release))


def _release_root(test):
    """A temporary root holding the committed scene set and presets, with an empty receipts folder."""
    tmp = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, str(tmp), True)
    shutil.copytree(str(_REPO / "content" / "scenes"), str(tmp / "content" / "scenes"))
    shutil.copytree(str(_REPO / "content" / "presets"), str(tmp / "content" / "presets"))
    (tmp / "content" / "receipts").mkdir()
    (tmp / _SET_PATH).write_bytes((json.dumps(_discovered_set()) + "\n").encode("utf-8"))
    (tmp / "artifacts" / "sha256").mkdir(parents=True)
    (tmp / "artifacts" / "sha256" / _CAPTURE_HASH).write_bytes(_CAPTURE)
    return tmp


def _receipt_name(station, profile, display):
    return "scene-%s-%s-%s.json" % (station, profile, display)


def _write_receipt(root, name, receipt):
    """Write a receipt as UTF-8 bytes with LF newlines."""
    (root / "content" / "receipts" / name).write_bytes((json.dumps(receipt, indent=2) + "\n").encode("utf-8"))


def _qualified_receipt(station, profile, display, **changes):
    """A qualified accepted receipt that matches the discovered set built by _discovered_set."""
    receipt = copy.deepcopy(_RECEIPT_BASE)
    receipt.update(
        station=station,
        profile=profile,
        display=display,
        wanted_set_sha256="a" * 64,
        coverage_sha256="b" * 64,
        tiers=[{"tier": 0, "complete": True}],
        scene_identity="%s.%s" % (station, profile),
    )
    receipt.update(changes)
    return receipt


def _write_full_receipts(root):
    """Write one qualified receipt for every row, profile and display: 9 rows x 2 x 2 = 36."""
    for row in _rows(_scene_set()):
        for profile in scene.PROFILES:
            for display in scene.DISPLAYS:
                name = _receipt_name(row["id"], profile, display)
                _write_receipt(root, name, _qualified_receipt(row["id"], profile, display))


def _release_ctx(root):
    return Context(str(root), False, True, expected_engine_revision=_ENGINE,
                   expected_game_revision=_GAME, artifact_root=str(root / "artifacts"))


def _release_problems(obj, root):
    ctx = _release_ctx(root)
    return scene.check_scene_set(_SET_PATH, obj, ctx)


def _assert_problem(test, problems, needle):
    test.assertTrue(problems, "expected a problem containing %r" % needle)
    test.assertTrue(any(needle in line for line in problems), "%r not in %r" % (needle, problems))


class SceneSetTests(unittest.TestCase):
    def test_committed_set_validates_with_allow_pending(self):
        self.assertEqual(_set_problems(_scene_set(), allow_pending=True), [])

    def test_committed_set_fails_without_allow_pending(self):
        problems = _set_problems(_scene_set(), allow_pending=False)
        _assert_problem(self, problems, "status pending-native-discovery is not allowed in this mode")

    def test_release_refuses_pending(self):
        problems = _set_problems(_scene_set(), allow_pending=False, release=True)
        _assert_problem(self, problems, "status pending-native-discovery is not allowed in this mode")

    def test_release_accepts_complete_discovered_set_with_receipts(self):
        root = _release_root(self)
        _write_full_receipts(root)
        self.assertEqual(len(list((root / "content" / "receipts").iterdir())), 36)
        self.assertEqual(_release_problems(_discovered_set(), root), [])

    def test_release_refuses_filled_set_without_receipts(self):
        root = _release_root(self)
        problems = _release_problems(_discovered_set(), root)
        _assert_problem(
            self,
            problems,
            "release requires a scene receipt for station 'tunnel-interior' profile 'quality' display '3840x1600'",
        )

    def test_release_refuses_missing_receipt(self):
        root = _release_root(self)
        _write_full_receipts(root)
        (root / "content" / "receipts" / _receipt_name("arch-8km", "performance", "3440x1440")).unlink()
        _assert_problem(
            self,
            _release_problems(_discovered_set(), root),
            "release requires a scene receipt for station 'arch-8km' profile 'performance' display '3440x1440'",
        )

    def test_release_refuses_duplicate_receipt(self):
        root = _release_root(self)
        _write_full_receipts(root)
        _write_receipt(root, "scene-duplicate.json", _qualified_receipt("tunnel-interior", "quality", "3840x1600"))
        _assert_problem(
            self,
            _release_problems(_discovered_set(), root),
            "duplicate scene receipt for station 'tunnel-interior' profile 'quality' display '3840x1600'",
        )

    def test_release_refuses_receipt_with_mismatched_wanted_hash(self):
        root = _release_root(self)
        _write_full_receipts(root)
        name = _receipt_name("cave-mouth-2km", "quality", "3840x1600")
        _write_receipt(root, name, _qualified_receipt("cave-mouth-2km", "quality", "3840x1600", wanted_set_sha256="f" * 64))
        _assert_problem(
            self,
            _release_problems(_discovered_set(), root),
            "wanted_set_sha256 does not match the scene set row 'cave-mouth-2km'",
        )

    def test_release_refuses_receipt_with_mismatched_coverage_hash(self):
        root = _release_root(self)
        _write_full_receipts(root)
        name = _receipt_name("horizon-16km", "performance", "3440x1440")
        _write_receipt(root, name, _qualified_receipt("horizon-16km", "performance", "3440x1440", coverage_sha256="f" * 64))
        _assert_problem(
            self,
            _release_problems(_discovered_set(), root),
            "coverage_sha256 does not match the scene set row 'horizon-16km'",
        )

    def test_release_refuses_receipt_with_mismatched_tiers(self):
        root = _release_root(self)
        _write_full_receipts(root)
        tiers = [{"tier": 0, "complete": True}, {"tier": 1, "complete": True}]
        name = _receipt_name("arch-8km", "quality", "3840x1600")
        _write_receipt(root, name, _qualified_receipt("arch-8km", "quality", "3840x1600", tiers=tiers))
        _assert_problem(self, _release_problems(_discovered_set(), root), "tiers do not match the scene set row 'arch-8km'")

    def test_release_refuses_scene_identity_shared_between_profiles(self):
        root = _release_root(self)
        _write_full_receipts(root)
        for profile in scene.PROFILES:
            for display in scene.DISPLAYS:
                name = _receipt_name("empty-tile", profile, display)
                _write_receipt(root, name, _qualified_receipt("empty-tile", profile, display, scene_identity="empty-tile.same"))
        _assert_problem(
            self,
            _release_problems(_discovered_set(), root),
            "scene_identity must differ between profiles for station 'empty-tile'",
        )

    def test_release_refuses_scene_identity_that_differs_across_displays(self):
        root = _release_root(self)
        _write_full_receipts(root)
        name = _receipt_name("empty-tile", "quality", "3440x1440")
        _write_receipt(root, name, _qualified_receipt("empty-tile", "quality", "3440x1440", scene_identity="empty-tile.other"))
        _assert_problem(
            self,
            _release_problems(_discovered_set(), root),
            "release requires one scene_identity for station 'empty-tile' profile 'quality' across both displays",
        )

    def test_release_refuses_mixed_game_revision(self):
        root = _release_root(self)
        _write_full_receipts(root)
        name = _receipt_name("arch-8km", "quality", "3840x1600")
        _write_receipt(root, name, _qualified_receipt("arch-8km", "quality", "3840x1600", game_revision="3" * 40))
        _assert_problem(
            self,
            _release_problems(_discovered_set(), root),
            "game_revision does not match expected_game_revision",
        )

    def test_release_refuses_mixed_engine_revision(self):
        root = _release_root(self)
        _write_full_receipts(root)
        name = _receipt_name("horizon-16km", "performance", "3440x1440")
        _write_receipt(root, name, _qualified_receipt("horizon-16km", "performance", "3440x1440", engine_revision="4" * 40))
        _assert_problem(
            self,
            _release_problems(_discovered_set(), root),
            "engine_revision does not match expected_engine_revision",
        )

    def test_release_refuses_mixed_preset_identity_within_station(self):
        root = _release_root(self)
        _write_full_receipts(root)
        name = _receipt_name("arch-8km", "performance", "3440x1440")
        _write_receipt(root, name, _qualified_receipt("arch-8km", "performance", "3440x1440", preset_identity="0" * 16))
        _assert_problem(
            self,
            _release_problems(_discovered_set(), root),
            "release requires one preset_identity for station 'arch-8km' across its receipts",
        )

    def test_release_refuses_mixed_content_identity_within_station(self):
        root = _release_root(self)
        _write_full_receipts(root)
        name = _receipt_name("horizon-16km", "quality", "3840x1600")
        _write_receipt(root, name, _qualified_receipt("horizon-16km", "quality", "3840x1600", content_identity="1"))
        _assert_problem(
            self,
            _release_problems(_discovered_set(), root),
            "release requires one content_identity for station 'horizon-16km' across its receipts",
        )

    def test_release_receipts_are_not_required_in_pending_mode(self):
        root = _release_root(self)
        self.assertEqual(scene.check_scene_set(_SET_PATH, _scene_set(), Context(root=str(root), allow_pending=True, release=False)), [])

    def test_release_refuses_defect_open_disposition(self):
        obj = _discovered_set()
        obj["stations"][0]["dispositions"]["quality"]["verdict"] = "defect-open"
        problems = _set_problems(obj, allow_pending=False, release=True)
        _assert_problem(self, problems, "release refuses verdict 'defect-open' for quality")

    def test_release_refuses_missing_disposition(self):
        obj = _discovered_set()
        obj["coverage"][1]["dispositions"]["performance"] = None
        problems = _set_problems(obj, allow_pending=False, release=True)
        _assert_problem(self, problems, "release requires a disposition for performance")

    def test_release_refuses_empty_tiers(self):
        obj = _discovered_set()
        obj["controls"][0]["qualification"]["tiers"] = []
        problems = _set_problems(obj, allow_pending=False, release=True)
        _assert_problem(self, problems, "release requires at least one tier")

    def test_unknown_top_level_key_refused(self):
        obj = _scene_set()
        obj["extra"] = 1
        _assert_problem(self, _set_problems(obj), "unknown key 'extra'")

    def test_unknown_station_key_refused(self):
        obj = _scene_set()
        obj["stations"][0]["extra"] = 1
        _assert_problem(self, _set_problems(obj), "unknown key 'extra'")

    def test_unknown_qualification_key_refused(self):
        obj = _scene_set()
        obj["controls"][0]["qualification"]["extra"] = 1
        _assert_problem(self, _set_problems(obj), "unknown key 'extra'")

    def test_unknown_requirement_key_refused(self):
        obj = _scene_set()
        obj["coverage"][0]["qualification"]["requirements"]["extra"] = 1
        _assert_problem(self, _set_problems(obj), "unknown key 'extra'")

    def test_future_schema_refused(self):
        obj = _scene_set()
        obj["schema"] = "luminumbra.game.scene-set.v2"
        _assert_problem(self, _set_problems(obj), "future schema version")

    def test_station_order_refused(self):
        obj = _scene_set()
        obj["stations"][0], obj["stations"][1] = obj["stations"][1], obj["stations"][0]
        _assert_problem(self, _set_problems(obj), "in that order")

    def test_station_count_refused(self):
        obj = _scene_set()
        obj["stations"].pop()
        _assert_problem(self, _set_problems(obj), "exactly 4 entries")

    def test_duplicate_station_id_refused(self):
        obj = _scene_set()
        obj["stations"][1]["id"] = "tunnel-interior"
        _assert_problem(self, _set_problems(obj), "duplicate id")

    def test_bad_settle_limit_refused(self):
        obj = _scene_set()
        obj["settle_limit_seconds"] = 60
        _assert_problem(self, _set_problems(obj), "settle_limit_seconds must be 90")

    def test_bad_profile_list_refused(self):
        obj = _scene_set()
        obj["profiles"] = ["quality"]
        _assert_problem(self, _set_problems(obj), "profiles must be exactly")

    def test_bad_display_list_refused(self):
        obj = _scene_set()
        obj["displays"] = ["3840x1600"]
        _assert_problem(self, _set_problems(obj), "displays must be exactly")

    def test_discovered_station_without_pose_refused(self):
        obj = _scene_set()
        obj["stations"][2]["status"] = "discovered"
        _assert_problem(self, _set_problems(obj), "status discovered requires a non-null pose")

    def test_pending_station_with_pose_refused(self):
        obj = _scene_set()
        obj["stations"][0]["pose"] = {"x": 1, "y": 2, "z": 3, "yaw": 0, "pitch": 0}
        _assert_problem(self, _set_problems(obj), "pose must be null while status is pending")

    def test_pending_station_with_wanted_hash_refused(self):
        obj = _scene_set()
        obj["stations"][0]["qualification"]["wanted_set_sha256"] = "a" * 64
        _assert_problem(
            self, _set_problems(obj), "qualification.wanted_set_sha256 must be null while status is pending"
        )

    def test_pending_control_with_coverage_hash_refused(self):
        obj = _scene_set()
        obj["controls"][1]["qualification"]["coverage_sha256"] = "b" * 64
        _assert_problem(
            self, _set_problems(obj), "qualification.coverage_sha256 must be null while status is pending"
        )

    def test_pending_coverage_row_with_tiers_refused(self):
        obj = _scene_set()
        obj["coverage"][0]["qualification"]["tiers"] = [{"tier": 0, "complete": True}]
        _assert_problem(self, _set_problems(obj), "qualification.tiers must be empty while status is pending")

    def test_pending_row_with_disposition_refused(self):
        obj = _scene_set()
        obj["controls"][0]["dispositions"]["quality"] = {"verdict": "accepted", "note": "premature"}
        _assert_problem(self, _set_problems(obj), "dispositions.quality must be null while status is pending")

    def test_discovered_top_level_with_pending_row_refused(self):
        obj = _scene_set()
        obj["status"] = "discovered"
        _assert_problem(self, _set_problems(obj), "every station, control and coverage row")

    def test_bad_hash_refused(self):
        obj = _scene_set()
        obj["stations"][0]["qualification"]["wanted_set_sha256"] = "XYZ"
        _assert_problem(self, _set_problems(obj), "wanted_set_sha256 must be null or 64 lowercase hex digits")

    def test_bad_coverage_hash_refused(self):
        obj = _scene_set()
        obj["controls"][1]["qualification"]["coverage_sha256"] = "A" * 64
        _assert_problem(self, _set_problems(obj), "coverage_sha256 must be null or 64 lowercase hex digits")

    def test_bad_below_horizon_requirement_refused(self):
        obj = _scene_set()
        obj["stations"][3]["qualification"]["requirements"]["below_horizon_sky_percent_max"] = 3
        _assert_problem(self, _set_problems(obj), "below_horizon_sky_percent_max must be 2")

    def test_bad_seam_requirement_refused(self):
        obj = _scene_set()
        obj["stations"][0]["qualification"]["requirements"]["seam_bands"] = 1
        _assert_problem(self, _set_problems(obj), "seam_bands must be 0")

    def test_bad_outer_edge_requirement_refused(self):
        obj = _scene_set()
        obj["stations"][0]["qualification"]["requirements"]["outer_edge"] = True
        _assert_problem(self, _set_problems(obj), "outer_edge must be false")

    def test_bad_tiers_complete_requirement_refused(self):
        obj = _scene_set()
        obj["stations"][0]["qualification"]["requirements"]["tiers_complete"] = False
        _assert_problem(self, _set_problems(obj), "tiers_complete must be true")

    def test_tiers_must_be_ascending(self):
        obj = _discovered_set()
        obj["stations"][0]["qualification"]["tiers"] = [
            {"tier": 1, "complete": True},
            {"tier": 0, "complete": True},
        ]
        _assert_problem(self, _set_problems(obj, allow_pending=False), "unique and ascending")

    def test_missing_discovery_notes_refused(self):
        obj = _scene_set()
        del obj["discovery_notes"]
        _assert_problem(self, _set_problems(obj), "missing key 'discovery_notes'")

    def test_empty_discovery_notes_refused(self):
        obj = _scene_set()
        obj["discovery_notes"] = []
        _assert_problem(self, _set_problems(obj), "discovery_notes must be a non-empty array")

    def test_first_note_must_name_beyond_4km_cave_opening(self):
        obj = _scene_set()
        obj["discovery_notes"][0] = "Discovery records the stations and poses only."
        _assert_problem(self, _set_problems(obj), "beyond the 4 km noise-cave cutoff")

    def test_bad_disposition_verdict_refused(self):
        obj = _scene_set()
        obj["stations"][0]["dispositions"]["quality"] = {"verdict": "maybe", "note": "unclear"}
        _assert_problem(self, _set_problems(obj), "verdict must be one of")

    def test_empty_disposition_note_refused(self):
        obj = _scene_set()
        obj["stations"][0]["dispositions"]["quality"] = {"verdict": "accepted", "note": " "}
        _assert_problem(self, _set_problems(obj), "note must be a non-empty string")

    def test_wrong_station_distance_refused(self):
        obj = _scene_set()
        obj["stations"][1]["distance_m"] = 1000
        _assert_problem(self, _set_problems(obj), "distance_m must be 2000")

    def test_wrong_station_preset_refused(self):
        obj = _scene_set()
        obj["stations"][2]["preset"] = "default"
        _assert_problem(self, _set_problems(obj), "preset must be 'caverns'")

    def test_bool_is_not_a_number_for_distance(self):
        obj = _scene_set()
        obj["stations"][0]["distance_m"] = False
        _assert_problem(self, _set_problems(obj), "distance_m must be 0")

    def test_coverage_id_must_match_preset(self):
        obj = _scene_set()
        obj["coverage"][0]["preset"] = "mountains"
        _assert_problem(self, _set_problems(obj), "preset must be 'default'")

    def test_native_commands_must_be_exact(self):
        obj = _scene_set()
        obj["native"]["commands"] = "docs/other.md"
        _assert_problem(self, _set_problems(obj), "native.commands and native.discovery_probe")

    def test_file_must_live_in_scene_dir(self):
        problems = scene.check_scene_set("content/other/distant-world.json", _scene_set(), _ctx(True))
        _assert_problem(self, problems, "scene sets must live in content/scenes/<id>.json")

    def test_unknown_pose_key_refused(self):
        obj = _discovered_set()
        obj["stations"][0]["pose"]["extra"] = 1
        _assert_problem(self, _set_problems(obj), "pose: unknown key 'extra'")

    def test_unknown_native_key_refused(self):
        obj = _scene_set()
        obj["native"]["extra"] = 1
        _assert_problem(self, _set_problems(obj), "native: unknown key 'extra'")

    def test_unknown_tier_key_refused(self):
        obj = _scene_set()
        obj["stations"][0]["qualification"]["tiers"] = [{"tier": 0, "complete": True, "extra": 1}]
        _assert_problem(self, _set_problems(obj), "unknown key 'extra'")

    def test_unknown_disposition_key_refused(self):
        obj = _scene_set()
        obj["stations"][0]["dispositions"]["quality"] = {"verdict": "accepted", "note": "ok", "extra": 1}
        _assert_problem(self, _set_problems(obj), "unknown key 'extra'")


class PresetTests(unittest.TestCase):
    def setUp(self):
        self.preset_text = _PRESET_FILE.read_text(encoding="utf-8")
        self.sidecar_text = _SIDECAR_FILE.read_text(encoding="utf-8")

    def _check(self, text, path=_PRESET_PATH):
        return scene.check_preset_file(path, text, _ctx())

    def test_committed_preset_and_sidecar_validate(self):
        self.assertEqual(self._check(self.preset_text), [])
        self.assertEqual(self._check(self.sidecar_text, _SIDECAR_PATH), [])

    def test_cave_dense_differs_from_caverns_only_in_whitelist(self):
        caverns = identity.loads_strict(_CAVERNS_FIXTURE.read_text(encoding="utf-8"))
        cave_dense = identity.loads_strict(self.preset_text)
        left = _leaves(caverns)
        right = _leaves(cave_dense)
        self.assertEqual(sorted(left), sorted(right))
        differing = sorted(key for key in left if left[key] != right[key])
        self.assertEqual(
            differing,
            [
                "description",
                "generation_params.features.cave_threshold",
                "generation_params.features.max_feature_radius",
                "generation_params.features.surface_break_density",
                "name",
            ],
        )
        self.assertEqual(right["generation_params.features.cave_threshold"], 0.54)
        self.assertEqual(right["generation_params.features.surface_break_density"], 0.55)
        self.assertEqual(right["generation_params.features.max_feature_radius"], 52)

    def test_identity_recomputes_to_sidecar(self):
        sidecar = json.loads(self.sidecar_text)
        raw = _PRESET_FILE.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), sidecar["file_sha256"])
        recomputed = identity.preset_identity(identity.loads_strict(self.preset_text))
        self.assertEqual(recomputed, sidecar["preset_identity"])
        self.assertEqual(sidecar["preset_identity"], "5d081f382b2d5d0d")

    def test_exponent_token_refused(self):
        text = self.preset_text.replace("0.54", "5.4e-1", 1)
        problems = self._check(text)
        _assert_problem(self, problems, "exponent")

    def test_control_character_refused(self):
        text = self.preset_text.replace('"name": "Cave Dense"', '"name": "Cave\\u0001Dense"', 1)
        _assert_problem(self, self._check(text), "control or surrogate")

    def test_loader_clamp_refused_for_max_feature_radius(self):
        text = self.preset_text.replace('"max_feature_radius": 52.0', '"max_feature_radius": 110.0', 1)
        _assert_problem(self, self._check(text), "max_feature_radius must be less than feature_cell_size")

    def test_surface_break_density_out_of_range_refused(self):
        text = self.preset_text.replace('"surface_break_density": 0.55', '"surface_break_density": 1.5', 1)
        _assert_problem(self, self._check(text), "surface_break_density must be in [0, 1]")

    def test_cave_threshold_out_of_range_refused(self):
        text = self.preset_text.replace('"cave_threshold": 0.54', '"cave_threshold": 1.0', 1)
        _assert_problem(self, self._check(text), "cave_threshold must be in (0, 1)")

    def test_cave_dense_values_are_exact(self):
        text = self.preset_text.replace('"cave_threshold": 0.54', '"cave_threshold": 0.55', 1)
        _assert_problem(self, self._check(text), "cave_threshold must be 0.54 for cave_dense")

    def test_preset_without_sidecar_refused(self):
        problems = scene.check_preset_file("content/presets/ghost.json", self.preset_text, _ctx())
        _assert_problem(self, problems, "missing identity sidecar content/presets/ghost.identity.json")

    def test_reserved_windows_device_preset_name_refused(self):
        for name in ("con", "com1"):
            problems = scene.check_preset_file("content/presets/%s.json" % name, self.preset_text, _ctx())
            _assert_problem(self, problems, "file name must not be a reserved Windows device name")

    def test_reserved_windows_device_sidecar_name_refused(self):
        problems = scene.check_preset_file("content/presets/con.identity.json", self.sidecar_text, _ctx())
        _assert_problem(self, problems, "file name must not be a reserved Windows device name")

    def test_reserved_stem_helper_is_case_insensitive_and_exact(self):
        for stem in ("con", "NUL", "Com9", "lpt1", "lpt9"):
            self.assertTrue(scene.is_reserved_stem(stem), stem)
        for stem in ("com0", "lpt10", "console", "cave_dense", "nul-x"):
            self.assertFalse(scene.is_reserved_stem(stem), stem)

    def test_duplicate_key_refused(self):
        text = self.preset_text.replace('"schema_rev": 7', '"schema_rev": 7, "schema_rev": 7', 1)
        _assert_problem(self, self._check(text), "duplicate key")

    def test_wrong_schema_rev_refused(self):
        for revision in ("5", "6", "8", "7.0", "true"):
            with self.subTest(revision=revision):
                text = self.preset_text.replace('"schema_rev": 7', '"schema_rev": ' + revision, 1)
                _assert_problem(self, self._check(text), "schema_rev must be 7")

    def test_sidecar_file_sha256_mismatch_refused(self):
        sidecar = json.loads(self.sidecar_text)
        sidecar["file_sha256"] = "0" * 64
        text = json.dumps(sidecar, indent=2) + "\n"
        _assert_problem(self, self._check(text, _SIDECAR_PATH), "file_sha256 does not match")

    def test_sidecar_preset_identity_mismatch_refused(self):
        sidecar = json.loads(self.sidecar_text)
        sidecar["preset_identity"] = "0000000000000000"
        text = json.dumps(sidecar, indent=2) + "\n"
        _assert_problem(self, self._check(text, _SIDECAR_PATH), "preset_identity does not match")

    def test_sidecar_missing_sibling_refused(self):
        sidecar = {
            "schema": "luminumbra.game.preset-identity.v1",
            "preset": "ghost",
            "file_sha256": "0" * 64,
            "preset_identity": "0" * 16,
        }
        text = json.dumps(sidecar, indent=2) + "\n"
        _assert_problem(self, self._check(text, "content/presets/ghost.identity.json"), "missing sibling preset content/presets/ghost.json")

    def test_sidecar_preset_must_equal_stem(self):
        sidecar = json.loads(self.sidecar_text)
        sidecar["preset"] = "caverns"
        text = json.dumps(sidecar, indent=2) + "\n"
        _assert_problem(self, self._check(text, _SIDECAR_PATH), "preset must equal the file stem 'cave_dense'")

    def test_sidecar_extra_key_refused(self):
        sidecar = json.loads(self.sidecar_text)
        sidecar["extra"] = "x"
        text = json.dumps(sidecar, indent=2) + "\n"
        _assert_problem(self, self._check(text, _SIDECAR_PATH), "unknown key 'extra'")

    def _edited(self, edit):
        """Return the committed cave_dense preset, re-serialised after EDIT changes its object."""
        obj = json.loads(self.preset_text)
        edit(obj)
        return json.dumps(obj, indent=2) + "\n"

    def test_empty_generation_params_refused_for_cave_dense(self):
        text = self._edited(lambda obj: obj.update(generation_params={}))
        _assert_problem(self, self._check(text), "generation_params must be a non-empty object")

    def test_empty_generation_params_refused_for_any_preset(self):
        text = self._edited(lambda obj: obj.update(generation_params={}))
        problems = scene.check_preset_file("content/presets/ghost.json", text, _ctx())
        _assert_problem(self, problems, "generation_params must be a non-empty object")

    def test_missing_features_refused_for_cave_dense(self):
        text = self._edited(lambda obj: obj["generation_params"].pop("features"))
        _assert_problem(self, self._check(text), "generation_params.features is required")

    def test_missing_cave_dense_feature_refused(self):
        text = self._edited(lambda obj: obj["generation_params"]["features"].pop("cave_threshold"))
        _assert_problem(self, self._check(text), "cave_threshold is missing for cave_dense")

    def test_unknown_top_level_key_refused_for_any_preset(self):
        text = self._edited(lambda obj: obj.update(extra=1))
        problems = scene.check_preset_file("content/presets/ghost.json", text, _ctx())
        _assert_problem(self, problems, "unknown key 'extra'")

    def test_unknown_nested_key_refused_for_cave_dense(self):
        text = self._edited(lambda obj: obj["generation_params"]["features"].update(extra_knob=1))
        _assert_problem(self, self._check(text), "generation_params.features has unknown key 'extra_knob'")

    def test_missing_nested_key_refused_for_cave_dense(self):
        text = self._edited(lambda obj: obj["generation_params"]["terrain"]["hydro"].pop("solubility"))
        _assert_problem(self, self._check(text), "generation_params.terrain.hydro is missing key 'solubility'")

    def test_malformed_spline_pair_refused_for_cave_dense(self):
        text = self._edited(lambda obj: obj["generation_params"]["terrain"]["shaping"]["erosion_spline"].append([1.0]))
        _assert_problem(self, self._check(text), "erosion_spline[6] must be a pair of two numbers")

    def test_nested_object_where_a_number_is_expected_refused(self):
        text = self._edited(lambda obj: obj["generation_params"]["features"].update(cave_frequency={"extra": 1}))
        _assert_problem(self, self._check(text), "generation_params.features.cave_frequency must be a number")

    def test_string_where_a_number_is_expected_refused(self):
        text = self._edited(lambda obj: obj["generation_params"]["terrain"].update(base_frequency="0.009"))
        _assert_problem(self, self._check(text), "generation_params.terrain.base_frequency must be a number")

    def test_bool_where_a_number_is_expected_refused(self):
        text = self._edited(lambda obj: obj["generation_params"]["features"].update(cave_frequency=True))
        _assert_problem(self, self._check(text), "generation_params.features.cave_frequency must be a number")

    def test_float_where_an_integer_is_expected_refused(self):
        text = self._edited(lambda obj: obj["generation_params"]["terrain"].update(octaves=6.0))
        _assert_problem(self, self._check(text), "generation_params.terrain.octaves must be an integer")

    def test_number_where_a_bool_is_expected_refused(self):
        text = self._edited(lambda obj: obj["generation_params"]["features"].update(caves_enabled=1))
        _assert_problem(self, self._check(text), "generation_params.features.caves_enabled must be true or false")

    def test_default_only_key_refused_for_cave_dense(self):
        text = self._edited(lambda obj: obj["generation_params"]["features"].update(lake_frequency=0.1))
        _assert_problem(self, self._check(text), "generation_params.features has unknown key 'lake_frequency'")

    def test_unknown_nested_key_refused_for_any_preset(self):
        text = self._ghost_text({"terrain": {"extra": 1}})
        _assert_problem(self, self._ghost_problems(text), "generation_params.terrain has unknown key 'extra'")

    def test_unknown_generation_params_key_refused_for_any_preset(self):
        text = self._ghost_text({"extra": 1})
        _assert_problem(self, self._ghost_problems(text), "generation_params has unknown key 'extra'")

    def test_wrong_leaf_type_refused_for_any_preset(self):
        text = self._ghost_text({"features": {"cave_frequency": "0.02"}})
        _assert_problem(self, self._ghost_problems(text), "generation_params.features.cave_frequency must be a number")

    def test_empty_terrain_object_refused_for_any_preset(self):
        text = self._raw_ghost_text({"terrain": {}})
        _assert_problem(self, self._ghost_problems(text), "generation_params.terrain.base_frequency is required")

    def test_each_mandatory_terrain_key_missing_refused_for_any_preset(self):
        for key in scene.MANDATORY_TERRAIN_KEYS:
            with self.subTest(key=key):
                params = _minimal_params()
                del params["terrain"][key]
                text = self._raw_ghost_text(params)
                _assert_problem(
                    self, self._ghost_problems(text), "generation_params.terrain.%s is required" % key
                )

    def test_each_mandatory_feature_key_missing_refused_for_any_preset(self):
        for key in scene.MANDATORY_FEATURE_KEYS:
            with self.subTest(key=key):
                params = _minimal_params()
                del params["features"][key]
                text = self._raw_ghost_text(params)
                _assert_problem(
                    self, self._ghost_problems(text), "generation_params.features.%s is required" % key
                )

    def test_missing_terrain_object_refused_for_any_preset(self):
        params = _minimal_params()
        del params["terrain"]
        _assert_problem(
            self, self._ghost_problems(self._raw_ghost_text(params)), "generation_params.terrain is required"
        )

    def test_missing_features_object_refused_for_any_preset(self):
        params = _minimal_params()
        del params["features"]
        _assert_problem(
            self, self._ghost_problems(self._raw_ghost_text(params)), "generation_params.features is required"
        )

    def test_mandatory_keys_present_passes_structure_for_any_preset(self):
        problems = self._ghost_problems(self._raw_ghost_text(_minimal_params()))
        self.assertFalse([p for p in problems if "is required" in p])

    def test_radius_clamp_refused_when_cell_size_omitted_for_any_preset(self):
        text = self._ghost_text({"features": {"max_feature_radius": 128.0}})
        _assert_problem(
            self, self._ghost_problems(text), "max_feature_radius must be less than feature_cell_size"
        )

    def test_radius_clamp_refused_when_radius_omitted_for_any_preset(self):
        text = self._ghost_text({"features": {"feature_cell_size": 50.0}})
        _assert_problem(
            self, self._ghost_problems(text), "max_feature_radius must be less than feature_cell_size"
        )

    def test_radius_clamp_refused_after_float32_rounding(self):
        text = self._ghost_text({"features": {"feature_cell_size": 110.0, "max_feature_radius": 110.0000001}})
        _assert_problem(
            self, self._ghost_problems(text), "max_feature_radius must be less than feature_cell_size"
        )

    def test_radius_clamp_passes_when_effective_values_fit(self):
        text = self._ghost_text({"features": {"feature_cell_size": 128.0}})
        problems = self._ghost_problems(text)
        self.assertFalse([p for p in problems if "less than feature_cell_size" in p])

    def test_engine_fixtures_validate_as_presets(self):
        for name, fixture in (("caverns", _CAVERNS_FIXTURE), ("default", _DEFAULT_FIXTURE)):
            with self.subTest(preset=name):
                root = self._fixture_root(name, fixture)
                ctx = Context(root=str(root), allow_pending=False, release=False)
                text = fixture.read_bytes().decode("utf-8")
                self.assertEqual(scene.check_preset_file("content/presets/%s.json" % name, text, ctx), [])
                sidecar = (root / "content" / "presets" / (name + ".identity.json")).read_bytes().decode("utf-8")
                self.assertEqual(scene.check_preset_file("content/presets/%s.identity.json" % name, sidecar, ctx), [])

    def test_deep_nesting_in_preset_is_one_line_problem(self):
        text = "[" * 200000 + "]" * 200000
        self.assertEqual(self._check(text), ["content/presets/cave_dense.json: json nesting is too deep"])

    def test_deep_nesting_in_sidecar_is_one_line_problem(self):
        text = "[" * 200000 + "]" * 200000
        self.assertEqual(self._check(text, _SIDECAR_PATH), ["content/presets/cave_dense.identity.json: json nesting is too deep"])

    def _raw_ghost_text(self, generation_params):
        obj = {"name": "Ghost", "description": "A test preset", "schema_rev": 7, "generation_params": generation_params}
        return json.dumps(obj, indent=2) + "\n"

    def _ghost_text(self, overrides):
        """A non-cave_dense preset that has every mandatory key, with OVERRIDES merged over it."""
        params = _minimal_params()
        for key, value in overrides.items():
            if isinstance(value, dict) and isinstance(params.get(key), dict):
                params[key].update(value)
            else:
                params[key] = value
        return self._raw_ghost_text(params)

    def _ghost_problems(self, text):
        return scene.check_preset_file("content/presets/ghost.json", text, _ctx())

    def _fixture_root(self, name, fixture):
        """A temporary root holding FIXTURE as content/presets/NAME.json with a matching sidecar."""
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(root), True)
        presets = root / "content" / "presets"
        presets.mkdir(parents=True)
        raw = fixture.read_bytes()
        (presets / (name + ".json")).write_bytes(raw)
        sidecar = {
            "schema": "luminumbra.game.preset-identity.v1",
            "preset": name,
            "file_sha256": hashlib.sha256(raw).hexdigest(),
            "preset_identity": identity.preset_identity(identity.loads_strict(raw.decode("utf-8"))),
        }
        (presets / (name + ".identity.json")).write_bytes((json.dumps(sidecar, indent=2) + "\n").encode("utf-8"))
        return root


def _minimal_params():
    """generation_params with every key the engine loader requires and nothing else."""
    return {
        "terrain": {
            "base_frequency": 0.01,
            "base_amplitude": 34.0,
            "octaves": 6,
            "persistence": 0.5,
            "lacunarity": 2.0,
            "height_offset": 5.0,
        },
        "features": {"caves_enabled": True, "cave_frequency": 0.02},
    }


def _leaves(obj, prefix=""):
    found = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            found.update(_leaves(value, key if not prefix else prefix + "." + key))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            found.update(_leaves(value, "%s[%d]" % (prefix, index)))
    else:
        found[prefix] = obj
    return found


_RECEIPT_BASE = {
    "schema": "luminumbra.game.scene-receipt.v1",
    "scene_set": "distant-world",
    "station": "cave-mouth-2km",
    "profile": "quality",
    "display": "3840x1600",
    "settled": True,
    "settle_seconds": 42.5,
    "wanted_set_sha256": "c" * 64,
    "coverage_sha256": "d" * 64,
    "tiers": [{"tier": 0, "complete": True}, {"tier": 1, "complete": True}],
    "below_horizon_sky_percent": 1.5,
    "seam_bands": 0,
    "outer_edge": False,
    "capture_sha256": _CAPTURE_HASH,
    "scene_identity": "cave-mouth-2km.quality",
    "preset_identity": "5d081f382b2d5d0d",
    "content_identity": "16636010052247870746",
    "adapter": "NVIDIA GeForce RTX 5070 Ti",
    "engine_revision": "1" * 40,
    "game_revision": "2" * 40,
    "disposition": {"verdict": "accepted", "note": "qualified on the native run"},
}


def _receipt(**changes):
    """Build a receipt with Decimal floats, as schema.load_json_file would return them."""
    base = copy.deepcopy(_RECEIPT_BASE)
    base.update(changes)
    return schema.loads_document(json.dumps(base))


def _receipt_problems(obj, release=False, path=_RECEIPT_PATH):
    if not release:
        return scene.check_scene_receipt(path, obj, _ctx(allow_pending=True))
    # Direct release calls have a complete, consistent discovered row context and capture.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        shutil.copytree(_REPO / "content" / "presets", root / "content" / "presets")
        (root / "content" / "scenes").mkdir()
        obj_set = _discovered_set()
        for row in _rows(obj_set):
            if row["id"] == obj["station"]:
                for field in ("wanted_set_sha256", "coverage_sha256", "tiers"):
                    row["qualification"][field] = copy.deepcopy(obj[field])
        (root / _SET_PATH).write_bytes((json.dumps(obj_set) + "\n").encode("utf-8"))
        (root / "artifacts" / "sha256").mkdir(parents=True)
        (root / "artifacts" / "sha256" / _CAPTURE_HASH).write_bytes(_CAPTURE)
        return scene.check_scene_receipt(path, obj, _release_ctx(root))


class SceneReceiptTests(unittest.TestCase):
    def test_qualified_accepted_receipt_passes(self):
        self.assertEqual(_receipt_problems(_receipt()), [])

    def test_settled_false_refused_when_accepted(self):
        _assert_problem(self, _receipt_problems(_receipt(settled=False)), "settled is false")

    def test_incomplete_tier_refused_when_accepted(self):
        tiers = [{"tier": 0, "complete": True}, {"tier": 1, "complete": False}]
        _assert_problem(self, _receipt_problems(_receipt(tiers=tiers)), "tier 1 is incomplete")

    def test_sky_over_two_percent_refused_when_accepted(self):
        problems = _receipt_problems(_receipt(below_horizon_sky_percent=2.5))
        _assert_problem(self, problems, "below_horizon_sky_percent 2.5 exceeds 2")

    def test_seam_band_refused_when_accepted(self):
        _assert_problem(self, _receipt_problems(_receipt(seam_bands=1)), "seam_bands 1 is not 0")

    def test_outer_edge_refused_when_accepted(self):
        _assert_problem(self, _receipt_problems(_receipt(outer_edge=True)), "outer_edge is true")

    def test_unqualified_defect_open_allowed(self):
        disposition = {"verdict": "defect-open", "note": "seam band at the 4 km tier"}
        self.assertEqual(_receipt_problems(_receipt(settled=False, seam_bands=1, disposition=disposition)), [])

    def test_unqualified_waived_allowed(self):
        disposition = {"verdict": "waived-with-reason", "note": "sky measured on an ultrawide display"}
        self.assertEqual(_receipt_problems(_receipt(below_horizon_sky_percent=2.5, disposition=disposition)), [])

    def test_unqualified_defect_fixed_refused(self):
        disposition = {"verdict": "defect-fixed", "note": "fixed in the engine"}
        problems = _receipt_problems(_receipt(outer_edge=True, disposition=disposition))
        _assert_problem(self, problems, "must have disposition defect-open or waived-with-reason")

    def test_release_requires_qualified(self):
        disposition = {"verdict": "waived-with-reason", "note": "waived"}
        problems = _receipt_problems(_receipt(seam_bands=1, disposition=disposition), release=True)
        _assert_problem(self, problems, "release requires a qualified receipt; failing: seam_bands 1")

    def test_release_refuses_defect_open_even_when_qualified(self):
        disposition = {"verdict": "defect-open", "note": "open"}
        problems = _receipt_problems(_receipt(disposition=disposition), release=True)
        _assert_problem(self, problems, "release requires disposition accepted or waived-with-reason")

    def test_release_accepts_qualified_accepted_receipt(self):
        self.assertEqual(_receipt_problems(_receipt(), release=True), [])

    def test_unknown_station_refused(self):
        _assert_problem(self, _receipt_problems(_receipt(station="nowhere")), "unknown station 'nowhere'")

    def test_preset_identity_mismatch_refused(self):
        _assert_problem(
            self,
            _receipt_problems(_receipt(preset_identity="0" * 16)),
            "preset_identity does not match the identity sidecar of preset 'cave_dense'",
        )

    def test_engine_preset_skips_identity_check(self):
        self.assertEqual(_receipt_problems(_receipt(station="horizon-16km", preset_identity="0" * 16)), [])

    def test_control_station_is_accepted_as_row(self):
        self.assertEqual(_receipt_problems(_receipt(station="cave-opening")), [])

    def test_bool_in_number_field_refused(self):
        _assert_problem(self, _receipt_problems(_receipt(settle_seconds=True)), "settle_seconds must be a number")

    def test_bool_in_sky_field_refused(self):
        _assert_problem(self, _receipt_problems(_receipt(below_horizon_sky_percent=False)), "below_horizon_sky_percent must be a number")

    def test_bool_in_seam_field_refused(self):
        _assert_problem(self, _receipt_problems(_receipt(seam_bands=False)), "seam_bands must be an integer")

    def test_settle_over_limit_refused_when_settled(self):
        _assert_problem(self, _receipt_problems(_receipt(settle_seconds=91)), "settle_seconds must be at most 90")

    def test_wrong_file_name_refused(self):
        problems = _receipt_problems(_receipt(), path="content/receipts/receipt-01.json")
        _assert_problem(self, problems, "scene receipts must be content/receipts/scene-*.json")

    def test_adapter_must_name_qualified_renderer(self):
        _assert_problem(self, _receipt_problems(_receipt(adapter="Other GPU")), "adapter must name the qualified renderer")

    def test_scene_identity_pattern_refused(self):
        _assert_problem(self, _receipt_problems(_receipt(scene_identity="bad id")), "scene_identity must be")

    def test_unknown_receipt_key_refused(self):
        _assert_problem(self, _receipt_problems(_receipt(extra=1)), "unknown key 'extra'")

    def test_future_receipt_schema_refused(self):
        problems = _receipt_problems(_receipt(schema="luminumbra.game.scene-receipt.v2"))
        _assert_problem(self, problems, "future schema version")

    def test_empty_tiers_refused(self):
        _assert_problem(self, _receipt_problems(_receipt(tiers=[])), "tiers must be a non-empty array")

    def test_duplicate_tier_numbers_refused(self):
        tiers = [{"tier": 0, "complete": True}, {"tier": 0, "complete": True}]
        _assert_problem(self, _receipt_problems(_receipt(tiers=tiers)), "tiers must be unique and ascending")

    def test_non_ascending_tiers_refused(self):
        tiers = [{"tier": 1, "complete": True}, {"tier": 0, "complete": True}]
        _assert_problem(self, _receipt_problems(_receipt(tiers=tiers)), "tiers must be unique and ascending")

    def test_each_failed_quantity_defect_open_allowed_and_accepted_refused(self):
        cases = [
            ("settled false", {"settled": False}, "settled is false"),
            (
                "incomplete tier",
                {"tiers": [{"tier": 0, "complete": True}, {"tier": 1, "complete": False}]},
                "tier 1 is incomplete",
            ),
            ("sky 2.5", {"below_horizon_sky_percent": 2.5}, "below_horizon_sky_percent 2.5 exceeds 2"),
            ("seam_bands 1", {"seam_bands": 1}, "seam_bands 1 is not 0"),
            ("outer_edge true", {"outer_edge": True}, "outer_edge is true"),
        ]
        open_disposition = {"verdict": "defect-open", "note": "open on the native run"}
        accepted = {"verdict": "accepted", "note": "qualified on the native run"}
        for label, changes, needle in cases:
            with self.subTest(quantity=label):
                self.assertEqual(_receipt_problems(_receipt(disposition=open_disposition, **changes)), [])
                _assert_problem(self, _receipt_problems(_receipt(disposition=accepted, **changes)), needle)

    def test_unknown_receipt_disposition_key_refused(self):
        disposition = {"verdict": "accepted", "note": "ok", "extra": 1}
        _assert_problem(self, _receipt_problems(_receipt(disposition=disposition)), "unknown key 'extra'")


class SceneReleaseRepairTests(unittest.TestCase):
    """Synthetic byte/format checks only; these fixtures never qualify a native run."""

    def setUp(self):
        self.root = _release_root(self)
        _write_full_receipts(self.root)
        self.obj = _discovered_set()
        self.ctx = _release_ctx(self.root)
        self.receipt = _qualified_receipt("cave-mouth-2km", "quality", "3840x1600")
        self.assertEqual(scene.check_scene_set(_SET_PATH, self.obj, self.ctx), [])
        self.assertEqual(scene.check_scene_receipt(_RECEIPT_PATH, self.receipt, self.ctx), [])

    def test_missing_context_refuses_both_direct_validators_individually(self):
        for field in ("expected_engine_revision", "expected_game_revision", "artifact_root"):
            with self.subTest(field=field):
                ctx = replace(self.ctx, **{field: None})
                for fn, path, obj in ((scene.check_scene_set, _SET_PATH, self.obj),
                                      (scene.check_scene_receipt, _RECEIPT_PATH, self.receipt)):
                    self.assertEqual(fn(path, obj, ctx), [path + ": scene release requires " + field])

    def test_uniformly_stale_engine_and_game_refuse(self):
        for field in ("engine_revision", "game_revision"):
            with self.subTest(field=field):
                for row in _rows(self.obj):
                    for profile in scene.PROFILES:
                        for display in scene.DISPLAYS:
                            _write_receipt(self.root, _receipt_name(row["id"], profile, display),
                                           _qualified_receipt(row["id"], profile, display, **{field: "0" * 40}))
                _assert_problem(self, scene.check_scene_set(_SET_PATH, self.obj, self.ctx),
                                field + " does not match expected_" + field)
                stale = dict(self.receipt, **{field: "0" * 40})
                _assert_problem(self, scene.check_scene_receipt(_RECEIPT_PATH, stale, self.ctx),
                                field + " does not match expected_" + field)
                _write_full_receipts(self.root)

    def test_malformed_programmatic_context_is_a_problem(self):
        for field, value, reason in (
                ("expected_engine_revision", "A" * 40, "must be 40 lowercase hex digits"),
                ("expected_game_revision", 7, "must be 40 lowercase hex digits"),
                ("artifact_root", "", "must be a nonempty existing directory"),
                ("artifact_root", str(self.root / "missing"), "must be a nonempty existing safe directory")):
            with self.subTest(field=field, value=value):
                ctx = replace(self.ctx, **{field: value})
                for release in (True, False):
                    _assert_problem(self, scene.check_scene_receipt(
                        _RECEIPT_PATH, self.receipt, replace(ctx, release=release)), reason)

    def test_exact_canonical_store_ignores_aliases_but_never_uses_them(self):
        store = self.root / "artifacts"
        leaf = store / "sha256" / _CAPTURE_HASH
        (store / _CAPTURE_HASH).write_bytes(b"unrelated bad alias")
        (store / "sha256" / (_CAPTURE_HASH + ".json")).write_bytes(b"unrelated")
        self.assertEqual(scene.check_scene_receipt(_RECEIPT_PATH, self.receipt, self.ctx), [])
        leaf.unlink()
        (store / _CAPTURE_HASH).write_bytes(_CAPTURE)
        (store / "sha256" / (_CAPTURE_HASH + ".json")).write_bytes(_CAPTURE)
        _assert_problem(self, scene.check_scene_receipt(_RECEIPT_PATH, self.receipt, self.ctx),
                        "capture artifact: cannot read file")

    def test_capture_mismatch_nonregular_and_unreadable_refuse(self):
        leaf = self.root / "artifacts" / "sha256" / _CAPTURE_HASH
        leaf.write_bytes(b"wrong bytes")
        _assert_problem(self, scene.check_scene_receipt(_RECEIPT_PATH, self.receipt, self.ctx),
                        "capture_sha256 does not match captured artifact bytes")
        leaf.unlink()
        leaf.mkdir()
        _assert_problem(self, scene.check_scene_receipt(_RECEIPT_PATH, self.receipt, self.ctx),
                        "capture artifact: nonregular file refused")
        leaf.rmdir()
        leaf.write_bytes(_CAPTURE)
        original_open = scene.os.open

        def unreadable(path, flags):
            if Path(path) == leaf:
                raise PermissionError("injected unreadable capture")
            return original_open(path, flags)

        with mock.patch.object(scene.os, "open", side_effect=unreadable):
            _assert_problem(self, scene.check_scene_receipt(_RECEIPT_PATH, self.receipt, self.ctx),
                            "injected unreadable capture")

    def test_capture_store_non_directory_and_observable_reparse_refuse(self):
        store = self.root / "artifacts" / "sha256"
        (store / _CAPTURE_HASH).unlink()
        store.rmdir()
        store.write_bytes(b"not a directory")
        _assert_problem(self, scene.check_scene_receipt(_RECEIPT_PATH, self.receipt, self.ctx),
                        "capture artifact: non-directory path refused")
        store.unlink()
        store.mkdir()
        (store / _CAPTURE_HASH).write_bytes(_CAPTURE)
        original = scene.os.lstat

        def reparse(path):
            info = original(path)
            if Path(path) == store:
                return type("ReparseInfo", (), {"st_mode": info.st_mode,
                                                "st_file_attributes": 0x400})()
            return info

        with mock.patch.object(scene.os, "lstat", side_effect=reparse):
            _assert_problem(self, scene.check_scene_receipt(_RECEIPT_PATH, self.receipt, self.ctx),
                            "symlink or reparse point refused")

    def test_symlink_leaf_store_root_and_ancestor_refuse(self):
        # This test alone may skip; ordinary failures/races do not require symlinks.
        target = self.root / "safe-target"
        target.mkdir()
        probe = self.root / "probe-link"
        try:
            probe.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        probe.unlink()
        store = self.root / "artifacts" / "sha256"
        leaf = store / _CAPTURE_HASH
        leaf.rename(target / _CAPTURE_HASH)
        leaf.symlink_to(target / _CAPTURE_HASH)
        _assert_problem(self, scene.check_scene_receipt(_RECEIPT_PATH, self.receipt, self.ctx),
                        "symlink or reparse point refused")
        leaf.unlink()
        store.rmdir()
        store.symlink_to(target, target_is_directory=True)
        _assert_problem(self, scene.check_scene_receipt(_RECEIPT_PATH, self.receipt, self.ctx),
                        "symlink or reparse point refused")
        store.unlink()
        alias = self.root / "artifact-alias"
        alias.symlink_to(target, target_is_directory=True)
        for root in (alias, alias / "child"):
            (target / "child").mkdir(exist_ok=True)
            _assert_problem(self, scene.check_scene_receipt(
                _RECEIPT_PATH, self.receipt, replace(self.ctx, artifact_root=str(root))),
                "symlink or reparse point refused")

    def test_streaming_detects_change_replacement_and_truncation(self):
        leaf = self.root / "artifacts" / "sha256" / _CAPTURE_HASH
        for kind in ("truncate", "modify"):
            with self.subTest(kind=kind):
                leaf.write_bytes(_CAPTURE)
                before = leaf.stat()
                digest = hashlib.sha256()

                def consume(chunk):
                    digest.update(chunk)
                    if kind == "truncate":
                        leaf.write_bytes(b"")
                    else:
                        leaf.write_bytes(b"x" * len(_CAPTURE))
                        # Make the metadata mutation observable even when the
                        # filesystem gives consecutive writes the same timestamp.
                        os.utime(leaf, ns=(before.st_atime_ns, before.st_mtime_ns + 1000000000))

                with self.assertRaisesRegex(scene.SceneError, "changed during reading"):
                    scene.stream_safe_file(str(leaf), "capture", consume)

    def test_windows_creation_and_descriptor_change_times_preserve_race_checks(self):
        leaf = self.root / "artifacts" / "sha256" / _CAPTURE_HASH
        real_lstat = os.lstat
        real_fstat = os.fstat
        for change in (False, True):
            with self.subTest(change=change):
                leaf.write_bytes(_CAPTURE)
                before = leaf.stat()
                mutated = []
                chunks = []

                def metadata(info, descriptor=False):
                    attrs = {name: getattr(info, name) for name in
                             ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns")}
                    attrs.update(st_birthtime_ns=before.st_ctime_ns,
                                 st_ctime_ns=before.st_ctime_ns +
                                 (100 + len(mutated) if descriptor else 0),
                                 st_file_attributes=0, st_reparse_tag=0)
                    return SimpleNamespace(**attrs)

                def path_stat(target, *args, **kwargs):
                    info = real_lstat(target, *args, **kwargs)
                    return metadata(info) if Path(target) == leaf else info

                def descriptor_stat(fd):
                    return metadata(real_fstat(fd), descriptor=True)

                def consume(chunk):
                    chunks.append(chunk)
                    if change:
                        leaf.write_bytes(b"x" * len(_CAPTURE))
                        os.utime(leaf, ns=(before.st_atime_ns, before.st_mtime_ns))
                        mutated.append(True)

                with mock.patch.object(scene, "_WINDOWS_METADATA", True), \
                        mock.patch.object(scene.os, "lstat", side_effect=path_stat), \
                        mock.patch.object(scene.os, "fstat", side_effect=descriptor_stat):
                    if change:
                        with self.assertRaisesRegex(scene.SceneError, "changed during reading"):
                            scene.stream_safe_file(str(leaf), "capture", consume)
                    else:
                        scene.stream_safe_file(str(leaf), "capture", consume)
                self.assertEqual(b"".join(chunks), _CAPTURE)
                self.assertEqual(leaf.read_bytes(), b"x" * len(_CAPTURE) if change else _CAPTURE)

    def test_post_read_replacement_is_refused_on_all_platforms(self):
        leaf = self.root / "artifacts" / "sha256" / _CAPTURE_HASH
        original = scene.safe_path_chain
        calls = []

        def replace_before_postcheck(full, where, *, directory=False):
            if Path(full) == leaf:
                calls.append(1)
                if len(calls) == 2:
                    # The read descriptor is closed before this boundary, including Windows.
                    other = leaf.with_name("post-read-replacement")
                    other.write_bytes(_CAPTURE)
                    os.replace(other, leaf)
            return original(full, where, directory=directory)

        with mock.patch.object(scene, "safe_path_chain", side_effect=replace_before_postcheck):
            _assert_problem(self, scene.check_scene_receipt(_RECEIPT_PATH, self.receipt, self.ctx),
                            "file or ancestor changed during reading")
        self.assertEqual(len(calls), 2)

    def test_pre_open_replacement_is_refused(self):
        leaf = self.root / "artifacts" / "sha256" / _CAPTURE_HASH
        original = scene.os.open

        def changed(path, flags):
            if Path(path) == leaf:
                other = leaf.with_name("replacement")
                other.write_bytes(_CAPTURE)
                os.replace(other, leaf)
            return original(path, flags)

        with mock.patch.object(scene.os, "open", side_effect=changed):
            _assert_problem(self, scene.check_scene_receipt(_RECEIPT_PATH, self.receipt, self.ctx),
                            "file changed before reading")

    def test_row_disposition_verdict_and_note_match_each_profile_and_display(self):
        for row in _rows(self.obj):
            for profile in scene.PROFILES:
                for display in scene.DISPLAYS:
                    for change in ({"verdict": "waived-with-reason"}, {"note": "different note"},
                                   {"note": "qualified on the native run "}):
                        with self.subTest(row=row["id"], profile=profile, display=display, change=change):
                            receipt = _qualified_receipt(row["id"], profile, display)
                            receipt["disposition"].update(change)
                            name = _receipt_name(row["id"], profile, display)
                            _write_receipt(self.root, name, receipt)
                            reason = "disposition does not match the scene set row '%s' profile '%s'" % (row["id"], profile)
                            _assert_problem(self, scene.check_scene_receipt(_receipt_path(name), receipt, self.ctx), reason)
                            _assert_problem(self, scene.check_scene_set(_SET_PATH, self.obj, self.ctx), reason)
                            _write_receipt(self.root, name, _qualified_receipt(row["id"], profile, display))

    def test_nested_receipts_use_validated_snapshot_without_reloading_scene_set(self):
        changed = copy.deepcopy(self.obj)
        changed["stations"][0]["dispositions"]["quality"]["note"] = "changed on disk"
        (self.root / _SET_PATH).write_bytes((json.dumps(changed) + "\n").encode("utf-8"))
        self.assertEqual(scene.check_scene_set(_SET_PATH, self.obj, self.ctx), [])
        receipt = _qualified_receipt("tunnel-interior", "quality", "3840x1600")
        _assert_problem(self, scene.check_scene_receipt(_RECEIPT_PATH, receipt, self.ctx),
                        "disposition does not match the scene set row 'tunnel-interior'")

    def test_direct_receipt_validates_required_row_without_releasing_other_rows(self):
        obj = _scene_set()
        obj["stations"][1] = copy.deepcopy(self.obj["stations"][1])
        (self.root / _SET_PATH).write_bytes((json.dumps(obj) + "\n").encode("utf-8"))
        self.assertEqual(scene.check_scene_receipt(_RECEIPT_PATH, self.receipt, self.ctx), [])
        _assert_problem(self, scene.check_scene_set(_SET_PATH, obj, self.ctx),
                        "status pending-native-discovery is not allowed in this mode")

    def test_matching_waiver_never_bypasses_any_numeric_gate(self):
        waiver = {"verdict": "waived-with-reason", "note": "matching reason"}
        self.obj["stations"][1]["dispositions"]["quality"] = waiver
        (self.root / _SET_PATH).write_bytes((json.dumps(self.obj) + "\n").encode("utf-8"))
        for changes, reason in (({"settled": False}, "settled is false"),
                                ({"tiers": [{"tier": 0, "complete": False}]}, "tier 0 is incomplete"),
                                ({"below_horizon_sky_percent": 2.5}, "exceeds 2"),
                                ({"seam_bands": 1}, "seam_bands 1 is not 0"),
                                ({"outer_edge": True}, "outer_edge is true")):
            receipt = dict(self.receipt, disposition=waiver, **changes)
            _assert_problem(self, scene.check_scene_receipt(_RECEIPT_PATH, receipt, self.ctx),
                            "release requires a qualified receipt; failing:")
            _assert_problem(self, scene.check_scene_receipt(_RECEIPT_PATH, receipt, self.ctx), reason)


    def test_matching_waiver_cannot_bypass_settle_time_limit(self):
        waiver = {"verdict": "waived-with-reason", "note": "matching reason"}
        self.obj["stations"][1]["dispositions"]["quality"] = waiver
        (self.root / _SET_PATH).write_bytes((json.dumps(self.obj) + "\n").encode("utf-8"))
        receipt = dict(self.receipt, disposition=waiver, settle_seconds=91)
        _assert_problem(self, scene.check_scene_receipt(_RECEIPT_PATH, receipt, self.ctx),
                        "settle_seconds must be at most 90 when settled")

    def test_stream_reads_bounded_chunks_without_limiting_total_size(self):
        capture = self.root / "large-capture"
        raw = (b"\x00\xffbinary capture\n" * 150000) + b"tail"
        capture.write_bytes(raw)
        actual = hashlib.sha256()
        sizes = []

        def consume(chunk):
            sizes.append(len(chunk))
            actual.update(chunk)

        scene.stream_safe_file(str(capture), "large capture", consume)
        self.assertGreater(len(sizes), 1)
        self.assertLessEqual(max(sizes), 1024 * 1024)
        self.assertEqual(sum(sizes), len(raw))
        self.assertEqual(actual.hexdigest(), hashlib.sha256(raw).hexdigest())

    def test_opened_file_type_is_checked_independently_of_path_check(self):
        leaf = self.root / "artifacts" / "sha256" / _CAPTURE_HASH
        original_open = scene.os.open
        original_fstat = scene.os.fstat
        capture_fds = []

        def track_open(path, flags):
            fd = original_open(path, flags)
            if Path(path) == leaf:
                capture_fds.append(fd)
            return fd

        def directory_fstat(fd):
            if fd in capture_fds:
                return (self.root / "artifacts").stat()
            return original_fstat(fd)

        with mock.patch.object(scene.os, "open", side_effect=track_open), \
                mock.patch.object(scene.os, "fstat", side_effect=directory_fstat):
            _assert_problem(self, scene.check_scene_receipt(_RECEIPT_PATH, self.receipt, self.ctx),
                            "capture artifact: opened file is nonregular or a reparse point")


def _receipt_path(name):
    return "content/receipts/" + name


if __name__ == "__main__":
    unittest.main()
