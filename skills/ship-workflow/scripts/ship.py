#!/usr/bin/env python3
"""Reconcile an existing PR through authorized landing and safe cleanup."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
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

from git_ops import GitError, GitRepository, parse_remote_identity
from github_ops import GitHub, ProviderError
from lifecycle import EXIT_CODES, Endpoint, execute, inspection, load_policy
from state_store import Receipt, ReceiptInputError, StateError, Store, validate_run_id


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
    args = parser.parse_args()
    if args.pr is None and args.resume is None:
        parser.error("provide --pr or --resume")
    try:
        policy = load_policy(args.policy.resolve()) if args.policy else None
    except (ValueError, TypeError, OSError) as error:
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
                    if (args.pr is None or record.number == args.pr)
                    and (
                        selected is None
                        or (record.host, record.repo.lower())
                        == (selected[0], selected[1].lower())
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
                if args.pr is not None and args.pr != receipt.number:
                    raise ReceiptInputError("--pr does not match the saved run")
                if selected is not None and (selected[0], selected[1].lower()) != (
                    receipt.host,
                    receipt.repo.lower(),
                ):
                    raise ReceiptInputError("--repo does not match the saved run")
                selected = (receipt.host, receipt.repo)
        if selected is None:
            selected = infer_repository(git)
        number = receipt.number if receipt is not None else args.pr
        if number is None:
            raise ReceiptInputError("no unambiguous existing PR is selected")
        endpoint: Endpoint
        if args.until is not None:
            endpoint = args.until
        elif receipt is not None:
            endpoint = cast(Endpoint, receipt.endpoint)
        else:
            endpoint = "clean"
        provider = GitHub(*selected, deadline=time.monotonic() + args.wait_timeout)
        if args.dry_run:
            result = inspection(git, provider, number, endpoint, policy)
            code = 0
        else:
            result, code = execute(
                git,
                provider,
                number,
                endpoint,
                policy,
                args.wait_timeout,
                store,
                receipt,
            )
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
    except (GitError, ProviderError, StateError, OSError) as error:
        status = error.kind if isinstance(error, ProviderError) else "BLOCKED"
        print(json.dumps({"schema_version": 1, "status": status, "error": str(error)}))
        return EXIT_CODES[status]
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
