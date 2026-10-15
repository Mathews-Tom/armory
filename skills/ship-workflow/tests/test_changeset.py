"""Logical changesets against real Git repositories, real hooks and real gates.

Every scenario builds an actual dirty checkout, authors a plan through the same
draft compiler an assistant uses, executes it, and then inspects the resulting
commits, refs, index and working-tree bytes with independent ``git`` commands.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import changeset
import pytest
from changeset import (
    ChangesetStop,
    GatePolicy,
    PlanError,
    compile_draft,
    execute_changeset,
    item_id,
    parse_gates,
    parse_plan,
    take_inventory,
)
from git_ops import GitRepository
from state_store import Receipt, Store

pytestmark = pytest.mark.skipif(os.name != "posix", reason="journals require POSIX")

SCAN = """\
import subprocess, sys
diff = subprocess.run(["git", "diff", sys.argv[1], sys.argv[2]], capture_output=True,
                      check=True).stdout
sys.exit(1 if b"TOPSECRET" in diff else 0)
"""
RECORDER = """\
import os, subprocess, sys
head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                      check=True).stdout.strip()
extra = subprocess.run(["git", "status", "--porcelain", "--ignored",
                        "--untracked-files=all"], capture_output=True, check=True).stdout
with open(sys.argv[1], "a") as handle:
    handle.write(head + "\\t" + os.getcwd() + "\\t" + str(len(extra)) + "\\n")
"""


@pytest.fixture(autouse=True)
def isolated_git(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    for name in list(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name, raising=False)
    home = tmp_path_factory.mktemp("home")
    config = home / "gitconfig"
    config.write_text("[gc]\nauto = 0\n[maintenance]\nauto = false\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Ship Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "ship@example.invalid")
    previous = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(previous)


def run_git(cwd: Path, *args: str, data: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", *args], cwd=cwd, input=data, capture_output=True, check=False
    )
    if result.returncode != 0:
        raise AssertionError(
            f"git {args} failed: {result.stderr.decode(errors='replace')}"
        )
    return result.stdout


def git(cwd: Path, *args: str) -> str:
    return os.fsdecode(run_git(cwd, *args)).rstrip("\n")


def tree_listing(cwd: Path, rev: str) -> dict[bytes, tuple[str, str]]:
    raw = run_git(cwd, "ls-tree", "-r", "-z", "--full-tree", rev)
    entries: dict[bytes, tuple[str, str]] = {}
    for record in raw.split(b"\0")[:-1]:
        meta, _, path = record.partition(b"\t")
        mode, _, oid = meta.decode().split(" ")
        entries[path] = (mode, oid)
    return entries


def blob(cwd: Path, rev: str, path: bytes) -> bytes:
    oid = tree_listing(cwd, rev)[path][1]
    return run_git(cwd, "cat-file", "blob", oid)


def worktree_bytes(root: Path) -> dict[str, tuple[int, bytes]]:
    """Every non-Git file and link with its mode bits and exact content."""
    state: dict[str, tuple[int, bytes]] = {}
    for directory, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name != ".git"]
        for name in [
            *filenames,
            *(d for d in dirnames if os.path.islink(os.path.join(directory, d))),
        ]:
            full = os.path.join(directory, name)
            info = os.lstat(full)
            content = (
                os.readlink(full).encode()
                if stat.S_ISLNK(info.st_mode)
                else Path(full).read_bytes()
            )
            state[os.path.relpath(full, root)] = (
                stat.S_IFMT(info.st_mode) | (info.st_mode & 0o111),
                content,
            )
    return state


def status(cwd: Path) -> bytes:
    return run_git(cwd, "status", "--porcelain=v1", "-z", "--untracked-files=all")


@dataclass
class World:
    root: Path
    work: Path
    base: str
    marker: Path

    def repo(self) -> GitRepository:
        return GitRepository(self.work)

    def store(self) -> Store:
        return Store(
            Path(
                git(
                    self.work, "rev-parse", "--path-format=absolute", "--git-common-dir"
                )
            )
        )

    def gates(self, *gate_code: tuple[str, str], scan: bool = True) -> GatePolicy:
        gates = [
            {"name": name, "argv": [sys.executable, "-c", code, str(self.marker)]}
            for name, code in gate_code
        ]
        return parse_gates(
            {
                "schema_version": 1,
                "sources": ["test policy: repository gates"],
                "gates": gates,
                "secret_scan": {
                    "argv": [sys.executable, "-c", SCAN, "{base}", "{head}"]
                    if scan
                    else [sys.executable, "-c", "raise SystemExit(0)"]
                },
            }
        )

    def recorder(self) -> GatePolicy:
        return self.gates(("unit", RECORDER))

    def draft(
        self,
        groups: list[dict[str, object]],
        *,
        mode: str = "new",
        branch: str = "feat/topic",
        exclude: dict[bytes, str] | None = None,
        acknowledge: dict[bytes, list[str]] | None = None,
        base: str | None = None,
    ) -> dict[str, object]:
        inventory = take_inventory(self.repo())
        exclusions = exclude or {}
        acknowledged = acknowledge or {}
        return {
            "schema_version": 1,
            "base": {"ref": "main", "oid": base or self.base},
            "placement": {"mode": mode, "branch": branch},
            "dispositions": [
                {
                    "item": item.id,
                    "disposition": "exclude" if item.path in exclusions else "include",
                    "reason": exclusions.get(item.path),
                    "acknowledge": acknowledged.get(item.path, []),
                }
                for item in inventory.items
            ],
            "groups": groups,
        }

    def execute(
        self, plan_raw: dict[str, object], gates: GatePolicy, run_id: str | None = None
    ) -> changeset.Outcome:
        """Resume through the same journal handle that loads the receipt."""
        store = self.store()
        receipt: Receipt | None = store.load(run_id) if run_id is not None else None
        return execute_changeset(
            self.repo(), store, parse_plan(plan_raw), gates, "pr", receipt
        )


def group(
    group_id: str,
    message: str,
    changes: list[dict[str, object]],
    *,
    requires: list[str] | None = None,
    validation: list[str] | None = None,
) -> dict[str, object]:
    return {
        "id": group_id,
        "message": message,
        "requires": requires or [],
        "validation": ["unit"] if validation is None else validation,
        "changes": changes,
    }


def final(path: bytes) -> dict[str, object]:
    return {"item": item_id(path), "content": "final"}


def partial(path: bytes, content_file: Path, mode: str = "100644") -> dict[str, object]:
    return {"item": item_id(path), "blob_file": str(content_file), "mode": mode}


@pytest.fixture
def world(tmp_path: Path) -> World:
    root = tmp_path.resolve()
    work = root / "work"
    work.mkdir()
    run_git(work, "init", "-q", "-b", "main")
    (work / "README.md").write_text("base\n")
    (work / "a.txt").write_text("one\ntwo\nthree\n")
    (work / "old.txt").write_text("old\n")
    (work / "tool.sh").write_text("#!/bin/sh\necho tool\n")
    (work / ".gitignore").write_text("generated.txt\n")
    run_git(work, "add", "-A")
    run_git(work, "commit", "-q", "-m", "base")
    marker = root / "gates.log"
    return World(root, work, git(work, "rev-parse", "HEAD"), marker)


def marker_heads(world: World) -> list[str]:
    if not world.marker.exists():
        return []
    return [line.split("\t")[0] for line in world.marker.read_text().splitlines()]


# -- inventory ------------------------------------------------------------------------


def test_inventory_accounts_for_every_change_without_writing(world: World) -> None:
    work = world.work
    (work / "a.txt").write_text("one\nTWO\nthree\n")
    run_git(work, "add", "a.txt")
    (work / "a.txt").write_text("one\nTWO\nthree\nfour\n")
    run_git(work, "rm", "-q", "old.txt")
    (work / "new.txt").write_text("brand new\n")
    (work / "intent.txt").write_text("intent\n")
    run_git(work, "add", "-N", "intent.txt")
    (work / "README.md").unlink()
    (work / "generated.txt").write_text("ignored artifact\n")
    git_dir = work / ".git"
    before_index = (
        (git_dir / "index").read_bytes(),
        (git_dir / "index").stat().st_mtime_ns,
    )
    before_objects = git(work, "count-objects", "-v")

    inventory = take_inventory(world.repo())

    rows = {item.path: item.to_json() for item in inventory.items}
    assert set(rows) == {b"a.txt", b"old.txt", b"new.txt", b"intent.txt", b"README.md"}
    assert (rows[b"a.txt"]["staged"], rows[b"a.txt"]["unstaged"]) == (True, True)
    assert rows[b"old.txt"]["deleted"] and rows[b"old.txt"]["staged"]
    assert rows[b"README.md"]["deleted"] and not rows[b"README.md"]["staged"]
    assert rows[b"new.txt"]["untracked"]
    assert rows[b"intent.txt"]["untracked"] and rows[b"intent.txt"]["index"] is None
    expected_oid = git(work, "hash-object", "a.txt")
    assert rows[b"a.txt"]["worktree"] == {"mode": "100644", "oid": expected_oid}
    assert b"generated.txt" in inventory.ignored
    # Read-only: no object, index, journal or lock was written.
    assert git(work, "count-objects", "-v") == before_objects
    assert (
        (git_dir / "index").read_bytes(),
        (git_dir / "index").stat().st_mtime_ns,
    ) == before_index
    assert not (git_dir / "armory").exists()
    assert (
        subprocess.run(
            ["git", "cat-file", "-e", expected_oid], cwd=work, check=False
        ).returncode
        != 0
    )


def test_inventory_flags_secret_like_and_generated_paths(world: World) -> None:
    (world.work / ".env").write_text("TOKEN=abc\n")
    (world.work / "notes.txt").write_text("key AKIA" + "A" * 16 + "\n")
    (world.work / "node_modules" / "pkg").mkdir(parents=True)
    (world.work / "node_modules" / "pkg" / "index.js").write_text("x\n")

    concerns = {item.path: item.concerns for item in take_inventory(world.repo()).items}

    assert concerns[b".env"] == ("potential-secret",)
    assert concerns[b"notes.txt"] == ("potential-secret",)
    assert concerns[b"node_modules/pkg/index.js"] == ("generated-artifact",)


# -- lossless grouping ----------------------------------------------------------------


def test_staged_and_unstaged_hunks_of_one_file_land_in_their_groups(
    world: World,
) -> None:
    work = world.work
    (work / "a.txt").write_text("one\nTWO\nthree\n")
    run_git(work, "add", "a.txt")
    staged = world.root / "staged-a.txt"
    staged.write_bytes(run_git(work, "show", ":a.txt"))
    (work / "a.txt").write_text("one\nTWO\nthree\nfour\n")
    before = worktree_bytes(work)
    gates = world.recorder()
    plan = compile_draft(
        world.repo(),
        world.draft(
            [
                group("g1", "fix(a): capitalize two", [partial(b"a.txt", staged)]),
                group("g2", "feat(a): add four", [final(b"a.txt")], requires=["g1"]),
            ],
            mode="new",
        ),
        gates,
    )

    outcome = world.execute(plan, gates)

    assert outcome.status == "COMPLETE", outcome.result()
    tip = git(work, "rev-parse", "refs/heads/feat/topic")
    first = git(work, "rev-parse", f"{tip}~1")
    assert git(work, "rev-parse", f"{tip}~2") == world.base
    assert blob(work, first, b"a.txt") == b"one\nTWO\nthree\n"
    assert blob(work, tip, b"a.txt") == b"one\nTWO\nthree\nfour\n"
    assert git(work, "log", "-1", "--format=%B", first) == "fix(a): capitalize two"
    # The dirty default branch moved to the new branch; main is untouched.
    assert git(work, "symbolic-ref", "HEAD") == "refs/heads/feat/topic"
    assert git(work, "rev-parse", "refs/heads/main") == world.base
    assert status(work) == b""
    assert worktree_bytes(work) == before
    # Each new commit was validated by itself, in a clean isolated checkout.
    assert marker_heads(world) == [first, tip]
    for line in world.marker.read_text().splitlines():
        _, cwd, extra = line.split("\t")
        assert Path(cwd).resolve() != work and extra == "0"


def test_staged_deletion_binary_mode_and_link_changes_are_exact(world: World) -> None:
    work = world.work
    run_git(work, "rm", "-q", "old.txt")
    (work / "data.bin").write_bytes(b"\x00\x01\xffbinary\x00")
    os.chmod(work / "tool.sh", 0o755)
    os.symlink("a.txt", work / "link")
    (work / "-n.txt").write_text("option-like name\n")
    (work / "ünïcode.txt").write_text("unicode name\n")
    before = worktree_bytes(work)
    gates = world.recorder()
    plan = compile_draft(
        world.repo(),
        world.draft(
            [
                group("g1", "chore: drop old file", [final(b"old.txt")]),
                group(
                    "g2",
                    "feat: add assets",
                    [
                        final(b"data.bin"),
                        final(b"tool.sh"),
                        final(b"link"),
                        final(b"-n.txt"),
                        final("ünïcode.txt".encode()),
                    ],
                ),
            ]
        ),
        gates,
    )

    outcome = world.execute(plan, gates)

    assert outcome.status == "COMPLETE", outcome.result()
    tip = git(work, "rev-parse", "refs/heads/feat/topic")
    first = tree_listing(work, f"{tip}~1")
    final_tree = tree_listing(work, tip)
    assert b"old.txt" not in first and b"data.bin" not in first
    assert final_tree[b"tool.sh"][0] == "100755"
    assert final_tree[b"link"][0] == "120000"
    assert blob(work, tip, b"link") == b"a.txt"
    assert blob(work, tip, b"data.bin") == b"\x00\x01\xffbinary\x00"
    assert blob(work, tip, b"-n.txt") == b"option-like name\n"
    assert "ünïcode.txt".encode() in final_tree
    assert status(work) == b""
    assert worktree_bytes(work) == before


def test_non_utf8_path_deletion_round_trips_byte_exactly(world: World) -> None:
    work = world.work
    oid = (
        run_git(work, "hash-object", "-w", "--stdin", data=b"legacy\n").decode().strip()
    )
    weird = b"legacy\xff\xfe.txt"
    run_git(
        work,
        "update-index",
        "-z",
        "--index-info",
        data=f"100644 {oid} 0\t".encode() + weird + b"\0",
    )
    run_git(work, "commit", "-q", "-m", "legacy name")
    base = git(work, "rev-parse", "HEAD")
    gates = world.recorder()
    inventory = take_inventory(world.repo())
    assert [item.path for item in inventory.items] == [weird]
    plan = compile_draft(
        world.repo(),
        world.draft(
            [group("g1", "chore: remove legacy name", [final(weird)])],
            branch="feat/legacy",
            base=base,
        ),
        gates,
    )
    item = json.loads(json.dumps(plan))["items"][0]
    assert changeset.decode_path(item["path"], "path") == weird

    outcome = world.execute(plan, gates)

    assert outcome.status == "COMPLETE", outcome.result()
    tip = git(work, "rev-parse", "refs/heads/feat/legacy")
    assert weird not in tree_listing(work, tip)
    assert weird in tree_listing(work, base)
    assert status(work) == b""


def test_excluded_work_keeps_its_staging_and_bytes(world: World) -> None:
    work = world.work
    (work / "a.txt").write_text("one\ntwo\nthree\nincluded\n")
    (work / "old.txt").write_text("old\nstaged but excluded\n")
    run_git(work, "add", "old.txt")
    (work / "old.txt").write_text("old\nstaged but excluded\nand unstaged\n")
    staged_before = run_git(work, "ls-files", "--stage", "--", "old.txt")
    before = worktree_bytes(work)
    gates = world.recorder()
    plan = compile_draft(
        world.repo(),
        world.draft(
            [group("g1", "feat(a): extend a", [final(b"a.txt")])],
            exclude={b"old.txt": "unrelated local experiment"},
        ),
        gates,
    )

    outcome = world.execute(plan, gates)

    assert outcome.status == "COMPLETE", outcome.result()
    assert run_git(work, "ls-files", "--stage", "--", "old.txt") == staged_before
    assert git(work, "status", "--porcelain", "--", "old.txt") == "MM old.txt"
    assert git(work, "status", "--porcelain", "--", "a.txt") == ""
    assert worktree_bytes(work) == before
    tip = git(work, "rev-parse", "refs/heads/feat/topic")
    assert blob(work, tip, b"old.txt") == b"old\n"


# -- placement ------------------------------------------------------------------------


def test_unrelated_feature_history_is_not_imported_into_the_new_branch(
    world: World,
) -> None:
    work = world.work
    run_git(work, "switch", "-q", "-c", "feat/unrelated")
    (work / "old.txt").write_text("old\nunrelated commit\n")
    run_git(work, "commit", "-q", "-am", "unrelated work")
    unrelated = git(work, "rev-parse", "HEAD")
    (work / "fresh.txt").write_text("independent concern\n")
    before = worktree_bytes(work)
    index_before = run_git(work, "ls-files", "--stage", "-z")
    gates = world.recorder()
    plan = compile_draft(
        world.repo(),
        world.draft([group("g1", "feat: fresh concern", [final(b"fresh.txt")])]),
        gates,
    )

    outcome = world.execute(plan, gates)

    assert outcome.status == "COMPLETE", outcome.result()
    tip = git(work, "rev-parse", "refs/heads/feat/topic")
    assert git(work, "rev-parse", f"{tip}^") == world.base
    assert blob(work, tip, b"old.txt") == b"old\n"
    assert git(work, "rev-list", "--count", f"{world.base}..{tip}") == "1"
    # The source branch, its checkout and index stay exactly as they were.
    assert git(work, "symbolic-ref", "HEAD") == "refs/heads/feat/unrelated"
    assert git(work, "rev-parse", "HEAD") == unrelated
    assert run_git(work, "ls-files", "--stage", "-z") == index_before
    assert worktree_bytes(work) == before


def test_work_that_depends_on_unrelated_history_needs_a_placement_decision(
    world: World,
) -> None:
    work = world.work
    run_git(work, "switch", "-q", "-c", "feat/unrelated")
    (work / "old.txt").write_text("old\nunrelated commit\n")
    run_git(work, "commit", "-q", "-am", "unrelated work")
    (work / "old.txt").write_text("old\nunrelated commit\nfollow-up\n")
    gates = world.recorder()
    draft = world.draft([group("g1", "feat: follow-up", [final(b"old.txt")])])

    with pytest.raises(ChangesetStop) as stop:
        compile_draft(world.repo(), draft, gates)

    assert stop.value.status == "NEEDS_JUDGMENT"
    assert stop.value.details["paths"] == [changeset.encode_path(b"old.txt")]
    assert (
        subprocess.run(
            ["git", "rev-parse", "--verify", "-q", "refs/heads/feat/topic"],
            cwd=work,
            check=False,
        ).returncode
        != 0
    )


def test_current_feature_branch_keeps_its_existing_commits(world: World) -> None:
    work = world.work
    run_git(work, "switch", "-q", "-c", "feat/topic")
    (work / "a.txt").write_text("one\ntwo\nthree\nfirst\n")
    run_git(work, "commit", "-q", "-am", "existing reasonable commit")
    existing = git(work, "rev-parse", "HEAD")
    (work / "a.txt").write_text("one\ntwo\nthree\nfirst\nsecond\n")
    gates = world.recorder()
    plan = compile_draft(
        world.repo(),
        world.draft(
            [group("g1", "feat(a): second", [final(b"a.txt")])],
            mode="current",
            branch="feat/topic",
        ),
        gates,
    )

    outcome = world.execute(plan, gates)

    assert outcome.status == "COMPLETE", outcome.result()
    assert git(work, "rev-parse", "HEAD^") == existing
    assert git(work, "symbolic-ref", "HEAD") == "refs/heads/feat/topic"
    assert status(work) == b""


# -- refusals -------------------------------------------------------------------------


def test_changed_snapshot_after_authoring_invalidates_the_plan(world: World) -> None:
    (world.work / "a.txt").write_text("one\ntwo\nthree\nplanned\n")
    gates = world.recorder()
    plan = compile_draft(
        world.repo(), world.draft([group("g1", "feat: plan", [final(b"a.txt")])]), gates
    )
    (world.work / "a.txt").write_text("one\ntwo\nthree\nplanned\nlater edit\n")

    outcome = world.execute(plan, gates)

    assert outcome.status == "NEEDS_JUDGMENT"
    assert "changed after this plan" in str(outcome.reason)
    assert outcome.receipt is None and world.store().list_runs() == ()
    assert (
        subprocess.run(
            ["git", "rev-parse", "--verify", "-q", "refs/heads/feat/topic"],
            cwd=world.work,
            check=False,
        ).returncode
        != 0
    )


def test_external_change_during_validation_blocks_local_publication(
    world: World,
) -> None:
    (world.work / "a.txt").write_text("one\ntwo\nthree\nplanned\n")
    intruder = (
        "import pathlib, sys\n"
        f"pathlib.Path({str(world.work / 'a.txt')!r}).write_text('concurrent edit\\n')\n"
    )
    gates = world.gates(("unit", intruder))
    plan = compile_draft(
        world.repo(), world.draft([group("g1", "feat: plan", [final(b"a.txt")])]), gates
    )

    outcome = world.execute(plan, gates)

    assert outcome.status == "NEEDS_JUDGMENT"
    assert "changed while commits were validated" in str(outcome.reason)
    assert git(world.work, "symbolic-ref", "HEAD") == "refs/heads/main"
    assert git(world.work, "rev-parse", "HEAD") == world.base
    assert (world.work / "a.txt").read_text() == "concurrent edit\n"
    receipt = world.store().list_runs()[0]
    assert receipt.changeset is not None and receipt.changeset.update is None
    assert [group.outcome for group in receipt.changeset.groups] == ["VALIDATED"]


def test_group_that_does_not_pass_alone_is_rejected_and_nothing_moves(
    world: World,
) -> None:
    work = world.work
    (work / "use.py").write_text("from lib import helper\nhelper()\n")
    (work / "lib.py").write_text("def helper():\n    return 1\n")
    importer = (
        "import os, subprocess, sys\n"
        "if os.path.exists('use.py'):\n"
        "    sys.exit(subprocess.run([sys.executable, '-c', 'import use']).returncode)\n"
    )
    gates = world.gates(("unit", importer))
    before = worktree_bytes(work)
    index_before = run_git(work, "ls-files", "--stage", "-z")
    broken = compile_draft(
        world.repo(),
        world.draft(
            [
                group("caller", "feat: call helper", [final(b"use.py")]),
                group("helper", "feat: add helper", [final(b"lib.py")]),
            ]
        ),
        gates,
    )

    outcome = world.execute(broken, gates)

    assert outcome.status == "NEEDS_JUDGMENT"
    assert outcome.details["group"] == "caller" and outcome.details["gate"] == "unit"
    assert git(work, "symbolic-ref", "HEAD") == "refs/heads/main"
    assert run_git(work, "ls-files", "--stage", "-z") == index_before
    assert worktree_bytes(work) == before
    # The assistant repairs the grouping; acceptance is unchanged.
    repaired = compile_draft(
        world.repo(),
        world.draft(
            [
                group("helper", "feat: add helper", [final(b"lib.py")]),
                group(
                    "caller",
                    "feat: call helper",
                    [final(b"use.py")],
                    requires=["helper"],
                ),
            ]
        ),
        gates,
    )
    assert world.execute(repaired, gates).status == "COMPLETE"


def test_ignored_local_artifact_cannot_make_a_gate_pass(world: World) -> None:
    (world.work / "generated.txt").write_text("only here, ignored\n")
    (world.work / "a.txt").write_text("one\ntwo\nthree\nchange\n")
    needs_artifact = (
        "import os, sys\nsys.exit(0 if os.path.exists('generated.txt') else 3)\n"
    )
    gates = world.gates(("unit", needs_artifact))
    plan = compile_draft(
        world.repo(),
        world.draft([group("g1", "feat: change", [final(b"a.txt")])]),
        gates,
    )

    outcome = world.execute(plan, gates)

    assert outcome.status == "NEEDS_JUDGMENT"
    assert "gate unit failed" in str(outcome.reason)
    assert git(world.work, "rev-parse", "HEAD") == world.base


def test_secret_in_a_new_commit_blocks_and_needs_owner_decision(world: World) -> None:
    (world.work / "config.txt").write_text("password = TOPSECRET\n")
    gates = world.recorder()
    plan = compile_draft(
        world.repo(),
        world.draft([group("g1", "feat: config", [final(b"config.txt")])]),
        gates,
    )

    outcome = world.execute(plan, gates)

    assert outcome.status == "BLOCKED"
    assert "secret scan" in str(outcome.reason)
    assert git(world.work, "rev-parse", "HEAD") == world.base


def test_secret_like_file_needs_an_explicit_disposition(world: World) -> None:
    (world.work / ".env").write_text("TOKEN=abc\n")
    (world.work / "a.txt").write_text("one\ntwo\nthree\nsafe\n")
    gates = world.recorder()
    silent = world.draft([group("g1", "feat: all", [final(b".env"), final(b"a.txt")])])

    with pytest.raises(ChangesetStop) as stop:
        compile_draft(world.repo(), silent, gates)

    assert stop.value.details["concerns"] == ["potential-secret"]
    excluded = world.draft(
        [group("g1", "feat: safe", [final(b"a.txt")])],
        exclude={b".env": "local credentials stay uncommitted"},
    )
    outcome = world.execute(compile_draft(world.repo(), excluded, gates), gates)
    assert outcome.status == "COMPLETE"
    assert (world.work / ".env").read_text() == "TOKEN=abc\n"
    assert b".env" not in tree_listing(world.work, "HEAD")


def test_dependency_order_and_successive_same_file_states_are_enforced(
    world: World,
) -> None:
    work = world.work
    (work / "a.txt").write_text("one\nTWO\nthree\n")
    step = world.root / "step.txt"
    step.write_text("one\nTWO\nthree\n")
    (work / "a.txt").write_text("one\nTWO\nthree\nfour\n")
    gates = world.recorder()
    missing_dependency = world.draft(
        [
            group("g1", "fix: two", [partial(b"a.txt", step)]),
            group("g2", "feat: four", [final(b"a.txt")]),
        ]
    )
    with pytest.raises(ChangesetStop, match="without requiring it"):
        compile_draft(world.repo(), missing_dependency, gates)

    forward = world.draft(
        [
            group("g1", "fix: two", [partial(b"a.txt", step)], requires=["g2"]),
            group("g2", "feat: four", [final(b"a.txt")]),
        ]
    )
    with pytest.raises(PlanError, match="earlier groups"):
        compile_draft(world.repo(), forward, gates)


def test_intermediate_content_cannot_invent_unapproved_lines(world: World) -> None:
    (world.work / "a.txt").write_text("one\ntwo\nthree\nfour\n")
    invented = world.root / "invented.txt"
    invented.write_text("one\ntwo\nthree\nnot in either version\n")
    gates = world.recorder()
    draft = world.draft(
        [
            group("g1", "feat: step", [partial(b"a.txt", invented)]),
            group("g2", "feat: finish", [final(b"a.txt")], requires=["g1"]),
        ]
    )
    before = worktree_bytes(world.work)
    index_before = run_git(world.work, "ls-files", "--stage", "-z")

    with pytest.raises(ChangesetStop) as caught:
        compile_draft(world.repo(), draft, gates)
    assert caught.value.status == "NEEDS_JUDGMENT"
    assert git(world.work, "rev-parse", "HEAD") == world.base
    assert run_git(world.work, "ls-files", "--stage", "-z") == index_before
    assert worktree_bytes(world.work) == before


def test_plan_that_drops_included_work_is_rejected(world: World) -> None:
    (world.work / "a.txt").write_text("one\ntwo\nthree\nfour\n")
    (world.work / "b.txt").write_text("bee\n")
    gates = world.recorder()
    plan = compile_draft(
        world.repo(),
        world.draft(
            [group("g1", "feat: a", [final(b"a.txt")])],
            exclude={b"b.txt": "later"},
        ),
        gates,
    )
    items = plan["items"]
    assert isinstance(items, list)
    for entry in items:
        entry["disposition"] = "include"
        entry["reason"] = None

    outcome = world.execute(plan, gates)

    assert outcome.status == "NEEDS_JUDGMENT"
    assert "final tree does not equal" in str(outcome.reason)
    assert outcome.details["paths"] == [changeset.encode_path(b"b.txt")]


def test_commit_hooks_run_on_the_isolated_group_and_can_refuse(world: World) -> None:
    hooks = world.work / ".git" / "hooks"
    seen = world.root / "pre-commit.log"
    (hooks / "pre-commit").write_text(
        f"#!/bin/sh\ngit diff --cached --name-only >> '{seen}'\npwd >> '{seen}'\n"
    )
    (hooks / "commit-msg").write_text(
        "#!/bin/sh\ngrep -q '^feat' \"$1\" || { echo 'needs feat' >&2; exit 1; }\n"
    )
    for name in ("pre-commit", "commit-msg"):
        (hooks / name).chmod(0o755)
    (world.work / "a.txt").write_text("one\ntwo\nthree\nhooked\n")
    gates = world.recorder()
    refused = compile_draft(
        world.repo(),
        world.draft([group("g1", "chore: wrong type", [final(b"a.txt")])]),
        gates,
    )

    outcome = world.execute(refused, gates)

    assert outcome.status == "NEEDS_JUDGMENT"
    assert "hook refused" in str(outcome.reason)
    assert git(world.work, "rev-parse", "HEAD") == world.base
    accepted = compile_draft(
        world.repo(),
        world.draft([group("g1", "feat: hooked", [final(b"a.txt")])]),
        gates,
    )
    assert world.execute(accepted, gates).status == "COMPLETE"
    lines = seen.read_text().splitlines()
    assert lines.count("a.txt") == 2
    assert all(
        Path(line).resolve() != world.work for line in lines if line.startswith("/")
    )


# -- recovery -------------------------------------------------------------------------


def test_interrupted_local_update_resumes_without_recreating_commits(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    (world.work / "a.txt").write_text("one\ntwo\nthree\nresumed\n")
    gates = world.recorder()
    plan = compile_draft(
        world.repo(),
        world.draft([group("g1", "feat: resume", [final(b"a.txt")])]),
        gates,
    )
    original = changeset._Run._move_ref

    def interrupted(self: changeset._Run, record: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(changeset._Run, "_move_ref", interrupted)
    first = world.execute(plan, gates)
    monkeypatch.setattr(changeset._Run, "_move_ref", original)

    assert (first.status, first.cancelled) == ("WAITING", True)
    run_id = first.result()["run_id"]
    assert isinstance(run_id, str)
    pending = world.store().load(run_id)
    assert pending.changeset is not None and pending.changeset.update is not None
    assert pending.changeset.update.outcome == "PENDING"
    assert git(world.work, "rev-parse", "HEAD") == world.base
    commit = pending.changeset.groups[0].commit
    gate_runs = len(marker_heads(world))

    resumed = world.execute(plan, gates, run_id)

    assert resumed.status == "COMPLETE", resumed.result()
    assert git(world.work, "rev-parse", "refs/heads/feat/topic") == commit
    assert git(world.work, "symbolic-ref", "HEAD") == "refs/heads/feat/topic"
    assert status(world.work) == b""
    assert len(marker_heads(world)) == gate_runs
    again = world.execute(plan, gates, run_id)
    assert again.status == "COMPLETE" and not again.mutation_attempted
    assert git(world.work, "rev-parse", "refs/heads/feat/topic") == commit


def test_journal_records_hashes_not_raw_content(world: World) -> None:
    (world.work / "a.txt").write_text("one\ntwo\nthree\nTOKEN_VALUE_IN_SOURCE\n")
    gates = world.recorder()
    plan = compile_draft(
        world.repo(),
        world.draft([group("g1", "feat: private", [final(b"a.txt")])]),
        gates,
    )
    outcome = world.execute(plan, gates)
    run_id = outcome.result()["run_id"]

    journal = (world.store().directory / f"{run_id}.json").read_bytes()

    assert b"TOKEN_VALUE_IN_SOURCE" not in journal
    assert b"feat: private" not in journal
    assert hashlib.sha256(b"feat: private").hexdigest().encode() in journal


def test_staged_modification_survives_a_later_worktree_deletion(world: World) -> None:
    work = world.work
    staged_bytes = b"one\nTWO staged\nthree\n"
    (work / "a.txt").write_bytes(staged_bytes)
    run_git(work, "add", "a.txt")
    staged = world.root / "staged-a.txt"
    staged.write_bytes(run_git(work, "show", ":a.txt"))
    (work / "a.txt").unlink()
    before = worktree_bytes(work)
    gates = world.recorder()
    plan = compile_draft(
        world.repo(),
        world.draft(
            [
                group(
                    "g1",
                    "fix(a): preserve staged correction",
                    [partial(b"a.txt", staged)],
                ),
                group(
                    "g2",
                    "refactor(a): remove corrected file",
                    [final(b"a.txt")],
                    requires=["g1"],
                ),
            ]
        ),
        gates,
    )
    outcome = world.execute(plan, gates)
    assert outcome.status == "COMPLETE", outcome.result()
    tip = git(work, "rev-parse", "refs/heads/feat/topic")
    first = git(work, "rev-parse", f"{tip}~1")
    assert blob(work, first, b"a.txt") == staged_bytes
    assert b"a.txt" not in tree_listing(work, tip)
    assert git(work, "rev-parse", f"{tip}~2") == world.base
    assert git(work, "rev-parse", "refs/heads/main") == world.base
    assert git(work, "symbolic-ref", "HEAD") == "refs/heads/feat/topic"
    assert status(work) == b""
    assert worktree_bytes(work) == before
    assert marker_heads(world) == [first, tip]


@pytest.mark.parametrize(
    ("existing", "target"), [("feat", "feat/parser"), ("feat/parser", "feat")]
)
def test_ref_path_collision_is_rejected_before_user_staging_changes(
    world: World, existing: str, target: str
) -> None:
    run_git(world.work, "branch", existing, world.base)
    (world.work / "a.txt").write_text("one\nSTAGED\nthree\n")
    run_git(world.work, "add", "a.txt")
    (world.work / "a.txt").write_text("one\nSTAGED\nthree\nunstaged\n")
    before = worktree_bytes(world.work)
    index_before = run_git(world.work, "ls-files", "--stage", "-z")
    gates = world.recorder()
    draft = world.draft(
        [group("g1", "feat: preserve staged work", [final(b"a.txt")])], branch=target
    )
    with pytest.raises(ChangesetStop) as caught:
        compile_draft(world.repo(), draft, gates)
    assert caught.value.status == "BLOCKED"
    assert git(world.work, "symbolic-ref", "HEAD") == "refs/heads/main"
    assert run_git(world.work, "ls-files", "--stage", "-z") == index_before
    assert worktree_bytes(world.work) == before


def test_ref_path_collision_appearing_during_gates_preserves_original_index(
    world: World,
) -> None:
    (world.work / "a.txt").write_text("one\nSTAGED\nthree\n")
    run_git(world.work, "add", "a.txt")
    (world.work / "a.txt").write_text("one\nSTAGED\nthree\nunstaged\n")
    before = worktree_bytes(world.work)
    index_before = run_git(world.work, "ls-files", "--stage", "-z")
    concurrent = (
        "import subprocess\n"
        f"subprocess.run(['git', '-C', {str(world.work)!r}, 'branch', "
        f"'feat', {world.base!r}], check=True)\n"
    )
    gates = world.gates(("unit", concurrent))
    plan = compile_draft(
        world.repo(),
        world.draft(
            [group("g1", "feat: preserve staged work", [final(b"a.txt")])],
            branch="feat/parser",
        ),
        gates,
    )
    outcome = world.execute(plan, gates)
    assert outcome.status == "BLOCKED", outcome.result()
    assert git(world.work, "symbolic-ref", "HEAD") == "refs/heads/main"
    assert run_git(world.work, "ls-files", "--stage", "-z") == index_before
    assert worktree_bytes(world.work) == before
    run_git(world.work, "branch", "-d", "feat")
    run_id = outcome.result()["run_id"]
    assert isinstance(run_id, str)
    resumed = world.execute(plan, gates, run_id)
    assert resumed.status == "COMPLETE", resumed.result()
    assert git(world.work, "rev-parse", "refs/heads/main") == world.base
    assert status(world.work) == b""
    assert worktree_bytes(world.work) == before


def test_base_oid_cannot_disguise_unrelated_feature_history_as_main(
    world: World,
) -> None:
    run_git(world.work, "switch", "-c", "feat/unrelated")
    (world.work / "README.md").write_text("unrelated feature history\n")
    run_git(world.work, "add", "README.md")
    run_git(world.work, "commit", "-q", "-m", "feat: retain unrelated history")
    unrelated = git(world.work, "rev-parse", "HEAD")
    (world.work / "a.txt").write_text("one\ntwo\nthree\nintended work\n")
    before = worktree_bytes(world.work)
    index_before = run_git(world.work, "ls-files", "--stage", "-z")
    gates = world.recorder()
    draft = world.draft(
        [group("g1", "feat: place intended work", [final(b"a.txt")])], base=unrelated
    )
    with pytest.raises(ChangesetStop) as caught:
        compile_draft(world.repo(), draft, gates)
    assert caught.value.status == "NEEDS_JUDGMENT"
    assert git(world.work, "rev-parse", "HEAD") == unrelated
    assert git(world.work, "rev-parse", "refs/heads/main") == world.base
    assert run_git(world.work, "ls-files", "--stage", "-z") == index_before
    assert worktree_bytes(world.work) == before


# -- commit identity and signing ------------------------------------------------------


@pytest.mark.skipif(
    shutil.which("ssh-keygen") is None, reason="SSH commit signing needs ssh-keygen"
)
def test_conditional_global_identity_and_ssh_signing_reach_the_planned_commit(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = world.work
    for role in ("AUTHOR", "COMMITTER"):
        for field in ("NAME", "EMAIL"):
            monkeypatch.delenv(f"GIT_{role}_{field}")
    key = world.root / "signing-key"
    subprocess.run(
        [
            "ssh-keygen",
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-C",
            "ship-test",
            "-f",
            str(key),
        ],
        check=True,
        capture_output=True,
    )
    public = (world.root / "signing-key.pub").read_text().split()
    allowed = world.root / "allowed-signers"
    allowed.write_text(f"work@example.invalid {public[0]} {public[1]}\n")
    work_config = world.root / "work.gitconfig"
    work_config.write_text(
        "[user]\n\tname = Work Person\n\temail = work@example.invalid\n"
        f'\tsigningkey = "{key}"\n'
        "[commit]\n\tgpgsign\n"
        "[gpg]\n\tformat = ssh\n"
        f'[gpg "ssh"]\n\tallowedSignersFile = "{allowed}"\n'
    )
    global_config = Path(os.environ["GIT_CONFIG_GLOBAL"])
    global_config.write_text(
        global_config.read_text()
        + "[user]\n\tname = Default Person\n\temail = default@example.invalid\n"
        + f'[includeIf "gitdir:{work}/"]\n\tpath = "{work_config}"\n'
    )
    # The identity and signing setup applies only through the conditional include
    # matching this checkout's gitdir: no repository-local value exists.
    assert git(work, "config", "--get", "user.email") == "work@example.invalid"
    local = subprocess.run(
        ["git", "config", "--local", "--get", "user.email"],
        cwd=work,
        capture_output=True,
        check=False,
    )
    assert local.returncode == 1
    (work / "a.txt").write_text("one\ntwo\nthree\nsigned\n")
    gates = world.recorder()
    plan = compile_draft(
        world.repo(),
        world.draft([group("g1", "feat: signed work", [final(b"a.txt")])]),
        gates,
    )

    outcome = world.execute(plan, gates)

    assert outcome.status == "COMPLETE", outcome.result()
    tip = git(work, "rev-parse", "refs/heads/feat/topic")
    identity = "Work Person <work@example.invalid>"
    assert (
        git(work, "log", "-1", "--format=%an <%ae>|%cn <%ce>", tip)
        == f"{identity}|{identity}"
    )
    assert "\ngpgsig -----BEGIN SSH SIGNATURE-----" in git(
        work, "cat-file", "commit", tip
    )
    # Git itself verifies the commit against the ephemeral key's allowed signers.
    verified = subprocess.run(
        ["git", "verify-commit", tip],
        cwd=work,
        capture_output=True,
        text=True,
        check=False,
    )
    report = verified.stdout + verified.stderr
    assert verified.returncode == 0, report


# -- ref path aliases -----------------------------------------------------------------
# Loose refs are files, so a case- or normalization-insensitive filesystem (the macOS
# default) names ``feat`` and ``Feat/parser`` by one path although Git compares the
# refs exactly. The refusal is spelling based and filesystem independent: these tests
# run everywhere, and on a case-insensitive filesystem the same plans would otherwise
# fail only after the user's index had been rewritten. A case-sensitive filesystem
# only proves the declared rule, not APFS behavior.


@pytest.mark.parametrize(
    ("existing", "target"),
    [
        ("feat", "Feat"),
        ("feat", "Feat/parser"),
        ("Feat/parser", "feat"),
        ("caf\u00e9", "cafe\u0301"),
    ],
)
def test_case_or_spelling_aliased_ref_path_is_rejected_before_user_staging_changes(
    world: World, existing: str, target: str
) -> None:
    run_git(world.work, "branch", existing, world.base)
    (world.work / "a.txt").write_text("one\nSTAGED\nthree\n")
    run_git(world.work, "add", "a.txt")
    (world.work / "a.txt").write_text("one\nSTAGED\nthree\nunstaged\n")
    before = worktree_bytes(world.work)
    index_before = run_git(world.work, "ls-files", "--stage", "-z")
    gates = world.recorder()
    draft = world.draft(
        [group("g1", "feat: preserve staged work", [final(b"a.txt")])], branch=target
    )

    with pytest.raises(ChangesetStop) as caught:
        compile_draft(world.repo(), draft, gates)

    assert caught.value.status == "BLOCKED"
    assert git(world.work, "symbolic-ref", "HEAD") == "refs/heads/main"
    assert run_git(world.work, "ls-files", "--stage", "-z") == index_before
    assert worktree_bytes(world.work) == before


@pytest.mark.parametrize(
    ("concurrent", "target"), [("feat", "Feat/parser"), ("Feat", "feat")]
)
def test_case_aliased_ref_path_appearing_during_gates_preserves_original_index(
    world: World, concurrent: str, target: str
) -> None:
    (world.work / "a.txt").write_text("one\nSTAGED\nthree\n")
    run_git(world.work, "add", "a.txt")
    (world.work / "a.txt").write_text("one\nSTAGED\nthree\nunstaged\n")
    before = worktree_bytes(world.work)
    index_before = run_git(world.work, "ls-files", "--stage", "-z")
    creator = (
        "import subprocess\n"
        f"subprocess.run(['git', '-C', {str(world.work)!r}, 'branch', "
        f"{concurrent!r}, {world.base!r}], check=True)\n"
    )
    gates = world.gates(("unit", creator))
    plan = compile_draft(
        world.repo(),
        world.draft(
            [group("g1", "feat: preserve staged work", [final(b"a.txt")])],
            branch=target,
        ),
        gates,
    )

    outcome = world.execute(plan, gates)

    assert outcome.status == "BLOCKED", outcome.result()
    assert git(world.work, "symbolic-ref", "HEAD") == "refs/heads/main"
    assert run_git(world.work, "ls-files", "--stage", "-z") == index_before
    assert worktree_bytes(world.work) == before
    run_git(world.work, "branch", "-d", concurrent)
    run_id = outcome.result()["run_id"]
    assert isinstance(run_id, str)
    resumed = world.execute(plan, gates, run_id)
    assert resumed.status == "COMPLETE", resumed.result()
    assert git(world.work, "rev-parse", "refs/heads/main") == world.base
    assert status(world.work) == b""
    assert worktree_bytes(world.work) == before


# -- staged state that no group commits -----------------------------------------------

STAGED_LOSS = ["added-then-deleted", "edited-then-reverted"]


def stage_then_lose(world: World, scenario: str) -> tuple[bytes, bytes]:
    """Stage content the working tree then deletes or reverts; b.txt is other work."""
    work = world.work
    if scenario == "added-then-deleted":
        path = b"added.txt"
        (work / "added.txt").write_text("staged only\n")
        run_git(work, "add", "added.txt")
        (work / "added.txt").unlink()
    else:
        path = b"a.txt"
        (work / "a.txt").write_text("one\nSTAGED\nthree\n")
        run_git(work, "add", "a.txt")
        (work / "a.txt").write_text("one\ntwo\nthree\n")
    (work / "b.txt").write_text("bee\n")
    return path, run_git(work, "show", f":{path.decode()}")


@pytest.mark.parametrize("scenario", STAGED_LOSS)
def test_staged_state_that_no_group_commits_is_refused_before_any_mutation(
    world: World, scenario: str
) -> None:
    work = world.work
    path, _ = stage_then_lose(world, scenario)
    before = worktree_bytes(work)
    index_before = run_git(work, "ls-files", "--stage", "-z")
    gates = world.recorder()
    draft = world.draft([group("g1", "feat: add b", [final(b"b.txt")])])

    with pytest.raises(ChangesetStop) as caught:
        compile_draft(world.repo(), draft, gates)

    assert caught.value.status == "NEEDS_JUDGMENT"
    assert caught.value.details["item"] == item_id(path)
    # A plan authored with the item excluded and then edited to include it is refused
    # by execution itself, before any journal, object-moving or index write.
    excluded = compile_draft(
        world.repo(),
        world.draft(
            [group("g1", "feat: add b", [final(b"b.txt")])],
            exclude={path: "keep the staged state"},
        ),
        gates,
    )
    items = excluded["items"]
    assert isinstance(items, list)
    for entry in items:
        entry["disposition"] = "include"
        entry["reason"] = None

    outcome = world.execute(excluded, gates)

    assert outcome.status == "NEEDS_JUDGMENT"
    assert outcome.details["item"] == item_id(path)
    assert outcome.receipt is None and world.store().list_runs() == ()
    assert git(work, "symbolic-ref", "HEAD") == "refs/heads/main"
    assert run_git(work, "ls-files", "--stage", "-z") == index_before
    assert worktree_bytes(work) == before
    assert marker_heads(world) == []


@pytest.mark.parametrize("scenario", STAGED_LOSS)
def test_excluding_the_unpreserved_staged_item_keeps_its_index_and_bytes(
    world: World, scenario: str
) -> None:
    work = world.work
    path, _ = stage_then_lose(world, scenario)
    entry_before = run_git(work, "ls-files", "--stage", "--", path.decode())
    status_before = git(work, "status", "--porcelain", "--", path.decode())
    before = worktree_bytes(work)
    gates = world.recorder()
    plan = compile_draft(
        world.repo(),
        world.draft(
            [group("g1", "feat: add b", [final(b"b.txt")])],
            exclude={path: "keep the staged state"},
        ),
        gates,
    )

    outcome = world.execute(plan, gates)

    assert outcome.status == "COMPLETE", outcome.result()
    assert run_git(work, "ls-files", "--stage", "--", path.decode()) == entry_before
    assert git(work, "status", "--porcelain", "--", path.decode()) == status_before
    assert worktree_bytes(work) == before


@pytest.mark.parametrize("scenario", STAGED_LOSS)
def test_staged_state_committed_before_its_reversion_reaches_history(
    world: World, scenario: str
) -> None:
    work = world.work
    path, staged_bytes = stage_then_lose(world, scenario)
    staged_file = world.root / "staged-copy.txt"
    staged_file.write_bytes(staged_bytes)
    before = worktree_bytes(work)
    gates = world.recorder()
    plan = compile_draft(
        world.repo(),
        world.draft(
            [
                group(
                    "g1",
                    "feat: keep the staged content",
                    [partial(path, staged_file), final(b"b.txt")],
                ),
                group(
                    "g2",
                    "revert: restore the working-tree state",
                    [final(path)],
                    requires=["g1"],
                ),
            ]
        ),
        gates,
    )

    outcome = world.execute(plan, gates)

    assert outcome.status == "COMPLETE", outcome.result()
    tip = git(work, "rev-parse", "refs/heads/feat/topic")
    first = git(work, "rev-parse", f"{tip}~1")
    assert blob(work, first, path) == staged_bytes
    if scenario == "added-then-deleted":
        assert path not in tree_listing(work, tip)
    else:
        assert blob(work, tip, path) == b"one\ntwo\nthree\n"
    assert status(work) == b""
    assert worktree_bytes(work) == before


# -- preservation proof before confirmation -------------------------------------------


def install_ref_hook(world: World, target: Path) -> None:
    """A real ``reference-transaction`` hook that writes into the user's checkout.

    It fires once the planned branch ref is committed, i.e. between ref publication
    and the preservation proof, as a concurrent editor or tool would.
    """
    hook = world.work / ".git" / "hooks" / "reference-transaction"
    hook.write_text(
        "#!/bin/sh\n"
        '[ "$1" = committed ] || exit 0\n'
        "while read -r old new ref; do\n"
        '  if [ "$ref" = refs/heads/feat/topic ]; then\n'
        f"    printf 'tampered\\n' >> '{target}'\n"
        "  fi\n"
        "done\n"
    )
    hook.chmod(0o755)


EXCLUDED_TEXT = "old\nstaged but excluded\n"


@pytest.mark.parametrize("target", ["a.txt", "old.txt", "stray.txt"])
def test_failed_preservation_proof_is_never_confirmed_and_resume_refuses(
    world: World, target: str
) -> None:
    work = world.work
    planned = "one\ntwo\nthree\nplanned\n"
    (work / "a.txt").write_text(planned)
    (work / "old.txt").write_text(EXCLUDED_TEXT)
    run_git(work, "add", "old.txt")
    gates = world.recorder()
    plan = compile_draft(
        world.repo(),
        world.draft(
            [group("g1", "feat: planned", [final(b"a.txt")])],
            exclude={b"old.txt": "unrelated local experiment"},
        ),
        gates,
    )
    excluded_entry = run_git(work, "ls-files", "--stage", "--", "old.txt")
    install_ref_hook(world, work / target)

    first = world.execute(plan, gates)

    assert first.status == "BLOCKED", first.result()
    assert first.mutation_performed
    run_id = first.result()["run_id"]
    assert isinstance(run_id, str)
    tip = git(work, "rev-parse", "refs/heads/feat/topic")
    pending = world.store().load(run_id).changeset
    assert pending is not None and pending.update is not None
    # The branch really moved, but the update was never confirmed and carries no
    # residual snapshot that a resume or a later publication could trust. The
    # original preserved-work checkpoint was journaled before publication.
    assert pending.update.new == tip
    assert pending.update.outcome == "PENDING"
    assert pending.residual_snapshot is None and pending.confirmed == []
    assert pending.preserved is not None
    assert first.result()["confirmed_commits"] == []
    if target == "a.txt":
        assert "observed_preserved" not in first.details
    else:
        assert first.details["expected_preserved"] == pending.preserved
        assert first.details["observed_preserved"] != pending.preserved
    held = worktree_bytes(work)
    index_held = run_git(work, "ls-files", "--stage", "-z")
    gate_runs = len(marker_heads(world))

    refused = world.execute(plan, gates, run_id)

    assert refused.status == "BLOCKED", refused.result()
    assert refused.result()["confirmed_commits"] == []
    unchanged = world.store().load(run_id).changeset
    assert unchanged is not None and unchanged.update is not None
    assert unchanged.update.outcome == "PENDING"
    assert unchanged.residual_snapshot is None
    assert unchanged.preserved == pending.preserved
    assert git(work, "rev-parse", "refs/heads/feat/topic") == tip
    assert run_git(work, "ls-files", "--stage", "-z") == index_held
    assert worktree_bytes(work) == held
    assert len(marker_heads(world)) == gate_runs
    # Only restoring the original work lets the same run prove, confirm and complete.
    if target == "a.txt":
        (work / "a.txt").write_text(planned)
    elif target == "old.txt":
        (work / "old.txt").write_text(EXCLUDED_TEXT)
    else:
        (work / "stray.txt").unlink()
    resumed = world.execute(plan, gates, run_id)
    assert resumed.status == "COMPLETE", resumed.result()
    done = world.store().load(run_id).changeset
    assert done is not None and done.update is not None
    assert done.update.outcome == "CONFIRMED" and done.confirmed == [tip]
    assert done.residual_snapshot == world.repo().snapshot().fingerprint
    assert done.preserved == pending.preserved
    assert run_git(work, "ls-files", "--stage", "--", "old.txt") == excluded_entry
    assert len(marker_heads(world)) == gate_runs


@pytest.mark.parametrize("edited", ["a.txt", "old.txt"])
@pytest.mark.parametrize("interrupted", ["_move_ref", "_confirm"])
def test_recovered_update_is_confirmed_only_after_the_preservation_proof(
    world: World, monkeypatch: pytest.MonkeyPatch, interrupted: str, edited: str
) -> None:
    work = world.work
    planned = "one\ntwo\nthree\nresumed\n"
    originals = {"a.txt": planned, "old.txt": EXCLUDED_TEXT}
    (work / "a.txt").write_text(planned)
    (work / "old.txt").write_text(EXCLUDED_TEXT)
    run_git(work, "add", "old.txt")
    gates = world.recorder()
    plan = compile_draft(
        world.repo(),
        world.draft(
            [group("g1", "feat: resume", [final(b"a.txt")])],
            exclude={b"old.txt": "unrelated local experiment"},
        ),
        gates,
    )

    def interrupt(self: changeset._Run, *args: object) -> None:
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(changeset._Run, interrupted, interrupt)
        first = world.execute(plan, gates)

    assert (first.status, first.cancelled) == ("WAITING", True)
    run_id = first.result()["run_id"]
    assert isinstance(run_id, str)
    pending = world.store().load(run_id).changeset
    assert pending is not None and pending.update is not None
    assert pending.update.outcome == "PENDING" and pending.preserved is not None
    commit = pending.groups[0].commit
    # While the update awaits recovery the user edits committed or excluded work.
    (work / edited).write_text(originals[edited] + "late edit\n")
    held = worktree_bytes(work)
    gate_runs = len(marker_heads(world))

    refused = world.execute(plan, gates, run_id)

    assert refused.status == "BLOCKED", refused.result()
    assert refused.result()["confirmed_commits"] == []
    unchanged = world.store().load(run_id).changeset
    assert unchanged is not None and unchanged.update is not None
    assert unchanged.update.outcome == "PENDING"
    assert unchanged.residual_snapshot is None and unchanged.confirmed == []
    assert unchanged.preserved == pending.preserved
    # The recovered ref publication is a fact and stays accurate; the work is kept.
    assert git(work, "rev-parse", "refs/heads/feat/topic") == commit
    assert git(work, "symbolic-ref", "HEAD") == "refs/heads/feat/topic"
    assert worktree_bytes(work) == held
    assert len(marker_heads(world)) == gate_runs
    (work / edited).write_text(originals[edited])
    resumed = world.execute(plan, gates, run_id)
    assert resumed.status == "COMPLETE", resumed.result()
    done = world.store().load(run_id).changeset
    assert done is not None and done.update is not None
    assert done.update.outcome == "CONFIRMED" and done.confirmed == [commit]
    assert done.residual_snapshot == world.repo().snapshot().fingerprint
    assert len(marker_heads(world)) == gate_runs


@pytest.mark.parametrize("excluded", [False, True])
def test_journal_without_a_preserved_checkpoint_is_trusted_only_for_all_included_plans(
    world: World, monkeypatch: pytest.MonkeyPatch, excluded: bool
) -> None:
    work = world.work
    (work / "a.txt").write_text("one\ntwo\nthree\nlegacy\n")
    if excluded:
        (work / "old.txt").write_text(EXCLUDED_TEXT)
        run_git(work, "add", "old.txt")
    gates = world.recorder()
    plan = compile_draft(
        world.repo(),
        world.draft(
            [group("g1", "feat: legacy", [final(b"a.txt")])],
            exclude={b"old.txt": "unrelated local experiment"} if excluded else None,
        ),
        gates,
    )

    def interrupt(self: changeset._Run, *args: object) -> None:
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(changeset._Run, "_move_ref", interrupt)
        first = world.execute(plan, gates)

    assert (first.status, first.cancelled) == ("WAITING", True)
    run_id = first.result()["run_id"]
    assert isinstance(run_id, str)
    # A journal written before the checkpoint existed knows no preserved baseline.
    store = world.store()
    receipt = store.load(run_id)
    assert receipt.changeset is not None and receipt.changeset.update is not None
    receipt.changeset.preserved = None
    with store.mutation_lock():
        store.save(receipt)
    held = worktree_bytes(work)

    resumed = world.execute(plan, gates, run_id)

    done = world.store().load(run_id).changeset
    assert done is not None and done.update is not None
    # Unknown stays unknown: no digest is ever fabricated for the record.
    assert done.preserved is None
    assert worktree_bytes(work) == held
    if excluded:
        # Excluded work in place cannot be proven from the plan alone.
        assert resumed.status == "BLOCKED", resumed.result()
        assert done.update.outcome == "PENDING" and done.residual_snapshot is None
    else:
        # A plan that includes every inventoried item leaves nothing in place, so
        # clean committed paths prove the empty baseline.
        assert resumed.status == "COMPLETE", resumed.result()
        assert done.update.outcome == "CONFIRMED"
        assert done.residual_snapshot == world.repo().snapshot().fingerprint


# -- intermediate line provenance -----------------------------------------------------


@pytest.mark.parametrize(
    ("path", "staged", "working", "intermediate"),
    [
        pytest.param("dup.txt", True, "a\n", "a\na\n", id="repeated-line-in-new-file"),
        pytest.param(
            "a.txt",
            False,
            "one\ntwo\nthree\nfour\n",
            "one\ntwo\ntwo\nthree\n",
            id="repeated-line-in-existing-file",
        ),
        pytest.param(
            "a.txt",
            False,
            "one\ntwo\nthree\nfour\n",
            "two\none\nthree\nfour\n",
            id="reordered-lines",
        ),
    ],
)
def test_intermediate_state_cannot_repeat_or_reorder_source_lines(
    world: World, path: str, staged: bool, working: str, intermediate: str
) -> None:
    work = world.work
    (work / path).write_text(working)
    if staged:
        run_git(work, "add", path)
    invented = world.root / "invented.txt"
    invented.write_text(intermediate)
    gates = world.recorder()
    draft = world.draft(
        [
            group("g1", "feat: step", [partial(path.encode(), invented)]),
            group("g2", "feat: finish", [final(path.encode())], requires=["g1"]),
        ]
    )
    before = worktree_bytes(work)
    index_before = run_git(work, "ls-files", "--stage", "-z")

    with pytest.raises(ChangesetStop) as caught:
        compile_draft(world.repo(), draft, gates)

    assert caught.value.status == "NEEDS_JUDGMENT"
    assert git(work, "rev-parse", "HEAD") == world.base
    assert run_git(work, "ls-files", "--stage", "-z") == index_before
    assert worktree_bytes(work) == before


def test_large_intermediate_cannot_duplicate_shared_source_occurrences(
    world: World,
) -> None:
    work = world.work
    shared = "shared line\n" * 3000
    (work / "repeat.txt").write_text(f"old header\n{shared}old footer\n")
    run_git(work, "add", "repeat.txt")
    (work / "repeat.txt").write_text(f"new header\n{shared}new footer\n")
    invented = world.root / "invented.txt"
    invented.write_text(f"old header\n{shared}{shared}new footer\n")
    gates = world.recorder()
    draft = world.draft(
        [
            group("g1", "feat: step", [partial(b"repeat.txt", invented)]),
            group("g2", "feat: finish", [final(b"repeat.txt")], requires=["g1"]),
        ]
    )
    before = worktree_bytes(work)
    index_before = run_git(work, "ls-files", "--stage", "-z")

    with pytest.raises(ChangesetStop) as caught:
        compile_draft(world.repo(), draft, gates)

    assert caught.value.status == "NEEDS_JUDGMENT"
    assert git(work, "rev-parse", "HEAD") == world.base
    assert run_git(work, "ls-files", "--stage", "-z") == index_before
    assert worktree_bytes(work) == before


@pytest.mark.parametrize(
    ("source", "final_bytes", "invented_bytes"),
    [
        (b"x\r\ny\r\n", b"x\r\ny\r\nz\r\n", b"x\ny\n"),
        (b"x\ny\n", b"x\ny\nz\n", b"x\ny"),
        (b"x\ry\r", b"x\ry\rz\r", b"x\ny\n"),
        (b"x\ny\n", b"x\ny\nz\n", b"x\ry\r"),
        (b"alpha\nbeta\ngamma\n", b"gamma\nbeta\nalpha\n", b"beta\nbeta\n"),
    ],
    ids=[
        "crlf-to-lf",
        "missing-final-newline",
        "cr-to-lf",
        "lf-to-cr",
        "duplicate-shared-occurrence-across-reordered-states",
    ],
)
def test_intermediate_cannot_invent_source_occurrences_or_terminators(
    world: World, source: bytes, final_bytes: bytes, invented_bytes: bytes
) -> None:
    work = world.work
    (work / "lines.txt").write_bytes(source)
    run_git(work, "add", "lines.txt")
    (work / "lines.txt").write_bytes(final_bytes)
    invented = world.root / "invented.txt"
    invented.write_bytes(invented_bytes)
    gates = world.recorder()
    draft = world.draft(
        [
            group("g1", "feat: step", [partial(b"lines.txt", invented)]),
            group("g2", "feat: finish", [final(b"lines.txt")], requires=["g1"]),
        ]
    )
    before = worktree_bytes(work)
    index_before = run_git(work, "ls-files", "--stage", "-z")

    with pytest.raises(ChangesetStop) as caught:
        compile_draft(world.repo(), draft, gates)

    assert caught.value.status == "NEEDS_JUDGMENT"
    assert git(work, "rev-parse", "HEAD") == world.base
    assert run_git(work, "ls-files", "--stage", "-z") == index_before
    assert worktree_bytes(work) == before


def test_ordered_selection_of_head_index_and_final_lines_is_accepted(
    world: World,
) -> None:
    work = world.work
    (work / "a.txt").write_text("one\nTWO\nthree\n")
    run_git(work, "add", "a.txt")
    (work / "a.txt").write_text("one\nTWO\nthree\nfour\nFIVE\n")
    selection = world.root / "selection.txt"
    selection.write_text("one\ntwo\nthree\nfour\n")
    before = worktree_bytes(work)
    gates = world.recorder()
    plan = compile_draft(
        world.repo(),
        world.draft(
            [
                group("g1", "feat(a): add four", [partial(b"a.txt", selection)]),
                group("g2", "feat(a): finish", [final(b"a.txt")], requires=["g1"]),
            ]
        ),
        gates,
    )

    outcome = world.execute(plan, gates)

    assert outcome.status == "COMPLETE", outcome.result()
    tip = git(work, "rev-parse", "refs/heads/feat/topic")
    assert blob(work, f"{tip}~1", b"a.txt") == b"one\ntwo\nthree\nfour\n"
    assert blob(work, tip, b"a.txt") == b"one\nTWO\nthree\nfour\nFIVE\n"
    assert status(work) == b""
    assert worktree_bytes(work) == before


def _packet(**changes: object) -> dict[str, object]:
    packet: dict[str, object] = {
        "schema_version": 1,
        "sources": ["test policy: repository gates"],
        "gates": [{"name": "unit", "argv": ["make", "test"]}],
        "secret_scan": {"argv": ["scan", "{base}", "{head}"]},
        "local_gates_free": False,
    }
    return {**packet, **changes}


def test_gate_deadline_and_per_commit_round_trip_through_the_canonical_packet() -> None:
    plain = parse_gates(_packet())
    explicit = parse_gates(
        _packet(
            gates=[{"name": "unit", "argv": ["make", "test"], "timeout": 7200}],
            per_commit=True,
        )
    )

    assert (plain.per_commit, plain.gates[0].timeout) == (False, changeset.GATE_TIMEOUT)
    assert (explicit.per_commit, explicit.gates[0].timeout) == (True, 7200.0)
    for policy in (plain, explicit):
        assert parse_gates(json.loads(json.dumps(policy.canonical()))) == policy
    # Identities recorded before either field existed stay valid; each field moves it.
    assert plain.canonical() == _packet(
        secret_scan={"argv": ["scan", "{base}", "{head}"]}
    )
    assert (
        plain.gates[0].identity
        == hashlib.sha256(
            json.dumps(["unit", ["make", "test"]], ensure_ascii=True).encode()
        ).hexdigest()
    )
    assert explicit.identity != plain.identity
    assert explicit.gates[0].identity != plain.gates[0].identity


@pytest.mark.parametrize("timeout", [0, -1, True, "60", float("inf"), 86_401])
def test_a_gate_deadline_must_be_a_bounded_positive_number(timeout: object) -> None:
    with pytest.raises(PlanError, match="timeout"):
        parse_gates(
            _packet(gates=[{"name": "unit", "argv": ["make"], "timeout": timeout}])
        )


def test_per_commit_must_be_a_boolean() -> None:
    with pytest.raises(PlanError, match="per_commit"):
        parse_gates(_packet(per_commit="yes"))
