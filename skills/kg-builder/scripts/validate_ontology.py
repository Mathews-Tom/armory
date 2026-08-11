#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml>=6.0"]
# ///
"""
Ontology validator for kg-builder.

Checks an `ontology.yaml` before any extraction runs. Catches the schema defects that
silently degrade a graph: relations pointing at undeclared entity types, vague relation
names that make domain/range validation meaningless, event schemas with no trigger, and
entity types nobody can give an example of.

Usage:
    uv run validate_ontology.py ontology.yaml
    uv run validate_ontology.py ontology.yaml --format json
    uv run validate_ontology.py ontology.yaml --strict     # warnings also fail

Exit codes:
    0  valid (warnings may be present unless --strict)
    1  invalid — errors found
    2  file missing or unparseable
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Relation names that defeat the purpose of typed edges. A relation must name a specific
# verb; these make every downstream query ambiguous and every domain/range check vacuous.
VAGUE_RELATIONS = frozenset({
    "RELATED_TO", "RELATES_TO", "HAS_LINK", "LINKED_TO", "ASSOCIATED_WITH",
    "CONNECTED_TO", "REFERS_TO", "HAS", "IS", "OF", "ABOUT", "SEE_ALSO",
})

RELATION_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
TYPE_NAME_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")

MIN_ENTITY_TYPES = 2
MAX_ENTITY_TYPES = 40
MAX_RELATION_TYPES = 80


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    @property
    def ok(self) -> bool:
        return not self.errors


def _as_mapping(value: Any, label: str, report: Report) -> dict[str, Any]:
    """Coerce a section to a mapping, recording an error when it is the wrong shape."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        report.error(f"'{label}' must be a mapping of name -> definition, got {type(value).__name__}")
        return {}
    return value


def check_entities(entities: dict[str, Any], report: Report) -> set[str]:
    """Validate entity type declarations; return the set of declared type names."""
    if not entities:
        report.error("no entity types declared — an ontology with no entities cannot constrain extraction")
        return set()

    count = len(entities)
    if count < MIN_ENTITY_TYPES:
        report.warn(f"{count} entity type(s); a graph usually needs at least {MIN_ENTITY_TYPES}")
    if count > MAX_ENTITY_TYPES:
        report.warn(
            f"{count} entity types exceeds {MAX_ENTITY_TYPES} — large schemas overfit the sample "
            "corpus; prune to the types your competency questions actually need"
        )

    for name, body in entities.items():
        if not TYPE_NAME_RE.match(str(name)):
            report.error(f"entity type '{name}' must be PascalCase (e.g. 'Person', 'ServiceTeam')")

        if not isinstance(body, dict):
            report.error(f"entity type '{name}' must be a mapping with 'desc' and 'examples'")
            continue

        if not str(body.get("desc", "")).strip():
            report.error(f"entity type '{name}' has no 'desc' — extraction prompts embed it verbatim")

        examples = body.get("examples") or []
        if not isinstance(examples, list) or len(examples) < 2:
            report.warn(
                f"entity type '{name}' has fewer than 2 examples — a type you cannot exemplify "
                "twice from the real corpus is probably speculative"
            )

    return set(entities)


def check_relations(relations: dict[str, Any], declared: set[str], report: Report) -> None:
    """Validate relation declarations against the declared entity types."""
    if not relations:
        report.error("no relation types declared — nodes without typed edges are a list, not a graph")
        return

    if len(relations) > MAX_RELATION_TYPES:
        report.warn(f"{len(relations)} relation types exceeds {MAX_RELATION_TYPES}; consider merging near-duplicates")

    for name, body in relations.items():
        label = str(name)

        if not RELATION_NAME_RE.match(label):
            report.error(f"relation '{label}' must be SCREAMING_SNAKE_CASE (e.g. 'EMPLOYED_BY')")

        if label.upper() in VAGUE_RELATIONS:
            report.error(
                f"relation '{label}' is too vague — name the specific verb (ACQUIRED, DEPENDS_ON). "
                "Vague relations make domain/range validation vacuous."
            )

        if not isinstance(body, dict):
            report.error(f"relation '{label}' must be a mapping with 'domain' and 'range'")
            continue

        for slot in ("domain", "range"):
            value = body.get(slot)
            if not value:
                report.error(f"relation '{label}' has no '{slot}' — unconstrained edges cannot be validated in code")
                continue
            for type_name in value if isinstance(value, list) else [value]:
                if str(type_name) not in declared:
                    report.error(
                        f"relation '{label}' {slot} references undeclared entity type '{type_name}'"
                    )


def check_events(events: dict[str, Any], declared: set[str], report: Report) -> None:
    """Validate event schemas.

    Events are first-class nodes, so an event type must also be declared as an entity
    type — the `events` section attaches an argument schema to it. An event schema with
    no matching entity type is dangling: nothing in the graph can carry those arguments.
    """
    for name, body in events.items():
        label = str(name)

        if not TYPE_NAME_RE.match(label):
            report.error(f"event type '{label}' must be PascalCase")

        if not isinstance(body, dict):
            report.error(f"event type '{label}' must be a mapping with 'trigger' and 'args'")
            continue

        if not str(body.get("trigger", "")).strip():
            report.error(
                f"event type '{label}' has no 'trigger' — an event with no trigger evidence "
                "is an inference, not an extracted fact"
            )

        args = body.get("args") or []
        if not isinstance(args, list) or not args:
            report.error(f"event type '{label}' has no 'args' — flattening loses which event carried which value")
        elif len(args) < 2:
            report.warn(f"event type '{label}' has one argument; a single-argument event is usually an attribute")

        if label not in declared:
            report.error(
                f"event type '{label}' is not declared under 'entities' — events are "
                "first-class nodes, so the type must exist before it can carry arguments"
            )


def check_canonical_form(canonical: dict[str, Any], declared: set[str], report: Report) -> None:
    """Canonical-form rules are what fusion enforces; unstated means unenforced."""
    if not canonical:
        report.warn(
            "no 'canonical_form' rules — fusion enforces whatever rule is stated here, "
            "so an absent rule means entity resolution has nothing to normalize against"
        )
        return

    for type_name in canonical:
        if str(type_name) not in declared:
            report.error(f"canonical_form references undeclared entity type '{type_name}'")

    missing = sorted(declared - {str(k) for k in canonical})
    if missing:
        report.warn(f"no canonical_form rule for: {', '.join(missing)}")


def check_reachability(relations: dict[str, Any], declared: set[str], report: Report) -> None:
    """An entity type no relation touches cannot participate in a multi-hop query."""
    touched: set[str] = set()
    for body in relations.values():
        if not isinstance(body, dict):
            continue
        for slot in ("domain", "range"):
            value = body.get(slot)
            if not value:
                continue
            for type_name in value if isinstance(value, list) else [value]:
                touched.add(str(type_name))

    isolated = sorted(declared - touched)
    if isolated:
        report.warn(
            f"entity type(s) with no relations: {', '.join(isolated)} — "
            "unreachable types cannot appear in a multi-hop answer"
        )


def validate(doc: Any) -> Report:
    """Run every check against a parsed ontology document."""
    report = Report()

    if not isinstance(doc, dict):
        report.error("ontology root must be a mapping")
        return report

    known = {"entities", "relations", "events", "canonical_form"}
    for key in doc:
        if str(key) not in known:
            report.warn(f"unknown top-level key '{key}' (expected: {', '.join(sorted(known))})")

    entities = _as_mapping(doc.get("entities"), "entities", report)
    relations = _as_mapping(doc.get("relations"), "relations", report)
    events = _as_mapping(doc.get("events"), "events", report)
    canonical = _as_mapping(doc.get("canonical_form"), "canonical_form", report)

    declared = check_entities(entities, report)
    check_relations(relations, declared, report)
    check_events(events, declared, report)
    check_canonical_form(canonical, declared, report)
    check_reachability(relations, declared, report)

    return report


def render_text(report: Report, path: Path) -> str:
    lines: list[str] = []
    for message in report.errors:
        lines.append(f"ERROR   {message}")
    for message in report.warnings:
        lines.append(f"WARN    {message}")
    if report.ok and not report.warnings:
        lines.append(f"OK      {path} is a valid ontology")
    else:
        lines.append("")
        lines.append(f"{len(report.errors)} error(s), {len(report.warnings)} warning(s) in {path}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a kg-builder ontology.yaml")
    parser.add_argument("ontology", type=Path, help="path to ontology.yaml")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--strict", action="store_true", help="treat warnings as failures")
    args = parser.parse_args(argv)

    path: Path = args.ontology
    if not path.is_file():
        print(f"ERROR   no such file: {path}", file=sys.stderr)
        return 2

    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        print(f"ERROR   unparseable YAML in {path}: {exc}", file=sys.stderr)
        return 2

    report = validate(doc)

    if args.format == "json":
        print(json.dumps({
            "path": str(path),
            "valid": report.ok,
            "errors": report.errors,
            "warnings": report.warnings,
        }, indent=2))
    else:
        print(render_text(report, path))

    if not report.ok:
        return 1
    if args.strict and report.warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
