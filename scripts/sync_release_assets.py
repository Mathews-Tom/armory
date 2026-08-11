#!/usr/bin/env python3
"""
Sync packaged artifacts to a GitHub release without tripping secondary rate limits.

The previous approach re-uploaded every artifact on every push to `main`. Each upload
is a delete plus a create, so a catalog of N packages cost ~2N API calls in a burst and
eventually failed with:

    You have exceeded a secondary rate limit.

This script uploads only what actually changed. It keeps a `checksums.txt` asset on the
release recording the SHA-256 of every artifact it uploaded; on the next run it fetches
that one small file, compares digests, and touches nothing else. A typical push that
changes one package costs two uploads instead of several hundred.

Cold starts (a fresh versioned tag, or a `latest` release with no checksums yet) still
upload everything, so every API call is wrapped in retry-with-backoff and batches are
spaced out.

Requires the `gh` CLI and a token in GH_TOKEN or GITHUB_TOKEN.

Usage:
    python sync_release_assets.py --tag latest --dist dist \
        --title "Latest Packages (rolling)" --notes-file notes.md \
        --prerelease --no-make-latest

    python sync_release_assets.py --tag latest --dist dist --dry-run
    python sync_release_assets.py --tag latest --dist dist --prune

Exit codes:
    0  release in sync
    1  an operation failed after exhausting retries
    2  bad invocation or missing prerequisite
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

CHECKSUM_ASSET = "checksums.txt"

# Uploads per `gh release upload` invocation. gh still issues one API call per file, so
# this bounds how many calls land back to back before the throttle pause.
BATCH_SIZE = 20

# Seconds to pause between batches. Cheap insurance against secondary limits, and it
# only costs anything on cold starts where many files change at once.
BATCH_PAUSE = 3.0

MAX_ATTEMPTS = 5
BASE_BACKOFF = 5.0

# GitHub does not document a retry-after for secondary limits and asks for a longer
# wait than an ordinary transient failure warrants.
SECONDARY_LIMIT_BACKOFF = 60.0
SECONDARY_LIMIT_MARKER = "secondary rate limit"


class CommandError(RuntimeError):
    """A gh invocation failed after exhausting retries."""


@dataclass
class Plan:
    upload: list[Path] = field(default_factory=list)
    unchanged: list[Path] = field(default_factory=list)
    prune: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.upload and not self.prune


def run(
    args: list[str],
    *,
    capture: bool = True,
    check: bool = True,
    retries: int = 1,
) -> subprocess.CompletedProcess[str]:
    """Run a command, retrying with backoff when GitHub throttles or the call flakes."""
    last: subprocess.CompletedProcess[str] | None = None

    for attempt in range(1, retries + 1):
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            args,
            capture_output=capture,
            text=True,
            check=False,
        )
        if proc.returncode == 0 or not check:
            return proc

        last = proc
        stderr = (proc.stderr or "").strip()

        if attempt == retries:
            break

        if SECONDARY_LIMIT_MARKER in stderr.lower():
            delay = SECONDARY_LIMIT_BACKOFF * attempt
            reason = "secondary rate limit"
        else:
            delay = BASE_BACKOFF * (2 ** (attempt - 1))
            reason = stderr.splitlines()[0] if stderr else f"exit {proc.returncode}"

        print(
            f"  retry {attempt}/{retries - 1} in {delay:.0f}s — {reason}",
            file=sys.stderr,
            flush=True,
        )
        time.sleep(delay)

    detail = (last.stderr or last.stdout or "").strip() if last else ""
    raise CommandError(f"{' '.join(args)} failed after {retries} attempt(s): {detail}")


def digest(path: Path) -> str:
    """SHA-256 of a file, read in chunks so large archives do not land in memory."""
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            sha.update(block)
    return sha.hexdigest()


def local_digests(dist: Path) -> dict[str, tuple[Path, str]]:
    """Map artifact name -> (path, digest) for every file directly under dist/."""
    artifacts: dict[str, tuple[Path, str]] = {}
    for path in sorted(dist.iterdir()):
        if not path.is_file() or path.name == CHECKSUM_ASSET:
            continue
        artifacts[path.name] = (path, digest(path))
    return artifacts


def parse_checksums(text: str) -> dict[str, str]:
    """Parse `<sha256>  <name>` lines. Unparseable lines are ignored, not fatal."""
    digests: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and len(parts[0]) == 64:
            digests[parts[1].strip()] = parts[0]
    return digests


def render_checksums(artifacts: dict[str, tuple[Path, str]]) -> str:
    return "".join(f"{sha}  {name}\n" for name, (_, sha) in sorted(artifacts.items()))


def release_exists(tag: str) -> bool:
    proc = run(["gh", "release", "view", tag, "--json", "tagName"], check=False)
    return proc.returncode == 0


def remote_assets(tag: str) -> list[str]:
    proc = run(
        ["gh", "release", "view", tag, "--json", "assets", "--jq", ".assets[].name"],
        retries=MAX_ATTEMPTS,
    )
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def fetch_remote_checksums(tag: str, assets: list[str]) -> dict[str, str]:
    """Download the checksum manifest from the release. Absent manifest = cold start."""
    if CHECKSUM_ASSET not in assets:
        return {}

    with tempfile.TemporaryDirectory() as tmp:
        proc = run(
            [
                "gh", "release", "download", tag,
                "--pattern", CHECKSUM_ASSET,
                "--dir", tmp,
                "--clobber",
            ],
            check=False,
            retries=MAX_ATTEMPTS,
        )
        if proc.returncode != 0:
            print(
                f"  could not fetch {CHECKSUM_ASSET}; treating as a cold start",
                file=sys.stderr,
            )
            return {}
        return parse_checksums((Path(tmp) / CHECKSUM_ASSET).read_text(encoding="utf-8"))


def build_plan(
    artifacts: dict[str, tuple[Path, str]],
    remote_digests: dict[str, str],
    assets: list[str],
    *,
    prune: bool,
) -> Plan:
    """Decide what to upload and, when pruning, what to remove."""
    plan = Plan()
    present = set(assets)

    for name, (path, sha) in sorted(artifacts.items()):
        if name in present and remote_digests.get(name) == sha:
            plan.unchanged.append(path)
        else:
            plan.upload.append(path)

    if prune:
        plan.prune = sorted(present - set(artifacts) - {CHECKSUM_ASSET})

    return plan


def upload(tag: str, paths: list[Path], *, label: str) -> None:
    """Upload in throttled batches so a cold start does not burst the API."""
    total = len(paths)
    for start in range(0, total, BATCH_SIZE):
        batch = paths[start : start + BATCH_SIZE]
        print(f"  {label} {start + 1}-{start + len(batch)} of {total}", flush=True)
        run(
            ["gh", "release", "upload", tag, *[str(p) for p in batch], "--clobber"],
            retries=MAX_ATTEMPTS,
        )
        if start + BATCH_SIZE < total:
            time.sleep(BATCH_PAUSE)


def delete_assets(tag: str, names: list[str]) -> None:
    for index, name in enumerate(names, start=1):
        print(f"  pruning {index}/{len(names)}: {name}", flush=True)
        run(["gh", "release", "delete-asset", tag, name, "--yes"], retries=MAX_ATTEMPTS)
        time.sleep(0.5)


def ensure_release(args: argparse.Namespace) -> bool:
    """Create the release when missing, otherwise refresh its metadata. Returns created."""
    if release_exists(args.tag):
        edit = ["gh", "release", "edit", args.tag]
        if args.title:
            edit += ["--title", args.title]
        if args.notes_file:
            edit += ["--notes-file", args.notes_file]
        run(edit, retries=MAX_ATTEMPTS)
        return False

    create = ["gh", "release", "create", args.tag, "--target", args.target]
    if args.title:
        create += ["--title", args.title]
    if args.notes_file:
        create += ["--notes-file", args.notes_file]
    else:
        create += ["--generate-notes"]
    if args.prerelease:
        create += ["--prerelease"]
    create += ["--latest=false"] if args.no_make_latest else ["--latest"]
    run(create, retries=MAX_ATTEMPTS)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync dist artifacts to a GitHub release")
    parser.add_argument("--tag", required=True, help="release tag, e.g. 'latest' or 'v1.2.0'")
    parser.add_argument("--dist", type=Path, default=Path("dist"), help="artifact directory")
    parser.add_argument("--title", help="release title")
    parser.add_argument("--notes-file", help="path to release notes markdown")
    parser.add_argument("--target", default="main", help="commitish for a new release")
    parser.add_argument("--prerelease", action="store_true")
    parser.add_argument("--no-make-latest", action="store_true", help="do not mark as latest")
    parser.add_argument(
        "--prune", action="store_true",
        help="delete release assets with no local counterpart (e.g. superseded versions)",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    args = parser.parse_args(argv)

    if not args.dist.is_dir():
        print(f"ERROR   no such directory: {args.dist}", file=sys.stderr)
        return 2

    if not args.dry_run and not (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")):
        print("ERROR   GH_TOKEN or GITHUB_TOKEN must be set", file=sys.stderr)
        return 2

    artifacts = local_digests(args.dist)
    if not artifacts:
        print(f"ERROR   {args.dist} contains no artifacts", file=sys.stderr)
        return 2

    try:
        exists = release_exists(args.tag)
        created = False
        if not args.dry_run:
            created = ensure_release(args)
            exists = True

        assets = remote_assets(args.tag) if exists and not created else []
        remote = fetch_remote_checksums(args.tag, assets) if assets else {}
        plan = build_plan(artifacts, remote, assets, prune=args.prune)

        print(
            f"{args.tag}: {len(artifacts)} local artifact(s), {len(assets)} remote asset(s)\n"
            f"  upload    {len(plan.upload)}\n"
            f"  unchanged {len(plan.unchanged)}\n"
            f"  prune     {len(plan.prune)}"
        )

        if args.dry_run:
            for path in plan.upload[:20]:
                print(f"  + {path.name}")
            if len(plan.upload) > 20:
                print(f"  + ... and {len(plan.upload) - 20} more")
            for name in plan.prune[:20]:
                print(f"  - {name}")
            if len(plan.prune) > 20:
                print(f"  - ... and {len(plan.prune) - 20} more")
            return 0

        if plan.upload:
            upload(args.tag, plan.upload, label="uploading")
        if plan.prune:
            delete_assets(args.tag, plan.prune)

        # The manifest is written last so a mid-run failure leaves the previous digests
        # in place; the next run then re-detects the unfinished uploads instead of
        # trusting a manifest that claims work which never completed.
        if plan.upload or plan.prune or CHECKSUM_ASSET not in assets:
            with tempfile.TemporaryDirectory() as tmp:
                manifest = Path(tmp) / CHECKSUM_ASSET
                manifest.write_text(render_checksums(artifacts), encoding="utf-8")
                run(
                    ["gh", "release", "upload", args.tag, str(manifest), "--clobber"],
                    retries=MAX_ATTEMPTS,
                )

        if plan.empty:
            print("release already in sync — no uploads issued")
        else:
            print(f"synced: {len(plan.upload)} uploaded, {len(plan.prune)} pruned")
    except CommandError as exc:
        print(f"ERROR   {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
