"""Real-repository regressions for the Git primitives behind manual stack promotion."""

from __future__ import annotations

import hashlib
import os
import shlex
import stat
import subprocess
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from git_ops import GitError, GitRefused, GitRepository, Promotion

SHARED = "".join(f"line {number}\n" for number in range(1, 11))
PARENT_AUTHOR = ("Parent Author", "parent@example.invalid", "@1690000000 +0000")
FIRST_AUTHOR = ("Child Author", "child@example.invalid", "@1700000000 +0200")
SECOND_AUTHOR = ("Second Author", "second@example.invalid", "@1700000100 -0700")
FIRST_AUTHOR_LINE = b"author Child Author <child@example.invalid> 1700000000 +0200"
FIRST_MESSAGE = b"child: edit shared line two\n\nStack-Id: stack-7\nStack-Position: 2\n"
# No trailing newline: the replay must keep the message byte-for-byte.
SECOND_MESSAGE = b"child: add second file\n\nStack-Id: stack-7\nStack-Position: 2"


@pytest.fixture(autouse=True)
def isolated_git(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in list(os.environ):
        if name.startswith("GIT_") or name.lower().endswith("_proxy"):
            monkeypatch.delenv(name, raising=False)
    home = tmp_path_factory.mktemp("home")
    config = home / "gitconfig"
    config.write_text(
        "[gc]\nauto = 0\n[maintenance]\nauto = false\n[receive]\nautoGC = false\n"
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("NO_PROXY", "*")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Ship Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "ship@example.invalid")


def git(cwd: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=False)
    if check and result.returncode != 0:
        raise AssertionError(
            f"git {args} failed: {result.stderr.decode(errors='replace')}"
        )
    return os.fsdecode(result.stdout).rstrip("\n")


def git_bytes(
    cwd: Path, *args: str, stdin: bytes = b"", env: dict[str, str] | None = None
) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        input=stdin,
        capture_output=True,
        check=False,
        env=None if env is None else {**os.environ, **env},
    )
    if result.returncode != 0:
        raise AssertionError(
            f"git {args} failed: {result.stderr.decode(errors='replace')}"
        )
    return result.stdout


def author_env(author: tuple[str, str, str]) -> dict[str, str]:
    name, email, date = author
    return {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_AUTHOR_DATE": date}


def commit_files(
    repo: Path, files: dict[str, str], message: bytes, author: tuple[str, str, str]
) -> str:
    """Commit ``files`` on the checked-out branch with an exact message and author."""
    for name, content in files.items():
        (repo / name).write_text(content)
    git(repo, "add", "-A")
    tree = git(repo, "write-tree")
    parent = git(repo, "rev-parse", "HEAD")
    new = git_bytes(
        repo,
        "commit-tree",
        "-p",
        parent,
        "-F",
        "-",
        tree,
        stdin=message,
        env=author_env(author),
    )
    oid = new.decode("ascii").strip()
    git(repo, "update-ref", "HEAD", oid, parent)
    return oid


def edit_line(number: int, text: str, source: str = SHARED) -> str:
    lines = source.splitlines(keepends=True)
    lines[number - 1] = f"{text}\n"
    return "".join(lines)


@dataclass(frozen=True)
class Stack:
    """A parent PR squash-landed on ``main`` and its two-commit child on the parent."""

    repo: Path
    base: str
    fork: str
    first: str
    head: str
    landing: str


def build_stack(
    root: Path,
    *,
    trunk: dict[str, str] | None = None,
    child_first: dict[str, str] | None = None,
) -> Stack:
    repo = root / "work"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    (repo / "shared.txt").write_text(SHARED)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-q", "-c", "parent")
    fork = commit_files(
        repo, {"parent.txt": "parent work\n"}, b"parent: add work\n", PARENT_AUTHOR
    )
    git(repo, "switch", "-q", "-c", "child")
    first_files = child_first or {
        "shared.txt": edit_line(2, "line 2 child"),
        "child.txt": "child one\n",
    }
    first = commit_files(repo, first_files, FIRST_MESSAGE, FIRST_AUTHOR)
    head = commit_files(
        repo, {"child2.txt": "child two\n"}, SECOND_MESSAGE, SECOND_AUTHOR
    )
    git(repo, "switch", "-q", "main")
    landing = commit_files(
        repo,
        {"parent.txt": "parent work\n"},
        b"parent: add work (#11)\n",
        PARENT_AUTHOR,
    )
    if trunk is not None:
        landing = commit_files(repo, trunk, b"trunk: later change\n", PARENT_AUTHOR)
    return Stack(
        repo=repo.resolve(),
        base=base,
        fork=fork,
        first=first,
        head=head,
        landing=landing,
    )


def child_tree(stack: Stack, scratch: Path, shared: str) -> str:
    """The expected promoted tree, built independently in a scratch index."""
    return tree_with(
        stack.repo,
        stack.landing,
        {"shared.txt": shared, "child.txt": "child one\n", "child2.txt": "child two\n"},
        scratch,
    )


def tree_with(repo: Path, base: str, files: dict[str, str], scratch: Path) -> str:
    """Tree of ``base`` with ``files`` replaced, composed in a scratch index file."""
    env = {"GIT_INDEX_FILE": str(scratch)}
    git_bytes(repo, "read-tree", base, env=env)
    for name, content in files.items():
        blob = git_bytes(repo, "hash-object", "-w", "--stdin", stdin=content.encode())
        entry = f"100644,{blob.decode('ascii').strip()},{name}"
        git_bytes(repo, "update-index", "--add", "--cacheinfo", entry, env=env)
    return git_bytes(repo, "write-tree", env=env).decode("ascii").strip()


def commit_parts(repo: Path, oid: str) -> tuple[bytes, bytes, bytes | None]:
    """The author line, message bytes and encoding line of a raw commit object."""
    raw = git_bytes(repo, "cat-file", "commit", oid)
    headers, _, message = raw.partition(b"\n\n")
    lines = headers.split(b"\n")
    authors = [line for line in lines if line.startswith(b"author ")]
    encodings = [line for line in lines if line.startswith(b"encoding ")]
    assert len(authors) == 1 and len(encodings) <= 1
    return authors[0], message, encodings[0] if encodings else None


def range_commits(repo: Path, start: str, tip: str) -> list[str]:
    return git(repo, "rev-list", "--reverse", f"{start}..{tip}").splitlines()


def ref_map(repo: Path) -> dict[str, str]:
    refs: dict[str, str] = {}
    listing = git(repo, "for-each-ref", "--format=%(refname) %(objectname)")
    for line in listing.splitlines():
        name, _, value = line.partition(" ")
        refs[name] = value
    return refs


def tree_state(root: Path) -> dict[str, tuple[int, int, int, str]]:
    """Every directory, file and link below ``root`` (``root`` included).

    Each entry records its mode, size, modification time in nanoseconds and its
    content: a SHA-256 for a file, the target for a link. For a working tree
    this covers the worktree files and the whole ``.git`` directory: objects,
    packs, refs, index, configuration, logs and locks.
    """
    state: dict[str, tuple[int, int, int, str]] = {}
    for directory, directories, files in os.walk(root):
        for name in [".", *directories, *files]:
            path = Path(directory, name)
            info = path.lstat()
            if stat.S_ISREG(info.st_mode):
                content = hashlib.sha256(path.read_bytes()).hexdigest()
            elif stat.S_ISLNK(info.st_mode):
                content = os.readlink(path)
            else:
                content = ""
            relative = os.path.normpath(os.path.relpath(path, root))
            state[relative] = (info.st_mode, info.st_size, info.st_mtime_ns, content)
    return state


def has_object(repo: Path, oid: str) -> bool:
    probe = subprocess.run(
        ["git", "cat-file", "-e", oid], cwd=repo, capture_output=True, check=False
    )
    return probe.returncode == 0


def private_tempdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Make ``tempfile`` create its directories in a fresh, observable place."""
    location = tmp_path / "tmp"
    location.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(location))
    return location


def without(refs: dict[str, str], name: str) -> dict[str, str]:
    return {ref: value for ref, value in refs.items() if ref != name}


# -- promotion ----------------------------------------------------------------------


def test_promote_slice_after_squash_landing_replays_only_the_child_commits(
    tmp_path: Path,
) -> None:
    stack = build_stack(tmp_path)
    repo = GitRepository(stack.repo)
    shared = edit_line(2, "line 2 child")
    expected = child_tree(stack, tmp_path / "scratch.index", shared)
    refs_before = ref_map(stack.repo)
    index_before = (stack.repo / ".git" / "index").read_bytes()

    promotion = repo.promote_slice(stack.fork, stack.head, stack.landing)

    assert (promotion.fork, promotion.old_head, promotion.landing) == (
        stack.fork,
        stack.head,
        stack.landing,
    )
    assert promotion.commits == 2
    assert promotion.expected_tree == expected
    assert git(stack.repo, "rev-parse", f"{promotion.new_head}^{{tree}}") == expected
    replayed = range_commits(stack.repo, stack.landing, promotion.new_head)
    assert len(replayed) == 2
    merges = git(stack.repo, "rev-list", "--merges", f"{stack.landing}..{replayed[-1]}")
    assert merges == ""
    assert [commit_parts(stack.repo, oid) for oid in replayed] == [
        commit_parts(stack.repo, stack.first),
        commit_parts(stack.repo, stack.head),
    ]
    first_author, _, _ = commit_parts(stack.repo, replayed[0])
    _, second_message, _ = commit_parts(stack.repo, replayed[1])
    assert first_author == FIRST_AUTHOR_LINE
    assert second_message == SECOND_MESSAGE
    changed = git(stack.repo, "diff", "--name-only", stack.landing, promotion.new_head)
    assert sorted(changed.splitlines()) == ["child.txt", "child2.txt", "shared.txt"]
    for oid in replayed:
        touched = git(
            stack.repo, "diff-tree", "--no-commit-id", "--name-only", "-r", oid
        )
        assert "parent.txt" not in touched.splitlines()
    assert ref_map(stack.repo) == refs_before
    assert (stack.repo / ".git" / "index").read_bytes() == index_before
    assert git(stack.repo, "status", "--porcelain") == ""
    repo.verify_promotion(promotion)


def test_slice_commits_lists_the_child_commits_oldest_first(tmp_path: Path) -> None:
    stack = build_stack(tmp_path)

    commits = GitRepository(stack.repo).slice_commits(stack.fork, stack.head)

    assert [commit.oid for commit in commits] == [stack.first, stack.head]
    assert [commit.parent for commit in commits] == [stack.fork, stack.first]
    assert [commit.message for commit in commits] == [FIRST_MESSAGE, SECOND_MESSAGE]
    assert [commit.author for commit in commits] == [
        b"Child Author <child@example.invalid> 1700000000 +0200",
        b"Second Author <second@example.invalid> 1700000100 -0700",
    ]
    assert commits[1].encoding is None
    assert commits[1].tree == git(stack.repo, "rev-parse", f"{stack.head}^{{tree}}")


def test_promote_slice_keeps_later_trunk_changes_on_a_file_the_child_edits(
    tmp_path: Path,
) -> None:
    trunk_shared = edit_line(9, "line 9 trunk")
    stack = build_stack(
        tmp_path, trunk={"shared.txt": trunk_shared, "trunk.txt": "trunk\n"}
    )
    repo = GitRepository(stack.repo)
    both = edit_line(2, "line 2 child", trunk_shared)

    promotion = repo.promote_slice(stack.fork, stack.head, stack.landing)

    expected = tree_with(
        stack.repo,
        stack.landing,
        {"shared.txt": both, "child.txt": "child one\n", "child2.txt": "child two\n"},
        tmp_path / "scratch.index",
    )
    assert promotion.expected_tree == expected
    assert git(stack.repo, "rev-parse", f"{promotion.new_head}^{{tree}}") == expected
    assert git(stack.repo, "show", f"{promotion.new_head}:shared.txt") == both.rstrip()
    assert git(stack.repo, "show", f"{promotion.new_head}:trunk.txt") == "trunk"
    # The child's own blob for shared.txt is not literally reproduced.
    assert git(stack.repo, "rev-parse", f"{promotion.new_head}:shared.txt") != git(
        stack.repo, "rev-parse", f"{stack.head}:shared.txt"
    )
    repo.verify_promotion(promotion)


def test_three_way_tree_matches_an_independent_tree_and_reports_conflicts(
    tmp_path: Path,
) -> None:
    trunk_shared = edit_line(9, "line 9 trunk")
    clean = build_stack(tmp_path / "clean", trunk={"shared.txt": trunk_shared})
    conflicted = build_stack(
        tmp_path / "conflicted", trunk={"shared.txt": edit_line(2, "line 2 trunk")}
    )
    index_before = (clean.repo / ".git" / "index").read_bytes()
    expected = child_tree(
        clean, tmp_path / "scratch.index", edit_line(2, "line 2 child", trunk_shared)
    )

    merged = GitRepository(clean.repo).three_way_tree(
        clean.fork, clean.landing, clean.head
    )
    conflict = GitRepository(conflicted.repo).three_way_tree(
        conflicted.fork, conflicted.landing, conflicted.head
    )

    assert merged == expected
    assert conflict is None
    assert (clean.repo / ".git" / "index").read_bytes() == index_before
    assert git(conflicted.repo, "status", "--porcelain") == ""


def test_promote_slice_refuses_a_conflict_without_writing_a_ref(tmp_path: Path) -> None:
    stack = build_stack(tmp_path, trunk={"shared.txt": edit_line(2, "line 2 trunk")})
    refs_before = ref_map(stack.repo)

    with pytest.raises(GitRefused):
        GitRepository(stack.repo).promote_slice(stack.fork, stack.head, stack.landing)

    trunk_shared = git(stack.repo, "show", "main:shared.txt")
    assert ref_map(stack.repo) == refs_before
    assert git(stack.repo, "status", "--porcelain") == ""
    assert trunk_shared == edit_line(2, "line 2 trunk").rstrip()


def test_promote_slice_refuses_a_merge_commit_in_the_slice(tmp_path: Path) -> None:
    stack = build_stack(tmp_path)
    git(stack.repo, "switch", "-q", "child")
    git(stack.repo, "merge", "-q", "--no-ff", "-m", "merge trunk into child", "main")
    merged = git(stack.repo, "rev-parse", "HEAD")
    git(stack.repo, "switch", "-q", "main")
    later = commit_files(
        stack.repo, {"trunk.txt": "trunk\n"}, b"trunk: later\n", PARENT_AUTHOR
    )
    repo = GitRepository(stack.repo)
    refs_before = ref_map(stack.repo)

    with pytest.raises(GitRefused):
        repo.slice_commits(stack.fork, merged)
    with pytest.raises(GitRefused):
        repo.promote_slice(stack.fork, merged, later)

    assert ref_map(stack.repo) == refs_before


def test_promote_slice_refuses_a_fork_point_that_is_not_an_ancestor(
    tmp_path: Path,
) -> None:
    stack = build_stack(tmp_path)
    repo = GitRepository(stack.repo)

    with pytest.raises(GitRefused):
        repo.slice_commits(stack.landing, stack.head)
    with pytest.raises(GitRefused):
        repo.promote_slice(stack.landing, stack.head, stack.landing)


def test_promote_slice_refuses_an_empty_slice(tmp_path: Path) -> None:
    stack = build_stack(tmp_path)
    repo = GitRepository(stack.repo)

    with pytest.raises(GitRefused):
        repo.slice_commits(stack.head, stack.head)
    with pytest.raises(GitRefused):
        repo.promote_slice(stack.head, stack.head, stack.landing)


def test_promote_slice_refuses_a_commit_that_becomes_empty_on_the_landing(
    tmp_path: Path,
) -> None:
    stack = build_stack(
        tmp_path,
        child_first={"child.txt": "child one\n"},
        trunk={"child.txt": "child one\n"},
    )
    refs_before = ref_map(stack.repo)

    with pytest.raises(GitRefused):
        GitRepository(stack.repo).promote_slice(stack.fork, stack.head, stack.landing)

    assert ref_map(stack.repo) == refs_before


def test_promote_slice_refuses_a_head_already_based_on_the_landing(
    tmp_path: Path,
) -> None:
    stack = build_stack(tmp_path)

    with pytest.raises(GitRefused):
        GitRepository(stack.repo).promote_slice(stack.base, stack.head, stack.fork)


def test_promote_slice_preserves_a_legacy_encoding_header(tmp_path: Path) -> None:
    stack = build_stack(tmp_path)
    git(stack.repo, "switch", "-q", "child")
    (stack.repo / "latin.txt").write_text("latin\n")
    git(stack.repo, "add", "-A")
    tree = git(stack.repo, "write-tree")
    legacy = git_bytes(
        stack.repo,
        "-c",
        "i18n.commitEncoding=ISO-8859-1",
        "commit-tree",
        "-p",
        stack.head,
        "-F",
        "-",
        tree,
        stdin=b"caf\xe9 au lait\n",
        env=author_env(SECOND_AUTHOR),
    )
    legacy_oid = legacy.decode("ascii").strip()
    git(stack.repo, "update-ref", "HEAD", legacy_oid, stack.head)
    git(stack.repo, "switch", "-q", "main")
    repo = GitRepository(stack.repo)

    promotion = repo.promote_slice(stack.fork, legacy_oid, stack.landing)

    last = range_commits(stack.repo, stack.landing, promotion.new_head)[-1]
    assert commit_parts(stack.repo, last) == (
        b"author Second Author <second@example.invalid> 1700000100 -0700",
        b"caf\xe9 au lait\n",
        b"encoding ISO-8859-1",
    )
    repo.verify_promotion(promotion)


def test_promote_slice_refuses_a_commit_header_it_cannot_preserve(
    tmp_path: Path,
) -> None:
    stack = build_stack(tmp_path)
    tree = git(stack.repo, "rev-parse", f"{stack.head}^{{tree}}")
    raw = (
        f"tree {tree}\nparent {stack.first}\n"
        "author Child Author <child@example.invalid> 1700000000 +0200\n"
        "committer Ship Test <ship@example.invalid> 1700000000 +0200\n"
        "change-id zzzzzzzz\n\nchild: add second file\n"
    ).encode()
    crafted = git_bytes(
        stack.repo,
        "hash-object",
        "-t",
        "commit",
        "-w",
        "--literally",
        "--stdin",
        stdin=raw,
    )

    with pytest.raises(GitRefused):
        GitRepository(stack.repo).promote_slice(
            stack.fork, crafted.decode("ascii").strip(), stack.landing
        )


def test_verify_promotion_accepts_the_proof_and_rejects_each_tampered_identity(
    tmp_path: Path,
) -> None:
    stack = build_stack(tmp_path)
    repo = GitRepository(stack.repo)
    promotion = repo.promote_slice(stack.fork, stack.head, stack.landing)
    replayed = range_commits(stack.repo, stack.landing, promotion.new_head)
    # Same trees and messages as the real replay, but not the original authors.
    impostor_first = (
        git_bytes(
            stack.repo,
            "commit-tree",
            "-p",
            stack.landing,
            "-F",
            "-",
            git(stack.repo, "rev-parse", f"{replayed[0]}^{{tree}}"),
            stdin=FIRST_MESSAGE,
        )
        .decode("ascii")
        .strip()
    )
    impostor = (
        git_bytes(
            stack.repo,
            "commit-tree",
            "-p",
            impostor_first,
            "-F",
            "-",
            promotion.expected_tree,
            stdin=SECOND_MESSAGE,
        )
        .decode("ascii")
        .strip()
    )
    landing_tree = git(stack.repo, "rev-parse", f"{stack.landing}^{{tree}}")

    repo.verify_promotion(promotion)
    tampered = [
        replace(promotion, new_head=stack.head),
        replace(promotion, new_head=impostor),
        replace(promotion, expected_tree=landing_tree),
        replace(promotion, commits=3),
        replace(promotion, commits=0),
        replace(promotion, landing=stack.base),
        replace(promotion, fork=stack.base),
        replace(promotion, slice_identity="0" * 64),
        replace(promotion, new_head="1" * 40),
    ]
    for candidate in tampered:
        with pytest.raises(GitRefused):
            repo.verify_promotion(candidate)


@pytest.mark.parametrize("scope", ["repository", "environment"])
def test_promote_slice_refuses_a_signing_policy_before_writing_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scope: str
) -> None:
    stack = build_stack(tmp_path)
    if scope == "repository":
        git(stack.repo, "config", "commit.gpgsign", "true")
        git(stack.repo, "config", "gpg.program", str(tmp_path / "no-such-signer"))
    else:
        monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
        monkeypatch.setenv("GIT_CONFIG_KEY_0", "commit.gpgSign")
        monkeypatch.setenv("GIT_CONFIG_VALUE_0", "yes")
    before = tree_state(stack.repo)

    with pytest.raises(GitRefused):
        GitRepository(stack.repo).promote_slice(stack.fork, stack.head, stack.landing)

    assert tree_state(stack.repo) == before
    assert git(stack.repo, "config", "--type=bool", "commit.gpgsign") == "true"


@pytest.mark.parametrize(
    ("setting", "required"),
    [(None, False), ("true", True), ("yes", True), ("off", False)],
)
def test_signing_required_reads_the_effective_commit_gpgsign_and_writes_nothing(
    tmp_path: Path, setting: str | None, required: bool
) -> None:
    stack = build_stack(tmp_path)
    if setting is not None:
        git(stack.repo, "config", "commit.gpgsign", setting)
    before = tree_state(stack.repo)

    assert GitRepository(stack.repo).signing_required() is required

    assert tree_state(stack.repo) == before


def test_signing_required_refuses_an_unreadable_commit_gpgsign(tmp_path: Path) -> None:
    stack = build_stack(tmp_path)
    git(stack.repo, "config", "commit.gpgsign", "sometimes")

    with pytest.raises(GitError) as raised:
        GitRepository(stack.repo).signing_required()

    assert not isinstance(raised.value, GitRefused)


@pytest.mark.parametrize("header", ["gpgsig", "gpgsig-sha256"])
def test_a_signed_slice_commit_is_refused_before_anything_is_written(
    tmp_path: Path, header: str
) -> None:
    stack = build_stack(tmp_path)
    tree = tree_with(
        stack.repo, stack.head, {"signed.txt": "signed\n"}, tmp_path / "scratch.index"
    )
    raw = (
        f"tree {tree}\nparent {stack.head}\n"
        "author Child Author <child@example.invalid> 1700000200 +0200\n"
        "committer Child Author <child@example.invalid> 1700000200 +0200\n"
        f"{header} -----BEGIN PGP SIGNATURE-----\n \n iQEzBAABCAAdFiEE\n"
        " -----END PGP SIGNATURE-----\n\nchild: signed change\n"
    ).encode()
    stored = git_bytes(
        stack.repo, "hash-object", "-t", "commit", "-w", "--stdin", stdin=raw
    )
    signed = stored.decode("ascii").strip()
    repo = GitRepository(stack.repo)
    before = tree_state(stack.repo)

    with pytest.raises(GitRefused):
        repo.slice_commits(stack.fork, signed)
    with pytest.raises(GitRefused):
        repo.promote_slice(stack.fork, signed, stack.landing)

    assert tree_state(stack.repo) == before
    assert git_bytes(stack.repo, "cat-file", "commit", signed) == raw


def test_an_overlong_slice_is_refused_before_anything_is_written(
    tmp_path: Path,
) -> None:
    stack = build_stack(tmp_path)
    steps: list[str] = []
    for number in range(300):
        start = f"from {stack.head}\n" if number == 0 else ""
        steps.append(
            "commit refs/heads/long\n"
            "committer Ship Test <ship@example.invalid> 1700000000 +0000\n"
            f"data 5\nstep\n{start}\n"
        )
    git_bytes(stack.repo, "fast-import", "--quiet", stdin="".join(steps).encode())
    tip = git(stack.repo, "rev-parse", "refs/heads/long")
    repo = GitRepository(stack.repo)
    before = tree_state(stack.repo)

    with pytest.raises(GitRefused):
        repo.slice_commits(stack.fork, tip)
    with pytest.raises(GitRefused):
        repo.promote_slice(stack.fork, tip, stack.landing)

    assert tree_state(stack.repo) == before


def test_slice_commits_and_verify_promotion_write_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stack = build_stack(tmp_path, trunk={"shared.txt": edit_line(9, "line 9 trunk")})
    repo = GitRepository(stack.repo)
    promotion = repo.promote_slice(stack.fork, stack.head, stack.landing)
    location = private_tempdir(tmp_path, monkeypatch)
    before = tree_state(stack.repo)

    commits = repo.slice_commits(stack.fork, stack.head)
    repo.verify_promotion(promotion)

    assert [commit.oid for commit in commits] == [stack.first, stack.head]
    assert tree_state(stack.repo) == before
    assert list(location.iterdir()) == []


# -- read-only three-way preview ----------------------------------------------------


def test_preview_three_way_matches_the_independent_tree_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trunk_shared = edit_line(9, "line 9 trunk")
    stack = build_stack(tmp_path, trunk={"shared.txt": trunk_shared})
    location = private_tempdir(tmp_path, monkeypatch)
    repo = GitRepository(stack.repo)
    before = tree_state(stack.repo)

    preview = repo.preview_three_way(stack.fork, stack.landing, stack.head)

    assert tree_state(stack.repo) == before
    assert list(location.iterdir()) == []
    assert preview is not None
    assert not has_object(stack.repo, preview)
    both = edit_line(2, "line 2 child", trunk_shared)
    assert preview == child_tree(stack, tmp_path / "scratch.index", both)
    assert repo.three_way_tree(stack.fork, stack.landing, stack.head) == preview


@pytest.mark.parametrize("packed", [False, True])
def test_preview_three_way_of_a_squash_landed_parent_leaves_existing_objects_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, packed: bool
) -> None:
    # The squash landing has the fork's tree, so the result is the existing head tree.
    stack = build_stack(tmp_path)
    if packed:
        git(stack.repo, "gc", "--quiet", "--prune=now")
        assert git(stack.repo, "count-objects", "-v").splitlines()[0] == "count: 0"
    head_tree = git(stack.repo, "rev-parse", f"{stack.head}^{{tree}}")
    location = private_tempdir(tmp_path, monkeypatch)
    before = tree_state(stack.repo)

    preview = GitRepository(stack.repo).preview_three_way(
        stack.fork, stack.landing, stack.head
    )

    assert preview == head_tree
    assert tree_state(stack.repo) == before
    assert list(location.iterdir()) == []


def test_preview_three_way_reports_a_conflict_as_none_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stack = build_stack(tmp_path, trunk={"shared.txt": edit_line(2, "line 2 trunk")})
    location = private_tempdir(tmp_path, monkeypatch)
    before = tree_state(stack.repo)

    preview = GitRepository(stack.repo).preview_three_way(
        stack.fork, stack.landing, stack.head
    )

    assert preview is None
    assert tree_state(stack.repo) == before
    assert list(location.iterdir()) == []


def test_preview_three_way_failure_removes_its_directory_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stack = build_stack(tmp_path)
    location = private_tempdir(tmp_path, monkeypatch)
    before = tree_state(stack.repo)
    # The local transport the preview reads through is forbidden to this process.
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "protocol.file.allow")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "never")

    with pytest.raises(GitError) as raised:
        GitRepository(stack.repo).preview_three_way(
            stack.fork, stack.landing, stack.head
        )

    assert type(raised.value) is GitError
    assert raised.value.uncertain is False
    assert list(location.iterdir()) == []
    assert tree_state(stack.repo) == before


def test_preview_three_way_refuses_unavailable_or_non_commit_ids_before_any_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stack = build_stack(tmp_path)
    tree = git(stack.repo, "rev-parse", f"{stack.head}^{{tree}}")
    location = private_tempdir(tmp_path, monkeypatch)
    repo = GitRepository(stack.repo)
    before = tree_state(stack.repo)

    with pytest.raises(GitError):
        repo.preview_three_way(stack.fork, stack.landing, "1" * 40)
    with pytest.raises(GitError):
        repo.preview_three_way(stack.fork, tree, stack.head)
    with pytest.raises(GitRefused):
        repo.preview_three_way(stack.fork, stack.landing, "HEAD")

    assert list(location.iterdir()) == []
    assert tree_state(stack.repo) == before


def test_preview_three_way_refuses_a_temporary_location_inside_the_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stack = build_stack(tmp_path)
    monkeypatch.setattr(tempfile, "tempdir", str(stack.repo / ".git"))
    before = tree_state(stack.repo)

    with pytest.raises(GitRefused):
        GitRepository(stack.repo).preview_three_way(
            stack.fork, stack.landing, stack.head
        )

    assert tree_state(stack.repo) == before


# -- remote and local ref mutation --------------------------------------------------


@dataclass(frozen=True)
class Hub:
    """A stack whose branches are published on a local bare remote, plus its proof."""

    stack: Stack
    remote: Path
    promotion: Promotion


def build_hub(tmp_path: Path) -> Hub:
    stack = build_stack(tmp_path)
    remote = tmp_path / "remote.git"
    git(tmp_path, "clone", "-q", "--bare", str(stack.repo), str(remote))
    git(stack.repo, "remote", "add", "origin", str(remote))
    promotion = GitRepository(stack.repo).promote_slice(
        stack.fork, stack.head, stack.landing
    )
    return Hub(stack=stack, remote=remote.resolve(), promotion=promotion)


def move_remote_child(hub: Hub, tmp_path: Path) -> str:
    """Another clone publishes one more commit on the remote ``child`` branch."""
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", "-b", "child", str(hub.remote), str(other))
    moved = commit_files(other, {"late.txt": "late\n"}, b"child: late\n", FIRST_AUTHOR)
    git(other, "push", "-q", "origin", "child")
    return moved


def write_hook(hooks: Path, name: str, body: str) -> None:
    hook = hooks / name
    hook.write_text(f"#!/bin/sh\n{body}\n")
    hook.chmod(0o755)


def test_push_rewrite_replaces_the_child_head_under_the_expected_old_lease(
    tmp_path: Path,
) -> None:
    hub = build_hub(tmp_path)
    remote_before = ref_map(hub.remote)

    GitRepository(hub.stack.repo).push_rewrite(
        "origin", "child", hub.promotion.new_head, hub.stack.head
    )

    remote_after = ref_map(hub.remote)
    assert remote_before["refs/heads/child"] == hub.stack.head
    assert remote_after["refs/heads/child"] == hub.promotion.new_head
    assert without(remote_after, "refs/heads/child") == without(
        remote_before, "refs/heads/child"
    )
    assert git(hub.stack.repo, "rev-parse", "refs/heads/child") == hub.stack.head


def test_push_rewrite_refuses_a_stale_expected_old_and_keeps_the_remote_as_moved(
    tmp_path: Path,
) -> None:
    hub = build_hub(tmp_path)
    moved = move_remote_child(hub, tmp_path)

    with pytest.raises(GitRefused):
        GitRepository(hub.stack.repo).push_rewrite(
            "origin", "child", hub.promotion.new_head, hub.stack.head
        )

    assert git(hub.remote, "rev-parse", "refs/heads/child") == moved


def test_push_rewrite_refuses_unsafe_requests_before_pushing(tmp_path: Path) -> None:
    hub = build_hub(tmp_path)
    repo = GitRepository(hub.stack.repo)
    remote_before = ref_map(hub.remote)
    new = hub.promotion.new_head

    with pytest.raises(GitRefused):
        repo.push_rewrite("origin", "main", new, remote_before["refs/heads/main"])
    with pytest.raises(GitRefused):
        repo.push_rewrite("origin", "child", new, None)  # type: ignore[arg-type]
    with pytest.raises(GitRefused):
        repo.push_rewrite("origin", "child", hub.stack.head, hub.stack.head)
    with pytest.raises(GitRefused):
        repo.push_rewrite("origin", "child", "1" * 40, hub.stack.head)

    assert ref_map(hub.remote) == remote_before


def test_push_rewrite_losing_a_race_after_dispatch_is_uncertain_and_keeps_the_winner(
    tmp_path: Path,
) -> None:
    hub = build_hub(tmp_path)
    remote = shlex.quote(str(hub.remote))
    # The concurrent writer lands between the lease check and the remote update.
    write_hook(
        hub.stack.repo / ".git" / "hooks",
        "pre-push",
        "cat >/dev/null\nunset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE\n"
        f"git --git-dir={remote} update-ref refs/heads/child {hub.stack.fork}",
    )

    with pytest.raises(GitError) as error:
        GitRepository(hub.stack.repo).push_rewrite(
            "origin", "child", hub.promotion.new_head, hub.stack.head
        )

    assert type(error.value) is GitError
    assert error.value.uncertain is True
    assert git(hub.remote, "rev-parse", "refs/heads/child") == hub.stack.fork


def test_push_rewrite_unobservable_after_an_accepted_push_is_uncertain(
    tmp_path: Path,
) -> None:
    hub = build_hub(tmp_path)
    write_hook(hub.remote / "hooks", "post-receive", 'mv "$(pwd -P)" "$(pwd -P).gone"')

    with pytest.raises(GitError) as error:
        GitRepository(hub.stack.repo).push_rewrite(
            "origin", "child", hub.promotion.new_head, hub.stack.head
        )

    assert error.value.uncertain is True
    Path(f"{hub.remote}.gone").rename(hub.remote)
    assert git(hub.remote, "rev-parse", "refs/heads/child") == hub.promotion.new_head


def test_push_rewrite_unobservable_after_a_refused_push_is_uncertain(
    tmp_path: Path,
) -> None:
    hub = build_hub(tmp_path)
    write_hook(
        hub.remote / "hooks", "pre-receive", 'mv "$(pwd -P)" "$(pwd -P).gone"\nexit 1'
    )

    with pytest.raises(GitError) as error:
        GitRepository(hub.stack.repo).push_rewrite(
            "origin", "child", hub.promotion.new_head, hub.stack.head
        )

    assert error.value.uncertain is True
    Path(f"{hub.remote}.gone").rename(hub.remote)
    assert git(hub.remote, "rev-parse", "refs/heads/child") == hub.stack.head


def test_advance_local_branch_moves_only_an_exact_unheld_branch(tmp_path: Path) -> None:
    stack = build_stack(tmp_path)
    repo = GitRepository(stack.repo)
    promotion = repo.promote_slice(stack.fork, stack.head, stack.landing)
    refs_before = ref_map(stack.repo)

    advanced = repo.advance_local_branch("child", stack.head, promotion.new_head)

    refs_after = ref_map(stack.repo)
    assert advanced is True
    assert refs_after["refs/heads/child"] == promotion.new_head
    assert without(refs_after, "refs/heads/child") == without(
        refs_before, "refs/heads/child"
    )
    assert git(stack.repo, "symbolic-ref", "HEAD") == "refs/heads/main"
    assert git(stack.repo, "status", "--porcelain") == ""


def test_advance_local_branch_leaves_a_branch_with_extra_local_commits(
    tmp_path: Path,
) -> None:
    stack = build_stack(tmp_path)
    repo = GitRepository(stack.repo)
    promotion = repo.promote_slice(stack.fork, stack.head, stack.landing)
    git(stack.repo, "switch", "-q", "child")
    extra = commit_files(
        stack.repo, {"local.txt": "local\n"}, b"child: local\n", FIRST_AUTHOR
    )
    git(stack.repo, "switch", "-q", "main")
    refs_before = ref_map(stack.repo)

    assert repo.advance_local_branch("child", stack.head, promotion.new_head) is False

    assert ref_map(stack.repo) == refs_before
    assert refs_before["refs/heads/child"] == extra


def test_advance_local_branch_leaves_checked_out_branches(tmp_path: Path) -> None:
    stack = build_stack(tmp_path)
    repo = GitRepository(stack.repo)
    promotion = repo.promote_slice(stack.fork, stack.head, stack.landing)
    linked = tmp_path / "linked"
    git(stack.repo, "worktree", "add", "-q", str(linked), "child")
    (linked / "wip.txt").write_text("dirty\n")
    refs_before = ref_map(stack.repo)

    in_linked = repo.advance_local_branch("child", stack.head, promotion.new_head)
    git(stack.repo, "worktree", "remove", "--force", str(linked))
    git(stack.repo, "switch", "-q", "child")
    in_main = repo.advance_local_branch("child", stack.head, promotion.new_head)

    assert in_linked is False
    assert in_main is False
    assert ref_map(stack.repo) == refs_before
    assert git(stack.repo, "rev-parse", "HEAD") == stack.head


def test_advance_local_branch_reports_an_absent_branch(tmp_path: Path) -> None:
    stack = build_stack(tmp_path)
    repo = GitRepository(stack.repo)
    promotion = repo.promote_slice(stack.fork, stack.head, stack.landing)
    refs_before = ref_map(stack.repo)

    assert repo.advance_local_branch("absent", stack.head, promotion.new_head) is False
    assert ref_map(stack.repo) == refs_before


def test_fetch_commit_acquires_the_advertised_tip_without_writing_refs(
    tmp_path: Path,
) -> None:
    hub = build_hub(tmp_path)
    moved = move_remote_child(hub, tmp_path)
    repo = GitRepository(hub.stack.repo)
    assert repo.resolve_ref(moved) is None
    refs_before = ref_map(hub.stack.repo)

    fetched = repo.fetch_commit("origin", "child", moved)

    assert fetched == moved
    assert git(hub.stack.repo, "cat-file", "-t", moved) == "commit"
    assert ref_map(hub.stack.repo) == refs_before
    assert not (hub.stack.repo / ".git" / "FETCH_HEAD").exists()


def test_fetch_commit_refuses_a_remote_that_advertises_another_tip(
    tmp_path: Path,
) -> None:
    hub = build_hub(tmp_path)
    moved = move_remote_child(hub, tmp_path)
    repo = GitRepository(hub.stack.repo)
    refs_before = ref_map(hub.stack.repo)

    with pytest.raises(GitRefused):
        repo.fetch_commit("origin", "child", hub.stack.head)
    with pytest.raises(GitRefused):
        repo.fetch_commit("origin", "absent", moved)

    assert repo.resolve_ref(moved) is None
    assert ref_map(hub.stack.repo) == refs_before
