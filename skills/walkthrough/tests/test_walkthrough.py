"""Offline subprocess/controlling-PTY acceptance tests. No real gh/browser calls."""

from __future__ import annotations

import errno
import fcntl
import importlib.util
import json
import os
import pty
import select
import signal
import stat
import subprocess
import sys
import termios
import time
from importlib.abc import Loader
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, NoReturn, Protocol, cast

import pytest

if TYPE_CHECKING:
    from typing import Self


class Helper(Protocol):
    os: ModuleType

    def load_values(self, path: object, keys: list[str]) -> dict[str, str]: ...

    def upsert_env(self, path: object, key: str, value: str) -> None: ...

    def main(self, argv: list[str]) -> int: ...


ROOT = Path(__file__).resolve().parents[1]
SHELL = ROOT / "templates" / "walkthrough.sh"
SPEC = cast(
    ModuleSpec,
    importlib.util.spec_from_file_location(
        "walkthrough_helper", ROOT / "templates" / "walkthrough.py"
    ),
)
MODULE = importlib.util.module_from_spec(SPEC)
cast(Loader, SPEC.loader).exec_module(MODULE)
HELPER = cast(Helper, MODULE)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path.resolve()
    root.chmod(0o700)
    return root


def stage(
    kind: str = "env", required: bool = True, **fields: object
) -> dict[str, object]:
    result: dict[str, object] = {
        "kind": kind,
        "label": "Disposable test stage",
        "instruction": "Test-only instruction",
        "source": "synthetic fixture, not a production key",
        "required": required,
    }
    if kind in ("env", "gh-secret", "gh-variable"):
        result["key"] = "TEST_TOKEN"
    if kind.startswith("gh-"):
        result["repo"] = "fixture/disposable"
    result.update(fields)
    return result


def stub(root: Path, name: str, code: str) -> Path:
    target = root / name
    target.write_text("#!" + sys.executable + "\n" + code)
    target.chmod(0o700)
    return target


class Session:
    def __init__(
        self, root: Path, stages: list[dict[str, object]], **environment: str
    ) -> None:
        plan = root / "plan.json"
        plan.write_text(json.dumps({"stages": stages}))
        self.master, slave = pty.openpty()
        self.pid = os.fork()
        if self.pid == 0:
            try:
                os.close(self.master)
                os.setsid()
                fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
                for fd in (0, 1, 2):
                    os.dup2(slave, fd)
                if slave > 2:
                    os.close(slave)
                env = dict(os.environ, ENV_FILE=str(root / ".env"))
                env.update(environment)
                os.execve("/bin/bash", ["bash", str(SHELL), "run", str(plan)], env)
            finally:
                os._exit(127)
        os.close(slave)
        self.output = b""
        self.reaped = False

    def until(self, marker: str) -> None:
        marker_bytes = marker.encode()
        deadline = time.monotonic() + 8
        start = len(self.output)
        while marker_bytes not in self.output[start:]:
            if time.monotonic() > deadline:
                raise AssertionError("PTY prompt timeout: " + repr(self.output))
            if select.select([self.master], [], [], 0.1)[0]:
                try:
                    data = os.read(self.master, 65536)
                except OSError as error:
                    if error.errno == errno.EIO:
                        raise AssertionError(
                            "process exited before prompt: " + repr(self.output)
                        ) from error
                    raise
                if not data:
                    raise AssertionError("PTY closed before prompt")
                self.output += data

    def send(self, data: str | bytes) -> None:
        pending = memoryview(data.encode() if isinstance(data, str) else data)
        while pending:
            pending = pending[os.write(self.master, pending) :]

    def finish(self) -> int:
        deadline = time.monotonic() + 8
        while True:
            if select.select([self.master], [], [], 0.1)[0]:
                try:
                    chunk = os.read(self.master, 65536)
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                    chunk = b""
                self.output += chunk
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                self.reaped = True
                # Drain bytes already written before child exit.
                while select.select([self.master], [], [], 0)[0]:
                    try:
                        chunk = os.read(self.master, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    self.output += chunk
                return os.waitstatus_to_exitcode(status)
            if time.monotonic() > deadline:
                raise AssertionError("helper did not terminate")

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        if not self.reaped:
            os.kill(self.pid, signal.SIGKILL)
            os.waitpid(self.pid, 0)
        os.close(self.master)


@pytest.mark.parametrize("failure_point", ["setsid", "ioctl", "dup2", "execve"])
def test_child_setup_failure_exits_without_unwinding(
    workspace: Path, failure_point: str
) -> None:
    probe = """
import importlib.util
import os
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("walkthrough_tests", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
root = Path(sys.argv[2])
marker = root / "escaped-child"
def fail(*args, **kwargs):
    raise OSError("injected child setup failure")
owner = module.fcntl if sys.argv[3] == "ioctl" else module.os
setattr(owner, sys.argv[3], fail)
try:
    session = module.Session(root, [module.stage()])
except OSError:
    marker.write_text("child unwound into caller")
    os._exit(42)
with session:
    status = session.finish()
assert status == 127 and not marker.exists(), (status, marker.exists())
"""
    result = subprocess.run(
        [sys.executable, "-c", probe, __file__, str(workspace), failure_point],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_secret_roundtrip_modes_and_upsert(workspace: Path) -> None:
    env = workspace / ".env"
    untouched = b"# untouched\nOTHER='leave $this alone'\n"
    env.write_bytes(untouched + b"TEST_TOKEN=old\nexport TEST_TOKEN=duplicate\n")
    env.chmod(0o644)
    values = [
        "quote' double\" dollar$ backtick` slash\\ hash# equals= spaces \t café",
        "replacement $(not-a-command)",
    ]
    for value in values:
        with Session(workspace, [stage()]) as session:
            session.until("Enter value (hidden; empty cancels): ")
            assert not termios.tcgetattr(session.master)[3] & termios.ECHO
            session.send(value + "\n")
            assert session.finish() == 0
            assert value.encode() not in session.output
            assert b"STATE complete" in session.output
        assert HELPER.load_values(str(env), ["TEST_TOKEN"]) == {"TEST_TOKEN": value}
        assert env.read_bytes().startswith(untouched)
        assert env.read_bytes().count(b"TEST_TOKEN=") == 1
        assert stat.S_IMODE(env.stat().st_mode) == 0o600
        assert not list(workspace.glob(".walkthrough-*"))


def test_long_hidden_utf8_input_and_backspace_roundtrip(workspace: Path) -> None:
    value = "long-secret-" + "é漢🙂abc" * 2048 + "-exact-end"
    with Session(workspace, [stage()]) as session:
        session.until("Enter value (hidden; empty cancels): ")
        mode = termios.tcgetattr(session.master)
        assert not mode[3] & (termios.ICANON | termios.ECHO | termios.ECHONL)
        assert mode[3] & termios.ISIG
        session.send(value + "é🙂")
        session.send(b"\x7f\x08\n")
        assert session.finish() == 0
        assert b"long-secret-" not in session.output
        assert "é漢🙂abc".encode() not in session.output
        assert b"-exact-end" not in session.output
        assert termios.tcgetattr(session.master)[3] & termios.ICANON
    assert HELPER.load_values(str(workspace / ".env"), ["TEST_TOKEN"]) == {
        "TEST_TOKEN": value
    }


@pytest.mark.parametrize("ending", [b"\x04", b"\x03"])
def test_partial_hidden_input_cancellation_restores_terminal(
    workspace: Path, ending: bytes
) -> None:
    with Session(workspace, [stage(), stage("manual")]) as session:
        session.until("Enter value (hidden; empty cancels): ")
        session.send(b"partial-secret" + ending)
        assert session.finish() == 130
        assert b"partial-secret" not in session.output
        assert b"Type BEGIN" not in session.output
        mode = termios.tcgetattr(session.master)
        assert mode[3] & termios.ICANON
        assert mode[3] & termios.ECHO
    assert not (workspace / ".env").exists()


@pytest.mark.parametrize("bad", ["BAD-KEY", "X\nINJECT", "X=Y", "", "1KEY"])
def test_invalid_keys_refused_before_capture(workspace: Path, bad: str) -> None:
    with Session(workspace, [stage(key=bad)]) as session:
        assert session.finish() == 1
        assert b"Enter value" not in session.output
    assert not (workspace / ".env").exists()


@pytest.mark.parametrize("kind", ["symlink", "directory", "fifo", "hardlink"])
def test_untrusted_destination_types(workspace: Path, kind: str) -> None:
    env = workspace / ".env"
    original = workspace / "original"
    original.write_text("unchanged")
    if kind == "symlink":
        env.symlink_to(original)
    elif kind == "directory":
        env.mkdir()
    elif kind == "fifo":
        os.mkfifo(env)
    else:
        os.link(original, env)
    with Session(workspace, [stage()]) as session:
        assert session.finish() == 1
    assert original.read_text() == "unchanged"
    assert not list(workspace.glob(".walkthrough-*"))


def test_writable_parent_and_symlink_ancestor_refused(workspace: Path) -> None:
    directory = workspace / "unsafe"
    directory.mkdir(mode=0o700)
    directory.chmod(0o777)
    with Session(workspace, [stage()], ENV_FILE=str(directory / ".env")) as session:
        assert session.finish() == 1
    directory.chmod(0o700)
    link = workspace / "link"
    link.symlink_to(directory, target_is_directory=True)
    with Session(workspace, [stage()], ENV_FILE=str(link / ".env")) as session:
        assert session.finish() == 1
    assert not (directory / ".env").exists()


@pytest.mark.parametrize("cancel", ["eof", "interrupt", "empty"])
def test_capture_cancellation_stops_later_actions(workspace: Path, cancel: str) -> None:
    marker = workspace / "ran"
    command = stub(
        workspace,
        "action",
        "from pathlib import Path\nPath(" + repr(str(marker)) + ").touch()\n",
    )
    with Session(workspace, [stage(), stage("action", argv=[str(command)])]) as session:
        session.until("Enter value (hidden; empty cancels): ")
        if cancel == "interrupt":
            os.kill(session.pid, signal.SIGINT)
        else:
            session.send(b"\x04" if cancel == "eof" else b"\n")
        assert session.finish() == 130
        assert b"STATE incomplete" in session.output
    assert not (workspace / ".env").exists()
    assert not marker.exists()


def test_irreversible_rejection_has_no_side_effect(workspace: Path) -> None:
    marker = workspace / "ran"
    command = stub(
        workspace,
        "action",
        "from pathlib import Path\nPath(" + repr(str(marker)) + ").touch()\n",
    )
    with Session(workspace, [stage("action", argv=[str(command)])]) as session:
        session.until("type APPLY to execute, otherwise cancel: ")
        session.send("no\n")
        assert session.finish() == 130
    assert not marker.exists()


@pytest.mark.parametrize("kind", ["gh-secret", "gh-variable"])
def test_github_failure_is_not_success_or_secret_log(
    workspace: Path, kind: str
) -> None:
    binary = workspace / "bin"
    binary.mkdir(mode=0o700)
    stub(
        binary,
        "gh",
        "import sys\nv=sys.stdin.read()\nprint(v)\nprint(v, file=sys.stderr)\nsys.exit(1)\n",
    )
    with Session(
        workspace, [stage(kind)], PATH=str(binary) + ":" + os.environ["PATH"]
    ) as session:
        session.until("Type WRITE")
        session.send("WRITE\n")
        session.until("Enter value (hidden; empty cancels): ")
        session.send("never-log-this-secret\n")
        assert session.finish() == 1
        assert b"never-log-this-secret" not in session.output
        assert b"STATE failed" in session.output
        assert b"STATE complete" not in session.output


def test_required_missing_github_is_incomplete(workspace: Path) -> None:
    binary = workspace / "bin"
    binary.mkdir(mode=0o700)
    (binary / "python3").symlink_to(sys.executable)
    # The launcher requires dirname; no gh is present in this isolated PATH.
    stub(binary, "dirname", "import os,sys\nprint(os.path.dirname(sys.argv[-1]))\n")
    with Session(workspace, [stage("gh-secret")], PATH=str(binary)) as session:
        assert session.finish() == 2
        assert b"STAGE 1 skipped" in session.output
        assert b"STATE incomplete" in session.output


def test_atomic_write_failure_preserves_original(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = workspace / ".env"
    env.write_bytes(b"OTHER=unchanged\n")

    def fail(src: str, dst: str, *, src_dir_fd: int, dst_dir_fd: int) -> NoReturn:
        info = os.stat(src, dir_fd=src_dir_fd, follow_symlinks=False)
        assert stat.S_IMODE(info.st_mode) == 0o600
        assert info.st_nlink == 1
        raise OSError("simulated rename failure")

    monkeypatch.setattr(HELPER.os, "replace", fail)
    with pytest.raises(OSError):
        HELPER.upsert_env(str(env), "TEST_TOKEN", "hidden")
    assert env.read_bytes() == b"OTHER=unchanged\n"
    assert not list(workspace.glob(".walkthrough-*"))


def test_browser_is_stubbed_and_no_shell_expression(workspace: Path) -> None:
    marker = workspace / "url"
    browser = stub(
        workspace,
        "browser",
        "import sys\nfrom pathlib import Path\nPath("
        + repr(str(marker))
        + ").write_text(sys.argv[1])\n",
    )
    with Session(
        workspace,
        [stage("open", url="https://example.invalid/setup")],
        BROWSER=str(browser),
    ) as session:
        assert session.finish() == 0
        assert b"Public URL: https://example.invalid/setup" in session.output
    assert marker.read_text() == "https://example.invalid/setup"


@pytest.mark.parametrize("available", [False, True])
def test_browser_missing_or_failed_keeps_public_url(
    workspace: Path, available: bool
) -> None:
    browser = workspace / "missing-browser"
    marker = workspace / "browser-attempted"
    if available:
        browser = stub(
            workspace,
            "failing-browser",
            "import sys\nfrom pathlib import Path\nPath("
            + repr(str(marker))
            + ").write_text(sys.argv[1])\nsys.exit(1)\n",
        )
    url = "https://example.invalid/setup"
    with Session(
        workspace, [stage("open", url=url), stage()], BROWSER=str(browser)
    ) as session:
        assert session.finish() == (1 if available else 2)
        assert ("Public URL: " + url).encode() in session.output
        assert b"STATE complete" not in session.output
        assert b"Enter value" not in session.output
    assert marker.exists() == available
    if available:
        assert marker.read_text() == url


def test_manual_authorization_then_skip(workspace: Path) -> None:
    with Session(workspace, [stage("manual", required=False)]) as session:
        session.until("Type BEGIN")
        assert b"Test-only instruction" not in session.output
        session.send("BEGIN\n")
        session.until("Type DONE")
        session.send("SKIP\n")
        assert session.finish() == 0
        assert b"STAGE 1 skipped" in session.output
        assert b"optional skips=1" in session.output


@pytest.mark.parametrize("kind", ["gh-secret", "gh-variable"])
def test_github_success_uses_stdin_and_exact_names(workspace: Path, kind: str) -> None:
    binary = workspace / "bin"
    binary.mkdir(mode=0o700)
    received = workspace / "received"
    argv_file = workspace / "argv"
    stub(
        binary,
        "gh",
        "import os,sys,json\n"
        "fd=os.open("
        + repr(str(received))
        + ",os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)\n"
        "with os.fdopen(fd,'w') as f: f.write(sys.stdin.read())\n"
        "with open(" + repr(str(argv_file)) + ",'w') as f: json.dump(sys.argv[1:],f)\n",
    )
    with Session(
        workspace, [stage(kind)], PATH=str(binary) + ":" + os.environ["PATH"]
    ) as session:
        session.until("Type WRITE")
        session.send("WRITE\n")
        session.until("Enter value (hidden; empty cancels): ")
        value = "sensitive '$`\"\\ #= value"
        session.send(value + "\n")
        assert session.finish() == 0
        assert value.encode() not in session.output
    assert received.read_text() == value
    assert stat.S_IMODE(received.stat().st_mode) == 0o600
    noun = "secret" if kind == "gh-secret" else "variable"
    assert json.loads(argv_file.read_text()) == [
        noun,
        "set",
        "TEST_TOKEN",
        "--repo",
        "fixture/disposable",
    ]


@pytest.mark.parametrize("reply", ["no\n", "\x04"])
def test_github_rejection_or_eof_does_not_invoke_binary(
    workspace: Path, reply: str
) -> None:
    binary = workspace / "bin"
    binary.mkdir(mode=0o700)
    marker = workspace / "ran"
    stub(
        binary,
        "gh",
        "from pathlib import Path\nPath(" + repr(str(marker)) + ").touch()\n",
    )
    with Session(
        workspace, [stage("gh-secret")], PATH=str(binary) + ":" + os.environ["PATH"]
    ) as session:
        session.until("Type WRITE")
        session.send(reply)
        assert session.finish() == 130
    assert not marker.exists()


def test_required_manual_skip_blocks_next_stage(workspace: Path) -> None:
    with Session(workspace, [stage("manual"), stage()]) as session:
        session.until("Type BEGIN")
        session.send("BEGIN\n")
        session.until("Type DONE")
        session.send("SKIP\n")
        assert session.finish() == 2
        assert b"Enter value" not in session.output
    assert not (workspace / ".env").exists()


def test_manual_rejection_hides_irreversible_instructions(workspace: Path) -> None:
    with Session(workspace, [stage("manual")]) as session:
        session.until("Type BEGIN")
        session.send("no\n")
        assert session.finish() == 130
        assert b"Test-only instruction" not in session.output


def test_local_write_failure_is_failed_exit(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = workspace / "plan.json"
    plan.write_text(json.dumps({"stages": [stage()]}))

    class FakeTerminal:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def read(self, prompt: str, hidden: bool = False) -> str:
            return "never-log-this"

    def fail(path: object, key: str, value: str) -> NoReturn:
        raise OSError("never-log-this")

    monkeypatch.setenv("ENV_FILE", str(workspace / ".env"))
    monkeypatch.setattr(HELPER, "Terminal", FakeTerminal)
    monkeypatch.setattr(HELPER, "upsert_env", fail)
    assert HELPER.main(["run", str(plan)]) == 1
    captured = capsys.readouterr()
    assert "STATE failed" in captured.err
    assert "never-log-this" not in captured.out + captured.err
    assert "STATE complete" not in captured.out


def test_no_controlling_terminal_refuses_capture(workspace: Path) -> None:
    plan = workspace / "plan.json"
    plan.write_text(json.dumps({"stages": [stage()]}))
    result = subprocess.run(
        ["/bin/bash", str(SHELL), "run", str(plan)],
        env=dict(os.environ, ENV_FILE=str(workspace / ".env")),
        input=b"never-read-from-pipe\n",
        capture_output=True,
        start_new_session=True,
        check=False,
    )
    assert result.returncode == 1
    assert b"never-read-from-pipe" not in result.stdout + result.stderr
    assert not (workspace / ".env").exists()
