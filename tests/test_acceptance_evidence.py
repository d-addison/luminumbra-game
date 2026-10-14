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
from unittest import mock

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import validate_acceptance_evidence  # noqa: E402
import validate_content  # noqa: E402
from lumlib.schema import load_json_file  # noqa: E402
from validators import acceptance, discover  # noqa: E402
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


# Command-line arguments written into each session's command artifact. The no_audio_flag
# declared for a session in make_bundle() must agree with its --no-audio argument (see
# CommandDeclarationTest). The precedence session (restart-no-audio) carries the diagnostic
# opt-in as well, and the null-audio startup session carries neither audio flag.
SESSION_FLAGS = {
    "create-world": (),
    "edit-world": (),
    "save-world": (),
    "restart-world": (),
    "load-world": (),
    "switch-world-a": (),
    "switch-world-b": (),
    "refusal-bad-save": (),
    "refusal-bad-switch": (),
    "preview-launch": ("--no-audio",),
    "restart-no-audio": ("--enable-audio", "--no-audio"),
}


def _blob(label):
    """Return the bytes stored under the content address of ``label``."""
    text = "artifact %s\n" % label
    if label.startswith("command-"):
        flags = SESSION_FLAGS[label[len("command-"):]]
        if flags:
            text += " ".join(flags) + "\n"
    if label in OFF_JOURNALS:
        text += MARKER + "\n"
    return text.encode("utf-8")


def _h(label):
    return hashlib.sha256(_blob(label)).hexdigest()


def _labels():
    labels = [
        "archive", "pack-base", "manifest-start", "manifest-edited", "settings-kept",
        "forest-submission", "forest-report", "launcher-identity", "disabled-backend-proof",
        "closure-finite-residency", "closure-distant-cave-edit-omitted",
        "closure-residency-cap", "closure-fixture-note",
        "closure-candidate-hang", "closure-second-hang",
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
    """Return a synthetic v2 bundle; validity does not establish native execution."""
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
        "save_flow": {
            "create_session": "create-world",
            "edit_session": "edit-world",
            "save_session": "save-world",
            "restart_session": "restart-world",
            "load_session": "load-world",
            "save_name": "edit-save",
            "loaded_sha256": [_h("manifest-edited"), _h("settings-kept")],
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
        # Synthetic closures exercise format and integrity only. Humans review actual
        # native completion records; these fixture bytes establish no qualification.
        "limitations": [
            {"blocks_release": True, "closure_sha256": _h("closure-finite-residency"),
             "id": "finite-residency", "status": "closed"},
            {"blocks_release": True, "closure_sha256": _h("closure-distant-cave-edit-omitted"),
             "id": "distant-cave-edit-omitted", "status": "closed"},
        ],
        "historical": [
            {
                "closure_sha256": None,
                "disposition": "kept as a historical record; never counted as a session exit",
                "id": "application-hang-66604",
                "kind": "application-hang",
                "recurrence_status": "not-observed",
            }
        ],
        "unresolved_diagnostics": [],
    }


def _closed_recurrence_bundle():
    """Return synthetic closure evidence for integrity tests, without native provenance."""
    doc = make_bundle()
    doc["historical"][0]["recurrence_status"] = "closed"
    doc["historical"][0]["closure_sha256"] = _h("closure-candidate-hang")
    return doc


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


def _assert_single_line_error(test, text):
    error_lines = [line for line in text.splitlines() if "error:" in line]
    test.assertEqual(len(error_lines), 1, text)
    test.assertIn("\\n", error_lines[0])
    test.assertIn("\\x1b", error_lines[0])
    test.assertFalse(any(ord(ch) < 32 or ord(ch) == 127 for ch in error_lines[0]))


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
        for name in ("valid.json", "valid-closed-recurrence.json"):
            with self.subTest(fixture=name):
                doc = load_json_file(FIXTURES / name)
                self.assertClean(doc)
                self.assertClean(doc, release=True)

    def test_fixture_is_byte_equal_to_helper_output(self):
        data = (FIXTURES / "valid.json").read_bytes()
        expected = (json.dumps(make_bundle(), indent=2, sort_keys=True) + "\n").encode("utf-8")
        self.assertEqual(data, expected)
        self.assertNotIn(b"\r", data)

    def test_closed_fixture_matches_synthetic_closure_helper(self):
        expected = (json.dumps(_closed_recurrence_bundle(), indent=2, sort_keys=True) + "\n").encode("utf-8")
        self.assertEqual((FIXTURES / "valid-closed-recurrence.json").read_bytes(), expected)

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
        doc["schema"] = "luminumbra.game.acceptance-evidence.v3"
        self.assertProblem(doc, "future schema version")

    def test_old_schema_without_recurrence_fields_is_not_defaulted(self):
        doc = self.bundle()
        doc["schema"] = "luminumbra.game.acceptance-evidence.v1"
        del doc["historical"][0]["recurrence_status"]
        del doc["historical"][0]["closure_sha256"]
        self.assertEqual(validate_bundle(doc), ["bundle: unknown schema"])
        self.assertEqual(validate_bundle(doc, release=True), ["bundle: unknown schema"])

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

    def test_marker_problem_refuses_short_markers(self):
        for short in ("a", "LUM-OFF", "1234567"):
            with self.subTest(marker=short):
                self.assertEqual(marker_problem(short), "must be at least 8 characters")
        self.assertIsNone(marker_problem("12345678"))

    def test_marker_problem_refuses_whitespace_only_markers(self):
        for blank in ("    ", "          ", "   "):
            with self.subTest(marker=blank):
                self.assertEqual(marker_problem(blank), "must not be only whitespace")
        self.assertIsNone(marker_problem("  audio off  "))

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

    def test_exit_code_above_uint32_refused_before_normalisation(self):
        doc = self.bundle()
        doc["sessions"][0]["exit_code"] = 4294967296
        self.assertProblem(
            doc, "sessions[0].exit_code: must be an integer from -2147483648 to 4294967295"
        )

    def test_exit_code_below_int32_refused_before_normalisation(self):
        doc = self.bundle()
        doc["sessions"][0]["exit_code"] = -2147483649
        self.assertProblem(
            doc, "sessions[0].exit_code: must be an integer from -2147483648 to 4294967295"
        )

    def test_exit_code_range_edges_are_not_range_refused(self):
        for value in (4294967295, -1, -2147483648):
            with self.subTest(value=value):
                doc = self.bundle()
                doc["sessions"][0]["exit_code"] = value
                self.assertNoProblem(doc, "must be an integer from -2147483648 to 4294967295")

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

    def test_audio_null_with_flag_refused(self):
        doc = self.bundle()
        doc["sessions"][0]["no_audio_flag"] = True
        self.assertProblem(doc, "sessions[0]: audio_mode null requires no_audio_flag false")

    def test_audio_null_with_flag_refused_in_refusal_session(self):
        doc = self.bundle()
        doc["sessions"][REFUSAL_SAVE]["no_audio_flag"] = True
        self.assertProblem(doc, "sessions[7]: audio_mode null requires no_audio_flag false")

    def test_audio_off_with_flag_is_consistent(self):
        doc = self.bundle()
        self.assertNoProblem(doc, "audio_mode null requires")
        self.assertNoProblem(doc, "audio_mode off requires")
        self.assertClean(doc)

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


class SaveFlowTest(_BundleTest):
    def test_save_flow_is_required(self):
        doc = self.bundle()
        del doc["save_flow"]
        self.assertProblem(doc, "bundle: missing key 'save_flow'")

    def test_every_pair_of_stages_must_be_in_order(self):
        for first in range(5):
            for second in range(first + 1, 5):
                with self.subTest(first=first, second=second):
                    doc = self.bundle()
                    sessions = doc["sessions"]
                    sessions[first], sessions[second] = sessions[second], sessions[first]
                    self.assertEqual(validate_bundle(doc), [
                        "save_flow: sessions must occur in create -> edit -> save -> restart -> load order",
                    ])

    def test_other_sessions_can_be_interleaved(self):
        doc = self.bundle()
        doc["sessions"].insert(2, doc["sessions"].pop(6))
        self.assertClean(doc, release=True)

    def test_flow_cannot_use_a_later_restart_after_load(self):
        doc = self.bundle()
        doc["save_flow"]["restart_session"] = "restart-no-audio"
        self.assertProblem(doc, "save_flow: sessions must occur in create -> edit -> save -> restart -> load order")

    def test_session_links_are_required_existing_and_of_the_right_kind(self):
        for kind in acceptance.SAVE_FLOW_KINDS:
            key = kind + "_session"
            with self.subTest(kind=kind):
                doc = self.bundle()
                del doc["save_flow"][key]
                self.assertProblem(doc, "save_flow: missing key '%s'" % key)
                for bad in ("absent", None, [], True):
                    doc = self.bundle()
                    doc["save_flow"][key] = bad
                    self.assertProblem(doc, "save_flow.%s: unknown session" % key)
                doc = self.bundle()
                doc["save_flow"][key] = "switch-world-a"
                self.assertProblem(doc, "save_flow.%s: session 'switch-world-a' must be a %s session" % (key, kind))

    def test_unknown_flow_key_is_refused(self):
        doc = self.bundle()
        doc["save_flow"]["extra"] = 1
        self.assertProblem(doc, "save_flow: unknown key 'extra'")

    def test_unknown_save_is_refused(self):
        for bad in ("absent", None, []):
            with self.subTest(name=bad):
                doc = self.bundle()
                doc["save_flow"]["save_name"] = bad
                self.assertProblem(doc, "save_flow.save_name: unknown save")

    def test_flow_must_cover_an_edited_save(self):
        doc = self.bundle()
        doc["save_flow"]["save_name"] = "save-refusal"
        doc["save_flow"]["loaded_sha256"] = [_h("manifest-edited")]
        self.assertEqual(validate_bundle(doc), [
            "save_flow: save flow must reference a save with an edited file",
        ])

    def test_load_hash_must_match_save_hash_for_every_file(self):
        for index in range(2):
            with self.subTest(file=index):
                doc = self.bundle()
                doc["save_flow"]["loaded_sha256"][index] = _h("manifest-start")
                self.assertProblem(doc, "save_flow.loaded_sha256[%d]: load hash must equal the hash recorded at save" % index)

    def test_load_hashes_are_required_well_formed_and_complete(self):
        for hashes, problem in (
            (None, "must be a list"),
            ([], "needs at least 1 item(s)"),
            ([_h("manifest-edited")], "needs one hash per file"),
            ([_h("manifest-edited"), _h("settings-kept"), _h("manifest-start")], "needs one hash per file"),
            (["bad", _h("settings-kept")], "must be 64 lowercase hex characters"),
        ):
            with self.subTest(hashes=hashes):
                doc = self.bundle()
                doc["save_flow"]["loaded_sha256"] = hashes
                self.assertProblem(doc, problem)


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
        doc["limitations"].append({"blocks_release": True, "closure_sha256": None,
                                   "id": "residency-cap", "status": "open"})
        self.assertProblem(doc, "limitations[2]: open blocking limitation is refused in release mode",
                           release=True)

    def test_open_blocking_limitation_accepted_outside_release(self):
        doc = self.bundle()
        doc["limitations"].append({"blocks_release": True, "closure_sha256": None,
                                   "id": "residency-cap", "status": "open"})
        self.assertNoProblem(doc, "open blocking limitation", release=False)

    def test_closed_blocking_limitation_accepted_in_release(self):
        doc = self.bundle()
        doc["limitations"].append({"blocks_release": True, "closure_sha256": _h("closure-residency-cap"),
                                   "id": "residency-cap", "status": "closed"})
        self.assertClean(doc, release=True)

    def test_limitation_status_must_be_open_or_closed(self):
        doc = self.bundle()
        doc["limitations"][0]["status"] = "pending"
        self.assertProblem(doc, "limitations[0].status: must be open or closed")

    def test_closed_limitation_without_closure_hash_refused(self):
        doc = self.bundle()
        doc["limitations"][0]["closure_sha256"] = None
        self.assertProblem(doc, "limitations[0].closure_sha256: closed limitation needs closure evidence")
        self.assertProblem(doc, "limitations[0].closure_sha256: closed limitation needs closure evidence",
                           release=True)

    def test_closed_limitation_missing_closure_key_refused(self):
        doc = self.bundle()
        del doc["limitations"][1]["closure_sha256"]
        self.assertProblem(doc, "limitations[1]: missing key 'closure_sha256'")

    def test_closed_limitation_closure_hash_must_be_hex(self):
        doc = self.bundle()
        doc["limitations"][0]["closure_sha256"] = _h("closure-finite-residency").upper()
        self.assertProblem(doc, "limitations[0].closure_sha256: must be 64 lowercase hex characters")

    def test_open_limitation_with_closure_hash_refused(self):
        doc = self.bundle()
        doc["limitations"][0]["status"] = "open"
        self.assertProblem(doc, "limitations[0].closure_sha256: open limitation must have a null closure_sha256")
        self.assertProblem(doc, "limitations[0].closure_sha256: open limitation must have a null closure_sha256",
                           release=True)

    def test_status_flip_alone_cannot_pass(self):
        doc = self.bundle()
        doc["limitations"][0]["status"] = "open"
        self.assertProblem(doc, "limitations[0].closure_sha256: open limitation must have a null closure_sha256")
        doc = self.bundle()
        doc["limitations"][0]["closure_sha256"] = None
        self.assertProblem(doc, "limitations[0].closure_sha256: closed limitation needs closure evidence")
        doc = self.bundle()
        doc["limitations"][0]["status"] = "open"
        doc["limitations"][0]["closure_sha256"] = None
        self.assertNoProblem(doc, "limitations[0].closure_sha256", release=False)
        self.assertProblem(doc, "limitations[0]: open blocking limitation is refused in release mode",
                           release=True)

    def test_closed_limitation_closure_hash_is_an_artifact_hash(self):
        doc = self.bundle()
        self.assertIn((_h("closure-finite-residency"), "limitations[0].closure_sha256"),
                      artifact_hashes(doc))
        self.assertIn((_h("closure-distant-cave-edit-omitted"), "limitations[1].closure_sha256"),
                      artifact_hashes(doc))

    def test_closure_equal_to_package_archive_refused(self):
        doc = self.bundle()
        doc["limitations"][0]["closure_sha256"] = doc["package"]["archive_sha256"]
        self.assertProblem(
            doc, "limitations[0].closure_sha256: closure evidence must differ from package.archive_sha256"
        )
        self.assertProblem(
            doc, "limitations[0].closure_sha256: closure evidence must differ from package.archive_sha256",
            release=True,
        )

    def test_closure_shared_between_limitations_refused(self):
        doc = self.bundle()
        doc["limitations"][1]["closure_sha256"] = doc["limitations"][0]["closure_sha256"]
        self.assertProblem(
            doc, "limitations[1].closure_sha256: closure evidence must differ from limitations[0].closure_sha256"
        )

    def test_distinct_closure_hashes_accepted(self):
        doc = self.bundle()
        self.assertNoProblem(doc, "must differ from", release=True)

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
        doc["limitations"][0]["closure_sha256"] = None
        self.assertProblem(doc, "limitations[0]: open blocking limitation is refused in release mode",
                           release=True)
        self.assertNoProblem(doc, "open blocking limitation", release=False)

    def test_open_distant_cave_edit_limitation_refused_in_release(self):
        doc = self.bundle()
        doc["limitations"][1]["status"] = "open"
        doc["limitations"][1]["closure_sha256"] = None
        self.assertProblem(doc, "limitations[1]: open blocking limitation is refused in release mode",
                           release=True)
        self.assertNoProblem(doc, "open blocking limitation", release=False)

    def test_open_limitation_that_does_not_block_is_allowed_in_release(self):
        doc = self.bundle()
        doc["limitations"].append({"blocks_release": False, "closure_sha256": None,
                                   "id": "fixture-note", "status": "open"})
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
        doc["limitations"].append({"blocks_release": False, "closure_sha256": _h("closure-fixture-note"),
                                   "id": "fixture-note", "status": "closed"})
        self.assertClean(doc, release=True)


class RecurrenceAndDiagnosticsTest(_BundleTest):
    def test_explicit_not_observed_and_closed_are_structurally_valid(self):
        for doc in (make_bundle(), _closed_recurrence_bundle()):
            for release in (False, True):
                with self.subTest(status=doc["historical"][0]["recurrence_status"], release=release):
                    self.assertClean(doc, release=release)

    def test_candidate_open_recurrence_refused_regardless_of_original_disposition(self):
        doc = self.bundle()
        doc["historical"][0]["disposition"] = "original incident owner-closed after non-reproduction"
        doc["historical"][0]["recurrence_status"] = "open"
        original = copy.deepcopy(doc)
        self.assertClean(doc)
        self.assertEqual(validate_bundle(doc, release=True), [
            "historical[0].recurrence_status: open recurrence is refused in release mode",
        ])
        self.assertEqual(doc, original)

    def test_historical_required_fields_have_no_defaults(self):
        for key in ("recurrence_status", "closure_sha256"):
            for release in (False, True):
                with self.subTest(key=key, release=release):
                    doc = self.bundle()
                    del doc["historical"][0][key]
                    self.assertEqual(validate_bundle(doc, release=release), [
                        "historical[0]: missing key '%s'" % key,
                    ])

    def test_missing_and_malformed_historical_inventory_refused(self):
        doc = self.bundle()
        del doc["historical"]
        for release in (False, True):
            self.assertEqual(validate_bundle(doc, release=release), ["bundle: missing key 'historical'"])
        for value, problem in (
            (None, "historical: must be a list"),
            ({}, "historical: must be a list"),
            ([None], "historical[0]: not an object"),
            ([[]], "historical[0]: not an object"),
        ):
            for release in (False, True):
                with self.subTest(value=value, release=release):
                    doc = self.bundle()
                    doc["historical"] = value
                    self.assertEqual(validate_bundle(doc, release=release), [problem])

    def test_historical_unknown_keys_refused(self):
        doc = self.bundle()
        doc["historical"][0]["reviewed"] = True
        for release in (False, True):
            self.assertEqual(validate_bundle(doc, release=release), [
                "historical[0]: unknown key 'reviewed'",
            ])

    def test_recurrence_status_requires_exact_enum_string(self):
        for status in (None, True, 0, [], {}, "", "pending", "Closed", "not_observed"):
            for release in (False, True):
                with self.subTest(status=status, release=release):
                    doc = self.bundle()
                    doc["historical"][0]["recurrence_status"] = status
                    self.assertEqual(validate_bundle(doc, release=release), [
                        "historical[0].recurrence_status: must be one of not-observed, open, closed",
                    ])

    def test_closed_recurrence_requires_nonnull_valid_hash(self):
        for closure in (None, "", "abc", "A" * 64, "g" * 64, 4, True, [], {}):
            for release in (False, True):
                with self.subTest(closure=closure, release=release):
                    doc = _closed_recurrence_bundle()
                    doc["historical"][0]["closure_sha256"] = closure
                    reason = ("closed recurrence needs closure evidence" if closure is None
                              else "must be 64 lowercase hex characters")
                    self.assertEqual(validate_bundle(doc, release=release), [
                        "historical[0].closure_sha256: " + reason,
                    ])

    def test_closed_recurrence_missing_closure_key_refused(self):
        doc = _closed_recurrence_bundle()
        del doc["historical"][0]["closure_sha256"]
        for release in (False, True):
            self.assertEqual(validate_bundle(doc, release=release), [
                "historical[0]: missing key 'closure_sha256'",
            ])

    def test_unclosed_recurrences_require_explicit_null_closure(self):
        for status in ("not-observed", "open"):
            for closure in (_h("closure-candidate-hang"), "", True, [], {}):
                for release in (False, True):
                    with self.subTest(status=status, closure=closure, release=release):
                        doc = self.bundle()
                        doc["historical"][0].update(recurrence_status=status, closure_sha256=closure)
                        expected = [
                            "historical[0].closure_sha256: %s recurrence must have a null closure_sha256"
                            % status,
                        ]
                        if status == "open" and release:
                            expected.append(
                                "historical[0].recurrence_status: open recurrence is refused in release mode"
                            )
                        self.assertEqual(validate_bundle(doc, release=release), expected)

    def test_historical_closure_must_differ_from_archive_and_limitation_closures(self):
        conflicts = [
            ("package.archive_sha256", _h("archive")),
            ("limitations[0].closure_sha256", _h("closure-finite-residency")),
            ("limitations[1].closure_sha256", _h("closure-distant-cave-edit-omitted")),
        ]
        for location, digest in conflicts:
            for release in (False, True):
                with self.subTest(location=location, release=release):
                    doc = _closed_recurrence_bundle()
                    doc["historical"][0]["closure_sha256"] = digest
                    self.assertEqual(validate_bundle(doc, release=release), [
                        "historical[0].closure_sha256: closure evidence must differ from " + location,
                    ])

    def test_historical_closures_are_unique_across_records(self):
        doc = _closed_recurrence_bundle()
        second = dict(doc["historical"][0], id="second-hang")
        doc["historical"].append(second)
        for release in (False, True):
            self.assertEqual(validate_bundle(doc, release=release), [
                "historical[1].closure_sha256: closure evidence must differ from historical[0].closure_sha256",
            ])
        second["closure_sha256"] = _h("closure-second-hang")
        self.assertClean(doc, release=True)

    def test_closure_reuse_of_a_journal_or_other_nonclosure_artifact_is_allowed(self):
        for digest in (_h("journal-create-world"), _h("forest-report")):
            with self.subTest(digest=digest):
                doc = _closed_recurrence_bundle()
                doc["historical"][0]["closure_sha256"] = digest
                self.assertClean(doc, release=True)

    def test_closed_historical_record_never_overrides_hang_exit_refusal(self):
        for code in (HANG_UNSIGNED, HANG_SIGNED):
            for index in range(len(SESSION_IDS)):
                for release in (False, True):
                    with self.subTest(code=code, session=index, release=release):
                        doc = _closed_recurrence_bundle()
                        doc["sessions"][index]["exit_code"] = code
                        self.assertEqual(validate_bundle(doc, release=release), [
                            "sessions[%d].exit_code: 0xCFFFFFFF is the application hang signature "
                            "and is refused in every session" % index,
                        ])

    def test_every_nonempty_diagnostics_inventory_blocks_release_and_is_preserved(self):
        for diagnostics in (["hang investigation pending"], [""], ["", ""], [" "]):
            with self.subTest(diagnostics=diagnostics):
                doc = self.bundle()
                doc["unresolved_diagnostics"] = diagnostics
                original = copy.deepcopy(doc)
                self.assertClean(doc)
                self.assertEqual(validate_bundle(doc, release=True), [
                    "unresolved_diagnostics: nonempty unresolved diagnostics are refused in release mode",
                ])
                self.assertEqual(doc, original)

    def test_diagnostics_must_be_a_list_in_both_modes(self):
        for diagnostics in (None, "", {}, False):
            for release in (False, True):
                with self.subTest(diagnostics=diagnostics, release=release):
                    doc = self.bundle()
                    doc["unresolved_diagnostics"] = diagnostics
                    self.assertEqual(validate_bundle(doc, release=release), [
                        "unresolved_diagnostics: must be a list",
                    ])

    def test_diagnostics_missing_key_refused_in_both_modes(self):
        doc = self.bundle()
        del doc["unresolved_diagnostics"]
        for release in (False, True):
            self.assertEqual(validate_bundle(doc, release=release), [
                "bundle: missing key 'unresolved_diagnostics'",
            ])

    def test_malformed_diagnostic_items_are_type_checked_and_block_release(self):
        for item in (None, False, 3, [], {}):
            with self.subTest(item=item):
                doc = self.bundle()
                doc["unresolved_diagnostics"] = [item]
                self.assertEqual(validate_bundle(doc), ["unresolved_diagnostics[0]: must be a string"])
                self.assertEqual(validate_bundle(doc, release=True), [
                    "unresolved_diagnostics: nonempty unresolved diagnostics are refused in release mode",
                    "unresolved_diagnostics[0]: must be a string",
                ])


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
                    r"x=\\server\share\run", r"<\\server\share\run>", r"it's '\\server\share\run'",
                    "see `" + r"\\server\share\run" + "`", "_" + r"\\server\share\run" + "_",
                    "**" + r"//server/share/run" + "**", "~" + r"\\server\share\run"):
            with self.subTest(value=bad):
                doc = self.bundle()
                doc["historical"][0]["disposition"] = bad
                self.assertProblem(doc, "historical[0].disposition: local absolute path shape is not allowed")

    def test_unc_path_inside_a_word_is_not_a_boundary(self):
        doc = self.bundle()
        doc["historical"][0]["disposition"] = r"run1\\server\share\run"
        self.assertNoProblem(doc, "local absolute path shape")

    def test_colon_prefixed_backslash_unc_refused(self):
        bad = "see:" + "\\" * 2 + "server" + "\\" + "share" + "\\" + "run"
        doc = self.bundle()
        doc["historical"][0]["disposition"] = bad
        self.assertProblem(doc, "historical[0].disposition: local absolute path shape is not allowed")

    def test_colon_prefixed_device_path_refused(self):
        bad = "note:" + "\\" * 2 + "?" + "\\" + "device"
        doc = self.bundle()
        doc["historical"][0]["disposition"] = bad
        self.assertProblem(doc, "historical[0].disposition: local absolute path shape is not allowed")

    def test_colon_prefixed_forward_slash_unc_stays_accepted(self):
        doc = self.bundle()
        doc["historical"][0]["disposition"] = "see://server/share"
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
    def test_null_historical_closures_are_not_artifact_references(self):
        for status in ("not-observed", "open"):
            doc = make_bundle()
            doc["historical"][0]["recurrence_status"] = status
            self.assertFalse(any(location.startswith("historical[") for _, location in artifact_hashes(doc)))
            self.assertEqual(artifact_count(doc), artifact_count(make_bundle()))

    def test_historical_closure_inventory_locations_and_distinct_counts(self):
        doc = _closed_recurrence_bundle()
        doc["historical"].append(dict(
            doc["historical"][0], id="second-hang", closure_sha256=_h("closure-second-hang"),
        ))
        self.assertEqual(artifact_hashes(doc)[-2:], [
            (_h("closure-candidate-hang"), "historical[0].closure_sha256"),
            (_h("closure-second-hang"), "historical[1].closure_sha256"),
        ])
        self.assertEqual(artifact_count(doc), artifact_count(make_bundle()) + 2)
        doc["historical"][0]["closure_sha256"] = _h("journal-create-world")
        self.assertEqual(artifact_count(doc), artifact_count(make_bundle()) + 1)
        self.assertIn((_h("journal-create-world"), "historical[0].closure_sha256"), artifact_hashes(doc))

    def test_artifact_hashes_cover_every_named_hash(self):
        doc = make_bundle()
        digests = {digest for digest, _location in artifact_hashes(doc)}
        expected = {
            _h("archive"), _h("pack-base"), _h("manifest-start"), _h("manifest-edited"), _h("settings-kept"),
            _h("forest-submission"), _h("forest-report"), _h("launcher-identity"),
            _h("disabled-backend-proof"), _h("closure-finite-residency"),
            _h("closure-distant-cave-edit-omitted"),
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

    def test_command_cannot_supply_its_own_journal_marker(self):
        _store(self.store)
        doc = make_bundle()
        digest = self._put(b"client --no-audio " + MARKER.encode("utf-8") + b"\n")
        doc["sessions"][PREVIEW]["command_sha256"] = digest
        doc["sessions"][PREVIEW]["journal_sha256"] = digest
        expected = [
            "sessions[9].journal_sha256: artifact digest collision between distinct roles "
            "command_sha256 and journal_sha256; must differ from sessions[9].command_sha256",
        ]
        self.assertEqual(validate_bundle(doc), expected)
        with mock.patch("validators.acceptance._scan_file") as scan:
            self.assertEqual(verify_artifacts(doc, str(self.store), MARKER), expected)
        scan.assert_not_called()

    def test_save_file_cannot_double_as_command_evidence(self):
        _store(self.store)
        doc = make_bundle()
        doc["sessions"][1]["command_sha256"] = _h("manifest-edited")
        problems = validate_bundle(doc)
        self.assertTrue(problems)
        self.assertTrue(all("artifact digest collision between distinct roles command_sha256 and save-file" in problem for problem in problems))
        self.assertIn("must differ from sessions[1].command_sha256", problems[0])
        with mock.patch("validators.acceptance._scan_file") as scan:
            self.assertEqual(verify_artifacts(doc, str(self.store), MARKER), problems)
        scan.assert_not_called()

    def test_command_and_journal_roles_cannot_collide_across_sessions(self):
        doc = make_bundle()
        doc["sessions"][1]["journal_sha256"] = doc["sessions"][0]["command_sha256"]
        self.assertEqual(validate_bundle(doc), [
            "sessions[1].journal_sha256: artifact digest collision between distinct roles "
            "command_sha256 and journal_sha256; must differ from sessions[0].command_sha256",
        ])

    def test_same_role_reuse_remains_valid(self):
        _store(self.store)
        doc = make_bundle()
        doc["sessions"][1]["command_sha256"] = doc["sessions"][0]["command_sha256"]
        self.assertEqual(validate_bundle(doc), [])
        self.assertEqual(verify_artifacts(doc, str(self.store), MARKER), [])

    def test_load_hashes_are_artifact_references(self):
        doc = make_bundle()
        digest = _h("unretained-load")
        doc["save_flow"]["loaded_sha256"][0] = digest
        self.assertIn((digest, "save_flow.loaded_sha256[0]"), artifact_hashes(doc))
        _store(self.store)
        self.assertEqual(verify_artifacts(doc, str(self.store), MARKER), [
            "save_flow.loaded_sha256[0]: artifact %s missing" % digest,
        ])

    def test_retained_hash_correct_historical_closures_verify_without_native_provenance(self):
        doc = _closed_recurrence_bundle()
        doc["historical"].append(dict(
            doc["historical"][0], id="second-hang", closure_sha256=_h("closure-second-hang"),
        ))
        _store(self.store)
        self.assertEqual(validate_bundle(doc, release=True), [])
        self.assertEqual(verify_artifacts(doc, str(self.store), MARKER), [])

    def test_missing_historical_closure_artifacts_report_each_json_path(self):
        doc = _closed_recurrence_bundle()
        first = _h("closure-candidate-hang")
        second = _h("closure-second-hang")
        doc["historical"].append(dict(doc["historical"][0], id="second-hang", closure_sha256=second))
        _store(self.store, skip=frozenset([first, second]))
        self.assertEqual(verify_artifacts(doc, str(self.store), MARKER), [
            "historical[0].closure_sha256: artifact %s missing" % first,
            "historical[1].closure_sha256: artifact %s missing" % second,
        ])

    def test_mismatched_historical_closure_artifact_reports_json_path(self):
        doc = _closed_recurrence_bundle()
        _store(self.store)
        digest = _h("closure-candidate-hang")
        (self.store / "sha256" / digest).write_bytes(b"tampered closure\n")
        self.assertEqual(verify_artifacts(doc, str(self.store), MARKER), [
            "historical[0].closure_sha256: artifact %s mismatch" % digest,
        ])

    def test_reused_artifact_is_hashed_once_and_reports_first_reference(self):
        doc = _closed_recurrence_bundle()
        digest = _h("journal-create-world")
        doc["historical"][0]["closure_sha256"] = digest
        _store(self.store)
        with mock.patch("validators.acceptance._scan_file", wraps=acceptance._scan_file) as scan:
            self.assertEqual(verify_artifacts(doc, str(self.store), MARKER), [])
        self.assertEqual(sum(Path(call.args[0]).name == digest for call in scan.call_args_list), 1)
        (self.store / "sha256" / digest).unlink()
        self.assertEqual(verify_artifacts(doc, str(self.store), MARKER), [
            "sessions[0].journal_sha256: artifact %s missing" % digest,
        ])

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

    def _put(self, data):
        """Store DATA under its content address in the test store and return the digest."""
        (self.store / "sha256").mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(data).hexdigest()
        (self.store / "sha256" / digest).write_bytes(data)
        return digest

    def _preview_command_problems(self, content):
        """Verify a bundle whose audio-off preview command artifact holds CONTENT."""
        doc = make_bundle()
        _store(self.store)
        doc["sessions"][PREVIEW]["command_sha256"] = self._put(content)
        return verify_artifacts(doc, str(self.store), MARKER)

    def test_missing_closure_artifact_reported_with_location(self):
        doc = make_bundle()
        closure = _h("closure-finite-residency")
        _store(self.store, skip=frozenset([closure]))
        self.assertEqual(
            verify_artifacts(doc, str(self.store), MARKER),
            ["limitations[0].closure_sha256: artifact %s missing" % closure],
        )

    def test_audio_off_command_without_no_audio_reported(self):
        self.assertEqual(
            self._preview_command_problems(b"artifact command-preview-launch\n--enable-audio\n"),
            ["sessions[9].command_sha256: audio-off command lacks --no-audio"],
        )

    def test_no_audio_inside_a_longer_argument_is_refused(self):
        for text in (b"--no-audio-x", b"--no-audiofoo", b"--no-audio1", b"--no-audio-",
                     b"--no-audio--", b"x--no-audio", b"0--no-audio", b"ab--no-audioZ",
                     b"--no-audio=1", b"--no-audio.exe", b"--no-audio/x", b"/--no-audio",
                     b"(--no-audio)", b"_--no-audio_", b"--no-audio:1", b"--no-audio;",
                     b"C:\\tools\\--no-audio", b"\t--no-audio=1"):
            with self.subTest(text=text):
                self.assertEqual(
                    self._preview_command_problems(b"artifact command-preview-launch\n" + text + b"\n"),
                    ["sessions[9].command_sha256: audio-off command lacks --no-audio"],
                )

    def test_no_audio_as_its_own_argument_is_accepted(self):
        for text in (b"--no-audio", b"--no-audio\n", b" --no-audio", b"\t--no-audio\t",
                     b'"--no-audio"', b"'--no-audio'", b'"--no-audio" x',
                     b"\x00--no-audio\x00", b"\r\n--no-audio\r\n", b"--enable-audio --no-audio"):
            with self.subTest(text=text):
                self.assertEqual(
                    self._preview_command_problems(b"artifact command-preview-launch\n" + text + b"\n"),
                    [],
                )

    def _precedence_command_problems(self, content):
        """Verify a bundle whose precedence session command artifact holds CONTENT."""
        doc = make_bundle()
        _store(self.store)
        doc["sessions"][NO_AUDIO_RESTART]["command_sha256"] = self._put(content)
        return verify_artifacts(doc, str(self.store), MARKER)

    def test_quoted_fragment_is_one_argument_and_refused_for_precedence(self):
        self.assertEqual(
            self._precedence_command_problems(b'artifact client "--enable-audio --no-audio"\n'),
            [
                "sessions[10].command_sha256: audio-off command lacks --no-audio",
                "startup_checks.no_audio_precedence_session: command lacks --enable-audio",
                "startup_checks.no_audio_precedence_session: command lacks --no-audio",
            ],
        )

    def test_quoted_flags_as_their_own_arguments_are_accepted_for_precedence(self):
        for text in (b'"--enable-audio" "--no-audio"', b"'--enable-audio' '--no-audio'"):
            with self.subTest(text=text):
                self.assertEqual(
                    self._precedence_command_problems(b"artifact client " + text + b"\n"),
                    [],
                )

    def test_unbalanced_quote_in_command_is_a_problem(self):
        self.assertEqual(
            self._preview_command_problems(b'artifact command-preview-launch\n"--no-audio\n'),
            ["sessions[9].command_sha256: command artifact has unbalanced quotes"],
        )

    def test_command_that_is_not_utf8_is_a_problem(self):
        self.assertEqual(
            self._preview_command_problems(b"artifact command-preview-launch\n\xff--no-audio\n"),
            ["sessions[9].command_sha256: command artifact is not UTF-8"],
        )

    def test_command_larger_than_64_kib_is_a_problem(self):
        prefix = b"artifact command-preview-launch --no-audio\n"
        self.assertEqual(
            self._preview_command_problems(prefix + b"a" * (65536 - len(prefix))),
            [],
        )
        self.assertEqual(
            self._preview_command_problems(prefix + b"a" * (65536 - len(prefix) + 1)),
            ["sessions[9].command_sha256: command artifact is larger than 65536 bytes"],
        )

    def test_marker_straddling_the_chunk_boundary_is_found(self):
        doc = make_bundle()
        _store(self.store)
        # The marker starts at offset 65536 - 3, so its first three bytes are in the first chunk.
        doc["sessions"][PREVIEW]["journal_sha256"] = self._put(
            b"a" * 65533 + MARKER.encode("utf-8") + b"\n"
        )
        self.assertEqual(verify_artifacts(doc, str(self.store), MARKER), [])
        doc["sessions"][PREVIEW]["journal_sha256"] = self._put(
            b"a" * 65533 + MARKER[:-1].encode("utf-8") + b"\n"
        )
        self.assertEqual(
            verify_artifacts(doc, str(self.store), MARKER),
            ["sessions[9].journal_sha256: audio-off journal lacks the audio-off marker"],
        )

    def test_precedence_command_needs_both_flags(self):
        doc = make_bundle()
        _store(self.store)
        doc["sessions"][NO_AUDIO_RESTART]["command_sha256"] = self._put(
            b"artifact command-restart-no-audio\n--no-audio\n"
        )
        self.assertEqual(
            verify_artifacts(doc, str(self.store), MARKER),
            ["startup_checks.no_audio_precedence_session: command lacks --enable-audio"],
        )
        doc["sessions"][NO_AUDIO_RESTART]["command_sha256"] = self._put(
            b"artifact command-restart-no-audio\n--enable-audio\n"
        )
        self.assertEqual(
            verify_artifacts(doc, str(self.store), MARKER),
            [
                "sessions[10].command_sha256: audio-off command lacks --no-audio",
                "startup_checks.no_audio_precedence_session: command lacks --no-audio",
            ],
        )

    def test_tampered_audio_off_command_reports_mismatch_only(self):
        doc = make_bundle()
        _store(self.store)
        digest = _h("command-preview-launch")
        (self.store / "sha256" / digest).write_bytes(b"artifact tampered\n")
        self.assertEqual(
            verify_artifacts(doc, str(self.store), MARKER),
            ["sessions[9].command_sha256: artifact %s mismatch" % digest],
        )


class CommandDeclarationTest(unittest.TestCase):
    """Each session's command must agree with its declared no_audio_flag."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Path(self._tmp.name) / "store"

    def tearDown(self):
        self._tmp.cleanup()

    def _command(self, index, content):
        """Return a bundle whose session INDEX names a command artifact holding CONTENT."""
        (self.store / "sha256").mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(content).hexdigest()
        (self.store / "sha256" / digest).write_bytes(content)
        doc = make_bundle()
        doc["sessions"][index]["command_sha256"] = digest
        return doc

    def test_helper_flags_agree_with_declared_no_audio_flags(self):
        for session in make_bundle()["sessions"]:
            with self.subTest(session=session["id"]):
                flags = SESSION_FLAGS[session["id"]]
                self.assertEqual("--no-audio" in flags, session["no_audio_flag"])
                self.assertEqual("--enable-audio" in flags, session["id"] == "restart-no-audio")

    def test_helper_bundle_verifies_with_declarations_in_place(self):
        _store(self.store)
        self.assertEqual(verify_artifacts(make_bundle(), str(self.store), MARKER), [])

    def test_false_flag_session_carrying_no_audio_refused(self):
        _store(self.store)
        doc = self._command(0, b"artifact command-create-world\n--no-audio\n")
        self.assertEqual(
            verify_artifacts(doc, str(self.store), MARKER),
            ["sessions[0].command_sha256: command contains --no-audio but no_audio_flag is false"],
        )

    def test_true_flag_null_session_lacking_no_audio_refused(self):
        _store(self.store)
        doc = make_bundle()
        doc["sessions"][1]["no_audio_flag"] = True
        self.assertEqual(
            verify_artifacts(doc, str(self.store), MARKER),
            ["sessions[1].command_sha256: command lacks --no-audio but no_audio_flag is true"],
        )

    def test_enable_audio_on_a_null_session_is_refused(self):
        _store(self.store)
        doc = self._command(1, b"artifact command-edit-world\n--enable-audio\n")
        self.assertEqual(
            verify_artifacts(doc, str(self.store), MARKER),
            ["sessions[1].command_sha256: command enables audio but audio_mode is null"],
        )

    def test_quoted_enable_audio_on_a_null_session_is_refused(self):
        _store(self.store)
        doc = self._command(1, b"artifact command-edit-world \"--enable-audio\"\n")
        self.assertEqual(
            verify_artifacts(doc, str(self.store), MARKER),
            ["sessions[1].command_sha256: command enables audio but audio_mode is null"],
        )

    def test_enable_audio_glued_to_other_text_is_not_a_flag(self):
        _store(self.store)
        doc = self._command(1, b"artifact command-edit-world\n--enable-audio=1 x--enable-audio\n")
        self.assertEqual(verify_artifacts(doc, str(self.store), MARKER), [])

    def test_null_audio_startup_command_carrying_enable_audio_refused(self):
        _store(self.store)
        doc = self._command(3, b"artifact command-restart-world\n--enable-audio\n")
        self.assertEqual(
            verify_artifacts(doc, str(self.store), MARKER),
            [
                "sessions[3].command_sha256: command enables audio but audio_mode is null",
                "startup_checks.null_audio_nonzero_master_session: command carries an audio flag",
            ],
        )

    def test_null_audio_startup_command_carrying_no_audio_reports_both(self):
        _store(self.store)
        doc = self._command(3, b"artifact command-restart-world\n--no-audio\n")
        self.assertEqual(
            verify_artifacts(doc, str(self.store), MARKER),
            [
                "sessions[3].command_sha256: command contains --no-audio but no_audio_flag is false",
                "startup_checks.null_audio_nonzero_master_session: command carries an audio flag",
            ],
        )

    def test_unverified_startup_command_is_not_judged(self):
        _store(self.store, skip=frozenset([_h("command-restart-world")]))
        self.assertEqual(
            verify_artifacts(make_bundle(), str(self.store), MARKER),
            ["sessions[3].command_sha256: artifact %s missing" % _h("command-restart-world")],
        )


class RegistryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_schema_is_registered(self):
        schemas, _globs = discover()
        self.assertEqual(SCHEMA_ID, "luminumbra.game.acceptance-evidence.v2")
        self.assertIn(SCHEMA_ID, schemas)
        self.assertNotIn("luminumbra.game.acceptance-evidence.v1", schemas)

    def test_registry_refuses_old_and_future_schema_versions(self):
        target = self.root / "content" / "acceptance"
        target.mkdir(parents=True)
        for version in ("v1", "v3"):
            with self.subTest(version=version):
                doc = make_bundle()
                doc["schema"] = "luminumbra.game.acceptance-evidence." + version
                _write_bundle(target / "bundle.json", doc)
                for release in (False, True):
                    self.assertEqual(validate_content.validate_tree(str(self.root), False, release), [
                        "content/acceptance/bundle.json: schema '%s' is not registered" % doc["schema"],
                    ])

    def test_release_registry_remains_structural_without_an_artifact_store(self):
        target = self.root / "content" / "acceptance"
        target.mkdir(parents=True)
        _write_bundle(target / "bundle.json", _closed_recurrence_bundle())
        self.assertEqual(validate_content.validate_tree(str(self.root), False, True), [])

    def test_registry_release_refuses_open_recurrence_and_every_nonempty_diagnostics_list(self):
        target = self.root / "content" / "acceptance"
        target.mkdir(parents=True)
        cases = [
            ("open recurrence", "historical[0].recurrence_status: open recurrence is refused in release mode"),
            (["pending"], "unresolved_diagnostics: nonempty unresolved diagnostics are refused in release mode"),
            ([""], "unresolved_diagnostics: nonempty unresolved diagnostics are refused in release mode"),
        ]
        for value, problem in cases:
            with self.subTest(value=value):
                doc = make_bundle()
                if value == "open recurrence":
                    doc["historical"][0]["recurrence_status"] = "open"
                else:
                    doc["unresolved_diagnostics"] = value
                _write_bundle(target / "bundle.json", doc)
                self.assertEqual(validate_content.validate_tree(str(self.root), False, False), [])
                self.assertEqual(validate_content.validate_tree(str(self.root), False, True), [
                    "content/acceptance/bundle.json: " + problem,
                ])

    def test_registry_rejects_missing_and_malformed_recurrence_data(self):
        target = self.root / "content" / "acceptance"
        target.mkdir(parents=True)
        for value in (None, []):
            with self.subTest(value=value):
                doc = make_bundle()
                if value is None:
                    del doc["historical"][0]["recurrence_status"]
                    problem = "historical[0]: missing key 'recurrence_status'"
                else:
                    doc["historical"][0]["recurrence_status"] = value
                    problem = "historical[0].recurrence_status: must be one of not-observed, open, closed"
                _write_bundle(target / "bundle.json", doc)
                for release in (False, True):
                    self.assertEqual(validate_content.validate_tree(str(self.root), False, release), [
                        "content/acceptance/bundle.json: " + problem,
                    ])

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

    def test_unknown_argument_control_characters_are_escaped(self):
        code, _out, err = _run_cli([str(self.bundle), "--bad\noption\x1bX"])
        self.assertEqual(code, 2)
        _assert_single_line_error(self, err)

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

    def test_short_audio_off_marker_is_usage_error(self):
        _write_bundle(self.bundle, make_bundle())
        _store(self.store)
        code, _out, err = _run_cli([str(self.bundle), "--artifact-root", str(self.store),
                                    "--audio-off-marker", "LUM-OFF"])
        self.assertEqual(code, 2)
        self.assertIn("--audio-off-marker: must be at least 8 characters", err)

    def test_whitespace_audio_off_marker_is_usage_error(self):
        _write_bundle(self.bundle, make_bundle())
        _store(self.store)
        code, _out, err = _run_cli([str(self.bundle), "--artifact-root", str(self.store),
                                    "--audio-off-marker", "        "])
        self.assertEqual(code, 2)
        self.assertIn("--audio-off-marker: must not be only whitespace", err)

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
        # Synthetic bytes validate integrity only; this is no native qualification.
        _write_bundle(self.bundle, make_bundle())
        _store(self.store)
        code, out, _err = _run_cli([str(self.bundle), "--artifact-root", str(self.store),
                                    "--audio-off-marker", MARKER, "--release"])
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("artifacts verified: "), out)

    def test_release_refuses_recurrence_and_diagnostics_with_complete_artifacts(self):
        _store(self.store)
        for value in ("open", ["pending"], [""]):
            with self.subTest(value=value):
                doc = make_bundle()
                if value == "open":
                    doc["historical"][0]["recurrence_status"] = value
                    problem = "historical[0].recurrence_status: open recurrence is refused in release mode"
                else:
                    doc["unresolved_diagnostics"] = value
                    problem = "unresolved_diagnostics: nonempty unresolved diagnostics are refused in release mode"
                _write_bundle(self.bundle, doc)
                argv = [str(self.bundle), "--artifact-root", str(self.store), "--audio-off-marker", MARKER]
                code, out, err = _run_cli(argv)
                self.assertEqual((code, out, err), (0, "artifacts verified: %d\n" % artifact_count(doc), ""))
                code, out, err = _run_cli(argv + ["--release"])
                self.assertEqual((code, out, err), (1, problem + "\n", ""))

    def test_closed_recurrence_release_requires_actual_hash_correct_closure_artifact(self):
        doc = _closed_recurrence_bundle()
        _write_bundle(self.bundle, doc)
        digest = _h("closure-candidate-hang")
        _store(self.store, skip=frozenset([digest]))
        argv = [str(self.bundle), "--artifact-root", str(self.store), "--audio-off-marker", MARKER, "--release"]
        code, out, err = _run_cli(argv)
        self.assertEqual((code, out, err), (1, "historical[0].closure_sha256: artifact %s missing\n" % digest, ""))
        closure = self.store / "sha256" / digest
        closure.write_bytes(b"wrong closure\n")
        code, out, err = _run_cli(argv)
        self.assertEqual((code, out, err), (1, "historical[0].closure_sha256: artifact %s mismatch\n" % digest, ""))
        closure.write_bytes(_blob("closure-candidate-hang"))
        code, out, err = _run_cli(argv)
        self.assertEqual((code, out, err), (0, "artifacts verified: %d\n" % artifact_count(doc), ""))

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
        ("invalid-old-schema.json", False, "bundle: unknown schema", False),
        ("invalid-missing-historical-recurrence-status.json", False, "historical[0]: missing key 'recurrence_status'", False),
        ("invalid-missing-historical-closure-sha256.json", False, "historical[0]: missing key 'closure_sha256'", False),
        ("invalid-malformed-recurrence.json", False, "historical[0].recurrence_status: must be one of", False),
        ("invalid-unknown-historical-key.json", False, "historical[0]: unknown key 'reviewed'", False),
        ("invalid-open-recurrence.json", True, "historical[0].recurrence_status: open recurrence is refused in release mode", True),
        ("invalid-closed-recurrence-missing-closure.json", False, "historical[0]: missing key 'closure_sha256'", False),
        ("invalid-closed-recurrence-null-closure.json", False, "historical[0].closure_sha256: closed recurrence needs closure evidence", False),
        ("invalid-closed-recurrence-bad-hash.json", False, "historical[0].closure_sha256: must be 64 lowercase hex characters", False),
        ("invalid-historical-archive-closure.json", False, "historical[0].closure_sha256: closure evidence must differ from package.archive_sha256", False),
        ("invalid-cross-collection-closure.json", False, "historical[0].closure_sha256: closure evidence must differ from limitations[0].closure_sha256", False),
        ("invalid-duplicate-historical-closure.json", False, "historical[1].closure_sha256: closure evidence must differ from historical[0].closure_sha256", False),
        ("invalid-not-observed-closure.json", False, "historical[0].closure_sha256: not-observed recurrence must have a null closure_sha256", False),
        ("invalid-unresolved-diagnostics.json", True, "unresolved_diagnostics: nonempty unresolved diagnostics are refused in release mode", True),
        ("invalid-empty-string-diagnostics.json", True, "unresolved_diagnostics: nonempty unresolved diagnostics are refused in release mode", True),
        ("invalid-malformed-diagnostics.json", False, "unresolved_diagnostics[0]: must be a string", False),
        ("invalid-missing-diagnostics.json", False, "bundle: missing key 'unresolved_diagnostics'", False),
    )

    def test_each_invalid_fixture_triggers_its_rule(self):
        for name, release, text, release_only in self.CASES:
            with self.subTest(fixture=name):
                doc = load_json_file(FIXTURES / name)
                problems = validate_bundle(doc, release=release)
                self.assertTrue(any(text in problem for problem in problems), problems)
                expected_rules = [text]
                if name == "invalid-missing-session-kind.json":
                    expected_rules.append("sessions: at least 2 sessions of kind 'switch' are required, found 0")
                if name == "invalid-no-edited-save.json":
                    expected_rules.append("save_flow: save flow must reference a save with an edited file")
                self.assertEqual(len(problems), len(expected_rules), problems)
                for problem, expected in zip(problems, expected_rules):
                    self.assertIn(expected, problem)
                if release_only:
                    self.assertEqual(validate_bundle(doc, release=False), [])

    def test_every_rule_fixture_file_exists(self):
        for name, _release, _text, _release_only in self.CASES:
            self.assertTrue((FIXTURES / name).is_file(), name)

    def test_every_fixture_is_covered_and_versions_are_explicit(self):
        expected = {name for name, _release, _text, _release_only in self.CASES}
        expected.update(("valid.json", "valid-closed-recurrence.json"))
        self.assertEqual({path.name for path in FIXTURES.glob("*.json")}, expected)
        for name in sorted(expected):
            with self.subTest(fixture=name):
                doc = load_json_file(FIXTURES / name)
                version = "v3" if name == "invalid-future-schema.json" else "v2"
                if name == "invalid-old-schema.json":
                    version = "v1"
                self.assertEqual(doc["schema"], "luminumbra.game.acceptance-evidence." + version)


if __name__ == "__main__":
    unittest.main()
