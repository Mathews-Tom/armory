#!/usr/bin/env python3
"""Rebuild the synthetic `queuebox` example and every generated file in examples/output/.

The repository is fictional (two contributors, Alice is the candidate, plus a
dependency bot). Dates, identities and the run timestamp are fixed, so a rerun
reproduces the same assessment_id. Usage:

    python3 skills/appraise/examples/regenerate.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent / "scripts" / "appraise.py"
WORK = Path("/tmp/appraise-example")
REPO = WORK / "queuebox"
RUN = WORK / "run"
NOW = "2026-10-14T00:00:00Z"
ALICE = ("Alice Doe", "alice@example.com")
BOB = ("Bob Roe", "bob@example.com")
BOT = ("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com")

STORE = '''"""Durable job store backed by SQLite."""

import sqlite3
import threading

SCHEMA_VERSION = 2


class StoreError(RuntimeError):
    pass


class JobStore:
    def __init__(self, path: str) -> None:
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    def _migrate(self) -> None:
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise StoreError(f"store written by a newer version ({version})")
        if version < 1:
            self._conn.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, payload TEXT, state TEXT)")
        if version < 2:
            self._conn.execute("ALTER TABLE jobs ADD COLUMN attempts INTEGER DEFAULT 0")
        self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._conn.commit()

    def claim(self) -> tuple[str, str] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, payload FROM jobs WHERE state = 'queued' ORDER BY rowid LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            self._conn.execute(
                "UPDATE jobs SET state = 'running', attempts = attempts + 1 WHERE id = ? AND state = 'queued'",
                (row[0],),
            )
            self._conn.commit()
            return row[0], row[1]

    def put(self, job_id: str, payload: str) -> None:
        with self._lock:
            self._conn.execute("INSERT INTO jobs (id, payload, state) VALUES (?, ?, 'queued')", (job_id, payload))
            self._conn.commit()
'''

WORKER = '''"""Worker loop with bounded retries."""

import time

from queuebox.store import JobStore

MAX_ATTEMPTS = 3


def run_once(store: JobStore, handler) -> bool:
    claimed = store.claim()
    if claimed is None:
        return False
    job_id, payload = claimed
    try:
        handler(payload)
    except Exception:
        time.sleep(0.1)
        raise
    return True
'''

TESTS = """from queuebox.store import JobStore


def test_put_then_claim(tmp_path):
    store = JobStore(str(tmp_path / "q.db"))
    store.put("a", "{}")
    assert store.claim() == ("a", "{}")


def test_claim_empty(tmp_path):
    store = JobStore(str(tmp_path / "q.db"))
    assert store.claim() is None


def test_worker_runs(tmp_path):
    store = JobStore(str(tmp_path / "q.db"))
    store.put("a", "{}")
    assert store.claim() is not None
"""

ADR = """# ADR 001: SQLite with WAL for the job store

Status: accepted

## Context
Jobs must survive process restarts; operators asked for zero external services.

## Decision
SQLite in WAL mode behind a process-wide lock. Postgres was rejected for v1 because it
adds an operational dependency the target deployments do not have.

## Consequences
Single-host only. Claiming is serialised by a lock, which caps throughput; revisit if
more than one worker process is needed.
"""

WEB = '''"""HTTP surface (owned by another contributor)."""

from http.server import BaseHTTPRequestHandler


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
'''

CI = """name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -e . pytest
      - run: pytest -q
"""


def git(*args: str, author: tuple[str, str] = ALICE, clock: int = 0) -> str:
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_NAME": author[0],
            "GIT_AUTHOR_EMAIL": author[1],
            "GIT_COMMITTER_NAME": author[0],
            "GIT_COMMITTER_EMAIL": author[1],
            "GIT_AUTHOR_DATE": f"{1_760_000_000 + clock * 86_400} +0000",
            "GIT_COMMITTER_DATE": f"{1_760_000_000 + clock * 86_400} +0000",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }
    )
    return subprocess.run(
        ["git", *args], cwd=REPO, env=env, check=True, capture_output=True, text=True
    ).stdout


def commit(
    day: int, files: dict[str, str], message: str, author: tuple[str, str] = ALICE
) -> None:
    for rel, text in files.items():
        target = REPO / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    git("add", "-A", author=author, clock=day)
    git("commit", "--quiet", "-m", message, author=author, clock=day)


def build_repo() -> None:
    shutil.rmtree(WORK, ignore_errors=True)
    REPO.mkdir(parents=True)
    git("init", "--quiet", "--initial-branch=main")
    commit(
        0,
        {
            "README.md": "# queuebox\n\nDurable single-host job queue.\n",
            "pyproject.toml": '[project]\nname = "queuebox"\n\n[project.scripts]\nqueuebox = "queuebox.worker:main"\n',
        },
        "init",
    )
    commit(
        1,
        {
            "src/queuebox/__init__.py": "",
            "src/queuebox/store.py": STORE.replace(
                "SCHEMA_VERSION = 2", "SCHEMA_VERSION = 1"
            ),
        },
        "feat(store): sqlite job store",
    )
    commit(3, {"docs/adr/001-sqlite-wal.md": ADR}, "docs: record storage decision")
    commit(5, {"src/queuebox/web.py": WEB}, "feat(web): health endpoint", BOB)
    commit(
        8,
        {"src/queuebox/store.py": STORE},
        "feat(store): versioned migrations and attempt counting",
    )
    commit(
        9,
        {"src/queuebox/worker.py": WORKER, "tests/test_store.py": TESTS},
        "feat(worker): run loop with tests",
    )
    commit(10, {".github/workflows/ci.yml": CI}, "ci: run tests on push")
    commit(12, {"uv.lock": "version = 1\n"}, "chore(deps): bump lock", BOT)
    git("remote", "add", "origin", "https://github.com/example-org/queuebox.git")


def engine(*args: str) -> dict[str, object]:
    proc = subprocess.run(
        [sys.executable, str(ENGINE), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    result: dict[str, object] = json.loads(proc.stdout)
    if proc.returncode != 0:
        raise SystemExit(f"engine {args[0]} failed: {json.dumps(result, indent=2)}")
    return result


def main() -> None:
    build_repo()
    engine(
        "discover",
        "--repo",
        str(REPO),
        "--candidate",
        "email:alice@example.com",
        "--display",
        "Alice Doe",
        "--offline",
        "--out",
        str(RUN),
        "--now",
        NOW,
    )
    run_id = json.loads((RUN / "forensics.json").read_text())["run_id"]
    judgments = json.loads((HERE / "judgments.json").read_text())
    judgments["run_id"] = run_id
    (RUN / "judgments.json").write_text(json.dumps(judgments, indent=2) + "\n")
    for item in judgments[
        "inspected"
    ]:  # read every inspected item the way an agent would, so coverage is audited
        target = (
            ["--path", item["path"]] if "path" in item else ["--commit", item["commit"]]
        )
        subprocess.run(
            [
                sys.executable,
                str(ENGINE),
                "show",
                "--run",
                str(RUN),
                "--repo",
                item["repo"],
                *target,
            ],
            capture_output=True,
            check=True,
        )
    engine("assess", "--run", str(RUN), "--now", NOW)
    out = HERE / "output"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir()
    for name in (
        "input.json",
        "sample-plan.md",
        "evidence.json",
        "assessment.json",
        "assessment.md",
        "assessment.html",
        "questions.md",
        "limitations.md",
    ):
        text = (
            (RUN / name)
            .read_text(encoding="utf-8")
            .replace(str(ENGINE), "<skill-dir>/scripts/appraise.py")
        )
        (out / name).write_text(text, encoding="utf-8")
    print(f"examples regenerated from {RUN}")


if __name__ == "__main__":
    main()
