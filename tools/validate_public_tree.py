#!/usr/bin/env python3
"""Public tree guard for the Luminumbra game repository.

The guard is a tripwire, not a proof of absence. It refuses only the file
kinds, signatures, local path shapes and credential shapes it knows about.
A clean run does not show that the tree holds no private material.

Checked for each file in the set (git tracked files; with --worktree also
untracked non-ignored files; without git, every file under ROOT except .git):
  symlinks, size limit, forbidden extensions, forbidden leading magic bytes,
  text-zone NUL and UTF-8 rules, strict-zone line endings, BOM, final LF and
  JSON validity, and local path or credential shaped strings in text files.

Exit codes: 0 clean, 1 problems found, 2 usage error.
"""

import argparse
import json
import os
import re
import subprocess
import sys

MAX_BYTES = 1048576

FORBIDDEN_EXTENSIONS = frozenset(
    [
        # audio
        ".wav", ".ogg", ".mp3", ".flac", ".opus", ".fsb", ".bank",
        # archives
        ".zip", ".7z", ".tar", ".gz", ".tgz", ".xz", ".zst", ".rar",
        # executables and libraries
        ".exe", ".dll", ".so", ".dylib", ".bin", ".msi",
        # saves and chunks
        ".lmr", ".lmc", ".lsave", ".sav",
        # logs and dumps
        ".log", ".dmp", ".mdmp",
        # SDK blobs
        ".pdb", ".lib", ".a",
    ]
)

FORBIDDEN_MAGIC = (
    b"RIFF",
    b"OggS",
    b"fLaC",
    b"ID3",
    b"MZ",
    b"\x7fELF",
    b"PK\x03\x04",
    b"7z\xbc\xaf",
    b"\x1f\x8b",
    b"SQLite format 3",
)

TEXT_EXTENSIONS = frozenset(
    [".md", ".json", ".py", ".cpp", ".h", ".yml", ".yaml", ".txt", ".traversal", ".gitignore"]
)

STRICT_PREFIXES = ("content/", "docs/evidence/")

# Literal fragments that would match these rules are split by concatenation so
# that this file does not match its own patterns.
ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"[A-Za-z]:\\Users"),
    re.compile(r"/home/[a-z]"),
    re.compile("/Use" "rs/"),
    re.compile("/l" "um/"),
    re.compile(r"/mnt/[a-z]/"),
)

CREDENTIAL_PATTERNS = (
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile("github" "_pat_"),
    re.compile(r"AKIA[0-9A-Z]{12,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY"),
)


def _extension(name):
    """Return the lowercase extension of a file name, dotfiles included."""
    if "." in name.lstrip("."):
        return os.path.splitext(name)[1].lower()
    if name.startswith("."):
        return name.lower()
    return ""


def _posix_rel(root, full):
    return os.path.relpath(full, root).replace(os.sep, "/")


def _split_nul(data):
    text = data.decode("utf-8", errors="surrogateescape")
    return {item for item in text.split("\0") if item}


def _git(root, *args):
    return subprocess.run(["git", "-C", root, *args], capture_output=True, check=False)


def _git_file_set(root, worktree):
    """Return the git file set for ROOT, or None when ROOT is not its own work tree."""
    try:
        top = _git(root, "rev-parse", "--show-toplevel")
        if top.returncode != 0:
            return None
        toplevel = top.stdout.decode("utf-8", errors="replace").strip()
        if os.path.normcase(os.path.realpath(toplevel)) != os.path.normcase(os.path.realpath(root)):
            return None
        tracked = _git(root, "ls-files", "-z")
        if tracked.returncode != 0:
            return None
        files = _split_nul(tracked.stdout)
        if worktree:
            untracked = _git(root, "ls-files", "-z", "-o", "--exclude-standard")
            if untracked.returncode != 0:
                return None
            files |= _split_nul(untracked.stdout)
        return files
    except OSError:
        return None


def _walk_file_set(root):
    """Return every file and symlink under ROOT, skipping .git and not following symlinked directories."""
    found = set()
    for dirpath, dirnames, filenames in os.walk(root):
        kept = []
        for name in dirnames:
            if name == ".git":
                continue
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                found.add(_posix_rel(root, full))
            else:
                kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            if name == ".git":
                continue
            found.add(_posix_rel(root, os.path.join(dirpath, name)))
    return found


def _list_file_set(path):
    with open(path, encoding="utf-8") as handle:
        return {line.strip() for line in handle if line.strip()}


def _check_strict(rel, ext, data):
    problems = []
    if b"\r" in data:
        problems.append(f"{rel}: CR byte in strict zone (LF only)")
    if data.startswith(b"\xef\xbb\xbf"):
        problems.append(f"{rel}: UTF-8 BOM in strict zone")
    if data and not data.endswith(b"\n"):
        problems.append(f"{rel}: missing final LF in strict zone")
    if ext == ".json":
        try:
            json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            problems.append(f"{rel}: invalid JSON in strict zone: {exc}")
    return problems


def _check_file(root, rel):
    full = os.path.join(root, *rel.split("/"))
    if os.path.islink(full):
        return [f"{rel}: symlink refused"]
    try:
        size = os.path.getsize(full)
    except OSError as exc:
        return [f"{rel}: cannot stat file: {exc.strerror}"]
    if size > MAX_BYTES:
        return [f"{rel}: {size} bytes exceeds the {MAX_BYTES} byte limit"]

    problems = []
    ext = _extension(rel.rsplit("/", 1)[-1])
    if ext in FORBIDDEN_EXTENSIONS:
        problems.append(f"{rel}: forbidden extension {ext}")

    try:
        with open(full, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        return problems + [f"{rel}: cannot read file: {exc.strerror}"]

    for magic in FORBIDDEN_MAGIC:
        if data.startswith(magic):
            problems.append(f"{rel}: forbidden file signature {magic!r}")
            break

    if ext in TEXT_EXTENSIONS or ext == "":
        if b"\x00" in data:
            problems.append(f"{rel}: NUL byte in text file")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            problems.append(f"{rel}: not valid UTF-8 (byte {exc.start})")

    if rel.startswith(STRICT_PREFIXES):
        problems.extend(_check_strict(rel, ext, data))

    if b"\x00" not in data:
        text = data.decode("utf-8", errors="replace")
        if any(pattern.search(text) for pattern in ABSOLUTE_PATH_PATTERNS):
            problems.append(f"{rel}: absolute local path")
        if any(pattern.search(text) for pattern in CREDENTIAL_PATTERNS):
            problems.append(f"{rel}: credential-shaped string")
    return problems


def scan(root, worktree=False, list_from=None):
    """Return (sorted problems, file count) for ROOT."""
    if list_from is not None:
        files = _list_file_set(list_from)
    else:
        files = _git_file_set(root, worktree)
        if files is None:
            files = _walk_file_set(root)
    problems = []
    for rel in sorted(files):
        problems.extend(_check_file(root, rel))
    return sorted(problems), len(files)


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="validate_public_tree.py",
        description=(
            "Public tree guard. A tripwire, not a proof of absence: it refuses the file "
            "kinds, signatures, local path shapes and credential shapes it knows about. "
            "A clean run does not prove that the tree holds no private material."
        ),
    )
    parser.add_argument(
        "--root", default=".", help="repository root to scan (default: current directory)"
    )
    parser.add_argument(
        "--worktree",
        action="store_true",
        help="also scan untracked, non-ignored files (git repositories only)",
    )
    parser.add_argument(
        "--list-from",
        metavar="FILE",
        help="testing: read newline-separated relative paths instead of asking git",
    )
    return parser


def main(argv=None):
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"{args.root}: not a directory", file=sys.stderr)
        return 2

    try:
        problems, count = scan(root, worktree=args.worktree, list_from=args.list_from)
    except OSError as exc:
        print(f"{args.list_from}: {exc.strerror}", file=sys.stderr)
        return 2

    if problems:
        for line in problems:
            print(line)
        return 1
    print(f"public tree ok ({count} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
