# Launch Mechanics

Verified against `claude` CLI v2.1.x (`claude --version` → `"2.1.x (Claude Code)"`). Re-verify against the installed version before trusting blindly — this is a living CLI, not a stable public API. Probe with `claude --version` before launching anything; a non-zero exit or a response missing `"Claude Code"` means stop and report, not fall back to a different tool.

## The invocation

```bash
claude -p "$(cat "$WORKTREE/.pr-swarm-prompt.md")" \
  --output-format stream-json --verbose \
  --input-format text \
  --strict-mcp-config \
  --permission-mode bypassPermissions \
  --no-session-persistence \
  --session-id "$(python3 -c "import uuid,sys; print(uuid.uuid5(uuid.NAMESPACE_URL, sys.argv[1]))" "pr-swarm-$N")"
```

Flag rationale:

- `-p`/`--print` — non-interactive, print-and-exit mode. Required; without it the process waits for interactive input and the lane never starts.
- `--output-format stream-json --verbose` — real-time NDJSON event stream, needed to tail progress and find the lane's real final message (see "Reading the log" below). A single-shot `--output-format json` only returns a terminal summary and does not distinguish "still working" from "hung."
- `--strict-mcp-config` — suppresses ambient MCP servers from the operator's own `~/.claude`/project config. Without it, a lane silently inherits whatever MCP servers, hooks, and CLAUDE.md the launching environment has configured — an unwanted capability leak for an unattended worker process. This should always be present, not conditional.
- `--permission-mode bypassPermissions` — required for unattended execution; without it the lane blocks on the first tool-approval prompt it can't answer.
- `--no-session-persistence` — avoids polluting the operator's own session history with N automated invocations.
- `--session-id` — a deterministic UUID (v5, namespaced on the PR number) makes each lane's session traceable back to which PR it belongs to, without depending on log-file naming alone.

**There is no CLI-level timeout flag.** `claude --help` has nothing matching `timeout|max-turns|max-time`. If a lane needs a hard time budget, enforce it externally by killing its process group after your own deadline — do not go looking for a flag that doesn't exist.

## Detached background launch

Run each lane's launch as its own, separate shell-tool call — never chain multiple `nohup ... &` launches inside one call. A single call whose foreground command chain completes can have its non-interactive shell reap backgrounded jobs launched earlier in the same chain before they've actually started; verify with `pgrep -fl "pr-swarm-<short>"` immediately after every single launch, not after the whole batch.

```bash
nohup bash -c '
  claude -p "$(cat "'"$WORKTREE"'/.pr-swarm-prompt.md")" \
    --output-format stream-json --verbose --input-format text \
    --strict-mcp-config --permission-mode bypassPermissions \
    --no-session-persistence --session-id "'"$SESSION_ID"'" \
    > "'"$LOGFILE"'" 2>&1
  echo $? > "'"$EXITFILE"'"
' > /dev/null 2>&1 < /dev/null &
disown
```

The `bash -c ... ; echo $? > exitfile` wrapper is what makes a real exit code recoverable later — a bare `nohup cmd &` loses the ability to `wait` for it once the launching shell call returns (the child is reparented, no longer a waitable job of that shell). Expect two PIDs per lane (the wrapper plus the `claude` process) — that's correct, not a double-launch.

`nohup`/`disown` protect against `SIGHUP` when the launching shell exits, but do not by themselves guarantee the child survives every tool-boundary condition a given harness might impose on backgrounded work. **Treat this as unverified until smoke-tested**: launch one real multi-minute lane this way, then confirm its log is still growing a full minute or more after the launching tool call has returned and the conversation has moved on to other work — not immediately, since a boundary-kill looks identical to a healthy lane for the first several seconds. `setsid` (stronger session detachment) is not reliably available on macOS by default (it's a Linux/util-linux tool); don't depend on it as the primary mechanism without checking `command -v setsid` first, and fall back to the `nohup`/`disown` pattern above when absent.

## Liveness checks

```bash
ps -p "$PID" -o pid=,stat=
```

**A `ps -p <pid>` check that only tests "is this PID present" gives a false positive for a zombie.** A process that has genuinely exited but hasn't been reaped yet still has a `ps` row. Always parse the `STAT` column explicitly and treat any state containing `Z` (`Z`, `Z+`) as exited — do not infer liveness from PID presence alone. Check liveness a full minute or more after launch, not immediately, per the detachment caveat above.

## Reading the log — a trailing "aborted" turn is not automatically a failure

A headless run's final turn is sometimes a harness-injected follow-up after the actual task's turn already completed and reported its final status; that trailing turn can itself fail (transient network blip) without touching the real work. Before writing off a process as failed, search backward through the log's NDJSON events for the last `assistant`-role message with non-empty `text` content — that is the lane's real final report, independent of what the very last event in the stream looks like. Still re-verify externally per `references/verification-gates.md` — a self-reported final status is never the gate, aborted trailing turn or not.

## Stale marker files

If `$EXITFILE`/`$LOGFILE` already exist from a previous run of this same swarm against the same repo, clear them (or compare mtime against the new launch timestamp) before relaunching — an old exit marker read as fresh produces a false-positive instant "done" for a lane that hasn't started yet.
