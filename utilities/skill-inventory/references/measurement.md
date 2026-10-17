# Skill inventory measurement — OMP, Claude Code and Codex

`measure` reports installed metadata, persisted disclosure observations and observed skill events. It never edits source logs or installed skills. It creates a private snapshot binding and, only when requested, a private installed-skill report. It does not recommend actions, score effectiveness or authorize inventory changes. Read frequency is not utility; a skill can influence behavior through its description without a body read.

## Running

Bootstrap the pinned dependency without opening logs:

```bash
uv run --no-project --script "$UTILITY_ROOT/scripts/skill_inventory.py" --help
```

Measurement is offline and fails when its dependency is unavailable:

```bash
uv run --offline --no-project --script "$UTILITY_ROOT/scripts/skill_inventory.py" \
  measure --harness omp --as-of "$AS_OF_UTC" --window-days 90 \
  --snapshot "$PRIVATE_SNAPSHOT" --aggregate-only
```

`UTILITY_ROOT` is the unpacked or installed package directory containing `scripts/`. `AS_OF_UTC` is an explicit UTC timestamp ending in `Z` or `+00:00`. The snapshot path is an operator-selected private path outside repositories and the package; first valid capture persists an immutable binding for later replay. Use a new binding path for a new cutoff, changed inventory or different root policy; existing bindings are never refreshed silently.

- `--window-days` selects `events.within_window` and the corresponding current-name statistics. Full-history observations through the cutoff remain separate so historical monthly medians can be reproduced.
- `--aggregate-only` is accepted; stdout is always aggregate-only, including errors.
- Repeatable `--log-root` and `--skill-root` replace the respective discovery defaults with explicit approved inputs. Paths found inside logs never authorize filesystem traversal.
- Repeatable `--reference` supplies explicitly approved instruction/agent dependency sources. These references are not successful loads. Missing reference inputs are an explicit coverage gap, not an empty complete protection set.
- `--private-report` writes an owner-only file outside repositories. Enumerated identities come only from installed files, never uninstalled names found in logs. Historical name matches remain unverified body provenance.

OMP defaults are logs under `~/.omp/agent/sessions`, managed-location skills under `~/.omp/agent/managed-skills`, and protected user skills under `~/.omp/agent/skills`. Resolve a configured root link once; approved alias targets remain protected, and inner links cannot widen the approved set. Root location is not evidence that a file was generated rather than user-authored. Missing or unsafe inputs have explicit coverage or error states, never silent complete zeros.

The optional OMP init runtime version accepts exactly `18.11.0` and `18.11.1` as non-material compatibility metadata; the OMP session schema set stays `{3}`. There are no ranges, so any other value (for example a later patch) fails closed. The actual parsed runtime identity is preserved per record rather than normalized to a single value. This allowlist does not authorize M7 recommendations or any action.

An assistant message whose `stopReason` is `aborted`, `error` or `length` ended mid-generation, so its streamed tool-call arguments can be partial: producers start each call with empty `arguments` and fill them while streaming ([stream block initialisation](https://github.com/can1357/oh-my-pi/blob/d0f2feaa5227db228467e54d64b0936fd3a0e139/packages/ai/src/dialect/owned-stream.ts#L420)), and the harness never runs such calls, pairing them with error or placeholder results instead ([interrupted turns](https://github.com/can1357/oh-my-pi/blob/d0f2feaa5227db228467e54d64b0936fd3a0e139/packages/ai/src/providers/transform-messages.ts#L753), [truncated `length` turns](https://github.com/can1357/oh-my-pi/blob/d0f2feaa5227db228467e54d64b0936fd3a0e139/packages/agent/src/agent-loop.ts#L999-L1001)). In those messages a `read` call with no `path` or an empty one counts under `interrupted_read_calls` and is never a skill read. Every other missing, empty or wrongly typed read path, including in completed messages, still produces `invalid_read_path`; a streamed path that did arrive is measured normally.

Historical schema-v3 `mcp_tool_selection` records require a valid timestamp and a `selectedToolNames` array of strings. The [producer schema](https://github.com/can1357/oh-my-pi/blob/d0f2feaa5227db228467e54d64b0936fd3a0e139/packages/coding-agent/src/session/session-entries.ts#L158-L163) and [context reconstruction](https://github.com/can1357/oh-my-pi/blob/d0f2feaa5227db228467e54d64b0936fd3a0e139/packages/coding-agent/src/session/session-context.ts#L268-L270) define persisted MCP discovery visibility, not skill disclosure, reads or invocation. Valid records contribute only to `ignored_records`; their selected names do not become skill observations. Missing or malformed selection payloads produce `invalid_mcp_tool_selection`; missing or invalid timestamps retain `invalid_timestamp`. Other unknown record types, the runtime allowlist, approved-root boundaries and snapshot checks remain unchanged.

Logical `session_init` identity is deduplicated across files: identical copies count once, and copies that share an identity but disagree are a conflict that makes the report incomplete rather than choosing one. Blocking coverage conditions from the catalog (unreadable, unsafe or unresolved inputs) propagate into the report's coverage and status instead of being reported as complete zeros.

Physical file placement is not a logical payload field. Copies retain separate file counts, but identical disclosure and call identities count once. A logical identity present in different physical cohorts is classified `unknown` rather than assigned to whichever copy was encountered last; conflicting counted payloads still fail.

The report exposes different cohort populations; do not compare them as interchangeable totals:

| Field | Population and interpretation |
|---|---|
| `snapshot.cohorts` | Capture-time physical file-placement hints. Non-OMP layouts can be entirely `unknown`; these hints do not assert logical session roles. |
| `scope.files_by_cohort` | Decoder-resolved roles for parsed captured files, using supported payload identity and provenance. This can resolve main/sub roles even when placement hints are unknown. |
| `exposure.by_cohort` | Deduplicated persisted disclosure observations, not physical files or requests. Copies with conflicting cohort evidence become unknown. |


Directory traversal is descriptor-based: each canonical absolute root is opened component by component from `/` with directory descriptors and no-follow semantics, with no path re-resolution afterwards, and files are opened relative to their pinned parent with a final no-follow open. Callers authorize canonical roots first. A traversal that cannot be completed is refused as incomplete, never treated as an empty or partial inventory.

## Native inventory and disclosure views

`--harness` accepts `omp`, `claude` and `codex`. Claude Code reads logs under `~/.claude/projects`; Codex reads `~/.codex/sessions`. Additional project or archived roots require explicit `--log-root` / `--skill-root`. A path mentioned by a log is never a discovery root.

The installed catalog is an **approved local skill-file view**, not proof that a harness enabled, disclosed or loaded every file. Claude Code discovers protected personal skills under `~/.claude/skills` and plugin resources through the exact version-2 registry `~/.claude/plugins/installed_plugins.json`. Plugin `.claude-plugin/plugin.json` metadata is optional; default `./skills` and custom `skills` directories are supplementary, not replacements. A resource may be a skill directory or a recursive collection. Registry-qualified plugin namespaces remain distinct. See the [Claude Code plugin reference](https://code.claude.com/docs/en/plugins-reference). A missing explicitly declared resource or an unknown registry version blocks complete measurement.

Codex discovers protected files under `~/.codex/skills`, its `.system` component, shared `~/.agents/skills`, and manifest-declared skill resources in the versioned `~/.codex/plugins/cache` layout. Cached versions are **not the active plugin selection**: disabled or stale caches can remain visible in this local file catalog. Do not interpret these counts as native enabled inventory or deduplicate different versions by picking one. `.codex-plugin/plugin.json` declares skill directories; a present remote-install marker requires its exact schema version `1`. Hidden staging outside that cache layout is not scanned. Claude Code, plugin, shared, system and explicit unknown-ownership roots remain protected; no mutation operation exists in M6.

Codex plugin skills use the manifest name as their `plugin:skill` namespace. An absent or empty declared resource list uses optional `./skills` as a fallback, not a supplement; malformed values or paths fail closed instead of widening to the plugin directory. This matches the supported [plugin-root and namespace source](https://github.com/openai/codex/blob/97ebf2d94d62e2ff2045f3ea17b6e11eae9a21fb/codex-rs/core-plugins/src/loader.rs). Only `.codex-plugin/plugin.json` cache layouts are supported here; alternate manifest layouts fail as incomplete. Native command-derived skills and unapproved project roots are outside this file view.

Native skill collections are traversed with bounded recursive, descriptor-based discovery. Manifest paths cannot escape their approved install base; inner aliases cannot authorize new roots. Unknown metadata schemas, missing required resources, unreadable metadata and namespace conflicts are anonymous blocking diagnostics, not fallback roots or successful zeros.

### Blocking diagnostics and safe next actions

| Code | Meaning | Safe operator action |
|---|---|---|
| `catalog_alias_escape` | An installed-file alias or declared resource resolves outside its approved containment boundary. | Inspect symlinks and manifest-declared resources privately within the already-approved installed-skill roots listed above. Reconcile the configuration and user-authorship boundary with the owner; never expand roots or suppress the diagnostic merely to obtain completion. |
| `unknown_record_type`, `invalid_mcp_tool_selection` | A record is outside the explicit supported set, or historical MCP selection metadata violates its typed contract. | Preserve the original corpus. Establish authoritative producer semantics and synthetic boundary checks before requesting a vetted adapter correction; do not guess compatibility, discard records or suppress errors to improve coverage. |
| `invalid_epoch_milliseconds`, `invalid_read_path`, `missing_session_header` | Typed event or session identity requirements were not met. | Retain the incomplete result; independently establish supported coverage before a fresh approved capture. Do not patch logs or invent missing values. |
| `snapshot_initial_unstable` | The capture changed before a trustworthy prefix baseline existed. | Stop relevant writers outside the utility and create a fresh private capture after inputs are stable. Do not call this proven rewriting or reuse an absent binding. |

Catalog diagnostics intentionally expose counts, not alias identities. The utility does not supply a path-level alias report; inspect approved installed files privately rather than deriving new paths from logs. A count alone cannot identify a particular alias. If no safe resolution is available, keep the report incomplete and every action blocked.


Claude Code `attachment.type=skill_listing` observations retain initial and dynamic sources separately. Model-dependent renderer budgets can downgrade descriptions to names, and truncation markers, names/content mismatch or count disagreement make exposure a lower bound. There is no universal character cap. Noninitial listings are partial observations, not additive initial exposure; use `exposure.monthly_by_source` and `latest_by_source` rather than interpreting pooled medians as request cost. `Skill` calls are native invocations; `Read` calls count only paths matched against approved installed files. Validate optional argument/range types; results resolve only declared call identities. Streamed copies and declared fork origins are deduplicated, while conflicting copies fail.

Codex disclosure sources are developer `response_item` messages, separate developer/user instruction fields in `turn_context`, `session_meta.payload.base_instructions.text`, and developer `input_text` messages in `compacted.replacement_history`. These are physical persisted instruction observations, including repeated/forked/compacted context, not new requests or proven transport. Only recognized skill blocks are reduced; surrounding text is discarded. Native read and invocation channels are unavailable (`null`), including in the private report: function-call arguments or a `SKILL.md` mention do not prove either.

A Codex compaction requires a string `message`, which is discarded without inspection. Absent or null `replacement_history` is valid summary-only output with no disclosure observation; a present value must be a list with recognized developer content. This is counted separately from measured empty skill blocks. Unknown or malformed relevant fields remain blocking.

Each adapter admits an exact client/schema allowlist, never a version range. The aggregate `validated_input_schema_identities` identifies accepted software metadata; unknown identities fail closed. Installed visibility, persisted disclosure coverage, observed reads and native invocations are separate denominators.

## Output and counting

The canonical sorted JSON uses `schema_version: 1`, `status`, `scope`, `snapshot`, `inventory`, `exposure`, `events`, `managed_current_name_matches`, `usage`, `coverage` and `diagnostics`.

`scope.supported_schema_files` counts files with supported version identities, not error-free files; record-level failures remain in `diagnostics` and make status incomplete. `validated_input_schema_identities` lists only validated software/schema identities, with no per-version usage counts. `physical_prefix_record_counts` includes the parser's recognized ignored, skipped and duplicate records across physical frozen prefixes; these counters are not deduplicated events or cutoff/window charges.

- `exposure.observations` counts persisted disclosure records, not invented records for files without `session_init`. `files_without_persisted_disclosure` reports that separate coverage gap. OMP main-session system prompts are not persisted and remain unavailable.
- `available`, `unavailable`, `monthly`, `latest` and `latest_available` distinguish an actual missing block from a measured empty block. Monthly medians retain unavailable counts and lower-bound status rather than treating them as zero characters.
- Characters are decoded Unicode code points, not JSON bytes or measured transport tokens. Persisted block, entry and wrapper spans are separate. Ordered prompt-string lists retain virtual joining separators separately; those inserted characters are not charged as persisted characters. `token_estimate_chars_div_4` is a fixed labeled estimate, not a tokenizer.
- `events.all_observed` and `events.within_window` distinguish URI/direct read attempts, successful/failed/unresolved results, full-body/partial-body/resource read calls, and slash invocations. Only assistant tool calls are counted; textual `skill://` mentions are not. A successful body-read counter means a matched full-body read call with a successful tool result, not proven downstream use or quality.
- Native OMP skill invocation is an unavailable channel, so its count is `null`, not a measured zero. User `skill-prompt` custom events are a separate slash channel; agent/autoload references remain dependency evidence.
- Physical files, session identities and deduplicated events are different denominators. Repeated declared call IDs are deduplicated; conflicting copies make the report incomplete. Result resolution respects the cutoff and cannot use a later tool result to resolve an earlier read.
- Managed current-name counts are explicitly unverified historical identity matches. `uri_only` retains the historical URI-attempt definition separately from direct reads. No never-read count is a prune recommendation.
- The optional private report separates first observed inventory, first/last read and invocation dates. Filesystem birth time is installation evidence only; authored creation remains unavailable and is never inferred from mtime.

`usage` contains allowlisted persisted token counters and the availability of local cost-estimate fields, not billing receipts. Aggregate stdout does not disclose recorded cost values. Cache-read availability requires an actual cache-read counter; cache writes or a cache-price estimate do not establish it. Whole-request counters and context snapshots never attribute tokens, cache hits or dollars to individual skills. No token-share, savings or effectiveness claim follows from these measurements.

Claude Code usage is deduplicated by declared message identity rather than streamed chunks. Codex token-count `last` and `cumulative` observations remain separate; identical values at separate physical positions are retained, and fork-lineage telemetry has a separate source. `counter_sums_by_source_and_kind` and `cumulative_session_maxima_by_source_not_billing` preserve that distinction. Cumulative values are summarized by per-session maxima, never added to last counters. Compaction and forks can repeat context-sized values: these are persisted telemetry observations, not newly billed requests. Codex cache-read exposure is labeled `persisted_token_count_telemetry_only`, not a skill-specific cache allocation.

## Exit status and incomplete inputs

Exit `0` means complete measurement of the declared input prefix and supported channels. Exit `2` means incomplete or invalid input. Unknown schema versions, malformed complete JSON, wrong relevant field types, conflicting identities and missing required discriminators fail with fixed anonymous diagnostic codes and counts. Valid partial aggregates remain labeled incomplete. CLI errors do not echo argument values.

Known malformed legacy records are not repaired or discarded to make smoke green. Their strict result remains incomplete until the owner chooses an explicit valid closed cohort or separately approves a narrow versioned legacy policy. Missing disclosure and unsupported channels are unavailable, never successful zero measurements. An incomplete measurement cannot authorize later recommendations or actions.

## Frozen inputs and replay

Capture freezes sorted file identities and byte lengths. Only complete JSONL lines inside those bounds are parsed; the final incomplete tail is excluded with explicit counts. Captured prefixes are checked again after reading. Truncation, rewrite, replacement, unreadable input or inventory listing/content drift invalidates the snapshot. New/appended bytes are counted anonymously but never read through an older binding.

The stdout `snapshot` object describes the attempted capture even when `snapshot.valid` is false. An invalid **initial** capture does not persist a reusable binding, so the requested `--snapshot` file can remain absent despite populated snapshot metadata and partial aggregate output. Do not fabricate that file or treat its requested pathname as proof of a saved snapshot. Preserve the incomplete aggregate result, obtain stable approved inputs and use a fresh explicit path for the next capture. A pre-existing replay binding is retained, never refreshed into a new capture.

The keyed inventory binding includes normalized installation-date evidence, including explicit unavailability, as well as listing, alias and content evidence. A changed installation date invalidates replay even when the file bytes are unchanged.

Prefix integrity is verified at three points: a keyed digest baseline taken eagerly when the snapshot is created, the digest of the bytes actually read, and a final digest after parsing. Discovery size and modification stamps must remain unchanged while establishing the initial baseline; even growth cannot prove an untouched prefix before a baseline exists. Initial instability fails with `snapshot_initial_unstable`, not a claim of proven rewriting. Once a baseline exists, verified append-only growth remains supported. Any baseline/read/final disagreement or incomplete traversal invalidates the snapshot. The input policy is `frozen-complete-jsonl-prefix-v3` and binding schema version is `3`; both appear in public snapshot metadata as `policy` and `binding_schema_version`. Version 1 and 2 bindings are rejected loudly without migration; use a new binding path.

Private binding and report writes are relative to a pinned, validated parent descriptor, and every ancestor directory must be outside any Git repository or package, owned by the effective user or root, and not group- or world-writable unless sticky.

Unchanged inputs, snapshot policy, clock and sorting produce byte-identical JSON. A changed live tree can change the growth diagnostics even when its captured measurement prefix is unchanged; do not label that situation unchanged input. Active appends, new files and partial tails set `snapshot.closed` false and cannot authorize later recommendations requiring closed stable inputs.

The binding contains opaque local identities, lengths, a private random key and locally keyed integrity digests, not paths, raw log hashes or content. Binding/report files are owner-only and outside repositories. An existing private report is accepted only if its bytes are identical; changed content needs a new explicit path.

## Scope limits

This is one practitioner's observational data. The harness's matching-skill MUST-read policy confounds read rate. Never-read does not mean useless, and description-only influence is unmeasured. No network, model, collector, daemon, implicit configuration edits or execution of log-derived instructions is part of measurement.
