"""Human-operated procedure runner and non-executable dotenv consumer (stdlib)."""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import termios
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Literal, TypedDict, cast
from urllib.parse import urlsplit

KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
ASSIGNMENT = re.compile(rb"^[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*=")


class CommonStage(TypedDict):
    label: str
    instruction: str
    source: str
    required: bool


class EnvStage(CommonStage):
    kind: Literal["env"]
    key: str


class GitHubStage(CommonStage):
    key: str
    repo: str


class SecretStage(GitHubStage):
    kind: Literal["gh-secret"]


class VariableStage(GitHubStage):
    kind: Literal["gh-variable"]


class ManualStage(CommonStage):
    kind: Literal["manual"]


class OpenStage(CommonStage):
    kind: Literal["open"]
    url: str


class ActionStage(CommonStage):
    kind: Literal["action"]
    argv: list[str]


if TYPE_CHECKING:
    from typing import Self

    Stage = (
        EnvStage | SecretStage | VariableStage | ManualStage | OpenStage | ActionStage
    )


class Refused(Exception):
    """A deliberately value-free diagnostic."""


class Cancelled(Exception):
    pass


def valid_key(key: object) -> str:
    if not isinstance(key, str) or not KEY.fullmatch(key):
        raise Refused("invalid key")
    return key


def snapshot(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def destination(path: object) -> tuple[int, str]:
    """Return pinned parent fd/name; refuse symlinks and writable ancestry."""
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or any(c in path for c in "\x00\r\n")
    ):
        raise Refused("ENV_FILE must be an absolute canonical path")
    parts = path.split("/")[1:]
    if not parts or any(p in ("", ".", "..") for p in parts):
        raise Refused("invalid destination components")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            sticky_root = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
            if info.st_uid not in (0, os.geteuid()) or (
                info.st_mode & 0o022 and not sticky_root
            ):
                raise Refused("untrusted destination ancestry")
        parent = os.fstat(fd)
        if parent.st_uid != os.geteuid() or parent.st_mode & 0o022:
            raise Refused(
                "destination parent must be owned and not group/world writable"
            )
        return fd, parts[-1]
    except BaseException:
        os.close(fd)
        raise


def existing(fd: int, name: str) -> os.stat_result | None:
    try:
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
    ):
        raise Refused("destination must be an owned regular file with one link")
    return info


def read_existing(fd: int, name: str) -> tuple[bytes, os.stat_result | None]:
    info = existing(fd, name)
    if info is None:
        return b"", None
    file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(file_fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if snapshot(opened) != snapshot(info):
            raise Refused("destination changed while opening")
        data = stream.read()
        if snapshot(os.fstat(stream.fileno())) != snapshot(info):
            raise Refused("destination changed while reading")
    return data, info


def upsert_env(path: object, key: str, value: str) -> None:
    """Atomic mode-0600 JSON-string RHS; never interpret shell syntax."""
    valid_key(key)
    if "\x00" in value or "\n" in value or "\r" in value:
        raise Refused("only single-line values without NUL are supported")
    fd, name = destination(path)
    temp: str | None = None
    try:
        data, before = read_existing(fd, name)
        kept: list[bytes] = []
        for line in data.splitlines(keepends=True):
            match = ASSIGNMENT.match(line)
            if match is None or match.group(1).decode("ascii") != key:
                kept.append(line)
        body = b"".join(kept)
        if body and not body.endswith(b"\n"):
            body += b"\n"
        body += (key + "=" + json.dumps(value, ensure_ascii=True) + "\n").encode(
            "ascii"
        )
        candidate = ".walkthrough-" + secrets.token_hex(16)
        out_fd = os.open(
            candidate,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=fd,
        )
        temp = candidate
        with os.fdopen(out_fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        after = existing(fd, name)
        if (None if before is None else snapshot(before)) != (
            None if after is None else snapshot(after)
        ):
            raise Refused("destination changed before replacement")
        os.replace(temp, name, src_dir_fd=fd, dst_dir_fd=fd)
        temp = None
        os.fsync(fd)
    finally:
        try:
            if temp is not None:
                try:
                    os.unlink(temp, dir_fd=fd)
                except FileNotFoundError:
                    # Rename may have committed immediately before SIGINT.
                    pass
        finally:
            os.close(fd)


def load_values(path: object, keys: Iterable[str]) -> dict[str, str]:
    """Declared dotenv consumer: parse selected managed RHS with json.loads."""
    selected = {valid_key(key) for key in keys}
    fd, name = destination(path)
    try:
        data, info = read_existing(fd, name)
        if info is None:
            raise Refused("dotenv file is missing")
        result: dict[str, str] = {}
        for line in data.splitlines():
            match = ASSIGNMENT.match(line)
            if match is not None:
                key = match.group(1).decode("ascii")
                if key in selected:
                    value: object = json.loads(line[match.end() :].decode("utf-8"))
                    if not isinstance(value, str) or key in result:
                        raise Refused("invalid or duplicate managed dotenv value")
                    result[key] = value
        if selected != set(result):
            raise Refused("managed dotenv value is missing")
        return result
    finally:
        os.close(fd)


class Terminal:
    def __enter__(self) -> Self:
        self.fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
        if not os.isatty(self.fd):
            raise Refused("an actual controlling terminal is required")
        return self

    def __exit__(self, *args: object) -> None:
        os.close(self.fd)

    def read(self, prompt: str, hidden: bool = False) -> str:
        previous = termios.tcgetattr(self.fd)
        mode = termios.tcgetattr(self.fd)
        if hidden:
            # Preserve UTF-8 bytes; canonical buffers have small platform limits.
            mode[0] &= ~termios.ISTRIP
            mode[3] &= ~(termios.ICANON | termios.ECHO | termios.ECHONL)
            mode[3] |= termios.ISIG
            mode[6][termios.VMIN] = 1
            mode[6][termios.VTIME] = 0
        # Discard pre-typed input before switching echo off; input is prompted.
        termios.tcsetattr(self.fd, termios.TCSAFLUSH, mode)
        try:
            os.write(self.fd, prompt.encode("utf-8"))
            answer = bytearray()
            while True:
                chunk = os.read(self.fd, 1)
                if not chunk:
                    raise Cancelled("EOF")
                if hidden and chunk == b"\x04":
                    raise Cancelled("EOF")
                if hidden and chunk in (b"\x7f", b"\x08"):
                    # Delete one UTF-8 character, not just its final byte.
                    if answer:
                        last = answer.pop()
                        while last & 0xC0 == 0x80 and answer:
                            last = answer.pop()
                    continue
                if chunk == b"\n":
                    return answer.decode("utf-8")
                answer.extend(chunk)
        finally:
            termios.tcsetattr(self.fd, termios.TCSANOW, previous)
            if hidden:
                os.write(self.fd, b"\n")


def run_child(argv: Sequence[str], value: str | None = None) -> int:
    """No child diagnostics can echo captured data; cancel the process group."""
    child = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE if value is not None else subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        child.communicate(None if value is None else value.encode("utf-8"))
    except BaseException:
        try:
            os.killpg(child.pid, signal.SIGTERM)
            child.wait(timeout=2)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
        raise
    # communicate()/wait() above have reaped the child and set its exit status.
    return cast(int, child.returncode)


def read_plan(path: str) -> list[Stage]:
    with open(path, encoding="utf-8") as stream:
        plan: object = json.load(stream)
    if (
        not isinstance(plan, dict)
        or set(plan) != {"stages"}
        or not isinstance(plan["stages"], list)
        or not plan["stages"]
    ):
        raise Refused("plan must contain a nonempty stages list")
    kinds: dict[str, set[str]] = {
        "env": {"key"},
        "gh-secret": {"key", "repo"},
        "gh-variable": {"key", "repo"},
        "manual": set(),
        "open": {"url"},
        "action": {"argv"},
    }
    common = {"kind", "label", "instruction", "source", "required"}
    for stage in plan["stages"]:
        if not isinstance(stage, dict) or stage.get("kind") not in kinds:
            raise Refused("unknown stage kind")
        kind = stage["kind"]
        if set(stage) != common | kinds[kind] or not isinstance(
            stage["required"], bool
        ):
            raise Refused("invalid stage fields")
        for field in ("label", "instruction", "source"):
            text = stage[field]
            if (
                not isinstance(text, str)
                or not text
                or any(ord(c) < 32 or ord(c) == 127 for c in text)
            ):
                raise Refused("stage text must be nonempty single-line public text")
        if "key" in stage:
            valid_key(stage["key"])
        if "repo" in stage and (
            not isinstance(stage["repo"], str)
            or not REPO.fullmatch(stage["repo"])
            or any(p in (".", "..") for p in stage["repo"].split("/"))
        ):
            raise Refused("repository must be explicit owner/name")
        if kind == "open":
            url = stage["url"]
            if not isinstance(url, str) or any(
                ord(c) <= 32 or ord(c) == 127 for c in url
            ):
                raise Refused("invalid public URL")
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise Refused(
                    "use a public HTTPS URL without credentials, query or fragment"
                )
        if kind == "action":
            argv = stage["argv"]
            if (
                not isinstance(argv, list)
                or not argv
                or any(
                    not isinstance(a, str) or not a or any(ord(c) < 32 for c in a)
                    for a in argv
                )
            ):
                raise Refused("action requires a public argument vector")
            if os.path.basename(argv[0]) in {
                "sh",
                "bash",
                "zsh",
                "dash",
                "eval",
                "source",
            }:
                raise Refused("shell action interpreters are not supported")
    # Field validation above establishes the public stage schema.
    return cast("list[Stage]", plan["stages"])


def perform(
    stage: Stage, terminal: Terminal, env_file: str | None
) -> Literal["complete", "skipped"]:
    if (
        stage["kind"] == "env"
        or stage["kind"] == "gh-secret"
        or stage["kind"] == "gh-variable"
    ):
        write_argv: list[str] | None
        if stage["kind"] == "env":
            fd, name = destination(env_file)
            try:
                existing(fd, name)
            finally:
                os.close(fd)
            write_argv = None
        else:
            gh = shutil.which("gh")
            if gh is None:
                return "skipped"
            if (
                terminal.read(
                    "Type WRITE to authorize this GitHub write, otherwise cancel: "
                )
                != "WRITE"
            ):
                raise Cancelled("GitHub write declined")
            noun = "secret" if stage["kind"] == "gh-secret" else "variable"
            write_argv = [gh, noun, "set", stage["key"], "--repo", stage["repo"]]
        value = terminal.read("Enter value (hidden; empty cancels): ", hidden=True)
        if not value:
            raise Cancelled("empty value")
        if write_argv is None:
            upsert_env(env_file, stage["key"], value)
        elif run_child(write_argv, value) != 0:
            raise Refused("GitHub write failed; diagnostics suppressed")
        return "complete"
    if stage["kind"] == "manual":
        reply = terminal.read(
            "Type DONE after completion, SKIP to skip, otherwise cancel: "
        )
        if reply == "SKIP":
            return "skipped"
        if reply != "DONE":
            raise Cancelled("manual step not confirmed")
        return "complete"
    if stage["kind"] == "open":
        print("Public URL: " + stage["url"], flush=True)
        # BROWSER is one executable name/path, never a shell expression.
        override = os.environ.get("BROWSER")
        browser = (
            shutil.which(override)
            if override
            else next(
                (
                    p
                    for p in (shutil.which(n) for n in ("open", "xdg-open", "wslview"))
                    if p
                ),
                None,
            )
        )
        if not browser:
            return "skipped"
        if run_child([browser, stage["url"]]) != 0:
            raise Refused("browser launch failed")
        return "complete"
    print("Action argv: " + json.dumps(stage["argv"]), flush=True)
    if (
        terminal.read("Irreversible action: type APPLY to execute, otherwise cancel: ")
        != "APPLY"
    ):
        raise Cancelled("irreversible action declined")
    if run_child(stage["argv"]) != 0:
        raise Refused("action failed; inspect its state before retrying")
    return "complete"


def main(argv: Sequence[str]) -> int:
    states: list[Literal["complete", "skipped"]] = []
    required_gap = False
    try:
        if len(argv) != 2 or argv[0] != "run":
            raise Refused("usage: walkthrough.sh run PLAN.json")
        stages = read_plan(argv[1])
        env_file = os.environ.get("ENV_FILE")
        if any(stage["kind"] == "env" for stage in stages):
            fd, name = destination(env_file)
            try:
                existing(fd, name)
            finally:
                os.close(fd)
        with Terminal() as terminal:
            for index, stage in enumerate(stages, 1):
                print(
                    "Stage {}/{}: {}".format(index, len(stages), stage["label"]),
                    flush=True,
                )
                # Consent precedes potentially irreversible UI instructions.
                if stage["kind"] == "manual" and (
                    terminal.read(
                        "Type BEGIN to authorize this manual stage, otherwise cancel: "
                    )
                    != "BEGIN"
                ):
                    raise Cancelled("manual stage declined")
                print(
                    "{}\nSource: {}".format(stage["instruction"], stage["source"]),
                    flush=True,
                )
                status = perform(stage, terminal, env_file)
                states.append(status)
                print(f"STAGE {index} {status}", flush=True)
                if status == "skipped" and stage["required"]:
                    required_gap = True
                    break
        if required_gap:
            print(
                "STATE incomplete: a required stage was skipped; later stages were not run.",
                flush=True,
            )
            return 2
        print(
            "STATE complete: all required stages completed; optional skips={}.".format(
                states.count("skipped")
            ),
            flush=True,
        )
        return 0
    except (Cancelled, KeyboardInterrupt):
        print(
            "STATE incomplete: cancelled; no later stages run; earlier completed writes remain.",
            flush=True,
        )
        return 130
    except (Refused, OSError, ValueError, TypeError):
        # Exception text, filenames and subprocess output may contain secrets.
        print(
            "STATE failed: operation refused or failed; no later stages run; earlier writes may remain.",
            file=sys.stderr,
            flush=True,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
