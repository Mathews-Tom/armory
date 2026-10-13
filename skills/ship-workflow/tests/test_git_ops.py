"""Real-repository regressions for Git inspection and guarded mutation primitives."""

from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import stat
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import git_ops
import pytest
from git_ops import (
    Activity,
    GitError,
    GitRefused,
    GitRepository,
    Snapshot,
    Worktree,
    parse_remote_identity,
    redact_credentials,
    redact_url,
    worktree_activity,
)

PATHOLOGICAL_NAMES = [
    "with space.txt",
    "line\nbreak.txt",
    "-dash-first.txt",
    "naïve-文件-✓.txt",
    'quo"te.txt',
    "tab\there.txt",
    "back\\slash.txt",
    " leading-space.txt",
    "trailing-space .txt",
]


@pytest.fixture(autouse=True)
def isolated_git(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in list(os.environ):
        if name.startswith("GIT_") or name.lower().endswith("_proxy"):
            monkeypatch.delenv(name, raising=False)
    # Keep background repository writers out of the read-only measurement.
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


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    (path / "tracked.txt").write_text("one\n")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "base")
    return path.resolve()


def commit_all(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


def snap(path: Path) -> Snapshot:
    return GitRepository(path).snapshot()


def porcelain(repo: Path) -> str:
    return git(repo, "status", "--porcelain", "--untracked-files=all")


def tree_state(root: Path) -> dict[str, tuple[int, int, int, str]]:
    """Mode, size, mtime and content hash of every entry, including all of .git."""
    state: dict[str, tuple[int, int, int, str]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            st = path.lstat()
            regular = stat.S_ISREG(st.st_mode)
            digest = hashlib.sha256(path.read_bytes()).hexdigest() if regular else ""
            state[str(path.relative_to(root))] = (
                st.st_mode,
                st.st_size if regular else 0,
                st.st_mtime_ns,
                digest,
            )
    return state


def make_conflict(repo: Path, name: str) -> None:
    (repo / name).write_text("base\n")
    commit_all(repo, "add conflicted file")
    git(repo, "switch", "-q", "-c", "topic")
    (repo / name).write_text("topic\n")
    commit_all(repo, "topic change")
    git(repo, "switch", "-q", "main")
    (repo / name).write_text("main\n")
    commit_all(repo, "main change")


# -- inventory ----------------------------------------------------------------


def test_clean_snapshot_reports_actual_checkout_identity(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "inner.txt").write_text("inner\n")
    commit_all(repo, "add pkg")

    first = snap(repo / "pkg")  # invoked from a subdirectory

    head = git(repo, "rev-parse", "HEAD")
    assert first.root == repo
    assert first.common_dir == repo / ".git"
    assert (first.head, first.branch, first.dirty) == (head, "main", False)
    assert first.conflicts == ()
    assert first.operations == ()
    assert first.remotes == {}
    assert first.worktrees == (
        Worktree(repo, head, "main", locked=False, prunable=False),
    )
    assert len(first.fingerprint) == 64
    assert snap(repo).fingerprint == first.fingerprint


def test_detached_head_has_no_branch(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    git(repo, "checkout", "-q", "--detach")

    result = snap(repo)

    assert result.branch is None
    assert result.worktrees[0].branch is None
    assert result.head == git(repo, "rev-parse", "HEAD")


def test_untracked_only_checkout_is_dirty(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    clean = snap(repo)
    (repo / "scratch.txt").write_text("x")

    dirty = snap(repo)

    assert (clean.dirty, dirty.dirty) == (False, True)
    assert dirty.fingerprint != clean.fingerprint


def test_snapshot_holds_hashes_not_file_contents(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / "notes.txt").write_text("TOP-SECRET-PAYLOAD")
    (repo / "tracked.txt").write_text("ANOTHER-SECRET-PAYLOAD")

    result = snap(repo)

    assert "SECRET-PAYLOAD" not in repr(result)


# -- fingerprint drift ----------------------------------------------------------


def test_unstaged_content_change_with_identical_status_changes_fingerprint(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    target = repo / "tracked.txt"
    target.write_text("aaaa\n")
    status = porcelain(repo)
    first = snap(repo).fingerprint

    target.write_text("bbbb\n")

    assert porcelain(repo) == status == " M tracked.txt"
    assert snap(repo).fingerprint != first
    target.write_text("aaaa\n")
    assert snap(repo).fingerprint == first


def test_staged_content_change_with_identical_status_changes_fingerprint(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    target = repo / "tracked.txt"
    target.write_text("stage-a\n")
    git(repo, "add", "tracked.txt")
    status = porcelain(repo)
    first = snap(repo).fingerprint

    target.write_text("stage-b\n")
    git(repo, "add", "tracked.txt")

    assert porcelain(repo) == status == "M  tracked.txt"
    assert snap(repo).fingerprint != first


def test_untracked_content_change_with_identical_status_changes_fingerprint(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    target = repo / "new" / "deep" / "data.bin"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"\x00\x01")
    status = porcelain(repo)
    first = snap(repo).fingerprint

    target.write_bytes(b"\x00\x02")

    assert porcelain(repo) == status
    assert snap(repo).fingerprint != first


def test_staged_and_unstaged_layers_are_distinguished(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    target = repo / "tracked.txt"
    target.write_text("layer-1\n")
    git(repo, "add", "tracked.txt")
    target.write_text("layer-2\n")
    both = snap(repo).fingerprint
    status = porcelain(repo)

    target.write_text("layer-3\n")  # same MM status, different unstaged bytes
    assert porcelain(repo) == status == "MM tracked.txt"
    assert snap(repo).fingerprint != both


def test_executable_bit_and_symlink_target_changes_alter_fingerprint(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    clean = snap(repo).fingerprint
    (repo / "tracked.txt").chmod(0o755)
    executable = snap(repo).fingerprint
    assert executable != clean

    os.symlink("target-a", repo / "link")
    first = snap(repo).fingerprint
    (repo / "link").unlink()
    os.symlink("target-b", repo / "link")
    assert snap(repo).fingerprint != first


def test_fingerprint_follows_content_not_index_stat_refresh(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    target = repo / "tracked.txt"
    st = target.stat()
    os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    before = snap(repo).fingerprint
    index_before = (repo / ".git" / "index").read_bytes()

    git(repo, "status")  # a plain status refreshes the index stat cache

    assert (repo / ".git" / "index").read_bytes() != index_before
    assert snap(repo).fingerprint == before


@pytest.mark.parametrize("name", PATHOLOGICAL_NAMES)
def test_pathological_paths_are_tracked_through_the_whole_lifecycle(
    tmp_path: Path, name: str
) -> None:
    repo = init_repo(tmp_path / "repo")
    clean = snap(repo)
    target = repo / name
    target.write_text("v1\n")

    untracked = snap(repo)
    target.write_text("v2\n")
    untracked_changed = snap(repo)
    assert untracked.dirty and untracked_changed.fingerprint != untracked.fingerprint

    commit_all(repo, "add pathological name")
    committed = snap(repo)
    assert committed.dirty is False
    target.write_text("v3\n")
    modified = snap(repo)
    assert modified.dirty and modified.fingerprint != committed.fingerprint
    target.unlink()
    deleted = snap(repo)
    assert deleted.dirty and deleted.fingerprint not in {
        committed.fingerprint,
        modified.fingerprint,
    }
    assert clean.fingerprint != committed.fingerprint


def test_nested_untracked_repository_content_counts_but_its_git_dir_does_not(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    nested = repo / "vendor" / "lib"
    nested.mkdir(parents=True)
    git(nested, "init", "-q", "-b", "main")
    (nested / "a.txt").write_text("one\n")
    first = snap(repo).fingerprint

    git(nested, "add", "a.txt")  # rewrites only the nested index
    assert snap(repo).fingerprint == first

    (nested / "a.txt").write_text("two\n")
    assert snap(repo).fingerprint != first


def test_submodule_head_and_content_changes_alter_fingerprint(tmp_path: Path) -> None:
    source = init_repo(tmp_path / "source")
    repo = init_repo(tmp_path / "repo")
    git(
        repo,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(source),
        "sub",
    )
    commit_all(repo, "add submodule")
    clean = snap(repo)
    assert clean.dirty is False

    git(repo / "sub", "commit", "-q", "--allow-empty", "-m", "first")
    first = snap(repo)
    git(repo / "sub", "commit", "-q", "--allow-empty", "-m", "second")
    second = snap(repo)
    (repo / "sub" / "untracked.txt").write_text("x")
    third = snap(repo)

    assert (
        len(
            {
                clean.fingerprint,
                first.fingerprint,
                second.fingerprint,
                third.fingerprint,
            }
        )
        == 4
    )
    assert all(item.dirty for item in (first, second, third))


def test_head_branch_and_remote_changes_alter_fingerprint(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    seen = {snap(repo).fingerprint}

    git(repo, "remote", "add", "origin", "https://github.com/me/repo.git")
    seen.add(snap(repo).fingerprint)
    git(repo, "remote", "set-url", "origin", "https://github.com/me/other.git")
    seen.add(snap(repo).fingerprint)
    git(repo, "branch", "-m", "renamed")
    seen.add(snap(repo).fingerprint)
    git(repo, "commit", "-q", "--allow-empty", "-m", "empty")
    seen.add(snap(repo).fingerprint)

    assert len(seen) == 5


# -- read-only guarantee ---------------------------------------------------------


def test_inspection_preserves_index_bytes_and_filesystem_metadata(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / "second.txt").write_text("two\n")
    commit_all(repo, "second")
    (repo / "staged.txt").write_text("staged\n")
    git(repo, "add", "staged.txt")
    (repo / "second.txt").write_text("changed\n")
    (repo / "untracked.txt").write_text("u\n")
    tracked = repo / "tracked.txt"
    st = tracked.stat()
    os.utime(
        tracked, ns=(st.st_atime_ns, st.st_mtime_ns + 7_000_000_000)
    )  # stale stat cache
    git(repo, "remote", "add", "origin", "https://user:pw@github.com/me/repo.git")
    git(repo, "worktree", "add", "-q", str(tmp_path / "linked"), "-b", "linked")
    index_before = (repo / ".git" / "index").read_bytes()
    state_before = tree_state(repo)
    linked_before = tree_state(tmp_path / "linked")

    inspector = GitRepository(repo)
    result = inspector.snapshot()
    inspector.remote_for("github.com", "me/repo")
    inspector.resolve_ref("HEAD")
    inspector.is_ancestor("HEAD", "HEAD")
    inspector.run("status", "--porcelain=v2")
    GitRepository(tmp_path / "linked").snapshot()

    assert result.dirty
    assert (repo / ".git" / "index").read_bytes() == index_before
    assert tree_state(repo) == state_before
    assert tree_state(tmp_path / "linked") == linked_before

    # Premise: the fixture really is stale enough that an ordinary status writes the index.
    git(repo, "status")
    assert (repo / ".git" / "index").read_bytes() != index_before


def test_repository_configured_fsmonitor_program_is_not_executed(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    marker = tmp_path / "fsmonitor-ran"
    hook = tmp_path / "hook.sh"
    hook.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n")
    hook.chmod(0o755)
    git(repo, "config", "core.fsmonitor", str(hook))

    snap(repo)
    assert not marker.exists()

    git(repo, "status")  # premise: plain Git does run the configured hook
    assert marker.exists()


def test_inspection_ignores_inherited_repository_redirection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(tmp_path / "repo")
    other = init_repo(tmp_path / "other")
    git(other, "commit", "-q", "--allow-empty", "-m", "make heads differ")
    expected_head = git(repo, "rev-parse", "HEAD")
    assert expected_head != git(other, "rev-parse", "HEAD")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    monkeypatch.setenv("GIT_INDEX_FILE", str(other / ".git" / "index"))

    result = snap(repo)

    assert result.root == repo
    assert result.head == expected_head


def test_run_disables_optional_locks_and_enforces_the_deadline(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")

    echoed = GitRepository(repo).run("-c", "alias.opt=!echo $GIT_OPTIONAL_LOCKS", "opt")
    assert echoed.stdout == b"0\n"

    started = time.monotonic()
    with pytest.raises(GitError, match="deadline"):
        GitRepository(repo, timeout=0.5).run("-c", "alias.slow=!sleep 30", "slow")
    assert time.monotonic() - started < 10


def test_run_reports_failures_unless_asked_not_to(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")

    with pytest.raises(GitError, match="exit"):
        GitRepository(repo).run("rev-parse", "--verify", "refs/heads/absent")
    result = GitRepository(repo).run(
        "rev-parse", "--verify", "--quiet", "refs/heads/absent", check=False
    )
    assert result.returncode == 1
    with pytest.raises(GitError):
        GitRepository(repo).run()
    with pytest.raises(GitError):
        GitRepository(repo).run("log", "bad\0arg")


def test_command_errors_do_not_leak_url_credentials(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")

    with pytest.raises(GitError) as raised:
        GitRepository(repo, timeout=30).run(
            "ls-remote", "https://user:hunter2@127.0.0.1:1/x.git"
        )

    assert "hunter2" not in str(raised.value)


# -- failure is never an empty success ------------------------------------------------


def test_unavailable_or_unborn_repositories_raise(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    unborn = tmp_path / "unborn"
    unborn.mkdir()
    git(unborn, "init", "-q", "-b", "main")
    bare = tmp_path / "bare.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))

    for target in (plain, unborn, bare, tmp_path / "missing"):
        with pytest.raises(GitError):
            GitRepository(target).snapshot()
    with pytest.raises(GitError):
        GitRepository(plain).resolve_ref("refs/heads/main")
    with pytest.raises(GitError):
        GitRepository(plain).is_ancestor("HEAD", "HEAD")
    assert GitRepository(unborn).resolve_ref("HEAD") is None
    assert GitRepository(unborn).resolve_ref("refs/heads/main") is None


# -- conflicts and in-progress operations ------------------------------------------------


def test_merge_conflict_reports_unmerged_paths_and_operation(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    name = "con flict\nfile.txt"
    make_conflict(repo, name)
    before = snap(repo).fingerprint
    git(repo, "merge", "topic", check=False)

    conflicted = snap(repo)

    assert conflicted.conflicts == (name,)
    assert conflicted.operations == ("merge",)
    assert conflicted.dirty
    assert conflicted.fingerprint != before

    (repo / name).write_text("resolved\n")
    git(repo, "add", "--", name)
    resolved = snap(repo)
    assert resolved.conflicts == ()
    assert resolved.operations == ("merge",)
    assert resolved.fingerprint != conflicted.fingerprint

    git(repo, "merge", "--abort")
    assert snap(repo).fingerprint == before


def test_rebase_conflict_reports_detached_head_and_operation(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    make_conflict(repo, "file.txt")
    git(repo, "switch", "-q", "topic")
    git(repo, "rebase", "main", check=False)

    result = snap(repo)

    assert result.operations == ("rebase",)
    assert result.conflicts == ("file.txt",)
    assert result.branch is None


def test_cherry_pick_conflict_reports_operation(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    make_conflict(repo, "file.txt")
    git(repo, "cherry-pick", "topic", check=False)

    result = snap(repo)

    assert "cherry-pick" in result.operations
    assert result.conflicts == ("file.txt",)


# -- worktrees and common directories ---------------------------------------------------


def test_worktree_inventory_covers_linked_locked_detached_and_prunable(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    linked = tmp_path / "wt\nnewline ✓"
    locked = tmp_path / "locked tree"
    detached = tmp_path / "detached tree"
    gone = tmp_path / "gone"
    git(repo, "worktree", "add", "-q", str(linked), "-b", "feature/linked")
    git(repo, "worktree", "add", "-q", str(locked), "-b", "locked-branch")
    git(repo, "worktree", "lock", "--reason", "ci running", str(locked))
    git(repo, "worktree", "add", "-q", "--detach", str(detached), "HEAD")
    git(repo, "worktree", "add", "-q", str(gone), "-b", "gone-branch")
    shutil.rmtree(gone)

    from_main = snap(repo)
    by_path = {
        item.path.resolve(): replace(item, path=item.path.resolve())
        for item in from_main.worktrees
    }
    head = git(repo, "rev-parse", "HEAD")

    assert len(from_main.worktrees) == 5
    assert by_path[repo] == Worktree(repo, head, "main", False, False)
    assert by_path[linked.resolve()] == Worktree(
        linked.resolve(), head, "feature/linked", False, False
    )
    assert by_path[locked.resolve()] == Worktree(
        locked.resolve(), head, "locked-branch", True, False
    )
    assert by_path[detached.resolve()] == Worktree(
        detached.resolve(), head, None, False, False
    )
    assert by_path[gone.resolve()].prunable is True
    assert by_path[gone.resolve()].branch == "gone-branch"

    from_linked = snap(linked)
    assert from_linked.root == linked.resolve()
    assert from_linked.common_dir == repo / ".git"
    assert from_linked.branch == "feature/linked"
    assert from_linked.worktrees == from_main.worktrees


def test_worktree_dirtiness_is_per_checkout(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    linked = tmp_path / "linked"
    git(repo, "worktree", "add", "-q", str(linked), "-b", "linked")
    (linked / "only-here.txt").write_text("x")

    assert snap(linked).dirty is True
    assert snap(repo).dirty is False
    assert snap(repo).fingerprint != snap(linked).fingerprint


def test_bare_repository_with_linked_worktree(tmp_path: Path) -> None:
    source = init_repo(tmp_path / "source")
    bare = tmp_path / "hub.git"
    git(tmp_path, "clone", "-q", "--bare", str(source), str(bare))
    checkout = tmp_path / "checkout"
    git(bare, "worktree", "add", "-q", str(checkout), "main")

    result = snap(checkout)

    assert result.common_dir == bare.resolve()
    assert [item.path.resolve() for item in result.worktrees] == [checkout.resolve()]
    assert result.branch == "main"


def test_in_progress_operation_state_is_per_worktree(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    linked = tmp_path / "linked"
    make_conflict(repo, "file.txt")
    git(repo, "worktree", "add", "-q", str(linked), "topic")
    git(linked, "rebase", "main", check=False)

    assert snap(linked).operations == ("rebase",)
    assert snap(repo).operations == ()


# -- refs and ancestry --------------------------------------------------------------------


def test_resolve_ref_distinguishes_absence_from_invalid_and_broken(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    head = git(repo, "rev-parse", "HEAD")
    git(repo, "tag", "-a", "-m", "annotated", "v1")
    git(
        repo, "branch", "refs/heads/zz"
    )  # creates refs/heads/refs/heads/zz, which DWIM would mistake for refs/heads/zz
    (repo / ".git" / "refs" / "heads" / "broken").write_text("1" * 40 + "\n")
    inspector = GitRepository(repo)

    assert inspector.resolve_ref("HEAD") == head
    assert inspector.resolve_ref("refs/heads/main") == head
    assert (
        inspector.resolve_ref("refs/tags/v1")
        == head
        != git(repo, "rev-parse", "refs/tags/v1")
    )
    assert inspector.resolve_ref(head) == head
    assert inspector.resolve_ref("refs/heads/absent") is None
    assert inspector.resolve_ref("refs/heads/zz") is None
    assert inspector.resolve_ref("f" * 40) is None
    for invalid in [
        "main",
        "",
        "-x",
        "refs/heads/a..b",
        "refs/heads/x y",
        "refs/heads/a\nb",
        "HEAD~1",
        head[:12],
        head.upper(),
    ]:
        with pytest.raises(GitError):
            inspector.resolve_ref(invalid)
    with pytest.raises(GitError):
        inspector.resolve_ref("refs/heads/broken")


def test_remote_tracking_refs_resolve_without_touching_the_remote(
    tmp_path: Path,
) -> None:
    source = init_repo(tmp_path / "source")
    remote = tmp_path / "remote.git"
    git(tmp_path, "clone", "-q", "--bare", str(source), str(remote))
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(remote), str(clone))
    git(source, "commit", "-q", "--allow-empty", "-m", "new upstream work")
    git(source, "push", "-q", str(remote), "main")
    remote_before = tree_state(remote)
    clone_before = tree_state(clone)

    inspector = GitRepository(clone)
    result = inspector.snapshot()

    assert result.remotes == {"origin": str(remote)}
    assert (
        inspector.resolve_ref("refs/remotes/origin/main") == result.head
    )  # no fetch happened
    assert inspector.remote_for("github.com", "me/repo") is None
    assert tree_state(remote) == remote_before
    assert tree_state(clone) == clone_before


def test_is_ancestor_separates_non_ancestry_from_unknown_revisions(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-q", "-c", "side")
    git(repo, "commit", "-q", "--allow-empty", "-m", "side")
    side = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-q", "main")
    git(repo, "commit", "-q", "--allow-empty", "-m", "main")
    main = git(repo, "rev-parse", "HEAD")
    inspector = GitRepository(repo)

    assert inspector.is_ancestor(base, main) is True
    assert inspector.is_ancestor(main, main) is True
    assert inspector.is_ancestor("refs/heads/main", "refs/heads/side") is False
    assert inspector.is_ancestor(main, base) is False
    assert inspector.is_ancestor(base, side) is True
    with pytest.raises(GitError):
        inspector.is_ancestor("f" * 40, main)
    with pytest.raises(GitError):
        inspector.is_ancestor(main, "refs/heads/absent")
    with pytest.raises(GitError):
        inspector.is_ancestor("main", main)


# -- remotes and identities -----------------------------------------------------------------


def test_remote_urls_are_credential_free_in_snapshots(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    git(
        repo, "remote", "add", "origin", "https://octo:s3cr3t-pw@github.com/me/repo.git"
    )
    git(repo, "remote", "add", "upstream", "git@github.com:orig/repo.git")
    git(
        repo,
        "config",
        "remote.upstream.pushurl",
        "https://ghp_tokenonly@github.com/orig/repo.git?x=1",
    )

    result = snap(repo)

    assert result.remotes == {
        "origin": "https://github.com/me/repo.git",
        "upstream": "github.com:orig/repo.git",
    }
    assert "s3cr3t" not in repr(result)
    assert "ghp_tokenonly" not in repr(result)


def test_fork_head_and_base_resolve_to_distinct_remotes(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    git(repo, "remote", "add", "origin", "https://github.com/me/repo.git")
    git(repo, "remote", "add", "upstream", "ssh://git@github.com/Orig/Repo")
    git(repo, "remote", "add", "elsewhere", "https://ghe.example.com/me/repo.git")
    inspector = GitRepository(repo)

    assert inspector.remote_for("github.com", "orig/repo") == "upstream"
    assert inspector.remote_for("GitHub.com", "ME/repo") == "origin"
    assert inspector.remote_for("ghe.example.com", "me/repo") == "elsewhere"
    assert inspector.remote_for("github.com", "other/repo") is None
    assert inspector.remote_for("ghe.example.com", "orig/repo") is None


def test_url_rewrites_are_honoured_when_resolving_the_push_destination(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    git(repo, "config", "url.https://ghe.example.com/.insteadOf", "gh:")
    git(repo, "remote", "add", "mirror", "gh:team/repo.git")
    inspector = GitRepository(repo)

    assert inspector.remote_for("ghe.example.com", "team/repo") == "mirror"
    assert inspector.snapshot().remotes == {
        "mirror": "https://ghe.example.com/team/repo.git"
    }


def test_ambiguous_remote_identities_raise_instead_of_guessing(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    git(repo, "remote", "add", "one", "https://github.com/me/repo.git")
    git(repo, "remote", "add", "two", "git@github.com:me/repo.git")
    git(repo, "remote", "add", "split", "https://github.com/me/split.git")
    git(repo, "config", "remote.split.pushurl", "https://github.com/other/split.git")
    inspector = GitRepository(repo)

    with pytest.raises(GitError, match="all resolve"):
        inspector.remote_for("github.com", "me/repo")
    with pytest.raises(GitError, match="different repositories"):
        inspector.remote_for("github.com", "me/split")
    with pytest.raises(GitError, match="different repositories"):
        inspector.remote_for("github.com", "other/split")
    assert inspector.remote_for("github.com", "nobody/nothing") is None


@pytest.mark.parametrize(
    "host",
    [
        "",
        "github.com/evil",
        "git hub.com",
        "github.com\nevil",
        "-bad.example.com",
        "github.com:",
        "git@github.com",
    ],
)
def test_invalid_hosts_are_rejected(tmp_path: Path, host: str) -> None:
    repo = init_repo(tmp_path / "repo")
    with pytest.raises(GitError):
        GitRepository(repo).remote_for(host, "me/repo")


@pytest.mark.parametrize(
    "full_name",
    [
        "",
        "owner",
        "a/b/c",
        "../x",
        "a/..",
        "a/b c",
        "/a/b",
        "a/b/",
        "a//b",
        "o/r.git",
        "a/b\n",
        "a%2fb/c",
    ],
)
def test_invalid_repository_names_are_rejected(tmp_path: Path, full_name: str) -> None:
    repo = init_repo(tmp_path / "repo")
    with pytest.raises(GitError):
        GitRepository(repo).remote_for("github.com", full_name)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/o/r.git", ("github.com", "o/r")),
        ("https://user:pw@GitHub.com/o/r", ("github.com", "o/r")),
        ("https://github.com/o/r/", ("github.com", "o/r")),
        ("https://github.com:443/o/r.git", ("github.com", "o/r")),
        ("https://ghe.example.com:8443/o/r.git", ("ghe.example.com:8443", "o/r")),
        ("git@github.com:o/r.git", ("github.com", "o/r")),
        ("github.com:o/r", ("github.com", "o/r")),
        ("ssh://git@github.com/o/r.git", ("github.com", "o/r")),
        ("ssh://git@ghe.example.com:2222/o/r.git", ("ghe.example.com", "o/r")),
        ("ssh://git@ssh.github.com:443/o/r.git", ("github.com", "o/r")),
        ("git://github.com/o/r.git", ("github.com", "o/r")),
        ("https://github.com/o/r.git?tab=x#frag", ("github.com", "o/r")),
        ("/srv/git/o/r.git", None),
        ("file:///srv/git/o/r.git", None),
        ("../relative/o/r", None),
        ("https://github.com/o", None),
        ("https://gitlab.example.com/group/sub/r.git", None),
        ("https://github.com/o%2fx/r.git", None),
        ("https://github.com:notaport/o/r.git", None),
        ("ext::sh -c 'echo x' o/r", None),
        ("origin", None),
    ],
)
def test_remote_identity_parsing(url: str, expected: tuple[str, str] | None) -> None:
    assert parse_remote_identity(url) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://user:pw@github.com/o/r.git", "https://github.com/o/r.git"),
        ("https://token@github.com/o/r.git?x=1#f", "https://github.com/o/r.git"),
        ("https://u:p@ss@github.com/o/r.git", "https://github.com/o/r.git"),
        ("ssh://git@github.com:22/o/r.git", "ssh://github.com:22/o/r.git"),
        ("git@github.com:o/r.git", "github.com:o/r.git"),
        ("/srv/git/r.git", "/srv/git/r.git"),
        ("file:///srv/git/r.git", "file:///srv/git/r.git"),
    ],
)
def test_url_redaction(url: str, expected: str) -> None:
    assert redact_url(url) == expected


def test_free_text_credential_redaction() -> None:
    text = "fatal: unable to access 'https://user:hunter2@example.com/x.git/': refused"
    assert "hunter2" not in redact_credentials(text)
    assert "example.com/x.git" in redact_credentials(text)


# -- guarded mutation fixtures ----------------------------------------------------------


def oid(repo: Path, ref: str) -> str:
    return git(repo, "rev-parse", ref)


def ref_map(repo: Path) -> dict[str, str]:
    refs: dict[str, str] = {}
    listing = git(repo, "for-each-ref", "--format=%(refname) %(objectname)")
    for line in listing.splitlines():
        name, _, value = line.partition(" ")
        refs[name] = value
    return refs


def write_hook(repo: Path, name: str, body: str) -> None:
    hook = repo / ".git" / "hooks" / name
    hook.write_text(f"#!/bin/sh\n{body}\n")
    hook.chmod(0o755)


def make_hub(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A source repository, a bare remote cloned from it and a working clone of it."""
    source = init_repo(tmp_path / "source")
    remote = tmp_path / "remote.git"
    git(tmp_path, "clone", "-q", "--bare", str(source), str(remote))
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(remote), str(clone))
    return source, remote, clone.resolve()


def push_commit(
    source: Path, remote: Path, filename: str, content: str = "new\n", ref: str = "main"
) -> str:
    """Commit ``filename`` on ``source``'s HEAD and publish it as ``remote``'s ``ref``."""
    (source / filename).write_text(content)
    commit_all(source, f"add {filename}")
    git(source, "push", "-q", str(remote), f"HEAD:refs/heads/{ref}")
    return oid(source, "HEAD")


def stage_base_update(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    """A clean clone parked on ``feature`` whose base moved upstream and was fetched."""
    source, remote, clone = make_hub(tmp_path)
    git(clone, "switch", "-q", "-c", "feature")
    tip = push_commit(source, remote, "next.txt")
    GitRepository(clone).fetch_base("origin", "main", tip)
    return source, remote, clone, tip


def linked_worktree(
    tmp_path: Path, repo: Path, name: str = "linked", branch: str = "feat"
) -> Path:
    path = tmp_path / name
    git(repo, "worktree", "add", "-q", str(path), "-b", branch)
    return path.resolve()


@contextmanager
def child_in(cwd: Path) -> Iterator[subprocess.Popen[bytes]]:
    """A real process whose working directory is ``cwd``."""
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; print('up', flush=True); time.sleep(120)"],
        cwd=cwd,
        stdout=subprocess.PIPE,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline() == b"up\n"
        yield process
    finally:
        process.kill()
        process.wait()
        if process.stdout is not None:
            process.stdout.close()


# -- branch inventories ---------------------------------------------------------------------


def test_local_heads_is_an_exact_read_only_inventory(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    git(repo, "branch", "feature/one")
    git(repo, "branch", "refs/heads/zz")  # really refs/heads/refs/heads/zz
    git(repo, "tag", "-a", "-m", "annotated", "v1")
    expected = {
        name: value
        for name, value in ref_map(repo).items()
        if name.startswith("refs/heads/")
    }
    before = tree_state(repo)

    heads = GitRepository(repo).local_heads()

    assert heads == expected
    assert set(heads) == {
        "refs/heads/main",
        "refs/heads/feature/one",
        "refs/heads/refs/heads/zz",
    }
    assert tree_state(repo) == before

    (repo / ".git" / "refs" / "heads" / "broken").write_text("1" * 40 + "\n")
    with pytest.raises(GitError):
        GitRepository(repo).local_heads()


def test_local_heads_distinguishes_an_empty_repository_from_an_unusable_one(
    tmp_path: Path,
) -> None:
    unborn = tmp_path / "unborn"
    unborn.mkdir()
    git(unborn, "init", "-q", "-b", "main")
    plain = tmp_path / "plain"
    plain.mkdir()

    assert GitRepository(unborn).local_heads() == {}
    for unusable in (plain, tmp_path / "missing"):
        with pytest.raises(GitError):
            GitRepository(unusable).local_heads()


def test_branch_upstream_reports_the_configured_remote_and_remote_ref(
    tmp_path: Path,
) -> None:
    _source, remote, clone = make_hub(tmp_path)
    fork = tmp_path / "fork.git"
    git(tmp_path, "clone", "-q", "--bare", str(remote), str(fork))
    git(clone, "remote", "add", "fork", str(fork))
    git(clone, "branch", "plain")
    git(clone, "branch", "--track", "child", "main")  # upstream is a local branch
    git(clone, "branch", "renamed")
    git(clone, "config", "branch.renamed.remote", "fork")
    git(clone, "config", "branch.renamed.merge", "refs/heads/team/renamed-upstream")
    before = tree_state(clone)
    inspector = GitRepository(clone)

    assert inspector.branch_upstream("main") == ("origin", "refs/heads/main")
    assert inspector.branch_upstream("renamed") == (
        "fork",
        "refs/heads/team/renamed-upstream",
    )
    assert inspector.branch_upstream("plain") is None
    assert inspector.branch_upstream("child") is None
    assert tree_state(clone) == before
    with pytest.raises(GitRefused, match="does not exist"):
        inspector.branch_upstream("absent")
    for unusable in ("", "-x", "a..b", "HEAD"):
        with pytest.raises(GitRefused):
            inspector.branch_upstream(unusable)


@pytest.mark.parametrize(
    "settings",
    [
        [("remote", "origin")],
        [("merge", "refs/heads/main")],
        [("remote", "origin"), ("merge", "refs/tags/v1")],
        [("remote", "origin"), ("merge", "refs/heads/")],
        [("remote", "origin"), ("merge", "main")],
        [("remote", "nope"), ("merge", "refs/heads/main")],
        [("remote", "https://example.invalid/x.git"), ("merge", "refs/heads/main")],
        [("remote", "origin"), ("remote", "origin"), ("merge", "refs/heads/main")],
        [("remote", "origin"), ("merge", "refs/heads/a"), ("merge", "refs/heads/b")],
    ],
)
def test_branch_upstream_never_turns_a_bad_configuration_into_none(
    tmp_path: Path, settings: list[tuple[str, str]]
) -> None:
    repo = init_repo(tmp_path / "repo")
    git(repo, "remote", "add", "origin", "https://example.invalid/me/repo.git")
    git(repo, "branch", "feat")
    for key, value in settings:
        git(repo, "config", "--add", f"branch.feat.{key}", value)

    with pytest.raises(GitError):
        GitRepository(repo).branch_upstream("feat")


def test_branch_upstream_refuses_a_resolution_that_disagrees_with_the_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(tmp_path / "repo")
    git(repo, "remote", "add", "origin", "https://example.invalid/me/repo.git")
    git(repo, "remote", "add", "upstream", "https://example.invalid/org/repo.git")
    git(repo, "branch", "feat")
    git(repo, "config", "branch.feat.remote", "origin")
    git(repo, "config", "branch.feat.merge", "refs/heads/feat")
    inspector = GitRepository(repo)

    with monkeypatch.context() as patch:
        patch.setenv("GIT_CONFIG_COUNT", "1")
        patch.setenv("GIT_CONFIG_KEY_0", "branch.feat.remote")
        patch.setenv("GIT_CONFIG_VALUE_0", "upstream")
        with pytest.raises(GitError, match="differently"):
            inspector.branch_upstream("feat")

    assert inspector.branch_upstream("feat") == ("origin", "refs/heads/feat")


def test_remote_heads_reports_advertised_branches_and_never_hides_failure(
    tmp_path: Path,
) -> None:
    source, remote, clone = make_hub(tmp_path)
    git(source, "push", "-q", str(remote), "HEAD:refs/heads/feature/x")
    git(source, "tag", "v1")
    git(source, "push", "-q", str(remote), "v1")
    tip = oid(source, "HEAD")
    clone_before, remote_before = tree_state(clone), tree_state(remote)

    heads = GitRepository(clone).remote_heads("origin")

    assert heads == {"refs/heads/main": tip, "refs/heads/feature/x": tip}
    assert tree_state(clone) == clone_before
    assert tree_state(remote) == remote_before

    empty = tmp_path / "empty.git"
    git(tmp_path, "init", "-q", "--bare", str(empty))
    git(clone, "remote", "add", "empty", str(empty))
    assert GitRepository(clone).remote_heads("empty") == {}  # answered, no branches

    git(clone, "remote", "add", "dead", str(tmp_path / "missing.git"))
    with pytest.raises(GitError):  # an unreachable remote is never an empty inventory
        GitRepository(clone).remote_heads("dead")
    for not_a_remote in (str(remote), "-x", "", "nope", "origin\0"):
        with pytest.raises(GitRefused):
            GitRepository(clone).remote_heads(not_a_remote)


@pytest.mark.parametrize(
    "advertisement",
    [
        b"not-an-oid\trefs/heads/a\n",
        b"1" * 40 + b" refs/heads/a\n",
        b"1" * 40 + b"\trefs/tags/v1\n",
        b"1" * 40 + b"\trefs/heads/\n",
        b"1" * 40 + b"\trefs/heads/a\n" + b"2" * 40 + b"\trefs/heads/a\n",
        b"1" * 40 + b"\trefs/heads/a",
        b"1" * 40 + b"\trefs/heads/a\textra\n",
    ],
)
def test_malformed_or_duplicate_remote_advertisements_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, advertisement: bytes
) -> None:
    repo = init_repo(tmp_path / "repo")
    git(repo, "remote", "add", "origin", "https://example.invalid/me/repo.git")
    real_run = GitRepository.run

    def fake_run(
        self: GitRepository, *args: str, **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        if args[:1] == ("ls-remote",):
            return subprocess.CompletedProcess(list(args), 0, advertisement, b"")
        return real_run(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(GitRepository, "run", fake_run)

    with pytest.raises(GitError):
        GitRepository(repo).remote_heads("origin")


# -- fetching the base ----------------------------------------------------------------------


def test_fetch_base_updates_only_the_base_tracking_ref(tmp_path: Path) -> None:
    source, remote, clone = make_hub(tmp_path)
    old_tip = oid(clone, "main")
    git(source, "push", "-q", str(remote), "HEAD:refs/heads/other")
    git(source, "tag", "v1")
    git(source, "push", "-q", str(remote), "v1")
    tip = push_commit(source, remote, "base-next.txt")
    # a stale tracking ref that ``fetch --prune`` would drop
    git(clone, "update-ref", "refs/remotes/origin/stale", old_tip)
    before = ref_map(clone)

    fetched = GitRepository(clone).fetch_base("origin", "main", tip)

    after = ref_map(clone)
    names = {*before, *after}
    changed = {name for name in names if before.get(name) != after.get(name)}
    assert fetched == tip == after["refs/remotes/origin/main"]
    assert changed - {"refs/remotes/origin/HEAD"} == {"refs/remotes/origin/main"}
    assert "refs/remotes/origin/other" not in after and "refs/tags/v1" not in after
    assert after["refs/remotes/origin/stale"] == old_tip
    assert after["refs/heads/main"] == old_tip  # the local branch is not advanced here
    assert not (clone / ".git" / "FETCH_HEAD").exists()

    with pytest.raises(GitRefused, match="expected"):  # a stale provider SHA
        GitRepository(clone).fetch_base("origin", "main", old_tip)
    assert ref_map(clone) == after


def test_fetch_base_rejects_unusable_arguments_before_touching_anything(
    tmp_path: Path,
) -> None:
    _source, remote, clone = make_hub(tmp_path)
    tip = oid(clone, "main")
    before = tree_state(clone)
    attempts = [
        ("origin", "-x", tip),
        ("origin", "a..b", tip),
        ("origin", "HEAD", tip),
        ("origin", "", tip),
        ("origin", "absent", tip),
        ("origin", "main", tip.upper()),
        ("origin", "main", tip[:12]),
        ("origin", "main", ""),
        (str(remote), "main", tip),
        ("-x", "main", tip),
        ("missing", "main", tip),
    ]

    for name, branch, sha in attempts:
        with pytest.raises(GitRefused):
            GitRepository(clone).fetch_base(name, branch, sha)

    assert tree_state(clone) == before


# -- preparing the retained base checkout ---------------------------------------------------


def test_prepare_base_checkout_fast_forwards_through_normal_hooks(
    tmp_path: Path,
) -> None:
    _source, _remote, clone, tip = stage_base_update(tmp_path)
    switched, merged = tmp_path / "post-checkout-ran", tmp_path / "post-merge-ran"
    write_hook(clone, "post-checkout", f"touch '{switched}'")
    write_hook(clone, "post-merge", f"touch '{merged}'")
    (clone / ".git" / "info" / "exclude").write_text("*.log\n")
    (clone / "cache.log").write_text("keep\n")
    inspector = GitRepository(clone)
    observed = inspector.snapshot()
    old_main = oid(clone, "refs/heads/main")

    result = inspector.prepare_base_checkout("main", tip, observed)

    assert (result.branch, result.head, result.dirty) == ("main", tip, False)
    assert oid(clone, "refs/heads/main") == tip != old_main
    assert (clone / "next.txt").read_text() == "new\n"
    assert (clone / "cache.log").read_text() == "keep\n"
    assert switched.exists() and merged.exists()
    assert porcelain(clone) == ""
    unchanged = inspector.prepare_base_checkout("main", tip, result)
    assert unchanged.fingerprint == result.fingerprint


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        ("dirty", "uncommitted"),
        ("staged", "uncommitted"),
        ("untracked", "uncommitted"),
        ("conflict", "uncommitted"),
        ("locked", "locked"),
        ("stale", "changed"),
        ("foreign", "not the checkout"),
        ("occupied", "checked out in"),
    ],
)
def test_prepare_base_checkout_refuses_unsafe_checkouts_without_changing_anything(
    tmp_path: Path, state: str, reason: str
) -> None:
    source, _remote, clone, tip = stage_base_update(tmp_path)
    target = clone
    if state == "locked":
        target = tmp_path / "locked-tree"
        git(clone, "worktree", "add", "-q", str(target), "-b", "other")
        git(clone, "worktree", "lock", str(target))
        target = target.resolve()
    elif state == "occupied":
        git(clone, "worktree", "add", "-q", str(tmp_path / "base-tree"), "main")
    elif state == "dirty":
        (clone / "tracked.txt").write_text("edited\n")
    elif state == "staged":
        (clone / "tracked.txt").write_text("staged\n")
        git(clone, "add", "tracked.txt")
    elif state == "untracked":
        (clone / "scratch.txt").write_text("x")
    elif state == "conflict":
        make_conflict(clone, "clash.txt")
        git(clone, "merge", "topic", check=False)
    inspector = GitRepository(target)
    observed = inspector.snapshot()
    if state == "stale":
        (target / "tracked.txt").write_text("changed after it was observed\n")
    elif state == "foreign":
        observed = snap(source)
    refs_before = ref_map(clone)
    status_before = porcelain(target)
    branch_before = git(target, "branch", "--show-current")
    head_before = oid(target, "HEAD")

    with pytest.raises(GitRefused, match=reason):
        inspector.prepare_base_checkout("main", tip, observed)

    assert ref_map(clone) == refs_before
    assert porcelain(target) == status_before
    assert git(target, "branch", "--show-current") == branch_before
    assert oid(target, "HEAD") == head_before


def test_prepare_base_checkout_uses_the_worktree_that_already_holds_the_base(
    tmp_path: Path,
) -> None:
    _source, _remote, clone, tip = stage_base_update(tmp_path)
    holder = tmp_path / "base-tree"
    git(clone, "worktree", "add", "-q", str(holder), "main")

    result = GitRepository(holder).prepare_base_checkout("main", tip, snap(holder))

    assert (result.root, result.branch, result.head) == (holder.resolve(), "main", tip)
    # the checkout that was not selected is untouched
    assert git(clone, "branch", "--show-current") == "feature"
    assert oid(clone, "refs/heads/main") == tip


@pytest.mark.parametrize("scenario", ["diverged", "ahead"])
def test_prepare_base_checkout_preserves_local_base_commits(
    tmp_path: Path, scenario: str
) -> None:
    source, remote, clone = make_hub(tmp_path)
    git(clone, "switch", "-q", "-c", "feature")
    git(clone, "switch", "-q", "main")
    (clone / "local-only.txt").write_text("unpublished\n")
    commit_all(clone, "local-only work on the base")
    git(clone, "switch", "-q", "feature")
    tip = oid(clone, "origin/main")
    if scenario == "diverged":
        tip = push_commit(source, remote, "upstream.txt")
        GitRepository(clone).fetch_base("origin", "main", tip)
    local_main = oid(clone, "refs/heads/main")
    inspector = GitRepository(clone)
    observed = inspector.snapshot()

    with pytest.raises(GitRefused, match="not on the base tip"):
        inspector.prepare_base_checkout("main", tip, observed)

    assert oid(clone, "refs/heads/main") == local_main != tip
    assert git(clone, "branch", "--show-current") == "feature"
    assert inspector.snapshot().fingerprint == observed.fingerprint


def test_prepare_base_checkout_never_overwrites_ignored_files(tmp_path: Path) -> None:
    source, remote, clone = make_hub(tmp_path)
    git(clone, "switch", "-q", "-c", "feature")
    (clone / ".git" / "info" / "exclude").write_text("generated.txt\n")
    (clone / "generated.txt").write_text("precious local data\n")
    tip = push_commit(source, remote, "generated.txt", "tracked upstream\n")
    inspector = GitRepository(clone)
    inspector.fetch_base("origin", "main", tip)
    observed = inspector.snapshot()
    main_before = oid(clone, "refs/heads/main")

    with pytest.raises(GitError):
        inspector.prepare_base_checkout("main", tip, observed)

    assert (clone / "generated.txt").read_text() == "precious local data\n"
    # the base is never advanced past the collision
    assert oid(clone, "refs/heads/main") == main_before


def test_prepare_base_checkout_does_not_create_a_missing_local_base(
    tmp_path: Path,
) -> None:
    _source, _remote, clone = make_hub(tmp_path)
    git(clone, "switch", "-q", "-c", "feature")
    git(clone, "branch", "-D", "main")
    tip = oid(clone, "origin/main")
    inspector = GitRepository(clone)

    with pytest.raises(GitRefused, match="does not exist"):
        inspector.prepare_base_checkout("main", tip, inspector.snapshot())

    assert "refs/heads/main" not in inspector.local_heads()
    assert git(clone, "branch", "--show-current") == "feature"


# -- deleting local branches ----------------------------------------------------------------


def test_delete_local_head_is_an_exact_compare_and_swap(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    git(repo, "branch", "feat")
    git(repo, "branch", "keep")
    git(repo, "config", "branch.feat.remote", "origin")
    git(repo, "config", "branch.feat.merge", "refs/heads/feat")
    observed = oid(repo, "refs/heads/feat")
    git(repo, "switch", "-q", "feat")
    (repo / "more.txt").write_text("work added after the branch was observed\n")
    commit_all(repo, "more")
    git(repo, "switch", "-q", "main")
    moved = oid(repo, "refs/heads/feat")
    inspector = GitRepository(repo)

    with pytest.raises(GitRefused, match="not the expected"):
        inspector.delete_local_head("feat", observed)
    assert oid(repo, "refs/heads/feat") == moved

    inspector.delete_local_head("feat", moved)

    assert set(inspector.local_heads()) == {"refs/heads/main", "refs/heads/keep"}
    leftover = git(
        repo, "config", "--local", "--get-regexp", r"^branch\.feat\.", check=False
    )
    assert leftover == ""
    with pytest.raises(GitRefused, match="does not exist"):
        inspector.delete_local_head("feat", moved)
    for unusable in (moved.upper(), moved[:12], ""):
        with pytest.raises(GitRefused):
            inspector.delete_local_head("keep", unusable)
    assert "refs/heads/keep" in inspector.local_heads()


def test_delete_local_head_survives_a_ref_that_moves_during_the_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(tmp_path / "repo")
    git(repo, "branch", "feat")
    expected = oid(repo, "refs/heads/feat")
    git(repo, "commit", "-q", "--allow-empty", "-m", "elsewhere")
    elsewhere = oid(repo, "HEAD")
    real_in_use = GitRepository._branch_in_use

    def racing(self: GitRepository, branch: str) -> str | None:
        reason = real_in_use(self, branch)
        git(repo, "update-ref", "refs/heads/feat", elsewhere)  # another process wins
        return reason

    monkeypatch.setattr(GitRepository, "_branch_in_use", racing)

    with pytest.raises(GitError) as raised:
        GitRepository(repo).delete_local_head("feat", expected)

    # the compare-and-swap itself failed, not a pre-mutation refusal
    assert not isinstance(raised.value, GitRefused)
    assert oid(repo, "refs/heads/feat") == elsewhere


def test_delete_local_head_refuses_branches_that_are_checked_out_or_symbolic(
    tmp_path: Path,
) -> None:
    _source, _remote, clone = make_hub(tmp_path)
    git(clone, "branch", "held")
    git(clone, "branch", "plain")
    git(clone, "branch", "spare")
    held_tree = tmp_path / "held-tree"
    git(clone, "worktree", "add", "-q", str(held_tree), "held")
    git(clone, "symbolic-ref", "refs/heads/alias", "refs/heads/plain")
    inspector = GitRepository(clone)
    heads = inspector.local_heads()

    with pytest.raises(GitRefused, match="checked out"):  # this worktree
        inspector.delete_local_head("main", heads["refs/heads/main"])
    with pytest.raises(GitRefused, match="checked out"):  # another worktree
        inspector.delete_local_head("held", heads["refs/heads/held"])
    # seen from that other worktree
    with pytest.raises(GitRefused, match="checked out"):
        GitRepository(held_tree).delete_local_head("held", heads["refs/heads/held"])
    with pytest.raises(GitRefused, match="not a plain branch"):
        inspector.delete_local_head("alias", heads["refs/heads/alias"])
    assert inspector.local_heads() == heads

    inspector.delete_local_head("spare", heads["refs/heads/spare"])

    assert set(heads) - set(inspector.local_heads()) == {"refs/heads/spare"}


def test_delete_local_head_refuses_a_remotes_default_branch(tmp_path: Path) -> None:
    _source, _remote, clone = make_hub(tmp_path)
    # main is no longer checked out anywhere
    git(clone, "switch", "-q", "-c", "feature")
    inspector = GitRepository(clone)
    main = inspector.local_heads()["refs/heads/main"]

    with pytest.raises(GitRefused, match="default branch"):
        inspector.delete_local_head("main", main)

    assert oid(clone, "refs/heads/main") == main


def test_delete_local_head_refuses_a_branch_held_by_a_rebase_in_progress(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    make_conflict(repo, "file.txt")
    rebasing = tmp_path / "rebasing"
    git(repo, "worktree", "add", "-q", str(rebasing), "topic")
    git(rebasing, "rebase", "main", check=False)
    assert snap(rebasing).operations == ("rebase",)
    topic = oid(repo, "refs/heads/topic")

    with pytest.raises(GitRefused):
        GitRepository(repo).delete_local_head("topic", topic)

    assert oid(repo, "refs/heads/topic") == topic


# -- deleting remote branches ------------------------------------------------------------------


def test_delete_remote_head_removes_only_the_leased_ref_and_verifies_absence(
    tmp_path: Path,
) -> None:
    source, remote, clone = make_hub(tmp_path)
    git(source, "push", "-q", str(remote), "HEAD:refs/heads/feat")
    git(source, "push", "-q", str(remote), "HEAD:refs/heads/keep")
    inspector = GitRepository(clone)
    heads = inspector.remote_heads("origin")

    inspector.delete_remote_head("origin", "feat", heads["refs/heads/feat"])

    remaining = set(inspector.remote_heads("origin"))
    assert remaining == {"refs/heads/main", "refs/heads/keep"}
    assert "refs/heads/feat" not in ref_map(remote)
    with pytest.raises(GitRefused, match="does not advertise"):  # already gone
        inspector.delete_remote_head("origin", "feat", heads["refs/heads/feat"])


def test_delete_remote_head_never_deletes_a_ref_that_changed(tmp_path: Path) -> None:
    source, remote, clone = make_hub(tmp_path)
    git(source, "push", "-q", str(remote), "HEAD:refs/heads/feat")
    observed = oid(source, "HEAD")
    moved = push_commit(source, remote, "moved.txt", ref="moved")
    inspector = GitRepository(clone)

    git(source, "push", "-q", "-f", str(remote), f"{moved}:refs/heads/feat")
    with pytest.raises(GitRefused, match="not the expected"):  # changed before the call
        inspector.delete_remote_head("origin", "feat", observed)
    assert oid(remote, "refs/heads/feat") == moved

    # Changed after the advertisement but before the delete lands: the server-side
    # lease (expected old value) rejects it, and the changed ref survives.
    git(source, "push", "-q", "-f", str(remote), f"{observed}:refs/heads/feat")
    marker = tmp_path / "pre-push-ran"
    write_hook(
        clone,
        "pre-push",
        f"touch '{marker}'\ngit --git-dir='{remote}' update-ref refs/heads/feat {moved}",
    )
    with pytest.raises(GitError) as raised:
        inspector.delete_remote_head("origin", "feat", observed)
    assert marker.exists()  # hooks are honoured, not bypassed
    assert not isinstance(raised.value, GitRefused)
    assert oid(remote, "refs/heads/feat") == moved


def test_delete_remote_head_refuses_the_default_branch_and_unusable_inputs(
    tmp_path: Path,
) -> None:
    _source, remote, clone = make_hub(tmp_path)
    tip = oid(remote, "refs/heads/main")
    inspector = GitRepository(clone)

    with pytest.raises(GitRefused, match="default branch"):
        inspector.delete_remote_head("origin", "main", tip)
    for name, branch, sha in [
        (str(remote), "main", tip),
        ("origin", "-x", tip),
        ("origin", "absent", tip),
        ("origin", "main", tip[:12]),
    ]:
        with pytest.raises(GitRefused):
            inspector.delete_remote_head(name, branch, sha)

    assert oid(remote, "refs/heads/main") == tip


# -- removing worktrees -----------------------------------------------------------------------


def test_remove_worktree_removes_clean_idle_linked_worktrees_through_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = init_repo(tmp_path / "repo")
    tree = linked_worktree(tmp_path, repo)
    detached = tmp_path / "detached"
    git(repo, "worktree", "add", "-q", "--detach", str(detached), "HEAD")
    head = oid(repo, "HEAD")
    inspector = GitRepository(repo)
    monkeypatch.setattr(
        git_ops, "_scan_processes", lambda: git_ops._ProcessScan("procfs", (), 0, ())
    )

    inspector.remove_worktree(tree, head, "feat")
    inspector.remove_worktree(detached.resolve(), head, None)

    assert not tree.exists() and not detached.exists()
    assert [item.path.resolve() for item in snap(repo).worktrees] == [repo]
    # deleting the branch is a separate, separately proven step
    assert oid(repo, "refs/heads/feat") == head
    assert (repo / "tracked.txt").read_text() == "one\n"
    with pytest.raises(GitRefused, match="not a worktree"):
        inspector.remove_worktree(tree, head, "feat")


@pytest.mark.parametrize(
    "case",
    [
        "unstaged",
        "staged",
        "untracked",
        "ignored",
        "locked",
        "git_lock",
        "wrong_head",
        "wrong_branch",
        "rebase",
    ],
)
def test_remove_worktree_keeps_trees_that_are_not_provably_disposable(
    tmp_path: Path, case: str
) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / ".gitignore").write_text("*.log\n")
    commit_all(repo, "ignore logs")
    branch: str | None = "feat"
    if case == "rebase":
        make_conflict(repo, "file.txt")
        tree = tmp_path / "linked"
        git(repo, "worktree", "add", "-q", str(tree), "topic")
        tree = tree.resolve()
        git(tree, "rebase", "main", check=False)
        branch = None  # detached in the middle of the rebase
    else:
        tree = linked_worktree(tmp_path, repo)
    head = oid(tree, "HEAD")
    if case == "unstaged":
        (tree / "tracked.txt").write_text("edited\n")
    elif case == "staged":
        (tree / "tracked.txt").write_text("staged\n")
        git(tree, "add", "tracked.txt")
    elif case == "untracked":
        (tree / "new.txt").write_text("x")
    elif case == "ignored":
        (tree / "debug.log").write_text("user data")
    elif case == "locked":
        git(repo, "worktree", "lock", "--reason", "busy", str(tree))
    elif case == "git_lock":
        admin_dir = Path(git(tree, "rev-parse", "--absolute-git-dir"))
        (admin_dir / "index.lock").write_text("")
    elif case == "wrong_head":
        head = "1" * 40
    elif case == "wrong_branch":
        branch = "other"
    before = tree_state(tree)

    with pytest.raises(GitRefused):
        GitRepository(repo).remove_worktree(tree, head, branch)

    # user data and ignored files are untouched too
    assert tree.exists() and tree_state(tree) == before
    assert any(item.path.resolve() == tree for item in snap(repo).worktrees)


def test_remove_worktree_protects_main_invoking_foreign_and_unregistered_trees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(tmp_path / "repo")
    tree = linked_worktree(tmp_path, repo)
    (tree / "sub").mkdir()
    (tree / "sub" / "f.txt").write_text("f\n")
    commit_all(tree, "tracked subdirectory")
    main_head, head = oid(repo, "HEAD"), oid(tree, "HEAD")
    other = init_repo(tmp_path / "other")
    foreign = linked_worktree(tmp_path, other, name="foreign", branch="elsewhere")
    foreign_head = oid(foreign, "HEAD")
    plain = tmp_path / "plain"
    plain.mkdir()
    attempts = [
        (GitRepository(tree), repo, main_head, "main", "main checkout"),
        (GitRepository(repo), repo, main_head, "main", "invoking checkout"),
        (GitRepository(tree), tree, head, "feat", "invoking checkout"),
        (GitRepository(tree / "sub"), tree, head, "feat", "invoking checkout"),
        (GitRepository(repo), foreign, foreign_head, "elsewhere", "not a worktree"),
        (GitRepository(repo), plain, main_head, None, "not a worktree"),
    ]

    for inspector, target, expected_head, expected_branch, reason in attempts:
        with pytest.raises(GitRefused, match=reason):
            inspector.remove_worktree(target, expected_head, expected_branch)
    # the process's own directory protects a tree from any instance
    monkeypatch.chdir(tree)
    with pytest.raises(GitRefused, match="invoking"):
        GitRepository(repo).remove_worktree(tree, head, "feat")

    for path in (repo, tree, foreign, plain):
        assert path.exists()


def test_remove_worktree_keeps_trees_in_use_or_of_unknown_activity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(tmp_path / "repo")
    tree = linked_worktree(tmp_path, repo)
    head = oid(tree, "HEAD")
    inspector = GitRepository(repo)

    with child_in(tree), pytest.raises(GitRefused, match="not provably idle"):
        inspector.remove_worktree(tree, head, "feat")
    assert tree.exists()

    with monkeypatch.context() as patch:
        patch.setattr(
            git_ops,
            "worktree_activity",
            lambda path: Activity("UNKNOWN", "cannot see the process table"),
        )
        with pytest.raises(GitRefused, match="cannot see the process table"):
            inspector.remove_worktree(tree, head, "feat")
    assert tree.exists()

    monkeypatch.setattr(
        git_ops, "_scan_processes", lambda: git_ops._ProcessScan("procfs", (), 0, ())
    )
    inspector.remove_worktree(tree, head, "feat")  # idle again, so Git removes it
    assert not tree.exists()


# -- process activity ---------------------------------------------------------------------------


def test_worktree_activity_sees_real_child_processes_by_working_directory(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    tree = linked_worktree(tmp_path, repo)
    sibling = tmp_path / "linked-sibling"  # shares a name prefix but is not inside
    sibling.mkdir()
    nested = tree / "deep" / "dir"
    nested.mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(tree)

    with child_in(sibling):
        assert worktree_activity(tree).status != "ACTIVE"
    with child_in(nested) as child:
        active = worktree_activity(tree)
        assert active.status == "ACTIVE", active.reason
        assert str(child.pid) in active.reason
        # the same tree through a symlink
        assert worktree_activity(alias).status == "ACTIVE"
        assert worktree_activity(nested).status == "ACTIVE"


def test_worktree_activity_is_never_inactive_from_an_incomplete_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    gap = ("pid 7: a process of this user withheld its directory",)

    def broken() -> git_ops._ProcessScan:
        raise GitError("the process table cannot be read")

    with monkeypatch.context() as patch:
        patch.setattr(
            git_ops,
            "_scan_processes",
            lambda: git_ops._ProcessScan("procfs", (), 0, gap),
        )
        unknown = worktree_activity(tree)
        assert unknown.status == "UNKNOWN" and "pid 7" in unknown.reason
        patch.setattr(git_ops, "_scan_processes", broken)
        assert worktree_activity(tree).status == "UNKNOWN"
        patch.setattr(  # a proven active process outranks any gap
            git_ops,
            "_scan_processes",
            lambda: git_ops._ProcessScan("procfs", ((4242, str(tree)),), 0, gap),
        )
        assert worktree_activity(tree).status == "ACTIVE"
    assert worktree_activity(tmp_path / "missing").status == "UNKNOWN"


# -- environment protection -----------------------------------------------------------------------


def test_execution_environment_is_a_sanitized_private_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirecting = (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY",
        "GIT_NAMESPACE",
        "GIT_CEILING_DIRECTORIES",
        "GIT_CONFIG",
    )
    for name in redirecting:
        monkeypatch.setenv(name, str(tmp_path / "foreign"))
    monkeypatch.setenv("SHIP_PRESERVED", "yes")
    inspector = GitRepository(tmp_path)

    env = inspector.execution_environment()

    assert not set(redirecting) & set(env)
    assert (env["GIT_OPTIONAL_LOCKS"], env["GIT_TERMINAL_PROMPT"], env["LC_ALL"]) == (
        "0",
        "0",
        "C",
    )
    assert env["SHIP_PRESERVED"] == "yes"
    # supported global configuration stays in place
    assert env["GIT_CONFIG_GLOBAL"] == os.environ["GIT_CONFIG_GLOBAL"]
    env["SHIP_PRESERVED"] = "mutated"
    assert inspector.execution_environment()["SHIP_PRESERVED"] == "yes"


def test_mutations_ignore_inherited_repository_and_config_file_redirection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(tmp_path / "repo")
    other = init_repo(tmp_path / "other")
    for target in (repo, other):
        git(target, "branch", "feat")
    git(repo, "config", "branch.feat.remote", "origin")
    feat, other_feat = oid(repo, "refs/heads/feat"), oid(other, "refs/heads/feat")
    foreign_config = tmp_path / "foreign.cfg"
    foreign_text = '[branch "feat"]\n\tremote = foreign\n'
    foreign_config.write_text(foreign_text)

    with monkeypatch.context() as patch:
        patch.setenv("GIT_DIR", str(other / ".git"))
        patch.setenv("GIT_WORK_TREE", str(other))
        patch.setenv("GIT_INDEX_FILE", str(other / ".git" / "index"))
        patch.setenv("GIT_COMMON_DIR", str(other / ".git"))
        patch.setenv("GIT_CONFIG", str(foreign_config))
        inspector = GitRepository(repo)
        assert inspector.local_heads()["refs/heads/feat"] == feat
        inspector.delete_local_head("feat", feat)

    assert "refs/heads/feat" not in GitRepository(repo).local_heads()
    assert oid(other, "refs/heads/feat") == other_feat
    assert foreign_config.read_text() == foreign_text
    leftover = git(
        repo, "config", "--local", "--get-regexp", r"^branch\.feat\.", check=False
    )
    assert leftover == ""


def test_environment_supplied_config_cannot_select_another_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(tmp_path / "repo")
    other = init_repo(tmp_path / "other")
    inspector = GitRepository(repo)

    with monkeypatch.context() as patch:
        patch.setenv("GIT_CONFIG_COUNT", "3")
        patch.setenv("GIT_CONFIG_KEY_0", "core.worktree")
        patch.setenv("GIT_CONFIG_VALUE_0", str(other))
        patch.setenv("GIT_CONFIG_KEY_1", "alias.shipmark")
        patch.setenv("GIT_CONFIG_VALUE_1", "!echo preserved")
        patch.setenv("GIT_CONFIG_KEY_2", "includeIf.gitdir:/never/.path")
        patch.setenv("GIT_CONFIG_VALUE_2", str(tmp_path / "foreign.cfg"))
        assert inspector.snapshot().root == repo
        # the other entries survive
        assert inspector.run("shipmark").stdout == b"preserved\n"
        counted = inspector.execution_environment()
    assert counted["GIT_CONFIG_COUNT"] == "1"
    assert counted["GIT_CONFIG_KEY_0"] == "alias.shipmark"
    assert counted["GIT_CONFIG_VALUE_0"] == "!echo preserved"
    assert "GIT_CONFIG_KEY_1" not in counted and "GIT_CONFIG_VALUE_2" not in counted

    with monkeypatch.context() as patch:
        patch.setenv(
            "GIT_CONFIG_PARAMETERS",
            f"'core.worktree'='{other}' 'alias.shipmark'='!echo preserved' "
            f"'include.path'='{tmp_path / 'foreign.cfg'}'",
        )
        assert inspector.snapshot().root == repo
        assert inspector.run("shipmark").stdout == b"preserved\n"
        parameters = inspector.execution_environment()["GIT_CONFIG_PARAMETERS"]
    assert shlex.split(parameters) == ["alias.shipmark=!echo preserved"]

    with monkeypatch.context() as patch:
        patch.setenv("GIT_CONFIG_PARAMETERS", f"'core.worktree'='{other}'")
        patch.setenv("GIT_CONFIG_COUNT", "1")
        patch.setenv("GIT_CONFIG_KEY_0", "core.bare")
        patch.setenv("GIT_CONFIG_VALUE_0", "true")
        assert inspector.snapshot().root == repo
        emptied = inspector.execution_environment()
    for name in ("GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0"):
        assert name not in emptied  # nothing but redirecting entries was supplied


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("GIT_CONFIG_COUNT", "x"),
        ("GIT_CONFIG_COUNT", "-1"),
        ("GIT_CONFIG_COUNT", "99999"),
        ("GIT_CONFIG_COUNT", "1"),  # names an entry that is not there
        ("GIT_CONFIG_PARAMETERS", "'unterminated"),
    ],
)
def test_unparseable_config_environment_is_rejected_not_guessed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    repo = init_repo(tmp_path / "repo")
    monkeypatch.setenv(name, value)

    with pytest.raises(GitError):
        GitRepository(repo).snapshot()


def test_a_repository_configured_foreign_work_tree_is_rejected(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    other = init_repo(tmp_path / "other")
    git(repo, "config", "core.worktree", str(other))
    assert Path(git(repo, "rev-parse", "--show-toplevel")).resolve() == other  # premise

    with pytest.raises(GitError):
        GitRepository(repo).snapshot()


def test_a_deadline_marks_the_failure_uncertain(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")

    with pytest.raises(GitError, match="deadline") as timed_out:
        GitRepository(repo, timeout=0.5).run("-c", "alias.slow=!sleep 30", "slow")
    with pytest.raises(GitError) as failed:
        GitRepository(repo).run("rev-parse", "--verify", "refs/heads/absent")

    assert timed_out.value.uncertain is True
    assert failed.value.uncertain is False


# -- landing proof -----------------------------------------------------------------------------------


def build_feature(repo: Path) -> list[str]:
    """Three commits on ``feature``: an edit, a new file and a binary file."""
    git(repo, "switch", "-q", "-c", "feature")
    commits: list[str] = []
    for name, data in (
        ("tracked.txt", b"one\nfeature edit\n"),
        ("added.txt", b"added\n"),
        ("data.bin", b"\0\1\2binary"),
    ):
        (repo / name).write_bytes(data)
        commit_all(repo, f"feature: {name}")
        commits.append(oid(repo, "HEAD"))
    git(repo, "switch", "-q", "main")
    return commits


def test_whole_change_landed_separates_complete_landings_from_partial_ones(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    first, second, feature = build_feature(repo)
    (repo / "unrelated.txt").write_text("the base moved on\n")
    commit_all(repo, "unrelated work on the base")
    base = oid(repo, "HEAD")

    git(repo, "switch", "-q", "-c", "squash-all", base)
    git(repo, "merge", "--squash", "feature")
    git(repo, "commit", "-q", "-m", "squash all three commits")
    squash_all = oid(repo, "HEAD")
    git(repo, "switch", "-q", "-c", "squash-part", base)
    git(repo, "merge", "--squash", second)
    git(repo, "commit", "-q", "-m", "squash only two of three commits")
    squash_part = oid(repo, "HEAD")
    git(repo, "switch", "-q", "-c", "rebase-all", base)
    git(repo, "cherry-pick", first, second, feature)
    rebase_all = oid(repo, "HEAD")
    git(repo, "switch", "-q", "-c", "rebase-part", base)
    git(repo, "cherry-pick", first, second)
    rebase_part = oid(repo, "HEAD")
    git(repo, "switch", "-q", "-c", "merged", base)
    git(repo, "merge", "-q", "--no-ff", "-m", "merge feature", "feature")
    merged = oid(repo, "HEAD")
    git(repo, "switch", "-q", "-c", "reused", "feature")
    (repo / "added-later.txt").write_text("work added after landing\n")
    commit_all(repo, "reused branch gains new work")
    reused = oid(repo, "HEAD")
    git(repo, "switch", "-q", "main")
    inspector = GitRepository(repo)
    before = tree_state(repo)

    assert inspector.whole_change_landed(feature, squash_all, squash_all) is True
    assert inspector.whole_change_landed(feature, rebase_all, rebase_all) is True
    assert inspector.whole_change_landed(feature, merged, merged) is True
    assert inspector.whole_change_landed(second, squash_part, squash_part) is True
    assert inspector.whole_change_landed(second, rebase_part, rebase_part) is True
    # Partial inclusion: the binary file of the third commit never landed.
    assert inspector.whole_change_landed(feature, squash_part, squash_part) is False
    assert inspector.whole_change_landed(feature, rebase_part, rebase_part) is False
    # Added work since the landing is not covered by it.
    assert inspector.whole_change_landed(reused, squash_all, squash_all) is False
    assert inspector.whole_change_landed(reused, merged, merged) is False
    # Never landed, or the landing is not reachable from the base tip.
    assert inspector.whole_change_landed(feature, base, base) is False
    assert inspector.whole_change_landed(feature, squash_all, squash_part) is False
    # Unknown or malformed evidence raises instead of answering.
    with pytest.raises(GitError):
        inspector.whole_change_landed("f" * 40, squash_all, squash_all)
    with pytest.raises(GitError):
        inspector.whole_change_landed(oid(repo, "HEAD^{tree}"), squash_all, squash_all)
    with pytest.raises(GitError):
        inspector.whole_change_landed(feature[:12], squash_all, squash_all)
    assert tree_state(repo) == before  # the proof never writes


@pytest.mark.parametrize(
    "landed_text,extra_text",
    [
        (
            "def render():\n    xs = []\n    for i in range(2):\n        xs.append(i)\n        xs.append(99)\n    return xs\n",
            "def render():\n    xs = []\n    for i in range(2):\n        xs.append(i)\n    xs.append(99)\n    return xs\n",
        ),
        ('value = "a  b"\n', 'value = "ab"\n'),
    ],
)
def test_whole_landing_never_discards_semantic_whitespace_work(
    tmp_path: Path, landed_text: str, extra_text: str
) -> None:
    repo = init_repo(tmp_path / "repo")
    git(repo, "switch", "-q", "-c", "feat/content")
    (repo / "content.py").write_text(landed_text)
    commit_all(repo, "feature content")
    git(repo, "switch", "-q", "main")
    git(repo, "merge", "--squash", "feat/content")
    git(repo, "commit", "-q", "-m", "land original content")
    landing = oid(repo, "HEAD")
    git(repo, "switch", "-q", "feat/content")
    (repo / "content.py").write_text(extra_text)
    commit_all(repo, "unlanded semantic whitespace")
    candidate = oid(repo, "HEAD")
    assert GitRepository(repo).whole_change_landed(candidate, landing, landing) is False
    assert (repo / "content.py").read_text() == extra_text


def test_withheld_foreign_processes_never_prove_idle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    monkeypatch.setattr(
        git_ops,
        "_scan_processes",
        lambda: git_ops._ProcessScan("procfs", ((os.getpid(), str(tmp_path)),), 3, ()),
    )
    assert worktree_activity(tree).status == "UNKNOWN"


def test_unresolved_process_namespace_never_proves_idle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    monkeypatch.setattr(
        git_ops,
        "_scan_processes",
        lambda: git_ops._ProcessScan(
            "procfs", ((99, str(tmp_path / "unresolvable" / "container-cwd")),), 0, ()
        ),
    )
    assert worktree_activity(tree).status == "UNKNOWN"


def test_uncached_live_remote_default_survives_local_deletion(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    remote = tmp_path / "server.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "origin", "main")
    expected = oid(repo, "main")
    git(repo, "switch", "-q", "-c", "feat/work")
    with pytest.raises(GitRefused):
        GitRepository(repo).delete_local_head("main", expected)
    assert oid(repo, "main") == expected


def test_unreported_remote_default_never_permits_deletion(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    remote = tmp_path / "server.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "switch", "-q", "-c", "feat/disposable")
    git(repo, "push", "-q", "origin", "main", "feat/disposable")
    expected = oid(repo, "HEAD")
    git(remote, "symbolic-ref", "HEAD", "refs/heads/unborn")
    with pytest.raises(GitRefused):
        GitRepository(repo).delete_remote_head("origin", "feat/disposable", expected)
    assert oid(remote, "feat/disposable") == expected


@pytest.mark.parametrize("applied", [False, True])
def test_lost_remote_delete_report_reconciles_without_retry(
    tmp_path: Path, applied: bool
) -> None:
    repo = init_repo(tmp_path / "repo")
    remote = tmp_path / "server.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "switch", "-q", "-c", "feat/disposable")
    git(repo, "push", "-q", "origin", "main", "feat/disposable")
    expected = oid(repo, "HEAD")

    class LostReport(GitRepository):
        pushes = 0

        def run(
            self, *args: str, check: bool = True, input_bytes: bytes | None = None
        ) -> subprocess.CompletedProcess[bytes]:
            if args[0] == "push":
                self.pushes += 1
                if applied:
                    git(
                        remote,
                        "update-ref",
                        "-d",
                        "refs/heads/feat/disposable",
                        expected,
                    )
                raise GitError("connection lost before report-status")
            return super().run(*args, check=check, input_bytes=input_bytes)

    inspector = LostReport(repo)
    if applied:
        inspector.delete_remote_head("origin", "feat/disposable", expected)
        assert "refs/heads/feat/disposable" not in inspector.remote_heads("origin")
    else:
        with pytest.raises(GitError) as error:
            inspector.delete_remote_head("origin", "feat/disposable", expected)
        assert error.value.uncertain is True
        assert oid(remote, "feat/disposable") == expected
    assert inspector.pushes == 1


def test_pr_head_observes_historical_ref_not_recreated_feature_tip(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    remote = tmp_path / "server.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "switch", "-q", "-c", "feat/reused")
    (repo / "tracked.txt").write_text("landed feature\n")
    commit_all(repo, "landed feature")
    landed_head = oid(repo, "HEAD")
    git(repo, "push", "-q", "origin", "main", "feat/reused", "HEAD:refs/pull/7/head")
    (repo / "tracked.txt").write_text("new unlanded feature\n")
    commit_all(repo, "unlanded addition")
    git(repo, "push", "-q", "origin", "feat/reused")
    inspector = GitRepository(repo)
    assert inspector.pr_head("origin", 7) == landed_head
    assert inspector.remote_heads("origin")["refs/heads/feat/reused"] == oid(
        repo, "HEAD"
    )
    assert inspector.pr_head("origin", 8) is None


def test_own_slice_identity_survives_a_landing_on_a_moved_trunk_byte_for_byte(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    root = oid(repo, "HEAD")
    git(repo, "switch", "-q", "-c", "stack/layer1")
    (repo / "lower.txt").write_text("lower layer\n")
    commit_all(repo, "lower layer")
    lower = oid(repo, "HEAD")
    git(repo, "switch", "-q", "-c", "stack/layer2")
    (repo / "data.bin").write_bytes(b"\x00\xff\x00binary\n")
    os.symlink("lower.txt", repo / "link")
    (repo / "tool.sh").write_text("#!/bin/sh\n")
    (repo / "tool.sh").chmod(0o755)
    (repo / "tracked.txt").unlink()
    commit_all(repo, "upper layer")
    upper = oid(repo, "HEAD")
    # The same contents with a plain file mode and a regular file for the link.
    git(repo, "switch", "-q", "-c", "variant", lower)
    (repo / "data.bin").write_bytes(b"\x00\xff\x00binary\n")
    (repo / "link").write_text("lower.txt")
    (repo / "tool.sh").write_text("#!/bin/sh\n")
    (repo / "tracked.txt").unlink()
    commit_all(repo, "upper layer without modes")
    variant = oid(repo, "HEAD")
    # The trunk moved on unrelated work; the lower layer, then the upper slice land.
    git(repo, "switch", "-q", "main")
    (repo / "unrelated.txt").write_text("trunk work\n")
    commit_all(repo, "unrelated trunk work")
    git(repo, "merge", "--squash", "stack/layer1")
    git(repo, "commit", "-q", "-m", "land lower")
    git(repo, "cherry-pick", upper)
    landing = oid(repo, "HEAD")
    inspector = GitRepository(repo)
    before = tree_state(repo)

    own = inspector.slice_identity(lower, upper)
    parent = inspector.first_parent(landing)

    assert parent == oid(repo, "HEAD^")
    assert inspector.slice_identity(str(parent), landing) == own
    assert inspector.commit_tree(upper) == oid(repo, f"{upper}^{{tree}}")
    assert inspector.commit_tree(landing) != inspector.commit_tree(upper)
    # Modes, symlinks and deletions are part of the identity; the base matters.
    assert inspector.slice_identity(lower, variant) != own
    assert inspector.slice_identity(root, upper) != own
    assert inspector.first_parent(root) is None
    with pytest.raises(GitRefused):
        inspector.slice_identity(upper, upper)
    with pytest.raises(GitError):
        inspector.slice_identity("f" * 40, upper)
    with pytest.raises(GitError):
        inspector.commit_tree(oid(repo, f"{upper}^{{tree}}"))
    with pytest.raises(GitError):
        inspector.first_parent(upper[:12])
    assert tree_state(repo) == before  # inspection never writes


def test_landing_bases_prove_a_multi_commit_rebase_landing_over_the_prior_trunk(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    base = oid(repo, "HEAD")
    git(repo, "switch", "-q", "-c", "stack/layer1")
    # Two commits of one slice edit the same line, so they overlap.
    (repo / "layer.txt").write_text("first\n")
    commit_all(repo, "layer: first")
    (repo / "layer.txt").write_text("second\n")
    commit_all(repo, "layer: second")
    head = oid(repo, "HEAD")
    git(repo, "switch", "-q", "main")
    (repo / "unrelated.txt").write_text("trunk work\n")
    commit_all(repo, "unrelated trunk work")
    before = oid(repo, "HEAD")
    git(repo, "cherry-pick", f"{base}..{head}")
    rebased = oid(repo, "HEAD")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge layer", head)
    merged = oid(repo, "HEAD")
    inspector = GitRepository(repo)
    state = tree_state(repo)

    bases = inspector.landing_bases(base, head, rebased)

    assert bases == (oid(repo, f"{rebased}^"), before)
    assert tree_state(repo) == state  # finding the candidates writes nothing
    # Only the trunk before the whole replay proves the landing.
    assert inspector.three_way_tree(base, bases[0], head) is None
    assert inspector.three_way_tree(base, before, head) == inspector.commit_tree(
        rebased
    )
    assert inspector.landing_bases(base, head, merged) == (rebased,)
    with pytest.raises(GitError):
        inspector.landing_bases(base, head[:12], rebased)
