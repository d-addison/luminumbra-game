#!/usr/bin/env python3
"""Public tree guard for the Luminumbra game repository.

The guard is a tripwire, not a proof of absence. It refuses only the file
kinds, signatures, local path shapes and credential shapes it knows about.
A clean run does not show that the tree holds no private material.

Checked for each file in the set (git tracked files; with --worktree also
untracked non-ignored files; without git, every file under ROOT except .git):
  symlinks, size limit, forbidden extensions, forbidden leading magic bytes,
  text-zone NUL and UTF-8 rules, strict-zone line endings, BOM, final LF and
  JSON validity and nesting depth, and local path or credential shaped strings in
  text files, including the decoded keys and string values of JSON files.

Exit codes: 0 clean, 1 problems found, 2 usage error.
"""

import json
import os
import re
import subprocess
import sys

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from lumlib import schema  # noqa: E402
from lumlib.diagnostics import SingleLineParser, printable  # noqa: E402

MAX_BYTES = 1048576

FORBIDDEN_EXTENSIONS = frozenset(
    [
        # audio
        ".wav", ".ogg", ".mp3", ".flac", ".opus", ".fsb", ".bank",
        ".m4a", ".aac", ".wma", ".aiff", ".aif", ".mid", ".midi",
        # images
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tga", ".dds", ".exr", ".hdr",
        ".psd", ".webp", ".ktx", ".ktx2", ".tif", ".tiff",
        # video
        ".mp4", ".mkv", ".avi", ".mov", ".webm",
        # archives
        ".zip", ".7z", ".tar", ".gz", ".tgz", ".xz", ".zst", ".rar",
        # executables and libraries
        ".exe", ".dll", ".so", ".dylib", ".bin", ".msi",
        # saves, runtime artifacts and chunks (release archives only, never git)
        ".lmr", ".lmc", ".lmesh", ".ltex", ".lsave", ".sav",
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
    # executables: PE, ELF, Mach-O thin (32 and 64 bit, both byte orders) and universal
    b"MZ",
    b"\x7fELF",
    b"\xfe\xed\xfa\xce",
    b"\xfe\xed\xfa\xcf",
    b"\xce\xfa\xed\xfe",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    # archives: zip local, central directory end, spanned; 7z; gzip; xz; bzip2; rar
    b"PK\x03\x04",
    b"PK\x05\x06",
    b"PK\x07\x08",
    b"7z\xbc\xaf",
    b"\x1f\x8b",
    b"\xfd7zXZ\x00",
    b"BZh",
    b"Rar!\x1a\x07",
    b"SQLite format 3",
    b"\x89PNG",
    b"\xff\xd8\xff",
    b"GIF87a",
    b"GIF89a",
)

# Repo-relative posix paths exempt from the extension and magic refusals. Only
# entries under assets/ count; the same path elsewhere is still refused.
INVENTORIED_BINARY = frozenset()

TEXT_EXTENSIONS = frozenset(
    [".md", ".json", ".py", ".cpp", ".h", ".yml", ".yaml", ".txt", ".traversal", ".gitignore"]
)

STRICT_PREFIXES = ("content/", "docs/evidence/")

EVIDENCE_PREFIX = "docs/evidence/"
_SCHEMA_ID_RE = re.compile(r"luminumbra\.[a-z0-9._-]+\.v[0-9]+")

# Literal fragments that would match these rules are split by concatenation so
# that this file does not match its own patterns.
ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"[A-Za-z]:\\Users"),
    re.compile(r"/home/[a-z]"),
    re.compile("/Use" "rs/"),
    re.compile("/l" "um/"),
    re.compile(r"/mnt/[a-z]/"),
    re.compile(r"(?i)[a-z]:(?:\\{1,2}|/)(?:users|documents and settings)(?=[\\/\s]|$)"),
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
            obj = schema.loads_document(data.decode("utf-8"))
        except RecursionError:
            problems.append(f"{rel}: json nesting is too deep")
            return problems
        except Exception as exc:
            problems.append(printable(f"{rel}: invalid JSON in strict zone: {exc}"))
            return problems
        if rel.startswith(EVIDENCE_PREFIX):
            if not isinstance(obj, dict):
                problems.append(f"{rel}: evidence JSON must be an object")
            elif not isinstance(obj.get("schema"), str) or _SCHEMA_ID_RE.fullmatch(obj["schema"]) is None:
                problems.append(f"{rel}: evidence JSON needs a schema key matching luminumbra.<name>.v<N>")
    return problems


def _json_strings(data):
    """Return every decoded object key and string value of a JSON document, or None when it does not parse.

    This is a lenient decode for the security scan, independent of the strict
    preset parser: exponent numbers and other tokens the strict zone refuses
    still decode here, so their strings are scanned. Parse failures are left to
    the existing reports; nothing is raised here.
    """
    try:
        obj = json.loads(data.decode("utf-8"))
    except (ValueError, RecursionError):
        return None
    strings = []
    stack = [obj]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                strings.append(key)
                stack.append(value)
        elif isinstance(node, list):
            stack.extend(node)
        elif isinstance(node, str):
            strings.append(node)
    return strings


_JSON_ESCAPE_RE = re.compile(r'\\(?:u([0-9a-fA-F]{4})|(["\\\\/bfnrt]))')
_JSON_SIMPLE_ESCAPES = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


def _unescape_json_text(text):
    """Resolve JSON string escapes in raw text without parsing the document.

    Unlike a decode, this keeps overwritten duplicate-key values and survives
    nesting depths a parser refuses, so the security scan also sees them.
    """

    def replace(match):
        if match.group(1) is not None:
            return chr(int(match.group(1), 16))
        char = match.group(2)
        return _JSON_SIMPLE_ESCAPES.get(char, char)

    return _JSON_ESCAPE_RE.sub(replace, text)


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

    inventoried = rel.startswith("assets/") and rel in INVENTORIED_BINARY
    problems = []
    ext = _extension(rel.rsplit("/", 1)[-1])
    if not inventoried and ext in FORBIDDEN_EXTENSIONS:
        problems.append(f"{rel}: forbidden extension {ext}")

    try:
        with open(full, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        return problems + [f"{rel}: cannot read file: {exc.strerror}"]

    if not inventoried:
        for magic in FORBIDDEN_MAGIC:
            if data.startswith(magic):
                problems.append(f"{rel}: forbidden file signature {magic!r}")
                break

    if ext in TEXT_EXTENSIONS or ext == "" or rel.startswith(STRICT_PREFIXES):
        if b"\x00" in data:
            problems.append(f"{rel}: NUL byte in text file")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            problems.append(f"{rel}: not valid UTF-8 (byte {exc.start})")

    if rel.startswith(STRICT_PREFIXES):
        problems.extend(_check_strict(rel, ext, data))

    if b"\x00" not in data:
        samples = [data.decode("utf-8", errors="replace")]
        if ext == ".json":
            samples.append(_unescape_json_text(samples[0]))
            decoded = _json_strings(data)
            if decoded is not None:
                samples.extend(decoded)
        if any(pattern.search(sample) for sample in samples for pattern in ABSOLUTE_PATH_PATTERNS):
            problems.append(f"{rel}: absolute local path")
        if any(pattern.search(sample) for sample in samples for pattern in CREDENTIAL_PATTERNS):
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
    parser = SingleLineParser(
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
        print(printable(f"{args.root}: not a directory"), file=sys.stderr)
        return 2

    try:
        problems, count = scan(root, worktree=args.worktree, list_from=args.list_from)
    except OSError as exc:
        print(printable(f"{args.list_from}: {exc.strerror}"), file=sys.stderr)
        return 2

    if problems:
        for line in problems:
            print(printable(line))
        return 1
    print(f"public tree ok ({count} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
