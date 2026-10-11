import contextlib
import hashlib
import io
import json
import os
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
from lumlib import identity  # noqa: E402

_PRESETS = _REPO / "content" / "presets"
_MAPPED = "worlds/atlas/presets/cave_dense.json"
_SIDECAR = "content/presets/cave_dense.identity.json"


def _run(argv):
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = exporter.main(argv)
    return code, out.getvalue(), err.getvalue()


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write(path, text):
    """Write UTF-8 bytes verbatim; Path.write_text would turn LF into CRLF on Windows."""
    Path(path).write_bytes(text.encode("utf-8"))


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


def _symlinks_supported():
    with tempfile.TemporaryDirectory() as probe:
        target = os.path.join(probe, "target")
        os.mkdir(target)
        try:
            os.symlink(target, os.path.join(probe, "link"), target_is_directory=True)
        except (OSError, NotImplementedError):
            return False
    return True


_SYMLINKS = _symlinks_supported()


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

    def _sidecar_copy_with(self, name, sidecar_text):
        root = self._content_copy(name)
        _write(root / _SIDECAR, sidecar_text)
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
        _write(keep, "keep\n")
        code, _, err = _run(["--out", str(out_dir)])
        self.assertEqual(code, 2)
        self.assertIn("not empty", err)
        self.assertEqual(keep.read_bytes(), b"keep\n")
        self.assertFalse((out_dir / "worlds").exists())

    def test_out_refuses_git_component(self):
        out_dir = self.tmp / ".git" / "export"
        code, _, err = _run(["--out", str(out_dir)])
        self.assertEqual(code, 2)
        self.assertIn(".git", err)
        self.assertFalse(out_dir.exists())

    def test_out_refuses_upper_case_git_component(self):
        out_dir = self.tmp / ".GIT" / "export"
        code, _, err = _run(["--out", str(out_dir)])
        self.assertEqual(code, 2)
        self.assertIn(".git", err)
        self.assertFalse(out_dir.exists())

    @unittest.skipUnless(_SYMLINKS, "symlinks are not available on this platform")
    def test_out_refuses_symlink_alias_into_git_directory(self):
        git_dir = self.tmp / ".git"
        git_dir.mkdir()
        alias = self.tmp / "alias"
        os.symlink(str(git_dir), str(alias), target_is_directory=True)
        code, _, err = _run(["--out", str(alias / "export")])
        self.assertEqual(code, 2)
        self.assertIn(".git", err)
        self.assertFalse((git_dir / "export").exists())

    def test_out_refuses_destination_inside_content_tree(self):
        root = self._content_copy("ctree")
        out_dir = root / "content" / "export"
        code, _, err = _run(["--root", str(root), "--out", str(out_dir)])
        self.assertEqual(code, 2)
        self.assertIn("content tree", err)
        self.assertFalse(out_dir.exists())

    def test_plain_out_path_is_accepted(self):
        out_dir = self.tmp / "plain" / "export"
        code, _, err = _run(["--out", str(out_dir)])
        self.assertEqual(code, 0, err)
        self.assertTrue((out_dir / "worlds" / "atlas" / "presets" / "cave_dense.json").is_file())

    def test_out_whose_parent_is_a_file_exits_1(self):
        blocker = self.tmp / "blocker"
        _write(blocker, "file\n")
        out_dir = blocker / "export"
        code, out, _ = _run(["--out", str(out_dir)])
        self.assertEqual(code, 1)
        lines = out.splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith("%s: cannot write output: " % out_dir), lines[0])

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

    def test_check_root_that_is_a_file_exits_1(self):
        engine = self.tmp / "engine-file"
        _write(engine, "not a directory\n")
        code, out, _ = _run(["--check", str(engine)])
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines(), ["%s: not a directory" % engine])

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
        _write(preset, text.replace('"max_feature_radius": 52.0', '"max_feature_radius": 110.0', 1))
        out_dir = self.tmp / "blocked"
        code, out, _ = _run(["--root", str(root), "--out", str(out_dir)])
        self.assertEqual(code, 1)
        self.assertIn("max_feature_radius must be less than feature_cell_size", out)
        self.assertFalse(out_dir.exists())

    @unittest.skipIf(os.name == "nt", "Windows cannot hold a file named nul.json; the validator test covers the rule")
    def test_reserved_windows_device_stem_blocks_export(self):
        root = self._content_copy("reserved")
        shutil.copy(root / "content" / "presets" / "cave_dense.json", root / "content" / "presets" / "nul.json")
        out_dir = self.tmp / "reserved-out"
        code, out, _ = _run(["--root", str(root), "--out", str(out_dir)])
        self.assertEqual(code, 1)
        self.assertEqual(
            out.splitlines(),
            ["content/presets/nul.json: file name must not be a reserved Windows device name"],
        )
        self.assertFalse(out_dir.exists())

    def test_missing_sidecar_blocks_export(self):
        root = self._content_copy("nosidecar")
        (root / "content" / "presets" / "cave_dense.identity.json").unlink()
        code, out, _ = _run(["--root", str(root)])
        self.assertEqual(code, 1)
        self.assertIn("missing identity sidecar", out)

    def _assert_sidecar_refused(self, sidecar_text, needle):
        root = self._sidecar_copy_with("sidecar", sidecar_text)
        out_dir = self.tmp / "refused"
        code, out, _ = _run(["--root", str(root), "--out", str(out_dir)])
        self.assertEqual(code, 1)
        self.assertIn(_SIDECAR + ": ", out)
        self.assertIn(needle, out)
        self.assertFalse(out_dir.exists())

        engine = self.tmp / "engine-empty"
        engine.mkdir()
        code, out, _ = _run(["--root", str(root), "--check", str(engine)])
        self.assertEqual(code, 1)
        self.assertIn(needle, out)
        self.assertNotIn(": missing", out)
        self.assertEqual(list(engine.iterdir()), [])

    def test_malformed_sidecar_blocks_export_and_check(self):
        self._assert_sidecar_refused("{not json\n", "not valid JSON")

    def test_stale_sidecar_hash_blocks_export_and_check(self):
        sidecar = json.loads((_PRESETS / "cave_dense.identity.json").read_text(encoding="utf-8"))
        sidecar["file_sha256"] = "0" * 64
        self._assert_sidecar_refused(json.dumps(sidecar, indent=2) + "\n", "file_sha256 does not match")

    def test_wrong_sidecar_identity_blocks_export_and_check(self):
        sidecar = json.loads((_PRESETS / "cave_dense.identity.json").read_text(encoding="utf-8"))
        sidecar["preset_identity"] = "0" * 16
        self._assert_sidecar_refused(json.dumps(sidecar, indent=2) + "\n", "preset_identity does not match")

    def _ghost_root(self, generation_params):
        """A temporary root whose content/presets holds a valid-looking preset named ghost."""
        root = self._content_copy("ghost")
        obj = {"name": "Ghost", "description": "A test preset", "schema_rev": 6, "generation_params": generation_params}
        text = json.dumps(obj, indent=2) + "\n"
        presets = root / "content" / "presets"
        _write(presets / "ghost.json", text)
        sidecar = {
            "schema": "luminumbra.game.preset-identity.v1",
            "preset": "ghost",
            "file_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "preset_identity": identity.preset_identity(identity.loads_strict(text)),
        }
        _write(presets / "ghost.identity.json", json.dumps(sidecar, indent=2) + "\n")
        return root

    def test_non_cave_dense_preset_with_unknown_params_blocks_export(self):
        params = _minimal_params()
        params["extra"] = 1
        root = self._ghost_root(params)
        out_dir = self.tmp / "ghost-out"
        code, out, _ = _run(["--root", str(root), "--out", str(out_dir)])
        self.assertEqual(code, 1)
        self.assertIn("content/presets/ghost.json: generation_params has unknown key 'extra'", out.splitlines())
        self.assertFalse(out_dir.exists())

    def test_empty_terrain_object_blocks_export(self):
        root = self._ghost_root({"terrain": {}})
        out_dir = self.tmp / "terrain-out"
        code, out, _ = _run(["--root", str(root), "--out", str(out_dir)])
        self.assertEqual(code, 1)
        self.assertIn(
            "content/presets/ghost.json: generation_params.terrain.base_frequency is required", out.splitlines()
        )
        self.assertFalse(out_dir.exists())

    def test_missing_mandatory_feature_key_blocks_export_and_check(self):
        params = _minimal_params()
        del params["features"]["caves_enabled"]
        root = self._ghost_root(params)
        engine = self.tmp / "engine-ghost"
        engine.mkdir()
        code, out, _ = _run(["--root", str(root), "--check", str(engine)])
        self.assertEqual(code, 1)
        self.assertIn(
            "content/presets/ghost.json: generation_params.features.caves_enabled is required", out.splitlines()
        )
        self.assertEqual(list(engine.iterdir()), [])

    def test_deep_nesting_in_preset_exits_1_with_one_line_problem(self):
        root = self._content_copy("deep")
        _write(root / "content" / "presets" / "cave_dense.json", "[" * 200000 + "]" * 200000)
        out_dir = self.tmp / "deep-out"
        code, out, _ = _run(["--root", str(root), "--out", str(out_dir)])
        self.assertEqual(code, 1)
        self.assertIn("content/presets/cave_dense.json: json nesting is too deep", out.splitlines())
        self.assertFalse(out_dir.exists())

    def test_deep_nesting_in_sidecar_blocks_export_and_check(self):
        self._assert_sidecar_refused("[" * 200000 + "]" * 200000, "json nesting is too deep")


if __name__ == "__main__":
    unittest.main()
