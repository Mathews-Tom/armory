#!/usr/bin/env python3
"""Finite, opt-in Claude 2.1.309 Delivery Radar actual-host qualification.

Uses the default HOME/authentication and explicitly reviewed additive settings.
Only completion-discovered native commands are submitted. Never answers trust,
login or policy prompts. Raw terminal/process captures stay in a private companion;
this is not a model/network-call meter or a CI prerequisite.
"""

from __future__ import annotations

import argparse
import codecs
import fcntl
import hashlib
import importlib.util
import json
import os
import pty
import re
import select
import selectors
import shlex
import shutil
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import termios
import time
from collections.abc import Callable
from pathlib import Path
from types import FrameType, ModuleType
from typing import Any, cast

pyte: ModuleType | None
try:
    import pyte
except ImportError:
    pyte = None

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.build_extensions import (
    CONTENT_MANIFEST,
    BuildError,
    ToolUnavailableError,
    assemble_feature,
    build_feature,
    load_metadata,
    verify_artifact_dir,
)

_spec = importlib.util.spec_from_file_location(
    "_armory_delivery_omp_smoke", Path(__file__).with_name("omp-smoke.py")
)
assert _spec is not None and _spec.loader is not None
shared = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = shared
_spec.loader.exec_module(shared)
Failure, Unavailable = shared.Failure, shared.Unavailable
require, private_write, compact = shared.require, shared.private_write, shared.compact
SCENARIOS = shared.SCENARIOS
ASSERTIONS = {
    **shared.ASSERTIONS,
    "changed-during-run": "native session disposal overtakes observed in-flight reads, suppresses the stale view, and resets the fresh session",
    "cancellation": "native interrupt terminates the observed actual helper and detached gh group while the same host remains usable",
}

type JsonObject = dict[str, Any]
STEP = 75
LIMIT = 900
MAX_CAPTURE = 8 * 1024 * 1024
MAX_HEADLESS = 2 * 1024 * 1024
COMMAND = "/armory-delivery"
DESCRIPTION = "Read selected PR delivery evidence without remote actions"
REPOSITORY = "Mathews-Tom/armory"
MISSING_PR = 2147483647
DIMENSIONS = ("implementation", "verification", "review", "merge", "publication")
ANSI = re.compile(r"\x1b(?:\][^\x07]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~]|[@-_])")
LITERAL = re.compile(
    r"/armory-delivery (?:help|refresh [A-Za-z0-9_.\-/]+ [0-9,]+(?: --json)?)\Z"
)
STOP_MARKERS = (
    "do you trust the files",
    "trust this folder",
    "please log in",
    "select login method",
    "sign in to continue",
    "permission required",
    "do you want to proceed",
    "requires approval",
    "permission denied",
)


def screen_text(raw: bytes) -> str:
    return cast(str, compact(ANSI.sub("", raw.decode("utf-8", "replace"))))


class NativeTTY:
    def __init__(self, argv: list[str], cwd: Path, env: dict[str, str]) -> None:
        self.argv, self.cwd, self.env = argv, cwd, env
        self.master = -1
        self.process: subprocess.Popen[bytes] | None = None
        self.raw = bytearray()
        self.answers: list[JsonObject] = []
        self.ready = False
        self.interaction_required = False
        self.closed = False
        if pyte is None:
            raise Unavailable("pyte-terminal-emulator-required")
        self.screen = pyte.HistoryScreen(240, 60, history=5000)
        self.terminal = pyte.Stream(self.screen)
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.pending: str | None = None
        self.discovered: set[str] = set()

    def rendered(self) -> bytes:
        history = [
            "".join(
                line.get(column, self.screen.default_char).data
                for column in range(self.screen.columns)
            )
            for line in self.screen.history.top
        ]
        return "\n".join([*history, *self.screen.display]).encode()

    def receive(self, chunk: bytes) -> None:
        self.raw.extend(chunk)
        require(len(self.raw) <= MAX_CAPTURE, "native-terminal-capture-limit")
        self.terminal.feed(self.decoder.decode(chunk))

    def guard(self) -> None:
        plain = ANSI.sub("", self.rendered().decode("utf-8", "replace")).lower()
        if any(marker in plain for marker in STOP_MARKERS):
            self.interaction_required = True
            raise Unavailable("native-trust-login-or-policy-interaction-required")

    def pump(self, timeout: float = 0.05) -> None:
        if self.master == -1:
            return
        if select.select([self.master], [], [], max(0, timeout))[0]:
            try:
                chunk = os.read(self.master, 65536)
            except OSError:
                return
            if chunk:
                self.receive(chunk)
        self.guard()

    def drain(self) -> None:
        deadline = time.monotonic() + 3
        while self.master != -1 and select.select([self.master], [], [], 0.1)[0]:
            if time.monotonic() >= deadline:
                raise Unavailable("native-terminal-drain-deadline")
            before = len(self.raw)
            self.pump(0)
            if before == len(self.raw):
                break

    def read(self, predicate: Callable[[bytes], bool], start: int = 0) -> bytes:
        deadline = time.monotonic() + STEP
        while time.monotonic() < deadline:
            self.guard()
            value = self.rendered()
            if len(self.raw) > start and predicate(value):
                return value
            if self.process is None or self.process.poll() is not None:
                self.drain()
                self.guard()
                value = self.rendered()
                if len(self.raw) > start and predicate(value):
                    return value
                raise Unavailable("native-process-exited-before-response")
            self.pump(min(0.2, max(0, deadline - time.monotonic())))
        raise Unavailable("native-command-response-deadline")

    def discover(self, command: str, description: str) -> None:
        self.drain()
        mark = len(self.raw)
        os.write(self.master, command.encode())
        self.read(lambda raw: compact(description) in screen_text(raw), mark)
        # Clear only our own unsubmitted typeahead. No trust/permission answer.
        os.write(self.master, b"\x15")
        self.drain()
        self.discovered.add(command)

    def start(self) -> None:
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 60, 240, 0, 0))

        try:
            self.process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    (
                        "import fcntl, os, sys, termios; "
                        "fcntl.ioctl(0, termios.TIOCSCTTY, 0); "
                        "os.execvpe(sys.argv[1], sys.argv[1:], os.environ)"
                    ),
                    *self.argv,
                ],
                cwd=self.cwd,
                env=self.env,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                start_new_session=True,
            )
        finally:
            os.close(slave)
        self.read(lambda raw: "❯" in raw.decode("utf-8", "replace"))
        self.discover(COMMAND, DESCRIPTION)
        self.discover("/exit", "Exit")
        self.ready = True

    def begin(self, text: str) -> int:
        require(
            self.pending is None
            and LITERAL.fullmatch(text) is not None
            and COMMAND in self.discovered,
            "non-native-command-refused",
        )
        self.drain()
        mark = len(self.raw)
        os.write(self.master, text.encode())
        self.read(
            lambda raw: screen_text(raw).rsplit("❯", 1)[-1].startswith(compact(text)),
            mark,
        )
        self.drain()
        mark = len(self.raw)
        self.pending = text
        os.write(self.master, b"\r")
        return mark

    def answer_text(self, rendered: bytes) -> str | None:
        if self.pending is None:
            return None
        # Select this command's complete native box, never ambient notices or a
        # retained prompt while the terminal is repainting. JSON string spaces
        # are escaped by the adapter; other source characters stay unchanged.
        visual = "".join(
            line.strip().removeprefix("│").removesuffix("│").strip()
            for line in rendered.decode("utf-8", "replace").splitlines()
        )
        flat = compact(visual)
        echo = f"❯{compact(self.pending)}"
        position = flat.rfind(echo)
        if position < 0:
            return None
        offset = position + len(echo)
        tail = flat[offset:]
        # A longer historical command may share the entire pending prefix.
        # Its argument suffix is not this command's answer boundary.
        if not tail.startswith("┌"):
            return None
        match = re.search(r"┌─+┐(.*?)└─+┘", tail)
        if match is None or "❯" not in tail[match.end() :]:
            return None
        if "┌" in tail[match.end() : tail.index("❯", match.end())]:
            raise Failure("native-multiple-answer-frames")
        positions = [index for index, char in enumerate(visual) if not char.isspace()]
        first, last = offset + match.start(1), offset + match.end(1)
        if first == last:
            return None
        candidate = visual[positions[first] : positions[last - 1] + 1].strip()
        # The pinned host stamps plugin command text with its owning package.
        if not candidate.startswith("delivery-radar:"):
            return None
        candidate = candidate.removeprefix("delivery-radar:").lstrip()
        if candidate.startswith("{"):
            try:
                _, json_end = json.JSONDecoder().raw_decode(candidate)
            except ValueError:
                return None
            if candidate[json_end:].strip():
                raise Failure("native-multiple-answer-frames")
            return candidate
        return cast(str, compact(candidate))

    def prompt_after_pending(self, rendered: bytes) -> bool:
        if self.pending is None:
            return False
        flat = screen_text(rendered)
        echo = f"❯{compact(self.pending)}"
        position = flat.rfind(echo)
        return position >= 0 and "❯" in flat[position + len(echo) :]

    def finish(self, mark: int) -> str:
        value = self.read(lambda raw: self.answer_text(raw) is not None, mark)
        answer = self.answer_text(value)
        require(answer is not None, "native-answer-framing-lost")
        assert answer is not None
        self.answers.append({"command": self.pending, "text": answer})
        self.pending = None
        return answer

    def command(self, text: str) -> str:
        return self.finish(self.begin(text))

    def interrupt(self) -> None:
        require(self.pending is not None, "native-interrupt-without-active-command")
        os.write(self.master, b"\x03")

    def dispose_active(self) -> None:
        require(
            self.pending is not None and "/exit" in self.discovered,
            "native-session-disposal-not-discovered",
        )
        # A native /exit must actually overtake the active refresh. If this UI
        # queues it until after publication, the suppression assertion fails.
        os.write(self.master, b"/exit\r")

    def stop(self, forced: bool = False) -> None:
        if self.closed:
            return
        try:
            if (
                self.process is not None
                and self.process.poll() is None
                and self.ready
                and not self.interaction_required
                and self.master != -1
                and self.pending is None
                and not forced
            ):
                os.write(self.master, b"/exit\r")
                deadline = time.monotonic() + 5
                while self.process.poll() is None and time.monotonic() < deadline:
                    self.pump(0.1)
        finally:
            if self.master != -1:
                os.close(self.master)
                self.master = -1
            if self.process is not None:
                shared.stop_process(
                    self.process,
                    graceful=not forced
                    and self.ready
                    and not self.interaction_required,
                )
            self.closed = True
        if self.process is not None:
            require(
                not shared.group_exists(self.process.pid),
                "native-process-group-survived",
            )


def context(args: argparse.Namespace) -> tuple[Path, Path]:
    if not args.trusted_cwd or not args.settings:
        raise Unavailable("reviewed-native-settings-and-trusted-cwd-required")
    cwd, settings = Path(args.trusted_cwd), Path(args.settings)
    if not cwd.is_absolute() or not settings.is_absolute():
        raise Unavailable("native-context-paths-must-be-absolute")
    if not cwd.is_dir() or settings.is_symlink() or not settings.is_file():
        raise Unavailable("reviewed-native-context-unavailable")
    if stat.S_IMODE(settings.stat().st_mode) & 0o077:
        raise Unavailable("native-settings-must-be-private")
    value = json.loads(settings.read_text())
    # Exact reviewed additive controls: genuine user/managed hooks, enforcement,
    # settings sources, HOME and existing authentication remain inherited.
    fixed: JsonObject = {
        "autoMemoryEnabled": False,
        "autoDreamEnabled": False,
        "idleCompaction": False,
        "promptSuggestionEnabled": False,
        "enabledPlugins": {
            "shopify-ai-toolkit@claude-plugins-official": False,
            "context7@claude-plugins-official": False,
        },
        "deniedMcpServers": [{"serverName": "tessera"}, {"serverName": "Context7"}],
        "statusLine": {
            "type": "command",
            "command": "printf 'armory native interface validation\\n'",
        },
    }
    if (
        not isinstance(value, dict)
        or set(value) != {*fixed, "env"}
        or any(value.get(key) != expected for key, expected in fixed.items())
    ):
        raise Unavailable("native-profile-must-match-reviewed-optional-controls")
    fixed_env = {
        "HOOKLINE_MEMORY": "0",
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        "CLAUDE_CODE_DISABLE_TERMINAL_TITLE": "1",
        "CLAUDE_CODE_ENABLE_PROMPT_SUGGESTION": "false",
        "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
        "CLAUDE_CODE_DISABLE_CRON": "1",
        "LAVISH_AXI_TELEMETRY": "0",
        "OPT_OUT_INSTRUMENTATION": "true",
    }
    auxiliary = {
        "LAVISH_AXI_STATE_DIR",
        "LACONIC_OBSERVE_AUDIT_PATH",
        "CHROME_DEVTOOLS_AXI_SESSION",
    }
    environment = value.get("env")
    if (
        not isinstance(environment, dict)
        or set(environment) != set(fixed_env) | auxiliary
        or any(environment.get(key) != expected for key, expected in fixed_env.items())
        or not all(isinstance(environment[key], str) for key in auxiliary)
    ):
        raise Unavailable("native-profile-must-preserve-authentication-and-enforcement")
    for key in ("LAVISH_AXI_STATE_DIR", "LACONIC_OBSERVE_AUDIT_PATH"):
        path = Path(environment[key])
        if (
            not path.is_absolute()
            or path.is_symlink()
            or not path.parent.is_dir()
            or stat.S_IMODE(path.parent.stat().st_mode) & 0o077
        ):
            raise Unavailable("native-auxiliary-writer-path-must-be-task-private")
    if not re.fullmatch(
        r"armory-native-[a-zA-Z0-9_-]{1,96}", environment["CHROME_DEVTOOLS_AXI_SESSION"]
    ):
        raise Unavailable("native-browser-session-label-must-be-synthetic")
    return cwd, settings


def prepare_artifact(args: argparse.Namespace, report: JsonObject, root: Path) -> Path:
    feature = Path(args.feature_dir).resolve(strict=True)
    metadata = load_metadata(feature)
    artifact = (
        Path(args.artifact).resolve(strict=True)
        if args.artifact
        else build_feature(feature, root / "build")["claude"]
    )
    manifest = verify_artifact_dir(artifact)
    require(
        metadata.name == "delivery-radar"
        and metadata.host_entries.get("claude") == "claude-code/register.ts"
        and metadata.storage == "none"
        and manifest.get("storage") == "none"
        and manifest.get("feature") == metadata.name
        and manifest.get("host") == "claude"
        and manifest.get("version") == metadata.version
        and manifest.get("runtime") == metadata.runtime
        and manifest.get("extension_schema_version") == metadata.schema_version
        and manifest.get("entrypoints")
        == {
            "hooks": "hooks/hooks.json",
            "module": "hooks/register.ts",
            "plugin_manifest": ".claude-plugin/plugin.json",
        },
        "native-artifact-identity-mismatch",
    )
    # Reassemble independently from the selected canonical definition and all
    # executable sources. A valid manifest belonging to a stale build is not a
    # source binding. This never modifies the supplied production artifact.
    _, artifacts = assemble_feature(feature)
    expected = artifacts["claude"]
    actual = {
        record["path"]: (artifact / record["path"]).read_bytes()
        for record in manifest["files"]
    }
    actual[CONTENT_MANIFEST] = (artifact / CONTENT_MANIFEST).read_bytes()
    require(actual == expected, "native-artifact-source-binding-mismatch")
    runtime = root / "native-artifact"
    shutil.copytree(artifact, runtime)
    verify_artifact_dir(runtime)
    digest = hashlib.sha256((artifact / CONTENT_MANIFEST).read_bytes()).hexdigest()
    report["artifact"] = {
        "mode": "supplied-production" if args.artifact else "built-production",
        "feature": metadata.name,
        "host": "claude",
        "sourceDefinitionSha256": hashlib.sha256(
            (feature / "EXTENSION.md").read_bytes()
        ).hexdigest(),
        "contentManifestSha256": digest,
        "allArtifactBytesMatchSelectedSourceAssembly": True,
    }
    report["artifactManifestSha256"] = digest
    report["developmentLoaderUsesDisposableCopy"] = True
    return runtime


def process_table(cwd: Path) -> dict[int, JsonObject]:
    raw = shared.finite(
        ["ps", "-axo", "pid=,ppid=,pgid=,command="],
        cwd,
        "native-process-listing-unavailable",
        timeout=5,
    )
    require(len(raw) <= MAX_CAPTURE, "native-process-listing-limit")
    result = {}
    for line in raw.decode("utf-8", "replace").splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) == 4 and all(item.isdecimal() for item in parts[:3]):
            pid, parent, group = map(int, parts[:3])
            result[pid] = {
                "pid": pid,
                "ppid": parent,
                "pgid": group,
                "command": parts[3],
            }
    return result


def below(pid: int, ancestor: int, table: dict[int, JsonObject]) -> bool:
    seen = set()
    while pid in table and pid not in seen:
        if pid == ancestor:
            return True
        seen.add(pid)
        pid = table[pid]["ppid"]
    return False


def owned_work(
    host: NativeTTY | subprocess.Popen[bytes], runtime: Path, require_both: bool = True
) -> list[JsonObject]:
    process = host.process if isinstance(host, NativeTTY) else host
    if process is None:
        return []
    table = process_table(runtime)
    helpers = []
    for item in table.values():
        try:
            argv = shlex.split(item["command"])
        except ValueError:
            continue
        if (
            len(argv) >= 3
            and argv[1] == str(runtime / "helpers/cli.js")
            and argv[2] == "refresh"
            and below(item["pid"], process.pid, table)
        ):
            helpers.append({**item, "kind": "helper"})
    children = []
    for item in table.values():
        try:
            argv = shlex.split(item["command"])
        except ValueError:
            continue
        if (
            len(argv) >= 4
            and Path(argv[0]).name == "gh"
            and argv[1:4] == ["api", "--hostname", "github.com"]
            and any(below(item["pid"], helper["pid"], table) for helper in helpers)
        ):
            require(item["pgid"] == item["pid"], "native-gh-not-detached-owned-group")
            children.append({**item, "kind": "gh"})
    if require_both and (not helpers or not children):
        return []
    return [*helpers, *children]


def wait_owned_work(host: NativeTTY, runtime: Path) -> list[JsonObject]:
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        host.pump(0.02)
        if host.answer_text(host.rendered()) is not None:
            raise Unavailable("native-refresh-completed-before-inflight-proof")
        if host.process is None or host.process.poll() is not None:
            raise Unavailable("native-host-ended-before-inflight-proof")
        work = owned_work(host, runtime)
        if work:
            return work
    raise Unavailable("native-helper-and-gh-inflight-ownership-not-observed")


def assert_work_absent(
    work: list[JsonObject], cwd: Path, host: NativeTTY | None = None
) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        table = process_table(cwd)
        alive = any(item["pid"] in table for item in work)
        groups = any(
            shared.group_exists(item["pgid"]) for item in work if item["kind"] == "gh"
        )
        if not alive and not groups:
            return
        if host is not None:
            host.pump(0.05)
        else:
            time.sleep(0.05)
    raise Failure("native-owned-helper-or-gh-group-survived-interruption")


def quiesce_owned_work(
    host: NativeTTY | subprocess.Popen[bytes], runtime: Path, captured: list[JsonObject]
) -> None:
    """Freeze only our owned execution before the final detached-child inventory."""
    process = host.process if isinstance(host, NativeTTY) else host
    if process is None or process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGSTOP)
    current = owned_work(host, runtime, require_both=False)
    captured.extend(current)
    for item in current:
        if item["kind"] == "helper":
            os.kill(item["pid"], signal.SIGSTOP)
    captured.extend(owned_work(host, runtime, require_both=False))


def cleanup_owned_work(work: list[JsonObject], cwd: Path) -> None:
    # Cleanup is not qualification evidence. Signal only exact captured process
    # identities; never signal a shared host group or an unproven descendant.
    table = process_table(cwd)
    for item in work:
        current = table.get(item["pid"])
        if current is None:
            continue
        require(
            all(current[key] == item[key] for key in ("pid", "pgid", "command")),
            "native-owned-process-identity-changed",
        )
        try:
            if item["kind"] == "gh" and item["pgid"] == item["pid"]:
                os.killpg(item["pgid"], signal.SIGTERM)
            else:
                os.kill(item["pid"], signal.SIGKILL)
        except ProcessLookupError:
            pass
    assert_work_absent(work, cwd)


def json_answer(text: str) -> JsonObject:
    # A TTY projection must retain source text inside strings. Exact title/url
    # validation below fails closed if terminal wrapping lost source characters.
    decoder = json.JSONDecoder()
    try:
        value, end = decoder.raw_decode(text)
    except (ValueError, TypeError) as error:
        raise Failure("native-json-answer-malformed") from error
    require(
        not text[end:].strip() and isinstance(value, dict),
        "native-json-answer-framing-invalid",
    )
    return cast(JsonObject, value)


def refresh_answer(
    text: str, expected: JsonObject, started: int, finished: int
) -> JsonObject:
    value = json_answer(text)
    require(
        set(value) == {"view", "transition"} and type(value["transition"]) is bool,
        "native-refresh-envelope-invalid",
    )
    shared.validate_view(value["view"], expected, started, finished)
    return value


def semantic(view: JsonObject) -> str:
    # Mirrors transitionKey's public semantic fields, excluding sample clocks.
    pulls = []
    for pull in sorted(view["pulls"], key=lambda item: item["number"]):
        value = {
            key: pull[key]
            for key in (
                "number",
                "title",
                "url",
                "headOid",
                "baseOid",
                "action",
                "nextAction",
            )
        }
        value["diagnostics"] = sorted(pull["diagnostics"])
        for name in DIMENSIONS:
            dimension = pull[name]
            value[name] = {
                "state": dimension["state"],
                "reasons": sorted(dimension["reasons"]),
                "sources": sorted(dimension["sources"]),
            }
        pulls.append(value)
    return json.dumps(
        {
            "schema": view["schema"],
            "repository": view["repository"],
            "viewerId": view["viewerId"],
            "pulls": pulls,
            "edges": sorted(
                view["edges"], key=lambda edge: (edge["parent"], edge["child"])
            ),
            "diagnostics": sorted(view["diagnostics"]),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def unavailable_answer(text: str, started: int, finished: int) -> None:
    value = json_answer(text)
    if "error" in value:
        require(
            value == {"error": "operation-failed"}, "native-unavailable-wrong-failure"
        )
        return
    require(
        set(value) == {"view", "transition"} and type(value["transition"]) is bool,
        "native-unavailable-envelope-invalid",
    )
    view = value["view"]
    require(
        isinstance(view, dict)
        and view.get("schema") == "armory.delivery-radar.view/v1"
        and view.get("repository") == REPOSITORY
        and type(view.get("observedAt")) is int
        and started <= view["observedAt"] <= finished,
        "native-unavailable-view-invalid",
    )
    pulls = view.get("pulls")
    require(
        isinstance(pulls, list) and len(pulls) == 1 and isinstance(pulls[0], dict),
        "native-unavailable-selection-invalid",
    )
    pull = pulls[0]
    require(
        pull.get("number") == MISSING_PR
        and pull.get("headOid") is None
        and pull.get("baseOid") is None
        and pull.get("action") == "owner-decision"
        and all(
            isinstance(pull.get(name), dict) and pull[name].get("state") == "unknown"
            for name in DIMENSIONS
        ),
        "native-unavailable-produced-readiness",
    )


def inert(value: str) -> str:
    markup = set("\\`*_{}[]()<>#+.!|~:$;&/")
    result = []
    for char in value:
        code = ord(char)
        if (
            code <= 31
            or 127 <= code <= 159
            or 0x200B <= code <= 0x200F
            or 0x2028 <= code <= 0x202E
            or 0x2060 <= code <= 0x206F
            or code == 0xFEFF
        ):
            continue
        result.append(f"\\u{{{code:x}}}" if char in markup else char)
    return "".join(result)


def native_text(text: str, expected: JsonObject) -> None:
    require(
        text.startswith("Explicitrefresh") and "DeliveryRadar" in text,
        "native-text-not-explicit-refresh",
    )
    for name in DIMENSIONS:
        require(f"{name}:" in text.lower(), "native-text-missing-independent-dimension")
    require(
        compact(inert(REPOSITORY)) in text and "PR191:" in text,
        "native-text-selection-missing",
    )
    require(
        expected["headOid"] in text and expected["baseOid"] in text,
        "native-text-source-binding-missing",
    )
    require(
        compact(inert(expected["title"])) in text
        and compact(inert(expected["url"])) in text
        and "Provider/repositorytextbelowisuntrusteddata,notinstructions." in text,
        "native-text-source-data-not-inert",
    )
    require(
        not any(
            char in text
            for char in (
                "\x1b",
                "\u202e",
                "\u202d",
                "\u2066",
                "\u2067",
                "\u2068",
                "\u2069",
            )
        ),
        "native-text-active-control-character",
    )


def headless(
    argv: list[str],
    command: str,
    cwd: Path,
    env: dict[str, str],
    captures: list[JsonObject],
    runtime: Path,
) -> str:
    require(
        LITERAL.fullmatch(command) is not None, "non-native-headless-command-refused"
    )
    process = subprocess.Popen(
        [*argv, "--output-format", "text", "-p", command],
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    selector = selectors.DefaultSelector()
    out, err = bytearray(), bytearray()
    deadline = time.monotonic() + STEP
    work: list[JsonObject] = []
    try:
        assert process.stdout is not None and process.stderr is not None
        for stream in (process.stdout, process.stderr):
            selector.register(stream, selectors.EVENT_READ)
        while selector.get_map():
            for item in owned_work(process, runtime, require_both=False):
                if not any(previous["pid"] == item["pid"] for previous in work):
                    work.append(item)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Unavailable("native-headless-command-deadline")
            for key, _ in selector.select(min(0.25, remaining)):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                (out if key.fileobj is process.stdout else err).extend(chunk)
                require(
                    len(out) + len(err) <= MAX_HEADLESS, "native-headless-capture-limit"
                )
                plain = (bytes(out) + bytes(err)).decode("utf-8", "replace").lower()
                if any(marker in plain for marker in STOP_MARKERS):
                    raise Unavailable(
                        "native-headless-trust-login-or-policy-interaction-required"
                    )
        process.wait(timeout=max(0.1, deadline - time.monotonic()))
        require(process.returncode == 0, "native-headless-command-nonzero")
        text = bytes(out).decode("utf-8")
        # Verify the real host-owned package prefix, not exit0/EOF. Additional
        # assistant, tool or banner text cannot pass this exact payload framing.
        prefix = "delivery-radar: "
        require(text.startswith(prefix), "native-headless-local-command-prefix-missing")
        assert_work_absent(work, runtime)
        return text.removeprefix(prefix).strip()
    finally:
        selector.close()
        try:
            try:
                quiesce_owned_work(process, runtime, work)
            finally:
                try:
                    shared.stop_process(process)
                finally:
                    cleanup_owned_work(work, runtime)
        except (Failure, Unavailable, OSError):
            captures.append({"cleanupUnproven": True, "ownedProcesses": work})
            raise
        finally:
            for pipe in (process.stdout, process.stderr):
                if pipe is not None:
                    pipe.close()
            captures.append(
                {
                    "command": command,
                    "exitCode": process.returncode,
                    "stdout": out.decode("utf-8", "replace"),
                    "stderr": err.decode("utf-8", "replace"),
                    "ownedProcesses": work,
                }
            )
        require(
            not shared.group_exists(process.pid),
            "native-headless-process-group-survived",
        )
        # This disposable artifact's exact helper argv must not survive even
        # when it has escaped its original host ancestry.
        table = process_table(runtime)
        require(
            not any(
                str(runtime / "helpers/cli.js") in item["command"]
                for item in table.values()
            ),
            "native-headless-helper-survived",
        )


def execute(args: argparse.Namespace, report: JsonObject, root: Path) -> None:
    if sys.version_info < (3, 12) or os.name != "posix":
        raise Unavailable("python312-posix-required")
    if pyte is None:
        raise Unavailable("pyte-terminal-emulator-required")
    cwd, settings = context(args)
    claude = shutil.which("claude")
    if claude is None or shutil.which("bun") is None or shutil.which("gh") is None:
        raise Unavailable("installed-claude-bun-gh-required")
    words = (
        shared.finite([claude, "--version"], root, "native-version-unavailable")
        .decode()
        .split()
    )
    if not words:
        raise Unavailable("native-version-unavailable")
    report["version"] = words[0]
    if words[0] != "2.1.309":
        raise Unavailable("installed-version-needs-native-interface-review")
    runtime = prepare_artifact(args, report, root)
    report["settingsSha256"] = hashlib.sha256(settings.read_bytes()).hexdigest()
    report["context"] = (
        "explicit reviewed additive settings; normal HOME/authentication/settings sources retained"
    )
    production = (
        Path(args.artifact).resolve()
        if args.artifact
        else root / "build/extensions/delivery-radar/claude"
    )
    source = Path(args.feature_dir).resolve()
    before_definition = (source / "EXTENSION.md").read_bytes()
    before_manifest = (production / CONTENT_MANIFEST).read_bytes()
    runtime_files = {
        record["path"]: (runtime / record["path"]).read_bytes()
        for record in verify_artifact_dir(runtime)["files"]
    }
    runtime_files[CONTENT_MANIFEST] = before_manifest
    argv = [claude, "--settings", str(settings), "--plugin-dir", str(runtime)]
    env = dict(os.environ)
    hosts: list[NativeTTY] = []
    captures: list[JsonObject] = []
    all_work: list[JsonObject] = []
    report["headless"] = {
        "mode": "whole-native-command",
        "scenarios": [
            {"name": name, "status": "not-run"}
            for name in ("help", "refresh", "invalid", "unavailable")
        ],
    }

    def host() -> NativeTTY:
        native = NativeTTY(argv, cwd, env)
        hosts.append(native)
        native.start()
        return native

    def observe(native: NativeTTY) -> JsonObject:
        expected = shared.public_pr(cwd)
        started = time.time_ns() // 1_000_000
        answer = native.command(f"{COMMAND} refresh {REPOSITORY} 191 --json")
        finished = time.time_ns() // 1_000_000
        value = refresh_answer(answer, expected, started, finished)
        report["selectedPublicObservation"] = {
            key: expected[key]
            for key in (
                "repository",
                "number",
                "state",
                "headOid",
                "baseOid",
                "observedAt",
            )
        }
        return value

    try:
        native = host()
        help_text = native.command(f"{COMMAND} help")
        require(
            help_text.startswith("DeliveryRadar:")
            and "Unknownisnotreadiness." in help_text
            and "nobackgroundtimer" in help_text,
            "native-help-contract-missing",
        )
        first = observe(native)
        require(first["transition"] is False, "native-baseline-falsely-notified")
        shared.passed(report, "success")
        second = observe(native)
        require(
            second["transition"]
            == (semantic(first["view"]) != semantic(second["view"])),
            "native-semantic-transition-not-deduplicated",
        )
        shared.passed(report, "freshness")
        invalid = native.command(f"{COMMAND} refresh {REPOSITORY} 191,191 --json")
        require(
            invalid == "DeliveryRadar:invalid-arguments;noreadinessresult.",
            "native-invalid-selection-not-refused",
        )
        started = time.time_ns() // 1_000_000
        missing = native.command(f"{COMMAND} refresh {REPOSITORY} {MISSING_PR} --json")
        unavailable_answer(missing, started, time.time_ns() // 1_000_000)
        shared.passed(report, "failure")
        expected = shared.public_pr(cwd)
        native_text(native.command(f"{COMMAND} refresh {REPOSITORY} 191"), expected)
        shared.passed(report, "native-text")

        # Each headless process receives exactly one whole native command. No
        # --continue/resume/profile/auth switch and no ordinary prompt.
        payload = headless(argv, f"{COMMAND} help", cwd, env, captures, runtime)
        require(
            compact(payload) == compact(help_text),
            "native-headless-help-payload-mismatch",
        )
        report["headless"]["scenarios"][0]["status"] = "passed"
        expected = shared.public_pr(cwd)
        started = time.time_ns() // 1_000_000
        payload = headless(
            argv,
            f"{COMMAND} refresh {REPOSITORY} 191 --json",
            cwd,
            env,
            captures,
            runtime,
        )
        qualified = refresh_answer(
            payload, expected, started, time.time_ns() // 1_000_000
        )
        require(
            qualified["transition"] is False,
            "native-headless-baseline-falsely-notified",
        )
        report["headless"]["scenarios"][1]["status"] = "passed"
        payload = headless(
            argv,
            f"{COMMAND} refresh {REPOSITORY} 191,191 --json",
            cwd,
            env,
            captures,
            runtime,
        )
        require(
            compact(payload) == "DeliveryRadar:invalid-arguments;noreadinessresult.",
            "native-headless-invalid-selection-not-refused",
        )
        report["headless"]["scenarios"][2]["status"] = "passed"
        started = time.time_ns() // 1_000_000
        payload = headless(
            argv,
            f"{COMMAND} refresh {REPOSITORY} {MISSING_PR} --json",
            cwd,
            env,
            captures,
            runtime,
        )
        unavailable_answer(payload, started, time.time_ns() // 1_000_000)
        report["headless"]["scenarios"][3]["status"] = "passed"

        native.stop()
        reopened = host()
        reopened_value = observe(reopened)
        require(
            reopened_value["transition"] is False,
            "native-reopen-retained-session-dedup",
        )
        shared.passed(report, "reopen")

        selection = ",".join(str(number) for number in range(172, 192))
        long_command = f"{COMMAND} refresh {REPOSITORY} {selection} --json"
        interrupt_mark = reopened.begin(long_command)
        work = wait_owned_work(reopened, runtime)
        all_work.extend(work)
        reopened.interrupt()
        # An actual helper AND detached gh must be absent before any forced
        # driver cleanup. A returned hook, empty stream or exit0 is not proof.
        assert_work_absent(work, runtime, reopened)
        require(
            reopened.process is not None and reopened.process.poll() is None,
            "native-interrupt-disposed-host-instead-of-active-work",
        )
        reopened.read(reopened.prompt_after_pending, interrupt_mark)
        reopened.drain()
        tail = reopened.answer_text(reopened.rendered())
        if tail is not None:
            require(
                json_answer(tail) == {"error": "cancelled"},
                "native-interrupted-refresh-published-view",
            )
        reopened.pending = None
        observe(reopened)  # The same actual host must remain locally usable.
        shared.passed(report, "cancellation")

        reopened.begin(long_command)
        work = wait_owned_work(reopened, runtime)
        all_work.extend(work)
        reopened.dispose_active()
        deadline = time.monotonic() + 12
        while reopened.process is not None and reopened.process.poll() is None:
            reopened.pump(0.05)
            require(
                reopened.answer_text(reopened.rendered()) is None,
                "native-session-disposal-published-stale-refresh",
            )
            if time.monotonic() >= deadline:
                raise Unavailable(
                    "native-session-disposal-during-command-not-supported"
                )
        # Disposal must itself end the session and active work. Driver stop is
        # deliberately later; it cannot manufacture this category's success.
        assert_work_absent(work, runtime)
        require(
            reopened.process is not None
            and not shared.group_exists(reopened.process.pid),
            "native-disposed-session-group-survived",
        )
        require(
            reopened.answer_text(reopened.rendered()) is None,
            "native-disposed-session-published-stale-refresh",
        )
        reopened.pending = None
        reopened.stop()
        fresh = host()
        require(
            observe(fresh)["transition"] is False,
            "native-new-session-retained-stale-transition",
        )
        fresh.stop()
        shared.passed(report, "changed-during-run")
        report["inflightOwnership"] = {
            "observedHelper": True,
            "observedDetachedGh": True,
            "interruptHelperAndGhAbsenceProven": True,
            "sessionDisposalHelperAndGhAbsenceProven": True,
            "stalePublicationSuppressed": True,
        }
    finally:
        cleanup_proven = True
        for native in reversed(hosts):
            try:
                quiesce_owned_work(native, runtime, all_work)
            except (Failure, Unavailable, OSError):
                cleanup_proven = False
            try:
                native.stop(forced=True)
            except (Failure, Unavailable, OSError):
                cleanup_proven = False
        for capture_record in captures:
            all_work.extend(capture_record.get("ownedProcesses", []))
        try:
            cleanup_owned_work(all_work, runtime)
            table = process_table(runtime)
            require(
                not any(
                    str(runtime / "helpers/cli.js") in item["command"]
                    for item in table.values()
                ),
                "native-helper-survived-cleanup",
            )
        except (Failure, Unavailable, OSError):
            cleanup_proven = False
        report["_cleanupProven"] = cleanup_proven
        capture = Path(args.report).with_suffix(".private.json")
        private_write(
            capture,
            json.dumps(
                {
                    "terminalHex": [bytes(item.raw).hex() for item in hosts],
                    "answers": [item.answers for item in hosts],
                    "headless": captures,
                    "ownedProcesses": all_work,
                }
            ),
        )
        require(
            stat.S_IMODE(capture.stat().st_mode) == 0o600,
            "native-private-capture-mode-invalid",
        )
        if not cleanup_proven:
            raise Failure("native-cleanup-not-proven")

    require(
        before_definition == (source / "EXTENSION.md").read_bytes()
        and before_manifest == (production / CONTENT_MANIFEST).read_bytes(),
        "native-feature-source-or-production-manifest-mutated",
    )
    verify_artifact_dir(production)
    for path, data in runtime_files.items():
        require(
            (runtime / path).read_bytes() == data,
            "native-runtime-artifact-content-mutated",
        )
    # The pinned development loader generates SDK declarations and an exact
    # extends-only root tsconfig. Neither is feature state.
    additions = {
        path.relative_to(runtime).as_posix()
        for path in runtime.rglob("*")
        if path.is_file()
    } - set(runtime_files)
    require(
        all(
            path.startswith(".claude-plugin/types/") or path == "tsconfig.json"
            for path in additions
        ),
        "native-feature-persisted-unexpected-artifact-state",
    )
    if "tsconfig.json" in additions:
        try:
            loader_config = json.loads((runtime / "tsconfig.json").read_text())
        except (UnicodeError, json.JSONDecodeError) as error:
            raise Failure("native-loader-typescript-config-invalid") from error
        require(
            loader_config == {"extends": "./.claude-plugin/types/tsconfig.json"},
            "native-loader-typescript-config-invalid",
        )
    require(
        not any(path.is_symlink() for path in runtime.rglob("*")),
        "native-runtime-symlink-created",
    )
    report["privateOutput"] = {
        "captureMode": "0600",
        "reportParentMode": "0700",
        "sourceAndProductionArtifactUnchanged": True,
        "onlyDisposableLoaderSdkAdditionsPermitted": True,
        "rawCapturesAndProcessArgumentsExcludedFromReport": True,
        "featurePersistenceClaimScope": "canonical definition, complete production artifact and detached runtime artifact",
    }
    shared.passed(report, "private-output")
    require(
        all(item["status"] == "passed" for item in report["scenarios"]),
        "native-required-scenario-incomplete",
    )
    require(
        all(item["status"] == "passed" for item in report["headless"]["scenarios"]),
        "native-headless-scenario-incomplete",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature-dir", required=True)
    parser.add_argument("--artifact")
    parser.add_argument("--report", required=True)
    parser.add_argument(
        "--trusted-cwd", default=os.environ.get("ARMORY_CLAUDE_NATIVE_CWD")
    )
    parser.add_argument(
        "--settings", default=os.environ.get("ARMORY_CLAUDE_NATIVE_SETTINGS")
    )
    args = parser.parse_args()
    report_path = Path(args.report)
    companion = report_path.with_suffix(".private.json")
    if (
        not Path(args.feature_dir).is_absolute()
        or not report_path.is_absolute()
        or (args.artifact and not Path(args.artifact).is_absolute())
    ):
        parser.error("feature/artifact/report paths must be absolute")
    if (
        not report_path.parent.is_dir()
        or report_path.parent.is_symlink()
        or os.path.lexists(report_path)
        or os.path.lexists(companion)
        or companion == report_path
        or stat.S_IMODE(report_path.parent.stat().st_mode) != 0o700
    ):
        parser.error(
            "report parent must be private 0700; report/capture must not exist"
        )
    os.umask(0o077)
    root = Path(
        tempfile.mkdtemp(prefix="armory-delivery-claude-", dir="/tmp")
    ).resolve()
    report: JsonObject = {
        "schemaVersion": 1,
        "host": "claude",
        "mode": "interactive",
        "version": None,
        "status": "unavailable",
        "driverSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scenarios": [
            {"name": name, "status": "not-run", "assertion": ASSERTIONS[name]}
            for name in SCENARIOS
        ],
        "normalHomeAndDefaultAuthentication": True,
        "managedAndUserEnforcementRetained": True,
        "ordinaryProfileSessionLogCacheEffectsPermitted": True,
        "usageInterpretation": "Only discovered native commands and whole-native-command -p submitted; not a model/network-call meter.",
        "notExercised": [
            "installed-loader",
            "SDK",
            "other host versions or operating systems",
            "network-call metering",
        ],
    }
    signals = (signal.SIGALRM, signal.SIGINT, signal.SIGTERM)
    old = {kind: signal.getsignal(kind) for kind in signals}

    def interrupted(signum: int, frame: FrameType | None) -> None:
        signal.alarm(0)
        for kind in signals:
            signal.signal(kind, signal.SIG_IGN)
        raise Unavailable(
            "whole-driver-deadline"
            if signum == signal.SIGALRM
            else "native-driver-interrupted"
        )

    for kind in signals:
        signal.signal(kind, interrupted)
    signal.alarm(LIMIT)
    code = 3
    try:
        execute(args, report, root)
        report["status"], code = "passed", 0
        report["reasonCode"] = "all-real-scenarios-passed"
    except Unavailable as error:
        report["reasonCode"] = str(error)
    except Failure as error:
        report["status"], report["reasonCode"], code = "failed", str(error), 1
    except ToolUnavailableError:
        report["reasonCode"] = "production-artifact-build-tool-unavailable"
    except BuildError:
        report["status"], report["reasonCode"], code = (
            "failed",
            "native-artifact-validation-or-build-failed",
            1,
        )
    except (OSError, ValueError, LookupError, TypeError, subprocess.SubprocessError):
        report["reasonCode"] = "native-prerequisite-or-protocol-unavailable"
    finally:
        signal.alarm(0)
        for kind, handler in old.items():
            signal.signal(kind, handler)
        if report.pop("_cleanupProven", True):
            try:
                shutil.rmtree(root)
            except OSError:
                report["status"], report["reasonCode"], code = (
                    "failed",
                    "owned-scratch-cleanup-failed",
                    1,
                )
        else:
            report["ownedScratchRetainedForUnprovenCleanup"] = True
            report["status"], report["reasonCode"], code = (
                "failed",
                "native-cleanup-not-proven",
                1,
            )
    if "reasonCode" in report and not re.fullmatch(
        r"[a-z0-9-]{1,160}", report["reasonCode"]
    ):
        report["reasonCode"] = "native-unsanitized-reason-rejected"
    try:
        private_write(report_path, json.dumps(report, sort_keys=True, indent=2) + "\n")
    except OSError:
        report["status"], report["reasonCode"], code = (
            "unavailable",
            "private-report-write-unavailable",
            3,
        )
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
