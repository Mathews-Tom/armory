#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["PyYAML==6.0.3"]
# ///
"""Measure local skill metadata without models, network calls or inventory edits."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn, cast

from inventory_catalog import load_inventory
from inventory_claude import parse_file as parse_claude
from inventory_codex import parse_file as parse_codex
from inventory_io import BINDING_VERSION, SNAPSHOT_POLICY, Snapshot, write_private_json
from inventory_omp import parse_file as parse_omp
from inventory_report import build_report
from inventory_types import Harness, ParsedFile, SchemaError, utc_time


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # argparse normally echoes invalid values, which can contain private paths.
        raise SchemaError("invalid_arguments")


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(
        description="Offline skill-inventory measurement; stdout is aggregate-only."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    measure = commands.add_parser(
        "measure", help="Measure frozen JSONL prefixes and installed skill metadata."
    )
    measure.add_argument("--harness", choices=("omp", "claude", "codex"), required=True)
    measure.add_argument("--as-of", required=True, help="Explicit UTC timestamp (Z).")
    measure.add_argument("--window-days", type=int, default=90)
    measure.add_argument(
        "--snapshot", type=Path, required=True, help="Private capture/replay binding."
    )
    measure.add_argument("--aggregate-only", action="store_true")
    measure.add_argument(
        "--log-root", type=Path, action="append", help="Explicit approved log root."
    )
    measure.add_argument(
        "--skill-root",
        type=Path,
        action="append",
        help="Explicit read-only skill root.",
    )
    measure.add_argument(
        "--reference", type=Path, action="append", help="Approved dependency source."
    )
    measure.add_argument(
        "--private-report",
        type=Path,
        help="Installed-file identities; never log identities.",
    )
    return parser


def measure(args: argparse.Namespace) -> dict[str, object]:
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
    skill_roots = cast(list[Path] | None, args.skill_root)
    references = cast(list[Path] | None, args.reference) or []
    snapshot = Snapshot(
        cast(Path, args.snapshot).expanduser(),
        harness=harness,
        roots=[path.expanduser() for path in log_roots],
        as_of=as_of,
        window_days=window_days,
    )
    inventory = load_inventory(
        harness,
        key=snapshot.key,
        skill_roots=(
            [path.expanduser() for path in skill_roots] if skill_roots else None
        ),
        reference_paths=[path.expanduser() for path in references],
    )
    snapshot.bind_inventory(inventory.integrity)
    parsed: list[ParsedFile] = []
    parse = {"omp": parse_omp, "claude": parse_claude, "codex": parse_codex}[harness]
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
        parsed.append(result)
    fresh_inventory = load_inventory(
        harness,
        key=snapshot.key,
        skill_roots=(
            [path.expanduser() for path in skill_roots] if skill_roots else None
        ),
        reference_paths=[path.expanduser() for path in references],
    )
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
    private_path = cast(Path | None, args.private_report)
    if private_path is not None:
        write_private_json(private_path.expanduser(), private_report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    try:
        report = measure(_parser().parse_args(argv))
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
