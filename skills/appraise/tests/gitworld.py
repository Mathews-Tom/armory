"""Deterministic synthetic Git repositories for tests."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

ALICE = ("Alice Doe", "alice@example.com")
BOB = ("Bob Roe", "bob@example.com")
CAROL = ("Carol Poe", "carol@example.com")
ALICE_ALT = ("Alice Doe", "alice@personal.example")
BOT = ("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com")

SOURCE = """\
\"\"\"Queue service.\"\"\"

import sqlite3
import threading


class Store:
    def __init__(self, path):
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(path)

    def put(self, key, value):
        with self.lock:
            self.conn.execute("INSERT INTO kv VALUES (?, ?)", (key, value))
            self.conn.commit()

    def get(self, key):
        try:
            row = self.conn.execute("SELECT v FROM kv WHERE k = ?", (key,)).fetchone()
        except sqlite3.Error as exc:
            raise KeyError(key) from exc
        return row[0] if row else None
"""


def body(name: str, lines: int = 30) -> str:
    return (
        "\n".join(
            [f'"""{name}."""', ""]
            + [f"def f_{name}_{i}(x):\n    return x + {i}\n" for i in range(lines // 3)]
        )
        + "\n"
    )


@dataclass
class Repo:
    path: Path
    clock: int = 1_700_000_000

    @classmethod
    def init(cls, path: Path) -> Repo:
        path.mkdir(parents=True, exist_ok=True)
        repo = cls(path)
        repo.git("init", "--quiet", "--initial-branch=main")
        return repo

    def git(
        self, *args: str, author: tuple[str, str] = ALICE, check: bool = True
    ) -> str:
        env = dict(os.environ)
        env.update(
            {
                "GIT_AUTHOR_NAME": author[0],
                "GIT_AUTHOR_EMAIL": author[1],
                "GIT_COMMITTER_NAME": author[0],
                "GIT_COMMITTER_EMAIL": author[1],
                "GIT_AUTHOR_DATE": f"{self.clock} +0000",
                "GIT_COMMITTER_DATE": f"{self.clock} +0000",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
            }
        )
        proc = subprocess.run(
            ["git", *args],
            cwd=self.path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if check and proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {proc.stderr}")
        return proc.stdout

    def commit(
        self,
        files: Mapping[str, str | None],
        message: str,
        author: tuple[str, str] = ALICE,
        trailers: list[str] | None = None,
    ) -> str:
        self.clock += 3600
        for rel, content in files.items():
            target = self.path / rel
            if content is None:
                target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        self.git("add", "-A")
        msg = message + ("\n\n" + "\n".join(trailers) if trailers else "")
        self.git("commit", "--quiet", "--allow-empty", "-m", msg, author=author)
        return self.git("rev-parse", "HEAD").strip()

    def head(self) -> str:
        return self.git("rev-parse", "HEAD").strip()


def clone(src: Path, dst: Path, *extra: str) -> Repo:
    subprocess.run(
        ["git", "clone", "--quiet", *extra, f"file://{src}", str(dst)],
        check=True,
        capture_output=True,
    )
    repo = Repo(dst)
    repo.clock = 1_800_000_000
    return repo


def solo_project(path: Path, author: tuple[str, str] = ALICE) -> Repo:
    repo = Repo.init(path)
    repo.commit(
        {
            "README.md": "# queue\n\nA small queue service.\n",
            "pyproject.toml": '[project]\nname = "queue"\n\n[project.scripts]\nqueue = "queue.cli:main"\n',
        },
        "init",
        author,
    )
    repo.commit(
        {"src/queue/store.py": SOURCE, "src/queue/__init__.py": ""},
        "feat: add sqlite store",
        author,
    )
    repo.commit({"src/queue/cli.py": body("cli", 24)}, "feat: add cli", author)
    repo.commit(
        {"tests/test_store.py": body("test_store", 18)}, "test: cover store", author
    )
    repo.commit(
        {
            "src/queue/store.py": SOURCE.replace(
                "return row[0] if row else None",
                "return None if row is None else row[0]",
            )
        },
        "fix: handle missing row",
        author,
    )
    repo.commit(
        {
            ".github/workflows/ci.yml": "name: ci\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n"
        },
        "ci: run tests",
        author,
    )
    repo.commit(
        {
            "docs/design/adr-001-storage.md": "# ADR 001: SQLite storage\n\nChosen over files for atomic writes.\n"
        },
        "docs: storage decision",
        author,
    )
    return repo
