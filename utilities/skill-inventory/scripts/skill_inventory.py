#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["PyYAML==6.0.3"]
# ///
"""Measure local skill metadata and propose actions without network or model calls."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import NoReturn, cast

# Wrapped utility installations are skills too; imports must not create bytecode there.
sys.dont_write_bytecode = True

import inventory_archive
from inventory_catalog import load_inventory
from inventory_claude import parse_file as parse_claude
from inventory_codex import parse_file as parse_codex
from inventory_io import (
    BINDING_VERSION,
    SNAPSHOT_POLICY,
    Snapshot,
    read_private_json,
    write_private_json,
)
from inventory_omp import parse_file as parse_omp
from inventory_policy import recommend
from inventory_report import build_report
from inventory_types import Harness, Inventory, ParsedFile, SchemaError, utc_time


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # argparse normally echoes invalid values, which can contain private paths.
        raise SchemaError("invalid_arguments")


@dataclass
class _Measurement:
    report: dict[str, object]
    private_report: dict[str, object]
    inventory: Inventory
    snapshot: Snapshot
    as_of: datetime
    window_days: int


def _measurement_arguments(
    command: argparse.ArgumentParser, *, private_report: bool = True
) -> None:
    command.add_argument("--harness", choices=("omp", "claude", "codex"), required=True)
    command.add_argument("--as-of", required=True, help="Explicit UTC timestamp (Z).")
    command.add_argument("--window-days", type=int, default=90)
    command.add_argument(
        "--snapshot", type=Path, required=True, help="Private capture/replay binding."
    )
    command.add_argument("--aggregate-only", action="store_true")
    command.add_argument(
        "--log-root", type=Path, action="append", help="Explicit approved log root."
    )
    command.add_argument(
        "--skill-root",
        type=Path,
        action="append",
        help="Explicit read-only skill root.",
    )
    command.add_argument(
        "--reference", type=Path, action="append", help="Approved dependency source."
    )
    if private_report:
        command.add_argument(
            "--private-report",
            type=Path,
            help="Installed-file identities; never log identities.",
        )


def _inventory(args: argparse.Namespace, snapshot: Snapshot) -> Inventory:
    skill_roots = cast(list[Path] | None, args.skill_root)
    references = cast(list[Path] | None, args.reference) or []
    return load_inventory(
        cast(Harness, args.harness),
        key=snapshot.key,
        skill_roots=(
            [path.expanduser() for path in skill_roots] if skill_roots else None
        ),
        reference_paths=[path.expanduser() for path in references],
    )


def _policy_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--pins", type=Path, help="Private versioned pin document.")
    command.add_argument(
        "--attestations",
        type=Path,
        help="Private per-item generated-only attestations.",
    )


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(description="Offline skill inventory; stdout is aggregate-only.")
    commands = parser.add_subparsers(dest="command", required=True)
    measure = commands.add_parser(
        "measure", help="Measure frozen JSONL prefixes and installed skill metadata."
    )
    _measurement_arguments(measure)
    recommendations = commands.add_parser(
        "recommend", help="Propose conservative actions; never move or merge skills."
    )
    _measurement_arguments(recommendations)
    _policy_arguments(recommendations)
    recommendations.add_argument(
        "--proposal",
        type=Path,
        required=True,
        help="Private installed-skill proposal output.",
    )
    archive = commands.add_parser(
        "archive", help="Validate or apply an exact reviewed OMP-only proposal."
    )
    _measurement_arguments(archive, private_report=False)
    _policy_arguments(archive)
    archive.add_argument(
        "--proposal", type=Path, required=True, help="Saved private proposal."
    )
    archive.add_argument("--approval", type=Path, help="Private exact-item approval.")
    archive_mode = archive.add_mutually_exclusive_group(required=True)
    archive_mode.add_argument("--dry-run", action="store_true")
    archive_mode.add_argument("--apply", action="store_true")
    restore = commands.add_parser(
        "restore", help="List journals or restore all or selected archived OMP skills."
    )
    source = restore.add_mutually_exclusive_group(required=True)
    source.add_argument("--list", action="store_true", dest="list_runs")
    source.add_argument("--manifest", type=Path)
    restore.add_argument(
        "--item",
        action="append",
        help="One installed identity from the private journal.",
    )
    restore_mode = restore.add_mutually_exclusive_group()
    restore_mode.add_argument("--dry-run", action="store_true")
    restore_mode.add_argument("--apply", action="store_true")
    return parser


def _measurement(
    args: argparse.Namespace, *, replay_only: bool = False
) -> _Measurement:
    harness = cast(Harness, args.harness)
    raw_as_of = cast(str, args.as_of)
    if not raw_as_of.endswith(("Z", "+00:00")):
        raise SchemaError("as_of_must_be_utc")
    as_of = utc_time(raw_as_of, "invalid_as_of")
    window_days = cast(int, args.window_days)
    if window_days <= 0:
        raise SchemaError("invalid_window")
    roots = cast(list[Path] | None, args.log_root)
    defaults = {
        "omp": Path.home() / ".omp" / "agent" / "sessions",
        "claude": Path.home() / ".claude" / "projects",
        "codex": Path.home() / ".codex" / "sessions",
    }
    log_roots = roots or [defaults[harness]]
    snapshot = Snapshot(
        cast(Path, args.snapshot).expanduser(),
        harness=harness,
        roots=[path.expanduser() for path in log_roots],
        as_of=as_of,
        window_days=window_days,
    )
    if replay_only and snapshot.mode != "replayed":
        raise SchemaError("snapshot_replay_required")
    inventory = _inventory(args, snapshot)
    snapshot.bind_inventory(inventory.integrity)
    parsed: list[ParsedFile] = []
    parse = {"omp": parse_omp, "claude": parse_claude, "codex": parse_codex}[harness]
    groups = snapshot.main_task_groups()
    for frozen in snapshot.files:
        try:
            result = parse(
                snapshot.records(frozen),
                inventory=inventory,
                file_key=frozen.key,
                cohort_hint=frozen.cohort,
            )
        except SchemaError as error:
            result = ParsedFile(
                frozen.key,
                frozen.cohort,
                issues=Counter({error.code: 1}),
                schema_supported=False,
            )
        group = groups.get(frozen.key)
        if group is not None:
            result.exposures = [
                replace(observation, main_task_group=group)
                for observation in result.exposures
            ]
        parsed.append(result)
    fresh_inventory = _inventory(args, snapshot)
    try:
        snapshot_summary = snapshot.finish(fresh_inventory.integrity)
    except SchemaError as error:
        snapshot.issues[error.code] += 1
        snapshot_summary = {
            "policy": SNAPSHOT_POLICY,
            "binding_schema_version": BINDING_VERSION,
            "files": len(snapshot.files),
            "valid": False,
            "closed": False,
        }
    report, private_report = build_report(
        harness=harness,
        parsed=parsed,
        inventory=inventory,
        as_of=as_of,
        window_days=window_days,
        snapshot=snapshot_summary,
        input_issues=snapshot.issues,
    )
    return _Measurement(report, private_report, inventory, snapshot, as_of, window_days)


def measure(args: argparse.Namespace) -> dict[str, object]:
    measurement = _measurement(args)
    private_path = cast(Path | None, args.private_report)
    if private_path is not None:
        write_private_json(private_path.expanduser(), measurement.private_report)
    return measurement.report


def _proposal(
    args: argparse.Namespace, measurement: _Measurement
) -> tuple[dict[str, object], dict[str, object]]:
    report, proposal = recommend(
        measurement.report,
        measurement.private_report,
        measurement.inventory,
        as_of=measurement.as_of,
        window_days=measurement.window_days,
        binding_path=cast(Path, args.snapshot).expanduser(),
        pins_path=(
            cast(Path, args.pins).expanduser() if args.pins is not None else None
        ),
        attestations_path=(
            cast(Path, args.attestations).expanduser()
            if args.attestations is not None
            else None
        ),
    )
    if (
        _inventory(args, measurement.snapshot).integrity
        != measurement.inventory.integrity
    ):
        raise SchemaError("inventory_changed_during_recommendation")
    return report, proposal


def recommendations(args: argparse.Namespace) -> dict[str, object]:
    measurement = _measurement(args)
    report, proposal = _proposal(args, measurement)
    write_private_json(cast(Path, args.proposal).expanduser(), proposal)
    private_path = cast(Path | None, args.private_report)
    if private_path is not None:
        write_private_json(private_path.expanduser(), measurement.private_report)
    return report


def archive_skills(args: argparse.Namespace) -> dict[str, object]:
    if args.harness != "omp" or not args.aggregate_only:
        raise SchemaError("archive_requires_omp_aggregate_only")
    saved = read_private_json(cast(Path, args.proposal).expanduser())
    approval_path = cast(Path | None, args.approval)
    approval = (
        None if approval_path is None else read_private_json(approval_path.expanduser())
    )
    measurement = _measurement(args, replay_only=True)
    _, current = _proposal(args, measurement)
    return inventory_archive.archive(saved, current, approval, apply=bool(args.apply))


def restore_skills(args: argparse.Namespace) -> dict[str, object]:
    if args.list_runs:
        if args.apply or args.dry_run or args.item:
            raise SchemaError("invalid_arguments")
    elif not (args.apply or args.dry_run):
        raise SchemaError("explicit_restore_mode_required")
    manifest = cast(Path | None, args.manifest)
    return inventory_archive.restore(
        manifest_path=None if manifest is None else manifest.expanduser(),
        items=cast(list[str] | None, args.item),
        apply=bool(args.apply),
        list_runs=bool(args.list_runs),
    )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        handlers = {
            "measure": measure,
            "recommend": recommendations,
            "archive": archive_skills,
            "restore": restore_skills,
        }
        report = handlers[args.command](args)
    except SchemaError as error:
        report = {
            "schema_version": 1,
            "status": "incomplete",
            "diagnostics": {error.code: 1},
        }
    except (OSError, UnicodeError):
        report = {
            "schema_version": 1,
            "status": "incomplete",
            "diagnostics": {"local_io_error": 1},
        }
    except OverflowError:
        report = {
            "schema_version": 1,
            "status": "incomplete",
            "diagnostics": {"invalid_measurement_range": 1},
        }
    except (
        ArithmeticError,
        AssertionError,
        AttributeError,
        LookupError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        # Privacy boundary: a programming error must fail loudly, not dump a record.
        report = {
            "schema_version": 1,
            "status": "incomplete",
            "diagnostics": {"internal_error": 1},
        }
    print(json.dumps(report, sort_keys=True, indent=2, allow_nan=False))
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
