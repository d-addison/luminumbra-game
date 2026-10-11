import copy
import hashlib
import json
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
    return Context(root=str(_REPO), allow_pending=allow_pending, release=release)


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


def _release_problems(obj, root):
    ctx = Context(root=str(root), allow_pending=False, release=True)
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
        self.assertEqual(sidecar["preset_identity"], "e70158a4777ee36b")

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

    def test_duplicate_key_refused(self):
        text = self.preset_text.replace('"schema_rev": 6', '"schema_rev": 6, "schema_rev": 6', 1)
        _assert_problem(self, self._check(text), "duplicate key")

    def test_wrong_schema_rev_refused(self):
        text = self.preset_text.replace('"schema_rev": 6', '"schema_rev": 5', 1)
        _assert_problem(self, self._check(text), "schema_rev must be 6")

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
        _assert_problem(self, self._check(text), "generation_params is missing key 'features'")

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
        problems = scene.check_preset_file("content/presets/ghost.json", text, _ctx())
        _assert_problem(self, problems, "generation_params.terrain has unknown key 'extra'")

    def test_unknown_generation_params_key_refused_for_any_preset(self):
        text = self._ghost_text({"extra": 1})
        problems = scene.check_preset_file("content/presets/ghost.json", text, _ctx())
        _assert_problem(self, problems, "generation_params has unknown key 'extra'")

    def test_wrong_leaf_type_refused_for_any_preset(self):
        text = self._ghost_text({"features": {"cave_frequency": "0.02"}})
        problems = scene.check_preset_file("content/presets/ghost.json", text, _ctx())
        _assert_problem(self, problems, "generation_params.features.cave_frequency must be a number")

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

    def _ghost_text(self, generation_params):
        obj = {"name": "Ghost", "description": "A test preset", "schema_rev": 6, "generation_params": generation_params}
        return json.dumps(obj, indent=2) + "\n"

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
    "capture_sha256": "e" * 64,
    "scene_identity": "cave-mouth-2km.quality",
    "preset_identity": "e70158a4777ee36b",
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
    return scene.check_scene_receipt(path, obj, _ctx(allow_pending=True, release=release))


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


if __name__ == "__main__":
    unittest.main()
