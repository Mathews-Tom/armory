# Delivery Radar

Read-only delivery observations for an explicitly selected GitHub.com repository and set of pull requests. Implementation, verification, review, merge and publication are independent dimensions. A merged PR does not prove successful verification or published artifacts; an exit code of zero means the observation completed, not that a PR is ready to merge.

This core delivery is unregistered. It provides a standalone CLI, deterministic derivation and a bounded GitHub CLI reader. It does not yet install a native extension or claim OMP/Claude compatibility. Complete package metadata, native adapters, lifecycle qualification and catalog activation belong to the native delivery.

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

Only explicitly selected same-repository branch dependencies form graph edges. Missing identities, ambiguous branches and cycles are reported rather than replaced with an invented stack order. Actions separate agent work, external wait and owner decision. Text rendering treats titles, URLs, branch-related diagnostics and source strings as untrusted data, escapes markup and discloses removed control/invisible characters. Semantic transition keys exclude sampling timestamps while retaining meaningful evidence changes.

## Bounds and cancellation

Each explicit refresh permits at most 320 requests, ten pages per source, 60 seconds total, ten seconds per request, 2 MiB per response and 12 MiB total process output. Exhausted budgets produce partial/unavailable evidence, not a successful prefix. Reads use argument vectors without a shell, GraphQL query documents and REST GET operations. The helper owns each `gh` process group and waits for bounded termination of the group on cancellation, timeout or output overflow. Windows process-tree cleanup is unsupported and fails closed.

## Verification

```sh
uv run --python 3.12 python scripts/check_extensions.py --feature delivery-radar --stage core
```

This runs workspace type checking, feature lint and deterministic core/process-backed integration cases. The local provider fixture independently validates request routes, pagination and read-only methods; it exercises real subprocess I/O, resource bounds and descendant cancellation without authenticating a host or contacting GitHub. Explicit selected public-PR reads are separate live observations, not credential-free CI prerequisites. Core success is not complete-package or native-compatibility evidence.
