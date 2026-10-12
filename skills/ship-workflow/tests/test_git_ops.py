"""Real-repository regressions for read-only Git inspection."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import time
from dataclasses import replace
from pathlib import Path

import pytest
from git_ops import (
    GitError,
    GitRepository,
    Snapshot,
    Worktree,
    parse_remote_identity,
    redact_credentials,
    redact_url,
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
