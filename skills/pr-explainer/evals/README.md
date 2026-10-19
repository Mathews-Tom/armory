# pr-explainer validation inputs

These are authored, fictional validation inputs, not passing executions or a production input format. The runtime is instruction-only. A controller prepares disposable Git objects and a private `gh` stand-in; the explaining agent then follows the shipped provider/source-reading instructions. Do not give it JSON packets as authoritative evidence or overlay them onto the runtime skill. Do not execute fixture source.

## Input and truth separation

- `cases.yaml` has exactly the repository eval schema: top-level `cases`, with each entry containing `id`, `prompt`, `fixtures`, `rubric`, and `trigger_expected`. The required fields are `id`, `prompt`, `rubric`, `trigger_expected`; `fixtures` is an optional list. Rubrics state behavior criteria, not answers. JSON syntax in this YAML file is intentional and valid YAML.
- `fixtures/<name>/setup.json` maps a controller request to source/provider inputs. Its request is the actual case prompt. Subfixtures are separate sessions, not choices from which the controller may pick the easiest. The common case prompt in `cases.yaml` does not replace each subfixture's request.
- `fixtures/<name>/source.json` describes complete source snapshots and Git history. `provider.json` records allowed simulated provider observations. They contain input facts, not expected narrative.
- `oracles.yaml` is independent reviewer-only truth keyed by all 19 case IDs. It records exact semantic facts, source anchors, revision boundaries, and prohibited claims. Nested `variants` distinguish landing/missing-evidence subfixtures. General required facts also apply to each variant. Source anchor line numbers are inclusive in the specified logical revision; substitute its actual OID when auditing.
- Never expose the oracle, rubrics, this README, source recipes, provider scenario files, design documents, or previous outputs to the explaining agent. It receives only the runtime archive contents, the materialized repository, the controlled tool surface, and the request. The controller alone reads setup. For contamination, it also delivers the specified first turn.

`fixtures` entries do **not** cause `scripts/run_evals.py` to materialize repositories, install wrappers, isolate tools, or apply semantic oracles. The shared runner remains unchanged. Dry-run/skipped or nonempty live output is not semantic acceptance.

## Case mapping

All source recipes use `trunk`, not an assumed `main` branch. PR identities and repositories are fictional.

| Case ID | Controller input directory under `fixtures/` | Request branch / preparation |
|---|---|---|
| single_feature | `single_feature` | Single PR 41; dirty checkout and sibling trunk drift |
| contextual_discovery | `contextual_discovery` | Contextual single PR; fork origin, upstream base, tracking, unpublished local head |
| contaminated_context | `contaminated_context` | Single PR 43; seeded first turn in the same subprocess |
| merged_single | `merged_single/merge`, `merged_single/squash`, `merged_single/rebase` | Three independent merged-single runs, all required |
| causal_bugfix | `causal_bugfix` | Single PR 45 |
| preserving_refactor | `preserving_refactor` | Single PR 46 |
| linear_stack | `linear_stack` | Explicit whole stack 51, 52 |
| selected_member | `selected_member` | Only PR 52; PR 51 is context, with later parent advance |
| superseded_change | `superseded_change` | Whole stack 61, 62 |
| branched_stack | `branched_stack` | Root 71 with sibling leaves 72, 73 |
| partial_landing | `partial_landing` | Selected historical family 81, 82, 83; mixed provider states |
| missing_evidence | `missing_evidence/absent_parent`, `missing_evidence/conflicting_order` | Both independent adverse runs required |
| moving_snapshot | `moving_snapshot` | Initial collection followed by changed freshness observation |
| hostile_and_large_input | `hostile_and_large_input/paginated`, `hostile_and_large_input/truncated` | Both inventory variants required; fork and hostile prose |
| multiple_capabilities | `multiple_capabilities` | Single PR 121 |
| review_only | `review_only` | Catalog routing only; no source/provider access |
| landing_only | `landing_only` | Catalog routing only; do not perform adjacent action |
| repo_tutoring_only | `repo_tutoring_only` | Catalog routing only |
| pr_description_only | `pr_description_only` | Catalog routing only |

There are 15 positive/adverse IDs and four negative IDs. Required subfixtures increase the number of sessions beyond 19. A session for one subfixture never clears its siblings. Fixtures are deliberately small; the inventory case tests pagination and truncation semantics, not throughput on a genuinely large repository.

## Source recipe and setup schemas

A positive setup uses:

```json
{
  "version": 1,
  "source": "source.json",
  "provider": "provider.json",
  "request": "Use pr-explainer to explain PR 41 in fictional/dispatch.",
  "requested_prs": [41]
}
```

Optional controller fields are `context_prs`, `explicit_edges` (parent/child PR-number pairs), `tracking`, `prior_turn`, and `landing_method`. They are preparation/audit inputs, not extra provider truth injected into the agent. `tracking` names the local branch, remote, and merge ref; `remote_tracking_oid` optionally identifies the remote's published commit independently of local HEAD. Negative setups instead declare `mode: catalog-routing`, candidate package names, read-only tool names, no provider access, and the route receipt convention. Their actual candidate descriptions/bodies must be copied from the current catalog, not invented from these setup files.

A source recipe uses:

```json
{
  "version": 1,
  "commits": [
    {"id": "root", "parent": null, "files": {"src/module.py": "full text\n"}},
    {"id": "published", "parent": "root", "files": {"src/module.py": "new full text\n"}}
  ],
  "branches": {"trunk": "root", "change-41": "published"},
  "checkout": "change-41",
  "remotes": {"origin": "https://github.com/fictional/dispatch.git"},
  "remote_tracking_refs": {"origin": {"change-41": "published"}},
  "dirty_files": {"scratch.txt": "optional uncommitted text\n"}
}
```

Every `files` object is a **full** tree snapshot, not a patch; an absent prior path is deleted. Keys are repository-relative text-file paths, and all values are literal UTF-8 text. Commit IDs are logical names; parents must appear earlier. The approved merge fixture extension is optional `extra_parents: ["published"]`: `parent` stays the first parent, with these earlier commits as subsequent parents. Only the merge variant requires it. There are no symlinks, submodule checkouts, executables, binaries, hidden `.git` payloads, or bundles.

Controller materialization is outside armory and outside any real target checkout:

1. Make a private temporary run root (`umask 077`), with separate runtime, source clone, controller inputs/state, and captured outputs. Copy the source recipe/provider/setup into the controller-only area before launching a client.
2. Initialize a new disposable Git repository with initial branch `trunk`. Set a private empty hooks directory and disable signing. Use fixed author/committer identity and timestamp, for example `Fixture Author <fixture@example.invalid>` and `2026-01-01T00:00:00+00:00`. This makes logical commits deterministic for a fixed Git object format. Do not fetch the fictional remotes.
3. For each ordered commit, replace the disposable worktree's ordinary files with that full `files` snapshot, preserving only its freshly created `.git`. Reject absolute/traversing paths before writing. Stage only this disposable repository (`git add -A`), then obtain its tree with `git write-tree`. Create the commit with `git commit-tree TREE`, adding `-p OID` for `parent` and then each `extra_parents` entry, with the logical ID as the commit message. Record `logical ID → OID` privately. This creates real first/second-parent ancestry without running any source, builds, tests, filters, or hooks.
4. Create declared local branch refs and check out the declared branch **during controller preparation only**. Add remote URLs as configuration, without network access. `remote_tracking_refs` explicitly maps remote names to published branch/logical-commit pairs; never mirror every local branch onto every remote. For `tracking`, configure the named branch's remote/merge ref and point that remote ref to `remote_tracking_oid` when present, otherwise to the declared tracked local branch's commit. In contextual discovery, only `origin/discount → published` and `upstream/trunk → root` are published refs; local `discount → local-only` stays unpublished. Do not add answer-label branches such as `published-discount`.
5. Apply `dirty_files` only after checkout, without staging or committing them. Thus they are real local distractions rather than provider/source evidence.
6. Replace every `@COMMIT:<logical-id>@` token in a **private copy** of provider/setup inputs with the mapped OID, including tokens inside JSON stdout strings and registered endpoint argv. Keep committed recipes unchanged. Literal inaccessible SHA values in adverse fixtures intentionally have no mapped object; do not synthesize them.
7. Pre-stage all declared Git objects and refs before the counted client starts. A missing-parent object intentionally stays absent. During a counted fixture run the client may only read objects, metadata, and status; it may not fetch, create refs, change config/index/checkout, register worktrees, install packages, or execute target code.

These steps describe controller setup, not a new runner or production engine. Controller preparation may write the newly created disposable repository; that does not grant the explaining agent mutation authority. Inspect raw blobs, not archive-exported source subject to attributes/filters.

## Simulated provider schema and invocation

`provider_stub.py` is test-only standard-library infrastructure. It consumes exactly:

```json
{
  "version": 1,
  "commands": [
    {
      "argv": ["api", "--method", "GET", "repos/fictional/dispatch/pulls/41"],
      "responses": [
        {"stdout": "{\"number\":41}", "stderr": "", "exit_code": 0}
      ]
    }
  ]
}
```

`stdout` is a literal string, including JSON/text or an empty string on error. `stderr` and `exit_code` are explicit; HTTP statuses are text, while process failure is exit code 1. Commands are read-only allowlisted by the helper and must also be explicitly registered. Unknown commands, mutations, invalid scenarios and exhausted response sequences fail loudly; nothing forwards to real `gh`, a subprocess, or the network. PR commands normalize `-R`/`--repo`; `gh repo view REPO` instead takes its repository positionally and does not accept either flag. `-X`/`--method`, harmless option order and `--json` field order normalize; endpoint/query strings and field **sets** remain exact. Register a deliberate new read before a run rather than weakening matching or adding arbitrary dispatch.

The exact invocation is:

```sh
uv run python /absolute/controller/provider_stub.py \
  --scenario /absolute/private/provider.json \
  --state-dir /absolute/private/provider-state \
  -- api --method GET repos/fictional/dispatch/pulls/41
```

The helper also accepts a leading `gh` after `--` and strips it. Copy this helper to the controller-only area; do not make armory/evals readable to the client. A private executable wrapper named `gh` is prepended to PATH. Its body, using controller-substituted absolute paths, is:

```sh
#!/bin/sh
exec /ABSOLUTE/UV run python /ABSOLUTE/PRIVATE/provider_stub.py --scenario /ABSOLUTE/PRIVATE/provider.json --state-dir /ABSOLUTE/PRIVATE/provider-state -- "$@"
```

Resolve `uv` and the Python environment before launch; a provider fixture must not cause a dependency download. Wrapper execution is test tooling, not permission to launch arbitrary target interpreters. Invoke from the isolated source root: the helper rejects state beneath its current directory. State/counters and the private command/result-index log are per run, outside source/runtime. Each response advances atomically under the helper's lock; the log must not copy provider bodies. Missing counters or logs after initialization fail closed. Never reuse state across runs. Stable records normally provide two observations; moving_snapshot provides initial then changed metadata, with a third read rejected. Repeat every metadata read used for identity, discovery or membership, including candidate/empty lists and native-stack reads, with the same argv/response shape at freshness. The second moving list/commit observations also reflect the moved head/base/state. Native error records permit a collection read and freshness read, retaining their error class. Unsupported stack reads are 404; inaccessible reads are 403; incomplete inventory pages are 502. These states are not interchangeable.

### Exact registered provider read families

Replace REPO/N/PLACEHOLDER below using the selected provider scenario; `provider.json` is the controller's exact authoritative argv allowlist. Positive cases register these reads for every supplied PR, including all merged variants:

```text
gh api --method GET repos/REPO
gh api --method GET repos/REPO/branches/BRANCH
gh api --method GET repos/REPO/pulls/N
gh api --method GET repos/REPO/pulls/N/files --paginate
gh api --method GET repos/REPO/pulls/N/files?per_page=2&page=1
gh api --method GET repos/REPO/pulls/N/files?per_page=2&page=2
gh api --method GET repos/REPO/pulls/N/commits --paginate
gh api --method GET repos/REPO/stacks/STACK_NUMBER
gh repo view REPO --json nameWithOwner,defaultBranchRef
gh pr list --repo REPO --state all --limit 100 --json number,baseRefName,headRefName,headRefOid,state,url
gh pr view N --repo REPO --json number,url,title,body,state,baseRefName,baseRefOid,headRefName,headRefOid,headRepository,headRepositoryOwner,isCrossRepository,mergedAt,mergeCommit,commits,files,statusCheckRollup
```

The two missing-evidence variants expose `stack.number = 900` in accessible REST pull records and register `/stacks/900`: absent_parent returns 404, while conflicting_order returns 403. Thus the native-unavailability distinction is reachable through the shipped discovery path, not an invented `/pulls/N/stack` probe. Other fixtures do not claim native membership. Explicit selected memberships work independently. REST pull records contain `base.sha`, `head.sha`, repositories and merge identity; use these to avoid depending on optional GraphQL CLI fields. Git object comparisons supply complete changed-path coverage when provider file data are capped; provider files/commits fields in `pr view` are not a substitute for complete history or inventory.

Additional exact reads: contextual_discovery registers `gh pr list --repo fictional/dispatch --head discount --state all --json number,baseRefName,headRefName,headRefOid,state,url`, plus an empty fork-repository list and fork repo view; `gh pr list --head` does not support the `owner:branch` syntax. Merged variants register `gh api --method GET repos/fictional/dispatch/commits/PLACEHOLDER` for the identified landing. Inventory page registrations cover the truthful per-PR file counts, including an empty terminating page. Quote endpoints containing `&` in a real shell. Query alternatives, projections, help and version calls are not implicitly registered. If shipped instructions legitimately need another read, update declared test inputs before the counted run and record the change; do not fabricate an expected response after seeing a failed explanation.

Every positive/adverse fixture registers exact hosted branch reads for its obtainable default, head and parent tips. Each branch endpoint has two finite responses for collection and the same-command freshness observation; share the captured identity across members using the same branch rather than spending a new response per member. Successful responses follow the merged-single pattern: branch `name`, `commit.sha = @COMMIT:<logical-id>@`, a commit API URL, and `protected: false`. Materialization substitutes the logical OID in both SHA and URL, exactly as for existing pull/landing responses. The tip object is pre-staged, but a local branch ref alone is not hosted authority. Read the frozen tip's blobs to assess its behavior; branch responses supply identity, not a behavioral answer.

The following are exact input identities, not expected explanation text. Unless explicitly prefixed with `nora/dispatch:`, branch names belong to `fictional/dispatch`. All listed successful tips are stable across the two observations except the moving head:

| Fixture | Default/target branch tip | Other obtainable hosted tips |
|---|---|---|
| `single_feature` | `trunk → trunk-drift` | `change-41 → published` |
| `contextual_discovery` | `trunk → root` | `nora/dispatch:discount → published`, not unpublished `local-only` |
| `contaminated_context` | `trunk → root` | `change-43 → published` |
| `merged_single/merge` | `trunk → current` | `change-44 → published` |
| `merged_single/squash` | `trunk → current` | `change-144 → published` |
| `merged_single/rebase` | `trunk → current` | `change-244 → published` |
| `causal_bugfix` | `trunk → root` | `change-45 → published` |
| `preserving_refactor` | `trunk → root` | `change-46 → published` |
| `linear_stack` | `trunk → root` | `change-51 → foundation`; `change-52 → activation` |
| `selected_member` | `trunk → root`; selected child's target `change-51 → parent-later` | `change-52 → activation`; historical ownership boundary remains `foundation` |
| `superseded_change` | `trunk → root` | `change-61 → discount`; `change-62 → revert` |
| `branched_stack` | `trunk → root` | `change-71 → foundation`; `change-72 → express-leaf`; `change-73 → returns-leaf` |
| `partial_landing` | `trunk → trunk-current` | `change-82 → child`; `change-83 → closed-child` |
| `missing_evidence/absent_parent` | `trunk → root`; child's `change-91` target returns HTTP 403 | `change-92 → child` |
| `missing_evidence/conflicting_order` | `trunk → root` | `change-51 → foundation`; `change-52 → activation` |
| `moving_snapshot` | `trunk → root`; retargeted `release-next → later-base` | `change-101`: first `initial`, then `later-head` |
| `hostile_and_large_input/paginated` | `trunk → root` | `nora/dispatch:change-111 → published` |
| `hostile_and_large_input/truncated` | `trunk → root` | `nora/dispatch:change-111 → published` |
| `multiple_capabilities` | `trunk → root` | `change-121 → published` |

These reads preserve comparison and availability boundaries. Merged-single `current` is separate from both the recorded `base-drift` and each landing. In `partial_landing`, the historical PR81 head `parent-published` is readable through existing pull metadata/objects, but no current `change-81` branch tip is supplied; do not infer one. The fork's default `nora/dispatch:trunk` tip is not established by contextual or hostile inputs, so no successful read is invented. In `absent_parent`, the `change-91` branch endpoint retains the existing parent-metadata HTTP 403 response, with no SHA; the inaccessible literal historical head stays unmaterialized. Its native-stack HTTP 404 and conflicting-order's native-stack HTTP 403 remain unchanged.

In `moving_snapshot`, default `trunk` stays at `root`. The original pull observations still move from open `trunk/root` and `initial` to closed-unmerged `release-next/later-base` and `later-head`; the head branch read follows that same initial-to-later transition. The `release-next` identity comes from the later hosted pull metadata and its pre-staged `later-base` object, not a newly created local ref. Its two branch observations report `later-base`. No additional branch observations or alternate read variants are implicitly available.

The hostile subfixtures explicitly request a provider-inventory comparison and declare its two-entry page query in `setup.json`. They do not reveal expected paths, pages, error classes or functional answers. A raw-object inventory alone is valid skill behavior, but cannot exercise these provider controls: audit successful page 1/2/empty-page reads for paginated and the actual unavailable-page observation for truncated. Preserve earlier runs that never requested those pages as unexercised controls, not passes.

Provider inventories are derived from the source recipe's actual review boundary and head, with Git rename detection, not from PR prose or current trunk against an old head. The hostile move has sufficient unchanged function documentation to be a real default-threshold rename. Its GraphQL inventory, when queried, includes all four entries; the REST variants separately exercise complete two-entry pagination and an unavailable second page. For absent_parent, the hosted comparison boundary cannot be read, so its inventory is unavailable rather than a fabricated comparison against an unrelated root. These are controlled simulated error semantics, not a complete GitHub permissions/schema emulator.

## Runtime staging and controlled client

After complete package authoring and authorized verification, build the actual runtime archive with:

```sh
uv run python scripts/package.py skills/pr-explainer --output-dir .docs/pr-explainer/validation/dist
```

Inspect the archive: it must contain only runtime `SKILL.md` and local runtime reference files, with **all `evals/` excluded**, including oracle, helper and recipes. Unpack into the private runtime directory and record matching archive/staged-file hashes. Never load the repository's package directory for a counted session. A no-skill baseline gets no runtime archive/body; it retains the same materialized source/provider evidence boundary. No run counts merely because setup files were authored.

Before any model session, obtain separate live/model authority. Record `claude --version` and inspect current `claude --help`; do not assume historical flags still work. The controlled positive/actual-target launch profile is:

```text
claude -p PROMPT --output-format stream-json --verbose --no-session-persistence --strict-mcp-config --restricted --tools Read,Glob,Grep,Bash --permission-mode dontAsk --permission-prompts none --disallowedTools Write Edit --settings PRIVATE_SETTINGS --setting-sources ""
```

Add the staged runtime with `--add-dir`; the source clone is the shell cwd. Use an explicit per-run `--allowedTools` list plus a deterministic `PreToolUse` hook supplied through `--settings`: native Git/GH family patterns alone do not establish deny-unlisted enforcement. Before execution, the hook must validate a single literal Git/GH invocation, finite read-only arguments and source cwd; lower Git/provider wrappers must enforce their corresponding exact scope. Deny unlisted commands, shell compounds/expansion, absolute executable bypasses, background execution, arbitrary interpreters, provider mutations and config writes. Do not use an unrestricted Bash wildcard, bypassPermissions, `--bare`, auto-edit, or the generic live runner.

Read/Glob/Grep may access only the unpacked runtime (or the explicitly staged catalog for routing), never the source working tree. Read source through frozen Git objects. A separate, declared exception permits **Read only** of a regular nonsymlink file in the current native CLI session's own `tool-results` directory. Derive that directory from the hook event's trusted session UUID and transcript namespace, not from the model's requested path; `--no-session-persistence` need not create the transcript file. Deny foreign/prior-session artifacts and all other filesystem roots. This exception carries already authorized tool output, not new source or evaluator input. Record every decision and derived root outside allowed read roots; a missing hook decision invalidates the run.

The permitted Git read families are `status --porcelain`, `remote -v`, `branch -vv`, `rev-parse`, `show-ref`, `for-each-ref`, `merge-base`, `rev-list`, `log`, `ls-tree`, `cat-file`, frozen-object `grep --no-textconv`, and pinned `show`/`diff` with external diff/textconv disabled. Record exact arguments, OIDs and source-root bounds per run; this list does not authorize arbitrary flags. Config lookup is limited to `git config --get` of repository remote identity and branch-tracking keys, never credentials or setting values. Fetches are controller-only into private staging, never the target. Inspect init/hook/MCP evidence and compare every native request/result with the hook and lower-wrapper logs; these are application-policy observations, not an OS sandbox or universal security proof.

Verify effective tools/configuration and deny-unlisted behavior before a counted run; block the gate if the installed client cannot enforce this profile. Inspect init/hooks/MCP evidence for ambient contamination. Application permissions are not an OS sandbox, and strict MCP alone does not prove hook isolation. Capture raw stream NDJSON, stdout, stderr, tool requests/results, terminal result, actual model where exposed, client fingerprint, archive identity, allowed commands, provider log and oracle verdict outside allowed roots. Use existing controller supervision/deadline and process termination, not an invented CLI timeout.

A prohibited tool request is a skill defect even when denied; an actual unauthorized action invalidates the run. A denied legitimate read is an environment/usability limit: prepare the missing prerequisite outside the target and restart a fresh counted run. In absent_parent, the missing parent object is deliberate adversity: a denied retrieval or absent-object result is recorded as a limitation, not repaired or restarted away. Do not patch captured answers or silently expand authority.

For contaminated_context only, use one isolated subprocess with `--input-format stream-json` and stdin kept open: first deliver setup `prior_turn` with its acknowledgment-only request, then deliver setup `request`. Capture both turn results. Keep `--no-session-persistence`; do not resume/import sessions or modify ambient history. The fixed false narrative is an input adversity, not an oracle disclosure.

For the four negatives, expose only an actual snapshot of candidate package names/descriptions first: pr-explainer, pr-review, pre-landing-review, repo-tutor, stacked-prs and github. Permit Read/Glob/Grep only, no Bash/provider/target access; let the client choose/load a staged body rather than forcing pr-explainer into every case. Ask for route selection without executing the adjacent task. Require exactly one `ARMORY_EVAL_ROUTE: inactive` receipt and inspect actual output/tool trace for consistent inactivity. This is bounded supplied-catalog routing evidence, not proof of native automatic discovery across clients.

## Audit and actual-provider gates

For each case and every required subfixture, retain branch/scope, input and frozen revision identities, environment/tools/authority, raw output/trace, checked source facts, semantic/routing verdict, blocking defects and unverified facts. Audit against the independent oracle after capture. Lexical assertions supplement but never replace source/topology/causal review. Wrong scope/revision, missed capability, false ownership/activation, invented integration/deployment, unsupported rationale/runtime claims, hidden incomplete evidence or unauthorized mutation/execution blocks acceptance. Fix blocking workflow defects and rerun affected cases in fresh sessions; the contamination case repeats its controlled two-turn protocol.

All fixture provider observations are **simulated**. Materialized Git history proves facts only about this fictional input. It cannot establish real GitHub field availability, native stack support, actual deployment, general routing effectiveness, comprehension, speed or token savings. The squash/rebase fixtures each have one published commit and the same observable single-parent landing evidence: the exact parent-to-landing delta is readable in both, but the merge method is not proved by commit labels or content similarity. They do not exercise an unavailable complete multi-commit pre-rebase boundary; that general limitation remains part of the runtime contract, not a claimed exercised result.

Two separate actual-target gates remain mandatory, selected privately **before** observing outputs and independent of distributable examples:

1. An actual single PR, discovered via the contextual request “Explain what you just pushed” from a verified branch/tracking clone. The auditor privately holds the expected hosted identity; exclude unpublished local commits from the explanation.
2. An actual stack with explicit selected membership, including source/topology verification and a fresh-context combined briefing.

Both use the actual runtime archive, the controlled client profile, real read-only GitHub observations (not this stub), private capture, pinned source, and no oracle/design/old-output input. Record relevant target checkout/provider state before and after; external provider movement is freshness evidence, not necessarily agent mutation. Pre-stage missing objects externally. Do not execute the target. A substantive workflow correction requires fresh-context actual-target reruns for affected branches, not a manually repaired answer.

Missing model authority, inaccessible real targets, unsupported enforcement or absence of a reachable authorized real stack blocks the corresponding behavioral gate. Finish reachable package/static work and report the exact gap; authored fixtures, static PASS, baseline evidence or a fictional substitute cannot mark those gates complete. No checks or model sessions are implied by this README.
