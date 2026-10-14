import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace
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
        # Match the exporter's resolved namespace, including Windows short aliases.
        self.tmp = Path(self._tmp.name).resolve()

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


class _BoundedReader:
    """Record reads and refuse requests beyond a recorded-size probe budget."""

    def __init__(self, handle, size):
        self.handle = handle
        self.remaining = size + 1
        self.requests = []
        self.returned_sizes = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.handle.close()

    def fileno(self):
        return self.handle.fileno()

    def read(self, size):
        if not 0 < size <= min(1024 * 1024, self.remaining):
            raise AssertionError("read exceeded recorded size plus probe budget")
        self.requests.append(size)
        chunk = self.handle.read(size)
        self.returned_sizes.append(len(chunk))
        self.remaining -= len(chunk)
        return chunk


class _GrowingReader:
    """Never returns EOF; fail promptly if the caller exceeds its read budget."""

    def __init__(self, handle, target, initial, chunk_size=3):
        self.handle, self.target, self.initial = handle, target, initial
        self.chunk_size = chunk_size
        self.requests = []
        self.returned_sizes = []
        self.count = 0
        self.external = initial + b"external growth\n"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.handle.close()

    def fileno(self):
        return self.handle.fileno()

    def read(self, size):
        self.requests.append(size)
        amount = min(size, self.chunk_size)
        if size <= 0 or self.count + amount > len(self.initial) + 1:
            raise AssertionError("growing reader exceeded size plus probe budget")
        if not self.returned_sizes:
            # Mutate only after pre/open checks, without threads or namespace races.
            with open(self.target, "ab", buffering=0) as writer:
                writer.write(self.external[len(self.initial):])
        chunk = self.initial[self.count:self.count + amount].ljust(amount, b"x")
        self.count += amount
        self.returned_sizes.append(amount)
        return chunk


class ExportRepairTests(unittest.TestCase):
    setUp = ExportTests.setUp
    tearDown = ExportTests.tearDown
    _content_copy = ExportTests._content_copy

    def _files(self):
        return [("worlds/atlas/presets/%s.json" % name, hashlib.sha256(data).hexdigest(), data)
                for name, data in (("first", b"first bytes\n"), ("second", b"second bytes\n"))]

    def _destination(self, existed=False, name="out"):
        path = self.tmp / name
        if existed:
            path.mkdir()
        return path, exporter.check_destination(str(path), str(_REPO))

    def _isolated_destination(self, existed, name):
        # A retained stage from another subcase is external to this invocation.
        case = self.tmp / name
        case.mkdir()
        return self._destination(existed, os.path.join(name, "out"))

    def _assert_clean(self, path, existed, initial_info):
        if existed:
            self.assertTrue(path.is_dir())
            self.assertEqual(exporter.scene.path_identity(path.stat()), exporter.scene.path_identity(initial_info))
            self.assertEqual(list(path.iterdir()), [])
        else:
            self.assertFalse(path.exists())
        self.assertEqual(list(path.parent.glob(".scene-export-*")), [])

    def _assert_retry(self, path):
        exporter.write_out(self._files(), exporter.check_destination(str(path), str(_REPO)), str(path))
        for mapped, _, data in self._files():
            self.assertEqual((path / mapped).read_bytes(), data)

    def _assert_growth_reader_bounded(self, reader, size):
        remaining = size + 1
        self.assertEqual(len(reader.requests), len(reader.returned_sizes))
        for requested, returned in zip(reader.requests, reader.returned_sizes):
            self.assertLessEqual(requested, min(1024 * 1024, remaining))
            remaining -= returned
        self.assertEqual(remaining, 0)
        self.assertEqual(reader.count, size + 1)
        self.assertTrue(reader.handle.closed)
        self.assertEqual(reader.target.read_bytes(), reader.external)

    def test_capture_growth_is_bounded_by_opened_size_and_preserves_artifact(self):
        real_fdopen = exporter.scene.os.fdopen
        for size in (0, 11, 1024 * 1024 + 7):
            with self.subTest(size=size):
                initial = b"c" * size
                digest = hashlib.sha256(initial).hexdigest()
                root = self.tmp / ("capture-growth-%s" % size)
                target = root / "sha256" / digest
                target.parent.mkdir(parents=True)
                target.write_bytes(initial)
                readers = []

                def growing_fdopen(fd, *args, **kwargs):
                    reader = _GrowingReader(real_fdopen(fd, *args, **kwargs), target, initial,
                                            chunk_size=1024 * 1024 if size > 1024 * 1024 else 3)
                    readers.append(reader)
                    return reader

                with mock.patch.object(exporter.scene.os, "fdopen", side_effect=growing_fdopen):
                    with self.assertRaisesRegex(exporter.scene.SceneError, "size increased") as caught:
                        exporter.scene._verify_capture("receipt.json", digest,
                                                       SimpleNamespace(artifact_root=str(root)))
                self.assertIn("receipt.json: capture artifact: file or ancestor changed during reading",
                              str(caught.exception))
                self.assertEqual(len(readers), 1)
                self._assert_growth_reader_bounded(readers[0], size)

    def test_ownership_reverification_refuses_growth_before_open_without_reading(self):
        target = self.tmp / "recorded-size.json"
        initial = b"recorded bytes"
        owned = exporter._OwnedPaths(exporter._directory_info(str(self.tmp)))
        owned.write(str(target), initial)
        original_stream = exporter.scene.stream_safe_file
        external = initial + b"growth before open"

        def grow_before_open(*args, **kwargs):
            # The outer recorded-version check passed; the opened snapshot is larger.
            target.write_bytes(external)
            return original_stream(*args, **kwargs)

        with mock.patch.object(exporter.scene, "stream_safe_file", side_effect=grow_before_open), \
                mock.patch.object(exporter.scene.os, "fdopen",
                                  side_effect=AssertionError("read started after recorded-size mismatch")) as reader:
            with self.assertRaisesRegex(exporter.ExportError, "file changed before reading") as caught:
                owned.verify_file(str(target))
        self.assertIn(str(target), str(caught.exception))
        reader.assert_not_called()
        self.assertEqual(target.read_bytes(), external)

    def test_growing_owned_files_are_bounded_retained_and_reported_at_export_boundaries(self):
        real_fdopen = exporter.scene.os.fdopen
        original_write = exporter._OwnedPaths.write
        original_cleanup = exporter._OwnedPaths.cleanup
        for boundary in ("stage-rollback", "publication-rollback", "stage-cleanup", "final-acceptance"):
            for existed in (False, True):
                with self.subTest(boundary=boundary, existed=existed):
                    case = self.tmp / ("growth-%s-%s" % (boundary, existed))
                    case.mkdir()
                    path, destination = self._destination(existed, os.path.join(case.name, "out"))
                    before = path.stat() if existed else None
                    selected = []
                    changed = []
                    stages = []
                    readers = []
                    initial = self._files()[0][2]
                    failure = "injected second %s write" % boundary

                    def write_boundary(owned, target, data):
                        in_output = str(target).startswith(str(path) + os.sep)
                        if boundary.endswith("rollback") and in_output == (boundary == "publication-rollback"):
                            if selected:
                                changed.append(selected[0])
                                stages.extend(path.parent.glob(".scene-export-*"))
                                raise OSError(failure)
                            result = original_write(owned, target, data)
                            selected.append(Path(target))
                            return result
                        return original_write(owned, target, data)

                    def cleanup_boundary(owned):
                        is_stage = any(Path(p).name.startswith(".scene-export-") for p in owned.directories)
                        if is_stage and boundary in ("stage-cleanup", "final-acceptance"):
                            stages.extend(path.parent.glob(".scene-export-*"))
                            if boundary == "stage-cleanup":
                                changed.append(stages[0] / self._files()[0][0])
                            result = original_cleanup(owned)
                            if boundary == "final-acceptance":
                                changed.append(path / self._files()[0][0])
                            return result
                        return original_cleanup(owned)

                    def growing_fdopen(fd, *args, **kwargs):
                        handle = real_fdopen(fd, *args, **kwargs)
                        if changed and exporter.scene.path_identity(os.fstat(fd)) == \
                                exporter.scene.path_identity(changed[0].stat()):
                            reader = _GrowingReader(handle, changed[0], initial)
                            readers.append(reader)
                            return reader
                        return handle

                    with mock.patch.object(exporter._OwnedPaths, "write", new=write_boundary), \
                            mock.patch.object(exporter._OwnedPaths, "cleanup", new=cleanup_boundary), \
                            mock.patch.object(exporter.scene.os, "fdopen", side_effect=growing_fdopen):
                        with self.assertRaisesRegex(exporter.ExportError, "cleanup uncertain") as caught:
                            exporter.write_out(self._files(), destination, str(path))
                    message = str(caught.exception)
                    if boundary.endswith("rollback"):
                        self.assertIn(failure, message)
                    elif boundary == "stage-cleanup":
                        self.assertIn("staging cleanup failed", message)
                    else:
                        self.assertIn("cannot write output", message)
                    self.assertIn(str(changed[0]) + ": file or ancestor changed during reading", message)
                    self.assertIn(str(changed[0]), message.split("retained paths:", 1)[1])
                    self.assertEqual(len(stages), 1)
                    self.assertIn("; stage: " + str(stages[0]), message)
                    self.assertEqual(len(readers), 1)
                    self._assert_growth_reader_bounded(readers[0], len(initial))
                    if existed:
                        self.assertEqual(exporter.scene.path_identity(path.stat()),
                                         exporter.scene.path_identity(before))
                    if boundary in ("stage-rollback", "stage-cleanup"):
                        self.assertEqual(list(stages[0].rglob("*.json")), changed)
                        if existed:
                            self.assertEqual(list(path.iterdir()), [])
                        else:
                            self.assertFalse(path.exists())
                        if boundary == "stage-rollback" and existed:
                            self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)
                    else:
                        self.assertFalse(stages[0].exists())
                        self.assertEqual(list(path.rglob("*.json")), changed)

    def test_captured_A_cannot_be_certified_by_B_sidecar(self):
        root = self._content_copy("snapshots")
        preset = root / "content/presets/cave_dense.json"
        sidecar = root / _SIDECAR
        raw_a = preset.read_bytes()
        obj_b = json.loads(raw_a)
        obj_b["description"] += " version B"
        raw_b = (json.dumps(obj_b, indent=2) + "\n").encode("utf-8")
        side_b = json.loads(sidecar.read_bytes())
        side_b.update(file_sha256=hashlib.sha256(raw_b).hexdigest(),
                      preset_identity=identity.preset_identity(identity.loads_strict(raw_b.decode("utf-8"))))
        original = exporter._read_bytes

        def switch_after_preset(rel, full):
            captured = original(rel, full)
            if rel == "content/presets/cave_dense.json":
                preset.write_bytes(raw_b)
                sidecar.write_bytes((json.dumps(side_b) + "\n").encode("utf-8"))
            return captured

        destination = self.tmp / "no-output"
        with mock.patch.object(exporter, "_read_bytes", side_effect=switch_after_preset):
            code, out, err = _run(["--root", str(root), "--out", str(destination)])
        self.assertEqual(code, 1, err)
        self.assertIn("file_sha256 does not match the bytes of content/presets/cave_dense.json", out)
        self.assertFalse(destination.exists())
        self.assertEqual(exporter.load_files(str(root), exporter.collect_sources(str(root)))[0][2], raw_b)

    def test_consistent_pair_exports_A_after_disk_switch_to_B(self):
        root = self._content_copy("captured-pair")
        preset = root / "content/presets/cave_dense.json"
        raw_a = preset.read_bytes()
        original = exporter._read_bytes

        def change_after_sidecar(rel, full):
            captured = original(rel, full)
            if rel == _SIDECAR:
                preset.write_bytes(b"changed after both captures")
                (root / _SIDECAR).write_bytes(b"changed sidecar too")
            return captured

        destination = self.tmp / "consistent-output"
        with mock.patch.object(exporter, "_read_bytes", side_effect=change_after_sidecar):
            code, out, err = _run(["--root", str(root), "--out", str(destination)])
        self.assertEqual(code, 0, (out, err))
        self.assertEqual((destination / _MAPPED).read_bytes(), raw_a)
        self.assertEqual(out.strip(), hashlib.sha256(raw_a).hexdigest() + "  " + _MAPPED)

    def test_pure_snapshot_missing_input_never_reads_disk(self):
        raw = (_PRESETS / "cave_dense.json").read_bytes()
        side = (_PRESETS / "cave_dense.identity.json").read_bytes()
        with mock.patch("builtins.open", side_effect=AssertionError("pure validation read disk")):
            self.assertEqual(exporter.scene.check_preset_snapshots("content/presets/cave_dense.json", raw, side), [])
            self.assertIn("missing preset snapshot", exporter.scene.check_preset_snapshots(
                "content/presets/cave_dense.json", None, side)[0])
            self.assertIn("missing identity sidecar snapshot", exporter.scene.check_preset_snapshots(
                "content/presets/cave_dense.json", raw, None)[0])

    def test_exporter_source_safety_without_tree_validator(self):
        for rel in ("content/presets/cave_dense.json", _SIDECAR):
            with self.subTest(rel=rel):
                root = self._content_copy("nonregular-" + str(len(list(self.tmp.iterdir()))))
                path = root / rel
                path.unlink()
                path.mkdir()
                code, out, err = _run(["--root", str(root)])
                self.assertEqual(code, 1, err)
                self.assertIn(rel + ": nonregular file refused", out)

    def test_observable_source_reparse_point_refused_without_symlinks(self):
        root = self._content_copy("reparse")
        original = exporter.scene.os.lstat
        unsafe = root / _SIDECAR

        def reparse(path):
            info = original(path)
            if Path(path) == unsafe:
                return type("ReparseInfo", (), {"st_mode": info.st_mode, "st_file_attributes": 0x400})()
            return info

        with mock.patch.object(exporter.scene.os, "lstat", side_effect=reparse):
            code, out, err = _run(["--root", str(root)])
        self.assertEqual(code, 1, err)
        self.assertIn(_SIDECAR + ": symlink or reparse point refused", out)

    @unittest.skipUnless(_SYMLINKS, "symlinks unavailable")
    def test_symlink_sources_and_source_ancestors_refused(self):
        for rel in ("content/presets/cave_dense.json", _SIDECAR, "content/presets", "content"):
            with self.subTest(rel=rel):
                root = self._content_copy("link-" + str(len(list(self.tmp.iterdir()))))
                path = root / rel
                target = self.tmp / ("target-" + str(len(list(self.tmp.iterdir()))))
                path.rename(target)
                path.symlink_to(target, target_is_directory=target.is_dir())
                code, out, err = _run(["--root", str(root)])
                self.assertEqual(code, 1, err)
                self.assertIn("symlink", out)

    def test_staging_and_publication_failures_rollback_then_retry_on_all_platforms(self):
        original = exporter._OwnedPaths.write
        for phase in ("stage", "publication"):
            for existed in (False, True):
                with self.subTest(phase=phase, existed=existed):
                    path, destination = self._destination(existed, phase + str(existed))
                    info = path.stat() if existed else None
                    writes = []

                    def fail_second(owned, target, data):
                        in_output = str(target).startswith(str(path) + os.sep)
                        selected = in_output if phase == "publication" else not in_output
                        if selected:
                            writes.append(target)
                            if len(writes) == 2:
                                raise OSError("injected second %s write" % phase)
                        return original(owned, target, data)

                    with mock.patch.object(exporter._OwnedPaths, "write", new=fail_second):
                        with self.assertRaisesRegex(exporter.ExportError, "injected second " + phase + " write"):
                            exporter.write_out(self._files(), destination, str(path))
                    self.assertEqual(len(writes), 2)
                    self._assert_clean(path, existed, info)
                    self._assert_retry(path)

    def test_partial_write_and_close_failures_rollback_then_retry(self):
        real_open = open
        for failure in ("write", "close"):
            for phase in ("stage", "publication"):
                for existed in (False, True):
                    with self.subTest(failure=failure, phase=phase, existed=existed):
                        path, destination = self._destination(existed, failure + phase + str(existed))
                        info = path.stat() if existed else None
                        injected = []

                        class FaultyHandle:
                            def __init__(self, handle):
                                self.handle = handle
                            def fileno(self):
                                return self.handle.fileno()
                            def flush(self):
                                return self.handle.flush()
                            def write(self, data):
                                if failure == "write":
                                    self.handle.write(data[:3])
                                    raise OSError("injected partial write")
                                return self.handle.write(data)
                            def close(self):
                                self.handle.close()
                                if failure == "close":
                                    raise OSError("injected close failure")

                        def faulty_open(target, mode="r", *args, **kwargs):
                            handle = real_open(target, mode, *args, **kwargs)
                            in_output = str(target).startswith(str(path) + os.sep)
                            selected = in_output if phase == "publication" else not in_output
                            if mode == "xb" and selected and not injected:
                                injected.append(target)
                                return FaultyHandle(handle)
                            return handle

                        with mock.patch.object(exporter, "open", side_effect=faulty_open, create=True):
                            with self.assertRaisesRegex(exporter.ExportError, "injected " + ("partial write" if failure == "write" else "close failure")):
                                exporter.write_out(self._files(), destination, str(path))
                        self.assertEqual(len(injected), 1)
                        self._assert_clean(path, existed, info)
                        self._assert_retry(path)

    def _assert_write_boundary_mutation_is_retained(self, truncate):
        real_open = open
        for phase in ("stage", "publication"):
            for existed in (False, True):
                with self.subTest(phase=phase, existed=existed, truncate=truncate):
                    path, destination = self._isolated_destination(existed, "boundary-%s-%s-%s" %
                                                         (truncate, phase, existed))
                    before = path.stat() if existed else None
                    injected = []
                    written = []
                    external_bytes = []

                    class MutatingHandle:
                        def __init__(self, handle, target):
                            self.handle = handle
                            self.target = target
                            self.data = None
                        def fileno(self):
                            return self.handle.fileno()
                        def write(self, data):
                            self.data = data
                            count = self.handle.write(data)
                            written.append(count)
                            return count
                        def flush(self):
                            self.handle.flush()
                            # A second writer changes the same file after the full write,
                            # before _OwnedPaths captures its final descriptor metadata.
                            with real_open(self.target, "r+b", buffering=0) as other:
                                if truncate:
                                    other.truncate(3)
                                    external_bytes.append(self.data[:3])
                                else:
                                    replacement = b"x" * len(self.data)
                                    other.write(replacement)
                                    external_bytes.append(replacement)
                        def close(self):
                            self.handle.close()

                    def mutating_open(target, mode="r", *args, **kwargs):
                        handle = real_open(target, mode, *args, **kwargs)
                        in_output = str(target).startswith(str(path) + os.sep)
                        selected = in_output if phase == "publication" else not in_output
                        if mode == "xb" and selected and not injected:
                            injected.append(Path(target))
                            return MutatingHandle(handle, target)
                        return handle

                    with mock.patch.object(exporter, "open", side_effect=mutating_open, create=True):
                        with self.assertRaisesRegex(exporter.ExportError, "output file changed") as caught:
                            exporter.write_out(self._files(), destination, str(path))
                    self.assertEqual(len(injected), 1)
                    self.assertEqual(written, [len(self._files()[0][2])])
                    self.assertEqual(len(external_bytes), 1)
                    message = str(caught.exception)
                    self.assertIn(str(injected[0]) + ": output file changed", message)
                    self.assertIn("cleanup uncertain; retained paths:", message)
                    self.assertIn(str(injected[0]), message.split("retained paths:", 1)[1])
                    self.assertIn("stage:", message)
                    self.assertEqual(injected[0].read_bytes(), external_bytes[0])
                    if existed:
                        self.assertEqual(exporter.scene.path_identity(path.stat()),
                                         exporter.scene.path_identity(before))
                    if phase == "stage":
                        self.assertEqual(len(list(path.parent.glob(".scene-export-*"))), 1)
                        if existed:
                            self.assertEqual(list(path.iterdir()), [])
                            self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)
                        else:
                            self.assertFalse(path.exists())
                    else:
                        self.assertTrue(path.is_dir())
                        self.assertEqual(list(path.rglob("*.json")), injected)
                        self.assertEqual(list(path.parent.glob(".scene-export-*")), [])

    def test_overwrite_during_flush_is_refused_and_external_bytes_retained(self):
        self._assert_write_boundary_mutation_is_retained(truncate=False)

    def test_full_write_truncated_during_flush_is_refused_and_prefix_retained(self):
        self._assert_write_boundary_mutation_is_retained(truncate=True)

    @staticmethod
    def _file_version_with_stable_creation_time(info):
        # Simulate unchanged Windows creation time on Ubuntu as well. In-place
        # writes change POSIX ctime even when length and mtime are restored.
        return exporter.scene.path_identity(info) + (info.st_size, info.st_mtime_ns, 0)

    def _overwrite_verified_file(self, target):
        target = Path(target)
        before = target.stat()
        original = target.read_bytes()
        external = b"x" * len(original)
        self.assertNotEqual(original, external)
        with open(target, "r+b", buffering=0) as handle:
            self.assertEqual(handle.write(external), len(external))
        os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(exporter.scene.file_version(target.stat()),
                         exporter.scene.file_version(before))
        return external

    def _assert_verified_overwrite_retained(self, path, existed, before, changed, external, phase, message):
        self.assertIn("cleanup uncertain; retained paths:", message)
        self.assertIn(str(changed), message.split("retained paths:", 1)[1])
        self.assertIn("output file changed", message)
        self.assertIn("stage:", message)
        self.assertEqual(changed.read_bytes(), external)
        if existed:
            self.assertEqual(exporter.scene.path_identity(path.stat()),
                             exporter.scene.path_identity(before))
        stages = list(path.parent.glob(".scene-export-*"))
        if phase == "stage":
            self.assertEqual(len(stages), 1)
            self.assertIn(str(stages[0]), message.split("stage:", 1)[1])
            self.assertEqual(list(stages[0].rglob("*.json")), [changed])
            if existed:
                self.assertEqual(list(path.iterdir()), [])
                self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)
            else:
                self.assertFalse(path.exists())
        else:
            self.assertEqual(stages, [])
            self.assertEqual(list(path.rglob("*.json")), [changed])

    def test_verified_overwrite_before_rollback_preserves_external_bytes_and_original_error(self):
        original_write = exporter._OwnedPaths.write
        for phase in ("stage", "publication"):
            for existed in (False, True):
                with self.subTest(phase=phase, existed=existed):
                    path, destination = self._isolated_destination(existed, "verified-rollback-%s-%s" % (phase, existed))
                    before = path.stat() if existed else None
                    writes = []
                    external = []
                    failure = "injected second %s write after verification" % phase

                    def fail_after_overwrite(owned, target, data):
                        in_output = str(target).startswith(str(path) + os.sep)
                        selected = in_output if phase == "publication" else not in_output
                        if selected and writes:
                            # The first write returned only after verification. Mutate
                            # now, so no publication guard runs before rollback.
                            external.append(self._overwrite_verified_file(writes[0]))
                            raise OSError(failure)
                        result = original_write(owned, target, data)
                        if selected:
                            writes.append(Path(target))
                        return result

                    with mock.patch.object(exporter.scene, "file_version",
                                           side_effect=self._file_version_with_stable_creation_time), \
                            mock.patch.object(exporter._OwnedPaths, "write", new=fail_after_overwrite):
                        with self.assertRaisesRegex(exporter.ExportError, failure) as caught:
                            exporter.write_out(self._files(), destination, str(path))
                    self.assertEqual(len(external), 1)
                    self._assert_verified_overwrite_retained(path, existed, before, writes[0], external[0],
                                                            phase, str(caught.exception))

    def test_verified_stage_overwrite_before_publication_is_refused_and_retained(self):
        original_write = exporter._OwnedPaths.write
        for existed in (False, True):
            with self.subTest(existed=existed):
                path, destination = self._isolated_destination(existed, "verified-stage-%s" % existed)
                before = path.stat() if existed else None
                writes = []
                external = []

                def overwrite_closed_stage(owned, target, data):
                    result = original_write(owned, target, data)
                    if not str(target).startswith(str(path) + os.sep):
                        writes.append(Path(target))
                        if len(writes) == len(self._files()):
                            external.append(self._overwrite_verified_file(writes[0]))
                    return result

                with mock.patch.object(exporter.scene, "file_version",
                                       side_effect=self._file_version_with_stable_creation_time), \
                        mock.patch.object(exporter._OwnedPaths, "write", new=overwrite_closed_stage):
                    with self.assertRaisesRegex(exporter.ExportError, "staged file changed") as caught:
                        exporter.write_out(self._files(), destination, str(path))
                self.assertEqual(len(external), 1)
                self._assert_verified_overwrite_retained(path, existed, before, writes[0], external[0],
                                                        "stage", str(caught.exception))

    def test_stage_overwrite_at_prepublication_guard_is_bounded_and_destination_untouched(self):
        original_guard = exporter._publication_guard
        real_fdopen = exporter.scene.os.fdopen
        for existed in (False, True):
            with self.subTest(existed=existed):
                path, destination = self._isolated_destination(existed, "snapshot-overwrite-%s" % existed)
                before = path.stat() if existed else None
                changed = []
                external = []
                readers = []

                def overwrite_at_guard(destination, owned, *, initial=False):
                    original_guard(destination, owned, initial=initial)
                    stages = list(path.parent.glob(".scene-export-*")) if initial else []
                    if stages and not changed:
                        changed.append(stages[0] / self._files()[0][0])
                        external.append(self._overwrite_verified_file(changed[0]))

                def bounded_fdopen(fd, *args, **kwargs):
                    handle = real_fdopen(fd, *args, **kwargs)
                    if changed and not readers and exporter.scene.path_identity(os.fstat(fd)) == \
                            exporter.scene.path_identity(changed[0].stat()):
                        reader = _BoundedReader(handle, len(self._files()[0][2]))
                        readers.append(reader)
                        return reader
                    return handle

                with mock.patch.object(exporter.scene, "file_version",
                                       side_effect=self._file_version_with_stable_creation_time), \
                        mock.patch.object(exporter, "_publication_guard", side_effect=overwrite_at_guard), \
                        mock.patch.object(exporter.scene.os, "fdopen", side_effect=bounded_fdopen), \
                        mock.patch.object(exporter.os, "mkdir", wraps=exporter.os.mkdir) as mkdir:
                    with self.assertRaisesRegex(exporter.ExportError, "staged file changed") as caught:
                        exporter.write_out(self._files(), destination, str(path))
                self.assertEqual(len(readers), 1)
                self.assertEqual(sum(readers[0].returned_sizes), len(self._files()[0][2]))
                self.assertTrue(readers[0].handle.closed)
                self.assertFalse(any(str(call.args[0]) == str(path) or
                                     str(call.args[0]).startswith(str(path) + os.sep)
                                     for call in mkdir.call_args_list))
                message = str(caught.exception)
                self.assertIn("cannot write output: staged file changed: %s: output file changed" % changed[0],
                              message.split("; cleanup uncertain", 1)[0])
                self._assert_verified_overwrite_retained(path, existed, before, changed[0], external[0],
                                                        "stage", message)

    def test_stage_growth_during_snapshot_is_bounded_and_destination_untouched(self):
        original_guard = exporter._publication_guard
        real_fdopen = exporter.scene.os.fdopen
        for existed in (False, True):
            with self.subTest(existed=existed):
                path, destination = self._isolated_destination(existed, "snapshot-growth-%s" % existed)
                before = path.stat() if existed else None
                selected = []
                readers = []
                initial = self._files()[0][2]

                def select_at_guard(destination, owned, *, initial=False):
                    original_guard(destination, owned, initial=initial)
                    stages = list(path.parent.glob(".scene-export-*")) if initial else []
                    if stages and not selected:
                        selected.append(stages[0] / self._files()[0][0])

                def growing_fdopen(fd, *args, **kwargs):
                    handle = real_fdopen(fd, *args, **kwargs)
                    if selected and not readers and exporter.scene.path_identity(os.fstat(fd)) == \
                            exporter.scene.path_identity(selected[0].stat()):
                        reader = _GrowingReader(handle, selected[0], initial)
                        readers.append(reader)
                        return reader
                    return handle

                with mock.patch.object(exporter, "_publication_guard", side_effect=select_at_guard), \
                        mock.patch.object(exporter.scene.os, "fdopen", side_effect=growing_fdopen), \
                        mock.patch.object(exporter.os, "mkdir", wraps=exporter.os.mkdir) as mkdir:
                    with self.assertRaisesRegex(exporter.ExportError, "staged file changed") as caught:
                        exporter.write_out(self._files(), destination, str(path))
                self.assertEqual(len(readers), 1)
                self._assert_growth_reader_bounded(readers[0], len(initial))
                self.assertFalse(any(str(call.args[0]) == str(path) or
                                     str(call.args[0]).startswith(str(path) + os.sep)
                                     for call in mkdir.call_args_list))
                message = str(caught.exception)
                self.assertIn("cannot write output: staged file changed: %s: " % selected[0],
                              message.split("; cleanup uncertain", 1)[0])
                self.assertIn("size increased", message.split("; cleanup uncertain", 1)[0])
                self._assert_verified_overwrite_retained(path, existed, before, selected[0], readers[0].external,
                                                        "stage", message)

    def test_publication_uses_single_verified_stage_snapshots(self):
        path, destination = self._destination()
        original_verify = exporter._OwnedPaths.verify_file
        original_cleanup = exporter._OwnedPaths.cleanup
        original_stream = exporter.scene.stream_safe_file
        captures = []
        cleaning = []

        def verify_snapshot(owned, target, *, capture=False):
            data = original_verify(owned, target, capture=capture)
            if capture:
                captures.append((target, data))
            return data

        def start_cleanup(owned):
            cleaning.append(owned)
            return original_cleanup(owned)

        def refuse_stage_publication_read(target, *args, **kwargs):
            if path.exists() and not cleaning and ".scene-export-" in str(target):
                raise AssertionError("stage reopened during publication")
            return original_stream(target, *args, **kwargs)

        with mock.patch.object(exporter._OwnedPaths, "verify_file", new=verify_snapshot), \
                mock.patch.object(exporter._OwnedPaths, "cleanup", new=start_cleanup), \
                mock.patch.object(exporter.scene, "stream_safe_file", side_effect=refuse_stage_publication_read):
            exporter.write_out(self._files(), destination, str(path))
        self.assertEqual(len(captures), len(self._files()))
        for (target, snapshot), (mapped, _, data) in zip(captures, self._files()):
            self.assertTrue(target.endswith(os.path.join(*mapped.split("/"))))
            self.assertEqual(snapshot, data)
            self.assertEqual((path / mapped).read_bytes(), snapshot)
        self.assertEqual(list(path.parent.glob(".scene-export-*")), [])

    def test_verified_output_overwrite_before_final_acceptance_is_refused_and_retained(self):
        original_write = exporter._OwnedPaths.write
        original_cleanup = exporter._OwnedPaths.cleanup
        for boundary in ("last-write", "stage-cleanup"):
            for existed in (False, True):
                with self.subTest(boundary=boundary, existed=existed):
                    path, destination = self._destination(existed, "verified-acceptance-%s-%s" %
                                                         (boundary, existed))
                    before = path.stat() if existed else None
                    writes = []
                    external = []
                    changed = path / self._files()[0][0]

                    def overwrite_after_last_write(owned, target, data):
                        result = original_write(owned, target, data)
                        if boundary == "last-write" and str(target).startswith(str(path) + os.sep):
                            writes.append(target)
                            if len(writes) == len(self._files()):
                                external.append(self._overwrite_verified_file(changed))
                        return result

                    def overwrite_after_stage_cleanup(owned):
                        result = original_cleanup(owned)
                        if boundary == "stage-cleanup" and not external:
                            # All writes and the pre-cleanup publication guard already
                            # succeeded. The final acceptance guard must reread bytes.
                            external.append(self._overwrite_verified_file(changed))
                        return result

                    with mock.patch.object(exporter.scene, "file_version",
                                           side_effect=self._file_version_with_stable_creation_time), \
                            mock.patch.object(exporter._OwnedPaths, "write", new=overwrite_after_last_write), \
                            mock.patch.object(exporter._OwnedPaths, "cleanup", new=overwrite_after_stage_cleanup):
                        with self.assertRaisesRegex(exporter.ExportError, "output file changed") as caught:
                            exporter.write_out(self._files(), destination, str(path))
                    self.assertEqual(len(external), 1)
                    self._assert_verified_overwrite_retained(path, existed, before, changed, external[0],
                                                            "publication", str(caught.exception))

    def test_success_and_prepublication_failure_preserve_existing_empty_identity(self):
        path, destination = self._destination(True, "existing")
        before = path.stat()
        original = exporter._publication_guard
        calls = []

        def fail_boundary(destination, owned, *, initial=False):
            original(destination, owned, initial=initial)
            if initial:
                calls.append(1)
                if len(calls) == 2:
                    raise OSError("injected prepublication failure")

        with mock.patch.object(exporter, "_publication_guard", side_effect=fail_boundary):
            with self.assertRaisesRegex(exporter.ExportError, "injected prepublication failure"):
                exporter.write_out(self._files(), destination, str(path))
        self._assert_clean(path, True, before)
        self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)
        self._assert_retry(path)
        self.assertEqual(exporter.scene.path_identity(path.stat()), exporter.scene.path_identity(before))

    def test_cleanup_failure_reports_retained_owned_stage_and_rolls_back_destination(self):
        path, destination = self._destination()
        original = exporter.os.unlink
        injected = []

        def refuse_stage_unlink(target, *args, **kwargs):
            if ".scene-export-" in str(target) and not injected:
                injected.append(Path(target))
                raise PermissionError("injected cleanup denial")
            return original(target, *args, **kwargs)

        with mock.patch.object(exporter.os, "unlink", side_effect=refuse_stage_unlink):
            with self.assertRaisesRegex(exporter.ExportError, "cleanup uncertain; retained paths:") as caught:
                exporter.write_out(self._files(), destination, str(path))
        self.assertIn("injected cleanup denial", str(caught.exception))
        self.assertIn("stage:", str(caught.exception))
        self.assertTrue(injected[0].is_file())
        self.assertFalse(path.exists())

    def test_unknown_stage_content_is_retained_and_success_refused(self):
        path, destination = self._destination()
        original = exporter._publication_guard
        keep = []

        def populate_stage(destination, owned, *, initial=False):
            if initial and not keep:
                stages = list(path.parent.glob(".scene-export-*"))
                if stages:
                    keep.append(stages[0] / "user-file")
                    keep[0].write_bytes(b"external stage data")
            return original(destination, owned, initial=initial)

        with mock.patch.object(exporter, "_publication_guard", side_effect=populate_stage):
            with self.assertRaisesRegex(exporter.ExportError, "cleanup uncertain"):
                exporter.write_out(self._files(), destination, str(path))
        self.assertEqual(keep[0].read_bytes(), b"external stage data")
        self.assertFalse(path.exists())

    def test_prepublication_external_population_and_empty_replacement_refused(self):
        for kind in ("file", "directory", "replacement", "disappearance", "new-empty"):
            with self.subTest(kind=kind):
                existed = kind != "new-empty"
                path, destination = self._destination(existed, kind)
                original = exporter._publication_guard
                calls = []
                saved = self.tmp / (kind + "-saved")

                def race(destination, owned, *, initial=False):
                    if initial:
                        calls.append(1)
                        if len(calls) == 2:
                            if kind == "file":
                                (path / "user-file").write_bytes(b"external bytes")
                            elif kind == "directory":
                                (path / "user-dir").mkdir()
                                (path / "user-dir/keep").write_bytes(b"external bytes")
                            elif kind == "new-empty":
                                path.mkdir()
                            else:
                                path.rename(saved)
                                if kind == "replacement":
                                    path.mkdir()
                    return original(destination, owned, initial=initial)

                reason = ("became populated" if kind in ("file", "directory") else
                          "originally absent destination appeared" if kind == "new-empty" else
                          "destination or ancestor changed" if kind == "replacement" else "cannot write output")
                with mock.patch.object(exporter, "_publication_guard", side_effect=race):
                    with self.assertRaisesRegex(exporter.ExportError, reason):
                        exporter.write_out(self._files(), destination, str(path))
                if kind == "file":
                    self.assertEqual((path / "user-file").read_bytes(), b"external bytes")
                elif kind == "directory":
                    self.assertEqual((path / "user-dir/keep").read_bytes(), b"external bytes")
                elif kind == "disappearance":
                    self.assertFalse(path.exists())
                    self.assertEqual(list(saved.iterdir()), [])
                else:
                    self.assertEqual(list(path.iterdir()), [])
                self.assertEqual(list(path.parent.glob(".scene-export-*")), [])

    def test_commit_races_preserve_external_files_directories_and_changed_owned_bytes(self):
        original = exporter._OwnedPaths.write
        for kind in ("file", "directory", "owned-change", "destination-replacement"):
            with self.subTest(kind=kind):
                path, destination = self._destination(False, "commit-" + kind)
                keep = []
                saved = self.tmp / ("saved-" + kind)

                def race(owned, target, data):
                    result = original(owned, target, data)
                    if str(target).startswith(str(path) + os.sep) and not keep:
                        if kind == "owned-change":
                            keep.append(Path(target))
                        elif kind == "destination-replacement":
                            path.rename(saved)
                            path.mkdir()
                            keep.append(path / "user-file")
                        elif kind == "directory":
                            (path / "user-dir").mkdir()
                            keep.append(path / "user-dir/keep")
                        else:
                            keep.append(path / "user-file")
                        keep[0].write_bytes(b"external bytes")
                    return result

                reason = ("output file changed" if kind == "owned-change" else
                          "destination or ancestor changed" if kind == "destination-replacement" else
                          "destination contains external data")
                with mock.patch.object(exporter._OwnedPaths, "write", new=race):
                    with self.assertRaisesRegex(exporter.ExportError, reason):
                        exporter.write_out(self._files(), destination, str(path))
                self.assertEqual(keep[0].read_bytes(), b"external bytes")
                if kind == "destination-replacement":
                    self.assertEqual((saved / self._files()[0][0]).read_bytes(), self._files()[0][2])

    def test_exclusive_create_refuses_racing_leaf_even_after_checks(self):
        path, destination = self._destination()
        original = exporter._OwnedPaths.write
        keep = []

        def occupy(owned, target, data):
            if str(target).startswith(str(path) + os.sep) and not keep:
                keep.append(Path(target))
                keep[0].write_bytes(b"external occupied leaf")
            return original(owned, target, data)

        with mock.patch.object(exporter._OwnedPaths, "write", new=occupy):
            with self.assertRaisesRegex(exporter.ExportError, "File exists|already exists") as caught:
                exporter.write_out(self._files(), destination, str(path))
        self.assertIn(str(keep[0]), str(caught.exception))
        self.assertEqual(keep[0].read_bytes(), b"external occupied leaf")

    def test_observed_ancestor_replacement_is_refused_and_external_data_survives(self):
        parent = self.tmp / "ancestor"
        parent.mkdir()
        path = parent / "out"
        destination = exporter.check_destination(str(path), str(_REPO))
        saved = self.tmp / "saved-ancestor"
        parent.rename(saved)
        parent.mkdir()
        (parent / "keep").write_bytes(b"external ancestor bytes")
        with self.assertRaisesRegex(exporter.ExportError, "destination or ancestor changed"):
            exporter.write_out(self._files(), destination, str(path))
        self.assertEqual((parent / "keep").read_bytes(), b"external ancestor bytes")
        self.assertEqual(list(saved.iterdir()), [])

    @unittest.skipUnless(_SYMLINKS, "symlinks unavailable")
    def test_observed_content_git_alias_and_symlink_leaf_races_preserve_targets(self):
        for kind in ("content", "git", "leaf"):
            with self.subTest(kind=kind):
                path = self.tmp / ("symlink-" + kind)
                root = self._content_copy("symlink-root-" + kind)
                destination = exporter.check_destination(str(path), str(root))
                target = self.tmp / ("target-" + kind)
                target.mkdir()
                (target / "keep").write_bytes(b"external target bytes")
                if kind != "leaf":
                    # Inject a changed alias at the typed destination before the first boundary.
                    if kind == "git":
                        protected = self.tmp / ".GIT"
                        protected.mkdir()
                    else:
                        protected = root / "content"
                    (protected / "keep").write_bytes(b"external protected bytes")
                    path.symlink_to(protected, target_is_directory=True)
                    with self.assertRaisesRegex(exporter.ExportError, "refuses to write inside"):
                        exporter.write_out(self._files(), destination, str(path))
                    self.assertEqual((protected / "keep").read_bytes(), b"external protected bytes")
                else:
                    original = exporter._OwnedPaths.write

                    def occupy(owned, leaf, data):
                        if str(leaf).startswith(str(path) + os.sep):
                            Path(leaf).symlink_to(target / "keep")
                        return original(owned, leaf, data)

                    with mock.patch.object(exporter._OwnedPaths, "write", new=occupy):
                        with self.assertRaisesRegex(exporter.ExportError, "File exists|already exists"):
                            exporter.write_out(self._files(), destination, str(path))
                self.assertEqual((target / "keep").read_bytes(), b"external target bytes")

    def test_owned_new_parents_rollback_and_zero_mapped_files(self):
        path = self.tmp / "new-parent" / "child" / "out"
        destination = exporter.check_destination(str(path), str(_REPO))
        with mock.patch.object(exporter._OwnedPaths, "write", side_effect=OSError("injected staging failure")):
            with self.assertRaisesRegex(exporter.ExportError, "injected staging failure"):
                exporter.write_out(self._files(), destination, str(path))
        self.assertFalse((self.tmp / "new-parent").exists())
        for existed in (False, True):
            empty, destination = self._destination(existed, "zero" + str(existed))
            before = empty.stat() if existed else None
            exporter.write_out([], destination, str(empty))
            self.assertEqual(list(empty.iterdir()), [])
            if existed:
                self.assertEqual(exporter.scene.path_identity(empty.stat()), exporter.scene.path_identity(before))
        self.assertEqual(list(self.tmp.glob(".scene-export-*")), [])


    def test_validation_failure_preserves_existing_empty_identity_and_metadata(self):
        root = self._content_copy("invalid-existing")
        preset = root / "content/presets/cave_dense.json"
        preset.write_bytes(preset.read_bytes().replace(b'"max_feature_radius": 52.0',
                                                     b'"max_feature_radius": 110.0', 1))
        path, _ = self._destination(True, "validation-empty")
        before = path.stat()
        code, out, err = _run(["--root", str(root), "--out", str(path)])
        self.assertEqual(code, 1, err)
        self.assertIn("max_feature_radius must be less than feature_cell_size", out)
        self._assert_clean(path, True, before)
        self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)

    def test_check_uses_captured_pair_when_sources_change_after_loading(self):
        root = self._content_copy("check-snapshot")
        raw_a = (root / "content/presets/cave_dense.json").read_bytes()
        engine = self.tmp / "check-engine"
        (engine / _MAPPED).parent.mkdir(parents=True)
        (engine / _MAPPED).write_bytes(raw_a)
        original = exporter._read_bytes

        def change_after_sidecar(rel, full):
            captured = original(rel, full)
            if rel == _SIDECAR:
                (root / "content/presets/cave_dense.json").write_bytes(b"changed on disk")
            return captured

        with mock.patch.object(exporter, "_read_bytes", side_effect=change_after_sidecar):
            code, out, err = _run(["--root", str(root), "--check", str(engine)])
        self.assertEqual(code, 0, (out, err))
        self.assertEqual(out, "")
        self.assertEqual((engine / _MAPPED).read_bytes(), raw_a)

    def test_substituted_stage_is_retained_without_deleting_external_content(self):
        path, destination = self._destination()
        original = exporter._publication_guard
        moved_stage = self.tmp / "moved-stage"
        substituted = []

        def replace_stage(destination, owned, *, initial=False):
            if initial and not substituted:
                stages = list(path.parent.glob(".scene-export-*"))
                if stages:
                    stage = stages[0]
                    stage.rename(moved_stage)
                    stage.mkdir()
                    substituted.append(stage / "external")
                    substituted[0].write_bytes(b"unknown replacement stage bytes")
            return original(destination, owned, initial=initial)

        with mock.patch.object(exporter, "_publication_guard", side_effect=replace_stage):
            with self.assertRaisesRegex(exporter.ExportError, "cleanup uncertain") as caught:
                exporter.write_out(self._files(), destination, str(path))
        self.assertIn("stage:", str(caught.exception))
        self.assertEqual(substituted[0].read_bytes(), b"unknown replacement stage bytes")
        self.assertEqual((moved_stage / self._files()[0][0]).read_bytes(), self._files()[0][2])
        self.assertFalse(path.exists())

    def test_injected_directory_at_exclusive_create_is_preserved(self):
        path, destination = self._destination()
        original = exporter._OwnedPaths.mkdir
        keep = []

        def occupy(owned, target):
            if target == str(path / "worlds") and not keep:
                Path(target).mkdir()
                keep.append(Path(target) / "keep")
                keep[0].write_bytes(b"external directory bytes")
            return original(owned, target)

        with mock.patch.object(exporter._OwnedPaths, "mkdir", new=occupy):
            with self.assertRaisesRegex(exporter.ExportError, "File exists|already exists") as caught:
                exporter.write_out(self._files(), destination, str(path))
        self.assertIn(str(keep[0].parent), str(caught.exception))
        self.assertEqual(keep[0].read_bytes(), b"external directory bytes")

    def test_exclusive_create_access_denied_collision_preserves_external_data(self):
        real_open = open
        for kind in ("file", "directory"):
            with self.subTest(kind=kind):
                path, destination = self._isolated_destination(False, "denied-" + kind)
                keep = []

                def occupy(target, mode="r", *args, **kwargs):
                    if mode == "xb" and str(target).startswith(str(path) + os.sep) and not keep:
                        leaf = Path(target)
                        if kind == "directory":
                            leaf.mkdir()
                            leaf = leaf / "keep"
                        leaf.write_bytes(b"external occupied bytes")
                        keep.append(leaf)
                        # Windows can report access denied instead of EEXIST.
                        raise PermissionError("injected exclusive-create denial")
                    return real_open(target, mode, *args, **kwargs)

                with mock.patch.object(exporter, "open", side_effect=occupy, create=True):
                    with self.assertRaisesRegex(exporter.ExportError, "already exists"):
                        exporter.write_out(self._files(), destination, str(path))
                self.assertEqual(keep[0].read_bytes(), b"external occupied bytes")
                self.assertEqual(list(path.parent.glob(".scene-export-*")), [])

    def test_created_stage_without_readable_identity_is_reported_and_retained(self):
        path, destination = self._destination()
        original = exporter.os.lstat
        created = []

        def unreadable(path, *args, **kwargs):
            if Path(path).name.startswith(".scene-export-") and not created:
                created.append(Path(path))
                raise OSError("injected stage identity failure")
            return original(path, *args, **kwargs)

        with mock.patch.object(exporter.os, "lstat", side_effect=unreadable):
            with self.assertRaisesRegex(exporter.ExportError, "cleanup uncertain") as caught:
                exporter.write_out(self._files(), destination, str(path))
        self.assertIn("injected stage identity failure", str(caught.exception))
        self.assertIn("created path identity could not be established", str(caught.exception))
        self.assertTrue(created[0].is_dir())
        self.assertFalse(path.exists())


    def test_output_change_during_stage_cleanup_is_refused_and_preserved(self):
        path, destination = self._destination()
        original = exporter.os.unlink
        changed = []

        def mutate_output(target, *args, **kwargs):
            result = original(target, *args, **kwargs)
            if ".scene-export-" in str(target) and not changed:
                changed.append(path / self._files()[0][0])
                changed[0].write_bytes(b"external change during cleanup")
            return result

        with mock.patch.object(exporter.os, "unlink", side_effect=mutate_output):
            with self.assertRaisesRegex(exporter.ExportError, "output file changed"):
                exporter.write_out(self._files(), destination, str(path))
        self.assertEqual(changed[0].read_bytes(), b"external change during cleanup")


    def test_windows_close_time_metadata_finalization_has_portable_source_coverage(self):
        path, destination = self._destination()
        real_open = open
        real_fstat = exporter.os.fstat
        captured = []
        state = {"closed": False}

        class FinalizingHandle:
            def __init__(self, handle):
                self.handle = handle
                captured.append(handle.fileno())
            def fileno(self):
                return self.handle.fileno()
            def write(self, data):
                return self.handle.write(data)
            def flush(self):
                return self.handle.flush()
            def close(self):
                self.handle.close()
                state["closed"] = True

        def finalizing_open(target, mode="r", *args, **kwargs):
            handle = real_open(target, mode, *args, **kwargs)
            if mode == "xb" and not captured:
                return FinalizingHandle(handle)
            return handle

        def before_close_stat(fd):
            info = real_fstat(fd)
            if captured and fd == captured[0] and not state["closed"]:
                return SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino, st_mode=info.st_mode,
                                       st_size=info.st_size, st_mtime_ns=info.st_mtime_ns - 100,
                                       st_ctime_ns=info.st_ctime_ns - 100,
                                       st_file_attributes=getattr(info, "st_file_attributes", 0),
                                       st_reparse_tag=getattr(info, "st_reparse_tag", 0))
            return info

        with mock.patch.object(exporter, "_CLOSE_TIME_FINALIZATION", True), \
                mock.patch.object(exporter, "open", side_effect=finalizing_open, create=True), \
                mock.patch.object(exporter.os, "fstat", side_effect=before_close_stat):
            exporter.write_out(self._files(), destination, str(path))
        self.assertTrue(captured)
        self.assertTrue(state["closed"])
        for mapped, _, data in self._files():
            self.assertEqual((path / mapped).read_bytes(), data)
        self.assertEqual(list(path.parent.glob(".scene-export-*")), [])


if __name__ == "__main__":
    unittest.main()
