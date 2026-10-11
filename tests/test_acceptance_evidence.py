"""Tests for tools/validators/acceptance.py and tools/validate_acceptance_evidence.py."""

import contextlib
import copy
import hashlib
import io
import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import validate_acceptance_evidence  # noqa: E402
import validate_content  # noqa: E402
from lumlib.schema import load_json_file  # noqa: E402
from validators import discover  # noqa: E402
from validators.acceptance import (  # noqa: E402
    SCHEMA_ID,
    artifact_count,
    artifact_hashes,
    validate_bundle,
    verify_artifacts,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "acceptance"
MARKER = "LUM-AUDIO-OFF-0x1"
OFF_JOURNALS = frozenset(["journal-preview-launch", "journal-restart-no-audio"])
SESSION_IDS = (
    "create-world", "edit-world", "save-world", "restart-world", "load-world",
    "switch-world-a", "switch-world-b", "refusal-bad-save", "refusal-bad-switch",
    "preview-launch", "restart-no-audio",
)
SCENE_IDS = ("forest-edge", "cave-mouth", "ridge-camp", "river-ford", "cliff-overlook", "dusk-meadow")
GIT_SHA = "3f9d2c1a8b7e6d5c4b3a2f1e0d9c8b7a6f5e4d3c"
GAME_REV = "9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2f1e0d"
ENGINE_REV = "b56cdba12e425ed2786778d5b02c98ba61466584"
HANG_UNSIGNED = 3489660927
HANG_SIGNED = -805306369

# Session indexes in make_bundle(): 0 create-world, 7 refusal-bad-save,
# 8 refusal-bad-switch, 9 preview-launch, 10 restart-no-audio.
REFUSAL_SAVE = 7
REFUSAL_SWITCH = 8
PREVIEW = 9
NO_AUDIO_RESTART = 10


def _blob(label):
    """Return the bytes stored under the content address of ``label``."""
    text = "artifact %s\n" % label
    if label in OFF_JOURNALS:
        text += MARKER + "\n"
    return text.encode("utf-8")


def _h(label):
    return hashlib.sha256(_blob(label)).hexdigest()


def _labels():
    labels = [
        "archive", "pack-base", "manifest-start", "manifest-edited", "settings-kept",
        "forest-submission", "forest-report", "launcher-identity", "disabled-backend-proof",
    ]
    for sid in SESSION_IDS:
        labels.append("command-" + sid)
        labels.append("journal-" + sid)
    for scene in SCENE_IDS:
        labels.append("capture-" + scene)
    return labels


def _session(sid, kind, audio_mode, no_audio_flag, exit_code=0, **extra):
    session = {
        "id": sid,
        "kind": kind,
        "command_sha256": _h("command-" + sid),
        "journal_sha256": _h("journal-" + sid),
        "exit_code": exit_code,
        "audio_mode": audio_mode,
        "no_audio_flag": no_audio_flag,
        "saved_master": 75,
    }
    session.update(extra)
    return session


def _scene(sid, defects=()):
    return {
        "id": sid,
        "capture_sha256": _h("capture-" + sid),
        "settled": True,
        "defects": list(defects),
    }


def make_bundle():
    """Return a fresh valid acceptance evidence bundle (the v0.3 shape)."""
    return {
        "schema": SCHEMA_ID,
        "package": {"git_sha": GIT_SHA, "archive_sha256": _h("archive")},
        "engine": {"rev": ENGINE_REV},
        "game": {"rev": GAME_REV},
        "content": {"packs": [{"id": "base-content", "sha256": _h("pack-base")}]},
        "policy": {"audio_off_marker": MARKER, "refusal_exit_codes": [2, 3]},
        "sessions": [
            _session("create-world", "create", "null", False),
            _session("edit-world", "edit", "null", False),
            _session("save-world", "save", "null", False),
            _session("restart-world", "restart", "null", False),
            _session("load-world", "load", "null", False),
            _session("switch-world-a", "switch", "null", False),
            _session("switch-world-b", "switch", "null", False),
            _session("refusal-bad-save", "refusal", "null", False, 2,
                     refusal_code="save-corrupt", saves_unchanged=True),
            _session("refusal-bad-switch", "refusal", "null", False, 3,
                     refusal_code="switch-target-missing", saves_unchanged=True),
            _session("preview-launch", "preview", "off", True),
            _session("restart-no-audio", "restart", "off", True),
        ],
        "saves": [
            {
                "name": "edit-save",
                "files": [
                    {"path": "world/manifest.txt",
                     "sha256_before": _h("manifest-start"),
                     "sha256_after": _h("manifest-edited")},
                    {"path": "world/settings.txt",
                     "sha256_before": _h("settings-kept"),
                     "sha256_after": _h("settings-kept")},
                ],
            },
            {
                "name": "save-refusal",
                "files": [
                    {"path": "world/manifest.txt",
                     "sha256_before": _h("manifest-edited"),
                     "sha256_after": _h("manifest-edited")},
                ],
            },
            {
                "name": "switch-refusal",
                "files": [
                    {"path": "world/manifest.txt",
                     "sha256_before": _h("manifest-edited"),
                     "sha256_after": _h("manifest-edited")},
                ],
            },
        ],
        "scenes": [
            _scene("forest-edge", [{"id": "shadow-seam", "disposition": "fixed",
                                    "note": "tree-line shadow seam removed"}]),
            _scene("cave-mouth", [{"id": "lod-pop", "disposition": "accepted",
                                   "note": "distant pop accepted at this range"}]),
            _scene("ridge-camp"),
            _scene("river-ford"),
            _scene("cliff-overlook"),
            _scene("dusk-meadow"),
        ],
        "forest": {
            "agree": True,
            "report_sha256": _h("forest-report"),
            "submission_sha256": _h("forest-submission"),
        },
        "launcher": {"identity_sha256": _h("launcher-identity"), "preview_audio_off": True},
        "disabled_backend": {"proof_sha256": _h("disabled-backend-proof"), "settings_preserved": True},
        # The valid release bundle has no open limitation: both gaps are closed here,
        # which models a run after the final v0.3 requirement is met. While open they
        # are blocking and release mode refuses them (see the limitation tests).
        "limitations": [
            {"blocks_release": True, "id": "finite-residency", "status": "closed"},
            {"blocks_release": True, "id": "distant-cave-edit-omitted", "status": "closed"},
        ],
        "historical": [
            {
                "disposition": "kept as a historical record; never counted as a session exit",
                "id": "application-hang-66604",
                "kind": "application-hang",
            }
        ],
        "unresolved_diagnostics": [],
    }


def _store(root, skip=frozenset()):
    """Write every blob into ROOT/sha256/<hex>, except digests listed in skip."""
    store = Path(root) / "sha256"
    store.mkdir(parents=True, exist_ok=True)
    for label in _labels():
        data = _blob(label)
        digest = hashlib.sha256(data).hexdigest()
        if digest not in skip:
            (store / digest).write_bytes(data)


def _write_bundle(path, doc):
    path.write_bytes((json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _run_cli(argv):
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = validate_acceptance_evidence.main(argv)
    return code, out.getvalue(), err.getvalue()


class _BundleTest(unittest.TestCase):
    def bundle(self):
        return copy.deepcopy(make_bundle())

    def assertProblem(self, doc, text, release=False):
        problems = validate_bundle(doc, release=release)
        self.assertTrue(any(text in problem for problem in problems), problems)

    def assertNoProblem(self, doc, text, release=False):
        problems = validate_bundle(doc, release=release)
        self.assertFalse(any(text in problem for problem in problems), problems)

    def assertClean(self, doc, release=False):
        self.assertEqual(validate_bundle(doc, release=release), [])


class ValidBundleTest(_BundleTest):
    def test_helper_bundle_is_valid_in_both_modes(self):
        self.assertClean(make_bundle())
        self.assertClean(make_bundle(), release=True)

    def test_fixture_parses_and_validates(self):
        doc = load_json_file(FIXTURES / "valid.json")
        self.assertClean(doc)
        self.assertClean(doc, release=True)

    def test_fixture_is_byte_equal_to_helper_output(self):
        data = (FIXTURES / "valid.json").read_bytes()
        expected = (json.dumps(make_bundle(), indent=2, sort_keys=True) + "\n").encode("utf-8")
        self.assertEqual(data, expected)
        self.assertNotIn(b"\r", data)

    def test_limitations_and_historical_records_are_present(self):
        doc = make_bundle()
        self.assertEqual(len(doc["historical"]), 1)
        self.assertEqual(
            {entry["id"] for entry in doc["limitations"]},
            {"finite-residency", "distant-cave-edit-omitted"},
        )


class SchemaRuleTest(_BundleTest):
    def test_unknown_root_key_refused(self):
        doc = self.bundle()
        doc["extra"] = 1
        self.assertProblem(doc, "bundle: unknown key 'extra'")

    def test_unknown_nested_key_refused(self):
        doc = self.bundle()
        doc["package"]["note"] = "x"
        self.assertProblem(doc, "package: unknown key 'note'")

    def test_unknown_session_key_refused(self):
        doc = self.bundle()
        doc["sessions"][0]["note"] = "x"
        self.assertProblem(doc, "sessions[0]: unknown key 'note'")

    def test_future_schema_refused(self):
        doc = self.bundle()
        doc["schema"] = "luminumbra.game.acceptance-evidence.v2"
        self.assertProblem(doc, "future schema version")

    def test_unknown_schema_refused(self):
        doc = self.bundle()
        doc["schema"] = "luminumbra.game.other.v1"
        self.assertProblem(doc, "unknown schema")

    def test_missing_root_key_refused(self):
        doc = self.bundle()
        del doc["limitations"]
        self.assertProblem(doc, "missing key 'limitations'")

    def test_missing_session_key_refused(self):
        doc = self.bundle()
        del doc["sessions"][0]["saved_master"]
        self.assertProblem(doc, "sessions[0]: missing key 'saved_master'")

    def test_uppercase_hash_refused(self):
        doc = self.bundle()
        doc["package"]["archive_sha256"] = doc["package"]["archive_sha256"].upper()
        self.assertProblem(doc, "package.archive_sha256: must be 64 lowercase hex characters")

    def test_short_hash_refused(self):
        doc = self.bundle()
        doc["forest"]["report_sha256"] = "abc"
        self.assertProblem(doc, "forest.report_sha256: must be 64 lowercase hex characters")

    def test_short_git_sha_refused(self):
        doc = self.bundle()
        doc["package"]["git_sha"] = "3f9d2c1a"
        self.assertProblem(doc, "package.git_sha: must be 40 lowercase hex characters")

    def test_engine_rev_must_be_forty_hex(self):
        doc = self.bundle()
        doc["engine"]["rev"] = "b56c"
        self.assertProblem(doc, "engine.rev: must be 40 lowercase hex characters")

    def test_pack_id_must_be_kebab(self):
        doc = self.bundle()
        doc["content"]["packs"][0]["id"] = "Base_Content"
        self.assertProblem(doc, "content.packs[0].id: must be lowercase kebab-case")

    def test_policy_exit_codes_must_be_in_range_and_unique(self):
        doc = self.bundle()
        doc["policy"]["refusal_exit_codes"] = [0, 2]
        self.assertProblem(doc, "policy.refusal_exit_codes[0]: must be an integer from 1 to 125")
        doc = self.bundle()
        doc["policy"]["refusal_exit_codes"] = [2, 2]
        self.assertProblem(doc, "policy.refusal_exit_codes[1]: duplicate exit code 2")

    def test_audio_marker_must_not_contain_control_characters(self):
        doc = self.bundle()
        doc["policy"]["audio_off_marker"] = "LUM\nOFF"
        self.assertProblem(doc, "policy.audio_off_marker: must not contain control characters")

    def test_duplicate_session_id_refused(self):
        doc = self.bundle()
        doc["sessions"][1]["id"] = "create-world"
        self.assertProblem(doc, "sessions[1].id: duplicate id 'create-world'")

    def test_session_kind_must_be_known(self):
        doc = self.bundle()
        doc["sessions"][0]["kind"] = "bogus"
        self.assertProblem(doc, "sessions[0].kind: must be one of")

    def test_negative_saved_master_refused(self):
        doc = self.bundle()
        doc["sessions"][0]["saved_master"] = -1
        self.assertProblem(doc, "sessions[0].saved_master: must be a finite non-negative number")

    def test_decimal_saved_master_accepted(self):
        doc = self.bundle()
        doc["sessions"][0]["saved_master"] = Decimal("0.5")
        self.assertNoProblem(doc, "saved_master")

    def test_saved_master_accepts_finite_int_float_and_decimal(self):
        for value in (0, 75, 0.5, Decimal("0.5"), Decimal("75")):
            with self.subTest(value=value):
                doc = self.bundle()
                doc["sessions"][0]["saved_master"] = value
                self.assertNoProblem(doc, "saved_master")

    def test_saved_master_refuses_nan_and_infinity(self):
        for value in (float("nan"), float("inf"), float("-inf"),
                      Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("-Infinity")):
            with self.subTest(value=value):
                doc = self.bundle()
                doc["sessions"][0]["saved_master"] = value
                self.assertProblem(doc, "sessions[0].saved_master: must be a finite non-negative number")

    def test_saved_master_refuses_bool(self):
        doc = self.bundle()
        doc["sessions"][0]["saved_master"] = True
        self.assertProblem(doc, "sessions[0].saved_master: must be a finite non-negative number")

    def test_refusal_keys_refused_on_non_refusal_session(self):
        doc = self.bundle()
        doc["sessions"][0]["refusal_code"] = "x"
        self.assertProblem(doc, "sessions[0]: unknown key 'refusal_code'")

    def test_refusal_session_needs_refusal_code(self):
        doc = self.bundle()
        del doc["sessions"][REFUSAL_SAVE]["refusal_code"]
        self.assertProblem(doc, "sessions[7]: missing key 'refusal_code'")


class ExitCodeRuleTest(_BundleTest):
    def test_non_zero_exit_refused_for_non_refusal_session(self):
        doc = self.bundle()
        doc["sessions"][0]["exit_code"] = 1
        self.assertProblem(doc, "sessions[0].exit_code: normalised exit code must be 0")

    def test_exit_code_must_be_an_integer(self):
        doc = self.bundle()
        doc["sessions"][0]["exit_code"] = "0"
        self.assertProblem(doc, "sessions[0].exit_code: must be an integer")

    def test_refusal_code_outside_policy_refused(self):
        doc = self.bundle()
        doc["sessions"][REFUSAL_SAVE]["exit_code"] = 9
        self.assertProblem(doc, "sessions[7].exit_code: refusal exit 9 is not in policy.refusal_exit_codes")

    def test_refusal_code_inside_policy_accepted(self):
        doc = self.bundle()
        doc["sessions"][REFUSAL_SAVE]["exit_code"] = 3
        self.assertNoProblem(doc, "sessions[7].exit_code")

    def test_hang_signature_unsigned_refused(self):
        doc = self.bundle()
        doc["sessions"][0]["exit_code"] = HANG_UNSIGNED
        self.assertProblem(doc, "sessions[0].exit_code: 0xCFFFFFFF is the application hang signature")

    def test_hang_signature_signed_refused(self):
        doc = self.bundle()
        doc["sessions"][0]["exit_code"] = HANG_SIGNED
        self.assertProblem(doc, "sessions[0].exit_code: 0xCFFFFFFF is the application hang signature")

    def test_hang_signature_refused_in_refusal_session_too(self):
        doc = self.bundle()
        doc["sessions"][REFUSAL_SAVE]["exit_code"] = HANG_SIGNED
        self.assertProblem(doc, "sessions[7].exit_code: 0xCFFFFFFF is the application hang signature")
        self.assertNoProblem(doc, "not in policy.refusal_exit_codes")


class AudioRuleTest(_BundleTest):
    def test_audio_off_without_flag_refused(self):
        doc = self.bundle()
        doc["sessions"][NO_AUDIO_RESTART]["no_audio_flag"] = False
        self.assertProblem(doc, "sessions[10]: audio_mode off requires no_audio_flag true")

    def test_audio_null_with_flag_is_allowed(self):
        doc = self.bundle()
        doc["sessions"][0]["no_audio_flag"] = True
        self.assertNoProblem(doc, "sessions[0]: audio_mode")

    def test_preview_with_null_audio_refused(self):
        doc = self.bundle()
        doc["sessions"][PREVIEW]["audio_mode"] = "null"
        self.assertProblem(doc, "sessions[9]: preview requires audio_mode off and no_audio_flag true")

    def test_preview_without_flag_refused(self):
        doc = self.bundle()
        doc["sessions"][PREVIEW]["no_audio_flag"] = False
        self.assertProblem(doc, "sessions[9]: preview requires audio_mode off and no_audio_flag true")

    def test_audio_mode_must_be_null_or_off(self):
        doc = self.bundle()
        doc["sessions"][0]["audio_mode"] = "on"
        self.assertProblem(doc, "sessions[0].audio_mode: must be null or off")


class SessionCoverageTest(_BundleTest):
    def test_missing_session_kind_refused(self):
        doc = self.bundle()
        doc["sessions"] = [s for s in doc["sessions"] if s["kind"] != "switch"]
        self.assertProblem(doc, "sessions: missing session kind 'switch'")

    def test_each_kind_is_required(self):
        for kind in ("create", "edit", "save", "restart", "load", "refusal", "preview"):
            doc = self.bundle()
            doc["sessions"] = [s for s in doc["sessions"] if s["kind"] != kind]
            self.assertProblem(doc, "sessions: missing session kind '%s'" % kind)

    def test_refusal_with_saves_changed_refused(self):
        doc = self.bundle()
        doc["sessions"][REFUSAL_SAVE]["saves_unchanged"] = False
        self.assertProblem(doc, "sessions[7].saves_unchanged: must be true")

    def test_refusal_code_must_be_non_empty(self):
        doc = self.bundle()
        doc["sessions"][REFUSAL_SWITCH]["refusal_code"] = ""
        self.assertProblem(doc, "sessions[8].refusal_code: must be a non-empty string")


class SaveRuleTest(_BundleTest):
    def test_no_edited_save_refused(self):
        doc = self.bundle()
        for save in doc["saves"]:
            for entry in save["files"]:
                entry["sha256_after"] = entry["sha256_before"]
        self.assertProblem(doc, "saves: no save has an edited file")

    def test_refusal_save_must_leave_files_unchanged(self):
        doc = self.bundle()
        doc["saves"][1]["files"][0]["sha256_after"] = _h("manifest-start")
        self.assertProblem(doc, "saves[1].files[0]: a refusal save must leave every file unchanged")

    def test_portable_relative_paths_only(self):
        for bad in ("/abs/manifest.txt", "world\\manifest.txt", "../manifest.txt",
                    "C:manifest.txt", "world//manifest.txt"):
            doc = self.bundle()
            doc["saves"][0]["files"][0]["path"] = bad
            self.assertProblem(doc, "saves[0].files[0].path: must be a portable relative path")

    def test_empty_save_files_refused(self):
        doc = self.bundle()
        doc["saves"][0]["files"] = []
        self.assertProblem(doc, "saves[0].files: needs at least 1 item(s)")

    def test_duplicate_save_name_refused(self):
        doc = self.bundle()
        doc["saves"][1]["name"] = "edit-save"
        self.assertProblem(doc, "saves[1].name: duplicate save name 'edit-save'")


class SceneRuleTest(_BundleTest):
    def test_scene_not_settled_refused(self):
        doc = self.bundle()
        doc["scenes"][0]["settled"] = False
        self.assertProblem(doc, "scenes[0].settled: must be true")

    def test_defect_without_disposition_refused(self):
        doc = self.bundle()
        del doc["scenes"][0]["defects"][0]["disposition"]
        self.assertProblem(doc, "scenes[0].defects[0]: missing key 'disposition'")

    def test_defect_disposition_must_be_known(self):
        doc = self.bundle()
        doc["scenes"][0]["defects"][0]["disposition"] = "maybe"
        self.assertProblem(doc, "scenes[0].defects[0].disposition: must be one of")

    def test_open_defect_accepted_outside_release(self):
        doc = self.bundle()
        doc["scenes"][2]["defects"].append({"id": "lod-pop", "disposition": "open", "note": ""})
        self.assertNoProblem(doc, "open defect", release=False)

    def test_open_defect_refused_in_release(self):
        doc = self.bundle()
        doc["scenes"][2]["defects"].append({"id": "lod-pop", "disposition": "open", "note": ""})
        self.assertProblem(doc, "scenes[2].defects[0].disposition: open defect is refused in release mode",
                           release=True)

    def test_note_longer_than_200_refused(self):
        doc = self.bundle()
        doc["scenes"][0]["defects"][0]["note"] = "x" * 201
        self.assertProblem(doc, "scenes[0].defects[0].note: must be a string of at most 200 characters")

    def test_note_of_200_accepted(self):
        doc = self.bundle()
        doc["scenes"][0]["defects"][0]["note"] = "x" * 200
        self.assertNoProblem(doc, "scenes[0].defects[0].note")

    def test_fewer_than_six_scenes_refused(self):
        doc = self.bundle()
        doc["scenes"] = doc["scenes"][:5]
        self.assertProblem(doc, "scenes: at least 6 scenes are required, found 5")


class ForestAndLimitationTest(_BundleTest):
    def test_forest_agree_false_refused(self):
        doc = self.bundle()
        doc["forest"]["agree"] = False
        self.assertProblem(doc, "forest.agree: must be true")

    def test_forest_hashes_may_differ(self):
        doc = self.bundle()
        self.assertNotEqual(doc["forest"]["submission_sha256"], doc["forest"]["report_sha256"])
        self.assertClean(doc)

    def test_open_blocking_limitation_refused_in_release(self):
        doc = self.bundle()
        doc["limitations"].append({"blocks_release": True, "id": "residency-cap", "status": "open"})
        self.assertProblem(doc, "limitations[2]: open blocking limitation is refused in release mode",
                           release=True)

    def test_open_blocking_limitation_accepted_outside_release(self):
        doc = self.bundle()
        doc["limitations"].append({"blocks_release": True, "id": "residency-cap", "status": "open"})
        self.assertNoProblem(doc, "open blocking limitation", release=False)

    def test_closed_blocking_limitation_accepted_in_release(self):
        doc = self.bundle()
        doc["limitations"].append({"blocks_release": True, "id": "residency-cap", "status": "closed"})
        self.assertClean(doc, release=True)

    def test_limitation_status_must_be_open_or_closed(self):
        doc = self.bundle()
        doc["limitations"][0]["status"] = "pending"
        self.assertProblem(doc, "limitations[0].status: must be open or closed")

    def test_no_historical_record_refused(self):
        doc = self.bundle()
        doc["historical"] = []
        self.assertProblem(doc, "historical: needs at least 1 item(s)")

    def test_historical_kind_must_be_application_hang(self):
        doc = self.bundle()
        doc["historical"][0]["kind"] = "crash"
        self.assertProblem(doc, "historical[0].kind: must be application-hang")

    def test_unresolved_diagnostics_must_be_strings(self):
        doc = self.bundle()
        doc["unresolved_diagnostics"] = [3]
        self.assertProblem(doc, "unresolved_diagnostics[0]: must be a string")

    def test_open_finite_residency_limitation_refused_in_release(self):
        doc = self.bundle()
        doc["limitations"][0]["status"] = "open"
        self.assertProblem(doc, "limitations[0]: open blocking limitation is refused in release mode",
                           release=True)
        self.assertNoProblem(doc, "open blocking limitation", release=False)

    def test_open_distant_cave_edit_limitation_refused_in_release(self):
        doc = self.bundle()
        doc["limitations"][1]["status"] = "open"
        self.assertProblem(doc, "limitations[1]: open blocking limitation is refused in release mode",
                           release=True)
        self.assertNoProblem(doc, "open blocking limitation", release=False)

    def test_open_limitation_that_does_not_block_is_allowed_in_release(self):
        doc = self.bundle()
        doc["limitations"].append({"blocks_release": False, "id": "fixture-note", "status": "open"})
        self.assertNoProblem(doc, "open blocking limitation", release=True)

    def test_blocks_release_must_be_bool(self):
        doc = self.bundle()
        doc["limitations"][0]["blocks_release"] = "true"
        self.assertProblem(doc, "limitations[0].blocks_release: must be true or false")


class ReleaseOnlyRecordTest(_BundleTest):
    def test_preview_audio_off_must_be_true_in_release_mode(self):
        doc = self.bundle()
        doc["launcher"]["preview_audio_off"] = False
        self.assertProblem(doc, "launcher.preview_audio_off must be true in release mode", release=True)

    def test_preview_audio_off_false_is_recorded_outside_release(self):
        doc = self.bundle()
        doc["launcher"]["preview_audio_off"] = False
        self.assertNoProblem(doc, "launcher.preview_audio_off", release=False)
        self.assertNoProblem(doc, "launcher.preview_audio_off must be true", release=False)

    def test_settings_preserved_must_be_true_in_release_mode(self):
        doc = self.bundle()
        doc["disabled_backend"]["settings_preserved"] = False
        self.assertProblem(doc, "disabled_backend.settings_preserved must be true in release mode",
                           release=True)

    def test_settings_preserved_false_is_recorded_outside_release(self):
        doc = self.bundle()
        doc["disabled_backend"]["settings_preserved"] = False
        self.assertNoProblem(doc, "disabled_backend.settings_preserved", release=False)
        self.assertClean(doc, release=False)

    def test_launcher_and_settings_flags_must_be_bool(self):
        doc = self.bundle()
        doc["launcher"]["preview_audio_off"] = "true"
        doc["disabled_backend"]["settings_preserved"] = 1
        self.assertProblem(doc, "launcher.preview_audio_off: must be true or false", release=True)
        self.assertProblem(doc, "disabled_backend.settings_preserved: must be true or false", release=True)


class MutationTableTest(_BundleTest):
    """Each row mutates one field of the valid helper bundle and expects a named problem."""

    CASES = (
        ("duplicate pack ids",
         lambda d: d["content"]["packs"].append(dict(d["content"]["packs"][0])),
         "content.packs[1].id: duplicate id 'base-content'"),
        ("duplicate scene ids",
         lambda d: d["scenes"][1].__setitem__("id", d["scenes"][0]["id"]),
         "scenes[1].id: duplicate id 'forest-edge'"),
        ("duplicate limitation ids",
         lambda d: d["limitations"].append(dict(d["limitations"][0])),
         "limitations[2].id: duplicate id 'finite-residency'"),
        ("duplicate historical ids",
         lambda d: d["historical"].append(dict(d["historical"][0])),
         "historical[1].id: duplicate id 'application-hang-66604'"),
        ("duplicate session ids",
         lambda d: d["sessions"][1].__setitem__("id", d["sessions"][0]["id"]),
         "sessions[1].id: duplicate id 'create-world'"),
        ("duplicate save names",
         lambda d: d["saves"][1].__setitem__("name", d["saves"][0]["name"]),
         "saves[1].name: duplicate save name 'edit-save'"),
        ("empty packs",
         lambda d: d["content"].__setitem__("packs", []),
         "content.packs: needs at least 1 item(s)"),
        ("empty policy.refusal_exit_codes",
         lambda d: d["policy"].__setitem__("refusal_exit_codes", []),
         "policy.refusal_exit_codes: needs at least 1 item(s)"),
        ("refusal exit code 0 in policy",
         lambda d: d["policy"].__setitem__("refusal_exit_codes", [0, 2]),
         "policy.refusal_exit_codes[0]: must be an integer from 1 to 125"),
        ("refusal exit code 126 in policy",
         lambda d: d["policy"].__setitem__("refusal_exit_codes", [126, 2]),
         "policy.refusal_exit_codes[0]: must be an integer from 1 to 125"),
        ("non-bool no_audio_flag",
         lambda d: d["sessions"][0].__setitem__("no_audio_flag", "false"),
         "sessions[0].no_audio_flag: must be true or false"),
        ("non-bool scene settled",
         lambda d: d["scenes"][0].__setitem__("settled", 1),
         "scenes[0].settled: must be true"),
        ("non-bool refusal saves_unchanged",
         lambda d: d["sessions"][REFUSAL_SAVE].__setitem__("saves_unchanged", "yes"),
         "sessions[7].saves_unchanged: must be true"),
        ("non-bool forest agree",
         lambda d: d["forest"].__setitem__("agree", "true"),
         "forest.agree: must be true"),
        ("non-bool launcher preview_audio_off",
         lambda d: d["launcher"].__setitem__("preview_audio_off", None),
         "launcher.preview_audio_off: must be true or false"),
        ("non-bool disabled settings_preserved",
         lambda d: d["disabled_backend"].__setitem__("settings_preserved", "true"),
         "disabled_backend.settings_preserved: must be true or false"),
        ("non-bool limitation blocks_release",
         lambda d: d["limitations"][0].__setitem__("blocks_release", 0),
         "limitations[0].blocks_release: must be true or false"),
        ("string exit_code",
         lambda d: d["sessions"][0].__setitem__("exit_code", "0"),
         "sessions[0].exit_code: must be an integer"),
        ("string refusal exit code in policy",
         lambda d: d["policy"].__setitem__("refusal_exit_codes", ["2", 3]),
         "policy.refusal_exit_codes[0]: must be an integer from 1 to 125"),
    )

    def test_each_mutation_is_refused_with_its_named_problem(self):
        for name, mutate, text in self.CASES:
            with self.subTest(mutation=name):
                doc = self.bundle()
                mutate(doc)
                self.assertProblem(doc, text)


class PrivateMaterialTest(_BundleTest):
    def test_private_extension_string_refused(self):
        doc = self.bundle()
        doc["historical"][0]["disposition"] = "see capture.wav"
        self.assertProblem(doc, "historical[0].disposition: private file extension '.wav'")

    def test_private_extension_in_save_path_refused(self):
        doc = self.bundle()
        doc["saves"][0]["files"][0]["path"] = "world/state.sav"
        self.assertProblem(doc, "saves[0].files[0].path: private file extension '.sav'")

    def test_every_private_extension_is_refused(self):
        for extension in (".wav", ".ogg", ".flac", ".mp3", ".m4a", ".aac", ".wma",
                          ".dll", ".so", ".exe", ".sav", ".lmc", ".zip"):
            doc = self.bundle()
            doc["historical"][0]["disposition"] = "item" + extension
            self.assertProblem(doc, "private file extension '%s'" % extension)

    def test_drive_path_string_refused(self):
        doc = self.bundle()
        doc["historical"][0]["disposition"] = "log at C:\\work\\run"
        self.assertProblem(doc, "historical[0].disposition: local absolute path shape is not allowed")

    def test_home_path_string_refused(self):
        doc = self.bundle()
        doc["historical"][0]["disposition"] = "copied from " + "/ho" + "me/" + "builder/run"
        self.assertProblem(doc, "historical[0].disposition: local absolute path shape is not allowed")

    def test_users_path_string_refused(self):
        doc = self.bundle()
        doc["historical"][0]["disposition"] = "copied from " + "/Us" + "ers/" + "builder"
        self.assertProblem(doc, "historical[0].disposition: local absolute path shape is not allowed")

    def test_drive_path_with_repeated_separators_refused(self):
        for bad in ("C://temp/run", "C:\\\\temp", "D:\\\\\\\\share\\\\run", "E:/temp/run"):
            with self.subTest(value=bad):
                doc = self.bundle()
                doc["historical"][0]["disposition"] = "log at " + bad
                self.assertProblem(doc, "historical[0].disposition: local absolute path shape is not allowed")

    def test_url_is_not_a_drive_path(self):
        doc = self.bundle()
        doc["historical"][0]["disposition"] = "see https://example.invalid/run"
        self.assertNoProblem(doc, "local absolute path shape")

    def test_bare_url_host_is_not_a_drive_path(self):
        doc = self.bundle()
        doc["historical"][0]["disposition"] = "see https://x"
        self.assertNoProblem(doc, "local absolute path shape")
        self.assertClean(doc)


class ArtifactHashListTest(unittest.TestCase):
    def test_artifact_hashes_cover_every_named_hash(self):
        doc = make_bundle()
        digests = {digest for digest, _location in artifact_hashes(doc)}
        expected = {
            _h("archive"), _h("pack-base"), _h("manifest-start"), _h("manifest-edited"), _h("settings-kept"),
            _h("forest-submission"), _h("forest-report"), _h("launcher-identity"),
            _h("disabled-backend-proof"),
        }
        for sid in SESSION_IDS:
            expected.add(_h("command-" + sid))
            expected.add(_h("journal-" + sid))
        for scene in SCENE_IDS:
            expected.add(_h("capture-" + scene))
        self.assertEqual(digests, expected)
        self.assertEqual(artifact_count(doc), len(expected))


class ArtifactRootTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = self.root / "store"

    def tearDown(self):
        self._tmp.cleanup()

    def test_success_when_every_artifact_present_and_hashed(self):
        doc = make_bundle()
        _store(self.store)
        self.assertEqual(verify_artifacts(doc, str(self.store)), [])
        self.assertEqual(artifact_count(doc), len({d for d, _ in artifact_hashes(doc)}))
        self.assertIn((_h("pack-base"), "content.packs[0].sha256"), artifact_hashes(doc))

    def test_missing_pack_artifact_reported_with_location(self):
        doc = make_bundle()
        _store(self.store, skip=frozenset([_h("pack-base")]))
        problems = verify_artifacts(doc, str(self.store))
        self.assertEqual(
            problems,
            ["content.packs[0].sha256: artifact %s missing" % _h("pack-base")],
        )

    def test_mismatched_pack_artifact_reported_with_location(self):
        doc = make_bundle()
        _store(self.store)
        digest = _h("pack-base")
        (self.store / "sha256" / digest).write_bytes(b"tampered pack\n")
        problems = verify_artifacts(doc, str(self.store))
        self.assertEqual(problems, ["content.packs[0].sha256: artifact %s mismatch" % digest])

    def test_missing_artifact_reported_with_location(self):
        doc = make_bundle()
        _store(self.store, skip=frozenset([_h("command-create-world")]))
        problems = verify_artifacts(doc, str(self.store))
        self.assertEqual(
            problems,
            ["sessions[0].command_sha256: artifact %s missing" % _h("command-create-world")],
        )

    def test_mismatched_artifact_reported(self):
        doc = make_bundle()
        _store(self.store)
        digest = _h("archive")
        (self.store / "sha256" / digest).write_bytes(b"tampered\n")
        problems = verify_artifacts(doc, str(self.store))
        self.assertEqual(problems, ["package.archive_sha256: artifact %s mismatch" % digest])

    def test_audio_off_journal_without_marker_reported(self):
        doc = make_bundle()
        _store(self.store)
        plain = b"artifact journal-preview-launch\n"
        digest = hashlib.sha256(plain).hexdigest()
        doc["sessions"][PREVIEW]["journal_sha256"] = digest
        (self.store / "sha256").mkdir(parents=True, exist_ok=True)
        (self.store / "sha256" / digest).write_bytes(plain)
        problems = verify_artifacts(doc, str(self.store))
        self.assertEqual(
            problems,
            ["sessions[9].journal_sha256: audio-off journal lacks the audio-off marker"],
        )

    def test_missing_artifact_root_reported(self):
        problems = verify_artifacts(make_bundle(), str(self.root / "absent"))
        self.assertEqual(len(problems), 1)
        self.assertIn("artifact root is not a directory", problems[0])


class RegistryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_schema_is_registered(self):
        schemas, _globs = discover()
        self.assertIn(SCHEMA_ID, schemas)

    def test_content_tree_runs_structure_checks(self):
        target = self.root / "content" / "acceptance"
        target.mkdir(parents=True)
        _write_bundle(target / "bundle.json", make_bundle())
        self.assertEqual(validate_content.validate_tree(str(self.root), False, False), [])

        bad = make_bundle()
        bad["forest"]["agree"] = False
        _write_bundle(target / "bundle.json", bad)
        problems = validate_content.validate_tree(str(self.root), False, False)
        self.assertEqual(problems, ["content/acceptance/bundle.json: forest.agree: must be true"])


class CliTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bundle = self.root / "bundle.json"
        self.store = self.root / "store"

    def tearDown(self):
        self._tmp.cleanup()

    def test_release_requires_artifact_root(self):
        _write_bundle(self.bundle, make_bundle())
        code, _out, err = _run_cli([str(self.bundle), "--structure-only", "--release"])
        self.assertEqual(code, 2)
        self.assertIn("release requires --artifact-root", err)

    def test_both_modes_given_is_usage_error(self):
        _write_bundle(self.bundle, make_bundle())
        code, _out, err = _run_cli([str(self.bundle), "--structure-only", "--artifact-root", str(self.store)])
        self.assertEqual(code, 2)
        self.assertIn("mutually exclusive", err)

    def test_neither_mode_given_is_usage_error(self):
        _write_bundle(self.bundle, make_bundle())
        code, _out, err = _run_cli([str(self.bundle)])
        self.assertEqual(code, 2)
        self.assertIn("one of --structure-only or --artifact-root DIR is required", err)

    def test_structure_only_prints_final_line(self):
        code, out, _err = _run_cli([str(FIXTURES / "valid.json"), "--structure-only"])
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[-1], "structure-only: artifacts NOT verified")

    def test_invalid_bundle_prints_path_reason_lines(self):
        doc = make_bundle()
        doc["forest"]["agree"] = False
        _write_bundle(self.bundle, doc)
        code, out, _err = _run_cli([str(self.bundle), "--structure-only"])
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines(), ["forest.agree: must be true"])

    def test_malformed_json_is_reported_without_traceback(self):
        self.bundle.write_bytes(b'{"schema": ')
        code, out, err = _run_cli([str(self.bundle), "--structure-only"])
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith(str(self.bundle) + ": "), out)
        self.assertNotIn("Traceback", out + err)

    def test_missing_bundle_file_is_reported(self):
        code, out, _err = _run_cli([str(self.root / "absent.json"), "--structure-only"])
        self.assertEqual(code, 1)
        self.assertIn("cannot read file", out)

    def test_release_refuses_open_defect_with_artifacts(self):
        doc = make_bundle()
        doc["scenes"][2]["defects"].append({"id": "lod-pop", "disposition": "open", "note": ""})
        _write_bundle(self.bundle, doc)
        _store(self.store)
        code, out, _err = _run_cli([str(self.bundle), "--artifact-root", str(self.store), "--release"])
        self.assertEqual(code, 1)
        self.assertIn("open defect is refused in release mode", out)

    def test_artifact_root_success_reports_count(self):
        doc = make_bundle()
        _write_bundle(self.bundle, doc)
        _store(self.store)
        code, out, _err = _run_cli([str(self.bundle), "--artifact-root", str(self.store)])
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), ["artifacts verified: %d" % artifact_count(doc)])

    def test_artifact_root_release_success(self):
        _write_bundle(self.bundle, make_bundle())
        _store(self.store)
        code, out, _err = _run_cli([str(self.bundle), "--artifact-root", str(self.store), "--release"])
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("artifacts verified: "), out)

    def test_missing_artifact_is_reported(self):
        _write_bundle(self.bundle, make_bundle())
        _store(self.store, skip=frozenset([_h("archive")]))
        code, out, _err = _run_cli([str(self.bundle), "--artifact-root", str(self.store)])
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines(), ["package.archive_sha256: artifact %s missing" % _h("archive")])

    def test_mismatched_artifact_is_reported(self):
        _write_bundle(self.bundle, make_bundle())
        _store(self.store)
        (self.store / "sha256" / _h("archive")).write_bytes(b"other\n")
        code, out, _err = _run_cli([str(self.bundle), "--artifact-root", str(self.store)])
        self.assertEqual(code, 1)
        self.assertIn("artifact %s mismatch" % _h("archive"), out)

    def test_missing_audio_marker_is_reported(self):
        doc = make_bundle()
        plain = b"artifact journal-preview-launch\n"
        digest = hashlib.sha256(plain).hexdigest()
        doc["sessions"][PREVIEW]["journal_sha256"] = digest
        _write_bundle(self.bundle, doc)
        _store(self.store)
        (self.store / "sha256" / digest).write_bytes(plain)
        code, out, _err = _run_cli([str(self.bundle), "--artifact-root", str(self.store)])
        self.assertEqual(code, 1)
        self.assertIn("audio-off journal lacks the audio-off marker", out)

    def test_problem_output_is_capped_at_fifty_lines(self):
        doc = make_bundle()
        base = doc["scenes"][0]
        doc["scenes"] = []
        for index in range(60):
            scene = copy.deepcopy(base)
            scene["id"] = "scene-%d" % index
            scene["settled"] = False
            doc["scenes"].append(scene)
        _write_bundle(self.bundle, doc)
        code, out, _err = _run_cli([str(self.bundle), "--structure-only"])
        self.assertEqual(code, 1)
        self.assertEqual(len(out.splitlines()), 50)


class FixtureTest(unittest.TestCase):
    # file, release flag, substring that must appear, release-only rule
    CASES = (
        ("invalid-unknown-key.json", False, "package: unknown key 'extra'", False),
        ("invalid-future-schema.json", False, "future schema version", False),
        ("invalid-missing-key.json", False, "missing key 'content'", False),
        ("invalid-bad-hash.json", False, "package.archive_sha256: must be 64", False),
        ("invalid-exit-code.json", False, "sessions[0].exit_code: normalised exit code must be 0", False),
        ("invalid-refusal-code.json", False, "not in policy.refusal_exit_codes", False),
        ("invalid-hang-signature.json", False, "application hang signature", False),
        ("invalid-audio-off-without-flag.json", False, "sessions[0]: audio_mode off requires no_audio_flag true", False),
        ("invalid-preview-audio.json", False, "preview requires audio_mode off", False),
        ("invalid-missing-session-kind.json", False, "missing session kind 'switch'", False),
        ("invalid-refusal-saves-changed.json", False, "saves_unchanged: must be true", False),
        ("invalid-no-edited-save.json", False, "saves: no save has an edited file", False),
        ("invalid-scene-unsettled.json", False, "scenes[0].settled: must be true", False),
        ("invalid-open-defect.json", True, "open defect is refused in release mode", True),
        ("invalid-few-scenes.json", False, "scenes: at least 6 scenes are required, found 5", False),
        ("invalid-forest-disagree.json", False, "forest.agree: must be true", False),
        ("invalid-open-limitation.json", True, "limitations[0]: open blocking limitation is refused", True),
        ("invalid-no-historical.json", False, "historical: needs at least 1 item(s)", False),
        ("invalid-private-extension.json", False, "private file extension '.wav'", False),
        ("invalid-drive-path.json", False, "local absolute path shape is not allowed", False),
    )

    def test_each_invalid_fixture_triggers_its_rule(self):
        for name, release, text, release_only in self.CASES:
            with self.subTest(fixture=name):
                doc = load_json_file(FIXTURES / name)
                problems = validate_bundle(doc, release=release)
                self.assertTrue(any(text in problem for problem in problems), problems)
                if release_only:
                    problems = validate_bundle(doc, release=False)
                    self.assertFalse(any(text in problem for problem in problems), problems)

    def test_every_rule_fixture_file_exists(self):
        for name, _release, _text, _release_only in self.CASES:
            self.assertTrue((FIXTURES / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
