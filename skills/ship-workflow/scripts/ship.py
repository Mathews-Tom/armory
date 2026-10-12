#!/usr/bin/env python3
"""Ship local work or an existing PR through publication, landing and safe cleanup."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import cast

# Suppress package cache writes before importing the installed local modules.
sys.dont_write_bytecode = True
if sys.version_info < (3, 12):  # noqa: UP036 -- installed entrypoints run outside project constraints
    print(
        json.dumps(
            {
                "schema_version": 1,
                "status": "BLOCKED",
                "blocker": "Python 3.12 or newer is required",
            }
        )
    )
    raise SystemExit(5)

from changeset import (
    ChangesetStop,
    PlanError,
    compile_draft,
    load_draft,
    load_gates,
    load_plan,
    parse_plan,
    take_inventory,
)
from git_ops import GitError, GitRepository, parse_remote_identity
from github_ops import GitHub, ProviderError
from lifecycle import EXIT_CODES, Endpoint, load_decision
from publish import Request, preview, ship
from state_store import Receipt, ReceiptInputError, StateError, Store, validate_run_id


def run_namespace(record: Receipt) -> tuple[str, str] | None:
    """The provider base namespace a saved run is bound to, if any."""
    if record.target is not None:
        return record.host, record.repo.lower()
    if record.publication is not None:
        return record.publication.host, record.publication.base_repo.lower()
    return None


def run_branches(record: Receipt) -> set[str]:
    branches: set[str] = set()
    if record.target is not None:
        branches.add(record.head_ref)
    if record.publication is not None:
        branches.add(record.publication.head_ref)
    if record.changeset is not None:
        branches.add(record.changeset.branch)
    return branches


def matches_pr(record: Receipt, number: int) -> bool:
    """A bound target is authoritative; otherwise only a confirmed own creation."""
    if record.target is not None:
        return record.number == number
    publication = record.publication
    create = None if publication is None else publication.create
    return (
        create is not None and create.outcome == "CONFIRMED" and create.number == number
    )


def repository_selector(value: str) -> tuple[str, str]:
    parts = value.split("/")
    host = "github.com"
    if len(parts) == 3:
        host, parts = parts[0], parts[1:]
    if len(parts) != 2 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", host):
        raise ValueError("--repo must be OWNER/REPO or HOST/OWNER/REPO")
    if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", part) for part in parts):
        raise ValueError("invalid provider repository identity")
    return host.lower(), "/".join(parts)


def infer_repository(git: GitRepository) -> tuple[str, str]:
    identities: set[tuple[str, str]] = set()
    for url in git.snapshot().remotes.values():
        identity = parse_remote_identity(url)
        if identity is not None:
            identities.add(identity)
    if len(identities) != 1:
        raise ValueError(
            "remote identities are ambiguous; provide the actual PR base with --repo"
        )
    return next(iter(identities))


def positive_number(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected a positive integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return parsed


def planning(draft: Path | None, gates_path: Path | None) -> int:
    """Read-only inventory, or explicit object authoring for a grouping draft."""
    try:
        git = GitRepository(Path.cwd())
        if draft is None:
            payload: dict[str, object] = {
                "schema_version": 1,
                "status": "PLANNED",
                "inventory": take_inventory(git).to_json(),
                "mutation_performed": False,
            }
        else:
            if gates_path is None:
                raise PlanError("a draft needs its gate decision packet")
            plan = compile_draft(
                git, load_draft(draft.resolve()), load_gates(gates_path.resolve())
            )
            payload = {
                "schema_version": 1,
                "status": "PLANNED",
                "plan": plan,
                "plan_identity": parse_plan(plan).identity,
                "objects_written": True,
                "mutation_performed": False,
            }
    except (PlanError, ValueError, TypeError) as error:
        print(
            json.dumps({"schema_version": 1, "status": "BLOCKED", "error": str(error)})
        )
        return 2
    except ChangesetStop as stop:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": stop.status,
                    "blocker": str(stop),
                    "details": stop.details,
                    "next_action": stop.next_action,
                },
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return EXIT_CODES[stop.status]
    except (GitError, OSError) as error:
        print(
            json.dumps({"schema_version": 1, "status": "BLOCKED", "error": str(error)})
        )
        return 5
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", type=positive_number)
    parser.add_argument(
        "--resume",
        nargs="?",
        const="unique",
        metavar="RUN_ID",
        help="resume one explicit or unambiguous saved run",
    )
    parser.add_argument(
        "--repo", help="actual PR base repository, optionally prefixed by host"
    )
    parser.add_argument("--until", choices=("pr", "merged", "clean"))
    parser.add_argument(
        "--policy", type=Path, help="explicit source-backed decision packet"
    )
    parser.add_argument("--wait-timeout", type=positive_number, default=1800)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--inventory",
        action="store_true",
        help="print the read-only change inventory of the current checkout",
    )
    parser.add_argument(
        "--draft",
        type=Path,
        help="compile a grouping draft into a commit plan (writes Git objects only)",
    )
    parser.add_argument(
        "--gates", type=Path, help="explicit source-backed gate decision packet"
    )
    parser.add_argument("--branch", help="local feature branch to publish and ship")
    parser.add_argument(
        "--plan", type=Path, help="snapshot-bound commit plan to execute first"
    )
    parser.add_argument(
        "--head-repo", help="head namespace OWNER/REPO when it differs (fork)"
    )
    parser.add_argument("--title", help="title of a PR this run creates")
    parser.add_argument("--body-file", type=Path, help="body of a PR this run creates")
    args = parser.parse_args()
    if args.inventory or args.draft is not None:
        if args.inventory and args.draft is not None:
            parser.error("choose one of --inventory or --draft")
        if (
            any(
                value is not None
                for value in (
                    args.pr,
                    args.resume,
                    args.until,
                    args.policy,
                    args.branch,
                    args.plan,
                    args.head_repo,
                    args.title,
                    args.body_file,
                )
            )
            or args.dry_run
        ):
            parser.error("--inventory and --draft select no target, run or endpoint")
        if args.draft is not None and args.gates is None:
            parser.error("--draft requires the --gates decision packet")
        return planning(args.draft, args.gates)
    if args.pr is not None and args.branch is not None:
        parser.error("--pr and --branch are mutually exclusive selectors")
    if (args.title is None) != (args.body_file is None):
        parser.error("--title and --body-file are given together")
    try:
        policy = load_decision(args.policy.resolve()) if args.policy else None
        plan = load_plan(args.plan.resolve()) if args.plan else None
        gates = load_gates(args.gates.resolve()) if args.gates else None
        body = args.body_file.resolve().read_bytes() if args.body_file else None
        head_repo = repository_selector(args.head_repo)[1] if args.head_repo else None
    except (PlanError, ValueError, TypeError, OSError) as error:
        print(
            json.dumps({"schema_version": 1, "status": "BLOCKED", "error": str(error)})
        )
        return 2
    try:
        git = GitRepository(Path.cwd())
        store = Store(git.snapshot().common_dir)
        receipt: Receipt | None = None
        selected = repository_selector(args.repo) if args.repo else None
        if args.resume is not None:
            if args.resume == "unique":
                candidates = tuple(
                    record
                    for record in store.list_runs()
                    if (args.pr is None or matches_pr(record, args.pr))
                    and (args.branch is None or args.branch in run_branches(record))
                    and (
                        selected is None
                        or run_namespace(record) == (selected[0], selected[1].lower())
                    )
                )
                pending = tuple(
                    record for record in candidates if record.status != "COMPLETE"
                )
                choices = pending if pending else candidates
                if len(choices) != 1:
                    raise ReceiptInputError(
                        "saved target is missing or ambiguous; provide a run id"
                    )
                receipt = choices[0]
            else:
                validate_run_id(args.resume)
                try:
                    receipt = store.load(args.resume)
                except FileNotFoundError:
                    if args.pr is None or args.until is None:
                        raise ReceiptInputError(
                            "missing receipt: provide --pr, --repo and --until to reconstruct scope"
                        ) from None
            if receipt is not None:
                if args.pr is not None and not matches_pr(receipt, args.pr):
                    raise ReceiptInputError("--pr does not match the saved run")
                if args.branch is not None and args.branch not in run_branches(receipt):
                    raise ReceiptInputError("--branch does not match the saved run")
                namespace = run_namespace(receipt)
                if namespace is not None:
                    if (
                        selected is not None
                        and (
                            selected[0],
                            selected[1].lower(),
                        )
                        != namespace
                    ):
                        raise ReceiptInputError("--repo does not match the saved run")
                    if receipt.target is not None:
                        selected = (receipt.host, receipt.repo)
                    elif receipt.publication is not None:
                        selected = (
                            receipt.publication.host,
                            receipt.publication.base_repo,
                        )
        if selected is None:
            selected = infer_repository(git)
        endpoint: Endpoint
        if args.until is not None:
            endpoint = args.until
        elif receipt is not None:
            endpoint = cast(Endpoint, receipt.endpoint)
        else:
            endpoint = "clean"
        provider = GitHub(*selected, deadline=time.monotonic() + args.wait_timeout)
        request = Request(
            host=selected[0],
            base_repo=selected[1],
            head_repo=head_repo,
            number=args.pr,
            branch=args.branch,
            endpoint=endpoint,
            plan=plan,
            gates=gates,
            decision=policy,
            title=args.title,
            body=body,
            wait_timeout=args.wait_timeout,
        )
        if args.dry_run:
            if receipt is not None and receipt.target is not None and plan is None:
                request = replace(request, number=receipt.number)
            elif receipt is not None and receipt.publication is not None:
                request = replace(
                    request,
                    branch=receipt.publication.head_ref,
                    head_repo=receipt.publication.head_repo,
                )
            result = preview(git, provider, request)
            code = 0
        else:
            result, code = ship(git, provider, store, request, receipt)
    except (ReceiptInputError, ValueError, TypeError) as error:
        print(
            json.dumps({"schema_version": 1, "status": "BLOCKED", "error": str(error)})
        )
        return 2
    except KeyboardInterrupt:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "WAITING",
                    "cancelled": True,
                    "next_action": "repeat the explicit selector",
                }
            )
        )
        return 130
    except ChangesetStop as stop:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": stop.status,
                    "blocker": str(stop),
                    "details": stop.details,
                    "next_action": stop.next_action,
                },
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return EXIT_CODES[stop.status]
    except (GitError, ProviderError, StateError, OSError) as error:
        status = error.kind if isinstance(error, ProviderError) else "BLOCKED"
        print(json.dumps({"schema_version": 1, "status": status, "error": str(error)}))
        return EXIT_CODES[status]
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
