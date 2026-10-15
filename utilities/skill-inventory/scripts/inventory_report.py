"""Deterministic aggregate serialization; log identities never leave this module."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime, timedelta
from statistics import median

from inventory_catalog import BLOCKING_COVERAGE
from inventory_types import (
    Exposure,
    Harness,
    Inventory,
    Invocation,
    ParsedFile,
    ReadAttempt,
    ReadResult,
    UsageObservation,
)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat().removesuffix("+00:00") + "Z"


def _median(values: list[int]) -> int | float | None:
    return median(values) if values else None


def _deduplicate_exposures(
    observations: list[Exposure], issues: Counter[str]
) -> list[Exposure]:
    keyed: dict[tuple[str, str, str], Exposure] = {}
    unkeyed: list[Exposure] = []
    for observation in observations:
        if observation.record_id is None:
            unkeyed.append(observation)
            continue
        if observation.fingerprint is None:
            issues["unverifiable_disclosure_identity"] += 1
            unkeyed.append(observation)
            continue
        identity = (
            observation.session_id,
            observation.source,
            observation.record_id,
        )
        previous = keyed.get(identity)
        if previous is None:
            keyed[identity] = observation
        elif previous != replace(observation, cohort=previous.cohort):
            issues["conflicting_duplicate_disclosure"] += 1
        elif previous.cohort != observation.cohort:
            keyed[identity] = replace(previous, cohort="unknown")
    return [*unkeyed, *keyed.values()]


def _deduplicate[T: (ReadAttempt, Invocation)](
    events: Iterable[T], issues: Counter[str]
) -> list[T]:
    unique: dict[tuple[str, str], T] = {}
    for event in events:
        key = (event.session_id, event.call_id)
        previous = unique.get(key)
        if previous is None:
            unique[key] = event
        elif previous != replace(event, cohort=previous.cohort):
            issues["conflicting_duplicate_event"] += 1
        elif previous.cohort != event.cohort:
            unique[key] = replace(previous, cohort="unknown")
    return list(unique.values())


def _event_counts(
    attempts: list[ReadAttempt],
    invocations: list[Invocation],
    results: dict[tuple[str, str], ReadResult],
    attempt_files: list[tuple[str, str, datetime]],
    lower: datetime | None,
    upper: datetime,
) -> dict[str, object]:
    selected = [
        event
        for event in attempts
        if event.timestamp <= upper and (lower is None or event.timestamp >= lower)
    ]
    invoked = [
        event
        for event in invocations
        if event.timestamp <= upper and (lower is None or event.timestamp >= lower)
    ]
    successes = [
        event
        for event in selected
        if (result := results.get((event.session_id, event.call_id))) is not None
        and result.success
    ]
    failed = sum(
        (result := results.get((event.session_id, event.call_id))) is not None
        and not result.success
        for event in selected
    )
    files: dict[str, set[str]] = defaultdict(set)
    for file_key, cohort, timestamp in attempt_files:
        if timestamp <= upper and (lower is None or timestamp >= lower):
            files[cohort].add(file_key)
    return {
        "read_attempts": len(selected),
        "uri_read_attempts": sum(event.channel == "uri" for event in selected),
        "direct_read_attempts": sum(event.channel == "direct" for event in selected),
        "distinct_skill_names": len(
            {event.skill_name for event in selected if event.skill_name is not None}
        ),
        "distinct_uri_names": len(
            {
                event.skill_name
                for event in selected
                if event.channel == "uri" and event.skill_name is not None
            }
        ),
        "successful_reads": len(successes),
        "failed_reads": failed,
        "unresolved_results": len(selected) - len(successes) - failed,
        "successful_body_loads": sum(
            event.body and not event.partial for event in successes
        ),
        "successful_partial_body_reads": sum(
            event.body and event.partial for event in successes
        ),
        "successful_resource_reads": sum(not event.body for event in successes),
        "native_invocations": sum(event.channel == "native" for event in invoked),
        "slash_invocations": sum(event.channel == "slash" for event in invoked),
        "files_with_reads": len(set().union(*files.values())) if files else 0,
        "files_with_reads_by_cohort": {
            cohort: len(files[cohort])
            for cohort in ("main", "sub", "nested", "unknown")
        },
    }


def _exposure_row(item: Exposure) -> dict[str, object]:
    return {
        "timestamp": _iso(item.timestamp),
        "cohort": item.cohort,
        "source": item.source,
        "status": item.status,
        "block_chars": item.block_chars,
        "wrapper_chars": item.wrapper_chars,
        "entry_chars": item.entry_chars,
        "entries": len(item.entries),
        "declared_count": item.declared_count,
        "listed_names": item.listed_names,
        "virtual_block_chars": item.virtual_block_chars,
        "inserted_separator_chars": item.separator_chars,
        "block_separator_chars": item.block_separator_chars,
        "prompt_chars": item.prompt_chars,
        "block_share_of_persisted_prompt": (
            item.block_chars / item.prompt_chars
            if item.block_chars is not None and item.prompt_chars
            else None
        ),
        "token_estimate_chars_div_4": (
            item.block_chars / 4 if item.block_chars is not None else None
        ),
        "mean_entry_chars": (
            item.entry_chars / len(item.entries)
            if item.entry_chars is not None and item.entries
            else None
        ),
    }


def _monthly_exposure(items: list[Exposure]) -> dict[str, object]:
    months: dict[str, list[Exposure]] = defaultdict(list)
    for item in items:
        months[item.timestamp.strftime("%Y-%m")].append(item)
    monthly: dict[str, object] = {}
    for month, observations in sorted(months.items()):
        chars = [
            item.block_chars for item in observations if item.block_chars is not None
        ]
        monthly[month] = {
            "observations": len(observations),
            "available": len(chars),
            "lower_bound_observations": sum(
                item.status == "lower_bound" for item in observations
            ),
            "median_observed_block_chars": _median(chars),
        }
    return monthly


def _exposure_summary(items: list[Exposure]) -> dict[str, object]:
    sources: dict[str, list[Exposure]] = defaultdict(list)
    for item in items:
        sources[item.source].append(item)
    ordered = sorted(
        items,
        key=lambda item: (
            item.timestamp,
            item.source,
            item.session_id,
            item.block_chars if item.block_chars is not None else -1,
        ),
    )
    latest_by_source = {item.source: item for item in ordered}
    available = [item for item in ordered if item.block_chars is not None]
    return {
        "observations": len(items),
        "available": len(available),
        "unavailable": len(items) - len(available),
        "by_cohort": dict(sorted(Counter(item.cohort for item in items).items())),
        "monthly": _monthly_exposure(items),
        "by_source": {source: len(rows) for source, rows in sorted(sources.items())},
        "monthly_by_source": {
            source: _monthly_exposure(rows) for source, rows in sorted(sources.items())
        },
        "latest_by_source": {
            source: _exposure_row(item)
            for source, item in sorted(latest_by_source.items())
        },
        "latest": _exposure_row(ordered[-1]) if ordered else None,
        "latest_available": _exposure_row(available[-1]) if available else None,
        "scope": "persisted_disclosure_observations_not_measured_transport_or_billing",
    }


def _usage_summary(
    observations: list[UsageObservation], harness: Harness, issues: Counter[str]
) -> dict[str, object]:
    unique: dict[tuple[str, str, tuple[str, ...]], UsageObservation] = {}
    for item in observations:
        key = (item.source, item.counter_kind, item.identity)
        previous = unique.get(key)
        if previous is None:
            unique[key] = item
            continue
        if previous.values == item.values:
            continue
        if harness != "claude" or item.counter_kind != "per_message":
            issues["conflicting_duplicate_usage"] += 1
            continue
        values = previous.values | item.values
        for counter in values:
            values[counter] = max(
                previous.values.get(counter, 0), item.values.get(counter, 0)
            )
        unique[key] = UsageObservation(
            item.identity,
            max(previous.timestamp, item.timestamp),
            item.source,
            item.counter_kind,
            values,
        )
    totals: dict[str, dict[str, int | float]] = {}
    by_source: dict[str, dict[str, dict[str, int | float]]] = {}
    cumulative: dict[tuple[str, str], dict[str, int | float]] = {}
    contexts: dict[str, list[int]] = defaultdict(list)
    cache_present = False
    cost_fields: set[str] = set()
    for item in unique.values():
        cache_present = cache_present or any(
            key in item.values
            for key in ("cacheRead", "cache_read_input_tokens", "cached_input_tokens")
        )
        if item.counter_kind == "context":
            for name, number in item.values.items():
                if isinstance(number, int):
                    contexts[name].append(number)
            continue
        if item.counter_kind == "cumulative":
            # Maxima are retained separately; never add them to last-event usage.
            session = item.identity[0] if item.identity else ""
            target = cumulative.setdefault((item.source, session), {})
            for name, number in item.values.items():
                if name.startswith("cost_"):
                    cost_fields.add(name)
                    continue
                target[name] = max(target.get(name, 0), number)
            continue
        for name, number in item.values.items():
            if name.startswith("cost_"):
                cost_fields.add(name)
                continue
            target = totals.setdefault(item.counter_kind, {})
            target[name] = target.get(name, 0) + number
            source_target = by_source.setdefault(item.source, {}).setdefault(
                item.counter_kind, {}
            )
            source_target[name] = source_target.get(name, 0) + number
    cumulative_totals: dict[str, int | float] = {}
    cumulative_by_source: dict[str, dict[str, int | float]] = {}
    for (source, _session), counters in cumulative.items():
        for name, number in counters.items():
            cumulative_totals[name] = cumulative_totals.get(name, 0) + number
            source_target = cumulative_by_source.setdefault(source, {})
            source_target[name] = source_target.get(name, 0) + number
    return {
        "status": (
            "persisted_counters"
            if totals or cumulative_totals or contexts
            else "cost_estimate_metadata_only"
            if cost_fields
            else "unavailable"
        ),
        "deduplicated_observations": len(unique),
        "counter_sums_separated_by_kind": totals,
        "counter_sums_by_source_and_kind": by_source,
        "cumulative_session_maxima_separate_not_billing": cumulative_totals,
        "cumulative_session_maxima_by_source_not_billing": cumulative_by_source,
        "context_snapshot_medians_not_skill_attribution": {
            name: _median(numbers) for name, numbers in sorted(contexts.items())
        },
        "cache_read_exposure": (
            "persisted_token_count_telemetry_only"
            if harness == "codex" and cache_present
            else "whole_request_fields_only"
            if cache_present
            else "unavailable"
        ),
        "skill_specific_cache_attribution": "unavailable",
        "skill_specific_dollars": "modeled_only_not_calculated",
        "persisted_cost_fields": "local_estimates_not_provider_billing_receipts",
        "persisted_cost_estimate_fields": sorted(cost_fields),
        "cost_values": "not_disclosed_by_aggregate_report",
        "claude_stream_policy": "maximum_observed_cumulative_counter_per_message",
        "codex_telemetry_scope": (
            "physical_observations_not_new_requests_forks_and_compaction_may_repeat"
            if harness == "codex"
            else "not_applicable"
        ),
    }


def _distribution(counts: Counter[str], population: int) -> dict[str, object]:
    total = counts.total()
    return {
        "read_attempts": total,
        "names_with_reads": len(counts),
        "names_without_observed_reads": population - len(counts),
        "names_with_at_least_5_reads": sum(n >= 5 for n in counts.values()),
        "names_with_at_least_20_reads": sum(n >= 20 for n in counts.values()),
        "top10_share_of_read_attempts": (
            sum(n for _, n in counts.most_common(10)) / total if total else None
        ),
    }


def _managed_counts(
    attempts: list[ReadAttempt], inventory: Inventory
) -> dict[str, object]:
    names: dict[str, list[str]] = defaultdict(list)
    for skill in inventory.entries:
        names[skill.name].append(skill.ownership)
    managed = {name for name, owners in names.items() if owners == ["managed"]}
    counts = Counter(
        item.skill_name
        for item in attempts
        if item.skill_name is not None and item.skill_name in managed
    )
    uri_counts = Counter(
        item.skill_name
        for item in attempts
        if item.channel == "uri"
        and item.skill_name is not None
        and item.skill_name in managed
    )
    return {
        "provenance": "current_installed_name_match_only_not_historical_body_identity",
        "installed_managed_names": len(managed),
        **_distribution(counts, len(managed)),
        "uri_only": _distribution(uri_counts, len(managed)),
        "ambiguous_installed_names": sum(len(owners) > 1 for owners in names.values()),
    }


def _private_rows(
    inventory: Inventory,
    attempts: list[ReadAttempt],
    invocations: list[Invocation],
    exposures: list[Exposure],
    channels_available: bool,
) -> list[dict[str, object]]:
    reads: dict[str, list[datetime]] = defaultdict(list)
    invokes: dict[str, list[datetime]] = defaultdict(list)
    seen: dict[str, list[tuple[datetime, int]]] = defaultdict(list)
    for item in attempts:
        if item.skill_name is not None:
            reads[item.skill_name].append(item.timestamp)
    for invocation in invocations:
        invokes[invocation.skill_name].append(invocation.timestamp)
    for exposure in exposures:
        for entry in exposure.entries:
            seen[entry.name].append((exposure.timestamp, entry.chars))
    rows: list[dict[str, object]] = []
    ambiguous = Counter(skill.name for skill in inventory.entries)
    for skill in sorted(
        inventory.entries, key=lambda item: (item.name, str(item.path))
    ):
        resolved = ambiguous[skill.name] == 1
        times = sorted(reads.get(skill.name, [])) if resolved else []
        invocation_times = sorted(invokes.get(skill.name, [])) if resolved else []
        presence = sorted(seen.get(skill.name, [])) if resolved else []
        rows.append(
            {
                "name": skill.name,
                "identity_source": "installed_file",
                "ownership": skill.ownership,
                "historical_provenance": (
                    "current_name_match_unverified" if resolved else "ambiguous"
                ),
                "installation_date": _iso(skill.installed_at),
                "installation_date_source": (
                    "filesystem_birthtime" if skill.installed_at else "unavailable"
                ),
                "authored_creation_date": None,
                "authored_creation_date_source": "unavailable",
                "first_observed_inventory_date": _iso(
                    presence[0][0] if presence else None
                ),
                "first_observed_inventory_source": "logged_name_match_unverified",
                "latest_observed_entry_chars": presence[-1][1] if presence else None,
                "latest_observed_entry_token_estimate_chars_div_4": (
                    presence[-1][1] / 4 if presence else None
                ),
                "first_read_date": _iso(times[0] if times else None),
                "last_read_date": _iso(times[-1] if times else None),
                "read_date_source": (
                    "unavailable_observation_channel"
                    if not channels_available
                    else "tool_call_attempt_name_match_unverified"
                ),
                "observed_read_attempts": len(times) if channels_available else None,
                "first_invocation_date": _iso(
                    invocation_times[0] if invocation_times else None
                ),
                "last_invocation_date": _iso(
                    invocation_times[-1] if invocation_times else None
                ),
                "observed_invocation_attempts": (
                    len(invocation_times) if channels_available else None
                ),
            }
        )
    return rows


def build_report(
    *,
    harness: Harness,
    parsed: list[ParsedFile],
    inventory: Inventory,
    as_of: datetime,
    window_days: int,
    snapshot: dict[str, object],
    input_issues: Counter[str],
) -> tuple[dict[str, object], dict[str, object]]:
    issues = input_issues.copy()
    issues.update(
        {
            f"catalog_{code}": inventory.coverage[code]
            for code in BLOCKING_COVERAGE
            if inventory.coverage[code]
        }
    )
    sessions: dict[str, str] = {}
    files_by_cohort: Counter[str] = Counter()
    attempt_files: list[tuple[str, str, datetime]] = []
    valid: list[ParsedFile] = []
    record_counts: Counter[str] = Counter()
    schema_identities: set[str] = set()
    for item in parsed:
        issues.update(item.issues)
        record_counts.update(item.counts)
        schema_identities.update(item.versions)
        if not item.schema_supported:
            if not item.issues:
                issues["unsupported_input_schema"] += 1
            continue
        valid.append(item)
        cohorts = set(item.sessions.values())
        cohort = next(iter(cohorts)) if len(cohorts) == 1 else item.cohort_hint
        files_by_cohort[cohort] += 1
        for session, session_cohort in item.sessions.items():
            if session in sessions and sessions[session] != session_cohort:
                # File placement is not payload identity. Mixed physical cohorts
                # cannot classify one logical session as exclusively main or sub.
                sessions[session] = "unknown"
            else:
                sessions[session] = session_cohort
        attempt_files.extend(
            (item.file_key, event.cohort, event.timestamp) for event in item.attempts
        )
    attempts = _deduplicate(
        (event for item in valid for event in item.attempts), issues
    )
    invocations = _deduplicate(
        (event for item in valid for event in item.invocations), issues
    )
    attempts = [event for event in attempts if event.timestamp <= as_of]
    invocations = [event for event in invocations if event.timestamp <= as_of]
    results: dict[tuple[str, str], ReadResult] = {}
    for item in valid:
        for result in item.results:
            if result.timestamp is None:
                issues["result_timestamp_unavailable"] += 1
                continue
            if result.timestamp > as_of:
                continue
            key = (result.session_id, result.call_id)
            previous = results.get(key)
            if previous is not None and previous != result:
                issues["conflicting_duplicate_result"] += 1
            else:
                results[key] = result
    lower = as_of - timedelta(days=window_days)
    recent_attempts = [event for event in attempts if event.timestamp >= lower]
    exposures = _deduplicate_exposures(
        [
            exposure
            for item in valid
            for exposure in item.exposures
            if exposure.timestamp <= as_of
        ],
        issues,
    )
    usage = _usage_summary(
        [u for item in valid for u in item.usage if u.timestamp <= as_of],
        harness,
        issues,
    )
    ownership = Counter(skill.ownership for skill in inventory.entries)
    coverage_values: dict[str, set[str]] = defaultdict(set)
    references = inventory.reference_names.copy()
    for item in valid:
        references.update(item.reference_names)
        for channel, state in item.coverage.items():
            coverage_values[channel].add(state)
    installed_names = {skill.name for skill in inventory.entries}
    exposure_summary = _exposure_summary(exposures)
    exposure_summary["files_without_persisted_disclosure"] = sum(
        not item.exposures for item in valid
    )
    report: dict[str, object] = {
        "schema_version": 1,
        "adapter_version": f"{harness}-metadata-v1",
        "status": "incomplete" if issues else "complete",
        "scope": {
            "harness": harness,
            "as_of_utc": _iso(as_of),
            "window_days": window_days,
            "window_start_utc": _iso(lower),
            "supported_schema_files": len(valid),
            "validated_input_schema_identities": sorted(schema_identities),
            "physical_prefix_record_counts": dict(sorted(record_counts.items())),
            "files_by_cohort": {
                cohort: files_by_cohort[cohort]
                for cohort in ("main", "sub", "nested", "unknown")
            },
            "session_identities": len(sessions),
            "sessions_by_cohort": dict(sorted(Counter(sessions.values()).items())),
        },
        "snapshot": snapshot,
        "inventory": {
            "installed_entries": len(inventory.entries),
            "scope": "approved_local_skill_files_not_native_enabled_or_disclosed_inventory",
            "by_ownership": dict(sorted(ownership.items())),
            "discovery_coverage": dict(sorted(inventory.coverage.items())),
            "dependency_references_matching_installed_names": len(
                references & installed_names
            ),
            "authored_creation_dates": "unavailable",
        },
        "exposure": exposure_summary,
        "events": {
            "all_observed": _event_counts(
                attempts, invocations, results, attempt_files, None, as_of
            ),
            "within_window": _event_counts(
                attempts, invocations, results, attempt_files, lower, as_of
            ),
        },
        "managed_current_name_matches": {
            "all_observed": _managed_counts(attempts, inventory),
            "within_window": _managed_counts(recent_attempts, inventory),
        },
        "usage": usage,
        "coverage": {
            "channels": {
                channel: sorted(states)
                for channel, states in sorted(coverage_values.items())
            },
            "main_omp_system_prompts": (
                "not_persisted_unavailable" if harness == "omp" else "not_applicable"
            ),
            "native_invocation_counts": (
                "unavailable"
                if harness in {"omp", "codex"} or not valid
                else "observed_tool_call_attempts_not_success"
            ),
            "slash_invocation_counts": (
                "observed_user_custom_events"
                if harness == "omp" and valid
                else "unavailable"
            ),
            "skill_read_counts": (
                "unavailable"
                if harness == "codex" or not valid
                else "observed_supported_channels"
            ),
            "historical_installed_body_lineage": "unverified_current_name_matches_only",
            "partial_results": bool(issues),
            "pruning_authorization": "none_measurement_only",
        },
        "diagnostics": dict(sorted(issues.items())),
        "caveats": [
            "chars_div_4_is_an_estimate_not_a_tokenizer",
            "matching_skill_must_read_policy_confounds_read_rate",
            "unread_does_not_mean_useless_description_influence_is_unmeasured",
            "single_practitioner_not_generalizable",
            "disclosure_observations_do_not_measure_request_transport_or_billing",
            "request_cache_counters_do_not_attribute_skill_cache_cost",
        ],
    }
    if harness != "codex":
        summaries = report["events"]
        if isinstance(summaries, dict):
            for counts in summaries.values():
                if isinstance(counts, dict):
                    if harness == "omp" or not valid:
                        counts["native_invocations"] = None
                    if harness == "claude" or not valid:
                        counts["slash_invocations"] = None
    if not valid:
        report["managed_current_name_matches"] = None
    # Codex has no verified load channel. Zero would falsely claim measured absence.
    if harness == "codex":
        report["events"] = {
            "all_observed": None,
            "within_window": None,
            "reason": "native_skill_read_and_invocation_channels_unavailable",
        }
        report["managed_current_name_matches"] = None
    private_report: dict[str, object] = {
        "schema_version": 1,
        "status": report["status"],
        "scope": report["scope"],
        "skills": _private_rows(
            inventory,
            attempts,
            invocations,
            exposures,
            channels_available=bool(valid) and harness != "codex",
        ),
        "diagnostics": report["diagnostics"],
    }
    return report, private_report
