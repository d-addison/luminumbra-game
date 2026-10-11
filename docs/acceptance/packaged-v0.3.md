# Packaged acceptance runbook for v0.3 (game issue #4)

This runbook covers the packaged content, saved-world, and audio-off acceptance
for the v0.3 release. It sets the final v0.3 criteria: audio is off, and no
audible-quality criterion applies to this release.

Engine baseline: `b56cdba12e425ed2786778d5b02c98ba61466584`.

The controlling verdict is the engine document `docs/v0.3-acceptance.md`. This
runbook does not override it. The evidence bundle records what that verdict
rests on: hashes and counts of the native runs.

**NEEDS-NATIVE-RUN**: the packaged acceptance has not been executed on the
qualified machine. No session, scene, forest, or launcher evidence exists yet.
This marker stays until a release-mode validation of a bundle passes.

## Step 0: repository gates before native acceptance

Run both commands from the game repository root before any native run starts.
Both must exit 0 before the native acceptance begins, and both are repeated as
completion conditions in the Native handoff table.

```
python -I -B tools/validate_content.py --root . --release
python -I -B tools/validate_public_tree.py --worktree
```

The first command runs in release mode: pending workloads, scenes, and identities
must be resolved. Pending entries are refused, so a content tree that still has
them is not ready for native acceptance.

## Two validation modes

The validator is `tools/validate_acceptance_evidence.py`. It takes exactly one
of two modes.

- `--structure-only` checks the bundle shape and its cross-field rules: session
  kinds and exit codes (an integer from -2147483648 to 4294967295), audio
  consistency (`off` requires the flag, and the flag requires `off` or a `null`
  session with the flag false), startup checks, refusal and save rules, scene and
  defect rules, forest agreement, limitations with their closure evidence,
  historical records, and private material. It does not open any artifact. On
  success its last line is `structure-only: artifacts NOT verified`. It refuses
  `--audio-off-marker`.
- `--artifact-root DIR --audio-off-marker TEXT` also verifies the artifacts.
  Every hash the bundle names must exist under the artifact root and hash to its
  name. Each audio-off session journal must contain the marker `TEXT` as UTF-8
  bytes, and each audio-off session command must contain the whole token
  `--no-audio`. The command of `startup_checks.no_audio_precedence_session` must
  contain the whole tokens `--enable-audio` and `--no-audio`. The command of
  `startup_checks.null_audio_nonzero_master_session` must contain neither token.
  Every session command must agree with its declared `no_audio_flag`: the
  `--no-audio` token is required when the flag is true and refused when it is
  false. Tokens are matched as whole arguments, as the engine's exact argument
  comparison sees them. A token counts only when the start of the file, whitespace,
  a single or double quote, or NUL comes before it, and the end of the file,
  whitespace, a quote, or NUL comes after it. Any other byte next to the token
  disqualifies it, including `=`, `.`, `/`, `\`, `:`, `;`, parentheses, letters,
  digits and `-`, so `--no-audio=1`, `--no-audio.exe` and `x--no-audio` do not
  count. A quoted `"--no-audio"` does count. Commands and journals are checked
  only when their hash verified. Each artifact is read once. The marker is an operator input, not a bundle field: the bundle cannot
  supply its own audio-off proof. `TEXT` must be at least 8 characters, not only
  whitespace, with no control characters. `--artifact-root` without
  `--audio-off-marker` is a usage error. On success it prints
  `artifacts verified: <n>`, where `<n>` is the count of distinct artifacts.

`--release` adds the release gate. It refuses any scene defect with disposition
`open`, any limitation with status `open` and `blocks_release` true, and any
bundle whose `launcher.preview_audio_off` or `disabled_backend.settings_preserved`
is not true. It requires `--artifact-root`. Using `--release` without
`--artifact-root` is a usage error (exit 2). Giving both modes, or neither, is
also a usage error.

Exit codes: 0 ok, 1 invalid, 2 usage error. Problems print one per line as
`PATH: reason`, where PATH is a json-path such as `sessions[2].exit_code`, and at
most 50 lines are printed.

## Content-addressed artifact root

The artifact root is a directory with one file per distinct hash:

```
DIR/
  sha256/
    <64 lowercase hex characters>   one file per hash, content = the artifact
```

A file's name is the sha256 of its content. The hashes the bundle names are the
package archive, each content pack, each session's command and journal, each save
file's before and after hash, each scene capture, the forest submission and
report, the launcher identity, the disabled-backend proof, and the closure
evidence of each closed limitation (`limitations[].closure_sha256`).

The closure evidence of a closed limitation is its retained completion record.
Each closed entry's closure hash must differ from the package archive hash and
from every other entry's closure hash, so one artifact cannot close two gaps or
stand in for the archive. The validator checks only that the record is stored and
hashes to its name. It does not decide whether the record proves completion. That
judgement is the human review of the release, and the release mode check does not
replace it.

## Evidence is hash-only

The bundle stores hashes and counts, never the material. Do not commit private
audio, Steam SDK payloads, saves, journals, captures, or reports to this
repository. The validator refuses private file extensions (audio, archives,
binaries, libraries, SDK and key material; the list is in
`tools/validators/acceptance.py`, matched case-insensitively). A private extension is refused
wherever it appears in a string unless an ASCII letter or digit follows it, so a bare `.wav` and
`recording (1).wav` are refused while `capture.wavelength` is accepted. Within one save, a repeated
file path is refused, comparing paths with Windows case folding (`world/A.txt` and `world/a.txt`
collide). The validator also refuses local or
network path shapes (drive paths, user home directories on Linux and macOS,
UNC server shares, extended device paths, and `//` network shares) in every string of a bundle, so a
bundle that names such material is rejected. A UNC or device path is recognised at the start of a string
or after whitespace, a quote, a parenthesis, a bracket, a brace, a comma, a semicolon, an equals sign, or
`<`, or a colon (backslash forms only, so `see:\\server\share` is refused). URLs are allowed, and so is
`see://server/share`, because a colon before `//` is not a boundary. A save path component may not contain a control character
(U+0000 through U+001F or U+007F). Every problem the validator reports escapes control
characters as `\n`, `\r`, `\t` or `\xNN`, so each diagnostic stays on one line.

## Criteria

Each row names the criterion, the command or procedure that produces the
evidence, the artifact expected, and the bundle key that records the result.

| Criterion | Command or procedure | Expected artifact | Evidence key |
|---|---|---|---|
| Pinned composition (client, server, tree) | Build the package from the pinned engine and game revisions; run `python3 -I -B tools/validate_public_tree.py --root . --worktree` on the game tree | Package archive; clean tree guard | `package.git_sha`, `package.archive_sha256`, `engine.rev`, `game.rev`, `content.packs` |
| Save flow: create, edit, save, restart, load | Operator supplies the packaged launch command; its sha256 goes in `command_sha256`. Run each step and keep its journal | Command and journal per session; before and after hash of each edited save file | `sessions[]` kinds `create`, `edit`, `save`, `restart`, `load`; `saves[].files` |
| Repeated switching | Same as above, switching between two saved worlds at least twice | Command and journal per switch | `sessions[]` kind `switch`, at least two |
| Refusals with refusal code and unchanged saves | Trigger each refusal path; record the exit code and refusal code. List in `saves` the saves the refusal leaves in place | Command and journal per refusal; refusal exit codes listed in policy | `sessions[]` kind `refusal` with `refusal_code`, `saves` (non-empty; each name must exist in `saves[]`), and `saves_unchanged`; every file of each referenced save has equal before and after hashes |
| Six settled scenes, each with a defect disposition | Capture each of six scenes; record each defect as `accepted`, `fixed`, or `waived` (release refuses `open`) | Capture per scene | `scenes[]` (at least six), `settled`, `defects[].disposition` |
| Forest submission and report agreement | Run the forest check described in the engine document; record both documents | Forest submission and report documents | `forest.agree`, `forest.submission_sha256`, `forest.report_sha256` |
| Normal startup selects null audio regardless of saved volume | Launch the packaged client with a nonzero saved master volume and without an audio flag | Journal | `startup_checks.null_audio_nonzero_master_session` names a session with `audio_mode` `null`, `no_audio_flag` false, and `saved_master` above zero; its command must contain neither `--enable-audio` nor `--no-audio` |
| `--no-audio` wins over a diagnostic opt-in | Launch with both `--enable-audio --no-audio` (the diagnostic opt-in and the audio-off flag). The engine document states that `--enable-audio` is an experimental diagnostic opt-in and that `--no-audio` always suppresses it | Journal containing the audio-off marker | `startup_checks.no_audio_precedence_session` names a `restart` or `load` session with `audio_mode` `off` and `no_audio_flag` true; its command must contain the whole tokens `--enable-audio` and `--no-audio` |
| Disabled settings controls preserve settings | Operator checks each disabled settings control and confirms the stored settings are unchanged | Proof record | `disabled_backend.proof_sha256`, `disabled_backend.settings_preserved` (release requires true) |
| Preview launcher stays audio-off and its guard holds | Run the preview launcher; record its identity and the preview session | Launcher identity; preview journal with the audio-off marker | `launcher.identity_sha256`, `launcher.preview_audio_off` (release requires true); `sessions[]` kind `preview` |
| Finite residency and distant cave/edit omissions | Not accepted for v0.3. Each gap is recorded as a `limitations[]` entry with status `open`, `blocks_release` true, and `closure_sha256` null. It stays open until the final requirement is met: an unbounded world with 16 km distant coverage, with edits and caves in distant tiers (the expanded v0.3 contract). Only then may the entry become `closed`, with `closure_sha256` set to the sha256 of its closure evidence (a 64-character lowercase hex value that differs from the package archive hash and from the other closure hash; the artifact must be in the artifact root). An open entry must have a null `closure_sha256`. | Closure evidence, once closed | `limitations[]` ids `finite-residency`, `distant-cave-edit-omitted`, with `status`, `blocks_release` and `closure_sha256`; both entries are mandatory in every bundle with `blocks_release` true; `--release` refuses either while open |
| Historical application hang kept as a record | Kept as the historical record of the client hang (exit `0xCFFFFFFF`, 3489660927 unsigned, -805306369 signed; see the engine document section "Native client hang (PID 66604)"). It is never counted as a session exit and is refused as an exit code in every session. A recurrence blocks publication | None | `historical[]` kind `application-hang` |

The startup and precedence rows are checked by the bundle itself. The first
`startup_checks` session must be `null` audio with a nonzero saved master and no
audio flag. The second must be a `restart` or `load` session with audio `off` and
the flag set, and its command must contain the whole tokens `--enable-audio` and `--no-audio`. The `sessions[]` list must hold at least two `switch` sessions.
The command artifacts are checked only with `--artifact-root`: the first startup
session's command must contain neither audio token, and every session's command
must agree with its declared `no_audio_flag`.

## Native handoff

| Item | Value |
|---|---|
| Owner | Operator on the qualified machine |
| Candidate identity | The package git sha and the package archive sha256 in the bundle |
| Launch conditions | Quoted from the engine document `docs/v0.3-acceptance.md`, section "Native client hang (PID 66604)": "every remaining native acceptance run launches with the watchdog armed and stdout on local disk, and a recurrence must be examined through its actual hang report and dump before any verdict; a recurrence blocks publication." The watchdog is armed with the documented opt-in `--hang-watchdog-seconds N`; N must exceed the longest legitimate stage (such as a large save). Stdout goes to a file on local disk, not over the WSL network redirector |
| Commands | Step 0 commands above; the criteria commands above; the packaged launch command is supplied by the operator and its sha256 goes in `command_sha256`; the audio-off marker text is supplied by the operator as `--audio-off-marker TEXT` |
| Completion | All of the following hold: `python -I -B tools/validate_content.py --root . --release` exits 0; `python -I -B tools/validate_public_tree.py --worktree` exits 0; `python3 -I -B tools/validate_acceptance_evidence.py BUNDLE.json --artifact-root DIR --audio-off-marker TEXT --release` exits 0 and prints `artifacts verified: <n>`; no hang recurrence is open |

Until that release-mode validation passes, the status of this runbook is
NEEDS-NATIVE-RUN.

## Commands for the bundle

```
python3 -I -B tools/validate_acceptance_evidence.py BUNDLE.json --structure-only
python3 -I -B tools/validate_acceptance_evidence.py BUNDLE.json --artifact-root DIR --audio-off-marker TEXT
python3 -I -B tools/validate_acceptance_evidence.py BUNDLE.json --artifact-root DIR --audio-off-marker TEXT --release
```

The bundle schema is `luminumbra.game.acceptance-evidence.v1`. CI runs the unit
tests and the public tree guard. It does not run the packaged client.
