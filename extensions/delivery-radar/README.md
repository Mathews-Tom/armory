# Delivery Radar

Read-only delivery observations for an explicitly selected GitHub.com repository and set of pull requests. Implementation, verification, review, merge and publication are independent dimensions. A merged PR does not prove successful verification or published artifacts; an exit code of zero means the observation completed, not that a PR is ready to merge.

The package includes the standalone CLI, pure derivation rules and explicit OMP/Claude Code adapters. It uses existing GitHub authentication and keeps only session-local derived transition state, never a durable feature store. Native compatibility is a separate fail-closed local/manual qualification, not a consequence of CI or package registration.

## Standalone command

Use the repository-pinned Bun workspace and an already configured `gh` login for GitHub.com. The reader does not start OAuth, change accounts or manage credentials.

```sh
bun install --cwd extensions --frozen-lockfile
bun extensions/delivery-radar/helpers/cli.ts refresh --repo Mathews-Tom/armory --prs 190,191 --format text
```

Select 1–20 unique positive PR numbers. Repository and PR selection are required; no repository discovery, global feed, background polling or persistent state is created. `--format json` is the default and returns the original normalized observation together with its derived view. All observation timestamps are epoch milliseconds.

`--help` prints arguments without contacting GitHub. Invalid or repeated arguments fail with exit 2; SIGINT/SIGTERM cancel owned reads and return 130/143. No model request, merge, review solicitation, mention, thread resolution, cleanup or publication operation is performed.

## Evidence and unknowns

The reader brackets each selected PR with fresh identity reads and brackets the whole observation with viewer reads. Sources record repository/PR/head/base/viewer bindings, observation time, a source reference and visibility status. Freshness defaults to five minutes. Changed head/base/viewer, stale observations, malformed or incomplete selection, missing sources and partial pagination prevent the affected conclusion from becoming green.

Reviews use current-head commit identities, latest substantive reviewer decisions, dismissals and unresolved threads, including outdated unresolved threads. Basic approval counts cannot prove codeowner eligibility or latest-push-approval requirements. Required policy combines visible traditional branch protection with effective branch rules; inaccessible or unmodelled policy stays unknown.

Checks retain exact GitHub App publisher IDs and distinguish pending, failed, cancelled, unavailable and unknown results. A check-suite's mutable PR association does not prove the base actually tested by a run. The current GitHub reader therefore reports checks as head-only and leaves tested-base verification unknown; it never promotes a successful check to integration acceptance without immutable evidence. Publication remains unknown because no independent artifact-provenance source is selected. Workflow success and merge state are not publication evidence.
Malformed, plain-HTTP, credential-bearing and schema-incompatible optional check display links are omitted without discarding independent check states or publisher evidence. The helper reuses the normalized URL policy, including whitespace, spelling and provenance limits, rather than relying on WHATWG parsing alone. PR identity URLs remain strictly validated.

Only explicitly selected same-repository branch dependencies form graph edges. Missing identities, ambiguous branches and cycles are reported rather than replaced with an invented stack order. Actions separate agent work, external wait and owner decision. Text rendering treats titles, URLs, branch-related diagnostics and source strings as untrusted data, escapes markup and discloses removed control/invisible characters. Semantic transition keys exclude sampling timestamps while retaining meaningful evidence changes.

## Bounds and cancellation

Each explicit refresh permits at most 320 requests, ten pages per source, 60 seconds total, ten seconds per request, 2 MiB per response and 12 MiB total process output. Exhausted budgets produce partial/unavailable evidence, not a successful prefix. Reads use argument vectors without a shell, GraphQL query documents and REST GET operations. The helper owns each `gh` process group and waits for bounded termination of the group on cancellation, timeout or output overflow. Windows process-tree cleanup is unsupported and fails closed.

## Native commands

```text
/armory-delivery help
/armory-delivery refresh Mathews-Tom/armory 190,191
/armory-delivery refresh Mathews-Tom/armory 191 --json
```

Both adapters return the same independently derived view. Native JSON is `{view, transition}`, not the standalone helper's `{observation, view}` envelope. The helper's claimed view is never trusted: each adapter revalidates the selected repository/ordered PRs and derives the native answer from guarded source observations. Invalid selection is refused without a GitHub read. Process or protocol failure produces a safe error, not a fabricated ready view or raw provider diagnostics.

Claude's terminal result uses a command-owned wrapping frame rather than the host's clipped default row. JSON string spaces are Unicode-escaped so terminal word wrapping cannot alter source titles or reasons; ordinary JSON parsing restores the exact strings. Host notices outside the frame are not part of the result. Headless invocations return the same answer without requiring a terminal frame.

The first successful sample for an ordered selection establishes a baseline (`transition: false`). A meaningful evidence change for that same selection produces `true` once; identical evidence with different sampling times remains `false`. Each explicit command still returns its requested current view. There are no unsolicited notices, widgets, timers that poll, or automatic remote actions. A session change resets transition state and revokes stale publication. OMP includes only its actually observed session ID/cwd as local correlation, never infers the selected repository from cwd.

OMP observes through the in-process bounded helper. Its pinned command context exposes no per-command AbortSignal or unload disposer: session switch/shutdown and a superseding refresh cancel and await owned reads, without intercepting Escape or installing signal handlers. Claude invokes the bundled helper through the native process stream, uses the dispatch AbortSignal and session-end lifecycle, checks the real unsignalled exit status and clears its finite invocation deadline. Each new Claude refresh awaits every previously owned in-flight invocation, including cleanup inherited through multiple superseding requests. Any cleanup failure blocks further helper work rather than claiming termination.

## Build and owned lifecycle

```sh
uv run --python 3.12 python scripts/build_extensions.py --feature delivery-radar --output-dir /tmp/armory-delivery-artifacts
uv run --python 3.12 python scripts/install.py --type extension --platform omp --name delivery-radar --action install --target-root /tmp/armory-delivery-owned-omp --yes
uv run --python 3.12 python scripts/install.py --type extension --platform omp --name delivery-radar --action update --target-root /tmp/armory-delivery-owned-omp --yes
uv run --python 3.12 python scripts/install.py --type extension --platform omp --name delivery-radar --action disable --target-root /tmp/armory-delivery-owned-omp --yes
uv run --python 3.12 python scripts/install.py --type extension --platform omp --name delivery-radar --action remove --target-root /tmp/armory-delivery-owned-omp --yes
```

Choose an explicitly owned host root; substitute `--platform claude` and a separate root for Claude Code. Re-enable an unchanged disabled package with `--action install`. Updates/removal refuse edited or foreign payloads and preserve unrelated settings, files and feature data. No profiles, presets, "all" selection or all-in-one plugin implicitly enable this executable extension.

For one-session loading, use `omp --extension <omp-artifact>/index.ts` or `claude --plugin-dir <disposable-claude-artifact-copy>`. Keep the Claude development-loader copy separate from a managed installation: that loader generates `.claude-plugin/types/` and an extends-only root `tsconfig.json`, which are not Armory-owned lifecycle files. Native qualification checks the root configuration's exact SDK reference and rejects other artifact additions or mutations. Bun and an already configured GitHub CLI are required; neither artifact imports source from this checkout.

## Verification

```sh
uv run --python 3.12 python scripts/check_extensions.py --feature delivery-radar
uv run --python 3.12 python scripts/check_extensions.py --feature delivery-radar --native-smoke
uv run --python 3.12 python scripts/check_extensions.py --all --catalog
```

Credential-free gates run type checking, lint, deterministic core/process-backed integration cases, pinned adapter/native test-kit contracts, offline schema validation, reproducible contained builds and owned lifecycle/package checks. The local provider fixture independently validates request routes, pagination and read-only methods, resource bounds and real descendant cancellation without authenticating a host or contacting GitHub. Static eval dry-runs are unexecuted prompt checks, not measured effectiveness or native proof.

`--native-smoke` additionally requests actual installed-host qualification and fails closed on missing hosts, authentication, trust, policy or supported process control. Preserve normal HOME/default authentication and genuine user/managed enforcement. The Claude driver requires an explicitly reviewed `ARMORY_CLAUDE_NATIVE_CWD` and private additive `ARMORY_CLAUDE_NATIVE_SETTINGS` that contain optional writers without changing enforcement; it never answers trust/login prompts. Use disposable artifacts/session/capture roots. Ordinary host session/log/cache/presence writes can occur; there is no claim of full-profile isolation or network-call metering. Raw captures stay private. Explicit public-PR reads are live observations, not CI prerequisites.

## Exercised compatibility

Actual detached-artifact qualification was exercised on macOS arm64 with the following installed hosts. This is distinct from offline adapter contracts, installation ownership and CI.

| Host | Exercised surface | Observed behavior |
| --- | --- | --- |
| OMP 18.12.6 | RPC | Literal command registration, selected public-PR identities and unknowns, semantic refresh deduplication, text, reopened session, in-flight reads overtaken by `new_session`, stale-publication suppression and owned process-group termination |
| Claude Code 2.1.310 | Terminal interactive | Complete framed text/JSON, exact public-PR source identities, repeated refresh, invalid/unavailable selection, reopen, Ctrl-C helper plus detached `gh` termination, in-flight `/exit` suppression and private artifact/capture boundaries |
| Claude Code 2.1.310 | Whole-native-command headless | Help, selected refresh, invalid selection and unavailable selection, without an ordinary model prompt |

The Claude development loader's generated SDK and exact extends-only root TypeScript configuration are allowed only in the disposable loader copy. Canonical source and complete production artifacts remained byte-equal. No feature persistence was introduced. OMP terminal-interactive UI, SDK/ACP, managed-installed loader behavior, other versions/operating systems and network-call metering are not certified by these native journeys.
