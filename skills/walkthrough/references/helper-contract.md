# Local helper contract

## Invocation and authority

Keep `walkthrough.sh` and `walkthrough.py` together. From the installed/copied package, the actual interface is:

```sh
ENV_FILE=/canonical/owned/project/.env bash templates/walkthrough.sh run /canonical/owned/project/procedure.json
```

Resolve the existing parent directory first when selecting `ENV_FILE`; macOS paths such as `/var` or `/tmp` may be symlinks. Use their physical path, not a symlink spelling. The destination parent must already exist, be owned by the current effective user and not group/world writable. Every ancestor must be owned by that user or root and not group/world writable, except root-owned sticky directories such as the physical system temporary directory. A private directory beneath that temporary directory is allowed; the shared temporary directory itself is not an allowed final parent. Relative paths, empty components, `.`/`..`, symlink ancestors/targets, nonregular targets, other owners and hardlinked files are refused. Existing files become mode `0600` on successful replacement.

Requires Bash 3.2+ and Python 3.9+ on macOS/Linux, with a real **controlling terminal** (`/dev/tty`), not merely redirected stdin. The helper has no CLI input/value bypass: secrets cannot be arguments or environment variables. It refuses headless capture rather than falling back to echoing input. EOF, an empty captured value and Ctrl-C cancel; an empty value is not an implicit reuse of a previous secret. Each capture is single-line UTF-8 without NUL/CR/LF. Quotes, backslashes, `$`, backticks, whitespace, `#`, `=` and Unicode are data. Values are never printed or inserted into subprocess arguments. Python keeps values in process memory; this is not a memory-erasure tool or protection against a compromised account/terminal.

Hidden capture disables canonical line buffering and terminal echo while retaining signal handling, so long printable UTF-8 values are not truncated by the terminal's canonical input limit. There is no helper-imposed length cap. Enter submits; Ctrl-D cancels even after partial entry; Backspace/Delete removes the preceding UTF-8 character. Terminal mode is restored on submission, cancellation or failure. Confirmation prompts retain ordinary terminal line editing.

Only explicitly approved `gh` stages need GitHub connectivity or credentials. There is no startup authentication/network probe or auto-install. `gh`, browser and action commands are resolved through the operator's trusted `PATH`. A hostile `PATH`/Python runtime/helper/plan can execute arbitrary code: these are trusted inputs. `BROWSER` optionally names **one executable** (path or name), not a shell command or `%s` expression. This makes disposable stub execution possible without real browsers or GitHub writes. Default browser lookup is `open`, `xdg-open`, then `wslview`.

The helper prints the validated public URL before resolving or invoking a browser launcher, so a missing or failed launcher still leaves a human-usable address. `BROWSER` must be a short-lived URL launcher, not a long-running browser binary: the helper synchronously waits for its exit status. A running child is not launch success; interruption cancels, nonzero exit fails, and a missing launcher remains skipped. Successful launcher exit proves only launch, not human navigation or setup completion.

## Concrete plan schema

The top level is exactly `{"stages": [...]}` with a nonempty list. Each stage has exactly the five common fields plus the fields for its kind. Unknown fields or malformed stages fail preflight before any stage side effect. All labels, instructions and source strings are nonempty public single-line text, without terminal control characters. `required` is a boolean, never inferred.

| Kind | Additional fields | Operation and evidence |
| --- | --- | --- |
| `env` | `key` | Hidden capture, atomic secure upsert into `ENV_FILE`; complete means write/rename/fsync returned successfully |
| `gh-secret` | `key`, `repo` | Confirm `WRITE`, hidden capture, `gh secret set KEY --repo OWNER/REPO`, value via stdin |
| `gh-variable` | `key`, `repo` | Confirm `WRITE`, hidden capture, `gh variable set KEY --repo OWNER/REPO`, value via stdin, never `--body VALUE` |
| `open` | `url` | Launch public HTTPS URL; no credentials, query or fragment accepted; launch is not UI/permission success |
| `manual` | none | `BEGIN` consent before showing detailed instructions; `DONE` attests completed human work, `SKIP` records skip; all other replies cancel |
| `action` | `argv` | Show reviewed public argument vector, require exact `APPLY` immediately before executing without shell; success means command exit 0, not proof of business outcome |

Keys match `[A-Za-z_][A-Za-z0-9_]*`; repositories are explicit `owner/name`, not inferred from local Git state. The runner accepts only the six kinds above. It does not interpret templated values or substitutions between stages. If one value is needed in two destinations, enter it at both hidden prompts; neither the plan nor shell becomes a secret transport. Do not put secrets into `argv`, instructions, labels, source strings or URLs. Bare shell interpreters are refused for actions, but arbitrary interpreters/binaries are still executable authority, not a sandbox. Author only reviewed non-shell argument vectors; never hide `eval`/`source` behind another executable.

A concrete **offline demonstration**, not a real project's setup configuration:

```json
{
  "stages": [
    {
      "kind": "env",
      "label": "Capture fixture credential",
      "instruction": "Paste the disposable test credential; this fixture has no dashboard UI.",
      "source": "Synthetic acceptance fixture; TEST_TOKEN is not a production key",
      "required": true,
      "key": "TEST_TOKEN"
    }
  ]
}
```

Replace the fixture with actual sourced names/instructions when authoring a real procedure. The helper deliberately has no real service/setup/CI defaults. To open a dashboard, put a public URL in an `open` stage before capture; unknown navigation remains explicit in the instruction. A manual irreversible operation needs its label to identify the consequence **before** `BEGIN`, with recovery limits in the approved stage list; use `DONE` only after the human observes the intended result. An executable cutover must put its entire concrete argument vector in `argv`; rejection runs none of that command. No generated-script permission is equivalent to user approval of irreversible behavior.

## Non-executable dotenv and its consumer

Managed values use one physical line `KEY=JSON_STRING`, for example:

```text
TEST_TOKEN="single' double\" dollar$ backtick` slash\\ unicode\u00e9"
```

The declared consumer is **`walkthrough.py:load_values(path, keys)`**, not a generic shell or an unspecified dotenv library. It selects only requested managed keys, parses RHS with `json.loads`, requires string values, rejects duplicates/missing keys, and never evaluates/interpolates. A caller can load the sibling module using Python's `importlib.util.spec_from_file_location`, then call `load_values(canonical_env_path, ["ACTUAL_DISCOVERED_KEY"])` and pass the returned dictionary directly to its application. Import performs no run or writes. Do not log the returned dictionary. This is a dotenv-shaped data format; standard dotenv parsers have varying escape/interpolation rules and are **not claimed compatible**. If the real project's loader is different, this destination stays blocked until compatibility is established or the application explicitly adopts this consumer. Never `source`, `eval`, shell-expand or execute the file.

Upsert preserves all unrelated original bytes, comments and values. It removes all assignments of the selected key (including whitespace/`export` variants), then appends one encoded assignment. An unterminated final unrelated line gains a separator newline. It does not rewrite/decode unrelated conventional dotenv values; `load_values` only supports managed keys, not conversion of an arbitrary existing dotenv file. Rerunning prompts again and preserves other keys; empty input cancels rather than retaining a secret silently.

Writes use a random exclusive mode-`0600` temporary file in the pinned parent directory, write/flush/fsync, then atomic same-directory replacement and directory fsync. The old file is never truncated in place. Tempfiles are removed on ordinary failure, EOF or interruption. Existing destination identity/content metadata is compared before replacement; detected changes fail rather than overwrite. This is not a concurrent-writer transaction/lock: run one operator at a time, with no competing writes to the same dotenv file. Filesystems without directory-fsync support fail honestly, potentially after rename. Abrupt process death/power loss can leave a secure tempfile; do not assume rollback.

## States, exit status and recovery

- Each successful stage prints `STAGE N complete`; a missing `gh`/browser or a manual `SKIP` prints `STAGE N skipped`.
- **`STATE complete`, exit 0:** every required stage completed. Optional skips are counted and remain explicitly skipped.
- **`STATE incomplete`, exit 2:** a required stage was skipped, including a required GitHub write when `gh` is absent. Stop before later/dependent stages.
- **`STATE incomplete`, exit 130:** EOF, SIGINT, empty capture, or rejected confirmation. Stop immediately; no later stage runs. Rejected action/GitHub confirmation invokes no write command. Rejected manual `BEGIN` shows no detailed operation instructions.
- **`STATE failed`, exit 1:** invalid plan/path/key, local write error, required or optional attempted GitHub write failure, browser failure, or action failure. A failed optional operation is still failure, not a silently successful skip. No later stage runs. Missing Python is also failed/nonzero from the launcher.

Earlier completed stages remain after any non-success; this is not a rollback mechanism. Failure during or after a remote/irreversible action can leave its outcome unknown. Inspect remote/current state before rerunning; `gh` success is only an accepted API operation, not evidence a later CI job consumed it. A manual `DONE` is explicitly human-reported evidence. No global “all configured” message is printed after required skips or failures.

All subprocess stdout/stderr is suppressed, including `gh` diagnostics that may echo a secret. Captured values go only to the approved file or subprocess stdin. Errors are generic, never exception tracebacks/values. For failure investigation, inspect non-secret status separately; do not rerun with secret tracing. Human-side terminal capture and shell history must also follow the operator's security policy.

## Offline acceptance handoff

`tests/test_walkthrough.py` uses pytest, a real controlling PTY and disposable `ENV_FILE`, plus `PATH`/`BROWSER` stubs; it invokes the actual Bash launcher. No real account/browser/credentials or runtime network is needed. It covers special-character roundtrip through the declared consumer, echo suppression, secure final modes and upsert, invalid keys/target types/ancestry, write failure preservation, EOF/SIGINT/empty cancellation, action rejection, required missing `gh`, noisy failing `gh`, browser stubbing and optional human skips. Authored tests are not evidence of a passing run. Authorized orchestrators can run `python3 -m pytest skills/walkthrough/tests/test_walkthrough.py`; never substitute a live GitHub write for these fixtures.

Additional PTY regressions cover exact roundtrip of more than 8192 UTF-8 bytes through the declared consumer, UTF-8 backspace editing, terminal-mode restoration, absence of secret output, and public URL retention with missing/failing launcher stubs.
