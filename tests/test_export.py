import contextlib
import hashlib
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_TOOLS = _REPO / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import export_engine_content as exporter  # noqa: E402

_PRESETS = _REPO / "content" / "presets"
_MAPPED = "worlds/atlas/presets/cave_dense.json"


def _run(argv):
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = exporter.main(argv)
    return code, out.getvalue(), err.getvalue()


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ExportTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _content_copy(self, name):
        """Copy the committed presets into a temporary root and return that root."""
        root = self.tmp / name
        (root / "content" / "presets").mkdir(parents=True)
        for item in _PRESETS.iterdir():
            shutil.copy(item, root / "content" / "presets" / item.name)
        return root

    def test_manifest_lists_cave_dense_only_with_matching_hashes(self):
        code, out, err = _run([])
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertEqual(len(lines), 1, lines)
        digest, mapped = lines[0].split("  ")
        self.assertEqual(mapped, _MAPPED)
        self.assertEqual(digest, _sha256(_PRESETS / "cave_dense.json"))

    def test_out_writes_byte_identical_files_at_mapped_path(self):
        out_dir = self.tmp / "export"
        code, _, err = _run(["--out", str(out_dir)])
        self.assertEqual(code, 0, err)
        written = out_dir / "worlds" / "atlas" / "presets" / "cave_dense.json"
        self.assertTrue(written.is_file())
        self.assertEqual(written.read_bytes(), (_PRESETS / "cave_dense.json").read_bytes())
        self.assertFalse((out_dir / "worlds" / "atlas" / "presets" / "cave_dense.identity.json").exists())

    def test_out_refuses_non_empty_directory(self):
        out_dir = self.tmp / "busy"
        out_dir.mkdir()
        keep = out_dir / "keep.txt"
        keep.write_text("keep\n", encoding="utf-8")
        code, _, err = _run(["--out", str(out_dir)])
        self.assertEqual(code, 2)
        self.assertIn("not empty", err)
        self.assertEqual(keep.read_text(encoding="utf-8"), "keep\n")
        self.assertFalse((out_dir / "worlds").exists())

    def test_out_refuses_git_component(self):
        out_dir = self.tmp / ".git" / "export"
        code, _, err = _run(["--out", str(out_dir)])
        self.assertEqual(code, 2)
        self.assertIn(".git", err)
        self.assertFalse(out_dir.exists())

    def test_check_passes_on_exported_copy(self):
        engine = self.tmp / "engine"
        code, _, err = _run(["--out", str(engine)])
        self.assertEqual(code, 0, err)
        code, out, _ = _run(["--check", str(engine)])
        self.assertEqual(code, 0)
        self.assertEqual(out, "")

    def test_check_fails_on_differing_file(self):
        engine = self.tmp / "engine"
        _run(["--out", str(engine)])
        (engine / _MAPPED).write_bytes((_PRESETS / "cave_dense.json").read_bytes() + b"\n")
        code, out, _ = _run(["--check", str(engine)])
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines(), ["%s: differs" % _MAPPED])

    def test_check_fails_on_missing_file(self):
        engine = self.tmp / "engine"
        _run(["--out", str(engine)])
        (engine / _MAPPED).unlink()
        code, out, _ = _run(["--check", str(engine)])
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines(), ["%s: missing" % _MAPPED])

    def test_out_and_check_together_exit_2(self):
        code, _, err = _run(["--out", str(self.tmp / "a"), "--check", str(self.tmp)])
        self.assertEqual(code, 2)
        self.assertIn("not allowed with", err)
        self.assertFalse((self.tmp / "a").exists())

    def test_check_with_missing_engine_root_exit_2(self):
        code, _, err = _run(["--check", str(self.tmp / "absent")])
        self.assertEqual(code, 2)
        self.assertIn("not a directory", err)

    def test_invalid_preset_blocks_export(self):
        root = self._content_copy("bad")
        preset = root / "content" / "presets" / "cave_dense.json"
        text = preset.read_text(encoding="utf-8")
        preset.write_text(text.replace('"max_feature_radius": 52.0', '"max_feature_radius": 110.0', 1), encoding="utf-8")
        out_dir = self.tmp / "blocked"
        code, out, _ = _run(["--root", str(root), "--out", str(out_dir)])
        self.assertEqual(code, 1)
        self.assertIn("max_feature_radius must be less than feature_cell_size", out)
        self.assertFalse(out_dir.exists())

    def test_missing_sidecar_blocks_export(self):
        root = self._content_copy("nosidecar")
        (root / "content" / "presets" / "cave_dense.identity.json").unlink()
        code, out, _ = _run(["--root", str(root)])
        self.assertEqual(code, 1)
        self.assertIn("missing identity sidecar", out)


if __name__ == "__main__":
    unittest.main()
