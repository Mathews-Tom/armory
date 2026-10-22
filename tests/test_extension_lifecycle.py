"""Disposable, real-artifact lifecycle safety and process-crash regressions."""

from __future__ import annotations

import json
import os
import select
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.extension_lifecycle import (
    HostLayout,
    LifecycleError,
    payload_problems,
    run_action,
)
from scripts.frontmatter import extract_body, parse_frontmatter

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "extensions" / "_fixtures" / "fixture-wordcount"
NAME = FIXTURE.name
CRASH = 72


@pytest.fixture
def sources(tmp_path: Path) -> Path:
    root = tmp_path / "sources"
    shutil.copytree(FIXTURE, root / NAME)
    return root


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / "host"
    path.mkdir()
    return path.resolve()


def _act(action: str, host: str, root: Path, sources: Path, name: str = NAME) -> str:
    return run_action(action, host, name, root, sources)


def _bump(sources: Path, version: str, name: str = NAME) -> None:
    definition = sources / name / "EXTENSION.md"
    text = definition.read_text()
    metadata = parse_frontmatter(text)
    metadata["metadata"]["version"] = version
    definition.write_text(
        f"---\n{yaml.safe_dump(metadata, sort_keys=False)}---\n{extract_body(text)}"
    )
    with (sources / name / "core" / "index.ts").open("a") as handle:
        handle.write(f"\n// release {version}\n")


def _sentinels(root: Path) -> dict[Path, bytes]:
    paths = {
        root / "receipts" / "kept.json": b'{"receipt":"foreign"}\n',
        root / ".armory-native" / "receipts" / "kept.json": b'{"receipt":"kept"}\n',
        root / ".armory-native" / "pending" / "draft.json": b'{"draft":"pending"}\n',
        root / ".armory-native" / "staging" / "foreign-note": b"not a transaction\n",
        root / "extensions" / "other" / "index.ts": b"// unrelated extension\n",
    }
    for path, data in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return paths


def _assert_sentinels(paths: dict[Path, bytes]) -> None:
    assert {path: path.read_bytes() for path in paths} == paths


def _record(layout: HostLayout) -> dict[str, Any]:
    record: dict[str, Any] = json.loads(layout.ownership.read_bytes())
    return record


def _optional_record(layout: HostLayout) -> dict[str, Any] | None:
    return _record(layout) if layout.ownership.exists() else None


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


def _config(root: Path, host: str) -> tuple[Path, bytes]:
    if host == "claude":
        path = root / "settings.json"
        data = b' { "model" : "x\\u0020y", "env" : { "KEEP" : "v", "CLAUDE_CODE_PLUGIN_DIRS" : "/opt/a::/opt/b:" }, "tail" : [1,  2] }\r\n'
    else:
        path = root / "config.yml"
        data = b'# keep header\ntheme: "dark#not-comment" # keep inline\nforeign: {x: 1, y:  2}\n'
    path.write_bytes(data)
    return path, data


def _assert_registration(layout: HostLayout, state: str | None) -> None:
    if layout.host == "claude":
        path = layout.root / "settings.json"
        settings = json.loads(path.read_bytes()) if path.exists() else {}
        value = settings.get("env", {}).get("CLAUDE_CODE_PLUGIN_DIRS", "")
        assert value.split(os.pathsep).count(str(layout.payload)) == (
            state == "enabled"
        )
    else:
        path = layout.root / "config.yml"
        config = yaml.safe_load(path.read_text()) if path.exists() else {}
        assert (config or {}).get("disabledExtensions", []).count(
            layout.omp_disabled_id
        ) == (state == "disabled")


def test_foreign_claude_registration_refusal_preserves_exact_preimage(
    root: Path, sources: Path
) -> None:
    layout = HostLayout(root, "claude", NAME)
    before = (
        '{ "env" : { "CLAUDE_CODE_PLUGIN_DIRS" : '
        + json.dumps("/opt/a::" + str(layout.payload) + ":")
        + ' }, "KEEP" :  [1,2] }\n'
    ).encode()
    (root / "settings.json").write_bytes(before)
    sentinels = _sentinels(root)
    snapshot = _snapshot(root)
    with pytest.raises(LifecycleError, match="does not own"):
        _act("install", "claude", root, sources)
    assert _snapshot(root) == snapshot
    assert (root / "settings.json").read_bytes() == before
    assert not layout.payload.exists()
    assert not layout.ownership.exists()
    _assert_sentinels(sentinels)


@pytest.mark.parametrize("host", ["omp", "claude"])
def test_versions_disabled_updates_and_data_survive_every_transition(
    host: str, root: Path, sources: Path
) -> None:
    layout = HostLayout(root, host, NAME)
    path, original = _config(root, host)
    sentinels = _sentinels(root)
    _act("install", host, root, sources)
    _assert_registration(layout, "enabled")
    if host == "claude":
        value = json.loads(path.read_bytes())["env"]["CLAUDE_CODE_PLUGIN_DIRS"]
        assert value == "/opt/a::/opt/b:" + os.pathsep + str(layout.payload)
        prefix, suffix = original.split(b'"/opt/a::/opt/b:"')
        assert path.read_bytes().startswith(prefix)
        assert path.read_bytes().endswith(suffix)
    else:
        assert path.read_bytes() == original
    _assert_sentinels(sentinels)
    _bump(sources, "1.0.1")
    _act("update", host, root, sources)
    assert _record(layout)["version"] == "1.0.1"
    assert b"release 1.0.1" in (layout.payload / "core" / "index.ts").read_bytes()
    _assert_registration(layout, "enabled")
    _assert_sentinels(sentinels)
    _act("disable", host, root, sources)
    disabled_config = path.read_bytes()
    _assert_registration(layout, "disabled")
    _assert_sentinels(sentinels)
    _bump(sources, "1.0.2")
    _act("update", host, root, sources)
    record = _record(layout)
    assert (record["version"], record["state"], record["pending"]) == (
        "1.0.2",
        "disabled",
        None,
    )
    assert payload_problems(layout.payload, record["files"]) == []
    assert path.read_bytes() == disabled_config
    _assert_registration(layout, "disabled")
    _assert_sentinels(sentinels)
    _act("install", host, root, sources)
    _assert_registration(layout, "enabled")
    _assert_sentinels(sentinels)
    _act("disable", host, root, sources)
    _act("remove", host, root, sources)
    assert path.read_bytes() == original
    assert not layout.payload.exists()
    assert not layout.ownership.exists()
    _assert_registration(layout, None)
    _assert_sentinels(sentinels)


@pytest.mark.parametrize(
    "original",
    [
        b"# header\n'disabledExtensions': [foreign,] # keep\ntheme: 'light'\n",
        b"# header\ndisabledExtensions: [foreign, # foreign trailing comma\n]\ntheme: dark\n",
        b"# header\ndisabledExtensions:\n-   'foreign' # inline\n# separate comment\ntheme: dark\n",
        b"disabledExtensions:\n  - |\n    foreign\ntheme: dark # unrelated\n",
        b"{ theme: 'dark', disabledExtensions: [foreign], } # flow map\n",
        b"  theme: 'dark' # indented root\n  foreign: {x:  1}\n",
        b"---\n# comments only\n...\n",
    ],
)
def test_commented_noncanonical_omp_configuration_roundtrips(
    original: bytes, root: Path, sources: Path
) -> None:
    path = root / "config.yml"
    path.write_bytes(original)
    _act("install", "omp", root, sources)
    _act("disable", "omp", root, sources)
    disabled = yaml.safe_load(path.read_text())["disabledExtensions"]
    assert disabled[-1] == f"extension-module:{NAME}"
    for line in original.splitlines():
        if b"#" in line:
            assert line.split(b"#", 1)[1] in path.read_bytes()
    _act("install", "omp", root, sources)
    assert path.read_bytes() == original
    _act("disable", "omp", root, sources)
    _act("remove", "omp", root, sources)
    assert path.read_bytes() == original


@pytest.mark.parametrize("origin", ["empty", "foreign-item"])
@pytest.mark.parametrize("style", ["|-", ">-"])
@pytest.mark.parametrize("action", ["install", "remove"])
@pytest.mark.parametrize("comment", [b"", b"# foreign suffix comment\n"])
def test_owned_block_scalar_removal_preserves_following_foreign_lines(
    origin: str,
    style: str,
    action: str,
    comment: bytes,
    root: Path,
    sources: Path,
) -> None:
    path = root / "config.yml"
    foreign = comment + b'theme: dark\nopaque: {keep: "synthetic"} # keep\n'
    prefix = (
        b"disabledExtensions:\n  - foreign\n"
        if origin == "foreign-item"
        else b"disabledExtensions: []\n"
    )
    path.write_bytes(prefix + foreign)
    path.chmod(0o640)
    _act("install", "omp", root, sources)
    _act("disable", "omp", root, sources)
    rewritten = "disabledExtensions:\n"
    if origin == "foreign-item":
        rewritten += "  - foreign\n"
    rewritten += f"  - {style}\n    extension-module:{NAME}\n"
    path.write_bytes(rewritten.encode() + foreign)

    _act(action, "omp", root, sources)

    foreign_lines = foreign.splitlines(keepends=True)
    assert (
        path.read_bytes().splitlines(keepends=True)[-len(foreign_lines) :]
        == foreign_lines
    )
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert yaml.safe_load(path.read_bytes()).get("disabledExtensions", []) == (
        ["foreign"] if origin == "foreign-item" else []
    )
    _assert_registration(
        HostLayout(root, "omp", NAME), "enabled" if action == "install" else None
    )


@pytest.mark.parametrize("host", ["omp", "claude"])
def test_foreign_config_edits_are_not_reformatted_or_discarded(
    host: str, root: Path, sources: Path
) -> None:
    layout = HostLayout(root, host, NAME)
    path, before = _config(root, host)
    if host == "claude":
        before = before.replace(b'"/opt/a::/opt/b:"', b'"\\u002fopt/a::/opt/b:"')
        path.write_bytes(before)
    _act("install", host, root, sources)
    if host == "omp":
        _act("disable", host, root, sources)
        with path.open("ab") as handle:
            handle.write(b"# NEW FOREIGN COMMENT\nnewForeign:  {z:  3}\n")
        _act("install", host, root, sources)
        assert (
            path.read_bytes()
            == before + b"# NEW FOREIGN COMMENT\nnewForeign:  {z:  3}\n"
        )
    else:
        content = path.read_bytes()
        path.write_bytes(
            content.replace(
                b'"tail" : [1,  2]', b'"tail" : [1,  2], "newForeign" : {"z":  3}'
            )
        )
        _act("disable", host, root, sources)
        assert b'"newForeign" : {"z":  3}' in path.read_bytes()
        assert (
            json.loads(path.read_bytes())["env"]["CLAUDE_CODE_PLUGIN_DIRS"]
            == "/opt/a::/opt/b:"
        )
        assert b'"\\u002fopt/a::/opt/b:"' in path.read_bytes()
    _assert_registration(layout, "enabled" if host == "omp" else "disabled")


# Faults happen *after* actual durable filesystem boundaries, then os._exit
# discards Python cleanup and releases the kernel lock. Recovery is a separate
# interpreter running the public entrypoint, not a same-process mock rollback.
_CHILD = r"""
import json, os, sys
from pathlib import Path
from scripts import extension_lifecycle as m
root, sources, host, name, action, fault = sys.argv[1:]
root, sources = Path(root), Path(sources)
layout = m.HostLayout(root.resolve(), host, name)
real_replace, real_rename, real_unlink = os.replace, os.rename, Path.unlink

def hit(point):
    if point == fault:
        os._exit(72)

def replace(src, dst, *args, **kwargs):
    point = None
    if Path(dst) == layout.ownership:
        record = json.loads(Path(src).read_bytes())
        pending = record['pending']
        point = 'final' if pending is None else {'prepared': 'journal', 'committed': 'commit', 'rolled-back': 'rollback'}[pending['phase']]
    elif Path(dst) == layout.config:
        point = 'config'
    result = real_replace(src, dst, *args, **kwargs)
    hit(point)
    return result

def rename(src, dst, *args, **kwargs):
    result = real_rename(src, dst, *args, **kwargs)
    if Path(dst) == layout.payload:
        hit('activate')
    if Path(dst).name == 'retired':
        hit('retire')
    return result

def unlink(path, *args, **kwargs):
    result = real_unlink(path, *args, **kwargs)
    if path == layout.config:
        hit('config')
    if path == layout.ownership:
        hit('final')
    if layout.staging in path.parents:
        hit('cleanup')
    return result

os.replace, os.rename, Path.unlink = replace, rename, unlink
try:
    print(m.run_action(action, host, name, root, sources))
except m.LifecycleError as error:
    print(str(error), file=sys.stderr)
    sys.exit(2)
"""


def _child(
    root: Path,
    sources: Path,
    host: str,
    action: str,
    fault: str = "none",
    *,
    name: str = NAME,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-c",
            _CHILD,
            str(root),
            str(sources),
            host,
            name,
            action,
            fault,
        ],
        cwd=REPO,
        text=True,
        capture_output=True,
        timeout=90,
        check=False,
    )


def _crash(root: Path, sources: Path, host: str, action: str, fault: str) -> None:
    result = _child(root, sources, host, action, fault)
    assert result.returncode == CRASH, (result.stdout, result.stderr, action, fault)


def _fault_cases() -> list[tuple[str, str, str]]:
    cases: list[tuple[str, str, str]] = []
    for host in ("omp", "claude"):
        for action in (
            "install",
            "update",
            "disable",
            "re-enable",
            "remove-enabled",
            "remove-disabled",
        ):
            points = ["journal", "commit", "final"]
            if action in ("update", "remove-enabled", "remove-disabled"):
                points += ["retire", "cleanup"]
            if action in ("install", "update"):
                points += ["activate"]
            if (
                action in ("disable", "re-enable")
                or (host == "claude" and action in ("install", "remove-enabled"))
                or (host == "omp" and action == "remove-disabled")
            ):
                points += ["config"]
            cases.extend((host, action, point) for point in points)
    return cases


@pytest.mark.parametrize(("host", "scenario", "fault"), _fault_cases())
def test_fresh_process_recovers_every_action_at_durable_boundaries(
    host: str, scenario: str, fault: str, root: Path, sources: Path
) -> None:
    layout = HostLayout(root, host, NAME)
    path, original_config = _config(root, host)
    sentinels = _sentinels(root)
    if scenario != "install":
        _act("install", host, root, sources)
    if scenario in ("re-enable", "remove-disabled"):
        _act("disable", host, root, sources)
    before = _optional_record(layout)
    config_before = path.read_bytes()
    ownership_before = layout.ownership.read_bytes() if before else None
    if scenario == "update":
        _bump(sources, "1.0.1")
    action = (
        "install"
        if scenario == "re-enable"
        else "remove"
        if scenario.startswith("remove-")
        else scenario
    )
    _crash(root, sources, host, action, fault)
    journal = _optional_record(layout)
    committed = fault in ("commit", "cleanup", "final")
    if fault != "final":
        assert journal is not None
        assert journal["pending"]["phase"] == ("committed" if committed else "prepared")
    _assert_sentinels(sentinels)
    # update triggers root recovery, then either reports absent/current or runs
    # a real update. Freeze source at the recovered preimage for rollback cases.
    if scenario == "update" and not committed:
        shutil.rmtree(sources / NAME)
        shutil.copytree(FIXTURE, sources / NAME)
    result = _child(root, sources, host, "update")
    assert result.returncode in (0, 2), (result.stdout, result.stderr)
    recovered = _optional_record(layout)
    if not committed:
        if before is None:
            assert recovered is None
            assert not layout.payload.exists()
            assert path.read_bytes() == original_config
        else:
            assert recovered == before
            assert layout.ownership.read_bytes() == ownership_before
            assert path.read_bytes() == config_before
            assert payload_problems(layout.payload, before["files"]) == []
            _assert_registration(layout, before["state"])
    elif scenario.startswith("remove-"):
        assert recovered is None
        assert not layout.payload.exists()
        assert path.read_bytes() == original_config
        _assert_registration(layout, None)
    else:
        assert recovered is not None
        state = "disabled" if scenario == "disable" else "enabled"
        assert recovered["state"] == state
        assert recovered["pending"] is None
        assert recovered["version"] == ("1.0.1" if scenario == "update" else "1.0.0")
        assert payload_problems(layout.payload, recovered["files"]) == []
        _assert_registration(layout, state)
    assert list(layout.staging.iterdir()) == [layout.staging / "foreign-note"]
    _assert_sentinels(sentinels)


@pytest.mark.parametrize("host", ["omp", "claude"])
@pytest.mark.parametrize(
    "damage", ["changed", "foreign-file", "foreign-empty-directory"]
)
@pytest.mark.parametrize("fault", ["activate", "commit"])
def test_ambiguous_update_recovery_keeps_new_old_and_journal(
    host: str, damage: str, fault: str, root: Path, sources: Path
) -> None:
    layout = HostLayout(root, host, NAME)
    _config(root, host)
    sentinels = _sentinels(root)
    _act("install", host, root, sources)
    before = _record(layout)
    _bump(sources, "1.0.1")
    _crash(root, sources, host, "update", fault)
    journal = _record(layout)
    retired = root / journal["pending"]["staged"] / "retired"
    if damage == "changed":
        (layout.payload / "core" / "index.ts").write_bytes(b"// user change\n")
    elif damage == "foreign-file":
        (layout.payload / "user-note").write_bytes(b"KEEP\n")
    else:
        (layout.payload / "user-directory").mkdir()
    snapshot = _snapshot(root)
    result = _child(root, sources, host, "remove")
    assert result.returncode == 2
    assert _snapshot(root) == snapshot
    assert _record(layout) == journal
    assert retired.is_dir()
    assert payload_problems(retired, before["files"]) == []
    assert layout.payload.is_dir()
    if damage == "foreign-empty-directory":
        assert (layout.payload / "user-directory").is_dir()
    _assert_sentinels(sentinels)


@pytest.mark.parametrize(
    "attack",
    [
        "absolute",
        "traversal",
        "unknown-schema",
        "unknown-ownership-schema",
        "unknown-action",
        "digest",
        "payload-digest",
        "version-binding",
        "ownership-preimage",
        "config-preimage",
        "action-binding",
        "staging-parent-link",
        "staging-leaf-link",
        "special-stage",
        "foreign-stage-data",
    ],
)
def test_malicious_or_foreign_pending_state_is_refused_without_deletion(
    attack: str, root: Path, sources: Path, tmp_path: Path
) -> None:
    layout = HostLayout(root, "omp", NAME)
    sentinels = _sentinels(root)
    _act("install", "omp", root, sources)
    _bump(sources, "1.0.1")
    _crash(root, sources, "omp", "update", "journal")
    record = _record(layout)
    pending = record["pending"]
    stage = root / pending["staged"]
    foreign = tmp_path / "outside"
    foreign.mkdir()
    (foreign / "KEEP").write_bytes(b"FOREIGN\n")
    if attack == "absolute":
        pending["staged"] = str(foreign)
    elif attack == "traversal":
        pending["staged"] = "../outside"
    elif attack == "unknown-schema":
        pending["schema_version"] = 999
    elif attack == "unknown-ownership-schema":
        record["schema_version"] = 999
    elif attack == "unknown-action":
        pending["action"] = "erase"
    elif attack == "digest":
        pending["after"]["files"]["../outside/KEEP"] = "0" * 64
    elif attack == "payload-digest":
        pending["after"]["files"]["core/index.ts"] = "0" * 64
    elif attack == "version-binding":
        pending["after"]["version"] = "9.9.9"
    elif attack == "ownership-preimage":
        pending["ownership_before"]["sha256"] = "0" * 64
    elif attack == "config-preimage":
        pending["config_before"]["sha256"] = "0" * 64
    elif attack == "action-binding":
        pending["action"] = "remove"
    elif attack == "staging-parent-link":
        saved = tmp_path / "saved-staging"
        layout.staging.rename(saved)
        layout.staging.symlink_to(saved, target_is_directory=True)
    elif attack == "staging-leaf-link":
        saved = tmp_path / "saved-stage"
        stage.rename(saved)
        stage.symlink_to(saved, target_is_directory=True)
    elif attack == "special-stage":
        saved = tmp_path / "saved-stage"
        stage.rename(saved)
        os.mkfifo(stage)
    else:
        (stage / "foreign-note").write_bytes(b"KEEP STAGING DATA\n")
    layout.ownership.write_text(json.dumps(record))
    journal_bytes = layout.ownership.read_bytes()
    payload_before = _snapshot(layout.payload)
    result = _child(root, sources, "omp", "remove")
    assert result.returncode == 2, result.stderr
    assert layout.ownership.read_bytes() == journal_bytes
    assert _snapshot(layout.payload) == payload_before
    assert (foreign / "KEEP").read_bytes() == b"FOREIGN\n"
    assert stage.exists() or stage.is_symlink()
    _assert_sentinels(sentinels)


@pytest.mark.parametrize("host", ["omp", "claude"])
@pytest.mark.parametrize("leaf", ["config", "ownership"])
def test_special_configuration_and_ownership_leaves_fail_without_opening(
    host: str, leaf: str, root: Path, sources: Path
) -> None:
    layout = HostLayout(root, host, NAME)
    if leaf == "ownership":
        _act("install", host, root, sources)
        path = layout.ownership
        path.unlink()
        action = "remove"
    else:
        path = layout.config
        action = "install"
    os.mkfifo(path)
    result = _child(root, sources, host, action)
    assert result.returncode == 2
    assert "regular file" in result.stderr
    assert stat.S_ISFIFO(path.lstat().st_mode)


def test_claude_colon_root_is_refused_before_mutation(
    tmp_path: Path, sources: Path
) -> None:
    root = tmp_path / "team:demo"
    root.mkdir()
    sentinels = _sentinels(root)
    before = _snapshot(root)
    with pytest.raises(LifecycleError, match="cannot be represented"):
        _act("install", "claude", root, sources)
    assert _snapshot(root) == before
    _assert_sentinels(sentinels)


_CONCURRENT = r"""
import fcntl, json, os, sys
from pathlib import Path
from scripts import extension_lifecycle as m
root, sources, host, name, action, mode, event_fd, release_fd = sys.argv[1:]
root, sources = Path(root), Path(sources)
event_fd, release_fd = int(event_fd), int(release_fd)
real_flock, real_replace = fcntl.flock, os.replace
notified = False

def flock(fd, operation):
    if mode == 'waiter' and operation == fcntl.LOCK_EX:
        os.write(event_fd, b'L')
    return real_flock(fd, operation)

def replace(src, dst, *args, **kwargs):
    global notified
    result = real_replace(src, dst, *args, **kwargs)
    if mode == 'holder' and not notified and str(dst).endswith(host + '-' + name + '.json'):
        record = json.loads(Path(dst).read_bytes())
        if record['pending'] is not None and record['pending']['phase'] == 'prepared':
            notified = True
            os.write(event_fd, b'J')
            if os.read(release_fd, 1) != b'R':
                raise RuntimeError('release pipe closed')
    return result

fcntl.flock, os.replace = flock, replace
print(m.run_action(action, host, name, root, sources))
"""


def _event(fd: int, expected: bytes) -> None:
    ready, _write, _error = select.select([fd], [], [], 90)
    assert ready, "child never reached its filesystem/lock boundary"
    assert os.read(fd, 1) == expected


@pytest.mark.parametrize("host", ["omp", "claude"])
@pytest.mark.parametrize("existing_config", [False, True])
def test_concurrent_features_serialize_shared_configuration(
    host: str, existing_config: bool, root: Path, sources: Path
) -> None:
    names = ["fixture-first", "fixture-second"]
    for name in names:
        target = sources / name
        shutil.copytree(FIXTURE, target)
        for path in target.rglob("*"):
            if path.is_file():
                path.write_text(path.read_text().replace(NAME, name))
    config_path = root / ("settings.json" if host == "claude" else "config.yml")
    config_bytes = _config(root, host)[1] if existing_config else None
    sentinels = _sentinels(root)
    action = "install"
    if host == "omp":
        for name in names:
            _act("install", host, root, sources, name)
        action = "disable"
    event_read, event_write = os.pipe()
    release_read, release_write = os.pipe()
    children: list[subprocess.Popen[str]] = []
    try:
        for index, name in enumerate(names):
            mode = "holder" if index == 0 else "waiter"
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    _CONCURRENT,
                    str(root),
                    str(sources),
                    host,
                    name,
                    action,
                    mode,
                    str(event_write),
                    str(release_read),
                ],
                cwd=REPO,
                pass_fds=(event_write, release_read),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            children.append(child)
            _event(event_read, b"J" if index == 0 else b"L")
        os.write(release_write, b"R")
        for child in children:
            stdout, stderr = child.communicate(timeout=90)
            assert child.returncode == 0, (stdout, stderr)
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.communicate()
        for fd in (event_read, event_write, release_read, release_write):
            os.close(fd)
    for name in names:
        layout = HostLayout(root, host, name)
        record = _record(layout)
        assert record["state"] == ("enabled" if host == "claude" else "disabled")
        assert record["pending"] is None
        assert payload_problems(layout.payload, record["files"]) == []
        _assert_registration(layout, record["state"])
    _assert_sentinels(sentinels)
    for name in names:
        _act("disable" if host == "claude" else "install", host, root, sources, name)
        _assert_sentinels(sentinels)
    if config_bytes is None:
        assert not config_path.exists()
    else:
        assert config_path.read_bytes() == config_bytes
    for name in names:
        _act("remove", host, root, sources, name)
    _assert_sentinels(sentinels)


@pytest.mark.parametrize("host", ["omp", "claude"])
@pytest.mark.parametrize("recovery_fault", ["activate", "rollback", "cleanup"])
def test_a_second_process_crash_during_rollback_is_recoverable(
    host: str, recovery_fault: str, root: Path, sources: Path
) -> None:
    layout = HostLayout(root, host, NAME)
    _config(root, host)
    sentinels = _sentinels(root)
    _act("install", host, root, sources)
    before = _record(layout)
    _bump(sources, "1.0.1")
    _crash(root, sources, host, "update", "activate")
    _crash(root, sources, host, "remove", recovery_fault)
    assert _record(layout)["pending"] is not None
    _assert_sentinels(sentinels)
    result = _child(root, sources, host, "disable")
    assert result.returncode == 0, (result.stdout, result.stderr)
    recovered = _record(layout)
    assert (recovered["version"], recovered["state"], recovered["pending"]) == (
        "1.0.0",
        "disabled",
        None,
    )
    assert payload_problems(layout.payload, before["files"]) == []
    _assert_registration(layout, "disabled")
    assert list(layout.staging.iterdir()) == [layout.staging / "foreign-note"]
    _assert_sentinels(sentinels)


@pytest.mark.parametrize(
    ("host", "scenario"),
    [
        ("claude", "install"),
        ("claude", "disable"),
        ("claude", "re-enable"),
        ("claude", "remove-enabled"),
        ("omp", "disable"),
        ("omp", "re-enable"),
        ("omp", "remove-disabled"),
    ],
)
def test_config_write_failure_restores_exact_transaction_preimages(
    host: str, scenario: str, root: Path, sources: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = HostLayout(root, host, NAME)
    path, _original = _config(root, host)
    sentinels = _sentinels(root)
    if scenario != "install":
        _act("install", host, root, sources)
    if scenario in ("re-enable", "remove-disabled"):
        _act("disable", host, root, sources)
    before = _optional_record(layout)
    config_before = path.read_bytes()
    ownership_before = layout.ownership.read_bytes() if before is not None else None
    replace = os.replace
    injected = False

    def fail_once(source: Any, destination: Any, *args: Any, **kwargs: Any) -> None:
        nonlocal injected
        replace(source, destination, *args, **kwargs)
        if Path(destination) == path and not injected:
            injected = True
            raise RuntimeError("configuration write failed after replacement")

    monkeypatch.setattr(os, "replace", fail_once)
    action = (
        "install"
        if scenario == "re-enable"
        else "remove"
        if scenario.startswith("remove-")
        else scenario
    )
    with pytest.raises(RuntimeError, match="configuration write failed"):
        _act(action, host, root, sources)
    assert injected
    assert _optional_record(layout) == before
    assert path.read_bytes() == config_before
    if before is None:
        assert not layout.payload.exists()
        assert not layout.ownership.exists()
    else:
        assert layout.ownership.read_bytes() == ownership_before
        assert payload_problems(layout.payload, before["files"]) == []
        _assert_registration(layout, before["state"])
    assert list(layout.staging.iterdir()) == [layout.staging / "foreign-note"]
    _assert_sentinels(sentinels)


@pytest.mark.parametrize("host", ["omp", "claude"])
def test_another_feature_cannot_adopt_an_ambiguous_pending_origin(
    host: str, root: Path, sources: Path
) -> None:
    layout = HostLayout(root, host, NAME)
    _config(root, host)
    sentinels = _sentinels(root)
    _act("install", host, root, sources)
    _bump(sources, "1.0.1")
    _crash(root, sources, host, "update", "activate")
    (layout.payload / "foreign-note").write_bytes(b"KEEP BOTH TREES\n")
    other_name = "fixture-other"
    other_source = sources / other_name
    shutil.copytree(FIXTURE, other_source)
    for path in other_source.rglob("*"):
        if path.is_file():
            path.write_text(path.read_text().replace(NAME, other_name))
    before = _snapshot(root)
    with pytest.raises(LifecycleError):
        _act("install", host, root, sources, other_name)
    assert _snapshot(root) == before
    other = HostLayout(root, host, other_name)
    assert not other.payload.exists()
    assert not other.ownership.exists()
    assert _record(layout)["pending"] is not None
    _assert_sentinels(sentinels)
