from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from conftest import Runner
from gitworld import ALICE, BOB, Repo, body, clone, solo_project


def upstream(tmp_path: Path) -> Repo:
    repo = Repo.init(tmp_path / "upstream")
    repo.commit(
        {f"src/lib/mod{i}.py": body(f"mod{i}", 60) for i in range(6)}, "platform", ALICE
    )
    repo.commit(
        {"pyproject.toml": '[project]\nname = "lib"\ndependencies = ["a==1"]\n'},
        "deps",
        ALICE,
    )
    return repo


def discover(
    cli: Runner, tmp_path: Path, repo: Path, *extra: str, name: str = "run"
) -> dict[str, Any]:
    code, out = cli(
        "discover",
        "--repo",
        str(repo),
        "--candidate",
        "email:bob@example.com",
        "--offline",
        "--out",
        str(tmp_path / name),
        *extra,
    )
    assert code in {0, 3}, out
    data: dict[str, Any] = json.loads((tmp_path / name / "forensics.json").read_text())[
        "repositories"
    ][0]
    return data


def test_unchanged_fork_gives_no_authorship_credit(tmp_path: Path, cli: Runner) -> None:
    up = upstream(tmp_path)
    fork = clone(up.path, tmp_path / "fork")
    r = discover(cli, tmp_path, fork.path, "--upstream", str(up.path))
    assert r["lineage"]["relationship"] == "declared_upstream"
    assert r["lineage"]["ancestry"] == "shared_history"
    assert r["lineage"]["delta_kind"] == "unchanged"
    assert r["attribution"]["surviving_lines"]["candidate"] == 0
    assert (
        r["attribution"]["surviving_lines"]["inherited"]
        == r["attribution"]["surviving_lines"]["total"]
    )


def test_dependency_only_fork_is_classified(tmp_path: Path, cli: Runner) -> None:
    up = upstream(tmp_path)
    fork = clone(up.path, tmp_path / "fork")
    fork.commit(
        {"pyproject.toml": '[project]\nname = "lib"\ndependencies = ["a==2"]\n'},
        "bump",
        BOB,
    )
    r = discover(cli, tmp_path, fork.path, "--upstream", str(up.path))
    assert r["lineage"]["delta_kind"] == "dependency_only"
    assert r["lineage"]["candidate_fork_only_commits"] == 1


def test_deep_fork_credits_only_the_delta(tmp_path: Path, cli: Runner) -> None:
    up = upstream(tmp_path)
    fork = clone(up.path, tmp_path / "fork")
    fork.commit(
        {f"src/ext/new{i}.py": body(f"new{i}", 240) for i in range(12)},
        "extension subsystem",
        BOB,
    )
    fork.commit({"src/lib/mod0.py": body("mod0", 75)}, "refactor mod0", BOB)
    r = discover(cli, tmp_path, fork.path, "--upstream", str(up.path))
    lin, att = r["lineage"], r["attribution"]
    assert lin["delta_kind"] == "substantial"
    assert lin["inherited_commits"] == 2 and lin["candidate_fork_only_commits"] == 2
    assert att["surviving_lines"]["inherited"] > 0
    mod5 = next(f for f in r["files"] if f["path"] == "src/lib/mod5.py")
    assert mod5["candidate_lines"] == 0 and mod5["inherited_lines"] == mod5["lines"]
    assert any(p.startswith("src/ext/") for p in lin["delta"]["new_paths"])


def test_upstream_sync_merges_stay_inherited(tmp_path: Path, cli: Runner) -> None:
    up = upstream(tmp_path)
    fork = clone(up.path, tmp_path / "fork")
    fork.commit({"src/ext/a.py": body("a", 30)}, "fork work", BOB)
    up.commit({"src/lib/later.py": body("later", 60)}, "upstream later", ALICE)
    fork.git(
        "pull", "--quiet", "--no-rebase", "--no-edit", "origin", "main", author=BOB
    )
    r = discover(cli, tmp_path, fork.path, "--upstream", str(up.path))
    assert r["lineage"]["upstream_sync_merges"] == 1
    later = next(f for f in r["files"] if f["path"] == "src/lib/later.py")
    assert later["candidate_lines"] == 0


def test_candidate_upstream_contributions_are_counted_separately(
    tmp_path: Path, cli: Runner
) -> None:
    up = upstream(tmp_path)
    up.commit({"src/lib/patch.py": body("patch", 30)}, "accepted patch", BOB)
    fork = clone(up.path, tmp_path / "fork")
    r = discover(cli, tmp_path, fork.path, "--upstream", str(up.path))
    assert r["lineage"]["candidate_upstream_commits"] == 1
    assert r["attribution"]["role"] == "upstream_contributor_only"


def test_manual_copy_without_shared_history_uses_content_baseline(
    tmp_path: Path, cli: Runner
) -> None:
    up = upstream(tmp_path)
    copy = Repo.init(tmp_path / "copy")
    files = {
        str(p.relative_to(up.path)): p.read_text()
        for p in up.path.rglob("*")
        if p.is_file() and ".git" not in p.parts
    }
    copy.commit(files, "initial import", BOB)
    copy.commit(
        {
            "src/lib/mod1.py": body("mod1", 60)
            + "\ndef bob_addition(x):\n    return x * 2\n"
        },
        "extend mod1",
        BOB,
    )
    r = discover(cli, tmp_path, copy.path, "--upstream", str(up.path))
    lin = r["lineage"]
    assert lin["ancestry"] == "no_common_ancestor"
    assert lin["content_baseline"]["blob_overlap"] == 1.0
    mod1 = next(f for f in r["files"] if f["path"] == "src/lib/mod1.py")
    assert 0 < mod1["candidate_lines"] < 5
    assert (
        r["attribution"]["surviving_lines"]["inherited"]
        > r["attribution"]["surviving_lines"]["candidate"]
    )


def test_copy_without_declared_upstream_is_flagged_not_trusted(
    tmp_path: Path, cli: Runner
) -> None:
    repo = solo_project(tmp_path / "copied", BOB)
    repo.commit(
        {
            "README.md": "# queue\n\nForked from https://github.com/upstream-org/queue with local changes.\n"
        },
        "readme",
        BOB,
    )
    r = discover(cli, tmp_path, repo.path)
    assert r["lineage"]["relationship"] == "none" and r["lineage"]["hints"]
    assert "possible_undeclared_upstream" in {lim["code"] for lim in r["limitations"]}
    assert r["attribution"]["attribution_confidence"] == "medium"


def test_unreachable_upstream_lowers_confidence(tmp_path: Path, cli: Runner) -> None:
    up = upstream(tmp_path)
    fork = clone(up.path, tmp_path / "fork")
    fork.commit({"src/ext/a.py": body("a", 30)}, "fork work", BOB)
    gone = tmp_path / "gone"
    shutil.copytree(up.path, gone)
    shutil.rmtree(gone)
    r = discover(cli, tmp_path, fork.path, "--upstream", str(gone))
    assert (
        r["lineage"]["upstream_available"] is False
        and r["lineage"]["ancestry"] == "unknown"
    )
    assert "upstream_unavailable" in {lim["code"] for lim in r["limitations"]}
    assert r["attribution"]["attribution_confidence"] != "high"


def test_host_declared_fork_and_template_are_followed(
    tmp_path: Path, cli: Runner
) -> None:
    up = upstream(tmp_path)
    fork = clone(up.path, tmp_path / "fork")
    fork.git("remote", "set-url", "origin", "https://github.com/bob/lib.git")
    fork.commit({"src/ext/a.py": body("a", 30)}, "fork work", BOB)
    fixture = tmp_path / "host.json"
    fixture.write_text(
        json.dumps(
            {
                "repos": {
                    "bob/lib": {
                        "fork": True,
                        "parent": {"full_name": "alice/lib", "clone_url": str(up.path)},
                    }
                }
            }
        )
    )
    code, _ = cli(
        "discover",
        "--repo",
        str(fork.path),
        "--candidate",
        "email:bob@example.com",
        "--host-fixture",
        str(fixture),
        "--out",
        str(tmp_path / "run"),
    )
    assert code == 0
    r = json.loads((tmp_path / "run" / "forensics.json").read_text())["repositories"][0]
    assert (
        r["lineage"]["relationship"] == "host_fork"
        and r["lineage"]["upstream_locator"] == "alice/lib"
    )
    assert r["lineage"]["ancestry"] == "shared_history"

    templated = Repo.init(tmp_path / "templated")
    files = {
        str(p.relative_to(up.path)): p.read_text()
        for p in up.path.rglob("*")
        if p.is_file() and ".git" not in p.parts
    }
    templated.commit(files, "Initial commit", BOB)
    templated.git("remote", "add", "origin", "https://github.com/bob/fromtpl.git")
    fixture.write_text(
        json.dumps(
            {
                "repos": {
                    "bob/fromtpl": {
                        "fork": False,
                        "template_repository": {
                            "full_name": "alice/lib",
                            "clone_url": str(up.path),
                        },
                    }
                }
            }
        )
    )
    code, _ = cli(
        "discover",
        "--repo",
        str(templated.path),
        "--candidate",
        "email:bob@example.com",
        "--host-fixture",
        str(fixture),
        "--out",
        str(tmp_path / "run2"),
    )
    r = json.loads((tmp_path / "run2" / "forensics.json").read_text())["repositories"][
        0
    ]
    assert r["lineage"]["relationship"] == "template"
    assert r["lineage"]["ancestry"] == "no_common_ancestor"
    assert r["attribution"]["surviving_lines"]["candidate"] == 0
