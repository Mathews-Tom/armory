#!/usr/bin/env python3
"""
Blocking strategy report for kg-builder entity resolution.

Blocking recall is a hard ceiling on fusion recall: any true match that no blocking key
puts in a shared block can never be matched downstream, at any threshold, by any model.
This script measures that ceiling against labeled pairs before you scale.

Reports, per key and for the union of keys:
  - reduction ratio  — fraction of all pairs eliminated (higher is cheaper)
  - pair recall      — fraction of true matches surviving into some block (the ceiling)
  - candidate pairs  — how many comparisons the matcher will actually run

No external dependencies — standard library only.

Input formats (JSON Lines):

  candidates.jsonl   one record per entity
      {"id": "e1", "type": "Organization", "name": "Acme Corp",
       "attrs": {"domain": "acme.com"}}

  matches.jsonl      one record per known true match (order-insensitive)
      {"a": "e1", "b": "e7"}

Usage:
    python blocking_report.py candidates.jsonl --labels matches.jsonl
    python blocking_report.py candidates.jsonl --labels matches.jsonl --format json
    python blocking_report.py candidates.jsonl --labels matches.jsonl --min-recall 0.95
    python blocking_report.py candidates.jsonl --attr-key domain

Exit codes:
    0  report produced (and union recall >= --min-recall when given)
    1  union pair recall below --min-recall
    2  input missing or malformed
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any, Callable, Iterable

# Legal-form suffixes stripped when building the normalized key. Suffix variation is the
# single most common surface difference between duplicate organization records.
LEGAL_SUFFIXES = frozenset({
    "inc", "inc.", "incorporated", "corp", "corp.", "corporation", "llc", "l.l.c.",
    "ltd", "ltd.", "limited", "plc", "gmbh", "ag", "sa", "s.a.", "nv", "bv", "co", "co.",
    "company", "holdings", "group", "the",
})

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")

Pair = tuple[str, str]


@dataclass(frozen=True)
class Entity:
    id: str
    type: str
    name: str
    attrs: dict[str, Any]


def normalize(text: str) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = _PUNCT.sub(" ", stripped.lower())
    return _WS.sub(" ", cleaned).strip()


def normalized_key(entity: Entity) -> set[str]:
    """Type plus the name with punctuation, casing, and legal suffixes removed."""
    tokens = [t for t in normalize(entity.name).split() if t not in LEGAL_SUFFIXES]
    if not tokens:
        return set()
    return {f"{entity.type}|norm|{' '.join(tokens)}"}


def token_keys(entity: Entity) -> set[str]:
    """Type plus each significant token. Catches shared-word variants."""
    tokens = [t for t in normalize(entity.name).split() if t not in LEGAL_SUFFIXES and len(t) > 2]
    return {f"{entity.type}|tok|{t}" for t in tokens}


def acronym_keys(entity: Entity) -> set[str]:
    """Bridge an initialism to its expansion: 'SEU' <-> 'Southeast University'."""
    tokens = [t for t in normalize(entity.name).split() if t not in LEGAL_SUFFIXES]
    keys: set[str] = set()
    if len(tokens) >= 2:
        keys.add(f"{entity.type}|acr|{''.join(t[0] for t in tokens)}")
    if len(tokens) == 1 and 2 <= len(tokens[0]) <= 6:
        keys.add(f"{entity.type}|acr|{tokens[0]}")
    return keys


def prefix_keys(entity: Entity) -> set[str]:
    """First four characters of the normalized name. Cheap catch-all for typos."""
    norm = normalize(entity.name).replace(" ", "")
    return {f"{entity.type}|pre|{norm[:4]}"} if len(norm) >= 4 else set()


def make_attr_key(attr: str) -> Callable[[Entity], set[str]]:
    """Block on an exact shared attribute value, e.g. an email domain or external id."""
    def key(entity: Entity) -> set[str]:
        value = entity.attrs.get(attr)
        return {f"{entity.type}|{attr}|{normalize(str(value))}"} if value else set()
    return key


BUILTIN_KEYS: dict[str, Callable[[Entity], set[str]]] = {
    "normalized": normalized_key,
    "token": token_keys,
    "acronym": acronym_keys,
    "prefix": prefix_keys,
}


def load_entities(path: Path) -> list[Entity]:
    entities: list[Entity] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
        if "id" not in record or "name" not in record:
            raise ValueError(f"{path}:{lineno}: record needs at least 'id' and 'name'")
        entities.append(Entity(
            id=str(record["id"]),
            type=str(record.get("type", "_")),
            name=str(record["name"]),
            attrs=record.get("attrs") or {},
        ))
    if not entities:
        raise ValueError(f"{path}: no records")
    return entities


def load_labels(path: Path, known_ids: set[str]) -> tuple[set[Pair], list[str]]:
    """Load true-match pairs. Returns the pair set plus warnings for unknown ids."""
    pairs: set[Pair] = set()
    warnings: list[str] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
        if "a" not in record or "b" not in record:
            raise ValueError(f"{path}:{lineno}: match record needs 'a' and 'b'")
        a, b = str(record["a"]), str(record["b"])
        if a == b:
            continue
        for missing in (i for i in (a, b) if i not in known_ids):
            warnings.append(f"{path}:{lineno}: match references unknown entity id '{missing}'")
        pairs.add((a, b) if a < b else (b, a))
    return pairs, warnings


def candidate_pairs(entities: Iterable[Entity], key_fn: Callable[[Entity], set[str]]) -> set[Pair]:
    """Pairs sharing at least one blocking key."""
    blocks: dict[str, list[str]] = defaultdict(list)
    for entity in entities:
        for key in key_fn(entity):
            blocks[key].append(entity.id)

    pairs: set[Pair] = set()
    for members in blocks.values():
        if len(members) < 2:
            continue
        for a, b in combinations(sorted(set(members)), 2):
            pairs.add((a, b))
    return pairs


def score(pairs: set[Pair], truth: set[Pair], total_pairs: int) -> dict[str, float | int]:
    found = len(pairs & truth)
    return {
        "candidate_pairs": len(pairs),
        "reduction_ratio": round(1 - (len(pairs) / total_pairs), 6) if total_pairs else 0.0,
        "matches_retained": found,
        "pair_recall": round(found / len(truth), 6) if truth else 0.0,
    }


def build_report(
    entities: list[Entity],
    truth: set[Pair],
    key_names: list[str],
    attr_keys: list[str],
) -> dict[str, Any]:
    total_pairs = len(entities) * (len(entities) - 1) // 2

    key_fns: dict[str, Callable[[Entity], set[str]]] = {
        name: BUILTIN_KEYS[name] for name in key_names
    }
    for attr in attr_keys:
        key_fns[f"attr:{attr}"] = make_attr_key(attr)

    per_key: dict[str, dict[str, float | int]] = {}
    union: set[Pair] = set()
    for name, fn in key_fns.items():
        pairs = candidate_pairs(entities, fn)
        per_key[name] = score(pairs, truth, total_pairs)
        union |= pairs

    union_score = score(union, truth, total_pairs)
    missed = sorted(truth - union)

    return {
        "entities": len(entities),
        "all_pairs": total_pairs,
        "labeled_matches": len(truth),
        "per_key": per_key,
        "union": union_score,
        "missed_matches": missed[:50],
        "missed_total": len(missed),
    }


def render_text(report: dict[str, Any]) -> str:
    lines = [
        f"entities         {report['entities']}",
        f"all pairs        {report['all_pairs']}",
        f"labeled matches  {report['labeled_matches']}",
        "",
        f"{'key':<16} {'cand pairs':>11} {'reduction':>10} {'recall':>8}",
        f"{'-' * 16} {'-' * 11} {'-' * 10} {'-' * 8}",
    ]
    for name, stats in report["per_key"].items():
        lines.append(
            f"{name:<16} {stats['candidate_pairs']:>11} "
            f"{stats['reduction_ratio']:>10.4f} {stats['pair_recall']:>8.4f}"
        )
    union = report["union"]
    lines += [
        f"{'-' * 16} {'-' * 11} {'-' * 10} {'-' * 8}",
        f"{'UNION':<16} {union['candidate_pairs']:>11} "
        f"{union['reduction_ratio']:>10.4f} {union['pair_recall']:>8.4f}",
        "",
        f"Union pair recall is the ceiling on fusion recall: {union['matches_retained']} of "
        f"{report['labeled_matches']} true matches survive blocking.",
    ]
    if report["missed_total"]:
        lines.append("")
        lines.append(f"unreachable true matches ({report['missed_total']}):")
        lines += [f"  {a} <-> {b}" for a, b in report["missed_matches"]]
        if report["missed_total"] > len(report["missed_matches"]):
            lines.append(f"  ... and {report['missed_total'] - len(report['missed_matches'])} more")
        lines.append("")
        lines.append("Add a blocking key that bridges these, or accept the recall ceiling.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure blocking reduction and pair recall")
    parser.add_argument("candidates", type=Path, help="entities as JSON Lines")
    parser.add_argument("--labels", type=Path, help="known true-match pairs as JSON Lines")
    parser.add_argument(
        "--keys", default="normalized,token,acronym,prefix",
        help="comma-separated builtin keys (default: all)",
    )
    parser.add_argument(
        "--attr-key", action="append", default=[], metavar="ATTR",
        help="also block on an exact shared attrs value; repeatable",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--min-recall", type=float, default=None,
        help="exit 1 when union pair recall falls below this",
    )
    args = parser.parse_args(argv)

    key_names = [k.strip() for k in args.keys.split(",") if k.strip()]
    unknown = [k for k in key_names if k not in BUILTIN_KEYS]
    if unknown:
        print(
            f"ERROR   unknown blocking key(s): {', '.join(unknown)}; "
            f"available: {', '.join(BUILTIN_KEYS)}",
            file=sys.stderr,
        )
        return 2

    try:
        entities = load_entities(args.candidates)
    except (OSError, ValueError) as exc:
        print(f"ERROR   {exc}", file=sys.stderr)
        return 2

    truth: set[Pair] = set()
    if args.labels:
        try:
            truth, warnings = load_labels(args.labels, {e.id for e in entities})
        except (OSError, ValueError) as exc:
            print(f"ERROR   {exc}", file=sys.stderr)
            return 2
        for warning in warnings:
            print(f"WARN    {warning}", file=sys.stderr)
    else:
        print(
            "WARN    no --labels given; reduction ratios are reported but pair recall "
            "cannot be measured, and recall is the number that matters",
            file=sys.stderr,
        )

    report = build_report(entities, truth, key_names, args.attr_key)

    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        print(render_text(report))

    if args.min_recall is not None and report["union"]["pair_recall"] < args.min_recall:
        print(
            f"FAIL    union pair recall {report['union']['pair_recall']:.4f} "
            f"below required {args.min_recall}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
