"""Deterministic manual-driver boundaries; no coding host or remote evidence needed."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import pty
import select
import shutil
import stat
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from scripts.build_extensions import build_feature

FEATURE = Path(__file__).resolve().parents[1] / "extensions" / "delivery-radar"
SCENARIOS = (
    "success",
    "failure",
    "reopen",
    "freshness",
    "changed-during-run",
    "cancellation",
    "private-output",
    "native-text",
)


def load_driver(host: str) -> ModuleType:
    """Restore the sibling import's fixed cache key and any import-path addition."""
    name = f"_delivery_radar_{host}_boundary"
    names = (name, "_armory_delivery_omp_smoke")
    previous = {key: sys.modules.get(key) for key in names}
    previous_path = sys.path[:]
    spec = importlib.util.spec_from_file_location(
        name, FEATURE / "tests" / f"{host}-smoke.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    try:
        sys.modules[name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = previous_path
        for key, value in previous.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value
    return module


@pytest.fixture(params=["omp", "claude"])
def driver(request: pytest.FixtureRequest) -> ModuleType:
    return load_driver(request.param)


def validator(driver: ModuleType) -> ModuleType:
    return driver.shared if hasattr(driver, "shared") else driver


@pytest.fixture
def evidence() -> tuple[dict[str, Any], dict[str, Any]]:
    """A merged fact with deliberately unknown policy and publication evidence."""
    expected = {
        "repository": "Mathews-Tom/armory",
        "number": 191,
        "headOid": "a" * 40,
        "baseOid": "b" * 40,
        "title": 'Keep  two spaces and "quoted" provenance',
        "url": "https://github.com/Mathews-Tom/armory/pull/191",
        "state": "MERGED",
        "requiredPolicyAvailable": False,
    }

    def dimension(state: str, reason: str, source: str) -> dict[str, Any]:
        return {"state": state, "reasons": [reason], "sources": [source]}

    pull = {
        key: expected[key] for key in ("number", "headOid", "baseOid", "title", "url")
    }
    pull.update(
        {
            "observedAt": 1500,
            "diagnostics": [],
            "implementation": dimension(
                "passed", "Implementation is merged", "pull.state"
            ),
            "verification": dimension(
                "unknown", "required policy: unavailable", "requiredPolicy"
            ),
            "review": dimension(
                "unknown", "required policy: unavailable", "requiredPolicy"
            ),
            "merge": dimension(
                "passed",
                "Already merged (not proof of verification or publication)",
                "pull.state",
            ),
            "publication": dimension(
                "unknown", "No publication source selected", "selection"
            ),
            "action": "owner-decision",
            "nextAction": "Select publication evidence; do not infer it from merge",
        }
    )
    return expected, {
        "schema": "armory.delivery-radar.view/v1",
        "repository": expected["repository"],
        "viewerId": "viewer-synthetic",
        "observedAt": 1500,
        "pulls": [pull],
        "edges": [],
        "diagnostics": [],
    }


def test_merged_fact_preserves_unknown_policy_and_publication(
    driver: ModuleType,
    evidence: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    expected, view = evidence
    observed = validator(driver).validate_view(view, expected, 1000, 2000)
    pull = observed["pulls"][0]
    assert pull["merge"]["state"] == "passed"
    assert [
        pull[name]["state"] for name in ("verification", "review", "publication")
    ] == [
        "unknown",
        "unknown",
        "unknown",
    ]
    assert pull["action"] == "owner-decision"


@pytest.mark.parametrize(
    "field,value",
    [
        ("repository", "Other/repository"),
        ("number", 190),
        ("headOid", "c" * 40),
        ("baseOid", "d" * 40),
        ("title", 'Keep two spaces and "quoted" provenance'),
        ("url", "https://github.com/Other/repository/pull/191"),
    ],
)
def test_view_rejects_mismatched_independent_selection_and_provenance(
    driver: ModuleType,
    evidence: tuple[dict[str, Any], dict[str, Any]],
    field: str,
    value: object,
) -> None:
    expected, view = evidence
    target = view if field == "repository" else view["pulls"][0]
    target[field] = value
    with pytest.raises(validator(driver).Failure):
        validator(driver).validate_view(view, expected, 1000, 2000)


@pytest.mark.parametrize("selection", ["empty", "duplicate", "additional"])
def test_singleton_selection_cannot_hide_missing_or_extra_pulls(
    driver: ModuleType,
    evidence: tuple[dict[str, Any], dict[str, Any]],
    selection: str,
) -> None:
    expected, view = evidence
    if selection == "empty":
        view["pulls"] = []
    else:
        additional = copy.deepcopy(view["pulls"][0])
        if selection == "additional":
            additional["number"] = 192
        view["pulls"].append(additional)
    with pytest.raises(validator(driver).Failure):
        validator(driver).validate_view(view, expected, 1000, 2000)


@pytest.mark.parametrize("dimension", ["verification", "review", "publication"])
def test_merged_pr_cannot_upgrade_unavailable_evidence_to_passed(
    driver: ModuleType,
    evidence: tuple[dict[str, Any], dict[str, Any]],
    dimension: str,
) -> None:
    expected, view = evidence
    view["pulls"][0][dimension]["state"] = "passed"
    with pytest.raises(validator(driver).Failure):
        validator(driver).validate_view(view, expected, 1000, 2000)


def test_missing_publication_cannot_be_reported_as_no_remaining_action(
    driver: ModuleType,
    evidence: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    expected, view = evidence
    view["pulls"][0]["action"] = "none"
    with pytest.raises(validator(driver).Failure):
        validator(driver).validate_view(view, expected, 1000, 2000)


@pytest.mark.parametrize("observed_at", [999, 2001])
def test_out_of_command_observation_cannot_qualify_freshness(
    driver: ModuleType,
    evidence: tuple[dict[str, Any], dict[str, Any]],
    observed_at: int,
) -> None:
    expected, view = evidence
    view["observedAt"] = view["pulls"][0]["observedAt"] = observed_at
    with pytest.raises(validator(driver).Failure):
        validator(driver).validate_view(view, expected, 1000, 2000)


def terminal_frame(payload: str) -> str:
    if payload.startswith("{"):
        payload = json.dumps(
            json.loads(payload), separators=(",", ":"), ensure_ascii=True
        ).replace(" ", "\\u0020")
    payload = f"delivery-radar: {payload}"
    rows = [payload[index : index + 220] for index in range(0, len(payload), 220)]
    return "\n".join(
        [
            "┌" + "─" * 220 + "┐",
            *("│" + row.ljust(220) + "│" for row in rows),
            "└" + "─" * 220 + "┘",
        ]
    )


def test_current_tty_answer_requires_new_complete_frame_and_preserves_provenance(
    tmp_path: Path,
    evidence: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    driver = load_driver("claude")
    native = driver.NativeTTY([], tmp_path, {})
    native.pending = "/armory-delivery refresh Mathews-Tom/armory 191 --json"
    expected, view = evidence
    old_view = copy.deepcopy(view)
    old_view["pulls"][0]["headOid"] = "e" * 40
    old_answer = json.dumps({"view": old_view, "transition": False})
    current_answer = json.dumps({"view": view, "transition": True})
    history = f"❯ {native.pending}\n{terminal_frame(old_answer)}\n❯ {native.pending}\n"
    assert native.answer_text(history.encode()) is None
    assert (
        native.answer_text((history + terminal_frame(current_answer)).encode()) is None
    )
    framed = native.answer_text(
        (history + terminal_frame(current_answer) + "\n❯ ").encode()
    )
    assert framed is not None
    observed = driver.refresh_answer(framed, expected, 1000, 2000)
    assert observed == {"view": view, "transition": True}
    assert observed["view"]["pulls"][0]["title"] == expected["title"]


@contextmanager
def buffered_terminal(driver: ModuleType, cwd: Path, output: str) -> Iterator[Any]:
    """Exercise the actual exit/drain path with one bounded, already-exited child."""
    native = driver.NativeTTY([], cwd, {})
    master, slave = pty.openpty()
    native.master = master
    try:
        native.process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                f"import sys; sys.stdout.write({output!r}); sys.stdout.flush()",
            ],
            stdin=subprocess.DEVNULL,
            stdout=slave,
            stderr=slave,
        )
        # Drain only the prefix so a large frame cannot block on the small macOS
        # PTY buffer. Keep the final response and prompt queued for the exit path.
        prefix = max(0, len(output.encode()) - 256)
        while len(native.raw) < prefix:
            assert select.select([master], [], [], 5)[0], "synthetic PTY stalled"
            native.receive(os.read(master, min(256, prefix - len(native.raw))))
        native.process.wait(timeout=5)
        yield native
    finally:
        if native.process is not None and native.process.poll() is None:
            native.process.kill()
            native.process.wait(timeout=5)
        os.close(slave)
        os.close(master)


def test_exited_tty_retains_buffered_final_evidence(
    tmp_path: Path,
    evidence: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    driver = load_driver("claude")
    expected, view = evidence
    command = "/armory-delivery refresh Mathews-Tom/armory 191 --json"
    answer = json.dumps({"view": view, "transition": False})
    output = f"❯ {command}\n{terminal_frame(answer)}\n❯ "
    with buffered_terminal(driver, tmp_path, output) as native:
        native.pending = command
        framed = native.finish(0)
        assert driver.refresh_answer(framed, expected, 1000, 2000) == {
            "view": view,
            "transition": False,
        }
        assert native.pending is None
        assert native.answers == [{"command": command, "text": framed}]


@pytest.mark.parametrize(
    "interaction",
    [
        "Do you trust the files in this folder?",
        "Please log in",
        "Permission required",
    ],
)
def test_buffered_trust_login_or_policy_prompt_cannot_pass_as_final_evidence(
    tmp_path: Path,
    evidence: tuple[dict[str, Any], dict[str, Any]],
    interaction: str,
) -> None:
    driver = load_driver("claude")
    _, view = evidence
    command = "/armory-delivery refresh Mathews-Tom/armory 191 --json"
    answer = json.dumps({"view": view, "transition": False})
    output = f"❯ {command}\n{terminal_frame(answer)}\n{interaction}\n❯ "
    with buffered_terminal(driver, tmp_path, output) as native:
        native.pending = command
        with pytest.raises(driver.Unavailable):
            native.finish(0)
        assert native.interaction_required is True
        assert native.answers == []
        assert native.pending == command


@pytest.mark.parametrize("error_type", [OSError, IndexError, TypeError, ValueError])
def test_unexpected_prerequisite_or_protocol_error_writes_sanitized_not_run_report(
    driver: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error_type: type[Exception],
) -> None:
    tmp_path.chmod(0o700)
    report_path = tmp_path / "report.json"
    private_detail = "private-token-and-protocol-detail\n\x1b[31m"

    def unavailable(*args: object) -> None:
        raise error_type(private_detail)

    monkeypatch.setattr(driver, "execute", unavailable)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smoke",
            "--feature-dir",
            str(FEATURE),
            "--report",
            str(report_path),
        ],
    )
    previous_umask = os.umask(0o077)
    try:
        assert driver.main() == 3
    finally:
        os.umask(previous_umask)
    serialized = report_path.read_text()
    report = json.loads(serialized)
    assert report["status"] == "unavailable"
    assert report["reasonCode"] == "native-prerequisite-or-protocol-unavailable"
    assert [case["name"] for case in report["scenarios"]] == list(SCENARIOS)
    assert all(case["status"] == "not-run" for case in report["scenarios"])
    assert all(case["assertion"] for case in report["scenarios"])
    assert stat.S_IMODE(report_path.stat().st_mode) == 0o600
    console = capsys.readouterr()
    assert private_detail not in serialized + console.out + console.err
    assert (
        "private-token-and-protocol-detail"
        not in serialized + console.out + console.err
    )


@pytest.mark.parametrize("failure", ["interrupted", "unexpected"])
def test_unproven_cleanup_retains_live_owned_process_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    driver = load_driver("claude")
    artifacts = build_feature(FEATURE, tmp_path / "build")
    settings = tmp_path / "synthetic-settings.json"
    settings.write_text("{}")
    report_path = tmp_path / "report.json"
    roots: list[Path] = []
    children: list[subprocess.Popen[bytes]] = []

    def prepared(*args: Any) -> Path:
        roots.append(args[2])
        return artifacts["claude"]

    class LocalOwnedHost:
        def __init__(self, *args: object) -> None:
            pass

        def start(self) -> None:
            child = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            children.append(child)
            (roots[0] / "owned.pid").write_text(str(child.pid))

        def command(self, command: str) -> str:
            raise driver.Failure("synthetic-scenario-stop")

    def interrupted(*args: object) -> None:
        raise driver.Unavailable("native-driver-interrupted")

    def unexpected(*args: object) -> None:
        raise RuntimeError("synthetic-cleanup-error")

    tmp_path.chmod(0o700)
    monkeypatch.setattr(driver, "context", lambda args: (tmp_path, settings))
    monkeypatch.setattr(driver, "prepare_artifact", prepared)
    monkeypatch.setattr(driver.shutil, "which", lambda name: sys.executable)
    reviewed_version = driver.load_metadata(FEATURE).exercised["claude"][0].version
    monkeypatch.setattr(
        driver.shared, "finite", lambda *args: reviewed_version.encode()
    )
    monkeypatch.setattr(driver, "NativeTTY", LocalOwnedHost)
    if failure == "interrupted":
        monkeypatch.setattr(driver, "reversed", interrupted, raising=False)
    else:
        monkeypatch.setattr(driver, "quiesce_owned_work", unexpected)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smoke",
            "--feature-dir",
            str(FEATURE),
            "--artifact",
            str(artifacts["claude"]),
            "--report",
            str(report_path),
        ],
    )
    previous_umask = os.umask(0o077)
    try:
        if failure == "interrupted":
            assert driver.main() == 1
            report = json.loads(report_path.read_text())
            assert report["status"] == "failed"
            assert report["reasonCode"] == "native-cleanup-not-proven"
            assert report["ownedScratchRetainedForUnprovenCleanup"] is True
        else:
            with pytest.raises(RuntimeError, match="synthetic-cleanup-error"):
                driver.main()
        assert children[0].poll() is None
        assert (roots[0] / "owned.pid").read_text() == str(children[0].pid)
    finally:
        os.umask(previous_umask)
        for child in children:
            driver.shared.stop_process(child, graceful=False)
        for root in roots:
            if root.exists():
                shutil.rmtree(root)


def test_bundled_helper_refuses_invalid_selection_before_any_observation(
    tmp_path: Path,
) -> None:
    bun = shutil.which("bun")
    assert bun is not None, "the pinned Bun toolchain is required"
    artifacts = build_feature(FEATURE, tmp_path / "build")
    result = subprocess.run(
        [
            bun,
            str(artifacts["claude"] / "helpers" / "cli.js"),
            "refresh",
            "--repo",
            "Mathews-Tom/armory",
            "--prs",
            "0",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 2


def test_native_correlation_uses_directory_identity_without_relaxing_session(
    tmp_path: Path,
) -> None:
    driver = load_driver("omp")
    actual = tmp_path / "workspace"
    actual.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    host = SimpleNamespace(session="selected-session", cwd=actual)
    answer = {
        "details": {
            "correlation": {"host": "omp", "sessionId": host.session, "cwd": str(alias)}
        }
    }
    assert driver.correlation(answer, host)["correlation"]["sessionId"] == host.session
    answer["details"]["correlation"]["sessionId"] = "replaced-session"
    with pytest.raises(driver.Failure):
        driver.correlation(answer, host)


def test_json_tty_frame_excludes_terminal_chrome_but_rejects_second_answer(
    tmp_path: Path,
    evidence: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    driver = load_driver("claude")
    expected, view = evidence
    native = driver.NativeTTY([], tmp_path, {})
    native.pending = "/armory-delivery refresh Mathews-Tom/armory 191 --json"
    payload = json.dumps({"view": view, "transition": False})
    rendered = f"❯ {native.pending}\n{terminal_frame(payload)}\nUnrelated host notice\n{'─' * 240}\n❯ "
    answer = native.answer_text(rendered.encode())
    assert driver.json_answer(answer)["view"]["pulls"][0]["title"] == expected["title"]
    other = terminal_frame(json.dumps({"error": "operation-failed"}))
    duplicate = f"❯ {native.pending}\n{terminal_frame(payload)}\n{other}\n❯ "
    with pytest.raises(driver.Failure):
        native.answer_text(duplicate.encode())


def test_json_tty_repaint_keeps_waiting_despite_a_retained_prompt(
    tmp_path: Path,
) -> None:
    driver = load_driver("claude")
    native = driver.NativeTTY([], tmp_path, {})
    native.pending = "/armory-delivery refresh Mathews-Tom/armory 191 --json"
    partial = f'❯ {native.pending}\n┌─────┐\n│delivery-radar: {{"view":{{"title":"still painting│\n└─────┘\n◐ refresh\n❯ '
    assert native.answer_text(partial.encode()) is None
    complete_payload = json.dumps({"view": {"title": "painted"}, "transition": False})
    complete = f"❯ {native.pending}\n{terminal_frame(complete_payload)}\n❯ "
    assert driver.json_answer(native.answer_text(complete.encode())) == {
        "view": {"title": "painted"},
        "transition": False,
    }


@pytest.mark.parametrize("suffix", [" --json", ",191 --json", "0 --json"])
def test_reply_for_a_longer_command_cannot_satisfy_pending_short_command(
    tmp_path: Path,
    suffix: str,
) -> None:
    driver = load_driver("claude")
    native = driver.NativeTTY([], tmp_path, {})
    native.pending = "/armory-delivery refresh Mathews-Tom/armory 191"
    previous = native.pending + suffix
    old = terminal_frame(json.dumps({"error": "invalid-arguments"}))
    repaint = f"❯ {previous}\n{old}\n❯ /armory-delivery ref"
    assert native.answer_text(repaint.encode()) is None
