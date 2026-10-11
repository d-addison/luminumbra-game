"""Tests for tools/validate_content.py and the tools/validators registry."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import validate_content  # noqa: E402
from validators import discover  # noqa: E402

SCHEMA = "test.game.thing.v1"
EVIDENCE_SCHEMA = "luminumbra.game-pack-download-verification.v1"
REAL_EVIDENCE = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "tree-small-02-download-verification.json"


def _accept(path, obj, ctx):
    return []


def _raises(path, obj, ctx):
    raise RuntimeError("boom")


class _ContentTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, data):
        path = self.root.joinpath(*rel.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, str):
            data = data.encode("utf-8")
        path.write_bytes(data)

    def validate(self, schemas=None, globs=None, allow_pending=False, release=False):
        return validate_content.validate_tree(
            str(self.root),
            allow_pending,
            release,
            schemas={SCHEMA: _accept} if schemas is None else schemas,
            globs={} if globs is None else globs,
        )


class SchemaEntryTest(_ContentTest):
    def test_registered_schema_passes(self):
        self.write("content/presets/a.json", '{"schema": "%s", "value": 1}\n' % SCHEMA)
        self.assertEqual(self.validate(), [])

    def test_schema_receives_parsed_object_and_path(self):
        seen = []

        def capture(path, obj, ctx):
            seen.append((path, obj))
            return []

        self.write("content/presets/a.json", '{"schema": "%s", "value": 1}\n' % SCHEMA)
        self.assertEqual(self.validate(schemas={SCHEMA: capture}), [])
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], "content/presets/a.json")
        self.assertEqual(seen[0][1]["value"], 1)

    def test_unknown_schema_refused(self):
        self.write("content/presets/a.json", '{"schema": "nope.v1"}\n')
        problems = self.validate()
        self.assertEqual(problems, ["content/presets/a.json: schema 'nope.v1' is not registered"])

    def test_missing_schema_refused(self):
        self.write("content/presets/a.json", '{"value": 1}\n')
        problems = self.validate()
        self.assertEqual(problems, ["content/presets/a.json: missing schema key"])

    def test_non_object_json_refused(self):
        self.write("content/presets/a.json", "[1, 2]\n")
        problems = self.validate()
        self.assertEqual(problems, ["content/presets/a.json: top level must be a JSON object"])

    def test_duplicate_json_keys_refused(self):
        self.write("content/dup.json", '{"schema": "%s", "schema": "%s"}\n' % (SCHEMA, SCHEMA))
        problems = self.validate()
        self.assertTrue(any(problem.startswith("content/dup.json: ") for problem in problems))

    def test_validator_exception_becomes_problem(self):
        self.write("content/presets/a.json", '{"schema": "%s"}\n' % SCHEMA)
        problems = self.validate(schemas={SCHEMA: _raises})
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("content/presets/a.json: validator raised RuntimeError"))

    def test_validator_problems_pass_through(self):
        def reject(path, obj, ctx):
            return [f"{path}: field missing"]

        self.write("content/presets/a.json", '{"schema": "%s"}\n' % SCHEMA)
        self.assertEqual(
            self.validate(schemas={SCHEMA: reject}),
            ["content/presets/a.json: field missing"],
        )


class GlobEntryTest(_ContentTest):
    def test_unrecognised_file_refused(self):
        self.write("content/notes.txt", "hello\n")
        self.assertEqual(self.validate(), ["content/notes.txt: unrecognised content file"])

    def test_glob_receives_text_for_non_json_file(self):
        seen = []

        def glob_fn(path, text, ctx):
            seen.append((path, text))
            return []

        self.write("content/engine/x.traversal", "dur 60\n")
        problems = self.validate(globs={"content/engine/*.traversal": glob_fn})
        self.assertEqual(problems, [])
        self.assertEqual(seen, [("content/engine/x.traversal", "dur 60\n")])

    def test_glob_problems_pass_through(self):
        self.write("content/engine/x.traversal", "dur 60\n")
        problems = self.validate(
            globs={"content/engine/*.traversal": lambda path, text, ctx: [f"{path}: bad duration"]}
        )
        self.assertEqual(problems, ["content/engine/x.traversal: bad duration"])

    def test_glob_json_needs_no_schema_key(self):
        self.write("content/presets/p.json", '{"name": "Default"}\n')
        problems = self.validate(globs={"content/presets/*.json": _accept})
        self.assertEqual(problems, [])

    def test_glob_json_still_must_parse(self):
        self.write("content/presets/p.json", '{"name": ')
        problems = self.validate(globs={"content/presets/*.json": _accept})
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("content/presets/p.json: "))

    def test_non_utf8_text_refused_for_glob(self):
        self.write("content/engine/bad.traversal", b"\xff\xfe\x00")
        problems = self.validate(globs={"content/engine/*.traversal": _accept})
        self.assertTrue(any(problem.startswith("content/engine/bad.traversal: not valid UTF-8") for problem in problems))


class TreeAndContextTest(_ContentTest):
    def test_absent_content_directory_has_no_problems(self):
        self.assertEqual(self.validate(), [])

    def test_empty_content_directory_has_no_problems(self):
        (self.root / "content").mkdir()
        self.assertEqual(self.validate(), [])

    def test_pending_flags_pass_through_to_context(self):
        seen = []

        def capture(path, obj, ctx):
            seen.append(ctx)
            return []

        self.write("content/presets/a.json", '{"schema": "%s"}\n' % SCHEMA)
        self.validate(schemas={SCHEMA: capture})
        self.validate(schemas={SCHEMA: capture}, allow_pending=True)
        self.validate(schemas={SCHEMA: capture}, release=True)
        self.assertFalse(seen[0].allow_pending)
        self.assertFalse(seen[0].release)
        self.assertTrue(seen[1].allow_pending)
        self.assertFalse(seen[1].release)
        self.assertFalse(seen[2].allow_pending)
        self.assertTrue(seen[2].release)
        self.assertTrue(Path(seen[0].root).is_absolute())

    def test_allow_pending_and_release_are_mutually_exclusive(self):
        with self.assertRaises(ValueError):
            self.validate(allow_pending=True, release=True)

    def test_discover_returns_two_mappings(self):
        schemas, globs = discover()
        self.assertIsInstance(schemas, dict)
        self.assertIsInstance(globs, dict)


class EvidenceZoneTest(_ContentTest):
    """docs/evidence JSON goes through the same registry rules, using the real registry."""

    def registry_problems(self):
        return validate_content.validate_tree(str(self.root), False, False)

    def test_real_download_verification_record_passes(self):
        self.write("docs/evidence/tree-small-02-download-verification.json", REAL_EVIDENCE.read_bytes())
        self.assertEqual(self.registry_problems(), [])

    def test_unknown_evidence_schema_refused(self):
        self.write("docs/evidence/x.json", '{"schema": "luminumbra.nope.v1"}\n')
        self.assertEqual(
            self.registry_problems(),
            ["docs/evidence/x.json: schema 'luminumbra.nope.v1' is not registered"],
        )

    def test_future_version_of_registered_schema_refused(self):
        future = EVIDENCE_SCHEMA[: -len("v1")] + "v999"
        self.write("docs/evidence/x.json", '{"schema": "%s", "verified_on": "2026-10-10"}\n' % future)
        self.assertEqual(
            self.registry_problems(),
            [f"docs/evidence/x.json: schema '{future}' is not registered"],
        )

    def _record(self):
        return json.loads(REAL_EVIDENCE.read_text(encoding="utf-8"))

    def _write_record(self, record, rel="docs/evidence/x.json"):
        self.write(rel, json.dumps(record) + "\n")

    def test_registered_schema_with_missing_key_refused(self):
        record = self._record()
        del record["method"]
        self._write_record(record)
        self.assertEqual(self.registry_problems(), ["docs/evidence/x.json: missing key 'method'"])

    def test_registered_schema_with_null_key_refused(self):
        record = self._record()
        record["method"] = None
        self._write_record(record)
        self.assertEqual(self.registry_problems(), ["docs/evidence/x.json: key 'method' must be a string"])

    def test_evidence_record_with_unknown_root_key_refused(self):
        record = self._record()
        record["extra"] = 1
        self._write_record(record)
        self.assertEqual(self.registry_problems(), ["docs/evidence/x.json: unknown key 'extra'"])

    def test_evidence_source_must_be_an_object(self):
        record = self._record()
        record["source"] = False
        self._write_record(record)
        self.assertEqual(self.registry_problems(), ["docs/evidence/x.json: source: not an object"])

    def test_evidence_source_with_unknown_key_refused(self):
        record = self._record()
        record["source"]["extra"] = "x"
        self._write_record(record)
        self.assertEqual(self.registry_problems(), ["docs/evidence/x.json: source: unknown key 'extra'"])

    def test_evidence_source_with_missing_nested_key_refused(self):
        record = self._record()
        del record["source"]["tag"]
        self._write_record(record)
        self.assertEqual(self.registry_problems(), ["docs/evidence/x.json: source: missing key 'tag'"])

    def test_evidence_bool_where_integer_expected_refused(self):
        record = self._record()
        record["source"]["archive_bytes"] = True
        self._write_record(record)
        self.assertEqual(
            self.registry_problems(),
            ["docs/evidence/x.json: source: key 'archive_bytes' must be an integer"],
        )

    def test_evidence_member_with_unknown_key_refused(self):
        record = self._record()
        record["runtime"]["members"][0]["extra"] = 1
        self._write_record(record)
        self.assertEqual(
            self.registry_problems(),
            ["docs/evidence/x.json: runtime: members[0]: unknown key 'extra'"],
        )

    def test_evidence_members_must_be_non_empty(self):
        record = self._record()
        record["source"]["members"] = []
        self._write_record(record)
        self.assertEqual(
            self.registry_problems(),
            ["docs/evidence/x.json: source: members: must be a non-empty array"],
        )

    def test_evidence_member_hash_must_be_64_lowercase_hex(self):
        record = self._record()
        record["source"]["members"][0]["sha256"] = "A" * 64
        self._write_record(record)
        self.assertEqual(
            self.registry_problems(),
            ["docs/evidence/x.json: source: members[0]: key 'sha256' has the wrong format"],
        )

    def test_evidence_acquisition_with_unknown_key_refused(self):
        record = self._record()
        record["acquisition"]["extra"] = "x"
        self._write_record(record)
        self.assertEqual(self.registry_problems(), ["docs/evidence/x.json: acquisition: unknown key 'extra'"])

    def test_evidence_script_hash_bool_refused(self):
        record = self._record()
        record["acquisition"]["script_sha256"]["acquire.py"] = True
        self._write_record(record)
        self.assertEqual(
            self.registry_problems(),
            ["docs/evidence/x.json: acquisition: script_sha256: key 'acquire.py' must be a string"],
        )

    def test_uppercase_json_extension_in_evidence_is_checked(self):
        self.write("docs/evidence/x.JSON", '{"schema": "luminumbra.nope.v1"}\n')
        self.assertEqual(
            self.registry_problems(),
            ["docs/evidence/x.JSON: schema 'luminumbra.nope.v1' is not registered"],
        )

    def test_mixed_case_json_extension_in_content_is_checked(self):
        self.write("content/x.Json", '{"schema": "luminumbra.nope.v1"}\n')
        self.assertEqual(
            self.validate(),
            ["content/x.Json: schema 'luminumbra.nope.v1' is not registered"],
        )

    def test_evidence_top_level_must_be_an_object(self):
        self.write("docs/evidence/x.json", "[1]\n")
        self.assertEqual(self.registry_problems(), ["docs/evidence/x.json: top level must be a JSON object"])

    def test_evidence_without_schema_key_refused(self):
        self.write("docs/evidence/x.json", '{"verified_on": "2026-09-07"}\n')
        self.assertEqual(self.registry_problems(), ["docs/evidence/x.json: missing schema key"])

    def test_non_json_evidence_file_is_left_to_the_public_guard(self):
        self.write("docs/evidence/notes.md", "hi\n")
        self.assertEqual(self.registry_problems(), [])

    def test_evidence_only_tree_is_validated_by_main(self):
        self.write("docs/evidence/x.json", '{"schema": "luminumbra.nope.v1"}\n')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = validate_content.main(["--root", str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn("docs/evidence/x.json: schema 'luminumbra.nope.v1' is not registered", out.getvalue().splitlines())

    def test_deep_json_nesting_reported_and_other_files_still_checked(self):
        self.write("content/presets/deep.json", b"[" * 200000 + b"]" * 200000)
        self.write("docs/evidence/bad.json", '{"schema": "luminumbra.nope.v1"}\n')
        problems = self.registry_problems()
        self.assertIn("content/presets/deep.json: json nesting is too deep", problems)
        self.assertIn("docs/evidence/bad.json: schema 'luminumbra.nope.v1' is not registered", problems)

    def test_deep_json_nesting_in_evidence_reported(self):
        self.write("docs/evidence/deep.json", b"[" * 200000 + b"]" * 200000)
        self.assertEqual(self.registry_problems(), ["docs/evidence/deep.json: json nesting is too deep"])

    def test_evidence_symlink_root_is_refused(self):
        (self.root / "docs").mkdir()
        (self.root / "elsewhere").mkdir()
        try:
            os.symlink(self.root / "elsewhere", self.root / "docs" / "evidence")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable on this platform")
        self.assertEqual(self.registry_problems(), ["docs/evidence: symlink or non-directory is not allowed"])


class MainTest(_ContentTest):
    def test_absent_content_directory_prints_notice_and_exits_zero(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = validate_content.main(["--root", str(self.root)])
        self.assertEqual(code, 0)
        self.assertIn("no content/ directory", out.getvalue())

    def test_release_and_allow_pending_are_usage_error(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = validate_content.main(["--root", str(self.root), "--release", "--allow-pending"])
        self.assertEqual(code, 2)

    def test_missing_root_is_usage_error(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = validate_content.main(["--root", str(self.root / "missing")])
        self.assertEqual(code, 2)

    def test_content_regular_file_is_refused(self):
        self.write("content", "not a directory\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = validate_content.main(["--root", str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn("content: symlink or non-directory is not allowed", out.getvalue().splitlines())

    def test_content_regular_file_is_refused_by_validate_tree(self):
        self.write("content", "not a directory\n")
        self.assertEqual(self.validate(), ["content: symlink or non-directory is not allowed"])

    def test_dangling_content_symlink_is_refused_before_absence_notice(self):
        try:
            os.symlink(self.root / "missing-target", self.root / "content")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable on this platform")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = validate_content.main(["--root", str(self.root)])
        self.assertEqual(code, 1)
        self.assertEqual(out.getvalue().splitlines(), ["content: symlink or non-directory is not allowed"])


if __name__ == "__main__":
    unittest.main()
