"""Acceptance evidence bundle: schema luminumbra.game.acceptance-evidence.v1.

validate_bundle checks a parsed bundle: structure, cross-field rules, and a
whole-document scan for private material. With release=True it also refuses
open defects and open blocking limitations. artifact_hashes lists the hashes a
bundle names, and verify_artifacts reads the content-addressed store
DIR/sha256/<hex>, recomputes every hash, and checks that audio-off session
journals contain the policy marker.

The bundle stores hashes and counts only; the store holds the artifacts.
Problems are strings of the form "PATH: reason", where PATH is a json-path
style location such as sessions[2].exit_code.

The module is also registered in the content registry (SCHEMAS) so that a
bundle placed under content/ gets the structural checks.
"""

import hashlib
import os
import re
from decimal import Decimal

from lumlib.schema import SchemaError, check_keys, check_schema_id, is_kebab
from validate_public_tree import ABSOLUTE_PATH_PATTERNS

SCHEMA_ID = "luminumbra.game.acceptance-evidence.v1"
HANG_EXIT_CODE = 0xCFFFFFFF
MIN_SCENES = 6
MAX_NOTE_LENGTH = 200
SESSION_KINDS = ("create", "edit", "save", "restart", "load", "switch", "refusal", "preview")
AUDIO_MODES = ("null", "off")
DISPOSITIONS = ("accepted", "fixed", "open", "waived")
LIMITATION_STATUSES = ("open", "closed")
HISTORICAL_KIND = "application-hang"
PRIVATE_EXTENSIONS = (
    ".wav", ".ogg", ".flac", ".mp3", ".m4a", ".aac", ".wma",
    ".dll", ".so", ".exe", ".sav", ".lmc", ".zip",
)

ROOT_KEYS = frozenset(
    [
        "schema", "package", "engine", "game", "content", "policy", "sessions", "saves",
        "scenes", "forest", "launcher", "disabled_backend", "limitations", "historical",
        "unresolved_diagnostics",
    ]
)
SESSION_KEYS = frozenset(
    [
        "id", "kind", "command_sha256", "journal_sha256", "exit_code", "audio_mode",
        "no_audio_flag", "saved_master",
    ]
)
REFUSAL_KEYS = frozenset(["refusal_code", "saves_unchanged"])

_HEX64 = re.compile(r"[0-9a-f]{64}")
_HEX40 = re.compile(r"[0-9a-f]{40}")
_DRIVE_START = re.compile(r"[A-Za-z]:")
_DRIVE_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:(?:\\|/(?!/))")
_LOCAL_PATTERNS = (re.compile("/ho" "me/"), re.compile("/Us" "ers/"))


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
    return (_is_int(value) or isinstance(value, Decimal)) and value >= 0


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
    if not _keys(problems, value, path, ("audio_off_marker", "refusal_exit_codes")):
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
    marker = value["audio_off_marker"]
    marker_path = _join(path, "audio_off_marker")
    if not isinstance(marker, str) or not marker:
        problems.append("%s: must be a non-empty string" % marker_path)
    elif any(ord(char) < 0x20 or ord(char) == 0x7F for char in marker):
        problems.append("%s: must not contain control characters" % marker_path)


def _refusal_codes(doc):
    policy = doc.get("policy")
    codes = policy.get("refusal_exit_codes") if isinstance(policy, dict) else None
    if not isinstance(codes, list):
        return set()
    return {code for code in codes if _is_int(code)}


def _check_exit_code(problems, session, here, codes):
    path = _join(here, "exit_code")
    code = session["exit_code"]
    if not _is_int(code):
        problems.append("%s: must be an integer" % path)
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


def _check_sessions(problems, value, path, codes):
    if not _list(problems, value, path):
        return
    seen = set()
    kinds = set()
    for index, session in enumerate(value):
        here = "%s[%d]" % (path, index)
        kind = session.get("kind") if isinstance(session, dict) else None
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
            problems.append("%s: must be a non-negative number" % _join(here, "saved_master"))
        if audio == "off" and flag is False:
            problems.append("%s: audio_mode off requires no_audio_flag true" % here)
        if session["kind"] == "preview" and not (audio == "off" and flag is True):
            problems.append("%s: preview requires audio_mode off and no_audio_flag true" % here)
        if kind == "refusal":
            refusal_code = session["refusal_code"]
            if not isinstance(refusal_code, str) or not refusal_code:
                problems.append("%s: must be a non-empty string" % _join(here, "refusal_code"))
            if session["saves_unchanged"] is not True:
                problems.append("%s: must be true" % _join(here, "saves_unchanged"))
    for kind in SESSION_KINDS:
        if kind not in kinds:
            problems.append("%s: missing session kind '%s'" % (_where(path), kind))


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
        refusal = isinstance(name, str) and name.endswith("-refusal")
        files_path = _join(here, "files")
        if not _list(problems, save["files"], files_path, minimum=1):
            continue
        for position, entry in enumerate(save["files"]):
            entry_here = "%s[%d]" % (files_path, position)
            if not _keys(problems, entry, entry_here, ("path", "sha256_after", "sha256_before")):
                continue
            _check_portable_path(problems, entry["path"], _join(entry_here, "path"))
            before_ok = _hex(problems, entry["sha256_before"], _join(entry_here, "sha256_before"))
            after_ok = _hex(problems, entry["sha256_after"], _join(entry_here, "sha256_after"))
            if before_ok and after_ok and entry["sha256_before"] != entry["sha256_after"]:
                edited = True
                if refusal:
                    problems.append(
                        "%s: a refusal save must leave every file unchanged" % entry_here
                    )
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
        for position, defect in enumerate(scene["defects"]):
            defect_here = "%s[%d]" % (defects_path, position)
            if not _keys(problems, defect, defect_here, ("disposition", "id", "note")):
                continue
            if not isinstance(defect["id"], str) or not defect["id"]:
                problems.append("%s: must be a non-empty string" % _join(defect_here, "id"))
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


def _check_launcher(problems, value, path):
    if not _keys(problems, value, path, ("identity_sha256", "preview_audio_off")):
        return
    _hex(problems, value["identity_sha256"], _join(path, "identity_sha256"))
    if not isinstance(value["preview_audio_off"], bool):
        problems.append("%s: must be true or false" % _join(path, "preview_audio_off"))


def _check_disabled_backend(problems, value, path):
    if not _keys(problems, value, path, ("proof_sha256", "settings_preserved")):
        return
    _hex(problems, value["proof_sha256"], _join(path, "proof_sha256"))
    if not isinstance(value["settings_preserved"], bool):
        problems.append("%s: must be true or false" % _join(path, "settings_preserved"))


def _check_limitations(problems, value, path, release):
    if not _list(problems, value, path):
        return
    seen = set()
    for index, entry in enumerate(value):
        here = "%s[%d]" % (path, index)
        if not _keys(problems, entry, here, ("blocks_release", "id", "status")):
            continue
        _check_id(problems, entry["id"], _join(here, "id"), seen)
        status = entry["status"]
        if status not in LIMITATION_STATUSES:
            problems.append("%s: must be open or closed" % _join(here, "status"))
        if not isinstance(entry["blocks_release"], bool):
            problems.append("%s: must be true or false" % _join(here, "blocks_release"))
        elif release and status == "open" and entry["blocks_release"] is True:
            problems.append("%s: open blocking limitation is refused in release mode" % here)


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
    """Refuse private extensions and local path shapes in every string value."""
    if isinstance(value, str):
        lowered = value.lower()
        for extension in PRIVATE_EXTENSIONS:
            if lowered.endswith(extension):
                problems.append(
                    "%s: private file extension '%s' is not allowed; evidence stores hashes and counts only"
                    % (_where(path), extension)
                )
                return
        if _DRIVE_PATH.search(value) or any(
            pattern.search(value) for pattern in ABSOLUTE_PATH_PATTERNS + _LOCAL_PATTERNS
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
        return [str(exc)]
    problems = []
    _keys(problems, doc, "", ROOT_KEYS)
    codes = _refusal_codes(doc)
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
        _check_sessions(problems, doc["sessions"], "sessions", codes)
    if "saves" in doc:
        _check_saves(problems, doc["saves"], "saves")
    if "scenes" in doc:
        _check_scenes(problems, doc["scenes"], "scenes", release)
    if "forest" in doc:
        _check_forest(problems, doc["forest"], "forest")
    if "launcher" in doc:
        _check_launcher(problems, doc["launcher"], "launcher")
    if "disabled_backend" in doc:
        _check_disabled_backend(problems, doc["disabled_backend"], "disabled_backend")
    if "limitations" in doc:
        _check_limitations(problems, doc["limitations"], "limitations", release)
    if "historical" in doc:
        _check_historical(problems, doc["historical"], "historical")
    if "unresolved_diagnostics" in doc:
        _check_diagnostics(problems, doc["unresolved_diagnostics"], "unresolved_diagnostics")
    _scan_strings(doc, "", problems)
    return problems


def artifact_hashes(doc):
    """Return (sha256 hex, location) for each artifact the bundle names, in document order."""
    refs = []

    def add(value, location):
        if isinstance(value, str) and _HEX64.fullmatch(value):
            refs.append((value, location))

    package = doc.get("package")
    if isinstance(package, dict):
        add(package.get("archive_sha256"), "package.archive_sha256")
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
    return refs


def artifact_count(doc):
    """Return the number of distinct artifacts the bundle names."""
    return len({digest for digest, _location in artifact_hashes(doc)})


def _file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _marker(doc):
    policy = doc.get("policy")
    marker = policy.get("audio_off_marker") if isinstance(policy, dict) else None
    return marker if isinstance(marker, str) and marker else None


def verify_artifacts(doc, root):
    """Return problems for the content-addressed store at ROOT (ROOT/sha256/<hex>).

    Every artifact the bundle names must exist and hash to its name. Each
    audio-off session journal must contain the policy marker as UTF-8 bytes.
    """
    if not os.path.isdir(root):
        return ["%s: artifact root is not a directory" % root]
    problems = []
    status = {}
    for digest, location in artifact_hashes(doc):
        if digest in status:
            continue
        full = os.path.join(root, "sha256", digest)
        if not os.path.isfile(full):
            problems.append("%s: artifact %s missing" % (location, digest))
            status[digest] = False
        elif _file_sha256(full) != digest:
            problems.append("%s: artifact %s mismatch" % (location, digest))
            status[digest] = False
        else:
            status[digest] = True

    marker = _marker(doc)
    sessions = doc.get("sessions")
    if marker is not None and isinstance(sessions, list):
        needle = marker.encode("utf-8")
        for index, session in enumerate(sessions):
            if not isinstance(session, dict) or session.get("audio_mode") != "off":
                continue
            journal = session.get("journal_sha256")
            if not isinstance(journal, str) or status.get(journal) is not True:
                continue
            with open(os.path.join(root, "sha256", journal), "rb") as handle:
                data = handle.read()
            if needle not in data:
                problems.append(
                    "sessions[%d].journal_sha256: audio-off journal lacks the audio-off marker"
                    % index
                )
    return problems


def _registry_entry(path, obj, ctx):
    return ["%s: %s" % (path, problem) for problem in validate_bundle(obj, release=ctx.release)]


SCHEMAS = {SCHEMA_ID: _registry_entry}
