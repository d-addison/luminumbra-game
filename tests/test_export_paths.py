"""Host-independent Windows filesystem regressions for export restrictions."""

import contextlib
import hashlib
import io
import ntpath
import os
import posixpath
import stat
import unittest
from types import SimpleNamespace
from unittest import mock

from test_export import exporter, _run


class _MemoryFile(io.BytesIO):
    def __init__(self, filesystem, descriptor):
        self.filesystem, self.descriptor = filesystem, descriptor
        super().__init__(filesystem.data[filesystem.descriptors[descriptor]])

    def fileno(self):
        return self.descriptor

    def write(self, data):
        count = super().write(data)
        self.filesystem.data[self.filesystem.descriptors[self.descriptor]] = self.getvalue()
        return count

    def close(self):
        self.filesystem.descriptors.pop(self.descriptor, None)
        super().close()


class _WindowsFilesystem:
    """An in-memory ntpath namespace with independent short names and symlinks.

    Non-strict resolution models Windows' missing-tail/readlink fallback,
    which can leave a short-name target unresolved or reset a drive on join.
    Strict resolution expands both kinds of alias and requires an existing target.
    """

    root = r"D:\repository"

    def __init__(self, content=True, windows=True):
        self.flavour = ntpath if windows else posixpath
        self.root = r"D:\repository" if windows else "/repository"
        self.nodes, self.data, self.aliases, self.links, self.spellings = {}, {}, {}, {}, {}
        self.descriptors, self.resolutions, self.created, self.writes = {}, [], [], []
        self.resolution_errors, self.resolution_results = {}, {}
        self.path = SimpleNamespace(**vars(self.flavour))
        self.path.abspath = self.abspath
        self.path.realpath = self.realpath
        self.path.lexists = self.lexists
        self.path.exists = self.exists
        self.path.isdir = self.isdir
        self.os = SimpleNamespace(**vars(os))
        self.os.path = self.path
        self.os.name, self.os.sep = ("nt", "\\") if windows else ("posix", "/")
        for method in ("lstat", "listdir", "mkdir", "rmdir", "unlink", "walk",
                       "fstat", "open", "fdopen", "close"):
            setattr(self.os, method, getattr(self, method))
        directories = (("D:\\", self.root, r"D:\out", r"D:\repository\.git", r"\\server\share")
                       if windows else ("/", self.root, "/out", "/repository/.git"))
        for directory in directories:
            self.add_directory(directory)
        if content:
            self.add_directory(self.flavour.join(self.root, "content"))
        if windows:
            self.aliases[self.key(r"D:\REPO")] = self.root
            self.aliases[self.key(self.root + r"\GITSAFE")] = self.root + r"\.git"
            self.aliases[self.key(self.root + r"\GIT~1")] = self.root + r"\.git"

    def key(self, path):
        path = self.flavour.normcase(self.flavour.normpath(path))
        if path.startswith("\\\\?\\unc\\"):
            path = "\\\\" + path[8:]
        elif path.startswith("\\\\?\\"):
            path = path[4:]
        drive, tail = self.flavour.splitdrive(path)
        if drive.startswith("\\\\") and tail == "\\":
            path = drive
        return path

    def abspath(self, path):
        return self.flavour.normpath(self.flavour.join(self.root, path))

    def canonical(self, path):
        path = self.key(self.abspath(path))
        for _ in range(20):
            for alias, target in {**self.aliases, **self.links}.items():
                if path == alias or path.startswith(alias + self.flavour.sep):
                    path = self.key(target) + path[len(alias):]
                    break
            else:
                return path
        raise OSError("alias cycle")

    def add_directory(self, path):
        self._add(path, stat.S_IFDIR)

    def _add(self, path, kind):
        key = self.canonical(path)
        self.spellings[key] = self.abspath(path)
        self.nodes[key] = SimpleNamespace(st_dev=1, st_ino=len(self.nodes) + 1,
                                         st_mode=kind | 0o700, st_size=0,
                                         st_mtime_ns=1, st_ctime_ns=1)
        if kind == stat.S_IFREG:
            self.data[key] = b""

    def symlink(self, path, target):
        self._add(path, stat.S_IFLNK)
        self.links[self.key(path)] = target

    def lstat(self, path):
        # An exact symlink exists even when its target is missing.
        key = self.key(self.abspath(path))
        if key not in self.links:
            key = self.canonical(path)
        if key not in self.nodes:
            raise FileNotFoundError(2, "not found", path)
        info = SimpleNamespace(**vars(self.nodes[key]))
        info.st_size = len(self.data.get(key, b""))
        return info

    def lexists(self, path):
        try:
            self.lstat(path)
            return True
        except FileNotFoundError:
            return False

    def exists(self, path):
        return self.canonical(path) in self.nodes

    def isdir(self, path):
        info = self.nodes.get(self.canonical(path))
        return info is not None and stat.S_ISDIR(info.st_mode)

    def realpath(self, path, *, strict=False):
        self.resolutions.append((path, strict))
        key = self.key(path)
        if key in self.resolution_errors:
            raise self.resolution_errors[key]
        if key in self.resolution_results:
            return self.resolution_results[key]
        if strict:
            if not self.exists(path):
                raise FileNotFoundError(2, "not found", path)
            resolved = self.spellings[self.canonical(path)]
            if path.startswith("\\\\?\\"):
                resolved = self.key(resolved)
                return ("\\\\?\\UNC\\" + resolved[2:] if resolved.startswith("\\\\")
                        else "\\\\?\\" + resolved)
            return resolved
        ancestor, tail = path, ""
        while not self.lexists(ancestor):
            parent, part = self.flavour.split(ancestor)
            if parent == ancestor or not part:
                return ancestor + tail
            tail = self.flavour.join(part, tail) if tail else part
            ancestor = parent
        resolved = self.links.get(self.key(ancestor), self.canonical(ancestor))
        return self.flavour.join(resolved, tail) if tail else resolved

    def listdir(self, path):
        key = self.canonical(path)
        return sorted(self.flavour.basename(child) for child in self.nodes
                      if child != key and self.key(self.flavour.dirname(child)) == key)

    def mkdir(self, path):
        if self.lexists(path):
            raise FileExistsError(17, "already exists", path)
        if not self.isdir(self.flavour.dirname(path)):
            raise FileNotFoundError(2, "parent not found", path)
        self.created.append(path)
        self.add_directory(path)

    def rmdir(self, path):
        if self.listdir(path):
            raise OSError(39, "directory not empty", path)
        del self.nodes[self.canonical(path)]

    def unlink(self, path):
        key = self.canonical(path)
        del self.nodes[key]
        del self.data[key]

    def walk(self, path, **kwargs):
        names = self.listdir(path)
        directories = [name for name in names if self.isdir(self.flavour.join(path, name))]
        yield path, directories, [name for name in names if name not in directories]
        for name in directories:
            yield from self.walk(self.flavour.join(path, name), **kwargs)

    def _descriptor(self, path):
        descriptor = max(self.descriptors, default=0) + 1
        self.descriptors[descriptor] = self.canonical(path)
        return descriptor

    def open_file(self, path, mode, **kwargs):
        if mode != "xb":
            raise AssertionError("publication must use exclusive binary writes")
        if self.lexists(path):
            raise FileExistsError(17, "already exists", path)
        self._add(path, stat.S_IFREG)
        self.writes.append(path)
        return _MemoryFile(self, self._descriptor(path))

    def open(self, path, flags):
        if not self.exists(path):
            raise FileNotFoundError(2, "not found", path)
        return self._descriptor(path)

    def fstat(self, descriptor):
        return self.lstat(self.descriptors[descriptor])

    def fdopen(self, descriptor, mode, **kwargs):
        return _MemoryFile(self, descriptor)

    def close(self, descriptor):
        del self.descriptors[descriptor]

    def mkdtemp(self, *, prefix, dir):
        path = self.flavour.join(dir, prefix + str(len(self.created)))
        self.mkdir(path)
        return path

    @contextlib.contextmanager
    def installed(self, files):
        # Patch module references, never the shared host os/ntpath modules.
        with mock.patch.object(exporter, "os", self.os), \
             mock.patch.object(exporter.scene, "os", self.os), \
             mock.patch.object(exporter, "REPO_ROOT", self.root), \
             mock.patch.object(exporter, "tempfile", SimpleNamespace(mkdtemp=self.mkdtemp)), \
             mock.patch.object(exporter, "open", self.open_file, create=True), \
             mock.patch.object(exporter, "collect_sources", return_value=[]), \
             mock.patch.object(exporter, "load_files", return_value=files):
            yield


class ExportPathRestrictionTests(unittest.TestCase):
    data = b"exported bytes\n"
    mapped = "worlds/atlas/presets/example.json"

    def files(self):
        return [(self.mapped, hashlib.sha256(self.data).hexdigest(), self.data)]

    def assert_refused(self, filesystem, out, reason, root=None):
        before = dict(filesystem.nodes)
        with filesystem.installed(self.files()):
            code, stdout, stderr = _run(["--root", root or filesystem.root, "--out", out])
            self.assertEqual(code, 2, stdout + stderr)
            self.assertEqual(stdout, "")
            self.assertIn(reason, stderr)
            with self.assertRaises(exporter.ExportError):
                exporter.write_out(self.files(), out, out)
        self.assertEqual(filesystem.nodes, before)
        self.assertEqual(filesystem.created, [])
        self.assertEqual(filesystem.writes, [])

    def test_embedded_drive_cannot_discard_literal_git_component(self):
        filesystem = _WindowsFilesystem()
        out = r".git/C:\Games\x.json"
        # Exercise the real Windows fallback shape independently of the host.
        legacy = filesystem.realpath(filesystem.abspath(out))
        self.assertFalse(ntpath.isabs(legacy), legacy)
        self.assertNotIn(".git", legacy)
        self.assert_refused(filesystem, out, "path with a .git component")

    def test_followed_links_expand_short_names_in_existing_ancestors(self):
        for target, reason in ((r"D:\repository\GITSAFE", ".git component"),
                               (r"D:\REPO\content", "content tree"),
                               (r"D:\repository\GIT~1", ".git component")):
            with self.subTest(target=target):
                filesystem = _WindowsFilesystem()
                filesystem.symlink(r"D:\out\link", target)
                out = r"D:\out\link\missing\export"
                self.assertEqual(filesystem.realpath(out), target + r"\missing\export")
                filesystem.resolutions.clear()
                self.assert_refused(filesystem, out, reason)
                self.assertIn((r"D:\out\link", True), filesystem.resolutions)
                self.assertTrue(all(strict for _, strict in filesystem.resolutions))

    def test_root_and_existing_content_directory_are_strictly_resolved(self):
        for root, content_target in ((r"D:\REPO", None),
                                     (r"D:\repository", r"D:\out\actual-content")):
            with self.subTest(root=root, content_target=content_target):
                filesystem = _WindowsFilesystem(content=content_target is None)
                if content_target:
                    filesystem.add_directory(content_target)
                    filesystem.symlink(filesystem.root + r"\content", content_target)
                out = (content_target or filesystem.root + r"\content") + r"\missing\export"
                self.assert_refused(filesystem, out, "content tree", root=root)
                self.assertIn((root, True), filesystem.resolutions)
                self.assertTrue(all(strict for _, strict in filesystem.resolutions))

    def test_missing_tail_normalization_devices_and_streams_exit_2(self):
        components = ("content ", "content.", "content .", ".git ", ".git.", ".GIT. ",
                      "CON", "nul.txt", "COM1", "LPT9.log", "COM¹", "LPT².txt",
                      "CONIN$", "CONOUT$", "NUL .txt", "content::$DATA", ".git::$DATA")
        for component in components:
            with self.subTest(component=component):
                filesystem = _WindowsFilesystem(content=False)
                # Neither protected spelling exists at this prefix.
                out = r"D:\out" + "\\" + component + r"\missing\export"
                self.assert_refused(filesystem, out, "Windows path component")
                self.assertTrue(all(strict for _, strict in filesystem.resolutions))
        for component in ("content ", "content."):
            with self.subTest(repository_component=component):
                filesystem = _WindowsFilesystem(content=False)
                out = filesystem.root + "\\" + component + r"\missing\export"
                self.assert_refused(filesystem, out, "unsafe missing Windows path component")

    def test_failed_strict_resolution_and_lost_anchor_are_refused(self):
        for location in (r"D:\out", r"D:\repository", r"D:\repository\content"):
            for failure in (PermissionError(13, "access denied"), "D:out", r"\out", r"\\server"):
                with self.subTest(location=location, failure=failure):
                    filesystem = _WindowsFilesystem()
                    key = filesystem.key(location)
                    if isinstance(failure, Exception):
                        filesystem.resolution_errors[key] = failure
                        reason = "access denied"
                    else:
                        filesystem.resolution_results[key] = failure
                        reason = "no absolute anchor"
                    self.assert_refused(filesystem, r"D:\out\missing\export", reason)
        filesystem = _WindowsFilesystem()
        filesystem.symlink(r"D:\out\dangling", r"D:\absent")
        self.assert_refused(filesystem, r"D:\out\dangling\export", "not found")

    def test_accepted_windows_paths_publish_exact_bytes(self):
        outputs = (r"D:\out\export", r"\\?\D:\out\export", r"\\server\share\export",
                   r"\\?\UNC\server\share\export", r"D:\out\.github\x", r"D:\out\x.git\y",
                   r"D:\out\ordinary~name\export", r"D:\out\GIT~1\export", r"D:\out\REPO~1\x")
        for out in outputs:
            for entry in ("main", "write_out"):
                with self.subTest(out=out, entry=entry):
                    filesystem = _WindowsFilesystem()
                    with filesystem.installed(self.files()):
                        if entry == "main":
                            code, stdout, stderr = _run(["--out", out])
                            self.assertEqual(code, 0, stdout + stderr)
                            self.assertEqual(stderr, "")
                        else:
                            exporter.write_out(self.files(), out, out)
                    target = filesystem.canonical(ntpath.join(out, *self.mapped.split("/")))
                    self.assertEqual(filesystem.data[target], self.data)
                    self.assertEqual(len(filesystem.writes), 2)
                    self.assertTrue(filesystem.resolutions)
                    self.assertTrue(all(strict for _, strict in filesystem.resolutions))
                    self.assertFalse(any(".scene-export-" in path for path in filesystem.nodes))

    def test_extended_paths_compare_with_unprefixed_content(self):
        filesystem = _WindowsFilesystem()
        self.assert_refused(filesystem, r"\\?\D:\repository\content\missing\export", "content tree")
        filesystem = _WindowsFilesystem()
        filesystem.symlink(r"D:\repository\content", r"\\server\share")
        self.assert_refused(filesystem, r"\\?\UNC\server\share\missing\export", "content tree")

    def test_existing_stream_ancestor_is_refused_before_creation(self):
        filesystem = _WindowsFilesystem()
        filesystem.add_directory(r"D:\out\streams::$DATA")
        self.assert_refused(filesystem, r"D:\out\streams::$DATA\missing\export", "stream suffix")

    def test_posix_keeps_windows_special_spellings_literal(self):
        outputs = ("/out/export", "/repository/content /missing/export",
                   "/repository/content./missing/export", "/out/.git /missing/export",
                   "/out/.git./missing/export", "/out/CON/export", "/out/NUL.txt/export",
                   "/out/content::$DATA/export", "/out/.git::$DATA/export", "/out/GIT~1/export")
        for out in outputs:
            with self.subTest(out=out):
                filesystem = _WindowsFilesystem(content=False, windows=False)
                with filesystem.installed(self.files()):
                    code, stdout, stderr = _run(["--out", out])
                    self.assertEqual(code, 0, stdout + stderr)
                    self.assertEqual(stderr, "")
                target = filesystem.canonical(posixpath.join(out, self.mapped))
                self.assertEqual(filesystem.data[target], self.data)
                self.assertTrue(all(strict for _, strict in filesystem.resolutions))
