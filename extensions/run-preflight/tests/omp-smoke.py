#!/usr/bin/env python3
"""Actual command-only OMP Run Preflight qualification, never a model prompt.

Normal HOME/default authentication and enforcement are retained. Read-only
installed-host discovery contains optional writers only. Unsupported controls,
trust requests and unavailable default models fail closed. Captures are private;
ordinary native transcripts, cache, logs and presence bookkeeping remain possible.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import selectors
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import FrameType
from typing import Any, BinaryIO, cast

from native_fixture import make_fixture

type JsonObject = dict[str, Any]
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
    "success": "read-only unknown check and explicit real Python-pass child; zero provider calls, no model receipt",
    "failure": "malformed, refused, stale and expired declarations produce no child or readiness",
    "reopen": "fresh actual host/session performs a new independently selected invocation",
    "freshness": "fresh authority is selection-bound; stale/expired authority refuses before dispatch",
    "changed-during-run": "identity changes behind a real bridge barrier and actual dispatch refuses before child",
    "cancellation": "awaited real session switch removes observed helper and nested bridge PID/groups and suppresses stale output",
    "private-output": "bounded captures remain mode0600 under mode0700; public report has no raw capture or admission",
    "native-text": "actual non-JSON command presents unknown quota, explicit scope and limitations",
}
COMMAND = MESSAGE = WIDGET = "armory-preflight"
COMMANDS = {COMMAND}
FEATURE = "run-preflight"
LIMIT = 480
STEP = 75
MAX_FRAME = 2 * 1024 * 1024
# Populated only from this driver's fresh owned fixtures before submission.
LITERALS: set[str] = {f"/{COMMAND} help", f"/{COMMAND} check {{}} --json"}


class Unavailable(Exception):
    pass


class Failure(Exception):
    pass


def require(value: object, code: str) -> None:
    if not value:
        raise Failure(code)


def private_write(path: Path, value: str | bytes) -> None:
    data = value.encode() if isinstance(value, str) else value
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)


def group_exists(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False


def stop_process(process: subprocess.Popen[bytes], graceful: bool = False) -> None:
    """Reap our direct child and bound its entire process group, not just its PID."""
    if graceful and process.stdin and not process.stdin.closed:
        process.stdin.close()
    if not graceful or process.poll() is None:
        if not graceful:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
    if group_exists(process.pid):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 5
        while group_exists(process.pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        if group_exists(process.pid):
            raise Failure("owned-process-group-survived")


def finite(argv: list[str], cwd: Path, code: str, timeout: float = STEP) -> bytes:
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    selector = selectors.DefaultSelector()
    stdout = bytearray()
    total = 0
    deadline = time.monotonic() + timeout
    try:
        for stream in (process.stdout, process.stderr):
            selector.register(cast(BinaryIO, stream), selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Unavailable(code + "-deadline")
            for key, _ in selector.select(remaining):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                total += len(chunk)
                if total > 4 * MAX_FRAME:
                    raise Unavailable(code + "-output-limit")
                if key.fileobj is process.stdout:
                    stdout.extend(chunk)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise Unavailable(code + "-deadline")
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as error:
            raise Unavailable(code + "-deadline") from error
        if process.returncode:
            raise Unavailable(code)
        return bytes(stdout)
    finally:
        try:
            stop_process(process)
        finally:
            selector.close()
            for stream in (process.stdout, process.stderr):
                cast(BinaryIO, stream).close()


def package_for(omp: str) -> tuple[Path, JsonObject]:
    for parent in Path(omp).resolve().parents:
        manifest = parent / "package.json"
        if manifest.is_file():
            try:
                value = json.loads(manifest.read_text())
            except (ValueError, OSError):
                continue
            if value.get("name") == "@oh-my-pi/pi-coding-agent":
                return parent, value
    raise Unavailable("installed-omp-package-source-unavailable")


# Runs read-only discovery in a separate Bun process, not an agent/model session.
# All effective settings are compared inside that process; secrets never leave it.
PREFLIGHT = r"""
try {
const pkg = process.argv[2], cwd = process.argv[3], overlay = process.argv[4];
const src = (p) => `${pkg}/src/${p}`;
await import(src("config/all-settings.ts"));
const { Settings } = await import(src("config/settings.ts"));
const { all } = await import(src("config/registry.ts"));
const { initializeWithSettings, loadCapability } = await import(src("discovery/index.ts"));
const { discoverExtensionPaths } = await import(src("extensibility/extensions/loader.ts"));
const { getExtensionNameFromPath } = await import(src("discovery/helpers.ts"));
const { cfgExtensions, cfgDisabledExtensions } = await import(src("extensibility/settings.ts"));
const { mcpCapability } = await import(src("capability/mcp.ts"));
const { loadAllMCPConfigs } = await import(src("mcp/config.ts"));
const allowed = new Set(["disabledExtensions", "memory.backend", "autolearn.enabled", "autolearn.autoContinue", "marketplace.autoUpdate"]);
const optional = ["archex-hook", "orca-agent-status", "orca-prefill", "orca-titlebar-spinner", "zz-laconic-runtime"];
const before = await Settings.loadReadOnly({cwd});
if (before.getStorage() !== null) throw Error("read-only-storage-opened");
const baseline = Object.fromEntries(all().map(s => [s.id, s.get(before)]));
const disabled = cfgDisabledExtensions.get(before);
let release = initializeWithSettings(before);
let original, originalMcp, originalConfigs;
try {
  original = await discoverExtensionPaths(cfgExtensions.get(before), cwd, disabled);
  originalMcp = await loadCapability(mcpCapability.id, {cwd});
  originalConfigs = await loadAllMCPConfigs(cwd);
} finally {release();}
if (originalMcp.warnings?.length) throw Error("mcp-inventory-incomplete");
if (original.some(p => !optional.includes(getExtensionNameFromPath(p)))) throw Error("unreviewed-ambient-extension");
const activeMcp = originalMcp.items.filter(s => s.enabled !== false);
const executableName = p => p.replaceAll("\\", "/").split("/").at(-1);
const isOptionalTessera = s => {
  if (s.name !== "tessera" || (s.transport ?? "stdio") !== "stdio" || !s.command || !s._source) return false;
  const name = executableName(s.command);
  const args = s.args ?? [];
  const pythonModule = ["python", "python3"].includes(name) && args.some((a, i) => a === "-m" && args[i + 1] === "tessera.cli");
  return name === "tessera" || pythonModule || (["uv", "uvx", "python", "python3"].includes(name) && args.some(a => a === "tessera" || a.startsWith("tessera==")));
};
if (activeMcp.some(s => !isOptionalTessera(s))) throw Error("unreviewed-ambient-mcp");
if (Object.entries(originalConfigs.configs).some(([name,s]) => s.enabled !== false && (name !== "tessera" || s.type !== "stdio"))) throw Error("unreviewed-ambient-mcp");
const activeTessera = activeMcp.length > 0 || originalConfigs.configs.tessera?.enabled !== false && originalConfigs.configs.tessera !== undefined;
if (activeTessera && !originalMcp.items.some(isOptionalTessera)) throw Error("unreviewed-ambient-mcp");
const mcpIds = activeTessera ? ["mcp:tessera"] : [];
await Bun.write(overlay, JSON.stringify({disabledExtensions:[...new Set([...disabled, ...optional.map(s => `extension-module:${s}`), ...mcpIds])],memory:{backend:"off"},autolearn:{enabled:false,autoContinue:false},marketplace:{autoUpdate:"off"}}));
const after = await Settings.loadReadOnly({cwd, configFiles:[overlay]});
if (after.getStorage() !== null) throw Error("read-only-storage-opened");
const effective = Object.fromEntries(all().map(s => [s.id, s.get(after)]));
for (const [id, value] of Object.entries(baseline)) {
  if (!allowed.has(id) && JSON.stringify(value) !== JSON.stringify(effective[id])) throw Error("nonoptional-setting-changed");
}
if (effective["memory.backend"] !== "off" || effective["autolearn.enabled"] !== false || effective["autolearn.autoContinue"] !== false || effective["marketplace.autoUpdate"] !== "off") throw Error("optional-writer-control-ineffective");
release = initializeWithSettings(after);
let remaining, remainingMcp, remainingConfigs;
try {
  remaining = await discoverExtensionPaths(cfgExtensions.get(after), cwd, cfgDisabledExtensions.get(after));
  remainingMcp = await loadCapability(mcpCapability.id, {cwd});
  remainingConfigs = await loadAllMCPConfigs(cwd);
} finally {release();}
if (remainingMcp.warnings?.length) throw Error("mcp-inventory-incomplete");
if (remaining.length !== 0) throw Error("ambient-extension-containment-ineffective");
if (remainingMcp.items.some(s => s.enabled !== false) || Object.values(remainingConfigs.configs).some(s => s.enabled !== false)) throw Error("mcp-containment-ineffective");
if (effective["telemetry.otlpExportEnabled"] && Object.entries(process.env).some(([k,v]) => k.startsWith("OTEL_EXPORTER_OTLP") && k.endsWith("ENDPOINT") && v)) throw Error("telemetry-export-not-contained");
console.log(JSON.stringify({storageOpened:false,optionalControlsVerified:true,enforcementSettingsUnchanged:true,ambientExtensions:remaining.length,activeMcp:0,optionalTesseraDisabled:cfgDisabledExtensions.get(after).includes("mcp:tessera")}));
} catch (error) {
  const safe = new Set(["read-only-storage-opened", "nonoptional-setting-changed", "optional-writer-control-ineffective", "unreviewed-ambient-extension", "ambient-extension-containment-ineffective", "telemetry-export-not-contained", "unreviewed-ambient-mcp", "mcp-inventory-incomplete", "mcp-containment-ineffective"]);
  console.log(JSON.stringify({blocked:safe.has(error?.message) ? error.message : "read-only-preflight-unavailable"}));
}
"""


class RPC:
    """Installed NDJSON RPC v1 only; no alternate host or replay-output path."""

    def __init__(
        self, argv: list[str], cwd: Path, report: JsonObject, session_root: Path
    ) -> None:
        self.selector = selectors.DefaultSelector()
        self.buffer = b""
        self.stderr_bytes = 0
        self.stdout_bytes = 0
        self.default_model_unavailable = False
        self.number = 0
        self.responses: dict[str, JsonObject] = {}
        self.prompt_results: dict[str, JsonObject] = {}
        self.requests: dict[str, str] = {}
        self.updates: list[JsonObject] = []
        self.messages: list[JsonObject] = []
        self.captures: list[JsonObject] = []
        self.ready: JsonObject | None = None
        self.report = report
        self.session: str | None = None
        self.sessions: list[str] = []
        self.cwd = cwd
        self.session_root = session_root
        self.closed = False
        self.command_registered = False
        try:
            self.process = subprocess.Popen(
                argv,
                cwd=cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                bufsize=0,
            )
        except BaseException:
            self.selector.close()
            raise
        try:
            self.selector.register(
                cast(BinaryIO, self.process.stdout), selectors.EVENT_READ, "out"
            )
            self.selector.register(
                cast(BinaryIO, self.process.stderr), selectors.EVENT_READ, "err"
            )
        except BaseException:
            try:
                stop_process(self.process)
                report["_cleanupProven"] = True
            finally:
                self.selector.close()
            raise

    def send(self, command: str, params: JsonObject | None = None) -> str:
        allowed = {
            "get_available_commands",
            "get_state",
            "get_session_stats",
            "new_session",
            "prompt",
        }
        require(command in allowed, "driver-refused-unknown-rpc-command")
        if command == "prompt":
            require(
                self.command_registered
                and isinstance(params, dict)
                and set(params) == {"message"}
                and isinstance(params.get("message"), str)
                and params["message"] in LITERALS,
                "driver-refused-nonliteral-or-undiscovered-prompt",
            )
        else:
            require(params is None, "driver-refused-unreviewed-rpc-parameters")
        self.number += 1
        identity = str(self.number)
        self.requests[identity] = command
        value = {"id": identity, "type": command, **(params or {})}
        cast(BinaryIO, self.process.stdin).write(
            (json.dumps(value, separators=(",", ":")) + "\n").encode()
        )
        cast(BinaryIO, self.process.stdin).flush()
        return identity

    def pump(self, deadline: float) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise Unavailable("native-rpc-deadline")
        events = self.selector.select(remaining)
        if not events:
            raise Unavailable("native-rpc-deadline")
        disconnected = False
        for key, _ in events:
            chunk = os.read(key.fd, 65536)
            if not chunk:
                self.selector.unregister(key.fileobj)
                if key.data == "out":
                    disconnected = True
                continue
            if key.data == "err":
                # Never retain potentially credential-bearing host diagnostics.
                self.stderr_bytes += len(chunk)
                if self.ready is None and (
                    b"No models available." in chunk
                    or b"Set an API key environment variable:" in chunk
                ):
                    self.default_model_unavailable = True
                if self.stderr_bytes > 4 * MAX_FRAME:
                    raise Unavailable("native-stderr-limit")
                continue
            self.stdout_bytes += len(chunk)
            require(self.stdout_bytes <= 8 * MAX_FRAME, "native-stdout-limit")
            self.buffer += chunk
            while b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                require(len(line) < MAX_FRAME, "native-frame-limit")
                if line.strip():
                    self.receive(json.loads(line))
            require(len(self.buffer) < MAX_FRAME, "native-frame-limit")
        if disconnected:
            raise Unavailable(
                "native-rpc-no-available-default-model"
                if self.default_model_unavailable
                else "native-rpc-disconnected-auth-trust-or-policy-may-block"
            )

    def receive(self, value: JsonObject) -> None:
        require(
            isinstance(value, dict) and isinstance(value.get("type"), str),
            "native-invalid-rpc-frame",
        )
        kind = value["type"]
        if kind == "response":
            identity = cast(str, value.get("id"))
            require(
                identity in self.requests
                and value.get("command") == self.requests[identity],
                "native-rpc-correlation-mismatch",
            )
            self.responses[identity] = value
            return
        if kind == "ready":
            require(
                self.ready is None and value.get("protocolVersion") == 1,
                "native-rpc-protocol-mismatch",
            )
            self.ready = value
            self.report["protocolVersion"] = 1
        elif kind == "extension_ui_request":
            method = value.get("method")
            # Native RPC widgets are one-way displays, not approval requests.
            if method == "setWidget":
                if value.get("widgetKey") == WIDGET:
                    self.updates.append(value)
                return
            if isinstance(method, str) and re.fullmatch(r"[A-Za-z_]{1,64}", method):
                self.report["blockedClientRequestMethod"] = method
            # A cancellation is the only client UI response permitted. Never
            # confirm trust/permissions or launch a terminal/browser/auth flow.
            if isinstance(value.get("id"), str):
                denial = {
                    "type": "extension_ui_response",
                    "id": value["id"],
                    "cancelled": True,
                }
                cast(BinaryIO, self.process.stdin).write(
                    (json.dumps(denial) + "\n").encode()
                )
                cast(BinaryIO, self.process.stdin).flush()
            raise Unavailable("native-client-request-blocked")
        elif kind == "extension_error":
            raise Failure("native-extension-registration-or-publication-failed")
        elif kind == "prompt_result":
            identity = cast(str, value.get("id"))
            require(
                self.requests.get(identity) == "prompt",
                "native-prompt-result-correlation-mismatch",
            )
            require(
                value.get("agentInvoked") is False
                and value.get("status") == "completed",
                "native-command-invoked-agent-or-failed",
            )
            self.prompt_results[identity] = value
        elif kind.startswith(
            ("agent_", "turn_", "tool_execution_", "subagent_", "btw_", "live_")
        ):
            raise Failure("unexpected-native-agent-or-tool-turn")
        elif kind in {"message_start", "message_update", "message_end"}:
            message = value.get("message", {})
            require(
                message.get("role") not in {"assistant", "toolResult"},
                "unexpected-native-model-message",
            )
            if (
                message.get("role") == "custom"
                and message.get("customType") == MESSAGE
                and kind == "message_end"
            ):
                require(
                    message.get("display") is True
                    and isinstance(message.get("content"), str),
                    "native-custom-text-not-displayable",
                )
                details = message.get("details")
                self.messages.append(
                    {
                        "text": message["content"],
                        "details": details if isinstance(details, dict) else None,
                    }
                )
        elif kind not in {
            "available_commands_update",
            "session_settled",
            "session_info_update",
            "config_update",
            "advisor_cost_changed",
        }:
            if re.fullmatch(r"[a-z_]{1,64}", kind):
                self.report["unreviewedEventType"] = kind
            raise Unavailable("unreviewed-native-rpc-event")
        self.updates.append(value)
        require(len(self.updates) <= 4096, "native-event-limit")

    def request(
        self, command: str, params: JsonObject | None = None
    ) -> tuple[str, JsonObject]:
        identity = self.send(command, params)
        deadline = time.monotonic() + STEP
        while identity not in self.responses:
            self.pump(deadline)
        response = self.responses.pop(identity)
        if response.get("success") is not True:
            raise Unavailable("native-rpc-rejected-" + command.replace("_", "-"))
        return identity, response.get("data") or {}

    def rpc(self, command: str, params: JsonObject | None = None) -> JsonObject:
        return self.request(command, params)[1]

    def start(self) -> None:
        deadline = time.monotonic() + STEP
        while self.ready is None:
            self.pump(deadline)
        self.bind_session()
        self.await_commands()
        self.observe_usage("startup")

    def bind_session(self) -> None:
        state = self.rpc("get_state")
        identity = state.get("sessionId")
        if not isinstance(identity, str) or not identity:
            raise Unavailable("native-session-identity-unavailable")
        require(
            state.get("isStreaming") is False
            and state.get("isCompacting") is False
            and state.get("queuedMessageCount") == 0
            and state.get("goal") is None,
            "native-session-not-model-idle",
        )
        require(
            not any(
                tool.get("name", "").startswith("mcp__")
                for tool in state.get("dumpTools", [])
            ),
            "runtime-mcp-containment-ineffective",
        )
        if state.get("sessionFile"):
            require(
                Path(state["sessionFile"]).resolve().is_relative_to(self.session_root),
                "native-session-storage-not-contained",
            )
        self.session = identity
        self.sessions.append(identity)

    def new_session(self) -> None:
        previous = self.session
        self.observe_usage("before-new-session")
        value = self.rpc("new_session")
        if value.get("cancelled") is not False:
            raise Unavailable("native-session-transition-blocked")
        self.bind_session()
        require(self.session != previous, "native-session-did-not-change")
        self.await_commands()

    def await_commands(self) -> None:
        value = self.rpc("get_available_commands")
        commands = value.get("commands", [])
        for name in COMMANDS:
            matching = [item for item in commands if item.get("name") == name]
            if len(matching) != 1 or matching[0].get("source") != "extension":
                raise Unavailable("literal-extension-commands-not-registered")
        self.command_registered = True

    def observe_usage(self, observation: str) -> None:
        stats = self.rpc("get_session_stats")
        fields = ("input", "output", "reasoning", "cacheRead", "cacheWrite", "total")
        raw_tokens = stats.get("tokens")
        tokens = None
        if isinstance(raw_tokens, dict):
            tokens = {key: raw_tokens[key] for key in fields if key in raw_tokens}
            require(
                all(type(value) is int and value == 0 for value in tokens.values()),
                "native-session-reported-model-tokens",
            )
        counts: dict[str, int] = {}
        for field in ("assistantMessages", "toolCalls", "toolResults"):
            if field in stats:
                require(
                    type(stats[field]) is int and stats[field] == 0,
                    "native-session-reported-model-work",
                )
                counts[field] = stats[field]
        self.report["usageObservations"].append(
            {
                "observation": observation,
                "tokens": tokens,
                "observability": "reported"
                if tokens is not None and all(key in tokens for key in fields)
                else "unknown",
                **counts,
            }
        )

    def prompt(self, text: str) -> JsonObject:
        """Submit one literal discovered command and return its single native answer."""
        require(text in LITERALS, "driver-refused-nonliteral-prompt")
        self.await_commands()
        start = len(self.messages)
        identity, ack = self.request("prompt", {"message": text})
        require(
            ack.get("agentInvoked") in (None, False),
            "native-command-acknowledged-agent-turn",
        )
        deadline = time.monotonic() + STEP
        if ack.get("agentInvoked") is not False:
            while identity not in self.prompt_results:
                self.pump(deadline)
            outcome = self.prompt_results.pop(identity)
            self.report.setdefault("localCommandObservations", []).append(
                {
                    "command": text.split()[0],
                    "agentInvoked": outcome["agentInvoked"],
                    "status": outcome["status"],
                    "sessionSettled": outcome.get("sessionSettled"),
                }
            )
        else:
            self.report.setdefault("localCommandObservations", []).append(
                {
                    "command": text.split()[0],
                    "agentInvoked": False,
                    "completion": "local-ack",
                }
            )
        while len(self.messages) <= start:
            self.pump(deadline)
        values = self.messages[start:]
        require(len(values) == 1, "native-command-published-more-than-once")
        self.captures.append({"command": text, "session": self.session, **values[0]})
        self.observe_usage(text.split()[0])
        return values[0]

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            stop_process(self.process, graceful=True)
        finally:
            self.selector.close()
            for stream in (self.process.stdout, self.process.stderr):
                cast(BinaryIO, stream).close()


def review_installed_host(omp: str, root: Path, report: JsonObject) -> Path:
    """Fail closed unless the installed sources still support the reviewed API."""
    package, metadata = package_for(omp)
    report["version"] = metadata.get("version")
    if report["version"] != "18.12.6":
        raise Unavailable("installed-version-needs-source-containment-review")
    native_rpc = (package / "src/modes/rpc/rpc-mode.ts").read_text()
    forwarder = (package / "src/modes/rpc/rpc-session-events.ts").read_text()
    mcp_capability = (package / "src/capability/mcp.ts").read_text()
    capability_filter = (package / "src/capability/index.ts").read_text()
    flags = (package / "src/cli/flag-tables.ts").read_text()
    if (
        'case "get_available_commands"' not in native_rpc
        or "watchAndReportPromptResult" not in native_rpc
        or "this.#output(frame)" not in forwarder
        or 'case "message_end"' not in forwarder
        or "toExtensionId: server => `mcp:${server.name}`" not in mcp_capability
        or "disabledExtensionIds.has(extensionId)" not in capability_filter
    ):
        raise Unavailable("native-rpc-routing-or-mcp-containment-source-unavailable")
    for flag in (
        "--mode",
        "--extension",
        "--no-title",
        "--no-prewalk",
        "--config",
        "--session-dir",
    ):
        if flag not in flags:
            raise Unavailable("native-launch-flag-unsupported")
    version_output = finite(
        [omp, "--version"], root, "installed-omp-version-unavailable"
    ).decode("utf-8")
    if not re.search(r"\b18\.12\.6\b", version_output):
        raise Unavailable("installed-omp-binary-version-mismatch")
    return package


def contain_ambient_writers(
    bun: str, package: Path, root: Path, cwd: Path, report: JsonObject
) -> Path:
    """Read-only inventory; disable only reviewed optional writers, never enforcement."""
    overlay, preflight = root / "overlay.json", root / "preflight.mjs"
    private_write(preflight, PREFLIGHT)
    # Resolve pi-utils through the actual installed package, not the checkout.
    (root / "node_modules").symlink_to(package.parent.parent)
    try:
        inventory = finite(
            [bun, str(preflight), str(package), str(cwd), str(overlay)],
            root,
            "read-only-effective-controls-or-startup-containment-unavailable",
        )
    finally:
        # The detached artifact must not inherit the inventory's resolution link.
        (root / "node_modules").unlink()
    try:
        observed = json.loads(inventory)
    except ValueError as error:
        raise Unavailable("read-only-preflight-result-invalid") from error
    if "blocked" in observed:
        raise Unavailable(observed["blocked"])
    require(
        observed.get("storageOpened") is False
        and observed.get("optionalControlsVerified") is True
        and observed.get("enforcementSettingsUnchanged") is True
        and observed.get("ambientExtensions") == 0
        and observed.get("activeMcp") == 0,
        "prelaunch-controls-not-effective",
    )
    os.chmod(overlay, 0o600)
    report["preflight"] = {
        "optionalControlsVerified": True,
        "enforcementSettingsUnchanged": True,
        "mcpContainment": "supported-disabledExtensions",
        "activeMcp": 0,
        "optionalTesseraDisabled": observed.get("optionalTesseraDisabled"),
        "ordinaryNativePresenceBookkeepingPossible": True,
        "catalogMetadataTrafficPossible": True,
    }
    return overlay


def passed(report: JsonObject, name: str) -> None:
    report["scenarios"][SCENARIOS.index(name)]["status"] = "passed"


def prepare_artifact(args: argparse.Namespace, report: JsonObject, root: Path) -> Path:
    """Bind the complete production artifact to a fresh canonical-source assembly."""
    checkout = Path(__file__).resolve().parents[3]
    if str(checkout) not in sys.path:
        sys.path.insert(0, str(checkout))
    from scripts import build_extensions as production

    feature = Path(args.feature_dir).resolve(strict=True)
    require(
        feature == checkout / "extensions" / FEATURE,
        "production-source-feature-path-mismatch",
    )
    try:
        metadata = production.load_metadata(feature)
        require(
            metadata.name == FEATURE and "omp" in metadata.host_entries,
            "production-source-feature-or-host-mismatch",
        )
        expected = production.build_feature(feature, root / "source-build")["omp"]
        supplied = Path(args.artifact) if args.artifact else expected
        manifest = production.verify_artifact_dir(supplied)
        expected_manifest = production.verify_artifact_dir(expected)
        require(
            manifest == expected_manifest, "production-artifact-source-content-mismatch"
        )
        require(
            (supplied / production.CONTENT_MANIFEST).read_bytes()
            == (expected / production.CONTENT_MANIFEST).read_bytes(),
            "production-artifact-source-manifest-mismatch",
        )
        require(
            manifest.get("host") == "omp" and manifest.get("feature") == FEATURE,
            "production-artifact-feature-host-mismatch",
        )
        # Launch only an owned detached byte-for-byte copy, never the caller's
        # artifact or an in-place modified source/artifact tree.
        detached = root / "runtime"
        shutil.copytree(supplied, detached)
        require(
            production.verify_artifact_dir(detached) == manifest,
            "detached-artifact-content-mismatch",
        )
        report["artifact"] = {
            "mode": "supplied-production" if args.artifact else "built-production",
            "contentManifestSha256": hashlib.sha256(
                (supplied / production.CONTENT_MANIFEST).read_bytes()
            ).hexdigest(),
            "sourceDefinitionSha256": hashlib.sha256(
                (feature / production.EXTENSION_TYPE.definition_file).read_bytes()
            ).hexdigest(),
            "completeCanonicalSourceBinding": True,
            "detachedCopyVerified": True,
            "entry": production.OMP_ROOT_ENTRY,
            "feature": FEATURE,
            "host": "omp",
        }
        return detached / production.OMP_ROOT_ENTRY
    except production.ToolUnavailableError as error:
        raise Unavailable("production-artifact-build-tool-unavailable") from error
    except production.BuildError as error:
        raise Failure("production-artifact-validation-or-build-failed") from error


def process_table(cwd: Path) -> dict[int, JsonObject]:
    raw = finite(
        ["/bin/ps", "-axo", "pid=,ppid=,pgid=,command="],
        cwd,
        "owned-process-inventory-unavailable",
        timeout=5,
    ).decode("utf-8", "replace")
    table: dict[int, JsonObject] = {}
    for line in raw.splitlines():
        fields = line.strip().split(None, 3)
        if len(fields) == 4 and all(field.isdigit() for field in fields[:3]):
            pid, ppid, pgid = map(int, fields[:3])
            table[pid] = {"pid": pid, "ppid": ppid, "pgid": pgid, "command": fields[3]}
    return table


def descends(pid: int, ancestor: int, table: dict[int, JsonObject]) -> bool:
    seen: set[int] = set()
    while pid in table and pid not in seen:
        if pid == ancestor:
            return True
        seen.add(pid)
        pid = table[pid]["ppid"]
    return False


def allow_fixture(fixture: Any) -> None:
    for action in ("check", "probe"):
        for json_mode in (True, False):
            LITERALS.add(fixture.command(action, json_mode))


def native_view(
    answer: JsonObject, host: RPC, fixture: Any, *, json_mode: bool = True
) -> JsonObject:
    details = answer.get("details")
    if not isinstance(details, dict):
        raise Failure("native-projected-details-unavailable")
    correlation = details.get("correlation")
    correlated_cwd = correlation.get("cwd") if isinstance(correlation, dict) else None
    cwd_matches = False
    if isinstance(correlated_cwd, str) and Path(correlated_cwd).is_absolute():
        try:
            # macOS can report /tmp for the same /private/tmp launch directory.
            # Bind the actual directory, not the host's spelling of its path.
            cwd_matches = Path(correlated_cwd).samefile(host.cwd)
        except (OSError, ValueError):
            pass
    require(
        cwd_matches
        and correlation
        == {"host": "omp", "sessionId": host.session, "cwd": correlated_cwd},
        "native-stale-session-or-cwd-correlation",
    )
    view = details.get("view")
    if not isinstance(view, dict):
        raise Failure("native-projected-view-unavailable")
    require(
        set(view)
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
        },
        "native-private-or-missing-fields",
    )
    require(
        view["schemaVersion"] == 1
        and view["coreVersion"] == "1.0.0"
        and view["admitted"] is False,
        "native-view-version-or-admission-invalid",
    )
    require(
        view["selection"]
        == {"config": str(fixture.config), "declaration": str(fixture.declaration)},
        "native-selection-unbound",
    )
    require(
        view["status"] in {"unknown", "blocked", "ready"}
        and isinstance(view["reasons"], list)
        and view["reasons"],
        "native-readiness-report-invalid",
    )
    require(
        isinstance(view["limitations"], list) and len(view["limitations"]) >= 2,
        "native-limitations-missing",
    )
    if view["quota"] is not None:
        require(
            set(view["quota"]) == {"status", "observedAt", "expiresAt"},
            "native-raw-quota-disclosed",
        )
    if view["run"] is not None:
        require(
            set(view["run"])
            == {
                "id",
                "purpose",
                "provider",
                "identityKind",
                "profile",
                "cell",
                "expiresAt",
            },
            "native-raw-run-disclosed",
        )
        require(
            view["run"]["provider"] == "synthetic-local"
            and view["run"]["identityKind"] == "synthetic-local",
            "native-declared-provider-or-identity-kind-invalid",
        )
    if json_mode:
        require(
            json.loads(answer["text"]) == view,
            "native-json-differs-from-projected-details",
        )
    else:
        require(not answer["text"].lstrip().startswith("{"), "native-text-is-json-only")
        require(
            "Selected config:" in answer["text"]
            and "Selected declaration:" in answer["text"],
            "native-text-selection-missing",
        )
        require(
            str(fixture.config) in answer["text"]
            and str(fixture.declaration) in answer["text"],
            "native-text-selection-unbound",
        )
    rendered = json.dumps(answer)
    for forbidden in (
        "accountFingerprint",
        "synthetic-no-account",
        "bridgeArgv",
        "recordSha256",
        "identityFile",
        "factsSha256",
    ):
        require(forbidden not in rendered, "native-private-admission-field-disclosed")
    # The real project deliberately has no terminal receipt for a Python-pass child.
    require(
        not list(fixture.checkpoint.rglob("*.json")),
        "synthetic-probe-wrote-derived-receipt",
    )
    return cast(JsonObject, view)


def unknown_check(host: RPC, fixture: Any, json_mode: bool = True) -> JsonObject:
    answer = host.prompt(fixture.command("check", json_mode))
    view = native_view(answer, host, fixture, json_mode=json_mode)
    require(
        view["status"] == "unknown"
        and view["admitted"] is False
        and view["probe"] is None,
        "normal-check-not-read-only-unknown",
    )
    require(
        isinstance(view["quota"], dict) and view["quota"]["status"] == "unknown",
        "normal-check-invented-quota",
    )
    require(
        not fixture.pid.exists() and not fixture.ready.exists(),
        "normal-check-started-project-bridge",
    )
    if not json_mode:
        lowered = answer["text"].lower()
        for term in (
            "unknown",
            "quota",
            "caller",
            "synthetic",
            "spend",
            "declared provider:",
            "profile:",
            "not an account probe",
        ):
            require(term in lowered, "native-text-scope-or-limitation-missing")
    return view


def blocked_probe(host: RPC, fixture: Any) -> None:
    view = native_view(host.prompt(fixture.command("probe")), host, fixture)
    require(
        view["status"] == "blocked"
        and view["probe"] is None
        and view["admitted"] is False,
        "invalid-authority-not-refused-before-bridge",
    )
    require(
        not fixture.pid.exists() and not fixture.ready.exists(),
        "invalid-authority-started-bridge",
    )


def complete_pending(host: RPC, identity: str) -> None:
    deadline = time.monotonic() + STEP
    while identity not in host.responses:
        host.pump(deadline)
    response = host.responses.pop(identity)
    require(response.get("success") is True, "native-pending-command-failed")
    ack = response.get("data") or {}
    require(
        ack.get("agentInvoked") in (None, False), "native-pending-command-invoked-agent"
    )
    if ack.get("agentInvoked") is not False:
        while identity not in host.prompt_results:
            host.pump(deadline)
        host.prompt_results.pop(identity)


def barrier_work(host: RPC, entry: Path, fixture: Any) -> list[JsonObject]:
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        if fixture.ready.exists() and fixture.pid.exists():
            break
        if host.process.poll() is not None:
            raise Failure("native-host-exited-before-owned-bridge")
        time.sleep(0.02)
    else:
        raise Unavailable("actual-project-barrier-not-observed")
    bridge_pid = int(fixture.pid.read_text())
    table = process_table(host.cwd)
    owner = table.get(host.process.pid)
    if owner is None:
        raise Failure("native-host-owner-disappeared")
    owner_args = shlex.split(owner["command"])
    require(
        "--extension" in owner_args
        and owner_args[owner_args.index("--extension") + 1] == str(entry),
        "native-host-artifact-argv-mismatch",
    )
    bridge = table.get(bridge_pid)
    if bridge is None or not descends(bridge_pid, host.process.pid, table):
        raise Failure("project-bridge-not-owned-by-native-host")
    helper_pid = bridge["ppid"]
    helper = table.get(helper_pid)
    if helper is None or not descends(helper_pid, host.process.pid, table):
        raise Failure("installed-helper-not-owned-by-native-host")
    argv = shlex.split(helper["command"])
    expected = [
        str(entry.parent / "helpers" / "cli.js"),
        "probe",
        "--config",
        str(fixture.config),
        "--declaration",
        str(fixture.declaration),
        "--format",
        "json",
    ]
    require(
        len(argv) >= 2 and Path(argv[0]).name == "bun" and argv[1:] == expected,
        "native-helper-not-literal-own-bun-argv",
    )
    for item in (helper, bridge):
        require(
            item["pgid"] == item["pid"] and group_exists(item["pid"]),
            "owned-work-not-detached-group",
        )
    return [helper, bridge]


def work_absent(work: list[JsonObject], cwd: Path) -> None:
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        table = process_table(cwd)
        if not any(item["pid"] in table or group_exists(item["pgid"]) for item in work):
            return
        time.sleep(0.03)
    raise Failure("owned-helper-or-bridge-pid-group-survived")


def emergency_cleanup(work: list[JsonObject], cwd: Path) -> None:
    # TERM helpers first, allowing their normal nested bridge cleanup to finish.
    for kind in (signal.SIGTERM, signal.SIGKILL):
        table = process_table(cwd)
        for item in work:
            live = table.get(item["pid"])
            if live is None:
                require(
                    not group_exists(item["pgid"]),
                    "owned-group-without-confirmed-leader",
                )
                continue
            require(
                all(live[key] == item[key] for key in ("pid", "pgid", "command")),
                "owned-process-identity-changed",
            )
            os.killpg(item["pgid"], kind)
        time.sleep(1 if kind == signal.SIGTERM else 0.1)
    work_absent(work, cwd)


def dispose(host: RPC) -> None:
    if host.process.stdin and not host.process.stdin.closed:
        host.process.stdin.close()
    try:
        host.process.wait(timeout=12)
    except subprocess.TimeoutExpired as error:
        raise Failure("native-supported-shutdown-not-finite") from error
    require(
        host.process.returncode == 0 and not group_exists(host.process.pid),
        "native-supported-shutdown-failed",
    )
    host.close()


def execute(args: argparse.Namespace, report: JsonObject, root: Path) -> None:
    if sys.version_info < (3, 12) or os.name != "posix":
        raise Unavailable("python312-posix-required")
    omp, bun = (shutil.which(name) for name in ("omp", "bun"))
    if omp is None or bun is None:
        raise Unavailable("installed-omp-bun-required")
    entry = prepare_artifact(args, report, root)
    feature = Path(args.feature_dir).resolve(strict=True)
    package = review_installed_host(omp, root, report)
    cwd = root / "workspace"
    cwd.mkdir(mode=0o700)
    sessions = root / "sessions"
    sessions.mkdir(mode=0o700)
    overlay = contain_ambient_writers(bun, package, root, cwd, report)
    hosts: list[RPC] = []
    owned: list[JsonObject] = []
    report["_cleanupProven"] = False

    def fresh(name: str, *, barrier: bool = False) -> Any:
        value = make_fixture(feature, entry.parent, root / name, barrier=barrier)
        allow_fixture(value)
        return value

    def launch() -> RPC:
        host = RPC(
            [
                omp,
                "--mode",
                "rpc",
                "--extension",
                str(entry),
                "--no-title",
                "--no-prewalk",
                "--config",
                str(overlay),
                "--session-dir",
                str(sessions),
            ],
            cwd,
            report,
            sessions,
        )
        hosts.append(host)
        host.start()
        return host

    try:
        host = launch()
        help_answer = host.prompt(f"/{COMMAND} help")
        require(
            help_answer.get("details", {}).get("help") is True
            and "Run Preflight" in help_answer["text"],
            "native-help-unavailable",
        )
        normal = fresh("normal-check", barrier=True)
        unknown_check(host, normal)
        positive = fresh("explicit-one-child")
        positive_view = native_view(
            host.prompt(positive.command("probe")), host, positive
        )
        probe = positive_view["probe"]
        require(
            positive_view["status"] == "unknown"
            and isinstance(probe, dict)
            and probe.get("status") == "terminal-receipt-unavailable"
            and probe.get("managedSpawns") == 1
            and probe.get("providerCalls") == 0,
            "real-synthetic-child-result-unavailable",
        )
        passed(report, "success")

        invalid = host.prompt(f"/{COMMAND} check {{}} --json")
        require(
            json.loads(invalid["text"]) == {"error": "invalid-arguments"}
            and invalid.get("details", {}).get("view") is None,
            "malformed-selection-not-refused",
        )
        malformed = fresh("malformed-declaration", barrier=True)
        malformed.declaration.write_text("{not-json", encoding="utf-8")
        blocked_probe(host, malformed)
        refused = fresh("refused-authority", barrier=True)
        declaration = json.loads(refused.declaration.read_text())
        declaration["authorizations"] = []
        refused.declaration.write_text(json.dumps(declaration) + "\n", encoding="utf-8")
        blocked_probe(host, refused)
        stale = fresh("stale-identity", barrier=True)
        stale.stale_identity()
        blocked_probe(host, stale)
        expired = fresh("expired-declaration", barrier=True)
        expired.expire_declaration()
        blocked_probe(host, expired)
        passed(report, "failure")
        passed(report, "freshness")

        text_fixture = fresh("native-text", barrier=True)
        unknown_check(host, text_fixture, False)
        passed(report, "native-text")

        race = fresh("identity-race", barrier=True)
        start = len(host.messages)
        identity = host.send("prompt", {"message": race.command("probe")})
        race_work = barrier_work(host, entry, race)
        owned.extend(race_work)
        race.stale_identity()
        race.release_bridge()
        complete_pending(host, identity)
        deadline = time.monotonic() + STEP
        while len(host.messages) <= start:
            host.pump(deadline)
        require(len(host.messages) == start + 1, "native-race-published-more-than-once")
        race_answer = host.messages[-1]
        host.captures.append(
            {"command": race.command("probe"), "session": host.session, **race_answer}
        )
        race_view = native_view(race_answer, host, race)
        raced_probe = race_view["probe"]
        require(
            race_view["status"] == "blocked"
            and isinstance(raced_probe, dict)
            and raced_probe.get("status") == "blocked"
            and raced_probe.get("managedSpawns") == 0
            and raced_probe.get("providerCalls") == 0,
            "real-bridge-race-not-refused-before-child",
        )
        work_absent(race_work, cwd)
        passed(report, "changed-during-run")

        cancelled = fresh("session-cancellation", barrier=True)
        start = len(host.messages)
        old_session = host.session
        identity = host.send("prompt", {"message": cancelled.command("probe")})
        cancelled_work = barrier_work(host, entry, cancelled)
        owned.extend(cancelled_work)
        host.new_session()
        work_absent(cancelled_work, cwd)
        complete_pending(host, identity)
        help_answer = host.prompt(f"/{COMMAND} help")
        require(
            help_answer.get("details", {}).get("help") is True
            and len(host.messages) == start + 1,
            "native-stale-publication-after-cancellation",
        )
        require(
            old_session != host.session and not cancelled.release.exists(),
            "native-session-transition-not-real-cancellation",
        )
        subsequent = fresh("fresh-after-cancel", barrier=True)
        unknown_check(host, subsequent)
        host.observe_usage("after-session-switch-and-fresh-check")
        passed(report, "cancellation")
        dispose(host)

        reopened = launch()
        require(
            reopened.session not in host.sessions, "native-reopened-host-session-reused"
        )
        recheck = fresh("fresh-reopened-host", barrier=True)
        unknown_check(reopened, recheck)
        reopened.observe_usage("fresh-reopened-host")
        dispose(reopened)
        passed(report, "reopen")
        report["execution"] = {
            "normalCheckUnknown": True,
            "explicitPythonPassChildren": 1,
            "raceRefusedBeforeChild": True,
            "ownedPidAndGroupsAbsent": True,
            "stalePublicationSuppressed": True,
            "zeroModelTurnsObserved": True,
            "projectBridgeProviderCalls": 0,
            "noTerminalModelReceiptClaimed": True,
            "mechanism": "awaited-native-session-switch",
        }
    finally:
        cleanup_ok = True
        for host in hosts:
            if host.process.poll() is None:
                try:
                    table = process_table(cwd)
                    helpers = []
                    for item in table.values():
                        if not descends(item["pid"], host.process.pid, table):
                            continue
                        argv = shlex.split(item["command"])
                        if (
                            len(argv) >= 2
                            and Path(argv[0]).name == "bun"
                            and argv[1] == str(entry.parent / "helpers" / "cli.js")
                        ):
                            helpers.append(item["pid"])
                    for item in table.values():
                        if (
                            item["pid"] == item["pgid"]
                            and any(
                                descends(item["pid"], helper, table)
                                for helper in helpers
                            )
                            and not any(
                                previous["pid"] == item["pid"] for previous in owned
                            )
                        ):
                            owned.append(item)
                    # Prefer the genuine awaited lifecycle before any fallback
                    # signal, including failures before a barrier became ready.
                    if host.command_registered:
                        try:
                            host.new_session()
                        except (Unavailable, Failure, OSError, ValueError):
                            # No approval is sent. Captured, still-proven groups
                            # are terminated below; this cannot turn a failed
                            # scenario into a pass.
                            pass
                except (Unavailable, Failure, OSError, ValueError):
                    cleanup_ok = False
        try:
            emergency_cleanup(owned, cwd)
        except (Unavailable, Failure, OSError, ValueError):
            cleanup_ok = False
        for host in hosts:
            try:
                host.close()
            except (Unavailable, Failure, OSError, ValueError):
                cleanup_ok = False
        try:
            work_absent(owned, cwd)
            require(
                all(
                    host.process.poll() is not None
                    and not group_exists(host.process.pid)
                    for host in hosts
                ),
                "native-host-owner-survived-cleanup",
            )
        except (Unavailable, Failure, OSError, ValueError):
            cleanup_ok = False
        report["_captures"] = [capture for host in hosts for capture in host.captures]
        report["_processCaptures"] = owned
        report["_cleanupProven"] = cleanup_ok
        require(cleanup_ok, "native-owned-cleanup-not-proven")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature-dir", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--artifact")
    args = parser.parse_args()
    paths = [Path(args.feature_dir), Path(args.report)] + (
        [Path(args.artifact)] if args.artifact else []
    )
    if not all(path.is_absolute() for path in paths):
        parser.error("all selected paths must be absolute")
    report_path = Path(args.report)
    companion = report_path.with_suffix(".private.json")
    if (
        not report_path.parent.is_dir()
        or report_path.parent.is_symlink()
        or stat.S_IMODE(report_path.parent.stat().st_mode) != 0o700
        or any(path.exists() or path.is_symlink() for path in (report_path, companion))
    ):
        parser.error("unused report paths under a private0700 parent are required")
    os.umask(0o077)
    report: JsonObject = {
        "schemaVersion": 1,
        "host": "omp",
        "mode": "rpc",
        "version": None,
        "status": "unavailable",
        "driverSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scenarios": [
            {"name": name, "status": "not-run", "assertion": ASSERTIONS[name]}
            for name in SCENARIOS
        ],
        "usageObservations": [],
        "authAndPolicy": "Normal HOME/default authentication; genuine enforcement; no trust auto-approval, account changes or ordinary model prompts.",
        "ordinaryHostWritesPossible": [
            "session transcripts",
            "logs",
            "cache",
            "presence bookkeeping",
        ],
        "notExercised": [
            "OMP TUI",
            "other versions/platforms",
            "model/provider turns",
            "network-call metering",
            "study authority",
        ],
    }
    root = Path(tempfile.mkdtemp(prefix="armory-preflight-omp-", dir="/tmp")).resolve()
    os.chmod(root, 0o700)
    signals = (signal.SIGALRM, signal.SIGINT, signal.SIGTERM)
    previous = {kind: signal.getsignal(kind) for kind in signals}

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
        require(
            all(
                item["status"] == "passed"
                for item in report["scenarios"]
                if item["name"] != "private-output"
            ),
            "native-required-scenario-incomplete",
        )
        report["status"] = "passed"
        report["reasonCode"] = "all-real-scenarios-passed"
        code = 0
    except Unavailable as error:
        report["reasonCode"] = str(error)
    except Failure as error:
        report["status"] = "failed"
        report["reasonCode"] = str(error)
        code = 1
    except (OSError, ValueError, LookupError, TypeError, subprocess.SubprocessError):
        report["reasonCode"] = "native-prerequisite-or-protocol-unavailable"
    finally:
        signal.alarm(0)
        for kind, handler in previous.items():
            signal.signal(kind, handler)
        captures = report.pop("_captures", [])
        process_captures = report.pop("_processCaptures", [])
        cleanup_proven = report.pop("_cleanupProven", True)
        try:
            raw = json.dumps(
                {"captures": captures, "ownedProcessEvidence": process_captures},
                ensure_ascii=True,
            )
            require(len(raw.encode()) <= 32 * MAX_FRAME, "native-private-capture-limit")
            private_write(companion, raw + "\n")
            require(
                stat.S_IMODE(companion.stat().st_mode) == 0o600
                and stat.S_IMODE(root.stat().st_mode) == 0o700,
                "native-private-output-mode-invalid",
            )
            if code == 0:
                require(cleanup_proven, "owned-cleanup-not-proven")
                passed(report, "private-output")
            report["privateOutput"] = {
                "companionMode": "0600",
                "parentMode": "0700",
                "rawCapturesPublished": False,
                "boundedCapture": True,
                "ownedCleanupProven": cleanup_proven,
                "featurePersistence": "none; normal host-owned transcripts may contain displayed answers",
            }
        except (OSError, Failure):
            report["status"] = "failed"
            report["reasonCode"] = "native-private-output-or-cleanup-failed"
            code = 1
        report["scratchRetained"] = not cleanup_proven
        if cleanup_proven:
            try:
                shutil.rmtree(root)
            except OSError:
                report["status"] = "failed"
                report["reasonCode"] = "owned-scratch-cleanup-failed"
                report["scratchRetained"] = True
                code = 1
        reason = report.get("reasonCode")
        if not isinstance(reason, str) or not re.fullmatch(
            r"[a-z][a-z0-9-]{0,63}", reason
        ):
            report["reasonCode"] = "native-prerequisite-or-protocol-unavailable"
        private_write(report_path, json.dumps(report, indent=2, sort_keys=True) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
