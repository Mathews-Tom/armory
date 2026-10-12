#!/usr/bin/env python3
"""Inspect an existing PR without local writes or provider mutations."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

# Suppress package cache writes before importing the installed local modules.
sys.dont_write_bytecode = True

from git_ops import GitError, GitRepository, parse_remote_identity
from github_ops import GitHub, ProviderError
from lifecycle import Endpoint, inspection, load_policy


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
    parser.add_argument("--pr", required=True, type=positive_number)
    parser.add_argument(
        "--repo", help="actual PR base repository, optionally prefixed by host"
    )
    parser.add_argument("--until", choices=("pr", "merged", "clean"), default="clean")
    parser.add_argument(
        "--policy", type=Path, help="explicit source-backed decision packet"
    )
    parser.add_argument("--wait-timeout", type=positive_number, default=1800)
    parser.add_argument("--dry-run", action="store_true", required=True)
    args = parser.parse_args()
    endpoint: Endpoint = args.until
    try:
        policy = load_policy(args.policy.resolve()) if args.policy else None
    except (ValueError, TypeError, OSError) as error:
        print(
            json.dumps({"schema_version": 1, "status": "BLOCKED", "error": str(error)})
        )
        return 2
    try:
        git = GitRepository(Path.cwd())
        host, name = (
            repository_selector(args.repo) if args.repo else infer_repository(git)
        )
        provider = GitHub(host, name, deadline=time.monotonic() + args.wait_timeout)
        result = inspection(git, provider, args.pr, endpoint, policy)
    except (ValueError, OSError) as error:
        print(
            json.dumps({"schema_version": 1, "status": "BLOCKED", "error": str(error)})
        )
        return 2
    except (GitError, ProviderError) as error:
        status = error.kind if isinstance(error, ProviderError) else "BLOCKED"
        print(json.dumps({"schema_version": 1, "status": status, "error": str(error)}))
        return 3 if status == "WAITING" else 5
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
