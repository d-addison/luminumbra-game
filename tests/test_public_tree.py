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
from unittest import mock

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
        self.write("docs/evidence/ok.json", '{"schema": "luminumbra.game-pack-download-verification.v1"}\n')
        code, lines = self.run_guard()
        self.assertEqual(code, 0)
        self.assertEqual(lines, ["public tree ok (2 files)"])

    def test_content_json_without_schema_key_passes(self):
        self.write("content/presets/p.json", '{"a": 1}\n')
        code, lines = self.run_guard()
        self.assertEqual(code, 0)
        self.assertEqual(lines, ["public tree ok (1 files)"])

    def test_nul_in_strict_zone_refused_for_any_extension(self):
        self.write("docs/evidence/blob.dat", b"\xff\x00\n")
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        self.assertIn("docs/evidence/blob.dat: NUL byte in text file", lines)
        self.assertTrue(any(line.startswith("docs/evidence/blob.dat: not valid UTF-8") for line in lines))

    def test_invalid_utf8_in_strict_zone_refused_for_any_extension(self):
        self.write("content/raw.bin", b"\xff\xfe\n")
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        self.assertTrue(any(line.startswith("content/raw.bin: not valid UTF-8") for line in lines))

    def test_duplicate_keys_in_strict_json_refused(self):
        self.write("content/dup.json", b'{"a": 1, "a": 2}\n')
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        self.assertTrue(any(line.startswith("content/dup.json: invalid JSON") and "duplicate key" in line for line in lines))

    def test_exponent_tokens_in_strict_json_refused(self):
        self.write("content/exp.json", b'{"a": 1e0}\n')
        self.write("docs/evidence/exp.json", b'{"schema": "luminumbra.x.v1", "a": 6.0e1}\n')
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        self.assertTrue(any(line.startswith("content/exp.json: invalid JSON") and "exponent" in line for line in lines))
        self.assertTrue(any(line.startswith("docs/evidence/exp.json: invalid JSON") and "exponent" in line for line in lines))

    def test_nan_in_strict_json_refused(self):
        self.write("content/nan.json", b'{"a": NaN}\n')
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        self.assertTrue(any(line.startswith("content/nan.json: invalid JSON") for line in lines))

    def test_evidence_json_without_schema_refused(self):
        self.write("docs/evidence/no-schema.json", '{"a": 1}\n')
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        self.assertTrue(any(line.startswith("docs/evidence/no-schema.json: evidence JSON needs a schema") for line in lines))

    def test_evidence_json_schema_must_be_a_string_matching_the_pattern(self):
        cases = {
            "not-string.json": '{"schema": 1}\n',
            "wrong-stem.json": '{"schema": "other.thing.v1"}\n',
            "no-version.json": '{"schema": "luminumbra.thing"}\n',
            "upper.json": '{"schema": "luminumbra.Thing.v1"}\n',
            "trailing-newline.json": '{"schema": "luminumbra.thing.v1\\n"}\n',
        }
        for name, text in cases.items():
            self.write(f"docs/evidence/{name}", text)
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        for name in cases:
            self.assertTrue(
                any(line.startswith(f"docs/evidence/{name}: evidence JSON needs a schema") for line in lines),
                msg=name,
            )

    def test_evidence_json_must_be_an_object(self):
        self.write("docs/evidence/list.json", "[1]\n")
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        self.assertIn("docs/evidence/list.json: evidence JSON must be an object", lines)

    def test_evidence_json_with_real_schema_passes(self):
        self.write(
            "docs/evidence/tree-small-02-download-verification.json",
            '{"schema": "luminumbra.game-pack-download-verification.v1", "verified_on": "2026-09-07"}\n',
        )
        code, lines = self.run_guard()
        self.assertEqual(code, 0)
        self.assertEqual(lines, ["public tree ok (1 files)"])

    def test_media_extensions_refused(self):
        extensions = (
            # images
            ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tga", ".dds", ".exr", ".hdr",
            ".psd", ".webp", ".ktx", ".ktx2", ".tif", ".tiff",
            # audio
            ".m4a", ".aac", ".wma", ".aiff", ".aif", ".mid", ".midi",
            # video
            ".mp4", ".mkv", ".avi", ".mov", ".webm",
            # runtime artifacts
            ".ltex", ".lmesh", ".lmc", ".lmr",
        )
        for ext in extensions:
            self.write("media/sample" + ext, "plain text\n")
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        for ext in extensions:
            self.assertIn(f"media/sample{ext}: forbidden extension {ext}", lines)

    def test_image_signatures_refused(self):
        signatures = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff\xe0", b"GIF87a", b"GIF89a")
        for index, magic in enumerate(signatures):
            self.write(f"media/img-{index}.dat", magic + b"\nbody\n")
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        for index in range(len(signatures)):
            self.assertTrue(
                any(line.startswith(f"media/img-{index}.dat: forbidden file signature") for line in lines),
                msg=index,
            )

    def test_inventoried_asset_passes(self):
        self.write("assets/icon.png", b"\x89PNG\r\n\x1a\n\x00\x00")
        with mock.patch.object(guard, "INVENTORIED_BINARY", frozenset({"assets/icon.png"})):
            code, lines = self.run_guard()
        self.assertEqual(code, 0)
        self.assertEqual(lines, ["public tree ok (1 files)"])

    def test_same_path_outside_assets_is_still_refused(self):
        self.write("docs/icon.png", b"\x89PNG\r\n\x1a\n\x00\x00")
        with mock.patch.object(guard, "INVENTORIED_BINARY", frozenset({"docs/icon.png"})):
            code, lines = self.run_guard()
        self.assertEqual(code, 1)
        self.assertIn("docs/icon.png: forbidden extension .png", lines)
        self.assertTrue(any(line.startswith("docs/icon.png: forbidden file signature") for line in lines))

    def test_uninventoried_asset_is_refused(self):
        self.write("assets/other.png", b"\x89PNG\r\n\x1a\n\x00\x00")
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        self.assertIn("assets/other.png: forbidden extension .png", lines)

    def test_default_inventory_is_empty(self):
        self.assertEqual(guard.INVENTORIED_BINARY, frozenset())

    def test_windows_drive_paths_refused(self):
        self.write("docs/w0.md", "C:" + "/" + "Users" + "/Alice\n")
        self.write("docs/w1.md", "C:" + "\\\\" + "Users" + "\\\\" + "Alice\n")
        self.write("docs/w2.md", "c:" + "\\" + "Users" + "\\" + "Bob\n")
        self.write("docs/w3.md", "D:" + "\\" + "Documents and Settings" + "\\" + "Eve\n")
        self.write("docs/w4.md", "e:" + "/" + "users" + "/Mallory\n")
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        for index in range(5):
            self.assertIn(f"docs/w{index}.md: absolute local path", lines)

    def test_windows_drive_text_without_user_folder_passes(self):
        self.write("docs/ok.md", "Drive C:" + "/" + "Games and tools\n")
        code, lines = self.run_guard()
        self.assertEqual(code, 0)
        self.assertEqual(lines, ["public tree ok (1 files)"])

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

    def test_escaped_windows_path_in_json_string_refused(self):
        # Literal backslash-u escapes: the file text never contains the flagged shape.
        self.write("docs/esc0.json", '{"a": "C:' + "\\u005c" + 'Users' + "\\u005c" + 'Alice"}\n')
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        self.assertIn("docs/esc0.json: absolute local path", lines)

    def test_escaped_slash_windows_path_in_json_string_refused(self):
        self.write("docs/esc1.json", '{"a": "C:' + "\\/" + 'Users' + "\\/" + 'Alice"}\n')
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        self.assertIn("docs/esc1.json: absolute local path", lines)

    def test_escaped_windows_path_in_json_key_refused(self):
        self.write("docs/esc2.json", '{"C:' + "\\u005c" + 'Users": 1}\n')
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        self.assertIn("docs/esc2.json: absolute local path", lines)

    def test_escaped_credential_in_json_string_refused(self):
        self.write("notes/esc3.json", '{"a": "' + "\\u0067" + 'hp_' + 'A' * 24 + '"}\n')
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        self.assertIn("notes/esc3.json: credential-shaped string", lines)

    def test_json_without_path_shapes_passes(self):
        self.write("content/presets/ok.json", '{"a": "C:' + "\\u005c" + 'Games"}\n')
        code, lines = self.run_guard()
        self.assertEqual(code, 0)
        self.assertEqual(lines, ["public tree ok (1 files)"])

    def test_deep_json_nesting_reported_and_scan_continues(self):
        self.write("content/deep.json", b"[" * 2000 + b"]" * 2000 + b"\n")
        self.write("content/bad.wav", b"plain\n")
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        self.assertIn("content/deep.json: json nesting is too deep", lines)
        self.assertIn("content/bad.wav: forbidden extension .wav", lines)

    def test_deep_json_outside_strict_zone_does_not_crash(self):
        self.write("notes/deep.json", b"[" * 2000 + b"]" * 2000 + b"\n")
        code, lines = self.run_guard()
        self.assertEqual(code, 0)
        self.assertEqual(lines, ["public tree ok (1 files)"])

    def test_escaped_path_after_exponent_number_refused_by_lenient_scan(self):
        # The strict preset parser rejects 1e0; the security scan still decodes the strings.
        text = '{"n":1e0,"p":"C:' + "\\u005c" + 'Users' + "\\u005c" + 'Alice"}\n'
        self.write("notes/x.json", text)
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["notes/x.json: absolute local path"])

    def test_invalid_json_outside_strict_zone_does_not_crash(self):
        self.write("notes/bad.json", '{"a": \n')
        code, lines = self.run_guard()
        self.assertEqual(code, 0)
        self.assertEqual(lines, ["public tree ok (1 files)"])

    def test_uppercase_json_extension_in_evidence_zone_is_checked(self):
        self.write("docs/evidence/x.JSON", '{"schema": "not-a-schema"}\n')
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        self.assertIn("docs/evidence/x.JSON: evidence JSON needs a schema key matching luminumbra.<name>.v<N>", lines)

    def test_uppercase_json_extension_gets_escaped_path_scan(self):
        self.write("notes/esc.Json", '{"a": "C:' + "\\u005c" + 'Users' + "\\u005c" + 'Alice"}\n')
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        self.assertIn("notes/esc.Json: absolute local path", lines)

    def test_archive_and_binary_signatures_refused_literal_bytes(self):
        cases = {
            "zip-eocd.dat": b"PK\x05\x06" + b"\x00" * 18,
            "zip-spanned.dat": b"PK\x07\x08" + b"\x00" * 12,
            "sevenzip.dat": b"7z\xbc\xaf\x27\x1c" + b"\x00" * 6,
            "xz.dat": b"\xfd7zXZ\x00" + b"\x00" * 8,
            "gzip.dat": b"\x1f\x8b\x08" + b"\x00" * 8,
            "bzip2.dat": b"BZh9" + b"\x00" * 8,
            "rar.dat": b"Rar!\x1a\x07\x01\x00" + b"\x00" * 4,
            "macho-32.dat": b"\xfe\xed\xfa\xce" + b"\x00" * 8,
            "macho-64.dat": b"\xfe\xed\xfa\xcf" + b"\x00" * 8,
            "macho-le-32.dat": b"\xce\xfa\xed\xfe" + b"\x00" * 8,
            "macho-le-64.dat": b"\xcf\xfa\xed\xfe" + b"\x00" * 8,
            "macho-universal.dat": b"\xca\xfe\xba\xbe" + b"\x00" * 8,
            "elf.dat": b"\x7fELF" + b"\x00" * 8,
            "pe.dat": b"MZ" + b"\x00" * 8,
            "bzip2-note.md": b"BZh9\n",
        }
        for name, data in cases.items():
            self.write("bin/" + name, data)
        code, lines = self.run_guard()
        self.assertEqual(code, 1)
        for name in cases:
            self.assertTrue(
                any(line.startswith(f"bin/{name}: forbidden file signature") for line in lines),
                msg=name,
            )


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
