"""Read-only Git inspection for the ship-workflow skill.

Every command is an argv-vector ``git`` subprocess with an explicit working
directory, a deadline, ``GIT_OPTIONAL_LOCKS=0`` and no repository-redirecting
environment. Inspection never fetches, prunes, locks or writes. Anything that
cannot be established raises :class:`GitError`; no method turns a failed or
unknown observation into an empty success.

Repository text (remote URLs, branch names, paths, command output) is data.
Remote URLs are stripped of credentials before they leave this module.
"""

from __future__ import annotations

import hashlib
import os
import re
import signal
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT = 60.0

_OID_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_HOST_RE = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?(?::[0-9]{1,5})?")
_SEGMENT_RE = re.compile(r"[A-Za-z0-9_.-]+")
_PORT_RE = re.compile(r"[0-9]{1,5}")
_SCHEME_URL_RE = re.compile(
    r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://(?P<authority>[^/?#]*)(?P<path>[^?#]*)(?:[?#].*)?",
    re.DOTALL,
)
_SCP_URL_RE = re.compile(
    r"(?:[^@/:]+@)?(?P<host>[^@/:]+):(?P<path>.*)",
    re.DOTALL,
)
_USERINFO_RE = re.compile(r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)[^\s'\"<>]*@")
_HTTP_DEFAULT_PORTS = {"http": "80", "https": "443"}
_SSH_SCHEMES = frozenset({"ssh", "git+ssh", "ssh+git"})
_WEB_SCHEMES = frozenset({"http", "https", "git"})

# Variables that would redirect Git away from the repository chosen by cwd.
_REDIRECTING_ENV = frozenset(
    {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_NAMESPACE",
        "GIT_PREFIX",
        "GIT_QUARANTINE_PATH",
        "GIT_CEILING_DIRECTORIES",
    }
)

_HASH_CHUNK = 1 << 20


class GitError(RuntimeError):
    """A Git observation failed or could not be established."""


@dataclass(frozen=True)
class Worktree:
    path: Path
    head: str
    branch: str | None
    locked: bool
    prunable: bool


@dataclass(frozen=True)
class Snapshot:
    """Local checkout identity.

    ``fingerprint`` covers HEAD, branch, staged content, unstaged/untracked
    content, in-progress operations and (credential-free) remotes. It does not
    cover other worktrees or untracked ignored files. ``conflicts`` and
    ``operations`` extend the shared contract with explicit unmerged paths and
    in-progress rebase/merge/cherry-pick/revert/am/bisect/sequencer state.
    """

    root: Path
    common_dir: Path
    head: str
    branch: str | None
    dirty: bool
    fingerprint: str
    remotes: dict[str, str]
    worktrees: tuple[Worktree, ...]
    conflicts: tuple[str, ...] = ()
    operations: tuple[str, ...] = ()


@dataclass(frozen=True)
class _StatusEntry:
    kind: str
    xy: str
    worktree_mode: str
    path: bytes

    @property
    def needs_worktree_content(self) -> bool:
        return self.kind in ("?", "u") or self.xy[1] != "."


@dataclass(frozen=True)
class _Observed:
    head: str
    branch: str | None
    status: bytes
    index_digest: str


def redact_credentials(text: str) -> str:
    """Remove ``user[:password]@`` from every URL-looking token in ``text``."""
    return _USERINFO_RE.sub(r"\g<scheme>", text)


def redact_url(url: str) -> str:
    """Return ``url`` without userinfo, query or fragment. Local paths pass through."""
    match = _SCHEME_URL_RE.fullmatch(url)
    if match is not None:
        host = match["authority"].rpartition("@")[2]
        return f"{match['scheme']}://{host}{match['path']}"
    scp = _SCP_URL_RE.fullmatch(url)
    if scp is not None:
        return f"{scp['host']}:{scp['path']}"
    return url


def parse_remote_identity(url: str) -> tuple[str, str] | None:
    """Return ``(host, owner/repo)`` for an https/http/git/ssh/scp-style URL.

    The host is lower-case; HTTP(S) keeps a non-default port, SSH drops its
    transport port, and ``ssh.github.com`` maps to ``github.com``. ``None`` means
    the URL does not name a two-segment repository on a host (local paths,
    ``file://``, nested groups, percent-encoding, IPv6 literals).
    """
    match = _SCHEME_URL_RE.fullmatch(url)
    if match is not None:
        scheme = match["scheme"].lower()
        if scheme not in _SSH_SCHEMES and scheme not in _WEB_SCHEMES:
            return None
        hostport = match["authority"].rpartition("@")[2]
        host, sep, port = hostport.partition(":")
        if sep and _PORT_RE.fullmatch(port) is None:
            return None
        host = host.lower()
        if (
            sep
            and scheme in _HTTP_DEFAULT_PORTS
            and port != _HTTP_DEFAULT_PORTS[scheme]
        ):
            host = f"{host}:{port}"
        path = match["path"]
    else:
        scp = _SCP_URL_RE.fullmatch(url)
        if scp is None:
            return None
        host = scp["host"].lower()
        path = scp["path"]
    if _HOST_RE.fullmatch(host) is None:
        return None
    if host == "ssh.github.com":
        host = "github.com"
    full_name = _repo_path(path)
    if full_name is None:
        return None
    return host, full_name


def _repo_path(path: str) -> str | None:
    trimmed = path.lstrip("/").rstrip("/")
    trimmed = trimmed.removesuffix(".git")
    segments = trimmed.split("/")
    if len(segments) != 2:
        return None
    for segment in segments:
        if segment in ("", ".", "..") or _SEGMENT_RE.fullmatch(segment) is None:
            return None
    return trimmed


def _normalize_identity(host: str, full_name: str) -> tuple[str, str]:
    if not isinstance(host, str) or _HOST_RE.fullmatch(host.lower()) is None:
        raise GitError("invalid repository host")
    if not isinstance(full_name, str) or _repo_path(full_name) != full_name:
        raise GitError("invalid repository full name; expected owner/repo")
    return host.lower(), full_name.lower()


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _git_env() -> dict[str, str]:
    env = {
        key: value for key, value in os.environ.items() if key not in _REDIRECTING_ENV
    }
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["LC_ALL"] = "C"
    return env


def _describe(args: tuple[str, ...]) -> str:
    return redact_credentials(" ".join(args[:3]))[:120]


def _path_from_output(raw: bytes) -> Path:
    """Decode one path printed by Git, removing only the terminating newline."""
    if not raw.endswith(b"\n"):
        raise GitError("unterminated path output from git")
    text = os.fsdecode(raw[:-1])
    if not text:
        raise GitError("git reported an empty path")
    return Path(text)


def _lstat_or_none(path: bytes) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as exc:
        raise GitError(f"cannot stat {os.fsdecode(path)!r}: {exc.strerror}") from exc


def _raise_walk_error(exc: OSError) -> None:
    raise GitError(
        f"cannot read {os.fsdecode(exc.filename or b'')!r}: {exc.strerror}"
    ) from exc


def _hash_file(path: bytes) -> str:
    digest = hashlib.sha256()
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as handle:
            while chunk := handle.read(_HASH_CHUNK):
                digest.update(chunk)
    except OSError as exc:
        raise GitError(f"cannot read {os.fsdecode(path)!r}: {exc.strerror}") from exc
    return digest.hexdigest()


def _leaf_identity(path: bytes) -> str:
    """Identity of one filesystem object: type, exec bit and content hash."""
    st = _lstat_or_none(path)
    if st is None:
        return "absent"
    if stat.S_ISLNK(st.st_mode):
        try:
            target = os.readlink(path)
        except OSError as exc:
            raise GitError(
                f"cannot read link {os.fsdecode(path)!r}: {exc.strerror}"
            ) from exc
        return "symlink:" + hashlib.sha256(target).hexdigest()
    if stat.S_ISREG(st.st_mode):
        executable = "x" if st.st_mode & 0o111 else "-"
        return f"file:{executable}:{_hash_file(path)}"
    if stat.S_ISDIR(st.st_mode):
        return "dir:" + _hash_directory(path)
    return f"special:{stat.S_IFMT(st.st_mode):o}"


def _hash_directory(top: bytes) -> str:
    """Hash a nested repository/submodule working tree, excluding its ``.git``."""
    digest = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(top, onerror=_raise_walk_error):
        if dirpath == top:
            dirnames[:] = [name for name in dirnames if name != b".git"]
            filenames[:] = [name for name in filenames if name != b".git"]
        dirnames.sort()
        leaves = sorted(
            filenames
            + [name for name in dirnames if os.path.islink(os.path.join(dirpath, name))]
        )
        for name in leaves:
            full = os.path.join(dirpath, name)
            relative = os.path.relpath(full, top)
            record = relative + b"\0" + _leaf_identity(full).encode("ascii") + b"\0"
            digest.update(len(record).to_bytes(8, "big") + record)
    return digest.hexdigest()


def _parse_status(raw: bytes) -> tuple[_StatusEntry, ...]:
    if raw and not raw.endswith(b"\0"):
        raise GitError("unterminated git status output")
    entries: list[_StatusEntry] = []
    for token in raw.split(b"\0")[:-1]:
        kind = token[:1]
        if kind == b"1":
            parts = token.split(b" ", 8)
            if len(parts) != 9:
                raise GitError("malformed ordinary status record")
            xy, worktree_mode, path = parts[1], parts[5], parts[8]
        elif kind == b"u":
            parts = token.split(b" ", 10)
            if len(parts) != 11:
                raise GitError("malformed unmerged status record")
            xy, worktree_mode, path = parts[1], parts[6], parts[10]
        elif kind == b"?":
            if token[:2] != b"? ":
                raise GitError("malformed untracked status record")
            xy, worktree_mode, path = b"??", b"", token[2:]
        else:
            raise GitError("unexpected git status record type")
        if len(xy) != 2 or not path:
            raise GitError("malformed git status record")
        entries.append(
            _StatusEntry(
                kind.decode("ascii"),
                xy.decode("ascii"),
                worktree_mode.decode("ascii"),
                path,
            )
        )
    return tuple(entries)


def _length_prefixed(value: bytes) -> bytes:
    return len(value).to_bytes(8, "big") + value


class GitRepository:
    """Read-only inspection of the repository containing ``path``."""

    def __init__(self, path: Path, *, timeout: float = DEFAULT_TIMEOUT) -> None:
        if not timeout > 0:
            raise GitError("git command deadline must be positive")
        self.path = Path(os.path.abspath(path))
        self.timeout = timeout

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
        """Run ``git *args`` in ``self.path`` with a deadline and no optional locks."""
        if not args:
            raise GitError("git requires arguments")
        for arg in args:
            if not isinstance(arg, str) or "\0" in arg:
                raise GitError("invalid git argument")
        argv = ["git", "-c", "core.fsmonitor=false", *args]
        try:
            process = subprocess.Popen(
                argv,
                cwd=self.path,
                env=_git_env(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            raise GitError(f"cannot run git in {self.path}: {exc.strerror}") from exc
        with process:
            try:
                stdout, stderr = process.communicate(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                _kill_process_group(process)
                process.communicate()
                raise GitError(
                    f"git {_describe(args)} exceeded its {self.timeout:g}s deadline"
                ) from None
            except BaseException:
                _kill_process_group(process)
                raise
        result = subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
        if check and result.returncode != 0:
            message = redact_credentials(stderr.decode("utf-8", "replace").strip())
            raise GitError(
                f"git {_describe(args)} failed (exit {result.returncode}): {message[:500]}"
            )
        return result

    # -- refs ---------------------------------------------------------------

    def resolve_ref(self, ref: str) -> str | None:
        """Commit OID for ``HEAD``, a full ``refs/...`` name or a full OID.

        ``None`` only means the ref/commit is absent (or HEAD is unborn). Invalid
        names, broken refs, non-commit targets and command failures raise.
        """
        if not isinstance(ref, str):
            raise GitError("ref must be a string")
        if ref == "HEAD":
            return self._resolve_head()
        if _OID_RE.fullmatch(ref):
            return self._peel_commit(ref)
        self._validate_full_ref(ref)
        oid = self._exact_ref_oid(ref)
        if oid is None:
            return None
        commit = self._peel_commit(oid)
        if commit is None:
            raise GitError(f"{ref} does not point at an available commit")
        return commit

    def is_ancestor(self, older: str, newer: str) -> bool:
        """True when ``older`` is an ancestor of (or equal to) ``newer``.

        Unknown revisions raise: absence is not evidence of non-ancestry.
        """
        resolved: list[str] = []
        for rev in (older, newer):
            oid = self.resolve_ref(rev)
            if oid is None:
                raise GitError(
                    f"cannot test ancestry: {rev!r} is not an available commit"
                )
            resolved.append(oid)
        result = self.run(
            "merge-base", "--is-ancestor", resolved[0], resolved[1], check=False
        )
        if result.returncode == 0:
            return True
        if result.returncode == 1:
            return False
        stderr = redact_credentials(result.stderr.decode("utf-8", "replace").strip())
        raise GitError(
            f"git merge-base --is-ancestor failed (exit {result.returncode}): {stderr[:500]}"
        )

    def _validate_full_ref(self, ref: str) -> None:
        if not ref.startswith("refs/"):
            raise GitError("ref must be HEAD, a full refs/ name or a full object id")
        result = self.run("check-ref-format", ref, check=False)
        if result.returncode == 1:
            raise GitError("invalid ref name")
        if result.returncode != 0:
            raise GitError(f"git check-ref-format failed (exit {result.returncode})")

    def _exact_ref_oid(self, ref: str) -> str | None:
        """Exact ref lookup; avoids rev-parse DWIM, which can match other refs."""
        result = self.run("for-each-ref", "--format=%(refname)%00%(objectname)", ref)
        found: str | None = None
        for line in result.stdout.split(b"\n"):
            if not line:
                continue
            name, _, oid = os.fsdecode(line).partition("\0")
            if name == ref:
                if _OID_RE.fullmatch(oid) is None:
                    raise GitError(f"{ref} has an invalid object id")
                found = oid
        if found is None and result.stderr.strip():
            stderr = redact_credentials(
                result.stderr.decode("utf-8", "replace").strip()
            )
            raise GitError(f"git could not read {ref}: {stderr[:500]}")
        return found

    def _peel_commit(self, oid: str) -> str | None:
        result = self.run(
            "rev-parse", "--verify", "--quiet", f"{oid}^{{commit}}", check=False
        )
        if result.returncode == 1:
            return None
        if result.returncode != 0:
            stderr = redact_credentials(
                result.stderr.decode("utf-8", "replace").strip()
            )
            raise GitError(
                f"git rev-parse failed (exit {result.returncode}): {stderr[:500]}"
            )
        commit = result.stdout.decode("ascii", "replace").strip()
        if _OID_RE.fullmatch(commit) is None:
            raise GitError("git returned an invalid commit id")
        return commit

    def _current_branch(self) -> str | None:
        """Short branch name, or ``None`` for a detached HEAD."""
        result = self.run("symbolic-ref", "--quiet", "HEAD", check=False)
        if result.returncode == 1:
            return None
        if result.returncode != 0:
            stderr = redact_credentials(
                result.stderr.decode("utf-8", "replace").strip()
            )
            raise GitError(
                f"git symbolic-ref failed (exit {result.returncode}): {stderr[:500]}"
            )
        ref = os.fsdecode(result.stdout).rstrip("\n")
        prefix = "refs/heads/"
        if not ref.startswith(prefix) or len(ref) == len(prefix):
            raise GitError("HEAD does not name a local branch")
        return ref[len(prefix) :]

    def _resolve_head(self) -> str | None:
        result = self.run(
            "rev-parse", "--verify", "--quiet", "HEAD^{commit}", check=False
        )
        if result.returncode == 0:
            commit = result.stdout.decode("ascii", "replace").strip()
            if _OID_RE.fullmatch(commit) is None:
                raise GitError("git returned an invalid commit id")
            return commit
        if result.returncode == 1:
            branch = self._current_branch()
            if (
                branch is not None
                and self._exact_ref_oid(f"refs/heads/{branch}") is None
            ):
                return None  # unborn branch
            raise GitError("HEAD does not point at an available commit")
        stderr = redact_credentials(result.stderr.decode("utf-8", "replace").strip())
        raise GitError(
            f"git rev-parse HEAD failed (exit {result.returncode}): {stderr[:500]}"
        )

    # -- remotes ------------------------------------------------------------

    def remote_for(self, host: str, full_name: str) -> str | None:
        """Name of the single remote whose fetch and push URLs all name ``host/full_name``.

        ``None`` when no remote names it. A remote whose URLs name different
        repositories, or several remotes naming the same repository, are
        ambiguous and raise instead of guessing.
        """
        wanted = _normalize_identity(host, full_name)
        matches: list[str] = []
        for name, (fetch_urls, push_urls) in self._remote_urls().items():
            identities = {
                _lower_identity(parse_remote_identity(url))
                for url in (*fetch_urls, *push_urls)
            }
            if wanted not in identities:
                continue
            if len(identities) != 1:
                raise GitError(f"remote {name!r} has URLs for different repositories")
            matches.append(name)
        if len(matches) > 1:
            raise GitError(
                f"remotes {sorted(matches)!r} all resolve to {wanted[0]}/{wanted[1]}"
            )
        return matches[0] if matches else None

    def _remote_urls(self) -> dict[str, tuple[tuple[str, ...], tuple[str, ...]]]:
        names = [
            os.fsdecode(line) for line in self.run("remote").stdout.split(b"\n") if line
        ]
        urls: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
        for name in names:
            fetch = self._url_list("remote", "get-url", "--all", "--", name)
            push = self._url_list("remote", "get-url", "--push", "--all", "--", name)
            urls[name] = (fetch, push)
        return urls

    def _url_list(self, *args: str) -> tuple[str, ...]:
        lines = tuple(
            os.fsdecode(line) for line in self.run(*args).stdout.split(b"\n") if line
        )
        if not lines:
            raise GitError("git remote reported no URL")
        return lines

    def _redacted_remotes(self) -> dict[str, str]:
        return {
            name: redact_url(fetch[0])
            for name, (fetch, _push) in self._remote_urls().items()
        }

    # -- worktrees ----------------------------------------------------------

    def _worktrees(self) -> tuple[Worktree, ...]:
        raw = self.run("worktree", "list", "--porcelain", "-z").stdout
        records: list[list[bytes]] = []
        current: list[bytes] = []
        for token in raw.split(b"\0"):
            if token:
                current.append(token)
            elif current:
                records.append(current)
                current = []
        if current:
            records.append(current)
        worktrees: list[Worktree] = []
        for record in records:
            worktree = _parse_worktree(record)
            if worktree is not None:
                worktrees.append(worktree)
        if not worktrees:
            raise GitError("git reported no worktrees")
        return tuple(worktrees)

    # -- snapshot -----------------------------------------------------------

    def snapshot(self) -> Snapshot:
        """Observe the checkout without modifying the repository."""
        root = _path_from_output(self.run("rev-parse", "--show-toplevel").stdout)
        common_dir = _path_from_output(
            self.run("rev-parse", "--path-format=absolute", "--git-common-dir").stdout
        )
        git_dir = _path_from_output(self.run("rev-parse", "--absolute-git-dir").stdout)
        top = GitRepository(root, timeout=self.timeout)

        first = top._observe()
        entries = _parse_status(first.status)
        content = top._worktree_content(root, entries)
        second = top._observe()
        if first != second:
            raise GitError("repository changed while it was being inspected")

        operations = _operations(git_dir)
        remotes = top._redacted_remotes()
        conflicts = tuple(sorted(os.fsdecode(e.path) for e in entries if e.kind == "u"))

        digest = hashlib.sha256()
        parts: list[bytes] = [
            b"ship-workflow-snapshot-v1",
            first.head.encode("ascii"),
            b"detached"
            if first.branch is None
            else b"branch:" + os.fsencode(first.branch),
            first.index_digest.encode("ascii"),
            first.status,
        ]
        for path, identity in content:
            parts.append(path + b"\0" + identity.encode("ascii"))
        parts.extend(b"op:" + op.encode("ascii") for op in operations)
        for name in sorted(remotes):
            parts.append(
                b"remote:" + os.fsencode(name) + b"\0" + os.fsencode(remotes[name])
            )
        for part in parts:
            digest.update(_length_prefixed(part))

        return Snapshot(
            root=root,
            common_dir=common_dir,
            head=first.head,
            branch=first.branch,
            dirty=bool(entries),
            fingerprint=digest.hexdigest(),
            remotes=remotes,
            worktrees=top._worktrees(),
            conflicts=conflicts,
            operations=operations,
        )

    def _observe(self) -> _Observed:
        head = self.resolve_ref("HEAD")
        if head is None:
            raise GitError("HEAD is unborn; there is no commit to inspect")
        status = self.run(
            "status",
            "--porcelain=v2",
            "-z",
            "--untracked-files=all",
            "--ignored=no",
            "--no-renames",
            "--ignore-submodules=none",
        ).stdout
        index = self.run("ls-files", "--stage", "-z").stdout
        return _Observed(
            head=head,
            branch=self._current_branch(),
            status=status,
            index_digest=hashlib.sha256(index).hexdigest(),
        )

    def _worktree_content(
        self, root: Path, entries: tuple[_StatusEntry, ...]
    ) -> list[tuple[bytes, str]]:
        """Content identity of every changed/untracked path; hashes only, no bytes."""
        root_bytes = os.fsencode(root)
        content: list[tuple[bytes, str]] = []
        for entry in sorted(entries, key=lambda e: e.path):
            if not entry.needs_worktree_content:
                continue
            full = os.path.join(root_bytes, entry.path.rstrip(b"/"))
            identity = _leaf_identity(full)
            if (
                entry.worktree_mode == "160000"
                and _lstat_or_none(os.path.join(full, b".git")) is not None
            ):
                sub = GitRepository(Path(os.fsdecode(full)), timeout=self.timeout)
                sub_head = (
                    sub.run("rev-parse", "--verify", "HEAD")
                    .stdout.decode("ascii", "replace")
                    .strip()
                )
                identity = f"{identity}+head:{sub_head}"
            content.append((entry.path, identity))
        return content


def _lower_identity(identity: tuple[str, str] | None) -> tuple[str, str] | None:
    return None if identity is None else (identity[0], identity[1].lower())


def _parse_worktree(record: list[bytes]) -> Worktree | None:
    first = record[0]
    if not first.startswith(b"worktree "):
        raise GitError("malformed worktree record")
    path = Path(os.fsdecode(first[len(b"worktree ") :]))
    head: str | None = None
    branch: str | None = None
    detached = bare = locked = prunable = False
    for attribute in record[1:]:
        if attribute.startswith(b"HEAD "):
            head = attribute[len(b"HEAD ") :].decode("ascii", "replace")
        elif attribute.startswith(b"branch "):
            ref = os.fsdecode(attribute[len(b"branch ") :])
            if not ref.startswith("refs/heads/"):
                raise GitError("worktree branch is not a local branch")
            branch = ref[len("refs/heads/") :]
        elif attribute == b"detached":
            detached = True
        elif attribute == b"bare":
            bare = True
        elif attribute == b"locked" or attribute.startswith(b"locked "):
            locked = True
        elif attribute == b"prunable" or attribute.startswith(b"prunable "):
            prunable = True
    if bare:
        return None  # a bare repository has no checkout to inventory
    if head is None or _OID_RE.fullmatch(head) is None:
        raise GitError("worktree record has no valid HEAD")
    if branch is None and not detached:
        raise GitError("worktree record is neither on a branch nor detached")
    return Worktree(
        path=path, head=head, branch=branch, locked=locked, prunable=prunable
    )


def _operations(git_dir: Path) -> tuple[str, ...]:
    base = os.fsencode(git_dir)

    def present(name: bytes) -> bool:
        return _lstat_or_none(os.path.join(base, name)) is not None

    found: set[str] = set()
    if present(b"rebase-merge"):
        found.add("rebase")
    if present(b"rebase-apply"):
        found.add("am" if present(b"rebase-apply/applying") else "rebase")
    for marker, name in (
        (b"MERGE_HEAD", "merge"),
        (b"CHERRY_PICK_HEAD", "cherry-pick"),
        (b"REVERT_HEAD", "revert"),
        (b"BISECT_LOG", "bisect"),
        (b"sequencer", "sequencer"),
    ):
        if present(marker):
            found.add(name)
    return tuple(sorted(found))
