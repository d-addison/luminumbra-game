"""Acceptance evidence bundle: schema luminumbra.game.acceptance-evidence.v1.

validate_bundle checks a parsed bundle: structure, cross-field rules, and a
whole-document scan for private material. With release=True it also refuses
open defects and open blocking limitations. artifact_hashes lists the hashes a
bundle names, and verify_artifacts reads the content-addressed store
DIR/sha256/<hex>, recomputes every hash, and checks that audio-off session
journals contain the audio-off marker the operator supplies, that each session
command agrees with its declared no_audio_flag, that the no-audio precedence
command carries both --enable-audio and --no-audio, and that the null-audio
startup command carries neither. Commands are matched as whole arguments. Every
artifact is read once.

The bundle stores hashes and counts only; the store holds the artifacts. The
audio-off marker is not part of the bundle: a bundle cannot vouch for its own
audio-off proof, so the marker comes from the operator on the command line.
Problems are strings of the form "PATH: reason", where PATH is a json-path
style location such as sessions[2].exit_code.

The module is also registered in the content registry (SCHEMAS) so that a
bundle placed under content/ gets the structural checks.
"""

import hashlib
import math
import os
import re
from decimal import Decimal

from lumlib.diagnostics import CONTROL, printable
from lumlib.schema import SchemaError, check_keys, check_schema_id, is_kebab
from validate_public_tree import ABSOLUTE_PATH_PATTERNS

SCHEMA_ID = "luminumbra.game.acceptance-evidence.v1"
HANG_EXIT_CODE = 0xCFFFFFFF
MIN_SCENES = 6
MIN_SWITCH_SESSIONS = 2
MAX_NOTE_LENGTH = 200
SESSION_KINDS = ("create", "edit", "save", "restart", "load", "switch", "refusal", "preview")
AUDIO_MODES = ("null", "off")
DISPOSITIONS = ("accepted", "fixed", "open", "waived")
LIMITATION_STATUSES = ("open", "closed")
HISTORICAL_KIND = "application-hang"
EXIT_CODE_MIN = -2147483648
EXIT_CODE_MAX = 4294967295
MARKER_MIN_LENGTH = 8
CHUNK_SIZE = 65536
NO_AUDIO_TOKEN = b"--no-audio"
ENABLE_AUDIO_TOKEN = b"--enable-audio"
PRIVATE_EXTENSIONS = (
    ".wav", ".ogg", ".flac", ".mp3", ".m4a", ".aac", ".wma",
    ".opus", ".aiff", ".aif", ".wem", ".bank", ".fsb", ".snd",
    ".mid", ".midi", ".ape", ".mka", ".amr",
    ".dll", ".so", ".dylib", ".exe", ".lib", ".a", ".obj", ".o", ".pdb",
    ".sav", ".lmc", ".lmr", ".zip", ".pck", ".sdk", ".p12", ".pfx", ".pem", ".key",
)

ROOT_KEYS = frozenset(
    [
        "schema", "package", "engine", "game", "content", "policy", "sessions", "saves",
        "scenes", "forest", "launcher", "disabled_backend", "limitations", "historical",
        "startup_checks", "unresolved_diagnostics",
    ]
)
SESSION_KEYS = frozenset(
    [
        "id", "kind", "command_sha256", "journal_sha256", "exit_code", "audio_mode",
        "no_audio_flag", "saved_master",
    ]
)
REFUSAL_KEYS = frozenset(["refusal_code", "saves", "saves_unchanged"])
STARTUP_KEYS = frozenset(["no_audio_precedence_session", "null_audio_nonzero_master_session"])

_HEX64 = re.compile(r"[0-9a-f]{64}")
_HEX40 = re.compile(r"[0-9a-f]{40}")
_DRIVE_START = re.compile(r"[A-Za-z]:")
_DRIVE_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:(?:\\|/)")
# Backslash UNC (\\server\share) and device (\\?\C:) paths. Only an ASCII letter or digit
# before them is refused as a word character; a colon is a boundary, so see:\\server\share
# is caught.
_UNC_BACKSLASH_PATH = re.compile(r"(?<![A-Za-z0-9])(?:\\\\\?\\|\\\\[^\\\s]+\\)")
# Forward-slash UNC (//server/share). A colon before the // is not a boundary, so the //
# of a URL such as https://host/path never matches.
_UNC_SLASH_PATH = re.compile(r"(?<![A-Za-z0-9:])//[^/\\\s]+/")
_REQUIRED_LIMITATIONS = ("finite-residency", "distant-cave-edit-omitted")
_LOCAL_PATTERNS = (re.compile("/ho" "me/"), re.compile("/Us" "ers/"))
# Any occurrence of a private extension that is not immediately followed by an ASCII
# letter or digit is refused, whatever precedes it. Matching ignores case, so a.wavelength,
# data.apple, notes.opusx and awav are accepted while a bare .wav, _capture.wav_ and
# recording (1).wav are refused.
_PRIVATE_FILE = re.compile(
    r"(\.(?:"
    + "|".join(re.escape(extension[1:]) for extension in PRIVATE_EXTENSIONS)
    + r"))(?![A-Za-z0-9])",
    re.IGNORECASE,
)
# Windows reserved device names, matched on the part before the first dot, and the
# characters Windows refuses in a path component.
_WINDOWS_DEVICE_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + ["COM%d" % number for number in range(1, 10)]
    + ["LPT%d" % number for number in range(1, 10)]
)
_WINDOWS_FORBIDDEN_CHARS = frozenset(':*?"<>|')


def _where(path):
    return path or "bundle"


def _join(parent, key):
    return "%s.%s" % (parent, key) if parent else key


def _keys(problems, value, path, required, optional=()):
    try:
        check_keys(value, set(required), set(optional), _where(path))
    except SchemaError as exc:
        problems.append(str(exc))
        return False
    return True


def _list(problems, value, path, minimum=0):
    if not isinstance(value, list):
        problems.append("%s: must be a list" % _where(path))
        return False
    if len(value) < minimum:
        problems.append("%s: needs at least %d item(s)" % (_where(path), minimum))
        return False
    return True


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    """Return True for a finite, non-negative int, float, or Decimal (not bool)."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value >= 0
    if isinstance(value, float):
        return math.isfinite(value) and value >= 0
    if isinstance(value, Decimal):
        return value.is_finite() and value >= 0
    return False


def _hex(problems, value, path, length=64):
    pattern = _HEX64 if length == 64 else _HEX40
    if isinstance(value, str) and pattern.fullmatch(value):
        return True
    problems.append("%s: must be %d lowercase hex characters" % (_where(path), length))
    return False


def _check_id(problems, value, path, seen):
    if not is_kebab(value):
        problems.append("%s: must be lowercase kebab-case" % _where(path))
        return
    if value in seen:
        problems.append("%s: duplicate id '%s'" % (_where(path), value))
        return
    seen.add(value)


def _check_rev(problems, value, path):
    if not _keys(problems, value, path, ("rev",)):
        return
    _hex(problems, value["rev"], _join(path, "rev"), 40)


def _check_package(problems, value, path):
    if not _keys(problems, value, path, ("archive_sha256", "git_sha")):
        return
    _hex(problems, value["git_sha"], _join(path, "git_sha"), 40)
    _hex(problems, value["archive_sha256"], _join(path, "archive_sha256"))


def _check_content(problems, value, path):
    if not _keys(problems, value, path, ("packs",)):
        return
    packs_path = _join(path, "packs")
    if not _list(problems, value["packs"], packs_path, minimum=1):
        return
    seen = set()
    for index, pack in enumerate(value["packs"]):
        here = "%s[%d]" % (packs_path, index)
        if not _keys(problems, pack, here, ("id", "sha256")):
            continue
        _check_id(problems, pack["id"], _join(here, "id"), seen)
        _hex(problems, pack["sha256"], _join(here, "sha256"))


def _check_policy(problems, value, path):
    if not _keys(problems, value, path, ("refusal_exit_codes",)):
        return
    codes_path = _join(path, "refusal_exit_codes")
    if _list(problems, value["refusal_exit_codes"], codes_path, minimum=1):
        seen = set()
        for index, code in enumerate(value["refusal_exit_codes"]):
            here = "%s[%d]" % (codes_path, index)
            if not _is_int(code) or not 1 <= code <= 125:
                problems.append("%s: must be an integer from 1 to 125" % here)
            elif code in seen:
                problems.append("%s: duplicate exit code %d" % (here, code))
            else:
                seen.add(code)


def marker_problem(marker):
    """Return why an operator audio-off marker is unusable, or None when it is valid."""
    if not isinstance(marker, str) or not marker:
        return "must be a non-empty string"
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in marker):
        return "must not contain control characters"
    if not marker.strip():
        return "must not be only whitespace"
    if len(marker) < MARKER_MIN_LENGTH:
        return "must be at least %d characters" % MARKER_MIN_LENGTH
    return None


def _refusal_codes(doc):
    policy = doc.get("policy")
    codes = policy.get("refusal_exit_codes") if isinstance(policy, dict) else None
    if not isinstance(codes, list):
        return set()
    return {code for code in codes if _is_int(code)}


def _index_by_name(value, key):
    """Map each dict entry's string ``key`` to the entry; the first occurrence wins."""
    index = {}
    if isinstance(value, list):
        for entry in value:
            if isinstance(entry, dict) and isinstance(entry.get(key), str):
                index.setdefault(entry[key], entry)
    return index


def _check_exit_code(problems, session, here, codes):
    path = _join(here, "exit_code")
    code = session["exit_code"]
    if not _is_int(code):
        problems.append("%s: must be an integer" % path)
        return
    if not EXIT_CODE_MIN <= code <= EXIT_CODE_MAX:
        problems.append(
            "%s: must be an integer from %d to %d" % (path, EXIT_CODE_MIN, EXIT_CODE_MAX)
        )
        return
    normalised = code & 0xFFFFFFFF
    if normalised == HANG_EXIT_CODE:
        problems.append(
            "%s: 0xCFFFFFFF is the application hang signature and is refused in every session"
            % path
        )
        return
    if session["kind"] == "refusal":
        if normalised not in codes:
            problems.append(
                "%s: refusal exit %d is not in policy.refusal_exit_codes" % (path, normalised)
            )
    elif normalised != 0:
        problems.append(
            "%s: normalised exit code must be 0 for a %s session" % (path, session["kind"])
        )


def _check_refusal_saves(problems, value, path, saves_by_name):
    """Each refusal names saves from saves[]; none of their files may change."""
    if not _list(problems, value, path, minimum=1):
        return
    seen = set()
    for index, name in enumerate(value):
        here = "%s[%d]" % (path, index)
        if not isinstance(name, str) or not name:
            problems.append("%s: must be a non-empty string" % here)
            continue
        if name in seen:
            problems.append("%s: duplicate save '%s' in this session" % (here, name))
            continue
        seen.add(name)
        save = saves_by_name.get(name)
        if save is None:
            problems.append("%s: unknown save '%s'" % (here, name))
            continue
        files = save.get("files")
        if not isinstance(files, list):
            continue
        for entry in files:
            if not isinstance(entry, dict):
                continue
            before = entry.get("sha256_before")
            after = entry.get("sha256_after")
            if isinstance(before, str) and isinstance(after, str) and before != after:
                problems.append(
                    "%s: referenced save '%s' changed file '%s'" % (here, name, entry.get("path"))
                )


def _check_sessions(problems, value, path, codes, saves_by_name):
    if not _list(problems, value, path):
        return
    seen = set()
    kinds = set()
    switches = 0
    for index, session in enumerate(value):
        here = "%s[%d]" % (path, index)
        kind = session.get("kind") if isinstance(session, dict) else None
        if kind == "switch":
            switches += 1
        required = SESSION_KEYS | REFUSAL_KEYS if kind == "refusal" else SESSION_KEYS
        if not _keys(problems, session, here, required):
            continue
        _check_id(problems, session["id"], _join(here, "id"), seen)
        if session["kind"] in SESSION_KINDS:
            kinds.add(session["kind"])
        else:
            problems.append(
                "%s: must be one of %s" % (_join(here, "kind"), ", ".join(SESSION_KINDS))
            )
        _hex(problems, session["command_sha256"], _join(here, "command_sha256"))
        _hex(problems, session["journal_sha256"], _join(here, "journal_sha256"))
        _check_exit_code(problems, session, here, codes)

        audio = session["audio_mode"]
        flag = session["no_audio_flag"]
        if audio not in AUDIO_MODES:
            problems.append("%s: must be null or off" % _join(here, "audio_mode"))
        if not isinstance(flag, bool):
            problems.append("%s: must be true or false" % _join(here, "no_audio_flag"))
        if not _is_number(session["saved_master"]):
            problems.append(
                "%s: must be a finite non-negative number" % _join(here, "saved_master")
            )
        if audio == "off" and flag is False:
            problems.append("%s: audio_mode off requires no_audio_flag true" % here)
        if audio == "null" and flag is True:
            problems.append("%s: audio_mode null requires no_audio_flag false" % here)
        if session["kind"] == "preview" and not (audio == "off" and flag is True):
            problems.append("%s: preview requires audio_mode off and no_audio_flag true" % here)
        if kind == "refusal":
            refusal_code = session["refusal_code"]
            if not isinstance(refusal_code, str) or not refusal_code:
                problems.append("%s: must be a non-empty string" % _join(here, "refusal_code"))
            if session["saves_unchanged"] is not True:
                problems.append("%s: must be true" % _join(here, "saves_unchanged"))
            _check_refusal_saves(problems, session["saves"], _join(here, "saves"), saves_by_name)
    for kind in SESSION_KINDS:
        if kind not in kinds:
            problems.append("%s: missing session kind '%s'" % (_where(path), kind))
    if switches < MIN_SWITCH_SESSIONS:
        problems.append(
            "%s: at least %d sessions of kind 'switch' are required, found %d"
            % (_where(path), MIN_SWITCH_SESSIONS, switches)
        )


def _check_startup(problems, value, path, sessions_by_id):
    """The startup checks name existing sessions whose audio state proves the rules."""
    if not _keys(problems, value, path, STARTUP_KEYS):
        return
    first_path = _join(path, "null_audio_nonzero_master_session")
    first_id = value["null_audio_nonzero_master_session"]
    first = sessions_by_id.get(first_id) if isinstance(first_id, str) else None
    if first is None:
        problems.append("%s: unknown session %r" % (first_path, first_id))
    elif not (
        first.get("audio_mode") == "null"
        and first.get("no_audio_flag") is False
        and _is_number(first.get("saved_master"))
        and first["saved_master"] > 0
    ):
        problems.append(
            "%s: session %r must have audio_mode null, no_audio_flag false and saved_master above zero"
            % (first_path, first_id)
        )

    second_path = _join(path, "no_audio_precedence_session")
    second_id = value["no_audio_precedence_session"]
    second = sessions_by_id.get(second_id) if isinstance(second_id, str) else None
    if second is None:
        problems.append("%s: unknown session %r" % (second_path, second_id))
    elif not (second.get("audio_mode") == "off" and second.get("no_audio_flag") is True):
        problems.append(
            "%s: session %r must have audio_mode off and no_audio_flag true"
            % (second_path, second_id)
        )
    elif second.get("kind") not in ("restart", "load"):
        problems.append("%s: session %r must be a restart or load session" % (second_path, second_id))


def _check_portable_path(problems, value, path):
    if not isinstance(value, str) or not value:
        problems.append("%s: must be a non-empty string" % path)
        return
    parts = value.split("/")
    if (
        value.startswith("/")
        or "\\" in value
        or _DRIVE_START.match(value)
        or ".." in parts
        or "" in parts
    ):
        problems.append(
            "%s: must be a portable relative path (no leading slash, backslash, '..', or drive)"
            % path
        )
        return
    for part in parts:
        if CONTROL.search(part):
            problems.append("%s: component '%s' contains a control character" % (path, part))
        elif part.split(".", 1)[0].rstrip(" ").upper() in _WINDOWS_DEVICE_NAMES:
            problems.append("%s: component '%s' is a reserved Windows device name" % (path, part))
        elif any(char in _WINDOWS_FORBIDDEN_CHARS for char in part):
            problems.append(
                "%s: component '%s' contains a character Windows does not allow" % (path, part)
            )
        elif part.endswith(".") or part.endswith(" "):
            problems.append("%s: component '%s' ends in a dot or a space" % (path, part))


def _check_saves(problems, value, path):
    if not _list(problems, value, path, minimum=1):
        return
    seen = set()
    edited = False
    for index, save in enumerate(value):
        here = "%s[%d]" % (path, index)
        if not _keys(problems, save, here, ("files", "name")):
            continue
        name = save["name"]
        if not isinstance(name, str) or not name:
            problems.append("%s: must be a non-empty string" % _join(here, "name"))
        elif name in seen:
            problems.append("%s: duplicate save name '%s'" % (_join(here, "name"), name))
        else:
            seen.add(name)
        files_path = _join(here, "files")
        if not _list(problems, save["files"], files_path, minimum=1):
            continue
        paths_seen = set()
        for position, entry in enumerate(save["files"]):
            entry_here = "%s[%d]" % (files_path, position)
            if not _keys(problems, entry, entry_here, ("path", "sha256_after", "sha256_before")):
                continue
            _check_portable_path(problems, entry["path"], _join(entry_here, "path"))
            if isinstance(entry["path"], str):
                # Windows file names are case-insensitive, so aliases of one path collide.
                folded = entry["path"].casefold()
                if folded in paths_seen:
                    problems.append(
                        "%s: duplicate path '%s'" % (_join(entry_here, "path"), entry["path"])
                    )
                paths_seen.add(folded)
            before_ok = _hex(problems, entry["sha256_before"], _join(entry_here, "sha256_before"))
            after_ok = _hex(problems, entry["sha256_after"], _join(entry_here, "sha256_after"))
            if before_ok and after_ok and entry["sha256_before"] != entry["sha256_after"]:
                edited = True
    if not edited:
        problems.append(
            "%s: no save has an edited file (sha256_before differs from sha256_after)"
            % _where(path)
        )


def _check_scenes(problems, value, path, release):
    if not _list(problems, value, path):
        return
    if len(value) < MIN_SCENES:
        problems.append(
            "%s: at least %d scenes are required, found %d" % (_where(path), MIN_SCENES, len(value))
        )
    seen = set()
    for index, scene in enumerate(value):
        here = "%s[%d]" % (path, index)
        if not _keys(problems, scene, here, ("capture_sha256", "defects", "id", "settled")):
            continue
        _check_id(problems, scene["id"], _join(here, "id"), seen)
        _hex(problems, scene["capture_sha256"], _join(here, "capture_sha256"))
        if scene["settled"] is not True:
            problems.append("%s: must be true" % _join(here, "settled"))
        defects_path = _join(here, "defects")
        if not _list(problems, scene["defects"], defects_path):
            continue
        defect_ids = set()
        for position, defect in enumerate(scene["defects"]):
            defect_here = "%s[%d]" % (defects_path, position)
            if not _keys(problems, defect, defect_here, ("disposition", "id", "note")):
                continue
            if not isinstance(defect["id"], str) or not defect["id"]:
                problems.append("%s: must be a non-empty string" % _join(defect_here, "id"))
            elif defect["id"] in defect_ids:
                problems.append("%s: duplicate id '%s'" % (defect_here, defect["id"]))
            else:
                defect_ids.add(defect["id"])
            disposition = defect["disposition"]
            if disposition not in DISPOSITIONS:
                problems.append(
                    "%s: must be one of %s" % (_join(defect_here, "disposition"), ", ".join(DISPOSITIONS))
                )
            elif disposition == "open" and release:
                problems.append(
                    "%s: open defect is refused in release mode" % _join(defect_here, "disposition")
                )
            note = defect["note"]
            if not isinstance(note, str) or len(note) > MAX_NOTE_LENGTH:
                problems.append(
                    "%s: must be a string of at most %d characters"
                    % (_join(defect_here, "note"), MAX_NOTE_LENGTH)
                )


def _check_forest(problems, value, path):
    if not _keys(problems, value, path, ("agree", "report_sha256", "submission_sha256")):
        return
    _hex(problems, value["submission_sha256"], _join(path, "submission_sha256"))
    _hex(problems, value["report_sha256"], _join(path, "report_sha256"))
    if value["agree"] is not True:
        problems.append("%s: must be true" % _join(path, "agree"))


def _check_launcher(problems, value, path, release):
    if not _keys(problems, value, path, ("identity_sha256", "preview_audio_off")):
        return
    _hex(problems, value["identity_sha256"], _join(path, "identity_sha256"))
    audio_off = value["preview_audio_off"]
    audio_path = _join(path, "preview_audio_off")
    if not isinstance(audio_off, bool):
        problems.append("%s: must be true or false" % audio_path)
    elif release and audio_off is not True:
        problems.append("%s must be true in release mode" % audio_path)


def _check_disabled_backend(problems, value, path, release):
    if not _keys(problems, value, path, ("proof_sha256", "settings_preserved")):
        return
    _hex(problems, value["proof_sha256"], _join(path, "proof_sha256"))
    preserved = value["settings_preserved"]
    preserved_path = _join(path, "settings_preserved")
    if not isinstance(preserved, bool):
        problems.append("%s: must be true or false" % preserved_path)
    elif release and preserved is not True:
        problems.append("%s must be true in release mode" % preserved_path)


def _check_limitations(problems, value, path, release, archive=None):
    """Check the limitation entries. ARCHIVE is package.archive_sha256 when it is known.

    Closure evidence is the retained completion record. Each closed entry's closure hash
    must differ from the package archive hash and from every other entry's closure hash.
    Whether the record proves completion is decided by the human review of the release.
    """
    if not _list(problems, value, path):
        return
    seen = set()
    first_index = {}
    closures = {}
    for index, entry in enumerate(value):
        here = "%s[%d]" % (path, index)
        if not _keys(problems, entry, here, ("blocks_release", "closure_sha256", "id", "status")):
            continue
        _check_id(problems, entry["id"], _join(here, "id"), seen)
        if isinstance(entry["id"], str):
            first_index.setdefault(entry["id"], index)
        status = entry["status"]
        closure = entry["closure_sha256"]
        closure_path = _join(here, "closure_sha256")
        if status not in LIMITATION_STATUSES:
            problems.append("%s: must be open or closed" % _join(here, "status"))
        elif status == "closed":
            if closure is None:
                problems.append("%s: closed limitation needs closure evidence" % closure_path)
            elif _hex(problems, closure, closure_path):
                if closure == archive:
                    problems.append(
                        "%s: closure evidence must differ from package.archive_sha256"
                        % closure_path
                    )
                elif closure in closures:
                    problems.append(
                        "%s: closure evidence must differ from %s"
                        % (closure_path, closures[closure])
                    )
                else:
                    closures[closure] = closure_path
        elif closure is not None:
            problems.append("%s: open limitation must have a null closure_sha256" % closure_path)
        if not isinstance(entry["blocks_release"], bool):
            problems.append("%s: must be true or false" % _join(here, "blocks_release"))
        elif release and status == "open" and entry["blocks_release"] is True:
            problems.append("%s: open blocking limitation is refused in release mode" % here)
    for required in _REQUIRED_LIMITATIONS:
        if required not in first_index:
            problems.append("%s: missing required entry '%s'" % (_where(path), required))
            continue
        index = first_index[required]
        if value[index]["blocks_release"] is not True:
            problems.append(
                "%s[%d]: '%s' must have blocks_release true" % (path, index, required)
            )


def _check_historical(problems, value, path):
    if not _list(problems, value, path, minimum=1):
        return
    seen = set()
    for index, record in enumerate(value):
        here = "%s[%d]" % (path, index)
        if not _keys(problems, record, here, ("disposition", "id", "kind")):
            continue
        _check_id(problems, record["id"], _join(here, "id"), seen)
        if record["kind"] != HISTORICAL_KIND:
            problems.append("%s: must be %s" % (_join(here, "kind"), HISTORICAL_KIND))
        disposition = record["disposition"]
        if not isinstance(disposition, str) or not disposition:
            problems.append("%s: must be a non-empty string" % _join(here, "disposition"))


def _check_diagnostics(problems, value, path):
    if not _list(problems, value, path):
        return
    for index, item in enumerate(value):
        if not isinstance(item, str):
            problems.append("%s[%d]: must be a string" % (path, index))


def _scan_strings(value, path, problems):
    """Refuse private extensions and local or network path shapes in every string value."""
    if isinstance(value, str):
        private = _PRIVATE_FILE.search(value)
        if private is not None:
            problems.append(
                "%s: private file extension '%s' is not allowed; evidence stores hashes and counts only"
                % (_where(path), private.group(1).lower())
            )
            return
        if (
            _DRIVE_PATH.search(value)
            or _UNC_BACKSLASH_PATH.search(value)
            or _UNC_SLASH_PATH.search(value)
            or any(pattern.search(value) for pattern in ABSOLUTE_PATH_PATTERNS + _LOCAL_PATTERNS)
        ):
            problems.append("%s: local absolute path shape is not allowed" % _where(path))
    elif isinstance(value, dict):
        for key in sorted(value):
            _scan_strings(value[key], _join(path, key), problems)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _scan_strings(item, "%s[%d]" % (path, index), problems)


def validate_bundle(doc, *, release=False):
    """Return the problems found in a parsed bundle; an empty list means valid.

    release=True also refuses open defects and open blocking limitations.
    """
    try:
        check_schema_id(doc, SCHEMA_ID, "bundle")
    except SchemaError as exc:
        return [printable(exc)]
    problems = []
    _keys(problems, doc, "", ROOT_KEYS)
    codes = _refusal_codes(doc)
    saves_by_name = _index_by_name(doc.get("saves"), "name")
    sessions_by_id = _index_by_name(doc.get("sessions"), "id")
    if "package" in doc:
        _check_package(problems, doc["package"], "package")
    if "engine" in doc:
        _check_rev(problems, doc["engine"], "engine")
    if "game" in doc:
        _check_rev(problems, doc["game"], "game")
    if "content" in doc:
        _check_content(problems, doc["content"], "content")
    if "policy" in doc:
        _check_policy(problems, doc["policy"], "policy")
    if "sessions" in doc:
        _check_sessions(problems, doc["sessions"], "sessions", codes, saves_by_name)
    if "startup_checks" in doc:
        _check_startup(problems, doc["startup_checks"], "startup_checks", sessions_by_id)
    if "saves" in doc:
        _check_saves(problems, doc["saves"], "saves")
    if "scenes" in doc:
        _check_scenes(problems, doc["scenes"], "scenes", release)
    if "forest" in doc:
        _check_forest(problems, doc["forest"], "forest")
    if "launcher" in doc:
        _check_launcher(problems, doc["launcher"], "launcher", release)
    if "disabled_backend" in doc:
        _check_disabled_backend(problems, doc["disabled_backend"], "disabled_backend", release)
    if "limitations" in doc:
        package = doc.get("package")
        archive = package.get("archive_sha256") if isinstance(package, dict) else None
        _check_limitations(problems, doc["limitations"], "limitations", release, archive)
    if "historical" in doc:
        _check_historical(problems, doc["historical"], "historical")
    if "unresolved_diagnostics" in doc:
        _check_diagnostics(problems, doc["unresolved_diagnostics"], "unresolved_diagnostics")
    _scan_strings(doc, "", problems)
    return [printable(problem) for problem in problems]


def artifact_hashes(doc):
    """Return (sha256 hex, location) for each artifact the bundle names, in document order."""
    refs = []

    def add(value, location):
        if isinstance(value, str) and _HEX64.fullmatch(value):
            refs.append((value, location))

    package = doc.get("package")
    if isinstance(package, dict):
        add(package.get("archive_sha256"), "package.archive_sha256")
    content = doc.get("content")
    packs = content.get("packs") if isinstance(content, dict) else None
    for index, pack in enumerate(packs if isinstance(packs, list) else []):
        if isinstance(pack, dict):
            add(pack.get("sha256"), "content.packs[%d].sha256" % index)
    sessions = doc.get("sessions")
    for index, session in enumerate(sessions if isinstance(sessions, list) else []):
        if not isinstance(session, dict):
            continue
        add(session.get("command_sha256"), "sessions[%d].command_sha256" % index)
        add(session.get("journal_sha256"), "sessions[%d].journal_sha256" % index)
    saves = doc.get("saves")
    for index, save in enumerate(saves if isinstance(saves, list) else []):
        files = save.get("files") if isinstance(save, dict) else None
        for position, entry in enumerate(files if isinstance(files, list) else []):
            if not isinstance(entry, dict):
                continue
            base = "saves[%d].files[%d]" % (index, position)
            add(entry.get("sha256_before"), base + ".sha256_before")
            add(entry.get("sha256_after"), base + ".sha256_after")
    scenes = doc.get("scenes")
    for index, scene in enumerate(scenes if isinstance(scenes, list) else []):
        if isinstance(scene, dict):
            add(scene.get("capture_sha256"), "scenes[%d].capture_sha256" % index)
    forest = doc.get("forest")
    if isinstance(forest, dict):
        add(forest.get("submission_sha256"), "forest.submission_sha256")
        add(forest.get("report_sha256"), "forest.report_sha256")
    launcher = doc.get("launcher")
    if isinstance(launcher, dict):
        add(launcher.get("identity_sha256"), "launcher.identity_sha256")
    disabled = doc.get("disabled_backend")
    if isinstance(disabled, dict):
        add(disabled.get("proof_sha256"), "disabled_backend.proof_sha256")
    limitations = doc.get("limitations")
    for index, entry in enumerate(limitations if isinstance(limitations, list) else []):
        if isinstance(entry, dict):
            add(entry.get("closure_sha256"), "limitations[%d].closure_sha256" % index)
    return refs


def artifact_count(doc):
    """Return the number of distinct artifacts the bundle names."""
    return len({digest for digest, _location in artifact_hashes(doc)})


# A whole-argument match, as the engine's exact argv comparison sees it: the flag must
# start the file or follow whitespace, a single quote, a double quote or NUL, and it must
# end the file or be followed by whitespace, a quote or NUL. Any other byte next to the
# flag (=, ., letters, digits, -, /, \\, parentheses, underscores) makes it a different
# argument.
_TOKEN_BEFORE = rb"(?:\A|(?<=[\s'\"\x00]))"
_TOKEN_AFTER = rb"(?=[\s'\"\x00]|\Z)"


def _scan_window(window, base, eof, patterns, found):
    """Record each pattern with a usable match in WINDOW, which starts at file offset BASE.

    A match that touches the start of a later window (base > 0) is skipped, because an
    earlier window already decided it. A match that touches the end of this window is
    skipped unless eof, because the next window decides it.
    """
    size = len(window)
    for needle, pattern in patterns:
        if needle in found:
            continue
        for match in pattern.finditer(window):
            start, end = match.span()
            if start == 0 and base > 0:
                continue
            if end == size and not eof:
                continue
            found.add(needle)
            break


def _scan_file(path, needles=(), tokens=()):
    """Hash PATH and find NEEDLES and TOKENS in one pass over the file, in 64 KiB chunks.

    NEEDLES are byte strings that count wherever they occur. TOKENS are byte strings
    that count only as whole tokens (see _TOKEN_BEFORE and _TOKEN_AFTER). Returns
    (sha256 hex digest, set of the needles and tokens that were found).

    Each window keeps its last reach bytes, one more than the longest pattern, so a
    match straddling a chunk boundary is seen whole and both of its neighbouring bytes
    are read.
    """
    patterns = [(needle, re.compile(re.escape(needle))) for needle in needles]
    patterns += [
        (token, re.compile(_TOKEN_BEFORE + re.escape(token) + _TOKEN_AFTER)) for token in tokens
    ]
    reach = max((len(needle) for needle, _pattern in patterns), default=0) + 1
    digest = hashlib.sha256()
    found = set()
    carry = b""
    base = 0
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
            if patterns:
                window = carry + chunk
                _scan_window(window, base, False, patterns, found)
                keep = window[-reach:]
                base += len(window) - len(keep)
                carry = keep
        if patterns:
            _scan_window(carry, base, True, patterns, found)
    return digest.hexdigest(), found


def _want(wanted, digest, needle):
    if isinstance(digest, str):
        wanted.setdefault(digest, set()).add(needle)


def _verified(status, digest):
    return isinstance(digest, str) and status.get(digest) is True


def verify_artifacts(doc, root, marker):
    """Return problems for the content-addressed store at ROOT (ROOT/sha256/<hex>).

    Every artifact the bundle names must exist and hash to its name. Each artifact is
    read once. Every session command is matched against the whole-argument tokens, and
    its --no-audio token must agree with the declared no_audio_flag. For each audio-off
    session, the journal must contain MARKER, the operator-supplied audio-off marker, as
    UTF-8 bytes. The command of startup_checks.no_audio_precedence_session must contain
    the --enable-audio and --no-audio tokens, and the command of
    startup_checks.null_audio_nonzero_master_session must contain neither. Commands and
    journals are checked only when their hash verified.
    """
    if not os.path.isdir(root):
        return ["%s: artifact root is not a directory" % root]
    reason = marker_problem(marker)
    if reason is not None:
        return ["audio-off marker: %s" % reason]
    marker_bytes = marker.encode("utf-8")
    sessions = doc.get("sessions") if isinstance(doc.get("sessions"), list) else []
    sessions_by_id = _index_by_name(sessions, "id")
    startup = doc.get("startup_checks")
    startup = startup if isinstance(startup, dict) else {}
    precedence = _named_session(startup, "no_audio_precedence_session", sessions_by_id)
    null_audio = _named_session(startup, "null_audio_nonzero_master_session", sessions_by_id)
    plain = {}
    tokens = {}
    for session in sessions:
        if not isinstance(session, dict):
            continue
        _want(tokens, session.get("command_sha256"), NO_AUDIO_TOKEN)
        if session.get("audio_mode") == "off":
            _want(plain, session.get("journal_sha256"), marker_bytes)
    for named in (precedence, null_audio):
        if named is not None:
            _want(tokens, named.get("command_sha256"), ENABLE_AUDIO_TOKEN)

    problems = []
    status = {}
    found = {}
    for digest, location in artifact_hashes(doc):
        if digest in status:
            continue
        full = os.path.join(root, "sha256", digest)
        if not os.path.isfile(full):
            problems.append("%s: artifact %s missing" % (location, digest))
            status[digest] = False
            continue
        actual, seen = _scan_file(
            full, tuple(sorted(plain.get(digest, ()))), tuple(sorted(tokens.get(digest, ())))
        )
        if actual != digest:
            problems.append("%s: artifact %s mismatch" % (location, digest))
            status[digest] = False
        else:
            status[digest] = True
            found[digest] = seen

    for index, session in enumerate(sessions):
        if not isinstance(session, dict):
            continue
        audio_off = session.get("audio_mode") == "off"
        journal = session.get("journal_sha256")
        if audio_off and _verified(status, journal) and marker_bytes not in found[journal]:
            problems.append(
                "sessions[%d].journal_sha256: audio-off journal lacks the audio-off marker"
                % index
            )
        command = session.get("command_sha256")
        if not _verified(status, command):
            continue
        has_flag = NO_AUDIO_TOKEN in found[command]
        if audio_off and not has_flag:
            problems.append(
                "sessions[%d].command_sha256: audio-off command lacks --no-audio" % index
            )
        elif session.get("no_audio_flag") is True and not has_flag:
            problems.append(
                "sessions[%d].command_sha256: command lacks --no-audio but no_audio_flag is true"
                % index
            )
        elif session.get("no_audio_flag") is False and has_flag:
            problems.append(
                "sessions[%d].command_sha256: command contains --no-audio but no_audio_flag is false"
                % index
            )
    if precedence is not None and _verified(status, precedence.get("command_sha256")):
        command = precedence["command_sha256"]
        if ENABLE_AUDIO_TOKEN not in found[command]:
            problems.append(
                "startup_checks.no_audio_precedence_session: command lacks --enable-audio"
            )
        if NO_AUDIO_TOKEN not in found[command]:
            problems.append(
                "startup_checks.no_audio_precedence_session: command lacks --no-audio"
            )
    if null_audio is not None and _verified(status, null_audio.get("command_sha256")):
        command = null_audio["command_sha256"]
        if ENABLE_AUDIO_TOKEN in found[command] or NO_AUDIO_TOKEN in found[command]:
            problems.append(
                "startup_checks.null_audio_nonzero_master_session: command carries an audio flag"
            )
    return problems


def _named_session(startup, key, sessions_by_id):
    """Return the session that the startup check KEY names, or None."""
    name = startup.get(key)
    return sessions_by_id.get(name) if isinstance(name, str) else None


def _registry_entry(path, obj, ctx):
    return [
        printable("%s: %s" % (path, problem))
        for problem in validate_bundle(obj, release=ctx.release)
    ]


SCHEMAS = {SCHEMA_ID: _registry_entry}
