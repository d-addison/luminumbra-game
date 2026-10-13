#!/usr/bin/env python3
"""Export game content to the engine's worlds/ layout.

Usage:
  python3 -I tools/export_engine_content.py                   print the manifest only
  python3 -I tools/export_engine_content.py --out DIR         write mapped files under DIR
  python3 -I tools/export_engine_content.py --check ENGINE_ROOT
                                                              compare with an engine tree

The only mapping at v0.3 is content/presets/<name>.json to
worlds/atlas/presets/<name>.json. Identity sidecars (*.identity.json) are not
exported, but each preset and its sibling sidecar are validated before anything
else happens against the exact captured bytes; any problem refuses the export. The --out destination is resolved
(symlinks included) and refused when the resolved path has a .git component in
any letter case, or lies inside the content/ tree.

Manifest lines are "sha256  mapped/path" (two spaces), sorted by mapped path.
Files are copied as exact bytes. --out closes a unique sibling stage before
exclusive publication, rolling back only unchanged invocation-owned paths on
ordinary failure. Existing empty destination identity is preserved. Cleanup
uncertainty refuses success and reports retained paths; whole-tree atomic
visibility, crash persistence and complete hostile-race exclusion are not promised.
This tool never writes into an engine tree:
--out and --check are mutually exclusive.

Exit codes: 0 ok; 1 invalid content, a differing or missing engine copy, or an
I/O failure; 2 usage error (bad arguments, a refused --out destination, or a
--check root that does not exist). Failures print one "PATH: reason" line.
"""

import argparse
import hashlib
import os
import re
import sys
import tempfile

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from validators import scene  # noqa: E402

REPO_ROOT = os.path.dirname(_TOOLS_DIR)
MAPPINGS = {"content/presets/{name}.json": "worlds/atlas/presets/{name}.json"}
_NAME_RE = re.compile(r"[a-z0-9_-]+")
_SEPARATORS = re.compile(r"[\\/]")
_GIT_DIR = ".git"
_JSON_SUFFIX = ".json"
_CLOSE_TIME_FINALIZATION = os.name == "nt"


class ExportError(Exception):
    """A source, destination or I/O problem; the message is one 'PATH: reason' line."""


def _abs(root, rel):
    return os.path.join(root, *rel.split("/"))


def collect_sources(root):
    """Return sorted (source, mapped) pairs for every non-sidecar preset file under ROOT."""
    source_template, mapped_template = next(iter(MAPPINGS.items()))
    source_dir = os.path.dirname(source_template.format(name="x")).replace(os.sep, "/")
    full_dir = _abs(root, source_dir)
    if not os.path.lexists(full_dir):
        # Even absent sources must not hide an unsafe existing ancestor.
        parent = os.path.dirname(full_dir)
        while not os.path.lexists(parent):
            parent = os.path.dirname(parent)
        _directory_info(parent)
        return []
    _directory_info(full_dir)
    pairs = []
    for name in sorted(os.listdir(full_dir)):
        if name.endswith(scene.IDENTITY_SUFFIX) or not name.endswith(_JSON_SUFFIX):
            continue
        rel = source_dir + "/" + name
        if os.path.islink(_abs(root, rel)):
            raise ExportError("%s: symlink refused" % rel)
        stem = name[: -len(_JSON_SUFFIX)]
        if not _NAME_RE.fullmatch(stem):
            raise ExportError("%s: file name must match [a-z0-9_-]+" % rel)
        if scene.is_reserved_stem(stem):
            raise ExportError("%s: file name must not be a reserved Windows device name" % rel)
        pairs.append((rel, mapped_template.format(name=stem)))
    return pairs


def _read_bytes(rel, full):
    try:
        return scene.safe_file_bytes(full, rel)
    except scene.SceneError as exc:
        raise ExportError(str(exc)) from None


def _sidecar_of(source):
    return source[: -len(_JSON_SUFFIX)] + scene.IDENTITY_SUFFIX


def load_files(root, pairs):
    """Capture both required sources and validate exactly the bytes emitted."""
    problems = []
    files = []
    for source, mapped in pairs:
        data = _read_bytes(source, _abs(root, source))
        sidecar = _sidecar_of(source)
        if not os.path.lexists(_abs(root, sidecar)):
            raise ExportError("%s: missing identity sidecar %s" % (source, sidecar))
        sidecar_data = _read_bytes(sidecar, _abs(root, sidecar))
        problems.extend(scene.check_preset_snapshots(source, data, sidecar_data))
        files.append((mapped, hashlib.sha256(data).hexdigest(), data))
    if problems:
        raise ExportError("\n".join(problems))
    return sorted(files, key=lambda item: item[0])


def manifest_lines(files):
    return ["%s  %s" % (digest, mapped) for mapped, digest, _ in files]


def _key(path):
    """Comparison key: the path normalised for the platform and case-folded."""
    return os.path.normcase(path).casefold()


def _has_git_component(path):
    return any(_key(part) == _GIT_DIR for part in _SEPARATORS.split(path))


def _is_within(path, base):
    inside = _key(path)
    outside = _key(base)
    return inside == outside or inside.startswith(outside.rstrip(os.sep) + os.sep)


class Destination(str):
    """Resolved destination plus the identity observed before source validation."""

    def __new__(cls, resolved, label, root, anchors, existed):
        obj = super().__new__(cls, resolved)
        obj.label, obj.root = label, root
        obj.anchors, obj.existed = anchors, existed
        return obj


def _restrictions(out, root):
    resolved = os.path.realpath(os.path.abspath(out))
    if _has_git_component(resolved):
        raise ExportError("%s: refuses to write inside a path with a .git component" % out)
    if _is_within(resolved, os.path.realpath(_abs(root, "content"))):
        raise ExportError("%s: refuses to write inside the content tree" % out)
    return resolved


def _directory_info(path):
    try:
        return scene.safe_path_chain(path, path, directory=True)
    except scene.SceneError as exc:
        raise ExportError(str(exc)) from None


def check_destination(out, root):
    """Capture absent/empty destination identity; never remove an existing directory."""
    resolved = _restrictions(out, root)
    existed = os.path.lexists(resolved)
    if existed:
        if not os.path.isdir(resolved):
            raise ExportError("%s: not a directory" % out)
        if os.listdir(resolved):
            raise ExportError("%s: output directory is not empty" % out)
    existing = resolved
    while not os.path.lexists(existing):
        existing = os.path.dirname(existing)
    # An ancestor that is a file is an ordinary publication I/O failure.
    # Capture its directory parent; exclusive parent creation will refuse the blocker.
    while not os.path.isdir(existing):
        existing = os.path.dirname(existing)
    anchors = _directory_info(existing)
    return Destination(resolved, os.path.abspath(out), os.path.abspath(root), anchors, existed)


class _OwnedPaths:
    """Invocation-owned paths only; cleanup never follows substituted ancestors."""

    def __init__(self, anchors):
        self.anchors = dict(anchors)
        self.directories = {}
        self.files = {}
        self.unverified_files = set()
        self.uncertain = []

    def guard(self):
        for path, info in {**self.anchors, **self.directories}.items():
            observed = os.lstat(path)
            if scene._unsafe_info(observed) or scene.path_identity(observed) != scene.path_identity(info):
                raise ExportError("%s: destination or ancestor changed" % path)

    def mkdir(self, path):
        self.guard()
        os.mkdir(path)  # exclusive even if a cooperative writer just created an empty directory
        self.record_directory(path)
        self.guard()

    def record_directory(self, path):
        self.uncertain.append(path)
        self.directories[path] = os.lstat(path)
        self.uncertain.remove(path)

    def parents(self, path):
        missing = []
        while path not in self.anchors and path not in self.directories:
            missing.append(path)
            path = os.path.dirname(path)
        for path in reversed(missing):
            self.mkdir(path)

    def write(self, path, data):
        self.guard()
        handle = open(path, "xb", buffering=0)
        self.unverified_files.add(path)
        opened = before_close = None
        count = None
        partial_write = False
        error = None
        try:
            opened = os.fstat(handle.fileno())
            try:
                count = handle.write(data)
            except OSError:
                partial_write = True
                raise
            if count != len(data):
                partial_write = True
                raise OSError("short output write")
            handle.flush()
        except (OSError, ExportError) as exc:
            error = exc
        finally:
            try:
                # Provisional metadata cannot authorize rollback until bytes verify.
                before_close = os.fstat(handle.fileno())
            except OSError as exc:
                error = exc if error is None else ExportError("%s; metadata capture failed: %s" % (error, exc))
            try:
                handle.close()  # a close error is a failure, never success
            except OSError as exc:
                error = exc if error is None else ExportError("%s; close failed: %s" % (error, exc))
        try:
            self.guard()
            if opened is None or before_close is None:
                raise ExportError("%s: output ownership could not be verified" % path)
            closed = os.lstat(path)
            if (scene.path_identity(closed) != scene.path_identity(opened)
                    or scene.path_identity(closed) != scene.path_identity(before_close)
                    or closed.st_size != before_close.st_size
                    or scene._unsafe_info(closed)):
                raise ExportError("%s: output file changed" % path)
            if not _CLOSE_TIME_FINALIZATION and scene.file_version(closed) != scene.file_version(before_close):
                raise ExportError("%s: output file changed" % path)
            # Allow close-time timestamp finalization on Windows. Full writes must
            # verify all bytes even if flush/close failed. Only an actual write failure
            # permits prefix verification for rollback of a partially written file.
            expected_size = count if partial_write else len(data)
            if (closed.st_size > len(data) or
                    (expected_size is not None and closed.st_size != expected_size)):
                raise ExportError("%s: output file changed" % path)
            expected = data[:closed.st_size] if partial_write else data
            digest = hashlib.sha256()
            scene.stream_safe_file(path, path, digest.update)
            if digest.hexdigest() != hashlib.sha256(expected).hexdigest():
                raise ExportError("%s: output file changed" % path)
            after = os.lstat(path)
            if scene.file_version(after) != scene.file_version(closed):
                raise ExportError("%s: output file changed" % path)
            # Metadata alone cannot detect an equal-length overwrite with restored
            # timestamps. Retain the exact content verified for rollback/publication.
            self.files[path] = (closed, closed.st_size, digest.hexdigest())
            self.unverified_files.remove(path)
        except (OSError, ExportError, scene.SceneError) as exc:
            error = exc if error is None else ExportError("%s; ownership verification failed: %s" % (error, exc))
        if error is not None:
            if isinstance(error, scene.SceneError):
                raise ExportError(str(error)) from None
            raise error

    def cleanup(self):
        retained = ["%s (created path identity could not be established)" % path for path in self.uncertain]
        retained.extend("%s (created file ownership could not be verified)" % path
                        for path in sorted(self.unverified_files))
        # Check ancestry for each leaf, so uncertainty in one subtree does not justify
        # touching another path through that subtree. Directory mtime may change on writes.
        for path in reversed(self.files):
            try:
                self.verify_file(path)
                # A writer can still change the file between this final reverify
                # and unlink. Complete hostile-race exclusion is not promised.
                os.unlink(path)
            except (OSError, ExportError) as exc:
                retained.append("%s (%s)" % (path, exc))
        for path, info in reversed(list(self.directories.items())):
            try:
                self._guard_ancestors(path)
                if scene.path_identity(os.lstat(path)) != scene.path_identity(info):
                    raise ExportError("owned directory changed")
                os.rmdir(path)  # refuses unknown children; never recursively deletes
            except (OSError, ExportError) as exc:
                retained.append("%s (%s)" % (path, exc))
        return retained

    def verify_file(self, path):
        """Recheck recorded identity/version and content using bounded streaming."""
        info, size, expected_digest = self.files[path]
        self._guard_ancestors(path)
        if scene.file_version(os.lstat(path)) != scene.file_version(info):
            raise ExportError("%s: output file changed" % path)
        digest = hashlib.sha256()
        count = 0

        def consume(chunk):
            nonlocal count
            count += len(chunk)
            digest.update(chunk)

        try:
            scene.stream_safe_file(path, path, consume, expected_size=size)
        except scene.SceneError as exc:
            raise ExportError(str(exc)) from None
        self._guard_ancestors(path)
        if (count != size or digest.hexdigest() != expected_digest
                or scene.file_version(os.lstat(path)) != scene.file_version(info)):
            raise ExportError("%s: output file changed" % path)

    def _guard_ancestors(self, path):
        current = os.path.dirname(path)
        expected = {**self.anchors, **self.directories}
        while True:
            info = expected.get(current)
            if info is None or scene.path_identity(os.lstat(current)) != scene.path_identity(info):
                raise ExportError("ancestor ownership uncertain: %s" % current)
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent


def _walk_error(exc):
    raise exc


def _publication_guard(destination, owned, *, initial=False):
    if _restrictions(destination.label, destination.root) != str(destination):
        raise ExportError("%s: resolved destination changed" % destination.label)
    owned.guard()
    for path in owned.files:
        owned.verify_file(path)
    if initial:
        if destination.existed:
            if os.listdir(destination):
                raise ExportError("%s: output directory became populated" % destination.label)
        elif os.path.lexists(destination):
            raise ExportError("%s: originally absent destination appeared" % destination.label)
    # During commit, all observed children must be ours. Unknown data stays untouched.
    if os.path.lexists(destination) and (destination.existed or str(destination) in owned.directories):
        known = set(owned.files) | set(owned.directories)
        for current, dirs, files in os.walk(destination, followlinks=False, onerror=_walk_error):
            for name in dirs + files:
                if os.path.join(current, name) not in known:
                    raise ExportError("%s: destination contains external data" % destination.label)


def write_out(files, destination, label):
    """Close a sibling stage, then exclusive creates; rollback only owned unchanged paths.

    Whole-tree atomic visibility, hostile namespace race exclusion and crash persistence
    are outside this portable transaction's guarantee.
    """
    if not isinstance(destination, Destination):
        destination = check_destination(destination, REPO_ROOT)
    owned = _OwnedPaths(destination.anchors)
    stage = None
    stage_owned = None
    committed = False
    error = None
    try:
        _publication_guard(destination, owned, initial=True)
        parent = os.path.dirname(destination)
        owned.parents(parent)
        stage_owned = _OwnedPaths({**owned.anchors, **owned.directories})
        owned.guard()
        stage = tempfile.mkdtemp(prefix=".scene-export-", dir=parent)
        stage_owned.record_directory(stage)
        for mapped, digest, data in files:
            # Public entry point refuses traversal and reserved names, too.
            parts = mapped.split("/")
            if (_has_git_component(mapped) or not parts or any(part in ("", ".", "..") or "\\" in part or ":" in part
                                 or scene.is_reserved_stem(part.split(".")[0]) for part in parts)):
                raise ExportError("%s: unsafe mapped path" % mapped)
            if hashlib.sha256(data).hexdigest() != digest:
                raise ExportError("%s: staged bytes do not match manifest digest" % mapped)
            target = _abs(stage, mapped)
            stage_owned.parents(os.path.dirname(target))
            stage_owned.write(target, data)
        _publication_guard(destination, owned, initial=True)
        if not destination.existed:
            owned.mkdir(str(destination))
        for mapped, digest, _ in files:
            _publication_guard(destination, owned)
            target = _abs(destination, mapped)
            owned.parents(os.path.dirname(target))
            # Read the closed stage safely; never reread source presets at publication.
            data = _read_bytes(mapped, _abs(stage, mapped))
            if hashlib.sha256(data).hexdigest() != digest:
                raise ExportError("%s: staged file changed" % mapped)
            _publication_guard(destination, owned)
            owned.write(target, data)
        _publication_guard(destination, owned)
        committed = True
    except (OSError, ExportError) as exc:
        error = "%s: cannot write output: %s" % (label, exc)
    # A staging cleanup failure must also refuse success and roll back publication.
    retained = stage_owned.cleanup() if stage_owned is not None else []
    if retained:
        error = (error or "%s: staging cleanup failed" % label)
    if error is None and committed:
        try:
            _publication_guard(destination, owned)
        except (OSError, ExportError) as exc:
            error = "%s: cannot write output: %s" % (label, exc)
    if error is not None or not committed:
        retained.extend(owned.cleanup())
        if retained:
            error = (error or "%s: cleanup failed" % label) + "; cleanup uncertain; retained paths: " + "; ".join(retained)
            if stage is not None:
                error += "; stage: " + stage
        raise ExportError(error or "%s: publication failed" % label)


def check_engine(files, engine_root):
    """Return one 'PATH: differs|missing' line per mapped file that does not match ENGINE_ROOT."""
    problems = []
    for mapped, _, data in files:
        target = _abs(engine_root, mapped)
        if not os.path.isfile(target):
            problems.append("%s: missing" % mapped)
        else:
            # Preserve the existing engine-copy comparison contract; source capture
            # safety is enforced independently by load_files, before this comparison.
            try:
                with open(target, "rb") as handle:
                    engine_data = handle.read()
            except OSError:
                raise ExportError("%s: cannot read file" % mapped) from None
            if engine_data != data:
                problems.append("%s: differs" % mapped)
    return problems


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="export_engine_content.py",
        description="Print the engine export manifest, write it to a directory, or check an engine tree.",
    )
    parser.add_argument("--root", default=REPO_ROOT, help="repository root (default: this repository)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--out", metavar="DIR", help="write the mapped files under DIR (must be absent or empty)")
    mode.add_argument("--check", metavar="ENGINE_ROOT", help="compare the mapped files with an engine tree")
    return parser


def main(argv=None):
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print("%s: not a directory" % args.root, file=sys.stderr)
        return 2
    if args.check is not None and not os.path.exists(os.path.abspath(args.check)):
        print("%s: not a directory" % args.check, file=sys.stderr)
        return 2

    destination = None
    if args.out is not None:
        try:
            destination = check_destination(args.out, root)
        except ExportError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        except OSError as exc:
            print("%s: cannot inspect destination: %s" % (args.out, exc.strerror or exc))
            return 1

    try:
        files = load_files(root, collect_sources(root))
    except ExportError as exc:
        print(str(exc))
        return 1
    except OSError as exc:
        print("%s: cannot read content: %s" % (scene.PRESET_DIR, exc.strerror or exc))
        return 1

    if args.check is not None:
        engine = os.path.abspath(args.check)
        if not os.path.isdir(engine):
            print("%s: not a directory" % args.check)
            return 1
        try:
            problems = check_engine(files, engine)
        except ExportError as exc:
            print(str(exc))
            return 1
        except OSError as exc:
            print("%s: cannot compare with engine tree: %s" % (args.check, exc.strerror or exc))
            return 1
        for line in problems:
            print(line)
        return 1 if problems else 0

    if destination is not None:
        try:
            write_out(files, destination, args.out)
        except ExportError as exc:
            print(str(exc))
            return 1

    for line in manifest_lines(files):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
