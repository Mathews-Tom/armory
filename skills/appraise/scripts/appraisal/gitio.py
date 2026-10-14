"""Read-only Git access through a private bare mirror.

Candidate repositories are never analysed in place. `Mirror.create` initialises
a bare repository inside the run directory and populates it with `git fetch`
from the source, which only runs upload-pack on the source side. The only
commands executed inside a local checkout are `rev-parse`, `config --get` and
`--no-optional-locks status`, none of which write.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

_BASE_CONFIG = (
    "-c",
    "core.quotepath=off",
    "-c",
    "color.ui=never",
    "-c",
    "log.showSignature=false",
    "-c",
    "blame.ignoreRevsFile=",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "diff.renames=false",
)


class GitError(RuntimeError):
    def __init__(self, args: Sequence[str], returncode: int, stderr: str) -> None:
        self.args_list = list(args)
        self.returncode = returncode
        self.stderr = stderr.strip()
        super().__init__(
            f"git {' '.join(list(args)[:3])} failed ({returncode}): {self.stderr[:400]}"
        )


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
        }
    )
    return env


def _cmd(git_dir: Path | None, args: Sequence[str]) -> list[str]:
    cmd = ["git", *_BASE_CONFIG]
    if git_dir is not None:
        cmd += ["--git-dir", str(git_dir)]
    return cmd + list(args)


def run_git(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    git_dir: Path | None = None,
    timeout: float = 600,
) -> str:
    proc = subprocess.run(
        _cmd(git_dir, args),
        cwd=str(cwd) if cwd else None,
        env=_env(),
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise GitError(
            list(args), proc.returncode, proc.stderr.decode("utf-8", "replace")
        )
    return proc.stdout.decode("utf-8", "replace")


@dataclass(frozen=True)
class LocalSource:
    """Facts read from a local checkout without writing to it."""

    top_level: Path
    is_bare: bool
    dirty: bool | None
    origin_url: str | None


def inspect_local(path: Path) -> LocalSource:
    is_bare = run_git(["rev-parse", "--is-bare-repository"], cwd=path).strip() == "true"
    dirty: bool | None
    if is_bare:
        top = Path(run_git(["rev-parse", "--absolute-git-dir"], cwd=path).strip())
        dirty = None
    else:
        top = Path(run_git(["rev-parse", "--show-toplevel"], cwd=path).strip())
        status = run_git(
            ["--no-optional-locks", "status", "--porcelain=v1", "--untracked-files=no"],
            cwd=top,
        )
        dirty = bool(status.strip())
    try:
        origin = (
            run_git(["config", "--get", "remote.origin.url"], cwd=top).strip() or None
        )
    except GitError:
        origin = None
    return LocalSource(top_level=top, is_bare=is_bare, dirty=dirty, origin_url=origin)


class Mirror:
    """A private bare repository holding fetched candidate and upstream history."""

    CANDIDATE_HEAD = "refs/appraise/head"
    UPSTREAM_PREFIX = "refs/appraise/upstream"
    REMOTES_PREFIX = "refs/appraise/remotes"

    def __init__(self, git_dir: Path) -> None:
        self.git_dir = git_dir

    @classmethod
    def create(cls, git_dir: Path) -> Mirror:
        git_dir.parent.mkdir(parents=True, exist_ok=True)
        if not (git_dir / "HEAD").exists():
            run_git(["init", "--bare", "--quiet", str(git_dir)])
        return cls(git_dir)

    def git(self, *args: str, timeout: float = 600) -> str:
        return run_git(list(args), git_dir=self.git_dir, timeout=timeout)

    def _fetch(self, source: str, *refspecs: str) -> None:
        self.git(
            "fetch",
            "--quiet",
            "--no-tags",
            "--update-shallow",
            "--force",
            source,
            *refspecs,
            timeout=3600,
        )

    def fetch_source(self, source: str) -> None:
        """Fetch HEAD, branches and tags; for local sources also remote-tracking refs."""
        self._fetch(
            source,
            f"+HEAD:{self.CANDIDATE_HEAD}",
            "+refs/heads/*:refs/appraise/heads/*",
            "+refs/tags/*:refs/appraise/tags/*",
        )
        try:
            self._fetch(source, f"+refs/remotes/*:{self.REMOTES_PREFIX}/*")
        except GitError:
            pass  # remote hosts do not advertise refs/remotes; absence is expected

    def fetch_upstream(self, source: str) -> None:
        self._fetch(
            source,
            f"+HEAD:{self.UPSTREAM_PREFIX}/head",
            f"+refs/heads/*:{self.UPSTREAM_PREFIX}/heads/*",
        )

    def resolve(self, rev: str) -> str | None:
        try:
            return (
                self.git(
                    "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"
                ).strip()
                or None
            )
        except GitError:
            return None

    def refs(self, prefix: str) -> list[str]:
        out = self.git("for-each-ref", "--format=%(refname)", prefix)
        return [line for line in out.splitlines() if line]

    def is_shallow(self) -> bool:
        shallow = self.git_dir / "shallow"
        return shallow.exists() and shallow.stat().st_size > 0

    def shallow_commits(self) -> set[str]:
        """Graft points of a shallow mirror: their content predates the visible history."""
        shallow = self.git_dir / "shallow"
        if not shallow.exists():
            return set()
        return {
            line.strip() for line in shallow.read_text().splitlines() if line.strip()
        }

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        try:
            self.git("merge-base", "--is-ancestor", ancestor, descendant)
        except GitError:
            return False
        return True

    def read_blob(self, rev: str, path: str) -> bytes | None:
        proc = subprocess.run(
            _cmd(self.git_dir, ["cat-file", "blob", f"{rev}:{path}"]),
            env=_env(),
            capture_output=True,
            check=False,
        )
        return proc.stdout if proc.returncode == 0 else None

    def read_blobs(self, object_ids: Sequence[str]) -> Iterator[tuple[str, bytes]]:
        """Stream blob contents for object ids through one `cat-file --batch` process."""
        if not object_ids:
            return
        proc = subprocess.Popen(
            _cmd(self.git_dir, ["cat-file", "--batch"]),
            env=_env(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if proc.stdin is None or proc.stdout is None:
            raise RuntimeError("cat-file pipes unavailable")
        try:
            for oid in object_ids:
                proc.stdin.write(f"{oid}\n".encode())
                proc.stdin.flush()
                header = proc.stdout.readline().decode().split()
                if len(header) < 3 or header[1] == "missing":
                    continue
                data = proc.stdout.read(int(header[2]))
                proc.stdout.read(1)
                yield oid, data
        finally:
            proc.stdin.close()
            proc.wait(timeout=120)

    def ls_tree(self, rev: str) -> list[tuple[str, str, int]]:
        """Return (path, blob_id, size) for regular files at rev."""
        out = self.git("ls-tree", "-r", "-l", "-z", "--full-tree", rev)
        entries: list[tuple[str, str, int]] = []
        for record in out.split("\0"):
            if not record:
                continue
            meta, path = record.split("\t", 1)
            mode, kind, oid, size = meta.split()
            if kind != "blob" or mode in {"120000", "160000"}:
                continue
            entries.append((path, oid, int(size) if size.isdigit() else 0))
        return entries
