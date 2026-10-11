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
    PRIVATE_EXTENSIONS,
    SCHEMA_ID,
    artifact_count,
    artifact_hashes,
    marker_problem,
    printable,
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

# Private extensions named in the rules before the extension list was extended.
ORIGINAL_EXTENSIONS = (
    ".wav", ".ogg", ".flac", ".mp3", ".m4a", ".aac", ".wma",
    ".dll", ".so", ".exe", ".sav", ".lmc", ".zip",
)
ADDED_EXTENSIONS = (
    ".opus", ".aiff", ".aif", ".wem", ".bank", ".fsb", ".snd", ".mid", ".midi", ".ape",
    ".mka", ".amr", ".pdb", ".lib", ".a", ".dylib", ".obj", ".o", ".pck", ".sdk",
    ".p12", ".pfx", ".pem", ".key", ".lmr",
)

# Session indexes in make_bundle(): 0 create-world, 3 restart-world, 6 switch-world-b,
# 7 refusal-bad-save, 8 refusal-bad-switch, 9 preview-launch, 10 restart-no-audio.
RESTART_WORLD = 3
SWITCH_WORLD_B = 6
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
        "policy": {"refusal_exit_codes": [2, 3]},
        "sessions": [
            _session("create-world", "create", "null", False),
            _session("edit-world", "edit", "null", False),
            _session("save-world", "save", "null", False),
            _session("restart-world", "restart", "null", False),
            _session("load-world", "load", "null", False),
            _session("switch-world-a", "switch", "null", False),
            _session("switch-world-b", "switch", "null", False),
            _session("refusal-bad-save", "refusal", "null", False, 2,
                     refusal_code="save-corrupt", saves=["save-refusal"], saves_unchanged=True),
            _session("refusal-bad-switch", "refusal", "null", False, 3,
                     refusal_code="switch-target-missing", saves=["switch-refusal"],
                     saves_unchanged=True),
            _session("preview-launch", "preview", "off", True),
            _session("restart-no-audio", "restart", "off", True),
        ],
        "startup_checks": {
            "no_audio_precedence_session": "restart-no-audio",
            "null_audio_nonzero_master_session": "restart-world",
        },
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

    def test_bundle_cannot_carry_the_audio_off_marker(self):
        doc = self.bundle()
        doc["policy"]["audio_off_marker"] = MARKER
        self.assertProblem(doc, "policy: unknown key 'audio_off_marker'")

    def test_marker_problem_refuses_empty_control_and_missing_values(self):
        self.assertIsNone(marker_problem(MARKER))
        self.assertEqual(marker_problem(""), "must be a non-empty string")
        self.assertEqual(marker_problem(None), "must be a non-empty string")
        self.assertEqual(marker_problem("LUM\nOFF"), "must not contain control characters")
        self.assertEqual(marker_problem("LUM\x7fOFF"), "must not contain control characters")

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


class StartupChecksTest(_BundleTest):
    def test_startup_checks_key_is_required(self):
        doc = self.bundle()
        del doc["startup_checks"]
        self.assertProblem(doc, "bundle: missing key 'startup_checks'")

    def test_startup_checks_unknown_key_refused(self):
        doc = self.bundle()
        doc["startup_checks"]["extra"] = "restart-world"
        self.assertProblem(doc, "startup_checks: unknown key 'extra'")

    def test_startup_checks_missing_key_refused(self):
        doc = self.bundle()
        del doc["startup_checks"]["null_audio_nonzero_master_session"]
        self.assertProblem(doc, "startup_checks: missing key 'null_audio_nonzero_master_session'")

    def test_first_check_must_reference_existing_session(self):
        doc = self.bundle()
        doc["startup_checks"]["null_audio_nonzero_master_session"] = "nope"
        self.assertProblem(doc, "startup_checks.null_audio_nonzero_master_session: unknown session 'nope'")

    def test_second_check_must_reference_existing_session(self):
        doc = self.bundle()
        doc["startup_checks"]["no_audio_precedence_session"] = "nope"
        self.assertProblem(doc, "startup_checks.no_audio_precedence_session: unknown session 'nope'")

    def test_first_check_with_zero_master_refused(self):
        doc = self.bundle()
        doc["sessions"][RESTART_WORLD]["saved_master"] = 0
        self.assertProblem(
            doc,
            "startup_checks.null_audio_nonzero_master_session: session 'restart-world' must have "
            "audio_mode null, no_audio_flag false and saved_master above zero",
        )

    def test_first_check_pointing_at_audio_off_session_refused(self):
        doc = self.bundle()
        doc["startup_checks"]["null_audio_nonzero_master_session"] = "restart-no-audio"
        self.assertProblem(
            doc,
            "startup_checks.null_audio_nonzero_master_session: session 'restart-no-audio' must have "
            "audio_mode null",
        )

    def test_second_check_with_wrong_audio_mode_refused(self):
        doc = self.bundle()
        doc["sessions"][NO_AUDIO_RESTART]["audio_mode"] = "null"
        self.assertProblem(
            doc,
            "startup_checks.no_audio_precedence_session: session 'restart-no-audio' must have "
            "audio_mode off and no_audio_flag true",
        )

    def test_second_check_without_flag_refused(self):
        doc = self.bundle()
        doc["sessions"][NO_AUDIO_RESTART]["no_audio_flag"] = False
        self.assertProblem(
            doc,
            "startup_checks.no_audio_precedence_session: session 'restart-no-audio' must have "
            "audio_mode off and no_audio_flag true",
        )

    def test_second_check_must_be_restart_or_load(self):
        doc = self.bundle()
        doc["sessions"][NO_AUDIO_RESTART]["kind"] = "save"
        self.assertProblem(
            doc,
            "startup_checks.no_audio_precedence_session: session 'restart-no-audio' must be a restart or load session",
        )

    def test_load_is_an_accepted_second_check_kind(self):
        doc = self.bundle()
        doc["sessions"][NO_AUDIO_RESTART]["kind"] = "load"
        self.assertNoProblem(doc, "startup_checks", release=True)

    def test_fewer_than_two_switch_sessions_refused(self):
        doc = self.bundle()
        del doc["sessions"][SWITCH_WORLD_B]
        self.assertProblem(doc, "sessions: at least 2 sessions of kind 'switch' are required, found 1")
        self.assertNoProblem(doc, "missing session kind 'switch'")


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


class RefusalSaveTest(_BundleTest):
    def test_refusal_session_without_saves_refused(self):
        doc = self.bundle()
        del doc["sessions"][REFUSAL_SAVE]["saves"]
        self.assertProblem(doc, "sessions[7]: missing key 'saves'")

    def test_refusal_saves_must_not_be_empty(self):
        doc = self.bundle()
        doc["sessions"][REFUSAL_SAVE]["saves"] = []
        self.assertProblem(doc, "sessions[7].saves: needs at least 1 item(s)")

    def test_unknown_save_name_refused(self):
        doc = self.bundle()
        doc["sessions"][REFUSAL_SAVE]["saves"] = ["nope"]
        self.assertProblem(doc, "sessions[7].saves[0]: unknown save 'nope'")

    def test_duplicate_save_name_in_session_refused(self):
        doc = self.bundle()
        doc["sessions"][REFUSAL_SAVE]["saves"] = ["save-refusal", "save-refusal"]
        self.assertProblem(doc, "sessions[7].saves[1]: duplicate save 'save-refusal' in this session")

    def test_referenced_save_with_changed_hash_refused(self):
        doc = self.bundle()
        doc["saves"][1]["files"][0]["sha256_after"] = _h("manifest-start")
        self.assertProblem(
            doc, "sessions[7].saves[0]: referenced save 'save-refusal' changed file 'world/manifest.txt'"
        )

    def test_non_refusal_session_carrying_saves_refused(self):
        doc = self.bundle()
        doc["sessions"][0]["saves"] = ["save-refusal"]
        self.assertProblem(doc, "sessions[0]: unknown key 'saves'")

    def test_save_name_suffix_no_longer_decides_refusal(self):
        doc = self.bundle()
        doc["saves"].append({
            "name": "stray-refusal",
            "files": [{"path": "world/stray.txt",
                       "sha256_before": _h("manifest-start"),
                       "sha256_after": _h("manifest-edited")}],
        })
        self.assertClean(doc)


class SaveRuleTest(_BundleTest):
    def test_no_edited_save_refused(self):
        doc = self.bundle()
        for save in doc["saves"]:
            for entry in save["files"]:
                entry["sha256_after"] = entry["sha256_before"]
        self.assertProblem(doc, "saves: no save has an edited file")

    def test_portable_relative_paths_only(self):
        for bad in ("/abs/manifest.txt", "world\\manifest.txt", "../manifest.txt",
                    "C:manifest.txt", "world//manifest.txt"):
            doc = self.bundle()
            doc["saves"][0]["files"][0]["path"] = bad
            self.assertProblem(doc, "saves[0].files[0].path: must be a portable relative path")

    def test_control_characters_in_components_refused(self):
        cases = (
            ("world/a\nb.txt", "a\\nb.txt"),
            ("world/a\tb.txt", "a\\tb.txt"),
            ("world/a\x00b.txt", "a\\x00b.txt"),
            ("world/a\x7fb.txt", "a\\x7fb.txt"),
            ("world/a\rb/manifest.txt", "a\\rb"),
        )
        for bad, component in cases:
            with self.subTest(component=component):
                doc = self.bundle()
                doc["saves"][0]["files"][0]["path"] = bad
                self.assertProblem(
                    doc,
                    "saves[0].files[0].path: component '%s' contains a control character"
                    % component,
                )
                for problem in validate_bundle(doc):
                    self.assertFalse(any(ord(char) < 0x20 or ord(char) == 0x7F for char in problem))

    def test_windows_device_names_refused_in_any_component(self):
        cases = (
            ("CON.txt", "CON.txt"),
            ("nul", "nul"),
            ("prn", "prn"),
            ("world/aux/manifest.txt", "aux"),
            ("world/com1/manifest.txt", "com1"),
            ("world/LPT9.log", "LPT9.log"),
            ("world/con .txt", "con .txt"),
        )
        for bad, component in cases:
            with self.subTest(path=bad):
                doc = self.bundle()
                doc["saves"][0]["files"][0]["path"] = bad
                self.assertProblem(
                    doc,
                    "saves[0].files[0].path: component '%s' is a reserved Windows device name"
                    % component,
                )

    def test_windows_forbidden_characters_refused_in_components(self):
        for bad in ("manifest.txt:private", "world/a*b.txt", "world/q?.txt", 'world/"x".txt',
                    "world/<a>.txt", "world/a|b.txt", "world/a>b.txt"):
            with self.subTest(path=bad):
                doc = self.bundle()
                doc["saves"][0]["files"][0]["path"] = bad
                component = [part for part in bad.split("/") if any(c in part for c in ':*?"<>|')][0]
                self.assertProblem(
                    doc,
                    "saves[0].files[0].path: component '%s' contains a character Windows does not allow"
                    % component,
                )

    def test_components_ending_in_dot_or_space_refused(self):
        for bad, component in (("a.", "a."), ("a ", "a "), ("world/dir./manifest.txt", "dir.")):
            with self.subTest(path=bad):
                doc = self.bundle()
                doc["saves"][0]["files"][0]["path"] = bad
                self.assertProblem(
                    doc,
                    "saves[0].files[0].path: component '%s' ends in a dot or a space" % component,
                )

    def test_normal_nested_paths_accepted(self):
        for good in ("world/manifest.txt", "world/slot one/manifest.txt",
                     "world/console.txt", "world/nullify/manifest.txt", "world/a.b/c.d"):
            with self.subTest(path=good):
                doc = self.bundle()
                doc["saves"][0]["files"][0]["path"] = good
                self.assertClean(doc)

    def test_empty_save_files_refused(self):
        doc = self.bundle()
        doc["saves"][0]["files"] = []
        self.assertProblem(doc, "saves[0].files: needs at least 1 item(s)")

    def test_duplicate_save_name_refused(self):
        doc = self.bundle()
        doc["saves"][1]["name"] = "edit-save"
        self.assertProblem(doc, "saves[1].name: duplicate save name 'edit-save'")

    def test_duplicate_path_in_one_save_refused(self):
        doc = self.bundle()
        doc["saves"][0]["files"].append(
            {"path": "world/settings.txt",
             "sha256_before": _h("settings-kept"),
             "sha256_after": _h("settings-kept")})
        self.assertProblem(doc, "saves[0].files[2].path: duplicate path 'world/settings.txt'")

    def test_duplicate_path_with_case_alias_and_other_hash_refused(self):
        doc = self.bundle()
        doc["saves"][0]["files"].append(
            {"path": "world/A.txt",
             "sha256_before": _h("alias-start"),
             "sha256_after": _h("alias-edited")})
        doc["saves"][0]["files"].append(
            {"path": "world/a.txt",
             "sha256_before": _h("other-start"),
             "sha256_after": _h("other-edited")})
        self.assertProblem(doc, "saves[0].files[3].path: duplicate path 'world/a.txt'")

    def test_same_path_in_different_saves_accepted(self):
        doc = self.bundle()
        doc["saves"][2]["files"][0]["path"] = "world/settings.txt"
        self.assertNoProblem(doc, "duplicate path")


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

    def test_duplicate_defect_id_in_one_scene_refused(self):
        doc = self.bundle()
        doc["scenes"][0]["defects"].append({"id": "shadow-seam", "disposition": "open", "note": ""})
        self.assertProblem(doc, "scenes[0].defects[1]: duplicate id 'shadow-seam'")
        self.assertProblem(doc, "scenes[0].defects[1]: duplicate id 'shadow-seam'", release=True)

    def test_same_defect_id_in_two_scenes_accepted(self):
        doc = self.bundle()
        doc["scenes"][2]["defects"].append({"id": "shadow-seam", "disposition": "fixed", "note": ""})
        self.assertClean(doc)
        self.assertNoProblem(doc, "duplicate id")

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

    def test_empty_limitations_refused_for_both_required_ids(self):
        doc = self.bundle()
        doc["limitations"] = []
        self.assertProblem(doc, "limitations: missing required entry 'finite-residency'")
        self.assertProblem(doc, "limitations: missing required entry 'distant-cave-edit-omitted'")

    def test_missing_required_limitation_refused(self):
        doc = self.bundle()
        del doc["limitations"][1]
        self.assertProblem(doc, "limitations: missing required entry 'distant-cave-edit-omitted'")
        self.assertNoProblem(doc, "missing required entry 'finite-residency'")

    def test_required_limitation_with_blocks_release_false_refused(self):
        doc = self.bundle()
        doc["limitations"][0]["blocks_release"] = False
        self.assertProblem(doc, "limitations[0]: 'finite-residency' must have blocks_release true")
        self.assertNoProblem(doc, "distant-cave-edit-omitted' must have blocks_release true")

    def test_distant_cave_limitation_with_blocks_release_false_refused(self):
        doc = self.bundle()
        doc["limitations"][1]["blocks_release"] = False
        self.assertProblem(doc, "limitations[1]: 'distant-cave-edit-omitted' must have blocks_release true")

    def test_other_limitations_may_be_added_freely(self):
        doc = self.bundle()
        doc["limitations"].append({"blocks_release": False, "id": "fixture-note", "status": "closed"})
        self.assertClean(doc, release=True)


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
        for extension in ORIGINAL_EXTENSIONS + ADDED_EXTENSIONS:
            with self.subTest(extension=extension):
                doc = self.bundle()
                doc["historical"][0]["disposition"] = "item" + extension
                self.assertProblem(doc, "private file extension '%s'" % extension)

    def test_private_extension_in_markdown_delimiters_refused(self):
        for text in ("`capture.wav`", "<capture.wav>", "**capture.wav**"):
            with self.subTest(text=text):
                doc = self.bundle()
                doc["historical"][0]["disposition"] = text
                self.assertProblem(doc, "historical[0].disposition: private file extension '.wav'")

    def test_region_save_extension_refused_in_prose_and_save_path(self):
        doc = self.bundle()
        doc["historical"][0]["disposition"] = "see r.0.0.lmr"
        self.assertProblem(doc, "historical[0].disposition: private file extension '.lmr'")
        doc = self.bundle()
        doc["saves"][0]["files"][0]["path"] = "world/r.0.0.lmr"
        self.assertProblem(doc, "saves[0].files[0].path: private file extension '.lmr'")

    def test_private_extension_list_includes_every_named_extension(self):
        self.assertTrue(set(ORIGINAL_EXTENSIONS + ADDED_EXTENSIONS) <= set(PRIVATE_EXTENSIONS))

    def test_private_extensions_are_case_insensitive(self):
        for extension in (".WAV", ".Opus", ".PEM", ".Key"):
            with self.subTest(extension=extension):
                doc = self.bundle()
                doc["historical"][0]["disposition"] = "item" + extension
                self.assertProblem(doc, "private file extension '%s'" % extension.lower())

    def test_private_extension_ending_a_filename_token_refused(self):
        for text in (
            "see capture.wav for details",
            "capture.wav",
            "capture.wav, then retry",
            "capture.wav; then retry",
            "capture.wav: attached",
            "capture.wav? no",
            "capture.wav! no",
            "capture.wav. Next line",
            "capture.wav.",
            "(capture.wav)",
            "[capture.wav]",
            "'capture.wav'",
            '"capture.wav"',
            "{capture.wav}",
        ):
            with self.subTest(text=text):
                doc = self.bundle()
                doc["historical"][0]["disposition"] = text
                self.assertProblem(doc, "historical[0].disposition: private file extension '.wav'")

    def test_bare_private_extension_refused(self):
        doc = self.bundle()
        doc["historical"][0]["disposition"] = ".wav"
        self.assertProblem(doc, "historical[0].disposition: private file extension '.wav'")

    def test_private_extension_wrapped_in_underscores_refused(self):
        doc = self.bundle()
        doc["historical"][0]["disposition"] = "_capture.wav_"
        self.assertProblem(doc, "historical[0].disposition: private file extension '.wav'")

    def test_private_extension_after_parenthesised_number_refused(self):
        doc = self.bundle()
        doc["historical"][0]["disposition"] = "see recording (1).wav"
        self.assertProblem(doc, "historical[0].disposition: private file extension '.wav'")

    def test_private_extension_inside_bold_or_backticks_refused(self):
        for text in ("**x.wav**", "`x.wav`", "[x.wav]"):
            with self.subTest(text=text):
                doc = self.bundle()
                doc["historical"][0]["disposition"] = text
                self.assertProblem(doc, "historical[0].disposition: private file extension '.wav'")

    def test_private_extension_in_upper_case_refused_in_text(self):
        doc = self.bundle()
        doc["historical"][0]["disposition"] = "see CAPTURE.WAV for details"
        self.assertProblem(doc, "historical[0].disposition: private file extension '.wav'")

    def test_innocent_text_near_private_extensions_accepted(self):
        for text in ("a.wavelength", "awav", "the wav file", "capture.wavelength",
                     "data.apple", "notes.opusx"):
            with self.subTest(text=text):
                doc = self.bundle()
                doc["historical"][0]["disposition"] = text
                self.assertNoProblem(doc, "private file extension")

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

    def test_unc_and_device_paths_refused(self):
        for bad in ("\\\\server\\share\\x", "\\\\?\\C:\\x", "//server/share/x"):
            for value in (bad, "log at " + bad):
                with self.subTest(value=value):
                    doc = self.bundle()
                    doc["historical"][0]["disposition"] = value
                    self.assertProblem(doc, "historical[0].disposition: local absolute path shape is not allowed")

    def test_unc_path_after_quote_or_bracket_refused(self):
        for bad in (r'see "\\server\share\run"', r"(//server/share/run)", r"[\\server\share\run]",
                    r"{//server/share/run}", r"a,\\server\share\run", r"a;//server/share/run",
                    r"x=\\server\share\run", r"<\\server\share\run>", r"it's '\\server\share\run'"):
            with self.subTest(value=bad):
                doc = self.bundle()
                doc["historical"][0]["disposition"] = bad
                self.assertProblem(doc, "historical[0].disposition: local absolute path shape is not allowed")

    def test_unc_path_inside_a_word_is_not_a_boundary(self):
        doc = self.bundle()
        doc["historical"][0]["disposition"] = r"run1\\server\share\run"
        self.assertNoProblem(doc, "local absolute path shape")

    def test_url_with_host_and_path_is_allowed(self):
        for value in ("https://host/path", "see https://host/path"):
            with self.subTest(value=value):
                doc = self.bundle()
                doc["historical"][0]["disposition"] = value
                self.assertNoProblem(doc, "local absolute path shape")

    def test_url_is_not_a_drive_path(self):
        doc = self.bundle()
        doc["historical"][0]["disposition"] = "see https://example.invalid/run"
        self.assertNoProblem(doc, "local absolute path shape")

    def test_url_with_double_slash_in_path_is_allowed(self):
        doc = self.bundle()
        doc["historical"][0]["disposition"] = "see https://example.invalid/a//b"
        self.assertNoProblem(doc, "local absolute path shape")
        self.assertClean(doc)

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
        self.assertEqual(verify_artifacts(doc, str(self.store), MARKER), [])
        self.assertEqual(artifact_count(doc), len({d for d, _ in artifact_hashes(doc)}))
        self.assertIn((_h("pack-base"), "content.packs[0].sha256"), artifact_hashes(doc))

    def test_missing_pack_artifact_reported_with_location(self):
        doc = make_bundle()
        _store(self.store, skip=frozenset([_h("pack-base")]))
        problems = verify_artifacts(doc, str(self.store), MARKER)
        self.assertEqual(
            problems,
            ["content.packs[0].sha256: artifact %s missing" % _h("pack-base")],
        )

    def test_mismatched_pack_artifact_reported_with_location(self):
        doc = make_bundle()
        _store(self.store)
        digest = _h("pack-base")
        (self.store / "sha256" / digest).write_bytes(b"tampered pack\n")
        problems = verify_artifacts(doc, str(self.store), MARKER)
        self.assertEqual(problems, ["content.packs[0].sha256: artifact %s mismatch" % digest])

    def test_missing_artifact_reported_with_location(self):
        doc = make_bundle()
        _store(self.store, skip=frozenset([_h("command-create-world")]))
        problems = verify_artifacts(doc, str(self.store), MARKER)
        self.assertEqual(
            problems,
            ["sessions[0].command_sha256: artifact %s missing" % _h("command-create-world")],
        )

    def test_mismatched_artifact_reported(self):
        doc = make_bundle()
        _store(self.store)
        digest = _h("archive")
        (self.store / "sha256" / digest).write_bytes(b"tampered\n")
        problems = verify_artifacts(doc, str(self.store), MARKER)
        self.assertEqual(problems, ["package.archive_sha256: artifact %s mismatch" % digest])

    def test_audio_off_journal_without_marker_reported(self):
        doc = make_bundle()
        _store(self.store)
        plain = b"artifact journal-preview-launch\n"
        digest = hashlib.sha256(plain).hexdigest()
        doc["sessions"][PREVIEW]["journal_sha256"] = digest
        (self.store / "sha256").mkdir(parents=True, exist_ok=True)
        (self.store / "sha256" / digest).write_bytes(plain)
        problems = verify_artifacts(doc, str(self.store), MARKER)
        self.assertEqual(
            problems,
            ["sessions[9].journal_sha256: audio-off journal lacks the audio-off marker"],
        )

    def test_journals_must_carry_the_operator_marker(self):
        doc = make_bundle()
        _store(self.store)
        problems = verify_artifacts(doc, str(self.store), "OTHER-MARKER")
        self.assertEqual(
            problems,
            [
                "sessions[9].journal_sha256: audio-off journal lacks the audio-off marker",
                "sessions[10].journal_sha256: audio-off journal lacks the audio-off marker",
            ],
        )

    def test_empty_marker_is_refused_by_verify(self):
        doc = make_bundle()
        _store(self.store)
        self.assertEqual(
            verify_artifacts(doc, str(self.store), ""),
            ["audio-off marker: must be a non-empty string"],
        )

    def test_missing_artifact_root_reported(self):
        problems = verify_artifacts(make_bundle(), str(self.root / "absent"), MARKER)
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

    def test_control_characters_in_registry_problems_are_escaped(self):
        target = self.root / "content" / "acceptance"
        target.mkdir(parents=True)
        bad = make_bundle()
        bad["policy"]["bad\nkey"] = 1
        _write_bundle(target / "bundle.json", bad)
        problems = validate_content.validate_tree(str(self.root), False, False)
        self.assertEqual(problems, ["content/acceptance/bundle.json: policy: unknown key 'bad\\nkey'"])
        for problem in problems:
            self.assertFalse(any(ord(char) < 0x20 or ord(char) == 0x7F for char in problem))

    def test_printable_escapes_control_characters(self):
        self.assertEqual(printable("a\nb\rc\td\x00e\x7f"), "a\\nb\\rc\\td\\x00e\\x7f")
        self.assertEqual(printable("plain"), "plain")


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

    def test_artifact_root_requires_audio_off_marker(self):
        _write_bundle(self.bundle, make_bundle())
        _store(self.store)
        code, _out, err = _run_cli([str(self.bundle), "--artifact-root", str(self.store)])
        self.assertEqual(code, 2)
        self.assertIn("--artifact-root requires --audio-off-marker", err)

    def test_audio_off_marker_with_structure_only_is_usage_error(self):
        _write_bundle(self.bundle, make_bundle())
        code, _out, err = _run_cli([str(self.bundle), "--structure-only", "--audio-off-marker", MARKER])
        self.assertEqual(code, 2)
        self.assertIn("--audio-off-marker is not used with --structure-only", err)

    def test_audio_off_marker_with_control_character_is_usage_error(self):
        _write_bundle(self.bundle, make_bundle())
        _store(self.store)
        code, _out, err = _run_cli([str(self.bundle), "--artifact-root", str(self.store),
                                    "--audio-off-marker", "LUM\nOFF"])
        self.assertEqual(code, 2)
        self.assertIn("--audio-off-marker: must not contain control characters", err)

    def test_empty_audio_off_marker_is_usage_error(self):
        _write_bundle(self.bundle, make_bundle())
        _store(self.store)
        code, _out, err = _run_cli([str(self.bundle), "--artifact-root", str(self.store),
                                    "--audio-off-marker", ""])
        self.assertEqual(code, 2)
        self.assertIn("--audio-off-marker: must be a non-empty string", err)

    def test_bundle_carrying_marker_is_refused_by_structure_check(self):
        doc = make_bundle()
        doc["policy"]["audio_off_marker"] = MARKER
        _write_bundle(self.bundle, doc)
        code, out, _err = _run_cli([str(self.bundle), "--structure-only"])
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines(), ["policy: unknown key 'audio_off_marker'"])

    def test_control_characters_in_a_key_keep_the_diagnostic_on_one_line(self):
        cases = (
            ("bad\nkey", "bad\\nkey"),
            ("bad\rkey", "bad\\rkey"),
            ("bad\tkey", "bad\\tkey"),
            ("bad\x01key", "bad\\x01key"),
            ("bad\x7fkey", "bad\\x7fkey"),
        )
        for raw, escaped in cases:
            with self.subTest(key=escaped):
                doc = make_bundle()
                doc["policy"][raw] = 1
                _write_bundle(self.bundle, doc)
                code, out, _err = _run_cli([str(self.bundle), "--structure-only"])
                self.assertEqual(code, 1)
                self.assertEqual(out.count("\n"), 1, out)
                self.assertEqual(out.splitlines(), ["policy: unknown key '%s'" % escaped])

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
        code, out, _err = _run_cli([str(self.bundle), "--artifact-root", str(self.store),
                                    "--audio-off-marker", MARKER, "--release"])
        self.assertEqual(code, 1)
        self.assertIn("open defect is refused in release mode", out)

    def test_artifact_root_success_reports_count(self):
        doc = make_bundle()
        _write_bundle(self.bundle, doc)
        _store(self.store)
        code, out, _err = _run_cli([str(self.bundle), "--artifact-root", str(self.store),
                                    "--audio-off-marker", MARKER])
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), ["artifacts verified: %d" % artifact_count(doc)])

    def test_artifact_root_release_success(self):
        _write_bundle(self.bundle, make_bundle())
        _store(self.store)
        code, out, _err = _run_cli([str(self.bundle), "--artifact-root", str(self.store),
                                    "--audio-off-marker", MARKER, "--release"])
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("artifacts verified: "), out)

    def test_missing_artifact_is_reported(self):
        _write_bundle(self.bundle, make_bundle())
        _store(self.store, skip=frozenset([_h("archive")]))
        code, out, _err = _run_cli([str(self.bundle), "--artifact-root", str(self.store),
                                    "--audio-off-marker", MARKER])
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines(), ["package.archive_sha256: artifact %s missing" % _h("archive")])

    def test_mismatched_artifact_is_reported(self):
        _write_bundle(self.bundle, make_bundle())
        _store(self.store)
        (self.store / "sha256" / _h("archive")).write_bytes(b"other\n")
        code, out, _err = _run_cli([str(self.bundle), "--artifact-root", str(self.store),
                                    "--audio-off-marker", MARKER])
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
        code, out, _err = _run_cli([str(self.bundle), "--artifact-root", str(self.store),
                                    "--audio-off-marker", MARKER])
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
        ("invalid-refusal-saves-changed.json", False, "changed file", False),
        ("invalid-no-edited-save.json", False, "saves: no save has an edited file", False),
        ("invalid-scene-unsettled.json", False, "scenes[0].settled: must be true", False),
        ("invalid-open-defect.json", True, "open defect is refused in release mode", True),
        ("invalid-few-scenes.json", False, "scenes: at least 6 scenes are required, found 5", False),
        ("invalid-forest-disagree.json", False, "forest.agree: must be true", False),
        ("invalid-open-limitation.json", True, "limitations[0]: open blocking limitation is refused", True),
        ("invalid-no-historical.json", False, "historical: needs at least 1 item(s)", False),
        ("invalid-private-extension.json", False, "private file extension '.wav'", False),
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
