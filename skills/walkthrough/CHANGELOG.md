# Changelog — walkthrough

## 1.0.1

- Terminate the forked PTY test child with exit 127 on setup or exec failure instead of unwinding into the caller; exercise failure paths in isolated subprocesses.

## 1.0.0

- Add standalone human-only operational procedure guidance, a Bash 3.2 launcher and a Python 3.9+ POSIX helper adapted from the pinned Matt Pocock wizard workflow.
- Require sourced setup names, explicit confirmation, hidden noncanonical secret entry, faithful long-value and UTF-8 handling, cancellation, and truthful complete/incomplete/failed/skipped states.
- Store local values as non-executable JSON-string dotenv assignments with the declared loader, private atomic writes and strict destination/key validation; pass GitHub values through stdin without child diagnostics.
- Print validated public dashboard URLs before attempting a short-lived browser launcher; preserve explicit failure and required-skip outcomes.
- Include local references, authored eval coverage, PTY regression tests, MIT attribution and a manual-only resync policy. Static conformance and exercised fixtures do not establish live effectiveness.
