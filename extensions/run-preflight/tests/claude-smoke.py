#!/usr/bin/env python3
"""Opt-in, command-only Claude Code 2.1.310 Run Preflight qualification.

This driver never submits an ordinary prompt, reads credentials, changes trust,
changes enforcement, or launches a hosted experiment. Only the explicit probe
can run the real project's bounded synthetic Python-pass child. Normal HOME,
default authentication and genuine user/managed hooks remain in force; ordinary
host session/log/cache effects are permitted. Exit zero requires all eight real
interactive categories, separately classified whole-command headless behavior,
and confirmed cleanup. Raw captures are private, bounded, and not public proof.

When qualification and cleanup both fail, reasonCode retains the qualification
failure and cleanupReasonCode/cleanupFailures report cleanup separately. Exact
process identities and exception messages stay in the private companion capture.
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
    "_armory_preflight_native_fixture", Path(__file__).with_name("native_fixture.py")
)
assert _spec is not None and _spec.loader is not None
_fixture_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _fixture_module
_spec.loader.exec_module(_fixture_module)
make_fixture = _fixture_module.make_fixture

type JsonObject = dict[str, Any]
COMMAND = "/armory-preflight"
DESCRIPTION = (
    "Check explicitly declared managed-run prerequisites without a provider call"
)
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
ASSERTIONS = {
    "success": "explicit JSON selection binds the installed helper; check is read-only and one explicit real-project probe reports exactly one Python-pass child, zero provider calls and no terminal receipt",
    "failure": "invalid/missing selection and stale or expired prerequisites never produce readiness or dispatch a bridge",
    "reopen": "a fresh actual host independently checks a fresh selected declaration, without persisted feature state",
    "freshness": "current local quota remains unknown; stale source and expired declaration block a subsequent invocation",
    "changed-during-run": "observed real bridge barrier is released after identity drift; real dispatch admission refuses before the child",
    "cancellation": "actual SDK command cancellation and session disposal suppress stale publication, terminate observed owned helper/bridge identities and allow a fresh command",
    "private-output": "bounded captures are 0600 and public report omits raw commands/paths/facts; production bytes are unchanged and runtime additions are loader-only",
    "native-text": "complete native help/text and JSON frames retain explicit selected paths with spaces and scope limitations",
}
STEP, LIMIT = 75, 900
MAX_CAPTURE, MAX_HEADLESS = 8 * 1024 * 1024, 2 * 1024 * 1024
APPROVED_SETTINGS = Path(
    "/var/folders/yr/1rcvpjws5mjfcq327shzrrz00000gn/T/armory-extensions-control-20261022-e7ozqsb3/m10-native-qualification-yddnnr5q/claude-settings.json"
)
TRUSTED_CWD = Path("/Users/druk/WorkSpace/AetherForge")
ANSI = re.compile(r"\x1b(?:\][^\x07]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~]|[@-_])")
STOP_MARKERS = (
    "do you trust the files",
    "trust this folder",
    "trust this workspace",
    "login required",
    "please log in",
    "sign in to",
    "permission required",
    "allow this action",
    "bypass permissions",
    "accept the risk",
    "do you want to proceed",
    "choose an account",
)


class Failure(Exception):
    pass


class Unavailable(Exception):
    pass


def require(value: object, code: str) -> None:
    if not value:
        raise Failure(code)


def cleanup_failure(phase: str, error: BaseException) -> JsonObject:
    reason = str(error)
    if not isinstance(error, (Failure, Unavailable)) or not re.fullmatch(
        r"[a-z0-9-]{1,160}", reason
    ):
        reason = "native-cleanup-inspection-or-process-error"
    return {
        "phase": phase,
        "reasonCode": reason,
        "exceptionType": type(error).__name__,
        "message": str(error),
    }


def compact(value: str) -> str:
    return "".join(value.split())


def private_write(path: Path, value: str | bytes) -> None:
    data = value.encode() if isinstance(value, str) else value
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)


def finite(argv: list[str], cwd: Path, limit: int = 4 * 1024 * 1024) -> bytes:
    # Only bounded local metadata/version commands, never a model prompt.
    result = subprocess.run(
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=15,
        check=False,
    )
    require(
        result.returncode == 0 and len(result.stdout) + len(result.stderr) <= limit,
        "native-local-inspection-failed",
    )
    return result.stdout


def literal(text: str) -> bool:
    if text == f"{COMMAND} help":
        return True
    match = re.fullmatch(r"/armory-preflight (check|probe|admit) (.+?)( --json)?", text)
    if match is None:
        return False
    try:
        selected = json.loads(match[2])
    except ValueError:
        return False
    # admit and relative/missing selections are included only as explicit local
    # negative commands; no shell, prompt, expansion, newline or extra option.
    return (
        isinstance(selected, dict)
        and set(selected) == {"config", "declaration"}
        and all(
            isinstance(value, str) and not any(ord(char) < 32 for char in value)
            for value in selected.values()
        )
    )


def screen_text(raw: bytes) -> str:
    return compact(ANSI.sub("", raw.decode("utf-8", "replace")))


class NativeTTY:
    def __init__(self, argv: list[str], cwd: Path, env: dict[str, str]) -> None:
        if pyte is None:
            raise Unavailable("pyte-terminal-emulator-required")
        self.argv, self.cwd, self.env = argv, cwd, env
        self.master = -1
        self.process: subprocess.Popen[bytes] | None = None
        self.raw = bytearray()
        self.answers: list[JsonObject] = []
        self.ready = self.interaction_required = self.closed = False
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

    def guard(self) -> None:
        plain = ANSI.sub("", self.rendered().decode("utf-8", "replace")).lower()
        if any(marker in plain for marker in STOP_MARKERS):
            self.interaction_required = True
            raise Unavailable("native-trust-login-or-policy-interaction-required")

    def pump(self, timeout: float = 0.05) -> None:
        if (
            self.master != -1
            and select.select([self.master], [], [], max(0, timeout))[0]
        ):
            try:
                chunk = os.read(self.master, 65536)
            except OSError:
                chunk = b""
            if chunk:
                self.raw.extend(chunk)
                require(len(self.raw) <= MAX_CAPTURE, "native-terminal-capture-limit")
                self.terminal.feed(self.decoder.decode(chunk))
        self.guard()

    def drain(self) -> None:
        deadline = time.monotonic() + 3
        while self.master != -1 and select.select([self.master], [], [], 0.1)[0]:
            if time.monotonic() >= deadline:
                raise Unavailable("native-terminal-drain-deadline")
            before = len(self.raw)
            self.pump(0)
            if len(self.raw) == before:
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
                value = self.rendered()
                if len(self.raw) > start and predicate(value):
                    return value
                raise Unavailable("native-process-exited-before-response")
            self.pump(0.1)
        raise Unavailable("native-command-response-deadline")

    def discover(self, command: str, description: str) -> None:
        self.drain()
        mark = len(self.raw)
        os.write(self.master, command.encode())
        self.read(lambda raw: compact(description) in screen_text(raw), mark)
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
                    "import fcntl,os,sys,termios; fcntl.ioctl(0,termios.TIOCSCTTY,0); os.execvpe(sys.argv[1],sys.argv[1:],os.environ)",
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
            self.pending is None and literal(text) and COMMAND in self.discovered,
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
        if not tail.startswith("┌"):
            return None
        match = re.search(r"┌─+┐(.*?)└─+┘", tail)
        if match is None or "❯" not in tail[match.end() :]:
            return None
        require(
            "┌" not in tail[match.end() : tail.index("❯", match.end())],
            "native-multiple-answer-frames",
        )
        positions = [index for index, char in enumerate(visual) if not char.isspace()]
        first, last = offset + match.start(1), offset + match.end(1)
        if first == last:
            return None
        candidate = visual[positions[first] : positions[last - 1] + 1].strip()
        if not candidate.startswith("run-preflight:"):
            return None
        candidate = candidate.removeprefix("run-preflight:").lstrip()
        if candidate.startswith("{"):
            try:
                _, end = json.JSONDecoder().raw_decode(candidate)
            except ValueError:
                return None
            require(not candidate[end:].strip(), "native-multiple-answer-frames")
            return candidate
        return compact(candidate)

    def prompt_after_pending(self, rendered: bytes) -> bool:
        if self.pending is None:
            return False
        flat = screen_text(rendered)
        echo = f"❯{compact(self.pending)}"
        position = flat.rfind(echo)
        return position >= 0 and "❯" in flat[position + len(echo) :]

    def finish(self, mark: int) -> str:
        answer = self.answer_text(
            self.read(lambda raw: self.answer_text(raw) is not None, mark)
        )
        require(answer is not None, "native-answer-framing-lost")
        assert answer is not None
        self.answers.append({"command": self.pending, "text": answer})
        self.pending = None
        return answer

    def command(self, text: str) -> str:
        return self.finish(self.begin(text))

    def stop(self, forced: bool = False) -> None:
        if self.closed:
            return
        try:
            if (
                self.process is not None
                and self.process.poll() is None
                and not forced
                and self.ready
                and not self.interaction_required
                and self.pending is None
            ):
                os.write(self.master, b"/exit\r")
                deadline = time.monotonic() + 8
                while self.process.poll() is None and time.monotonic() < deadline:
                    self.pump(0.1)
        finally:
            # Release the owned terminal before waiting, as in existing drivers.
            if self.master != -1:
                os.close(self.master)
                self.master = -1
            if self.process is not None:
                stop_process(self.process)
            self.closed = True


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
    # A leader can exit while other members survive; check the actual group.
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        return
    os.killpg(process.pid, signal.SIGKILL)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    raise Failure("native-host-process-group-survived")


def context(
    args: argparse.Namespace, root: Path, report: JsonObject
) -> tuple[Path, Path]:
    cwd, source = Path(args.trusted_cwd), Path(args.settings)
    if (
        not cwd.is_absolute()
        or not source.is_absolute()
        or cwd.resolve() != TRUSTED_CWD
        or source.is_symlink()
        or not source.is_file()
        or stat.S_IMODE(source.stat().st_mode) & 0o077
    ):
        raise Unavailable("reviewed-native-context-unavailable")
    value = json.loads(source.read_text())
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
    environment = {
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
    if (
        not isinstance(value, dict)
        or set(value) != {*fixed, "env"}
        or any(value.get(key) != expected for key, expected in fixed.items())
        or not isinstance(value.get("env"), dict)
        or set(value["env"]) != set(environment) | auxiliary
        or any(
            value["env"].get(key) != expected for key, expected in environment.items()
        )
        or not all(isinstance(value["env"][key], str) for key in auxiliary)
    ):
        raise Unavailable("native-profile-must-match-reviewed-additive-controls")
    # Rebind only reviewed optional-writer destinations, not auth, trust,
    # permissions, hooks, model, settings sources or owner-vault configuration.
    value["env"] = {
        **environment,
        "LAVISH_AXI_STATE_DIR": str(root / "optional-lavish"),
        "LACONIC_OBSERVE_AUDIT_PATH": str(root / "optional-laconic.jsonl"),
        "CHROME_DEVTOOLS_AXI_SESSION": f"armory-native-preflight-{root.name}",
    }
    settings = root / "claude-settings.json"
    private_write(settings, json.dumps(value))
    # Read only settings JSON, never credential/keychain/auth files. Record only
    # genuine hook definitions in memory and expose a digest/count, not commands.
    controls = []
    sources = [
        Path.home() / ".claude/settings.json",
        Path("/Library/Application Support/ClaudeCode/managed-settings.json"),
        cwd / ".claude/settings.json",
        cwd / ".claude/settings.local.json",
    ]
    for path in sources:
        if path.is_file():
            configured = json.loads(path.read_text())
            require(isinstance(configured, dict), "native-current-settings-invalid")
            hooks = configured.get("hooks", {})
            require(isinstance(hooks, dict), "native-current-hooks-invalid")
            controls.append(hooks)
    count = sum(
        len(group.get("hooks", []))
        for hooks in controls
        for groups in hooks.values()
        if isinstance(groups, list)
        for group in groups
        if isinstance(group, dict)
    )
    if count == 0:
        raise Unavailable("native-genuine-user-managed-hooks-not-observed")
    report["controls"] = {
        "genuineHookCount": count,
        "genuineHooksSha256": hashlib.sha256(
            json.dumps(controls, sort_keys=True).encode()
        ).hexdigest(),
        "reviewedSettingsSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "additiveSettingsSha256": hashlib.sha256(settings.read_bytes()).hexdigest(),
        "noHooksPermissionsAuthTrustOrSettingsSourceOverride": True,
        "optionalWriterDestinationsAreDisposable": True,
    }
    return cwd, settings


def prepare_artifact(
    args: argparse.Namespace, report: JsonObject, root: Path
) -> tuple[Path, Path]:
    feature = Path(args.feature_dir).resolve(strict=True)
    metadata = load_metadata(feature)
    artifact = (
        Path(args.artifact).resolve(strict=True)
        if args.artifact
        else build_feature(feature, root / "build")["claude"]
    )
    manifest = verify_artifact_dir(artifact)
    require(
        metadata.name == "run-preflight"
        and metadata.host_entries.get("claude") == "claude-code/register.ts"
        and metadata.storage == "none"
        and manifest.get("feature") == metadata.name
        and manifest.get("host") == "claude"
        and manifest.get("storage") == "none"
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
    _, assembled = assemble_feature(feature)
    actual = {
        record["path"]: (artifact / record["path"]).read_bytes()
        for record in manifest["files"]
    }
    actual[CONTENT_MANIFEST] = (artifact / CONTENT_MANIFEST).read_bytes()
    require(actual == assembled["claude"], "native-artifact-source-binding-mismatch")
    runtime = root / "detached native package"
    shutil.copytree(artifact, runtime)
    verify_artifact_dir(runtime)
    digest = hashlib.sha256(actual[CONTENT_MANIFEST]).hexdigest()
    report["artifactManifestSha256"] = digest
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
    report["developmentLoaderUsesDisposableCopy"] = True
    return runtime, artifact


def process_table(cwd: Path) -> dict[int, JsonObject]:
    raw = finite(["ps", "-axo", "pid=,ppid=,pgid=,lstart=,command="], cwd).decode(
        "utf-8", "replace"
    )
    table = {}
    for line in raw.splitlines():
        fields = line.strip().split(None, 8)
        if len(fields) == 9:
            pid, ppid, pgid = map(int, fields[:3])
            table[pid] = {
                "pid": pid,
                "ppid": ppid,
                "pgid": pgid,
                "start": " ".join(fields[3:8]),
                "command": fields[8],
            }
    return table


def below(pid: int, ancestor: int, table: dict[int, JsonObject]) -> bool:
    seen = set()
    while pid in table and pid not in seen:
        if pid == ancestor:
            return True
        seen.add(pid)
        pid = table[pid]["ppid"]
    return False


def owned_work(
    host: NativeTTY | subprocess.Popen[bytes],
    runtime: Path,
    table: dict[int, JsonObject] | None = None,
) -> list[JsonObject]:
    process = host.process if isinstance(host, NativeTTY) else host
    if process is None:
        return []
    if table is None:
        table = process_table(runtime)
    helpers = [
        item
        for item in table.values()
        if str(runtime / "helpers/cli.js") in item["command"]
        and below(item["pid"], process.pid, table)
    ]
    return [
        item
        for item in table.values()
        if any(below(item["pid"], helper["pid"], table) for helper in helpers)
    ]


def wait_barrier(host: NativeTTY, runtime: Path, fixture: Any) -> list[JsonObject]:
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        host.pump(0.05)
        if fixture.ready.is_file() and fixture.pid.is_file():
            pid = int(fixture.pid.read_text())
            work = owned_work(host, runtime)
            require(
                any(
                    item["pid"] == pid and str(fixture.config.parent) in item["command"]
                    for item in work
                ),
                "native-barrier-ownership-not-proven",
            )
            require(
                any(
                    str(runtime / "helpers/cli.js") in item["command"] for item in work
                ),
                "native-helper-ownership-not-proven",
            )
            return work
    raise Unavailable("native-real-bridge-barrier-not-observed")


def assert_absent(work: list[JsonObject], runtime: Path) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        table = process_table(runtime)
        if not any(
            item["pid"] in table and table[item["pid"]]["start"] == item["start"]
            for item in work
        ):
            return
        time.sleep(0.05)
    raise Failure("native-owned-helper-or-bridge-survived")


def cleanup_work(work: list[JsonObject], runtime: Path) -> None:
    # Cleanup is not qualification. Signal only observed identities, never an
    # unrelated group or a PID inferred from a fixture file without ancestry.
    for kind in (signal.SIGTERM, signal.SIGKILL):
        table = process_table(runtime)
        for item in reversed(work):
            current = table.get(item["pid"])
            if current is not None and current["start"] == item["start"]:
                try:
                    if current["pgid"] == current["pid"]:
                        os.killpg(current["pid"], kind)
                    else:
                        os.kill(current["pid"], kind)
                except ProcessLookupError:
                    pass
        time.sleep(0.1)
    assert_absent(work, runtime)


def json_answer(text: str) -> JsonObject:
    try:
        value, end = json.JSONDecoder().raw_decode(text)
    except (ValueError, TypeError) as error:
        raise Failure("native-json-answer-malformed") from error
    require(
        isinstance(value, dict) and not text[end:].strip(),
        "native-json-answer-framing-invalid",
    )
    return cast(JsonObject, value)


def validate_view(
    text: str, fixture: Any, status: str, probe: str | None = None
) -> JsonObject:
    value = json_answer(text)
    require(
        set(value)
        == {
            "schemaVersion",
            "coreVersion",
            "selection",
            "status",
            "reasons",
            "quota",
            "run",
            "admitted",
            "probe",
            "limitations",
        }
        and value["schemaVersion"] == 1
        and value["coreVersion"] == "1.0.0"
        and value["selection"]
        == {"config": str(fixture.config), "declaration": str(fixture.declaration)}
        and value["status"] == status
        and value["admitted"] is False
        and isinstance(value["reasons"], list)
        and len(value["limitations"]) == 2,
        "native-projected-view-invalid",
    )
    require(
        not any(
            marker in json.dumps(value)
            for marker in (
                "accountFingerprint",
                "bridgeArgv",
                "recordSha256",
                "native-local-sentinel-no-account",
            )
        ),
        "native-sensitive-admission-exposed",
    )
    if value["quota"] is not None:
        require(
            set(value["quota"]) == {"status", "observedAt", "expiresAt"},
            "native-private-quota-fields-exposed",
        )
    if value["run"] is not None:
        require(
            set(value["run"])
            == {
                "id",
                "purpose",
                "provider",
                "identityKind",
                "profile",
                "cell",
                "expiresAt",
            },
            "native-private-run-fields-exposed",
        )
    if status == "unknown":
        require(
            value["quota"]["status"] == "unknown"
            and value["run"]["purpose"] == "synthetic-local-sentinel"
            and value["run"]["provider"] == "synthetic-local"
            and value["run"]["identityKind"] == "synthetic-local",
            "native-unknown-quota-or-scope-lost",
        )
    if probe is None:
        require(
            value["probe"] is None, "native-readonly-or-prerequisite-refusal-ran-bridge"
        )
    else:
        require(isinstance(value["probe"], dict), "native-probe-result-missing")
        expected = 1 if probe == "terminal-receipt-unavailable" else 0
        require(
            value["probe"]
            == {
                "schemaVersion": 1,
                "coreVersion": "1.0.0",
                "status": probe,
                "managedSpawns": expected,
                "providerCalls": 0,
                "reasons": value["probe"].get("reasons"),
            },
            "native-real-project-probe-result-invalid",
        )
        require(bool(value["probe"]["reasons"]), "native-probe-reason-missing")
    require(
        not list(fixture.checkpoint.rglob("*.json")),
        "native-synthetic-child-produced-derived-receipt",
    )
    return value


def headless(
    argv: list[str],
    text: str,
    cwd: Path,
    env: dict[str, str],
    captures: list[JsonObject],
    runtime: Path,
) -> str | None:
    require(literal(text), "non-native-headless-command-refused")
    process = subprocess.Popen(
        [*argv, "--output-format", "text", "-p", text],
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    selector = selectors.DefaultSelector()
    out, err = bytearray(), bytearray()
    work: list[JsonObject] = []
    deadline = time.monotonic() + STEP
    try:
        assert process.stdout is not None and process.stderr is not None
        for stream in (process.stdout, process.stderr):
            selector.register(stream, selectors.EVENT_READ)
        while selector.get_map():
            for item in owned_work(process, runtime):
                if not any(
                    prior["pid"] == item["pid"] and prior["start"] == item["start"]
                    for prior in work
                ):
                    work.append(item)
            if time.monotonic() >= deadline:
                raise Unavailable("native-headless-command-deadline")
            for key, _ in selector.select(0.1):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                (out if key.fileobj is process.stdout else err).extend(chunk)
                require(
                    len(out) + len(err) <= MAX_HEADLESS, "native-headless-capture-limit"
                )
                if any(
                    marker
                    in (bytes(out) + bytes(err)).decode("utf-8", "replace").lower()
                    for marker in STOP_MARKERS
                ):
                    raise Unavailable(
                        "native-headless-trust-login-or-policy-interaction-required"
                    )
        process.wait(timeout=max(0.1, deadline - time.monotonic()))
        assert_absent(work, runtime)
        payload = out.decode("utf-8")
        if process.returncode == 0 and payload.startswith("run-preflight: "):
            return payload.removeprefix("run-preflight: ").strip()
        # Honest compatibility classification: explicit local-command rejection,
        # not empty exit0/EOF, never silently accepted as a successful command.
        plain = (bytes(out) + bytes(err)).decode("utf-8", "replace").lower()
        if process.returncode != 0 and any(
            marker in plain
            for marker in (
                "unknown command",
                "command not found",
                "not supported in print mode",
                "not supported in headless",
                "not available in print mode",
            )
        ):
            return None
        raise Failure("native-headless-neither-command-result-nor-explicit-unsupported")
    finally:
        primary = sys.exception()
        cleanup_errors: list[JsonObject] = []
        selector.close()
        try:
            work.extend(owned_work(process, runtime))
        except (Failure, Unavailable, OSError, subprocess.SubprocessError) as error:
            cleanup_errors.append(
                cleanup_failure("headless-ownership-inventory", error)
            )
        try:
            stop_process(process)
        except (Failure, Unavailable, OSError, subprocess.SubprocessError) as error:
            cleanup_errors.append(cleanup_failure("headless-host-stop", error))
        try:
            cleanup_work(work, runtime)
        except (Failure, Unavailable, OSError, subprocess.SubprocessError) as error:
            cleanup_errors.append(cleanup_failure("headless-helper-cleanup", error))
        for pipe in (process.stdout, process.stderr):
            if pipe is not None:
                pipe.close()
        captures.append(
            {
                "command": text,
                "pid": process.pid,
                "exitCode": process.returncode,
                "stdout": out.decode("utf-8", "replace"),
                "stderr": err.decode("utf-8", "replace"),
                "ownedProcesses": work,
                "cleanupFailures": cleanup_errors,
            }
        )
        if cleanup_errors and primary is None:
            raise Failure("native-headless-cleanup-not-proven")


def execute(args: argparse.Namespace, report: JsonObject, root: Path) -> None:
    cwd, settings = context(args, root, report)
    claude = shutil.which("claude")
    if not claude or not shutil.which("bun"):
        raise Unavailable("installed-claude-and-bun-required")
    words = finite([claude, "--version"], root).decode().split()
    report["version"] = words[0] if words else None
    if not words or words[0] != "2.1.310":
        raise Unavailable("installed-version-needs-native-interface-review")
    runtime, production = prepare_artifact(args, report, root)
    source = Path(args.feature_dir).resolve()
    source_definition = (source / "EXTENSION.md").read_bytes()
    production_bytes = {
        record["path"]: (production / record["path"]).read_bytes()
        for record in verify_artifact_dir(production)["files"]
    }
    production_bytes[CONTENT_MANIFEST] = (production / CONTENT_MANIFEST).read_bytes()
    argv = [claude, "--settings", str(settings), "--plugin-dir", str(runtime)]
    env = dict(os.environ)
    hosts: list[NativeTTY] = []
    captures: list[JsonObject] = []
    all_work: list[JsonObject] = []
    report["headless"] = {"mode": "whole-native-command", "scenarios": []}
    report["_cleanupProven"] = False

    def passed(name: str) -> None:
        next(item for item in report["scenarios"] if item["name"] == name)["status"] = (
            "passed"
        )

    def host() -> NativeTTY:
        native = NativeTTY(argv, cwd, env)
        hosts.append(native)
        native.start()
        return native

    def fixture(name: str, barrier: bool = False) -> Any:
        return make_fixture(source, runtime, root / name, barrier=barrier)

    try:
        native = host()
        help_text = native.command(f"{COMMAND} help")
        for clause in (
            "checkisread-only",
            "Unknownquotaisnotcapacity",
            "ornativeadmitcommand",
        ):
            require(clause in help_text, "native-help-contract-missing")
        require(
            "notcampaignapproval" in help_text
            and "JSONstringssupportspaces" in help_text,
            "native-help-scope-missing",
        )
        first = fixture("selected project with spaces")
        validate_view(native.command(first.command("check")), first, "unknown")
        require(not list(first.checkpoint.iterdir()), "native-check-wrote-checkpoint")
        validate_view(
            native.command(first.command("probe")),
            first,
            "unknown",
            "terminal-receipt-unavailable",
        )
        passed("success")
        text = native.command(first.command("check", json=False))
        require(
            "Selectedconfig:" in text
            and "Selecteddeclaration:" in text
            and "Status:unknown" in text
            and "not signed or one-use authority, a spend guard, a sandbox, or study approval.".replace(
                " ", ""
            )
            in text,
            "native-complete-text-scope-missing",
        )
        # These paths contain only the shared renderer's allowed punctuation.
        # Retain quotes and every selected character, not just a status prefix.
        require(
            compact(json.dumps(str(first.config))) in text
            and compact(json.dumps(str(first.declaration))) in text,
            "native-text-selection-clipped",
        )
        passed("native-text")
        invalid = first.command("check").replace("check ", "admit ", 1)
        require(
            json_answer(native.command(invalid)) == {"error": "invalid-arguments"},
            "native-admit-command-not-refused",
        )
        missing = fixture("missing declaration")
        missing.declaration.unlink()
        validate_view(native.command(missing.command("check")), missing, "blocked")
        stale = fixture("stale identity source")
        stale.stale_identity()
        validate_view(native.command(stale.command("probe")), stale, "blocked")
        stale_source = fixture("stale owned bridge source", True)
        bridge_entry = Path(
            json.loads(stale_source.config.read_text())["bridgeArgv"][1]
        )
        require(
            bridge_entry.parent == stale_source.config.parent
            and bridge_entry.name == "bound-bridge.py",
            "native-owned-source-drift-target-invalid",
        )
        descriptor = os.open(bridge_entry, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(b"\n")
        validate_view(
            native.command(stale_source.command("probe")), stale_source, "blocked"
        )
        require(not stale_source.ready.exists(), "native-stale-source-started-bridge")
        expired = fixture("expired declaration")
        expired.expire_declaration()
        validate_view(native.command(expired.command("probe")), expired, "blocked")
        passed("failure")
        validate_view(native.command(first.command("check")), first, "unknown")
        passed("freshness")
        race = fixture("raced real bridge", True)
        mark = native.begin(race.command("probe"))
        work = wait_barrier(native, runtime, race)
        all_work.extend(work)
        race.stale_identity()
        race.release_bridge()
        validate_view(native.finish(mark), race, "blocked", "blocked")
        assert_absent(work, runtime)
        passed("changed-during-run")
        cancelled = fixture("cancelled real bridge", True)
        mark = native.begin(cancelled.command("probe"))
        work = wait_barrier(native, runtime, cancelled)
        all_work.extend(work)
        os.write(native.master, b"\x03")
        rendered = native.read(lambda raw: native.prompt_after_pending(raw), mark)
        answer = native.answer_text(rendered)
        if answer is not None:
            require(
                json_answer(answer).get("error") in {"cancelled", "context-changed"},
                "native-abort-published-result",
            )
        # Absence is checked before forced cleanup or releasing the barrier.
        assert_absent(work, runtime)
        require(
            not list(cancelled.checkpoint.iterdir()),
            "native-cancelled-probe-wrote-receipt",
        )
        native.pending = None
        fresh = fixture("fresh after cancellation")
        validate_view(native.command(fresh.command("check")), fresh, "unknown")
        ended = fixture("session disposal real bridge", True)
        native.begin(ended.command("probe"))
        work = wait_barrier(native, runtime, ended)
        all_work.extend(work)
        require("/exit" in native.discovered, "native-session-disposal-not-discovered")
        os.write(native.master, b"/exit\r")
        deadline = time.monotonic() + 12
        assert native.process is not None
        while native.process.poll() is None and time.monotonic() < deadline:
            native.pump(0.1)
        require(
            native.process.poll() == 0,
            "native-session-disposal-did-not-cleanly-overtake-active-command",
        )
        native.drain()
        final_screen = screen_text(native.rendered())
        echo = f"❯{compact(ended.command('probe'))}"
        position = final_screen.rfind(echo)
        require(position >= 0, "native-ended-command-evidence-lost")
        after_command = final_screen[position + len(echo) :]
        require(
            '"status":' not in after_command and "Status:" not in after_command,
            "native-ended-session-published-stale-result",
        )
        assert_absent(work, runtime)
        require(
            not list(ended.checkpoint.iterdir()), "native-ended-probe-wrote-receipt"
        )
        passed("cancellation")
        reopened = host()
        again = fixture("fresh reopened selection")
        validate_view(reopened.command(again.command("check")), again, "unknown")
        passed("reopen")
        # Headless compatibility is independent of interactive qualification.
        # Supported commands must be complete/exact; explicit unsupported is
        # reported honestly, never promoted to a model-prompt success.
        headless_fixture = fixture("headless selected project")
        headless_blocked = fixture("headless stale declaration")
        headless_blocked.stale_identity()
        for name, command in (
            ("help", f"{COMMAND} help"),
            ("check", headless_fixture.command("check")),
            ("probe", headless_fixture.command("probe")),
            (
                "invalid",
                headless_fixture.command("check").replace("check ", "admit ", 1),
            ),
            ("blocked", headless_blocked.command("probe")),
        ):
            payload = headless(argv, command, cwd, env, captures, runtime)
            if payload is None:
                report["headless"]["scenarios"].append(
                    {
                        "name": name,
                        "status": "unsupported",
                        "reasonCode": "host-explicitly-rejects-whole-local-command",
                    }
                )
            else:
                if name == "help":
                    require(
                        compact(payload) == help_text, "native-headless-help-mismatch"
                    )
                elif name == "check":
                    validate_view(payload, headless_fixture, "unknown")
                elif name == "probe":
                    validate_view(
                        payload,
                        headless_fixture,
                        "unknown",
                        "terminal-receipt-unavailable",
                    )
                elif name == "blocked":
                    validate_view(payload, headless_blocked, "blocked")
                else:
                    require(
                        json_answer(payload) == {"error": "invalid-arguments"},
                        "native-headless-invalid-not-refused",
                    )
                report["headless"]["scenarios"].append(
                    {"name": name, "status": "passed"}
                )
    finally:
        primary = sys.exception()
        cleanup_errors: list[JsonObject] = []
        host_processes: list[JsonObject] = []
        # Inventory before host shutdown, and await every owner even if one
        # cleanup fails. Keep exact identities and exception details private.
        for native in reversed(hosts):
            process = native.process
            inventory: JsonObject = {
                "pid": process.pid if process is not None else None,
                "argv": native.argv,
            }
            host_processes.append(inventory)
            try:
                table = process_table(runtime)
                if process is not None:
                    inventory["leaderBeforeCleanup"] = table.get(process.pid)
                    inventory["processesBeforeCleanup"] = [
                        item
                        for item in table.values()
                        if item["pgid"] == process.pid
                        or below(item["pid"], process.pid, table)
                    ]
                all_work.extend(owned_work(native, runtime, table))
            except (Failure, Unavailable, OSError, subprocess.SubprocessError) as error:
                cleanup_errors.append(
                    cleanup_failure("native-ownership-inventory", error)
                )
            try:
                native.stop(forced=True)
            except (Failure, Unavailable, OSError, subprocess.SubprocessError) as error:
                cleanup_errors.append(cleanup_failure("native-host-stop", error))
            try:
                table = process_table(runtime)
                if process is not None:
                    inventory["exitCodeAfterCleanup"] = process.poll()
                    inventory["processesAfterCleanup"] = [
                        item
                        for item in table.values()
                        if item["pgid"] == process.pid
                        or below(item["pid"], process.pid, table)
                    ]
            except (Failure, Unavailable, OSError, subprocess.SubprocessError) as error:
                cleanup_errors.append(
                    cleanup_failure("native-post-stop-inventory", error)
                )
        for capture in captures:
            all_work.extend(capture.get("ownedProcesses", []))
            cleanup_errors.extend(capture.get("cleanupFailures", []))
        try:
            cleanup_work(all_work, runtime)
        except (Failure, Unavailable, OSError, subprocess.SubprocessError) as error:
            cleanup_errors.append(cleanup_failure("native-helper-cleanup", error))
        remaining_helpers: list[JsonObject] = []
        try:
            remaining_helpers = [
                item
                for item in process_table(runtime).values()
                if str(runtime / "helpers/cli.js") in item["command"]
            ]
            require(not remaining_helpers, "native-helper-survived-cleanup")
        except (Failure, Unavailable, OSError, subprocess.SubprocessError) as error:
            cleanup_errors.append(cleanup_failure("native-helper-absence", error))
        capture_path = Path(args.report).with_suffix(".private.json")
        try:
            private_write(
                capture_path,
                json.dumps(
                    {
                        "terminalHex": [bytes(item.raw).hex() for item in hosts],
                        "answers": [item.answers for item in hosts],
                        "headless": captures,
                        "ownedProcesses": all_work,
                        "hostProcesses": host_processes,
                        "remainingHelpers": remaining_helpers,
                        "primaryFailure": (
                            {
                                "exceptionType": type(primary).__name__,
                                "message": str(primary),
                            }
                            if primary is not None
                            else None
                        ),
                        "cleanupFailures": cleanup_errors,
                    }
                ),
            )
            require(
                stat.S_IMODE(capture_path.stat().st_mode) == 0o600,
                "native-private-capture-mode-invalid",
            )
        except (Failure, Unavailable, OSError, subprocess.SubprocessError) as error:
            cleanup_errors.append(cleanup_failure("native-private-capture", error))
        clean = not cleanup_errors
        report["_cleanupProven"] = clean
        if not clean:
            report["cleanupReasonCode"] = "native-cleanup-not-proven"
            report["cleanupFailures"] = [
                {"phase": error["phase"], "reasonCode": error["reasonCode"]}
                for error in cleanup_errors
            ]
            if primary is None:
                raise Failure("native-cleanup-not-proven")
    require(
        (source / "EXTENSION.md").read_bytes() == source_definition,
        "native-definition-mutated",
    )
    verify_artifact_dir(production)
    for path, data in production_bytes.items():
        require(
            (production / path).read_bytes() == data
            and (runtime / path).read_bytes() == data,
            "native-artifact-content-mutated",
        )
    additions = {
        path.relative_to(runtime).as_posix()
        for path in runtime.rglob("*")
        if path.is_file()
    } - set(production_bytes)
    require(
        all(
            path.startswith(".claude-plugin/types/") or path == "tsconfig.json"
            for path in additions
        ),
        "native-feature-persisted-unexpected-state",
    )
    if "tsconfig.json" in additions:
        require(
            json.loads((runtime / "tsconfig.json").read_text())
            == {"extends": "./.claude-plugin/types/tsconfig.json"},
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
    }
    passed("private-output")
    require(
        all(item["status"] == "passed" for item in report["scenarios"]),
        "native-required-scenario-incomplete",
    )
    report["headless"]["status"] = (
        "supported"
        if all(item["status"] == "passed" for item in report["headless"]["scenarios"])
        else "explicitly-unsupported-or-partial"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature-dir", required=True)
    parser.add_argument("--artifact")
    parser.add_argument("--report", required=True)
    parser.add_argument(
        "--trusted-cwd",
        default=os.environ.get("ARMORY_CLAUDE_NATIVE_CWD", str(TRUSTED_CWD)),
    )
    parser.add_argument(
        "--settings",
        default=os.environ.get("ARMORY_CLAUDE_NATIVE_SETTINGS", str(APPROVED_SETTINGS)),
    )
    args = parser.parse_args()
    report_path = Path(args.report)
    companion = report_path.with_suffix(".private.json")
    if (
        not Path(args.feature_dir).is_absolute()
        or not report_path.is_absolute()
        or (args.artifact and not Path(args.artifact).is_absolute())
        or not report_path.parent.is_dir()
        or report_path.parent.is_symlink()
        or stat.S_IMODE(report_path.parent.stat().st_mode) != 0o700
        or os.path.lexists(report_path)
        or os.path.lexists(companion)
        or companion == report_path
    ):
        parser.error(
            "absolute source/artifact/report required; report parent must be private0700 and report/capture nonexistent"
        )
    os.umask(0o077)
    root = Path(
        tempfile.mkdtemp(prefix="armory-preflight-claude-", dir="/tmp")
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
        "usageInterpretation": "Discovered native commands and literal whole-command -p only; probe providerCalls0 is project-local evidence, not a universal host/network/spend meter.",
        "notExercised": [
            "installed-loader",
            "other host versions or operating systems",
            "hosted model capacity",
            "provider/network-call metering",
            "live-study authorization",
        ],
    }
    signals = (signal.SIGALRM, signal.SIGINT, signal.SIGTERM)
    old = {kind: signal.getsignal(kind) for kind in signals}

    def interrupted(signum: int, _frame: FrameType | None) -> None:
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
        report["status"], report["reasonCode"], code = (
            "passed",
            "all-real-interactive-scenarios-passed",
            0,
        )
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
                report["cleanupReasonCode"] = "owned-scratch-cleanup-failed"
                if report.get("status") == "passed" or "reasonCode" not in report:
                    report["reasonCode"] = "owned-scratch-cleanup-failed"
                report["status"], code = "failed", 1
        else:
            report["ownedScratchRetainedForUnprovenCleanup"] = True
            report["cleanupReasonCode"] = "native-cleanup-not-proven"
            if report.get("status") == "passed" or "reasonCode" not in report:
                report["reasonCode"] = "native-cleanup-not-proven"
            report["status"], code = "failed", 1
    if not re.fullmatch(r"[a-z0-9-]{1,160}", report.get("reasonCode", "")):
        report["reasonCode"] = "native-unsanitized-reason-rejected"
    try:
        private_write(report_path, json.dumps(report, sort_keys=True, indent=2) + "\n")
    except OSError:
        code = 3
        report["status"], report["reasonCode"] = (
            "unavailable",
            "private-report-write-unavailable",
        )
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
