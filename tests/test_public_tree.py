"""Tests for tools/validate_public_tree.py.

Negative-control strings are built at runtime by concatenation so that this
file never contains the literal patterns the guard refuses.
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import validate_public_tree as guard  # noqa: E402

LIMIT = guard.MAX_BYTES


def _token():
    return "gh" + "p_" + "A" * 24 + "\n"


def _fine_grained_token():
    return "github" + "_pat_" + "x" * 12 + "\n"


def _aws_key():
    return "AK" + "IA" + "0123456789ABC" + "\n"


def _private_key_header():
    return "-----" + "BEGIN " + "RSA " + "PRIVATE KEY-----\n"


ABSOLUTE_PATH_SAMPLES = (
    "/ho" + "me/d/src\n",
    "C:" + "\\" + "Users" + "\\" + "d\n",
    "/Us" + "ers/d/x\n",
    "/l" + "um/x\n",
    "/mn" + "t/c/x\n",
)


class _TreeTest(unittest.TestCase):
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

    def run_guard(self, *extra):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = guard.main(["--root", str(self.root), *extra])
        return code, out.getvalue().splitlines()


class CleanTreeTest(_TreeTest):
    def test_clean_tree_passes_and_counts_files(self):
        self.write("README.md", "hello\n")
        self.write("docs/notes.md", "plain text\n")
        code, lines = self.run_guard()
        self.assertEqual(code, 0)
        self.assertEqual(lines, ["public tree ok (2 files)"])

    def test_size_at_limit_passes(self):
        self.write("edge.txt", b"a" * LIMIT)
        code, lines = self.run_guard()
        self.assertEqual(code, 0)
        self.assertEqual(lines, ["public tree ok (1 files)"])

    def test_size_over_limit_refused(self):
        self.write("big.txt", b"a" * (LIMIT + 1))
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        self.assertTrue(any(line.startswith("big.txt: ") and "exceeds" in line for line in lines))

    def test_symlink_refused(self):
        self.write("target.md", "x\n")
        try:
            os.symlink(self.root / "target.md", self.root / "link.md")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable on this platform")
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        self.assertIn("link.md: symlink refused", lines)

    def test_forbidden_extensions_refused_case_insensitively(self):
        for ext in sorted(guard.FORBIDDEN_EXTENSIONS):
            self.write("sample" + ext, "plain text\n")
        self.write("UPPER.WAV", "plain text\n")
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        for ext in sorted(guard.FORBIDDEN_EXTENSIONS):
            self.assertIn(f"sample{ext}: forbidden extension {ext}", lines)
        self.assertIn("UPPER.WAV: forbidden extension .wav", lines)

    def test_forbidden_leading_signatures_refused(self):
        for index, magic in enumerate(guard.FORBIDDEN_MAGIC):
            self.write(f"blob-{index}.dat", magic + b"\nbody\n")
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        for index, magic in enumerate(guard.FORBIDDEN_MAGIC):
            self.assertTrue(
                any(line.startswith(f"blob-{index}.dat: forbidden file signature") for line in lines),
                msg=repr(magic),
            )

    def test_signature_after_first_sixteen_bytes_not_refused(self):
        self.write("late.dat", b"x" * 20 + b"RIFF\n")
        code, _ = self.run_guard()
        self.assertEqual(code, 0)

    def test_nul_in_text_file_refused(self):
        self.write("bad.md", b"a\x00b\n")
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        self.assertIn("bad.md: NUL byte in text file", lines)

    def test_invalid_utf8_in_text_file_refused(self):
        self.write("latin.md", b"caf\xe9\n")
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        self.assertTrue(any(line.startswith("latin.md: not valid UTF-8") for line in lines))

    def test_crlf_in_strict_zone_refused(self):
        self.write("content/x.json", b'{"a": 1}\r\n')
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        self.assertTrue(any(line.startswith("content/x.json: CR byte") for line in lines))

    def test_bom_in_strict_zone_refused(self):
        self.write("content/b.txt", b"\xef\xbb\xbfhi\n")
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        self.assertTrue(any(line.startswith("content/b.txt: UTF-8 BOM") for line in lines))

    def test_missing_final_lf_in_strict_zone_refused(self):
        self.write("docs/evidence/e.md", "hi")
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        self.assertTrue(any(line.startswith("docs/evidence/e.md: missing final LF") for line in lines))

    def test_invalid_json_in_strict_zone_refused(self):
        self.write("content/bad.json", '{"a": ')
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        self.assertTrue(any(line.startswith("content/bad.json: invalid JSON") for line in lines))

    def test_strict_zone_clean_files_pass(self):
        self.write("content/ok.json", '{"a": 1}\n')
        self.write("docs/evidence/ok.md", "x\n")
        code, lines = self.run_guard()
        self.assertEqual(code, 0)
        self.assertEqual(lines, ["public tree ok (2 files)"])

    def test_line_rules_do_not_apply_outside_strict_zones(self):
        self.write("docs/notes.md", b"hi\r\nno final newline")
        code, _ = self.run_guard()
        self.assertEqual(code, 0)

    def test_absolute_local_paths_refused(self):
        for index, text in enumerate(ABSOLUTE_PATH_SAMPLES):
            self.write(f"docs/p{index}.md", text)
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        for index in range(len(ABSOLUTE_PATH_SAMPLES)):
            self.assertIn(f"docs/p{index}.md: absolute local path", lines)

    def test_credential_shapes_refused(self):
        self.write("notes/c0.md", _token())
        self.write("notes/c1.md", _fine_grained_token())
        self.write("notes/c2.md", _aws_key())
        self.write("notes/c3.md", _private_key_header())
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        for index in range(4):
            self.assertIn(f"notes/c{index}.md: credential-shaped string", lines)

    def test_tests_directory_is_still_scanned(self):
        self.write("tests/sample.md", _token())
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        self.assertIn("tests/sample.md: credential-shaped string", lines)


class WalkAndListTest(_TreeTest):
    def test_walk_fallback_used_without_git_repository(self):
        self.write("a.md", "one\n")
        self.write("sub/b.md", "two\n")
        code, lines = self.run_guard()
        self.assertEqual(code, 0)
        self.assertEqual(lines, ["public tree ok (2 files)"])

    def test_list_from_limits_scope(self):
        self.write("a.md", "one\n")
        self.write("bad.wav", "plain\n")
        listing = self.root / "list.txt"
        listing.write_text("a.md\n\n", encoding="utf-8")
        code, lines = self.run_guard("--list-from", str(listing))
        self.assertEqual(code, 0)
        self.assertEqual(lines, ["public tree ok (1 files)"])

    def test_list_from_missing_entry_is_reported(self):
        listing = self.root / "list.txt"
        listing.write_text("missing.md\n", encoding="utf-8")
        code, lines = self.run_guard("--list-from", str(listing))
        self.assertEqual(code, 1)
        self.assertTrue(any(line.startswith("missing.md: cannot stat file") for line in lines))

    def test_missing_root_is_usage_error(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = guard.main(["--root", str(self.root / "does-not-exist")])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
