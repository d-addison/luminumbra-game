"""Tests for tools/validate_content.py and the tools/validators registry."""

import contextlib
import io
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
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("content/presets/a.json: "))
        self.assertIn("unknown schema", problems[0])

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


if __name__ == "__main__":
    unittest.main()
