"""Consumer-boundary tests for the ``measure`` CLI on fictional OMP fixtures.

Every name, path and identifier below is invented for these tests. The CLI is
invoked as a subprocess through ``sys.executable`` against explicit synthetic
roots, with ``HOME`` redirected so no default location is ever read.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

ENTRY = Path(__file__).resolve().parent.parent / "scripts" / "skill_inventory.py"
AS_OF = "2026-10-01T00:00:00Z"
INSTALLED = "quokka-planner"
OTHER_INSTALLED = "marmot-reviewer"
SESSION_ID = "fictional-session-7c1d"
CWD = "/fictional/workspace/orchard"


class Env:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.home = root / "home"
        self.home.mkdir()
        self.logs = root / "logs"
        self.logs.mkdir()
        self.skills = root / "skills"
        self.skills.mkdir()
        self.snapshot = root / "private" / "binding.json"
        self.snapshot.parent.mkdir(mode=0o700)
        for name in (INSTALLED, OTHER_INSTALLED):
            directory = self.skills / name
            directory.mkdir()
            (directory / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: Fictional skill {name}.\n---\n\n"
                f"# {name}\n\nBody text.\n"
            )

    @property
    def installed_file(self) -> Path:
        return self.skills / INSTALLED / "SKILL.md"

    def write_log(self, name: str, lines: Sequence[object | str]) -> Path:
        path = self.logs / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(
                (line if isinstance(line, str) else json.dumps(line)) + "\n"
                for line in lines
            )
        )
        return path

    def measure(
        self, *extra: str, window_days: int = 90
    ) -> subprocess.CompletedProcess[str]:
        return run(
            self,
            "measure",
            "--harness",
            "omp",
            "--as-of",
            AS_OF,
            "--window-days",
            str(window_days),
            "--snapshot",
            str(self.snapshot),
            "--aggregate-only",
            "--log-root",
            str(self.logs),
            "--skill-root",
            str(self.skills),
            *extra,
        )


def run(env: Env, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ENTRY), *args],
        capture_output=True,
        text=True,
        timeout=60,
        env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(env.home),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        cwd=env.root,
        check=False,
    )


def ms(stamp: str) -> int:
    return int(datetime.fromisoformat(stamp).astimezone(UTC).timestamp() * 1000)


def header(
    stamp: str = "2026-09-01T10:00:00.000Z", version: int = 3
) -> dict[str, object]:
    return {
        "type": "session",
        "version": version,
        "id": SESSION_ID,
        "timestamp": stamp,
        "cwd": CWD,
    }


def init(stamp: str = "2026-09-01T10:00:01.000Z") -> dict[str, object]:
    block = "\n".join(
        [
            "<skills>",
            f"- {INSTALLED}: Fictional skill {INSTALLED}.",
            f"- {OTHER_INSTALLED}: Fictional skill {OTHER_INSTALLED}.",
            "</skills>",
        ]
    )
    return {
        "type": "session_init",
        "id": "init1",
        "parentId": None,
        "timestamp": stamp,
        "systemPrompt": ["Fictional preamble.", block],
    }


def read_call(
    call_id: str, path: object, stamp: str = "2026-09-01T10:01:00.000Z"
) -> dict[str, object]:
    return {
        "type": "message",
        "id": f"m-{call_id}",
        "parentId": "init1",
        "timestamp": stamp,
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "toolCall",
                    "id": call_id,
                    "name": "read",
                    "arguments": {"path": path},
                }
            ],
            "timestamp": ms(stamp),
        },
    }


def read_result(
    call_id: str, *, error: bool, stamp: str = "2026-09-01T10:01:02.000Z"
) -> dict[str, object]:
    return {
        "type": "message",
        "id": f"r-{call_id}",
        "parentId": f"m-{call_id}",
        "timestamp": stamp,
        "message": {
            "role": "toolResult",
            "toolCallId": call_id,
            "toolName": "read",
            "isError": error,
            "content": [{"type": "text", "text": "fictional output"}],
            "timestamp": ms(stamp),
        },
    }


def standard_session(env: Env) -> list[object]:
    return [
        header(),
        init(),
        read_call("c1", f"skill://{INSTALLED}/SKILL.md"),
        read_result("c1", error=False),
        read_call("c2", str(env.installed_file), "2026-09-01T10:02:00.000Z"),
        read_result("c2", error=True, stamp="2026-09-01T10:02:01.000Z"),
        read_call(
            "c3", f"skill://{OTHER_INSTALLED}/SKILL.md", "2026-09-01T10:03:00.000Z"
        ),
    ]


def report(proc: subprocess.CompletedProcess[str]) -> dict[str, object]:
    parsed = json.loads(proc.stdout)
    assert isinstance(parsed, dict)
    return parsed


def events(data: dict[str, object], scope: str) -> dict[str, object]:
    section = data["events"]
    assert isinstance(section, dict)
    selected = section[scope]
    assert isinstance(selected, dict)
    return selected


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


def test_counts_actual_reads_and_redacts_identities(env: Env) -> None:
    env.write_log("orchard/session-one.jsonl", standard_session(env))

    proc = env.measure()

    data = report(proc)
    assert proc.returncode == 0, proc.stdout
    assert data["status"] == "complete"
    for scope in ("all_observed", "within_window"):
        counts = events(data, scope)
        assert counts["read_attempts"] == 3
        assert counts["uri_read_attempts"] == 2
        assert counts["direct_read_attempts"] == 1
        assert counts["successful_reads"] == 1
        assert counts["failed_reads"] == 1
        assert counts["unresolved_results"] == 1
        assert counts["successful_body_loads"] == 1
        assert counts["native_invocations"] is None
        assert counts["slash_invocations"] == 0
    exposure = data["exposure"]
    assert isinstance(exposure, dict)
    assert exposure["observations"] == 1
    for private in (
        INSTALLED,
        OTHER_INSTALLED,
        SESSION_ID,
        CWD,
        str(env.root),
        "orchard",
    ):
        assert private not in proc.stdout
        assert private not in proc.stderr


def test_window_excludes_old_reads_from_window_counts_only(env: Env) -> None:
    env.write_log("orchard/session-one.jsonl", standard_session(env))

    # 20 days ending at the as-of date start after the September fixtures.
    data = report(env.measure(window_days=20))

    assert events(data, "all_observed")["read_attempts"] == 3
    assert events(data, "within_window")["read_attempts"] == 0


def test_unknown_session_version_is_incomplete_and_nonzero(env: Env) -> None:
    env.write_log("orchard/session-one.jsonl", [header(version=99), init()])

    proc = env.measure()

    assert proc.returncode == 2
    assert report(proc)["status"] == "incomplete"
    assert SESSION_ID not in proc.stdout + proc.stderr


@pytest.mark.parametrize(
    "bad_line",
    [
        "{this is not json and mentions marmot-reviewer",
        json.dumps(read_call("c9", 12345)),
        json.dumps({**read_call("c9", "skill://x"), "timestamp": "not-a-timestamp"}),
    ],
)
def test_malformed_relevant_record_is_incomplete_without_echo(
    env: Env, bad_line: str
) -> None:
    lines = [header(), init(), bad_line, read_call("c1", f"skill://{INSTALLED}")]
    env.write_log("orchard/session-one.jsonl", lines)

    proc = env.measure()

    assert proc.returncode == 2
    assert report(proc)["status"] == "incomplete"
    assert "not json" not in proc.stdout + proc.stderr
    assert OTHER_INSTALLED not in proc.stdout + proc.stderr


def test_snapshot_replay_is_byte_identical(env: Env) -> None:
    env.write_log("orchard/session-one.jsonl", standard_session(env))

    first = env.measure()
    second = env.measure()

    assert first.returncode == 0, first.stdout
    assert second.returncode == 0, second.stdout
    assert first.stdout == second.stdout
    assert env.snapshot.exists()
    assert env.snapshot.stat().st_mode & 0o077 == 0


def test_replay_never_reads_appended_bytes(env: Env) -> None:
    log = env.write_log("orchard/session-one.jsonl", standard_session(env))
    first = env.measure()

    with log.open("a") as handle:
        handle.write(json.dumps(read_call("c4", f"skill://{INSTALLED}")) + "\n")
    second = env.measure()

    assert first.returncode == 0, first.stdout
    assert events(report(first), "all_observed")["read_attempts"] == 3
    # The frozen prefix is replayed; the appended read is not counted.
    assert events(report(second), "all_observed")["read_attempts"] == 3


def test_replay_after_truncation_invalidates_snapshot(env: Env) -> None:
    log = env.write_log("orchard/session-one.jsonl", standard_session(env))
    assert env.measure().returncode == 0

    log.write_text(json.dumps(header()) + "\n")
    proc = env.measure()

    assert proc.returncode == 2
    assert report(proc)["status"] == "incomplete"


def test_help_does_not_open_default_log_roots(env: Env) -> None:
    sessions = env.home / ".omp" / "agent" / "sessions" / "proj"
    sessions.mkdir(parents=True)
    # Opening a FIFO for reading blocks forever; --help must never try.
    os.mkfifo(sessions / "trap.jsonl")

    proc = run(env, "--help")

    assert proc.returncode == 0
    assert not env.snapshot.exists()

    measure_help = run(env, "measure", "--help")
    assert measure_help.returncode == 0
    assert not env.snapshot.exists()


def test_bad_arguments_do_not_echo_private_paths(env: Env) -> None:
    secret = str(env.root / "private-fictional-marker")

    proc = run(env, "measure", "--harness", "omp", "--bogus-flag", secret)
    proc_value = run(
        env, "measure", "--harness", "omp", "--as-of", secret, "--snapshot", secret
    )

    for result in (proc, proc_value):
        assert result.returncode != 0
        assert "private-fictional-marker" not in result.stdout + result.stderr
