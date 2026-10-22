"""Git inspection and guarded mutation primitives for the ship-workflow skill.

Every command is an argv-vector ``git`` subprocess with an explicit working
directory, a deadline, ``GIT_OPTIONAL_LOCKS=0`` and no repository-redirecting
environment. Inspection never fetches, prunes, locks or writes;
:meth:`GitRepository.preview_three_way` copies three commits out through
``git upload-pack`` into a private temporary repository and writes nothing
here. Anything that cannot be established raises :class:`GitError`; no method
turns a failed or unknown observation into an empty success.

The mutation helpers (:meth:`GitRepository.fetch_base`,
:meth:`~GitRepository.fetch_commit`,
:meth:`~GitRepository.prepare_base_checkout`,
:meth:`~GitRepository.delete_local_head`,
:meth:`~GitRepository.delete_remote_head`,
:meth:`~GitRepository.push_head`,
:meth:`~GitRepository.push_rewrite`,
:meth:`~GitRepository.advance_local_branch` and
:meth:`~GitRepository.remove_worktree`) change exactly the one named target.
Each re-observes the live state first and rejects with :class:`GitRefused`,
before changing anything, when a safety precondition does not hold. They never
force, never use ``--force``/raw deletion/blanket prune, never disable hooks and
never retry. A failure after a command was dispatched whose outcome is unknown
carries ``uncertain=True``; the caller must reobserve instead of repeating it.

Repository text (remote URLs, branch names, paths, command output) is data.
Remote URLs are stripped of credentials before they leave this module.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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
        "GIT_CONFIG",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_NAMESPACE",
        "GIT_PREFIX",
        "GIT_QUARANTINE_PATH",
        "GIT_CEILING_DIRECTORIES",
        "GIT_DIFF_OPTS",
    }
)

# Config keys that, supplied through the environment, would let a caller (or a
# parent Git process) select a different checkout or pull in a foreign file.
_REDIRECTING_CONFIG_KEYS = frozenset({"core.worktree", "core.bare", "include.path"})
_MAX_CONFIG_ENV_ENTRIES = 4096

_HASH_CHUNK = 1 << 20

# An author/committer identity as ``git fsck`` accepts it: a non-empty name, an
# email, a date without zero padding or overflow, and a zone.
_IDENT_RE = re.compile(rb"[^<>\n\0]+ <[^<>\n\0]*> (?:0|[1-9][0-9]{0,17}) [+-][0-9]{4}")
# A replay cannot sign; a slice commit carrying one of these is refused.
_SIGNATURE_HEADERS = frozenset({b"gpgsig", b"gpgsig-sha256"})
# The only headers a replayed commit is written with.
_REPLAYED_HEADERS = frozenset(
    {b"tree", b"parent", b"author", b"committer", b"encoding"}
)
# A slice with more commits than this is refused before anything is replayed.
_MAX_SLICE_COMMITS = 256
_OBJECT_FORMATS = frozenset({"sha1", "sha256"})
_REPLAY_REFLOG = "ship-workflow: advance to the promoted head"


class GitError(RuntimeError):
    """A Git observation or mutation failed or could not be established.

    ``uncertain`` is true only when a mutating command may have been dispatched
    and its outcome is unknown (deadline, or the post-condition did not hold).
    The caller must reobserve the actual state and never repeat the mutation.
    """

    def __init__(self, message: str, *, uncertain: bool = False) -> None:
        super().__init__(message)
        self.uncertain = uncertain


class GitRefused(GitError):
    """A safety precondition rejected a mutation before anything was changed."""


@dataclass(frozen=True)
class Activity:
    """Whether any observable process is using a worktree.

    ``ACTIVE`` is a proven conflict and always wins. ``INACTIVE`` means the
    working-directory inventory is complete. Open files or editor buffers are
    not inventoried. ``UNKNOWN`` is never treated as inactive.
    """

    status: Literal["ACTIVE", "INACTIVE", "UNKNOWN"]
    reason: str


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
class SliceCommit:
    """One commit of a child's own slice, exactly as its raw object records it.

    ``author`` is the complete author header value (``Name <email> epoch tz``)
    and ``encoding`` the ``encoding`` header value, ``None`` when absent; a
    replay writes both back byte-for-byte. ``message`` is every byte after the
    header block, trailers and (missing) trailing newline included.
    """

    oid: str
    parent: str
    tree: str
    author: bytes
    encoding: bytes | None
    message: bytes


@dataclass(frozen=True)
class Promotion:
    """Proof that a child's own slice was replayed onto its parent's landing.

    ``fork`` is the old parent head the slice sat on, ``old_head`` the child head
    before the rewrite and ``landing`` the trunk tip it was replayed onto.
    ``expected_tree`` is the clean three-way merge ``base=fork, ours=landing,
    theirs=old_head``; ``new_head`` has exactly that tree, has ``landing`` as an
    ancestor and holds ``commits`` linear commits with the original authors and
    messages. ``slice_identity`` is the net delta identity of ``fork..old_head``
    (see :meth:`GitRepository.whole_change_landed`); ``None`` only for a
    net-empty slice, which :meth:`GitRepository.promote_slice` refuses.
    """

    fork: str
    old_head: str
    landing: str
    expected_tree: str
    new_head: str
    commits: int
    slice_identity: str | None


@dataclass(frozen=True)
class _CommitRecord:
    """The parts of a raw commit a replay preserves, and what it cannot.

    ``signatures`` names the signature headers present; ``unsupported`` every
    other header that is not written back, and any header (other than a
    signature) continued over several lines.
    """

    tree: str
    parents: tuple[str, ...]
    author: bytes
    encoding: bytes | None
    message: bytes
    signatures: tuple[str, ...]
    unsupported: tuple[str, ...]


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


def _redirecting_config_key(key: str) -> bool:
    name = key.lower()
    if name in _REDIRECTING_CONFIG_KEYS:
        return True
    return name.startswith("includeif.") and name.endswith(".path")


def _strip_redirecting_config(env: dict[str, str]) -> None:
    """Drop repository-redirecting keys from the environment-supplied config.

    Covers ``GIT_CONFIG_PARAMETERS`` (what ``git -c`` exports to child processes)
    and ``GIT_CONFIG_COUNT``/``GIT_CONFIG_KEY_n``/``GIT_CONFIG_VALUE_n``. Every
    other entry (credential helpers, URL rewrites, ...) is left exactly as it was;
    an environment that cannot be parsed is rejected rather than guessed at.
    """
    parameters = env.get("GIT_CONFIG_PARAMETERS")
    if parameters is not None:
        try:
            entries = shlex.split(parameters)
        except ValueError:
            raise GitError("GIT_CONFIG_PARAMETERS is malformed") from None
        kept = [
            entry
            for entry in entries
            if not _redirecting_config_key(entry.partition("=")[0])
        ]
        if len(kept) != len(entries):
            if kept:
                env["GIT_CONFIG_PARAMETERS"] = " ".join(shlex.quote(e) for e in kept)
            else:
                del env["GIT_CONFIG_PARAMETERS"]
    raw_count = env.get("GIT_CONFIG_COUNT")
    if raw_count is None:
        return
    if not (raw_count.isascii() and raw_count.isdigit()):
        raise GitError("GIT_CONFIG_COUNT is not a count")
    count = int(raw_count)
    if count > _MAX_CONFIG_ENV_ENTRIES:
        raise GitError("GIT_CONFIG_COUNT is implausibly large")
    pairs: list[tuple[str, str]] = []
    for index in range(count):
        key = env.get(f"GIT_CONFIG_KEY_{index}")
        value = env.get(f"GIT_CONFIG_VALUE_{index}")
        if key is None or value is None:
            raise GitError(f"GIT_CONFIG_COUNT names the missing entry {index}")
        pairs.append((key, value))
    kept_pairs = [pair for pair in pairs if not _redirecting_config_key(pair[0])]
    if len(kept_pairs) == len(pairs):
        return
    for index in range(count):
        del env[f"GIT_CONFIG_KEY_{index}"]
        del env[f"GIT_CONFIG_VALUE_{index}"]
    if not kept_pairs:
        del env["GIT_CONFIG_COUNT"]
        return
    env["GIT_CONFIG_COUNT"] = str(len(kept_pairs))
    for index, (key, value) in enumerate(kept_pairs):
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value


def _git_env() -> dict[str, str]:
    env = {
        key: value for key, value in os.environ.items() if key not in _REDIRECTING_ENV
    }
    _strip_redirecting_config(env)
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


def _parse_commit(oid: str, raw: bytes) -> _CommitRecord:
    """Split one raw commit object into the headers a replay needs and its message.

    A continuation line (leading space) belongs to the header before it; only a
    signature is expected to continue. The message is every byte after the
    first blank line, unchanged.
    """
    end = raw.find(b"\n\n")
    if end < 0:
        raise GitError(f"commit {oid} has no header terminator")
    values: dict[bytes, list[bytes]] = {}
    continued: set[bytes] = set()
    name = b""
    for line in raw[:end].split(b"\n"):
        if line.startswith(b" "):
            if not name:
                raise GitError(f"commit {oid} starts with a continuation line")
            continued.add(name)
            continue
        name, sep, value = line.partition(b" ")
        if not sep or not name:
            raise GitError(f"commit {oid} has a malformed header line")
        values.setdefault(name, []).append(value)
    trees = values.get(b"tree", [])
    authors = values.get(b"author", [])
    committers = values.get(b"committer", [])
    encodings = values.get(b"encoding", [])
    if len(trees) != 1 or len(authors) != 1 or len(committers) != 1:
        raise GitError(f"commit {oid} lacks exactly one tree, author and committer")
    if len(encodings) > 1:
        raise GitError(f"commit {oid} has more than one encoding header")
    tree = trees[0].decode("ascii", "replace")
    parents = tuple(p.decode("ascii", "replace") for p in values.get(b"parent", []))
    for identity in (tree, *parents):
        if _OID_RE.fullmatch(identity) is None:
            raise GitError(f"commit {oid} names an invalid object id")
    signatures = sorted(
        header.decode("ascii") for header in values if header in _SIGNATURE_HEADERS
    )
    unsupported = {
        header.decode("ascii", "replace")
        for header in values
        if header not in _REPLAYED_HEADERS and header not in _SIGNATURE_HEADERS
    }
    unsupported.update(
        f"{header.decode('ascii', 'replace')} (multi-line)"
        for header in continued
        if header not in _SIGNATURE_HEADERS
    )
    return _CommitRecord(
        tree=tree,
        parents=parents,
        author=authors[0],
        encoding=encodings[0] if encodings else None,
        message=raw[end + 2 :],
        signatures=tuple(signatures),
        unsupported=tuple(sorted(unsupported)),
    )


class GitRepository:
    """Inspection and guarded mutation of the repository containing ``path``."""

    def __init__(self, path: Path, *, timeout: float = DEFAULT_TIMEOUT) -> None:
        if not timeout > 0:
            raise GitError("git command deadline must be positive")
        self.path = Path(os.path.abspath(path))
        self.timeout = timeout

    def run(
        self,
        *args: str,
        check: bool = True,
        input_bytes: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        """Run ``git *args`` in ``self.path`` with a deadline and no optional locks.

        ``input_bytes`` is written to the command's standard input; otherwise stdin
        is closed. A deadline raises an ``uncertain`` :class:`GitError`.
        """
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
                stdin=subprocess.DEVNULL if input_bytes is None else subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            raise GitError(f"cannot run git in {self.path}: {exc.strerror}") from exc
        with process:
            try:
                stdout, stderr = process.communicate(
                    input=input_bytes, timeout=self.timeout
                )
            except subprocess.TimeoutExpired:
                _kill_process_group(process)
                process.communicate()
                raise GitError(
                    f"git {_describe(args)} exceeded its {self.timeout:g}s deadline",
                    uncertain=True,
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

    def execution_environment(self) -> dict[str, str]:
        """A fresh copy of the exact environment every Git command here runs under.

        It is the caller's environment minus the variables that would redirect Git
        away from the repository chosen by the working directory, with prompts and
        optional locks disabled. It can hold the caller's credentials: use it to
        launch subprocesses, never to record or print.
        """
        return _git_env()

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
        _verify_selected_checkout(self.path, root, common_dir, git_dir)
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

    # -- branch inventories -------------------------------------------------

    def local_heads(self) -> dict[str, str]:
        """Every local branch as ``{"refs/heads/<name>": commit_oid}``.

        The inventory is exact or it raises: a broken ref, a branch that does not
        name a commit, a malformed record or a duplicate is never skipped.
        """
        result = self.run(
            "for-each-ref",
            "--format=%(refname)%00%(objectname)%00%(objecttype)",
            "refs/heads/",
        )
        if result.stderr.strip():
            stderr = redact_credentials(
                result.stderr.decode("utf-8", "replace").strip()
            )
            raise GitError(f"git could not read every local branch: {stderr[:500]}")
        heads: dict[str, str] = {}
        for line in result.stdout.split(b"\n"):
            if not line:
                continue
            fields = os.fsdecode(line).split("\0")
            if len(fields) != 3:
                raise GitError("malformed local branch record from git")
            name, oid, kind = fields
            _check_head_name(name)
            if _OID_RE.fullmatch(oid) is None or kind != "commit":
                raise GitError(f"{name} does not name a commit")
            if name in heads:
                raise GitError(f"{name} is listed more than once")
            heads[name] = oid
        return heads

    def remote_heads(self, remote: str) -> dict[str, str]:
        """Branches ``remote`` advertises as ``{"refs/heads/<name>": oid}``.

        Reads the network, bounded by the command deadline. An unreachable remote,
        a malformed or a duplicated advertisement raises; an empty mapping means
        the remote answered and has no branches.
        """
        return self._advertised_heads(self._require_remote(remote))

    def _advertised_heads(self, remote: str, *patterns: str) -> dict[str, str]:
        raw = self.run("ls-remote", "--heads", "--", remote, *patterns).stdout
        if raw and not raw.endswith(b"\n"):
            raise GitError("unterminated ls-remote output")
        heads: dict[str, str] = {}
        for line in raw.split(b"\n")[:-1]:
            oid_raw, tab, name_raw = line.partition(b"\t")
            oid = oid_raw.decode("ascii", "replace")
            if not tab or b"\t" in name_raw or _OID_RE.fullmatch(oid) is None:
                raise GitError("malformed ls-remote record")
            name = os.fsdecode(name_raw)
            _check_head_name(name)
            if name in heads:
                raise GitError(f"the remote advertises {name} more than once")
            heads[name] = oid
        return heads

    def _remote_default_ref(self, remote: str) -> str | None:
        """The full ref the remote's ``HEAD`` points at, when it reports one."""
        raw = self.run("ls-remote", "--symref", "--", remote, "HEAD").stdout
        for line in raw.split(b"\n"):
            if line.startswith(b"ref: "):
                target, tab, what = line[len(b"ref: ") :].partition(b"\t")
                if tab and what == b"HEAD":
                    return os.fsdecode(target)
        return None

    def _require_remote(self, remote: str) -> str:
        """``remote`` must be the exact name of a configured remote, never a URL."""
        if (
            not isinstance(remote, str)
            or not remote
            or remote.startswith("-")
            or "\0" in remote
        ):
            raise GitRefused("remote must be the name of a configured remote")
        names = {
            os.fsdecode(line) for line in self.run("remote").stdout.split(b"\n") if line
        }
        if remote not in names:
            raise GitRefused(f"{remote!r} is not a configured remote")
        return remote

    def _validated_branch(self, branch: str) -> str:
        """``branch`` must be a short branch name that Git accepts."""
        if (
            not isinstance(branch, str)
            or not branch
            or branch.startswith("-")
            or branch == "HEAD"
        ):
            raise GitRefused("branch must be a short branch name")
        try:
            self._validate_full_ref(f"refs/heads/{branch}")
        except GitError as exc:
            raise GitRefused(f"unusable branch name: {exc}") from exc
        return branch

    def _common_dir(self) -> Path:
        return _path_from_output(
            self.run("rev-parse", "--path-format=absolute", "--git-common-dir").stdout
        )

    def _git_dir(self) -> Path:
        return _path_from_output(self.run("rev-parse", "--absolute-git-dir").stdout)

    def _head_record(self, ref: str) -> tuple[str, str, str] | None:
        """``(oid, object type, symref target)`` of one exact local ref."""
        result = self.run(
            "for-each-ref",
            "--format=%(refname)%00%(objectname)%00%(objecttype)%00%(symref)",
            ref,
        )
        found: tuple[str, str, str] | None = None
        for line in result.stdout.split(b"\n"):
            if not line:
                continue
            fields = os.fsdecode(line).split("\0")
            if len(fields) != 4:
                raise GitError("malformed ref record from git")
            if fields[0] != ref:
                continue
            if found is not None or _OID_RE.fullmatch(fields[1]) is None:
                raise GitError(f"{ref} could not be read exactly")
            found = (fields[1], fields[2], fields[3])
        if found is None and result.stderr.strip():
            stderr = redact_credentials(
                result.stderr.decode("utf-8", "replace").strip()
            )
            raise GitError(f"git could not read {ref}: {stderr[:500]}")
        return found

    def _remote_default_branches(self) -> set[str]:
        """Current advertised default names; cached origin/HEAD is not authority."""
        names: set[str] = set()
        for raw in self.run("remote").stdout.splitlines():
            remote = self._require_remote(os.fsdecode(raw))
            ref = self._remote_default_ref(remote)
            if ref is None:
                raise GitRefused(f"{remote} default branch is not observable; kept")
            names.add(ref.removeprefix("refs/heads/"))
        return names

    def _branch_in_use(self, branch: str) -> str | None:
        """Why ``refs/heads/<branch>`` must not be deleted now, or ``None``."""
        reason = self._branch_held(branch)
        if reason is not None:
            return reason
        if branch in self._remote_default_branches():
            return "the default branch of a remote"
        return None

    def _branch_held(self, branch: str) -> str | None:
        """Why local state holds ``refs/heads/<branch>``, or ``None``.

        Held means checked out in any worktree, the branch of a rebase or bisect in
        progress, or the common-directory HEAD. Reads no network.
        """
        ref = f"refs/heads/{branch}"
        for entry in self._worktrees():
            if entry.branch == branch:
                return f"checked out in the worktree {entry.path}"
        for gitdir in _worktree_git_dirs(self._common_dir()):
            if {ref, branch} & _operation_branches(gitdir):
                where = os.fsdecode(gitdir)
                return f"the branch of a rebase or bisect in progress under {where}"
        common_head = self.run(
            f"--git-dir={self._common_dir()}",
            "symbolic-ref",
            "--quiet",
            "HEAD",
            check=False,
        )
        if common_head.returncode not in (0, 1):
            raise GitError("common-directory HEAD identity is unavailable")
        if common_head.stdout.rstrip(b"\n") == ref.encode():
            return "the common-directory primary/default HEAD"
        return None

    def branch_upstream(self, branch: str) -> tuple[str, str] | None:
        """The configured upstream of local ``branch``: ``(remote, "refs/heads/<name>")``.

        Read-only. ``remote`` is the alias of a configured remote and the ref is the
        full branch ref on that remote, so it need not equal the local name (fork
        and upstream namespaces can differ). ``None`` means exactly that no remote
        upstream is configured: neither ``branch.<name>.remote`` nor ``.merge`` is
        set, or the upstream is a local branch (``remote = .``). A half-configured,
        repeated, non-branch or unknown-remote upstream, or one that Git's own
        resolution reads differently, raises: it is never reported as ``None``. A
        missing or unusable ``branch`` is refused.
        """
        name = self._validated_branch(branch)
        ref = f"refs/heads/{name}"
        if self._head_record(ref) is None:
            raise GitRefused(f"{ref} does not exist")
        remotes = self._config_values(f"branch.{name}.remote")
        merges = self._config_values(f"branch.{name}.merge")
        if not remotes and not merges:
            return None
        if len(remotes) != 1 or len(merges) != 1:
            raise GitError(f"the upstream configuration of {ref} is incomplete")
        remote, merge = remotes[0], merges[0]
        prefix = "refs/heads/"
        if not merge.startswith(prefix) or len(merge) == len(prefix):
            raise GitError(f"the upstream of {ref} is not a branch ref")
        self._validate_full_ref(merge)
        if remote == ".":
            return None
        try:
            self._require_remote(remote)
        except GitRefused as exc:
            raise GitError(f"the upstream remote of {ref} is unusable: {exc}") from exc
        listing = self.run(
            "for-each-ref",
            "--format=%(refname)%00%(upstream:remotename)%00%(upstream:remoteref)",
            ref,
        ).stdout
        resolved: tuple[str, str] | None = None
        for line in listing.split(b"\n"):
            if not line:
                continue
            fields = os.fsdecode(line).split("\0")
            if len(fields) != 3:
                raise GitError("malformed upstream record from git")
            if fields[0] == ref:
                resolved = (fields[1], fields[2])
        if resolved != (remote, merge):
            raise GitError(
                f"git resolves the upstream of {ref} differently from its "
                "branch configuration"
            )
        return remote, merge

    def _config_values(self, key: str) -> list[str]:
        """Every repository-local value of ``key``; ``[]`` only when it is unset."""
        result = self.run("config", "--local", "-z", "--get-all", key, check=False)
        if result.returncode == 1 and not result.stderr.strip():
            return []
        if result.returncode != 0:
            stderr = redact_credentials(result.stderr.decode("utf-8", "replace"))
            raise GitError(
                f"git could not read {key}: exit {result.returncode}: "
                f"{stderr.strip()[:300]}"
            )
        if not result.stdout.endswith(b"\0"):
            raise GitError(f"unterminated git config output for {key}")
        return [os.fsdecode(item) for item in result.stdout.split(b"\0")[:-1]]

    # -- guarded mutations --------------------------------------------------

    def fetch_base(self, remote: str, base_branch: str, expected_sha: str) -> str:
        """Fetch only ``base_branch`` from ``remote`` and return its verified tip.

        The remote must still advertise exactly ``expected_sha`` (the provider's
        tip) before anything is fetched, and the fetched remote-tracking ref must
        equal it afterwards. Only ``refs/remotes/<remote>/<base_branch>`` is
        written: no tags, no prune, no submodule recursion, no other ref and no
        ``FETCH_HEAD``.
        """
        name = self._require_remote(remote)
        branch = self._validated_branch(base_branch)
        expected = _require_oid(expected_sha, "expected base SHA")
        source = f"refs/heads/{branch}"
        tracking = f"refs/remotes/{name}/{branch}"
        advertised = self._advertised_heads(name, source).get(source)
        if advertised is None:
            raise GitRefused(f"{name} does not advertise {source}")
        if advertised != expected:
            raise GitRefused(
                f"{name} {source} is {advertised}, not the expected {expected}; "
                "nothing was fetched"
            )
        self.run(
            "-c",
            "fetch.writeCommitGraph=false",
            "fetch",
            "--no-tags",
            "--no-prune",
            "--no-recurse-submodules",
            "--no-write-fetch-head",
            "--no-auto-gc",
            "--no-auto-maintenance",
            "--",
            name,
            f"+{source}:{tracking}",
        )
        fetched = self.resolve_ref(tracking)
        if fetched != expected:
            raise GitError(
                f"after the fetch {tracking} is {fetched}, not the expected {expected}",
                uncertain=True,
            )
        return expected

    def fetch_commit(self, remote: str, branch: str, expected_oid: str) -> str:
        """Fetch the objects of ``remote``'s ``branch`` tip, exactly ``expected_oid``.

        The remote must still advertise exactly ``expected_oid`` for
        ``refs/heads/<branch>`` before anything is fetched; when the commit is
        already available locally nothing is fetched at all. Otherwise only that
        advertised branch is fetched, with ``--refmap=`` (the configured
        remote-tracking refspecs are not applied) and no destination, so no
        branch, remote-tracking ref, tag or ``FETCH_HEAD`` is written: the fetch
        adds objects only. A plain advertised ref is used instead of a raw object
        id because every server serves its advertised tips, while fetching an
        unadvertised id depends on server configuration. The fetched objects are
        unreferenced until the caller references them (``gc`` may prune them
        after its expiry). ``expected_oid`` must resolve as a local commit
        afterwards, else the outcome is ``uncertain``. The index, worktrees and
        every user branch are untouched. Returns ``expected_oid``.
        """
        name = self._require_remote(remote)
        short = self._validated_branch(branch)
        expected = _require_oid(expected_oid, "expected branch tip")
        source = f"refs/heads/{short}"
        advertised = self._advertised_heads(name, source).get(source)
        if advertised is None:
            raise GitRefused(f"{name} does not advertise {source}; nothing was fetched")
        if advertised != expected:
            raise GitRefused(
                f"{name} {source} is {advertised}, not the expected {expected}; "
                "nothing was fetched"
            )
        if self.resolve_ref(expected) == expected:
            return expected
        self.run(
            "-c",
            "fetch.writeCommitGraph=false",
            "fetch",
            "--no-tags",
            "--no-prune",
            "--no-recurse-submodules",
            "--no-write-fetch-head",
            "--no-auto-gc",
            "--no-auto-maintenance",
            "--refmap=",
            "--",
            name,
            source,
        )
        if self.resolve_ref(expected) != expected:
            raise GitError(
                f"after fetching {name} {source} the commit {expected} is not "
                "available locally",
                uncertain=True,
            )
        return expected

    def prepare_base_checkout(
        self, base_branch: str, base_tip: str, expected_snapshot: Snapshot
    ) -> Snapshot:
        """Leave this checkout clean on ``base_branch`` fast-forwarded to ``base_tip``.

        ``self`` must be the explicitly selected retained checkout (the existing
        worktree of the base when it is checked out elsewhere), and it must still
        be exactly ``expected_snapshot``. Refused, with nothing changed, when the
        checkout is dirty, conflicted, mid-operation or locked; when the base is
        checked out in a different worktree or does not exist locally; or when
        the local base holds commits that are not on ``base_tip`` (it is
        preserved, never reset). Switching and fast-forwarding use Git's normal
        hooks with automatic stashing and ignored-file overwrite disabled and
        never force; any collision stops with the checkout unchanged by the step
        that failed.
        """
        branch = self._validated_branch(base_branch)
        tip = _require_oid(base_tip, "base tip")
        if not isinstance(expected_snapshot, Snapshot):
            raise GitRefused(
                "the observed snapshot of the retained checkout is required"
            )
        current = self.snapshot()
        same_root = _real(current.root) == _real(expected_snapshot.root)
        same_common = _real(current.common_dir) == _real(expected_snapshot.common_dir)
        if not (same_root and same_common):
            raise GitRefused("this is not the checkout that was observed")
        if current.fingerprint != expected_snapshot.fingerprint:
            raise GitRefused("the retained checkout changed since it was observed")
        if current.dirty:
            raise GitRefused("the retained checkout has uncommitted changes")
        if current.conflicts:
            raise GitRefused("the retained checkout has unmerged paths")
        if current.operations:
            raise GitRefused(
                f"the retained checkout has {', '.join(current.operations)} in progress"
            )
        mine = _worktree_entry(current.worktrees, current.root)
        if mine is None:
            raise GitRefused("the retained checkout is not in the worktree inventory")
        if mine.locked or mine.prunable:
            raise GitRefused("the retained checkout is locked or prunable")
        ref = f"refs/heads/{branch}"
        for entry in current.worktrees:
            if entry.branch == branch and _real(entry.path) != _real(current.root):
                raise GitRefused(
                    f"{ref} is checked out in {entry.path}; use that retained checkout"
                )
        if self.resolve_ref(tip) != tip:
            raise GitRefused("the base tip is not an available commit; fetch it first")
        record = self._head_record(ref)
        if record is None:
            raise GitRefused(f"local {ref} does not exist and is not created here")
        local, kind, symref = record
        if symref or kind != "commit":
            raise GitRefused(f"local {ref} is not a plain branch")
        if local != tip and not self.is_ancestor(local, tip):
            raise GitRefused(
                f"local {ref} has commits that are not on the base tip; left untouched"
            )

        top = GitRepository(current.root, timeout=self.timeout)
        if current.branch != branch:
            try:
                top.run(
                    "-c",
                    "submodule.recurse=false",
                    "switch",
                    "--no-guess",
                    "--no-recurse-submodules",
                    "--no-overwrite-ignore",
                    branch,
                )
            except GitError as exc:
                raise GitError(
                    f"could not switch to {branch}: {exc}", uncertain=exc.uncertain
                ) from exc
        if local != tip:
            try:
                top.run(
                    "-c",
                    "submodule.recurse=false",
                    "merge",
                    "--ff-only",
                    "--no-autostash",
                    "--no-overwrite-ignore",
                    "--no-edit",
                    tip,
                )
            except GitError as exc:
                raise GitError(
                    f"could not fast-forward {branch} to {tip}; the checkout may now "
                    f"be on {branch} at its previous tip: {exc}",
                    uncertain=exc.uncertain,
                ) from exc
        final = top.snapshot()
        if (
            final.branch != branch
            or final.head != tip
            or final.dirty
            or final.conflicts
            or final.operations
        ):
            raise GitError(
                f"the retained checkout is not clean on {branch} at {tip} afterwards",
                uncertain=True,
            )
        return final

    def delete_local_head(self, branch: str, expected_oid: str) -> None:
        """Delete local branch ``branch`` only while it is exactly ``expected_oid``.

        ``branch`` is the short name. Refused when the branch is checked out in any
        worktree, is held by a rebase or bisect in progress, is a remote's default
        branch, is symbolic, or no longer holds ``expected_oid``. The deletion is
        an atomic compare-and-swap (``update-ref -d <ref> <old>``), so a ref that
        moves between the check and the delete survives.
        """
        name = self._validated_branch(branch)
        expected = _require_oid(expected_oid, "expected branch OID")
        ref = f"refs/heads/{name}"
        record = self._head_record(ref)
        if record is None:
            raise GitRefused(f"{ref} does not exist")
        oid, kind, symref = record
        if symref or kind != "commit":
            raise GitRefused(f"{ref} is not a plain branch; kept")
        if oid != expected:
            raise GitRefused(f"{ref} is {oid}, not the expected {expected}; kept")
        reason = self._branch_in_use(name)
        if reason is not None:
            raise GitRefused(f"{ref} is {reason}; kept")
        self.run("update-ref", "-d", "--no-deref", ref, expected)
        if self._head_record(ref) is not None:
            raise GitError(f"{ref} still exists after its deletion", uncertain=True)
        removed = self.run(
            "config", "--local", "--remove-section", f"branch.{name}", check=False
        )
        if removed.returncode != 0 and not (
            removed.returncode == 128 and b"no such section" in removed.stderr
        ):
            stderr = redact_credentials(removed.stderr.decode("utf-8", "replace"))
            raise GitError(
                f"{ref} was deleted but its branch configuration remains: "
                f"{stderr.strip()[:300]}"
            )

    def delete_remote_head(self, remote: str, branch: str, expected_oid: str) -> None:
        """Delete ``branch`` on ``remote`` only while it is exactly ``expected_oid``.

        The push carries an explicit ``--force-with-lease=<ref>:<expected_oid>``
        so the server rejects the deletion of a ref that moved, and the absence
        is verified against the remote afterwards. A remote's default branch is
        refused. Hooks run normally; nothing is retried.
        """
        name = self._require_remote(remote)
        short = self._validated_branch(branch)
        expected = _require_oid(expected_oid, "expected branch OID")
        ref = f"refs/heads/{short}"
        advertised = self._advertised_heads(name, ref).get(ref)
        if advertised is None:
            raise GitRefused(f"{name} does not advertise {ref}")
        if advertised != expected:
            raise GitRefused(
                f"{name} {ref} is {advertised}, not the expected {expected}; kept"
            )
        default = self._remote_default_ref(name)
        if default is None:
            raise GitRefused(f"{name} default branch is not observable; kept")
        if default == ref:
            raise GitRefused(f"{name} {ref} is the default branch; kept")
        try:
            self.run(
                "push",
                "--porcelain",
                "--no-recurse-submodules",
                f"--force-with-lease={ref}:{expected}",
                "--",
                name,
                f":{ref}",
            )
        except GitError as exc:
            try:
                observed = self._advertised_heads(name, ref).get(ref)
            except GitError as observe_error:
                raise GitError(
                    "remote delete was dispatched but its actual outcome is unavailable",
                    uncertain=True,
                ) from observe_error
            if observed is None:
                return
            raise GitError(
                f"remote delete response failed and {name} {ref} remains; reconcile before retry",
                uncertain=True,
            ) from exc
        try:
            still = self._advertised_heads(name, ref).get(ref)
        except GitError as exc:
            raise GitError(
                f"the delete was sent but {name} {ref} could not be verified: {exc}",
                uncertain=True,
            ) from exc
        if still is not None:
            raise GitError(
                f"{name} still advertises {ref} after the delete was accepted",
                uncertain=True,
            )

    def remote_head(self, remote: str, branch: str) -> str | None:
        """What ``remote`` advertises for ``refs/heads/<branch>``; ``None`` if absent.

        Reads the network. An unreachable remote or a malformed advertisement raises.
        """
        name = self._require_remote(remote)
        ref = f"refs/heads/{self._validated_branch(branch)}"
        return self._advertised_heads(name, ref).get(ref)

    def push_head(
        self, remote: str, branch: str, new_oid: str, expected_old: str | None
    ) -> None:
        """Publish exactly ``new_oid`` as ``refs/heads/<branch>`` on ``remote``.

        The remote must still advertise ``expected_old`` (``None``: absent), and a
        present ``expected_old`` must be an ancestor of ``new_oid``: published
        history is only extended, never rewritten. The push carries an explicit
        ``--force-with-lease=<ref>:<expected_old>`` (empty: must not exist), runs
        the repository's hooks, checks submodule commits are published, and is
        verified against the remote. A remote's default branch is refused and
        nothing is retried. A failure whose outcome is unknown is ``uncertain``.
        """
        name = self._require_remote(remote)
        short = self._validated_branch(branch)
        new = _require_oid(new_oid, "new head")
        ref = f"refs/heads/{short}"
        if self.resolve_ref(new) != new:
            raise GitRefused(f"{new} is not an available local commit")
        if expected_old is not None:
            old = _require_oid(expected_old, "expected remote head")
            if self.resolve_ref(old) != old:
                raise GitRefused(
                    f"the published {ref} {old} is not available locally; nothing was pushed"
                )
            if not self.is_ancestor(old, new):
                raise GitRefused(
                    f"{new} does not extend the published {ref}; rewriting it is not authorized"
                )
        self._leased_push(name, ref, new, expected_old)

    def push_rewrite(
        self, remote: str, branch: str, new_oid: str, expected_old: str
    ) -> None:
        """Move remote ``branch`` from exactly ``expected_old`` to ``new_oid``.

        The rewrite-authorized sibling of :meth:`push_head`: ``new_oid`` need not
        extend ``expected_old``. ``expected_old`` is required (never ``None``) and
        must differ from ``new_oid``, and ``new_oid`` must be an available local
        commit. The caller proves ``new_oid`` first (for a promoted slice:
        :meth:`verify_promotion`). The remote must still advertise exactly
        ``expected_old`` immediately before the push, else nothing is pushed. The
        push carries only ``--force-with-lease=refs/heads/<branch>:<expected_old>``
        (no other force), runs the repository's hooks, checks submodule commits
        are published and is verified against the remote. A remote's default
        branch is refused and nothing is retried. After a failure, a remote that
        advertises ``new_oid`` is success; one that still advertises
        ``expected_old`` after a definite refusal is :class:`GitRefused`; anything
        else, or an unobservable remote, is ``uncertain``.
        """
        name = self._require_remote(remote)
        short = self._validated_branch(branch)
        new = _require_oid(new_oid, "new head")
        old = _require_oid(expected_old, "expected remote head")
        if old == new:
            raise GitRefused(
                f"the rewritten head {new} is the expected old head; nothing was pushed"
            )
        ref = f"refs/heads/{short}"
        if self.resolve_ref(new) != new:
            raise GitRefused(f"{new} is not an available local commit")
        self._leased_push(name, ref, new, old)

    def _leased_push(
        self, name: str, ref: str, new: str, expected_old: str | None
    ) -> None:
        """Push ``new`` to ``ref`` under an explicit lease on ``expected_old``.

        ``name``, ``ref`` and both identities are already validated. Refuses unless
        the remote advertises exactly ``expected_old`` (``None``: absent) and ``ref``
        is not its default branch; then dispatches once and reconciles the outcome
        against the remote.
        """
        advertised = self._advertised_heads(name, ref).get(ref)
        if advertised != expected_old:
            raise GitRefused(
                f"{name} {ref} is {advertised}, not the expected {expected_old}; "
                "nothing was pushed"
            )
        default = self._remote_default_ref(name)
        if default is None:
            raise GitRefused(
                f"{name} default branch is not observable; nothing was pushed"
            )
        if default == ref:
            raise GitRefused(f"{name} {ref} is the default branch; nothing was pushed")
        try:
            self.run(
                "push",
                "--porcelain",
                "--recurse-submodules=check",
                f"--force-with-lease={ref}:{expected_old or ''}",
                "--",
                name,
                f"{new}:{ref}",
            )
        except GitError as exc:
            try:
                observed = self._advertised_heads(name, ref).get(ref)
            except GitError as observe_error:
                raise GitError(
                    "the push was dispatched but its actual outcome is unavailable",
                    uncertain=True,
                ) from observe_error
            if observed == new:
                return
            if observed == expected_old and not exc.uncertain:
                raise GitRefused(
                    f"the push did not publish {ref}; {name} still advertises the "
                    f"expected revision (check hook, transport or provider diagnostics): {exc}"
                ) from exc
            raise GitError(
                f"the push of {ref} has an unknown outcome; {name} advertises {observed}",
                uncertain=True,
            ) from exc
        try:
            published = self._advertised_heads(name, ref).get(ref)
        except GitError as exc:
            raise GitError(
                f"the push was accepted but {name} {ref} could not be verified: {exc}",
                uncertain=True,
            ) from exc
        if published != new:
            raise GitError(
                f"{name} advertises {published} for {ref} after the push was accepted",
                uncertain=True,
            )

    def advance_local_branch(
        self, branch: str, expected_old: str, new_oid: str
    ) -> bool:
        """Move local ``branch`` from exactly ``expected_old`` to ``new_oid``.

        ``True`` when the branch was advanced. ``False``, with nothing changed,
        when ``refs/heads/<branch>`` is absent, symbolic, no longer exactly
        ``expected_old``, checked out in any worktree, held by a rebase or bisect
        in progress or the common-directory HEAD. The move is an atomic
        compare-and-swap (``update-ref <ref> <new> <old>``), so a branch that
        moves between the check and the update survives. ``new_oid`` must be an
        available local commit and differ from ``expected_old``. This primitive
        does not judge ancestry: the caller passes the recorded old child head as
        ``expected_old`` and a verified promotion as ``new_oid``. The index,
        worktrees and every other branch are untouched.
        """
        name = self._validated_branch(branch)
        old = _require_oid(expected_old, "expected branch OID")
        new = _require_oid(new_oid, "new branch OID")
        if old == new:
            raise GitRefused(f"{new} is already the expected branch OID")
        if self.resolve_ref(new) != new:
            raise GitRefused(f"{new} is not an available local commit")
        ref = f"refs/heads/{name}"
        record = self._head_record(ref)
        if record is None:
            return False
        oid, kind, symref = record
        if symref or kind != "commit" or oid != old:
            return False
        if self._branch_held(name) is not None:
            return False
        result = self.run(
            "update-ref", "--no-deref", "-m", _REPLAY_REFLOG, ref, new, old, check=False
        )
        after = self._head_record(ref)
        current = None if after is None else after[0]
        if result.returncode == 0:
            if current != new:
                raise GitError(
                    f"{ref} is {current} after it was advanced to {new}", uncertain=True
                )
            return True
        if current == old:
            stderr = redact_credentials(result.stderr.decode("utf-8", "replace"))
            raise GitError(
                f"git update-ref failed and {ref} is unchanged: {stderr.strip()[:300]}"
            )
        return False

    def remove_worktree(
        self, path: Path, expected_head: str, expected_branch: str | None
    ) -> None:
        """Remove one linked worktree through ``git worktree remove`` (never forced).

        Refused, with nothing changed, unless the worktree belongs to this
        repository's common directory, is a linked worktree (not the main
        checkout) that does not contain the checkout this instance was opened on
        or the process's working directory, is not locked or missing, is exactly
        at ``expected_head`` on ``expected_branch`` (``None`` for detached), has no
        staged, unstaged, untracked, conflicted, in-progress or *ignored* files and
        no Git lock, and :func:`worktree_activity` reports it ``INACTIVE``. Every
        proof is taken twice immediately before the removal; any difference refuses.
        """
        head = _require_oid(expected_head, "expected worktree HEAD")
        branch = (
            None if expected_branch is None else self._validated_branch(expected_branch)
        )
        target = _real(path)
        entry = next(
            (item for item in self._worktrees() if _real(item.path) == target), None
        )
        if entry is None:
            raise GitRefused(f"{path} is not a worktree of this repository")
        first = self._prove_worktree_removable(entry, head, branch)
        if self._prove_worktree_removable(entry, head, branch) != first:
            raise GitRefused(f"{entry.path} changed while it was being inspected")
        try:
            self.run("worktree", "remove", "--", str(entry.path))
        except GitError as exc:
            raise GitError(
                f"git worktree remove failed; the tree may be partly removed: {exc}",
                uncertain=True,
            ) from exc
        if os.path.lexists(entry.path) or any(
            _real(item.path) == target for item in self._worktrees()
        ):
            raise GitError(
                f"{entry.path} is still present after its removal", uncertain=True
            )

    def _prove_worktree_removable(
        self, entry: Worktree, head: str, branch: str | None
    ) -> str:
        """Return the checkout's fingerprint when every removal proof holds."""
        where = entry.path
        if entry.prunable:
            raise GitRefused(f"{where} is missing; stale metadata is not removed here")
        if entry.locked:
            raise GitRefused(f"{where} is locked; kept")
        if entry.head != head or entry.branch != branch:
            raise GitRefused(f"{where} is not at the expected head and branch; kept")
        real = _real(where)
        try:
            invoking = (self.path, Path(os.getcwd()))
        except OSError as exc:
            raise GitRefused(
                f"the invoking directory cannot be determined ({exc.strerror}); kept"
            ) from exc
        for protected in invoking:
            if _within(_real(protected), real):
                raise GitRefused(f"{where} contains the invoking checkout; kept")
        top = GitRepository(where, timeout=self.timeout)
        common = top._common_dir()
        if _real(common) != _real(self._common_dir()):
            raise GitRefused(f"{where} belongs to a different repository; kept")
        gitdir = top._git_dir()
        if _real(gitdir) == _real(common):
            raise GitRefused(f"{where} is the main checkout; kept")
        observed = top.snapshot()
        if _real(observed.root) != real:
            raise GitRefused(f"{where} is not the root of its checkout; kept")
        if observed.head != head or observed.branch != branch:
            raise GitRefused(f"{where} is not at the expected head and branch; kept")
        if observed.dirty or observed.conflicts or observed.operations:
            raise GitRefused(f"{where} has uncommitted or in-progress work; kept")
        ignored = top._ignored_entries()
        if ignored:
            shown = ", ".join(repr(name) for name in ignored[:3])
            raise GitRefused(
                f"{where} holds {len(ignored)} ignored path(s) ({shown}); kept"
            )
        locks = [
            os.path.join(os.fsencode(gitdir), b"index.lock"),
            os.path.join(os.fsencode(gitdir), b"HEAD.lock"),
        ]
        if branch is not None:
            ref_lock = os.fsencode(f"refs/heads/{branch}.lock")
            locks.append(os.path.join(os.fsencode(common), ref_lock))
        for lock in locks:
            if _lstat_or_none(lock) is not None:
                raise GitRefused(f"{where} has a Git lock ({os.fsdecode(lock)}); kept")
        activity = worktree_activity(where)
        if activity.status != "INACTIVE":
            raise GitRefused(f"{where} is not provably idle ({activity.reason}); kept")
        return observed.fingerprint

    def _ignored_entries(self) -> tuple[str, ...]:
        """Ignored paths in this checkout (directories collapse to ``dir/``)."""
        raw = self.run(
            "status",
            "--porcelain=v2",
            "-z",
            "--untracked-files=normal",
            "--ignored=traditional",
            "--no-renames",
            "--ignore-submodules=none",
        ).stdout
        if raw and not raw.endswith(b"\0"):
            raise GitError("unterminated git status output")
        tokens = raw.split(b"\0")[:-1]
        return tuple(os.fsdecode(token[2:]) for token in tokens if token[:2] == b"! ")

    # -- landing proof ------------------------------------------------------

    def pr_head(self, remote: str, number: int) -> str | None:
        """Read GitHub's read-only PR head ref in the actual base namespace.

        None means the exact advertised PR ref is absent, not a landed-head
        proof. Malformed, contradictory or inaccessible evidence raises.
        """
        if type(number) is not int or number <= 0:
            raise ValueError("PR number must be a positive integer")
        name = self._require_remote(remote)
        ref = f"refs/pull/{number}/head"
        raw = self.run("ls-remote", "--refs", "--", name, ref).stdout
        rows = [line.split(b"\t") for line in raw.splitlines() if line]
        if not rows:
            return None
        if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != ref.encode():
            raise GitError("PR head advertisement is contradictory")
        oid = rows[0][0].decode("ascii", "replace")
        if _OID_RE.fullmatch(oid) is None:
            raise GitError("PR head advertisement has an invalid object identity")
        return oid

    def whole_change_landed(
        self, candidate_head: str, landing: str, base_tip: str
    ) -> bool:
        """Whether the candidate's entire net change is part of the landing.

        ``True`` requires ``landing`` to be reachable from ``base_tip`` and either
        the candidate to be an ancestor of ``landing`` (merge/fast-forward), or the
        candidate's complete tree delta against its fork point to have exactly
        the same paths, modes and full before/after blob identities as the delta
        the landing itself introduced: one squash commit, or the same number
        of linear commits as the candidate for a rebase landing. A candidate with
        added work, a partial inclusion, a net-empty change or an ambiguous fork
        point is ``False``; ``git cherry`` is never the proof. Nothing is
        written. Unknown or non-commit revisions raise.
        """
        candidate = self._require_commit(candidate_head, "candidate head")
        landed = self._require_commit(landing, "landing commit")
        tip = self._require_commit(base_tip, "base tip")
        if not self.is_ancestor(landed, tip):
            return False
        if self.is_ancestor(candidate, landed):
            return True
        fork = self.merge_base(candidate, landed)
        if fork is None:
            return False
        wanted = self._net_change_identity(fork, candidate)
        if wanted is None:
            return False
        count = self._change_commits(fork, candidate)
        for width in sorted({1, count}):
            if width < 1:
                continue
            parent = self._landing_parent(landed, width)
            if (
                parent is not None
                and self._net_change_identity(parent, landed) == wanted
            ):
                return True
        return False

    def landing_bases(self, base: str, head: str, landing: str) -> tuple[str, ...]:
        """Where the trunk stood before ``landing`` put the change ``base..head`` on it.

        The first parent of ``landing`` (one squash or merge commit, or a rebase
        of a single commit) and, when the change has N > 1 non-merge commits, the
        parent of the N-th linear first-parent commit back from ``landing`` (a
        rebase replaying them one by one), the widths
        :meth:`whole_change_landed` reads. Nothing is proved here: the caller
        compares a tree over each candidate. Read-only; all three must be full
        ids of available commits, and unknown or non-commit revisions raise.
        """
        start = self._require_commit(base, "change base")
        tip = self._require_commit(head, "change head")
        landed = self._require_commit(landing, "landing commit")
        bases: list[str] = []
        first = self.first_parent(landed)
        if first is not None:
            bases.append(first)
        count = self._change_commits(start, tip)
        if count > 1:
            parent = self._landing_parent(landed, count)
            if parent is not None and parent not in bases:
                bases.append(parent)
        return tuple(bases)

    def _change_commits(self, base: str, head: str) -> int:
        """The number of non-merge commits in ``base..head``."""
        raw = self.run("rev-list", "--count", "--no-merges", f"{base}..{head}").stdout
        try:
            return int(raw)
        except ValueError:
            raise GitError("git returned an invalid commit count") from None

    def _require_commit(self, oid: str, what: str) -> str:
        value = _require_oid(oid, what)
        if self.resolve_ref(value) != value:
            raise GitError(f"{what} {value} is not an available commit")
        return value

    def _landing_parent(self, landing: str, width: int) -> str | None:
        """Parent of the ``width``-th first-parent commit back, if all are linear."""
        raw = self.run(
            "rev-list", "--first-parent", "--parents", "-n", str(width), landing
        ).stdout
        rows = [line.split() for line in raw.split(b"\n") if line]
        if len(rows) != width or any(len(row) != 2 for row in rows):
            return None
        parent = rows[-1][1].decode("ascii", "replace")
        return parent if _OID_RE.fullmatch(parent) else None

    def _net_change_identity(self, old: str, new: str) -> str | None:
        """Exact path/mode/blob identity of the complete net delta; None if empty."""
        diff = self.run(
            "diff-tree",
            "-r",
            "--raw",
            "--no-abbrev",
            "--no-commit-id",
            "-z",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            "--ignore-submodules=none",
            old,
            new,
        ).stdout
        if not diff:
            return None
        return hashlib.sha256(diff).hexdigest()

    def commit_tree(self, commit: str) -> str:
        """The full tree id of available commit ``commit`` (a full id). Read-only."""
        return self._tree_of(self._require_commit(commit, "commit"))

    def first_parent(self, commit: str) -> str | None:
        """The first parent of available commit ``commit``; None for a root commit.

        Read-only. ``commit`` must be a full id; replacement objects and grafts
        are whatever this repository's Git honours.
        """
        return self._peel_commit(f"{self._require_commit(commit, 'commit')}^1")

    def merge_base(self, first: str, second: str) -> str | None:
        """The single best common ancestor of two available commits (full ids).

        Read-only. None when they share no history or when Git reports several
        best common ancestors: an ambiguous fork point is never chosen.
        """
        one = self._require_commit(first, "commit")
        two = self._require_commit(second, "commit")
        bases = self.run("merge-base", "--all", one, two, check=False)
        if bases.returncode == 1:
            return None
        if bases.returncode != 0:
            raise GitError("git merge-base failed")
        forks = [line for line in bases.stdout.split(b"\n") if line]
        if len(forks) != 1:
            return None
        fork = forks[0].decode("ascii", "replace")
        if _OID_RE.fullmatch(fork) is None:
            raise GitError("git returned an invalid merge base")
        return fork

    def slice_identity(self, base: str, head: str) -> str:
        """Identity of the exact net change from commit ``base`` to commit ``head``.

        The SHA-256 of ``git diff-tree -r --raw -z --no-renames`` of the two
        commits' trees: every changed path with both modes, both full object ids
        (blobs, symlink targets and submodule gitlinks alike) and its change
        status, byte for byte and binary-safe. Rename and copy detection are off
        and no index, worktree, textconv or external diff is used, so the same
        delta between any two commits has the same identity. Read-only. A
        net-empty change has no own slice and is refused with
        :class:`GitRefused`; unknown or non-commit revisions raise
        :class:`GitError`.
        """
        start = self._require_commit(base, "slice base")
        tip = self._require_commit(head, "slice head")
        identity = self._net_change_identity(start, tip)
        if identity is None:
            raise GitRefused(f"the change from {start} to {tip} is empty")
        return identity

    # -- stack promotion ----------------------------------------------------

    def three_way_tree(self, base: str, ours: str, theirs: str) -> str | None:
        """Tree of the clean three-way merge of ``ours`` and ``theirs`` over ``base``.

        Execution only: it writes objects into this repository. All three must be
        full ids of available commits. Runs ``git merge-tree --write-tree
        --merge-base=<base>``, which writes the merged trees and blobs (and
        refreshes the modification time of objects that already exist) and
        nothing else: no index, worktree, ref or merge state. Inspection uses
        :meth:`preview_three_way` instead. ``None`` means the merge conflicts; a
        conflict is never resolved. Needs Git 2.40 or later; an older Git, any
        other failure or malformed output raises :class:`GitError`.
        """
        merge_base = self._require_commit(base, "merge base")
        mine = self._require_commit(ours, "merge side")
        other = self._require_commit(theirs, "merge side")
        return self._merge_tree(merge_base, mine, other)

    def preview_three_way(self, base: str, ours: str, theirs: str) -> str | None:
        """:meth:`three_way_tree` of three local commits, writing nothing here.

        For inspection and dry runs. The three commits must be available in this
        repository (checked read-only). A private bare repository is created in a
        fresh temporary directory outside this repository (refused when the
        temporary location lies inside its git directory or a worktree), with
        the same object format and no templates. It receives exactly the three
        commits at depth 1 through ``git fetch`` from this repository's common
        directory over protocol v2, whose ``upload-pack`` only reads (and serves
        unreferenced commits too), with no tags, ``FETCH_HEAD``, submodule
        recursion, commit-graph or automatic maintenance. The merge runs there and
        the directory is always removed, also on failure. Nothing in this
        repository is written: no object, ref, index, configuration, lock, file or
        modification time.

        The result is the cumulative three-way tree only: it does not prove the
        per-commit replay of :meth:`promote_slice`, and the private repository has
        none of this repository's local configuration or attributes (merge
        drivers, rename settings), which the execution-time :meth:`three_way_tree`
        sees. ``None`` means the merge conflicts. Every failure raises
        :class:`GitError` (never ``uncertain``: nothing here was changed).
        """
        merge_base = self._require_commit(base, "merge base")
        mine = self._require_commit(ours, "merge side")
        other = self._require_commit(theirs, "merge side")
        source = _real(self._common_dir())
        protected = [source, _real(self._git_dir())]
        protected.extend(_real(entry.path) for entry in self._worktrees())
        location = _real(tempfile.gettempdir())
        if any(_within(location, root) for root in protected):
            raise GitRefused(
                f"the temporary directory {location} lies inside the repository; "
                "nothing was previewed"
            )
        scratch = tempfile.mkdtemp(prefix="ship-preview-")
        try:
            private = _real(scratch)
            if any(_within(private, root) for root in protected):
                raise GitRefused(
                    f"the temporary directory {private} lies inside the repository; "
                    "nothing was previewed"
                )
            scope = self._seed_preview(private, source, (merge_base, mine, other))
            return self._merge_tree(merge_base, mine, other, *scope)
        except GitError as exc:
            if exc.uncertain:
                raise GitError(
                    f"the three-way preview did not finish; nothing here changed: {exc}"
                ) from exc
            raise
        finally:
            try:
                shutil.rmtree(scratch)
            except OSError as exc:
                raise GitError(
                    f"cannot remove the preview directory {scratch}: {exc.strerror}"
                ) from exc

    def _seed_preview(
        self, private: str, source: str, commits: tuple[str, ...]
    ) -> tuple[str, ...]:
        """Make ``private`` a bare repository holding ``commits`` from ``source``.

        Returns the global options that select it. ``source`` (this repository's
        common directory) is only read, by ``git upload-pack``.
        """
        reported = self.run("rev-parse", "--show-object-format").stdout
        object_format = reported.decode("ascii", "replace").strip()
        if object_format not in _OBJECT_FORMATS:
            raise GitError(f"unsupported object format {object_format!r}")
        scope = ("-C", private, f"--git-dir={private}")
        self.run(
            *scope,
            "init",
            "--quiet",
            "--bare",
            "--template=",
            f"--object-format={object_format}",
        )
        self.run(
            *scope,
            "-c",
            "protocol.version=2",
            "-c",
            "fetch.writeCommitGraph=false",
            "fetch",
            "--quiet",
            "--no-tags",
            "--no-write-fetch-head",
            "--no-recurse-submodules",
            "--no-auto-gc",
            "--no-auto-maintenance",
            "--depth=1",
            "--",
            source,
            *commits,
        )
        for oid in commits:
            seeded = self.run(
                *scope,
                "rev-parse",
                "--verify",
                "--quiet",
                f"{oid}^{{commit}}",
                check=False,
            )
            received = seeded.stdout.decode("ascii", "replace").strip()
            if seeded.returncode != 0 or received != oid:
                raise GitError(f"the preview repository did not receive {oid}")
        return scope

    def _merge_tree(self, base: str, ours: str, theirs: str, *scope: str) -> str | None:
        """``git [scope] merge-tree --write-tree`` of three verified commit ids."""
        result = self.run(
            *scope,
            "merge-tree",
            "--write-tree",
            "--no-messages",
            "-z",
            f"--merge-base={base}",
            ours,
            theirs,
            check=False,
        )
        if result.returncode == 129:
            raise GitError(
                "git merge-tree --write-tree --merge-base is unavailable; "
                "Git 2.40 or later is required to prove a promotion"
            )
        if result.returncode not in (0, 1):
            stderr = redact_credentials(
                result.stderr.decode("utf-8", "replace").strip()
            )
            raise GitError(
                f"git merge-tree failed (exit {result.returncode}): {stderr[:500]}"
            )
        tree_raw, terminator, rest = result.stdout.partition(b"\0")
        tree = tree_raw.decode("ascii", "replace")
        if not terminator or _OID_RE.fullmatch(tree) is None:
            raise GitError("git merge-tree reported no valid tree")
        if result.returncode == 1:
            return None
        if rest:
            raise GitError("git merge-tree listed conflicts for a clean merge")
        return tree

    def slice_commits(self, fork: str, head: str) -> tuple[SliceCommit, ...]:
        """The child's own commits ``fork..head``, oldest first. Read-only.

        Reads objects only; writes nothing, so it is safe in inspection. ``fork``
        must be a strict ancestor of ``head`` and the range one linear chain of
        at most ``_MAX_SLICE_COMMITS`` (256) commits: every commit has exactly
        one parent and the oldest one's parent is ``fork``. Refused with
        :class:`GitRefused`: an empty or longer range, a merge or root commit,
        any other topology, a signed commit (``gpgsig``/``gpgsig-sha256``: a
        replay cannot sign it and never drops a signature, which would remove
        provenance), any header a replay does not write back (anything but
        tree, parent, author, committer and encoding, or one of those continued
        over several lines), or an author identity ``git fsck`` would reject.
        """
        start = self._require_commit(fork, "fork point")
        tip = self._require_commit(head, "slice head")
        if start == tip:
            raise GitRefused(f"the slice is empty: the fork point is the head {tip}")
        if not self.is_ancestor(start, tip):
            raise GitRefused(f"the fork point {start} is not an ancestor of {tip}")
        commits: list[SliceCommit] = []
        parent = start
        for oid in self._linear_chain(start, tip):
            record = self._commit_record(oid)
            if record.parents != (parent,):
                raise GitError(f"commit {oid} contradicts the listed history")
            if record.signatures:
                raise GitRefused(
                    f"commit {oid} is signed ({', '.join(record.signatures)}); a "
                    "replay cannot sign it and never drops a signature"
                )
            if record.unsupported:
                raise GitRefused(
                    f"commit {oid} carries {', '.join(record.unsupported)} "
                    "header(s) that a replay cannot preserve"
                )
            if _IDENT_RE.fullmatch(record.author) is None:
                raise GitRefused(
                    f"commit {oid} has an author identity that cannot be written back"
                )
            commits.append(
                SliceCommit(
                    oid=oid,
                    parent=parent,
                    tree=record.tree,
                    author=record.author,
                    encoding=record.encoding,
                    message=record.message,
                )
            )
            parent = oid
        return tuple(commits)

    def promote_slice(
        self,
        fork: str,
        head: str,
        landing: str,
        *,
        reviewed: tuple[tuple[str, str], ...] = (),
    ) -> Promotion:
        """Replay the child's own slice ``fork..head`` onto ``landing``.

        Execution only: it writes objects (merged trees and the replayed commits)
        into this repository; no ref, index, worktree or checkout changes and no
        hook runs. Without ``reviewed`` the expected result is the clean aggregate
        three-way tree ``base=fork, ours=landing, theirs=head``. ``reviewed``
        contains ordered (original commit, approved tree) pairs only for actual
        conflicting per-commit steps. Clean steps always retain their mechanically
        proved trees; missing, extraneous or reordered approvals refuse the replay.
        Each commit, oldest first, is replayed with plumbing. Its object preserves
        the original author, ``encoding`` header and message bytes (trailers and
        a missing trailing newline included) and written with ``git hash-object
        -t commit -w``, then read back and compared byte-for-byte. The committer
        is the repository's normal committer identity (``git var
        GIT_COMMITTER_IDENT``, read once).

        The replayed commits are unsigned, so the replay is refused before any
        object is written when the effective configuration sets
        ``commit.gpgSign`` (the caller's signing policy is never overridden or
        bypassed) or when a slice commit is signed (see :meth:`slice_commits`).
        A repository that requires signed commits needs a different,
        caller-signed path; whether the provider requires signed commits is not
        observable here. Also refused before any object is written: ``landing``
        already an ancestor of ``head``, an unusable slice, a net-empty slice.
        Refused after objects may have been written (never a ref): a conflicting
        cumulative merge, a conflicting commit, or a commit that would become
        empty on the landing (it is never dropped silently), and a result whose
        tree is not the expected tree or whose ``landing..new_head`` is not one
        linear chain of exactly the slice's commit count. Repeated calls give the
        same result except for the committer timestamp, so a caller that must
        republish the same commit ids freezes the result and re-proves it with
        :meth:`verify_promotion` instead of replaying again.
        """
        start = self._require_commit(fork, "fork point")
        old = self._require_commit(head, "child head")
        target = self._require_commit(landing, "landing")
        if self.signing_required():
            raise GitRefused(
                "commit.gpgSign requires signed commits and a plumbing replay cannot "
                "sign them; nothing was written. A caller-signed path is required"
            )
        if self.is_ancestor(target, old):
            raise GitRefused(f"{old} is already based on the landing {target}")
        commits = self.slice_commits(start, old)
        identity = self._net_change_identity(start, old)
        if identity is None:
            raise GitRefused(f"the slice {start}..{old} has no net change")
        committer = self._committer_ident()
        approvals = self._reviewed_trees(commits, reviewed)
        expected = self.three_way_tree(start, target, old)
        if expected is None and not approvals:
            raise GitRefused(
                f"replaying {start}..{old} onto {target} is a conflict; "
                "it is never resolved automatically"
            )
        tip = target
        tip_tree = self._tree_of(target)
        used: list[str] = []
        for commit in commits:
            tree = self.three_way_tree(commit.parent, tip, commit.oid)
            if tree is None:
                if commit.oid not in approvals:
                    raise GitRefused(
                        f"replaying {commit.oid} requires an explicitly reviewed tree"
                    )
                tree = approvals[commit.oid]
                used.append(commit.oid)
            elif commit.oid in approvals:
                raise GitRefused(
                    f"{commit.oid} has extraneous approval for a nonconflicting replay"
                )
            if tree == tip_tree:
                raise GitRefused(
                    f"{commit.oid} would become empty on {target}; it is never dropped silently"
                )
            tip = self._replay(commit, tree, tip, committer)
            tip_tree = tree
        final_tree = self._tree_of(tip)
        if used != list(approvals):
            raise GitRefused(
                "reviewed conflict trees are absent, extraneous or out of replay order"
            )
        if approvals:
            expected = final_tree
        if final_tree != expected:
            raise GitRefused(
                f"the replayed slice has tree {final_tree}, not the clean three-way tree {expected}"
            )
        if len(self._linear_chain(target, tip)) != len(commits):
            raise GitRefused(f"{target}..{tip} does not hold exactly the slice")
        return Promotion(
            fork=start,
            old_head=old,
            landing=target,
            expected_tree=expected,
            new_head=tip,
            commits=len(commits),
            slice_identity=identity,
        )

    def verify_promotion(
        self,
        promotion: Promotion,
        *,
        reviewed: tuple[tuple[str, str], ...] = (),
    ) -> None:
        """Re-prove a recorded promotion from its identities; refuse any mismatch.

        Read-only: nothing in this repository is written (the three-way tree is
        recomputed with :meth:`preview_three_way`), so it is safe in inspection.
        Checks, raising :class:`GitRefused` with the exact difference: every
        recorded id is well-formed and every commit is available locally;
        ``new_head`` has the tree ``expected_tree``; ``landing`` is an ancestor
        of ``new_head`` and ``landing..new_head`` is one linear chain of exactly
        ``commits`` non-merge commits carrying, in order, exactly the author,
        ``encoding`` and message of the commits of ``fork..old_head`` (a usable
        slice, see :meth:`slice_commits`) and no signature or other header;
        ``slice_identity`` is the net delta identity of ``fork..old_head``.
        Every per-commit tree is re-proved read-only; only actual conflicts may use
        the supplied ordered ``reviewed`` trees. Without approvals, the clean
        aggregate three-way tree must also equal ``expected_tree``. Recorded
        output trees and heads alone are never authority for a replay.
        """
        if not isinstance(promotion, Promotion):
            raise GitRefused("a recorded promotion is required")
        fork = _require_oid(promotion.fork, "recorded fork point")
        old = _require_oid(promotion.old_head, "recorded old head")
        landing = _require_oid(promotion.landing, "recorded landing")
        expected = _require_oid(promotion.expected_tree, "recorded expected tree")
        new = _require_oid(promotion.new_head, "recorded new head")
        count = promotion.commits
        if type(count) is not int or count < 1:
            raise GitRefused("the recorded commit count must be a positive integer")
        for what, value in (
            ("fork point", fork),
            ("old head", old),
            ("landing", landing),
            ("new head", new),
        ):
            if self.resolve_ref(value) != value:
                raise GitRefused(
                    f"the recorded {what} {value} is not an available local commit"
                )
        tree = self._tree_of(new)
        if tree != expected:
            raise GitRefused(
                f"the new head {new} has the tree {tree}, not the recorded {expected}"
            )
        if not self.is_ancestor(landing, new):
            raise GitRefused(f"the landing {landing} is not an ancestor of {new}")
        replayed = self._linear_chain(landing, new)
        originals = self.slice_commits(fork, old)
        if len(replayed) != count or len(originals) != count:
            raise GitRefused(
                f"{landing}..{new} holds {len(replayed)} commit(s) and "
                f"{fork}..{old} {len(originals)}, not the recorded {count}"
            )
        approvals = self._reviewed_trees(originals, reviewed)
        used: list[str] = []
        replay_parent = landing
        for original, oid in zip(originals, replayed, strict=True):
            record = self._commit_record(oid)
            if record.signatures or record.unsupported:
                raise GitRefused(
                    f"{oid} carries headers a replay of {original.oid} never writes"
                )
            if (record.author, record.message, record.encoding) != (
                original.author,
                original.message,
                original.encoding,
            ):
                raise GitRefused(
                    f"{oid} does not carry the exact author and message of "
                    f"{original.oid}"
                )
            step_tree = self.preview_three_way(
                original.parent, replay_parent, original.oid
            )
            if step_tree is None:
                if original.oid not in approvals:
                    raise GitRefused(f"{original.oid} has no reviewed conflict tree")
                step_tree = approvals[original.oid]
                used.append(original.oid)
            elif original.oid in approvals:
                raise GitRefused(
                    f"{original.oid} has approval for a nonconflicting step"
                )
            if record.tree != step_tree or record.tree == self._tree_of(replay_parent):
                raise GitRefused(
                    f"{oid} does not preserve the proved nonempty replay step"
                )
            replay_parent = oid
        if used != list(approvals):
            raise GitRefused("reviewed conflict trees do not match replay order")
        identity = self._net_change_identity(fork, old)
        if identity != promotion.slice_identity:
            raise GitRefused(
                f"the recorded slice identity does not match {fork}..{old}"
            )
        recomputed = (
            expected if approvals else self.preview_three_way(fork, landing, old)
        )
        if recomputed != expected:
            raise GitRefused(
                f"the clean three-way tree of the recorded fork, landing and old "
                f"head is {recomputed}, not the recorded {expected}"
            )

    def _reviewed_trees(
        self,
        commits: tuple[SliceCommit, ...],
        reviewed: tuple[tuple[str, str], ...],
    ) -> dict[str, str]:
        approvals: dict[str, str] = {}
        originals = {commit.oid for commit in commits}
        for old, tree in reviewed:
            _require_oid(old, "reviewed original")
            _require_oid(tree, "reviewed tree")
            if old in approvals or old not in originals:
                raise GitRefused(
                    "reviewed originals must be unique members of the source slice"
                )
            kind = self.run("cat-file", "-t", tree, check=False)
            if kind.returncode != 0 or kind.stdout.strip() != b"tree":
                raise GitRefused(
                    f"reviewed tree {tree} is not an available tree object"
                )
            approvals[old] = tree
        return approvals

    def _linear_chain(self, start: str, tip: str) -> tuple[str, ...]:
        """Commits ``start..tip`` oldest first; refused unless one linear chain.

        A range of more than ``_MAX_SLICE_COMMITS`` commits is refused; at most
        one commit beyond the bound is ever listed.
        """
        raw = self.run(
            "rev-list",
            "--topo-order",
            "--reverse",
            "--parents",
            f"--max-count={_MAX_SLICE_COMMITS + 1}",
            f"{start}..{tip}",
        ).stdout
        if raw and not raw.endswith(b"\n"):
            raise GitError("unterminated rev-list output")
        rows = [
            line.decode("ascii", "replace").split(" ") for line in raw.split(b"\n")[:-1]
        ]
        if len(rows) > _MAX_SLICE_COMMITS:
            raise GitRefused(
                f"{start}..{tip} holds more than {_MAX_SLICE_COMMITS} commits; "
                "a slice that long is never replayed"
            )
        for fields in rows:
            if any(_OID_RE.fullmatch(field) is None for field in fields):
                raise GitError("malformed rev-list record")
            if len(fields) != 2:
                kind = "root" if len(fields) == 1 else "merge"
                raise GitRefused(
                    f"{fields[0]} is a {kind} commit; {start}..{tip} is not one "
                    "linear chain"
                )
        chain: list[str] = []
        parent = start
        for fields in rows:
            if fields[1] != parent:
                raise GitRefused(
                    f"{start}..{tip} is not one linear chain at {fields[0]}"
                )
            chain.append(fields[0])
            parent = fields[0]
        if not chain or parent != tip:
            raise GitRefused(f"{start}..{tip} is not one linear chain ending at {tip}")
        return tuple(chain)

    def _commit_record(self, oid: str) -> _CommitRecord:
        return _parse_commit(oid, self.run("cat-file", "commit", oid).stdout)

    def _tree_of(self, commit: str) -> str:
        raw = self.run("rev-parse", "--verify", f"{commit}^{{tree}}").stdout
        tree = raw.decode("ascii", "replace").strip()
        if _OID_RE.fullmatch(tree) is None:
            raise GitError("git returned an invalid tree id")
        return tree

    def signing_required(self) -> bool:
        """Whether the effective configuration sets ``commit.gpgSign``. Read-only.

        Repository, global, system and environment-supplied configuration all
        count, as they do for ``git commit``. A plumbing replay cannot sign, so
        :meth:`promote_slice` refuses when this holds and inspection reports it.
        An unreadable or malformed value raises :class:`GitError`.
        """
        result = self.run(
            "config", "--type=bool", "--get", "commit.gpgsign", check=False
        )
        if result.returncode == 1 and not result.stdout:
            return False
        if result.returncode != 0:
            stderr = redact_credentials(result.stderr.decode("utf-8", "replace"))
            raise GitError(
                f"commit.gpgSign cannot be read: exit {result.returncode}: "
                f"{stderr.strip()[:300]}"
            )
        value = result.stdout.rstrip(b"\n")
        if value not in (b"true", b"false"):
            raise GitError("git reported an unexpected commit.gpgSign value")
        return value == b"true"

    def _committer_ident(self) -> bytes:
        """The committer identity Git gives a new commit here (``git var``)."""
        raw = self.run("var", "GIT_COMMITTER_IDENT").stdout
        if not raw.endswith(b"\n") or _IDENT_RE.fullmatch(raw[:-1]) is None:
            raise GitError("git reported an unusable committer identity")
        return raw[:-1]

    def _replay(
        self, commit: SliceCommit, tree: str, parent: str, committer: bytes
    ) -> str:
        """Write ``commit`` again as ``tree`` on ``parent``; return the new id.

        The object is composed here from the original author, ``encoding`` and
        message bytes and written with ``git hash-object -t commit -w``, which
        refuses a malformed object; read back, it must be exactly those bytes.
        """
        encoding = (
            b"" if commit.encoding is None else b"encoding %s\n" % commit.encoding
        )
        raw = b"".join(
            (
                b"tree %s\n" % tree.encode("ascii"),
                b"parent %s\n" % parent.encode("ascii"),
                b"author %s\n" % commit.author,
                b"committer %s\n" % committer,
                encoding,
                b"\n",
                commit.message,
            )
        )
        written = self.run(
            "hash-object", "-t", "commit", "-w", "--stdin", input_bytes=raw
        ).stdout
        new = written.decode("ascii", "replace").strip()
        if _OID_RE.fullmatch(new) is None:
            raise GitError("git hash-object returned an invalid commit id")
        if self.run("cat-file", "commit", new).stdout != raw:
            raise GitError(f"git stored {new} with other bytes than the replay")
        return new


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


def _verify_selected_checkout(
    requested: Path, root: Path, common_dir: Path, git_dir: Path
) -> None:
    """Prove Git selected the checkout that really contains ``requested``.

    Repository configuration (``core.worktree``) or an inherited setting can make
    Git report another repository's work tree. The reported root must contain the
    requested directory, the git directory must live in the common directory, and
    the root's ``.git`` must lead back to that git directory.
    """
    if not _within(_real(requested), _real(root)):
        raise GitError(
            f"git selected the work tree {root}, which does not contain {requested}"
        )
    if not _within(_real(git_dir), _real(common_dir)):
        raise GitError("git selected a git directory outside its common directory")
    link = os.path.join(os.fsencode(root), b".git")
    found = _lstat_or_none(link)
    if found is None:
        raise GitError(f"the selected work tree {root} has no .git link")
    if stat.S_ISDIR(found.st_mode):
        target = os.fsdecode(link)
    else:
        text = _read_small(link)
        if text is None or not text.startswith("gitdir:"):
            raise GitError(f"the .git file of {root} is not a gitdir link")
        target = os.path.join(root, text[len("gitdir:") :].strip())
    if _real(target) != _real(git_dir):
        raise GitError(
            f"the work tree {root} does not lead to the selected git directory"
        )


def _real(path: str | os.PathLike[str]) -> str:
    return os.path.realpath(path)


def _within(path: str, root: str) -> bool:
    """True when real path ``path`` is ``root`` or lies below it."""
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _require_oid(value: object, what: str) -> str:
    if not isinstance(value, str) or _OID_RE.fullmatch(value) is None:
        raise GitRefused(f"{what} must be a full lowercase object id")
    return value


def _check_head_name(name: str) -> None:
    prefix = "refs/heads/"
    if not name.startswith(prefix) or len(name) == len(prefix):
        raise GitError(f"unexpected ref {name!r} in a branch inventory")


def _worktree_entry(worktrees: Sequence[Worktree], root: Path) -> Worktree | None:
    wanted = _real(root)
    for entry in worktrees:
        if _real(entry.path) == wanted:
            return entry
    return None


def _worktree_git_dirs(common: Path) -> list[bytes]:
    """The common directory (main checkout) plus every linked worktree's admin dir."""
    base = os.fsencode(common)
    dirs = [base]
    try:
        with os.scandir(os.path.join(base, b"worktrees")) as entries:
            admin = [e.path for e in entries if e.is_dir(follow_symlinks=False)]
        dirs.extend(sorted(admin))
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise GitError(f"cannot list linked worktree metadata: {exc.strerror}") from exc
    return dirs


def _read_small(path: bytes) -> str | None:
    try:
        with open(path, "rb") as handle:
            return os.fsdecode(handle.read(4096)).strip()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise GitError(f"cannot read {os.fsdecode(path)!r}: {exc.strerror}") from exc


def _operation_branches(gitdir: bytes) -> set[str]:
    """Branch names/refs a rebase or bisect in progress under ``gitdir`` restores."""
    held: set[str] = set()
    for name in (b"rebase-merge", b"rebase-apply"):
        directory = os.path.join(gitdir, name)
        if _lstat_or_none(directory) is None:
            continue
        head_name = _read_small(os.path.join(directory, b"head-name"))
        if head_name is None:
            if _lstat_or_none(os.path.join(directory, b"applying")) is not None:
                continue  # git am: HEAD itself already names the branch
            raise GitError(
                f"cannot tell which branch the operation in {os.fsdecode(directory)!r} "
                "will restore"
            )
        held.add(head_name)
    start = _read_small(os.path.join(gitdir, b"BISECT_START"))
    if start is not None:
        held.add(start)
    return held


# -- worktree activity ----------------------------------------------------------

_PROC_ALL_PIDS = 1
_PROC_PIDVNODEPATHINFO = 9
_VNODEPATHINFO_SIZE = 2352
_LIBPROC = "/usr/lib/libproc.dylib"
_PS_DEADLINE = 10.0


class _VInfoStat(ctypes.Structure):
    _fields_ = [
        ("vst_dev", ctypes.c_uint32),
        ("vst_mode", ctypes.c_uint16),
        ("vst_nlink", ctypes.c_uint16),
        ("vst_ino", ctypes.c_uint64),
        ("vst_uid", ctypes.c_uint32),
        ("vst_gid", ctypes.c_uint32),
        ("vst_atime", ctypes.c_int64),
        ("vst_atimensec", ctypes.c_int64),
        ("vst_mtime", ctypes.c_int64),
        ("vst_mtimensec", ctypes.c_int64),
        ("vst_ctime", ctypes.c_int64),
        ("vst_ctimensec", ctypes.c_int64),
        ("vst_birthtime", ctypes.c_int64),
        ("vst_birthtimensec", ctypes.c_int64),
        ("vst_size", ctypes.c_int64),
        ("vst_blocks", ctypes.c_int64),
        ("vst_blksize", ctypes.c_int32),
        ("vst_flags", ctypes.c_uint32),
        ("vst_gen", ctypes.c_uint32),
        ("vst_rdev", ctypes.c_uint32),
        ("vst_qspare", ctypes.c_int64 * 2),
    ]


class _VInfo(ctypes.Structure):
    _fields_ = [
        ("vi_stat", _VInfoStat),
        ("vi_type", ctypes.c_int),
        ("vi_pad", ctypes.c_int),
        ("vi_fsid", ctypes.c_int32 * 2),
    ]


class _VInfoPath(ctypes.Structure):
    _fields_ = [("vip_vi", _VInfo), ("vip_path", ctypes.c_char * 1024)]


class _VnodePathInfo(ctypes.Structure):
    """``struct proc_vnodepathinfo``: the current and root directory of a process."""

    _fields_ = [("pvi_cdir", _VInfoPath), ("pvi_rdir", _VInfoPath)]


@dataclass(frozen=True)
class _ProcessScan:
    """What one pass over the process table could and could not observe."""

    source: str
    cwds: tuple[tuple[int, str], ...]
    foreign: int  # other-user processes whose working directory the OS withholds
    gaps: tuple[str, ...]  # reasons the inventory cannot be trusted as complete


def _process_owners() -> dict[int, int]:
    """``pid -> effective uid`` for every process, from ``ps``."""
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,uid="],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=_PS_DEADLINE,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitError(f"cannot run ps: {exc}") from exc
    if result.returncode != 0:
        raise GitError(f"ps failed (exit {result.returncode})")
    owners: dict[int, int] = {}
    for line in result.stdout.decode("ascii", "replace").splitlines():
        fields = line.split()
        if not fields:
            continue
        numeric = all(item.isascii() and item.isdigit() for item in fields)
        if len(fields) != 2 or not numeric:
            raise GitError("unparseable ps output")
        owners[int(fields[0])] = int(fields[1])
    return owners


def _scan_libproc() -> _ProcessScan:
    """macOS: every process's current directory through ``proc_pidinfo``."""
    if ctypes.sizeof(_VnodePathInfo) != _VNODEPATHINFO_SIZE:
        raise GitError("unexpected libproc structure layout")
    try:
        lib = ctypes.CDLL(_LIBPROC, use_errno=True)
        list_pids = lib.proc_listpids
        pid_info = lib.proc_pidinfo
    except (OSError, AttributeError) as exc:
        raise GitError(f"cannot load libproc: {exc}") from exc
    list_pids.argtypes = [
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_int,
    ]
    list_pids.restype = ctypes.c_int
    pid_info.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint64,
        ctypes.c_void_p,
        ctypes.c_int,
    ]
    pid_info.restype = ctypes.c_int

    needed: int = list_pids(_PROC_ALL_PIDS, 0, None, 0)
    if needed <= 0:
        raise GitError("proc_listpids reported no processes")
    capacity = needed * 2 + 4096
    for _ in range(4):
        buffer = (ctypes.c_int32 * (capacity // 4))()
        filled: int = list_pids(_PROC_ALL_PIDS, 0, buffer, ctypes.sizeof(buffer))
        if filled <= 0:
            raise GitError("proc_listpids failed")
        if filled < ctypes.sizeof(buffer):
            break  # the list did not fill the buffer: it is not truncated
        capacity *= 2
    else:
        raise GitError("the process list kept growing; the inventory is incomplete")
    pids = [buffer[index] for index in range(filled // 4) if buffer[index] > 0]

    cwds: list[tuple[int, str]] = []
    denied: list[int] = []
    gaps: list[str] = []
    for pid in pids:
        info = _VnodePathInfo()
        ctypes.set_errno(0)
        written: int = pid_info(
            pid, _PROC_PIDVNODEPATHINFO, 0, ctypes.byref(info), ctypes.sizeof(info)
        )
        if written == ctypes.sizeof(info):
            raw = bytes(info.pvi_cdir.vip_path)
            if raw:
                cwds.append((pid, os.fsdecode(raw)))
            else:
                gaps.append(f"pid {pid}: no working directory path")
            continue
        code = ctypes.get_errno()
        if code == errno.ESRCH:
            continue  # exited, or a zombie, which holds no working directory
        if code in (errno.EPERM, errno.EACCES):
            denied.append(pid)
        else:
            gaps.append(f"pid {pid}: libproc error {code}")

    foreign = 0
    if denied:
        try:
            owners = _process_owners()
        except GitError as exc:
            gaps.append(
                f"{len(denied)} processes withheld their working directory and their "
                f"owner could not be established: {exc}"
            )
        else:
            me = os.geteuid()
            for pid in denied:
                owner = owners.get(pid)
                if owner is None:
                    continue  # exited since
                if owner == me:
                    gaps.append(
                        f"pid {pid}: a process of this user withheld its directory"
                    )
                else:
                    foreign += 1
    if os.getpid() not in {pid for pid, _ in cwds}:
        gaps.append("this process is missing from the inventory")
    return _ProcessScan("libproc", tuple(cwds), foreign, tuple(gaps))


def _scan_procfs() -> _ProcessScan:
    """Linux: every process's current directory through ``/proc/<pid>/cwd``."""
    try:
        names = os.listdir("/proc")
    except OSError as exc:
        raise GitError(f"cannot list /proc: {exc.strerror}") from exc
    me = os.geteuid()
    cwds: list[tuple[int, str]] = []
    gaps: list[str] = []
    foreign = 0
    for name in names:
        if not (name.isascii() and name.isdigit()):
            continue
        pid = int(name)
        try:
            cwds.append((pid, os.readlink(f"/proc/{name}/cwd")))
        except (FileNotFoundError, ProcessLookupError, NotADirectoryError):
            continue  # exited, or a zombie
        except PermissionError:
            try:
                owner = os.stat(f"/proc/{name}").st_uid
            except OSError:
                continue
            if owner == me:
                gaps.append(f"pid {pid}: a process of this user withheld its directory")
            else:
                foreign += 1
        except OSError as exc:
            gaps.append(f"pid {pid}: {exc.strerror}")
    if os.getpid() not in {pid for pid, _ in cwds}:
        gaps.append("this process is missing from the inventory")
    return _ProcessScan("procfs", tuple(cwds), foreign, tuple(gaps))


def _scan_processes() -> _ProcessScan:
    if sys.platform == "darwin":
        return _scan_libproc()
    if sys.platform.startswith("linux"):
        return _scan_procfs()
    raise GitError(f"process inspection is not implemented on {sys.platform}")


def _inside_tree(cwd: str, root: tuple[int, int]) -> bool | None:
    """Whether ``cwd`` is the tree with device/inode ``root`` or below it.

    Identity, not spelling: case-insensitive, normalising and symlinked paths
    still match. ``None`` when ``cwd`` cannot be resolved from here (deleted, or
    in another mount namespace); other filesystem errors propagate.
    """
    current = cwd
    unresolved = False
    while True:
        try:
            st = os.stat(current)
        except (FileNotFoundError, NotADirectoryError):
            return None
        except PermissionError:
            unresolved = True
            parent = os.path.dirname(current)
            if parent == current:
                return None
            current = parent
            continue
        if (st.st_dev, st.st_ino) == root:
            return True
        parent = os.path.dirname(current)
        if parent == current:
            return None if unresolved else False
        current = parent


def worktree_activity(path: Path | str) -> Activity:
    """Whether any process has its working directory inside the tree at ``path``.

    Observation is real, not inferred: ``proc_pidinfo`` through ``libproc`` on
    macOS and ``/proc/<pid>/cwd`` on Linux. ``ACTIVE`` (a process is inside)
    always wins. ``UNKNOWN`` when the tree cannot be examined, the platform is
    unsupported, the inventory is unavailable/truncated, any live process
    withholds its directory, or a directory cannot be resolved. INACTIVE
    requires a complete working-directory inventory. This boundary does not
    inventory open files, executables, or unsaved editor buffers.
    """
    try:
        root = os.stat(_real(path))
    except OSError as exc:
        return Activity("UNKNOWN", f"cannot examine {path}: {exc.strerror}")
    if not stat.S_ISDIR(root.st_mode):
        return Activity("UNKNOWN", f"{path} is not a directory")
    try:
        scan = _scan_processes()
    except (GitError, OSError) as exc:
        return Activity("UNKNOWN", f"the process inventory is unavailable: {exc}")

    identity = (root.st_dev, root.st_ino)
    verdicts: dict[str, bool | None] = {}
    inside: list[int] = []
    unresolved = 0
    gaps = list(scan.gaps)
    for pid, cwd in scan.cwds:
        if cwd not in verdicts:
            try:
                verdicts[cwd] = _inside_tree(cwd, identity)
            except OSError as exc:
                verdicts[cwd] = None
                gaps.append(f"pid {pid}: cannot resolve {cwd!r}: {exc.strerror}")
        verdict = verdicts[cwd]
        if verdict:
            inside.append(pid)
        elif verdict is None:
            unresolved += 1
    if scan.foreign:
        gaps.append(f"{scan.foreign} other-user process directories are withheld")
    if unresolved:
        gaps.append(f"{unresolved} process directories cannot be resolved")
    if inside:
        extra = f" and {len(inside) - 1} more" if len(inside) > 1 else ""
        return Activity(
            "ACTIVE",
            f"pid {inside[0]}{extra} has its working directory inside this tree",
        )
    if gaps:
        shown = "; ".join(gaps[:3])
        more = f" (+{len(gaps) - 3} more)" if len(gaps) > 3 else ""
        return Activity(
            "UNKNOWN", f"the process inventory is incomplete: {shown}{more}"
        )
    return Activity(
        "INACTIVE",
        f"no process in the complete {scan.source} inventory of {len(scan.cwds)} "
        "has its working directory inside this tree; open files, executables and "
        "editor buffers are not inventoried (only working directories are observed)",
    )
