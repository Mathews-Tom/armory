#!/usr/bin/env python3
"""Finite, authenticated installed-OMP RPC exercise; never provisions credentials.

Exit 0: all native scenarios passed; 1: demonstrated regression; 2: arguments;
3: unavailable prerequisite. Only fixed, advertised local commands are submitted.
The driver owns its detached bundle, synthetic repository, gates and host group.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import selectors
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from types import FrameType
from typing import Any, BinaryIO, cast

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
COMMANDS = {"armory-verify", "armory-evidence"}
LIMIT = 240
STEP = 25
MAX_FRAME = 1024 * 1024


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
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        if len(stdout) + len(stderr) > 4 * MAX_FRAME:
            raise Unavailable(code + "-output-limit")
        if process.returncode:
            raise Unavailable(code)
        return stdout
    except subprocess.TimeoutExpired as error:
        raise Unavailable(code + "-deadline") from error
    finally:
        stop_process(process)


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

# Real synthetic gate executable. Readiness is an authenticated Unix-socket
# handshake, never a sleep or a file-existence loop. The root reaps its child.
GATE = r"""
import json, os, signal, socket, subprocess, sys
mode, endpoint, token, secret, lifecycle = sys.argv[1:]
child = None

def terminate(signum, frame):
    global child
    if child is not None:
        try: child.terminate()
        except ProcessLookupError: pass
        try: child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            child.kill(); child.wait(timeout=2)
    raise SystemExit(128 + signum)

signal.signal(signal.SIGTERM, terminate)
if mode != "descendant":
    fd = os.open(lifecycle, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump({"pid":os.getpid(),"pgid":os.getpgrp()}, stream)
        stream.flush()
        os.fsync(stream.fileno())
if mode == "failure":
    print(secret, flush=True)
    raise SystemExit(7)
if mode == "success":
    print(secret, flush=True)
    raise SystemExit(0)
if mode == "cancellation":
    child = subprocess.Popen([sys.executable, "-I", "-S", __file__, "descendant", endpoint, token, secret, lifecycle], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
channel = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
channel.settimeout(30)
channel.connect(endpoint)
print(secret, flush=True)
channel.sendall((json.dumps({"token":token,"role":mode,"pid":os.getpid(),"pgid":os.getpgrp()})+"\n").encode())
value = channel.recv(32)
if mode == "changed-during-run" and value == b"continue\n":
    raise SystemExit(0)
raise SystemExit(9)
"""


class Barrier:
    def __init__(self, root: Path, token: str) -> None:
        self.path = root / "ready.sock"
        self.token = token
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(str(self.path))
        self.listener.listen(3)
        self.listener.settimeout(STEP)
        self.channels: list[socket.socket] = []
        self.pids: dict[str, int] = {}
        self.closed = False

    def ready(self, roles: set[str]) -> dict[str, tuple[JsonObject, socket.socket]]:
        deadline = time.monotonic() + STEP
        values: dict[str, tuple[JsonObject, socket.socket]] = {}
        for _ in roles:
            self.listener.settimeout(max(0.01, deadline - time.monotonic()))
            connection, _ = self.listener.accept()
            self.channels.append(connection)
            connection.settimeout(max(0.01, deadline - time.monotonic()))
            data = b""
            while not data.endswith(b"\n") and len(data) <= 1024:
                chunk = connection.recv(1024)
                require(bool(chunk), "gate-readiness-disconnected")
                data += chunk
            value = json.loads(data)
            require(value.get("token") == self.token, "gate-readiness-token")
            role = value.get("role")
            require(role in roles and role not in values, "gate-readiness-role")
            pid = value.get("pid")
            require(isinstance(pid, int) and pid > 1, "gate-readiness-pid")
            # Track immediately, including on subsequent assertion failure.
            self.pids[role] = pid
            require(
                os.getpgid(pid) == value.get("pgid"), "gate-readiness-process-group"
            )
            values[role] = (value, connection)
        return values

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for channel in self.channels:
            channel.close()
        self.listener.close()
        self.path.unlink(missing_ok=True)


class RPC:
    """Installed NDJSON RPC v1 only; no alternate host or replay-output path."""

    def __init__(
        self, argv: list[str], cwd: Path, report: JsonObject, session_root: Path
    ) -> None:
        self.selector = selectors.DefaultSelector()
        self.buffer = b""
        self.stderr_bytes = 0
        self.number = 0
        self.responses: dict[str, JsonObject] = {}
        self.prompt_results: dict[str, JsonObject] = {}
        self.requests: dict[str, str] = {}
        self.updates: list[JsonObject] = []
        self.messages: list[JsonObject] = []
        self.ready: JsonObject | None = None
        self.report = report
        self.session: str | None = None
        self.sessions: list[str] = []
        self.cwd = cwd
        self.session_root = session_root
        self.closed = False
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
        report["_cleanupProven"] = False
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
            "abort",
        }
        require(command in allowed, "driver-refused-unknown-rpc-command")
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
        for key, _ in events:
            chunk = os.read(key.fd, 65536)
            if not chunk:
                self.selector.unregister(key.fileobj)
                if key.data == "out":
                    raise Unavailable(
                        "native-rpc-disconnected-auth-trust-or-policy-may-block"
                    )
                continue
            if key.data == "err":
                # Never retain potentially credential-bearing host diagnostics.
                self.stderr_bytes += len(chunk)
                if self.stderr_bytes > 4 * MAX_FRAME:
                    raise Unavailable("native-stderr-limit")
                continue
            self.buffer += chunk
            while b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                require(len(line) < MAX_FRAME, "native-frame-limit")
                if line.strip():
                    self.receive(json.loads(line))
            require(len(self.buffer) < MAX_FRAME, "native-frame-limit")

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
                if value.get("widgetKey") == "armory-receipts":
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
            raise Unavailable("native-extension-registration-or-publication-failed")
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
                and message.get("customType") == "armory-receipts"
                and kind == "message_end"
            ):
                require(
                    message.get("display") is True
                    and isinstance(message.get("content"), str),
                    "native-custom-text-not-displayable",
                )
                projection = json.loads(message["content"])
                safe_message(projection)
                if "error" in projection:
                    self.report["nativeAdapterError"] = projection["error"]
                self.messages.append(projection)
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
        allowed = {
            "/armory-evidence",
            "/armory-evidence wait",
            "/armory-evidence cancel",
            "/armory-verify success",
            "/armory-verify failure",
            "/armory-verify changed-during-run",
            "/armory-verify cancellation",
        }
        require(text in allowed, "driver-refused-nonliteral-prompt")
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
        is_evidence = text.startswith("/armory-evidence")

        def published() -> list[JsonObject]:
            return [
                value
                for value in self.messages[start:]
                if (
                    "receipts" in value
                    if is_evidence
                    else "state" in value or "executionId" in value
                )
            ]

        while not published():
            if any("error" in value for value in self.messages[start:]):
                raise Failure("native-adapter-returned-error")
            self.pump(deadline)
        values = published()
        self.report.setdefault("nativeText", []).extend(
            {"command": text.split()[0][1:], "value": value} for value in values
        )
        self.observe_usage(text.split()[0])
        return values[-1]

    def evidence(self, cwd: Path, suffix: str = "") -> list[JsonObject]:
        require(cwd == self.cwd, "driver-refused-repository-switch")
        value = self.prompt("/armory-evidence" + suffix)
        require(
            set(value) == {"receipts"} and isinstance(value["receipts"], list),
            "native-evidence-projection-missing",
        )
        return cast(list[JsonObject], value["receipts"])

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            if self.process.poll() is None:
                self.rpc("abort")
        finally:
            try:
                stop_process(self.process, graceful=True)
            finally:
                self.selector.close()
                for stream in (self.process.stdout, self.process.stderr):
                    cast(BinaryIO, stream).close()


def safe_message(value: JsonObject) -> None:
    if "receipts" in value:
        require(
            set(value) == {"receipts"} and isinstance(value["receipts"], list),
            "unsafe-native-evidence-fields",
        )
        for receipt in value["receipts"]:
            safe_message(receipt)
    elif "executionId" in value:
        require(
            set(value) == {"executionId", "status", "applicability", "proof", "output"},
            "unsafe-native-receipt-fields",
        )
        require(
            bool(re.fullmatch(r"[0-9a-f-]{36}", value["executionId"])),
            "unsafe-native-execution-id",
        )
        require(
            value["status"] in {"passed", "failed", "cancelled", "incomplete"},
            "unsafe-native-status",
        )
        require(
            value["applicability"] in {"current", "stale", "unknown"}
            and type(value["proof"]) is bool,
            "unsafe-native-applicability",
        )
        output = value["output"]
        require(
            set(output) == {"sha256", "capturedBytes", "totalBytes", "truncated"},
            "unsafe-native-output-fields",
        )
        require(
            bool(re.fullmatch("[0-9a-f]{64}", output["sha256"])),
            "unsafe-native-output-digest",
        )
        require(
            type(output["capturedBytes"]) is int and output["capturedBytes"] >= 0,
            "unsafe-native-output-size",
        )
        require(
            output["totalBytes"] is None or type(output["totalBytes"]) is int,
            "unsafe-native-output-total",
        )
        require(
            output["truncated"] is None or type(output["truncated"]) is bool,
            "unsafe-native-output-truncation",
        )
    elif "state" in value:
        require(value == {"state": "running"}, "unsafe-native-running-fields")
    else:
        require(
            set(value) == {"error"}
            and isinstance(value["error"], str)
            and bool(re.fullmatch("[a-z][a-z0-9-]{0,79}", value["error"])),
            "unsafe-native-error-fields",
        )


def receipt_for(receipts: list[JsonObject], identity: str) -> JsonObject:
    matches = [value for value in receipts if value["executionId"] == identity]
    require(len(matches) == 1, "native-receipt-not-durable")
    return matches[0]


def execute(args: argparse.Namespace, report: JsonObject, root: Path) -> None:
    if sys.version_info < (3, 12) or os.name != "posix":
        raise Unavailable("python312-posix-required")
    omp, bun, git = (shutil.which(name) for name in ("omp", "bun", "git"))
    if omp is None or bun is None or git is None:
        raise Unavailable("installed-omp-bun-git-required")
    package, metadata = package_for(omp)
    report["version"] = metadata.get("version")
    if report["version"] != "18.12.6":
        raise Unavailable("installed-version-needs-source-containment-review")
    # Fail closed if the installed sources no longer support the reviewed API.
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
    feature = Path(args.feature_dir).resolve(strict=True)
    entry = feature / "omp/index.ts"
    if not entry.is_file():
        raise Unavailable("feature-omp-entry-unavailable")
    artifact, repo, data, sessions = (
        root / name for name in ("artifact", "repository", "data", "sessions")
    )
    for directory in (artifact, repo, data, sessions):
        directory.mkdir(mode=0o700)
    finite([git, "init", "--quiet", str(repo)], root, "synthetic-git-init-blocked")
    private_write(repo / "input.txt", "original covered input\n")
    private_write(repo / "unrelated.txt", "original unrelated input\n")
    private_write(repo / "gate.py", GATE)
    token = uuid.uuid4().hex
    secret = "SYNTHETIC_PRIVATE_OUTPUT_" + uuid.uuid4().hex
    endpoint = root / "ready.sock"
    gates = {}
    for name in ("success", "failure", "changed-during-run", "cancellation"):
        gates[name] = {
            "criterionId": name,
            "kind": "integration",
            "executable": sys.executable,
            "args": [
                "-I",
                "-S",
                str(repo / "gate.py"),
                name,
                str(endpoint),
                token,
                secret,
                str(root / (name + ".pid.json")),
            ],
            "cwd": ".",
            "timeoutMs": 45000,
            "maxOutputBytes": 4096,
            "requiresCompleteOutput": True,
            "scope": {
                "paths": ["input.txt"],
                "configPaths": ["gate.py"],
                "environmentNames": [],
                "datasetIdentity": None,
            },
        }
    private_write(
        repo / "receipts.json",
        json.dumps(
            {"schemaVersion": 1, "configId": "native-omp-smoke", "gates": gates}
        ),
    )
    # Synthetic commit metadata only; inherit hooks, signing, credentials and includes.
    finite(
        [
            git,
            "-C",
            str(repo),
            "add",
            "input.txt",
            "unrelated.txt",
            "gate.py",
            "receipts.json",
        ],
        root,
        "synthetic-git-add-blocked",
    )
    finite(
        [
            git,
            "-C",
            str(repo),
            "-c",
            "user.name=Receipt Test",
            "-c",
            "user.email=receipt@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "Synthetic native receipt input",
        ],
        root,
        "synthetic-git-commit-auth-or-policy-blocked",
    )
    overlay, preflight = root / "overlay.json", root / "preflight.mjs"
    private_write(preflight, PREFLIGHT)
    # Resolve pi-utils through the actual installed package, not the checkout.
    (root / "node_modules").symlink_to(package.parent.parent)
    try:
        inventory = finite(
            [bun, str(preflight), str(package), str(repo), str(overlay)],
            root,
            "read-only-effective-controls-or-startup-containment-unavailable",
        )
    finally:
        # The native detached artifact must not inherit even this read-only
        # inventory's installed-package resolution link at host runtime.
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
    # Preserve native HOME/profile/runtime roots. Synthetic-cwd keyed presence,
    # normal session/cache bookkeeping and metadata catalog refresh are allowed;
    # they are not extension install lifecycle or live-vault capture.
    report["preflight"] = {
        "optionalControlsVerified": True,
        "enforcementSettingsUnchanged": True,
        "mcpContainment": "supported-disabledExtensions",
        "activeMcp": 0,
        "optionalTesseraDisabled": observed.get("optionalTesseraDisabled"),
        "ordinaryNativePresenceBookkeepingPossible": True,
        "catalogMetadataTrafficPossible": True,
    }
    # One standalone ESM bundle, no workspace link or developer import at runtime.
    (artifact / "omp").mkdir(mode=0o700)
    built = artifact / "omp" / "index.js"
    finite(
        [
            bun,
            "build",
            str(entry),
            "--target=bun",
            "--format=esm",
            "--outfile",
            str(built),
        ],
        root,
        "detached-adapter-bundle-unavailable",
    )
    source = built.read_text()
    imports = re.findall(
        r"""(?m)^\s*import\s+(?:[^;\n]*?\s+from\s+)?["']([^"']+)["']""", source
    )
    imports += re.findall(
        r"""(?:import|require)\s*\(\s*["']([^"']+)["']\s*\)""", source
    )
    builtin_check = (
        "import { isBuiltin } from 'node:module';"
        f"const imports = {json.dumps(imports)};"
        "console.log(imports.every(s => isBuiltin(s) || s === 'bun' || s.startsWith('bun:')));"
    )
    builtins_only = finite(
        [bun, "-e", builtin_check], root, "detached-bundle-builtin-check-unavailable"
    )
    if json.loads(builtins_only) is not True:
        raise Unavailable("detached-bundle-runtime-import-not-contained")
    private_write(
        artifact / "package.json",
        json.dumps(
            {
                "name": "armory-verification-receipts-native-smoke",
                "private": True,
                "type": "module",
                "omp": {"extensions": ["./omp/index.js"]},
            }
        ),
    )
    os.chmod(built, 0o600)
    argv = [
        omp,
        "--mode",
        "rpc",
        "--extension",
        str(built),
        "--no-title",
        "--no-prewalk",
        "--config",
        str(overlay),
        "--session-dir",
        str(sessions),
        "--armory-receipts-repo",
        str(repo),
        "--armory-receipts-config",
        "receipts.json",
        "--armory-receipts-data-root",
        str(data),
        "--armory-receipts-account",
        "synthetic-native-smoke",
        "--armory-receipts-work-context",
        "synthetic-native-smoke",
    ]
    host = RPC(argv, repo, report, sessions)
    barriers = []
    retained = []
    try:
        host.start()
        require(host.evidence(repo) == [], "native-initial-evidence-not-empty")
        results = {}
        for name, status in (("success", "passed"), ("failure", "failed")):
            host.prompt("/armory-verify " + name)
            receipts = host.evidence(repo, " wait")
            matching = [
                value for value in receipts if value["executionId"] not in results
            ]
            require(len(matching) == 1, "native-execution-cardinality")
            value = matching[0]
            require(
                value["status"] == status
                and value["applicability"] == "current"
                and value["proof"] == (status == "passed"),
                "native-" + name + "-mismatch",
            )
            results[value["executionId"]] = value
            report["scenarios"][SCENARIOS.index(name)]["status"] = "passed"
        baseline = host.evidence(repo)
        host.new_session()
        require(host.evidence(repo) == baseline, "fresh-native-session-reopen-mismatch")
        report["scenarios"][SCENARIOS.index("reopen")]["status"] = "passed"
        (repo / "unrelated.txt").write_text("unrelated edit\n")
        require(host.evidence(repo) == baseline, "unrelated-edit-invalidated-receipt")
        (repo / "input.txt").write_text("covered edit\n")
        stale = host.evidence(repo)
        require(
            {v["executionId"] for v in stale} == set(results)
            and all(v["applicability"] == "stale" and not v["proof"] for v in stale),
            "covered-edit-did-not-stale",
        )
        report["scenarios"][SCENARIOS.index("freshness")]["status"] = "passed"
        barrier = Barrier(root, token)
        barriers.append(barrier)
        host.prompt("/armory-verify changed-during-run")
        ready = barrier.ready({"changed-during-run"})
        (repo / "input.txt").write_text("mutation after actual gate readiness\n")
        ready["changed-during-run"][1].sendall(b"continue\n")
        changed = host.evidence(repo, " wait")
        added = [value for value in changed if value["executionId"] not in results]
        require(
            len(added) == 1
            and added[0]["status"] == "passed"
            and added[0]["applicability"] == "unknown"
            and not added[0]["proof"],
            "changed-during-run-not-unknown",
        )
        results[added[0]["executionId"]] = added[0]
        report["scenarios"][SCENARIOS.index("changed-during-run")]["status"] = "passed"
        barrier.close()
        barrier = Barrier(root, token)
        barriers.append(barrier)
        host.prompt("/armory-verify cancellation")
        ready = barrier.ready({"cancellation", "descendant"})
        root_pid = ready["cancellation"][0]["pid"]
        require(
            ready["cancellation"][0]["pgid"] == root_pid
            and ready["descendant"][0]["pgid"] == root_pid,
            "gate-descendant-not-owned-group",
        )
        host.rpc("abort")
        cancelled = host.evidence(repo, " cancel")
        waited = host.evidence(repo, " wait")
        require(waited == cancelled, "native-cancel-wait-not-durable")
        added = [value for value in cancelled if value["executionId"] not in results]
        require(
            len(added) == 1
            and added[0]["status"] == "cancelled"
            and not added[0]["proof"],
            "native-cancelled-receipt-missing",
        )
        for value, connection in ready.values():
            require(connection.recv(1) == b"", "cancelled-gate-channel-still-open")
            try:
                os.kill(value["pid"], 0)
            except ProcessLookupError:
                pass
            else:
                raise Failure("cancelled-root-or-descendant-survived")
        require(not group_exists(root_pid), "cancelled-gate-group-survived")
        final = host.evidence(repo)
        host.new_session()
        require(host.evidence(repo) == final, "cancelled-receipt-reopen-mismatch")
        report["scenarios"][SCENARIOS.index("cancellation")]["status"] = "passed"
        # Capture/verify actual immutable private receipts and artifacts, not CLI substitutes.
        for path in data.rglob("receipts/*.json"):
            receipt = json.loads(path.read_text())
            identity = receipt["plan"]["executionId"]
            projection = receipt_for(final, identity)
            require(
                receipt["plan"]["context"]["host"] == "omp"
                and receipt["plan"]["context"]["sessionId"] in host.sessions,
                "receipt-not-bound-to-actual-native-session",
            )
            require(
                receipt["result"]["descendantsStopped"] is True,
                "private-receipt-descendant-cleanup-uncertain",
            )
            output = path.parent.parent / "runs" / identity / "artifacts/output.bin"
            content = output.read_bytes()
            require(
                secret.encode() in content
                and hashlib.sha256(content).hexdigest()
                == projection["output"]["sha256"],
                "private-output-capture-mismatch",
            )
            require(
                stat.S_IMODE(path.stat().st_mode) == 0o600
                and stat.S_IMODE(output.stat().st_mode) == 0o600,
                "private-receipt-mode-mismatch",
            )
            retained.append({"receipt": receipt, "outputHex": content.hex()})
        require(len(retained) == 4, "private-receipt-cardinality")
        public = json.dumps(host.updates)
        require(
            secret not in public
            and str(repo) not in public
            and str(data) not in public,
            "private-output-or-path-leaked-to-rpc",
        )
        report["scenarios"][SCENARIOS.index("private-output")]["status"] = "passed"
        live = {value["command"] for value in report.get("nativeText", [])}
        report["scenarios"][SCENARIOS.index("native-text")]["status"] = (
            "passed" if COMMANDS <= live else "unavailable"
        )
        report["receipts"] = final
    finally:
        try:
            host.close()
        finally:
            roots = {
                pid
                for barrier in barriers
                for role, pid in barrier.pids.items()
                if role != "descendant"
            }
            # PID records precede even the first child spawn/IPC handshake, so
            # failure before readiness still has an owned process-group target.
            for path in root.glob("*.pid.json"):
                value = json.loads(path.read_text())
                pid = value.get("pid")
                require(
                    type(pid) is int and pid > 1 and value.get("pgid") == pid,
                    "gate-lifecycle-identity-invalid",
                )
                roots.add(pid)
            try:
                for pid in roots:
                    if group_exists(pid):
                        try:
                            os.killpg(pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        if group_exists(pid):
                            raise Failure("emergency-gate-cleanup-not-proven")
                require(
                    not group_exists(host.process.pid), "native-host-cleanup-not-proven"
                )
                report["_cleanupProven"] = True
            finally:
                for barrier in barriers:
                    barrier.close()
    # Session storage is also native evidence: no assistant/tool/model message
    # is accepted. This is not a network-call meter or a fabricated zero usage.
    session_records = 0
    for path in sessions.rglob("*.jsonl"):
        for line in path.read_text().splitlines():
            value = json.loads(line)
            message = value.get("message", {})
            require(
                message.get("role") not in {"assistant", "toolResult"},
                "unexpected-native-model-session-entry",
            )
            session_records += 1
    require(session_records > 0, "native-session-storage-evidence-missing")
    report["nativeSessionEvidence"] = {
        "recordsObserved": session_records,
        "assistantOrToolMessagesObserved": False,
    }
    private = Path(args.report).with_suffix(".private.json")
    private_write(
        private,
        json.dumps(
            {"schemaVersion": 1, "syntheticOnly": True, "captures": retained}, indent=2
        )
        + "\n",
    )
    report["privateCapture"] = {
        "retained": True,
        "receipts": len(retained),
        "mode": "0600",
    }
    if report["scenarios"][SCENARIOS.index("native-text")]["status"] != "passed":
        raise Unavailable("native-live-custom-text-unavailable")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature-dir", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    if not Path(args.feature_dir).is_absolute() or not Path(args.report).is_absolute():
        parser.error("--feature-dir and --report must be absolute")
    report_path = Path(args.report)
    if (
        not report_path.parent.is_dir()
        or report_path.exists()
        or report_path.with_suffix(".private.json").exists()
    ):
        parser.error(
            "report parent must exist and report/private capture must not exist"
        )
    if stat.S_IMODE(report_path.parent.stat().st_mode) & 0o077:
        parser.error("report parent must be private (0700)")
    os.umask(0o077)
    report: JsonObject = {
        "schemaVersion": 1,
        "host": "omp",
        "mode": "rpc",
        "status": "unavailable",
        "version": None,
        "scenarios": [{"name": name, "status": "not-run"} for name in SCENARIOS],
        "usageObservations": [],
        "usageInterpretation": "Native session token counters are observations, not a network-call meter; missing telemetry is unknown.",
    }
    code = 3
    root = Path(tempfile.mkdtemp(prefix="armory-vr-omp-", dir="/tmp")).resolve()
    signals = (signal.SIGALRM, signal.SIGINT, signal.SIGTERM)
    old_handlers = {kind: signal.getsignal(kind) for kind in signals}

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
    try:
        execute(args, report, root)
        report["status"] = "passed"
        code = 0
    except Unavailable as error:
        report["reasonCode"] = str(error)
    except Failure as error:
        report["status"] = "failed"
        report["reasonCode"] = str(error)
        code = 1
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        report["reasonCode"] = "native-prerequisite-or-protocol-unavailable"
    finally:
        signal.alarm(0)
        for kind, previous in old_handlers.items():
            signal.signal(kind, previous)
        # Preserve owned scratch if process absence could not be established.
        proven = report.pop("_cleanupProven", True)
        if proven:
            try:
                shutil.rmtree(root)
            except OSError:
                report["status"] = "failed"
                report["reasonCode"] = "owned-scratch-cleanup-failed"
                code = 1
        else:
            report["ownedScratchRetainedForUnprovenCleanup"] = True
            report["status"] = "failed"
            report["reasonCode"] = "native-or-gate-cleanup-not-proven"
            code = 1
    encoded = json.dumps(report, sort_keys=True, indent=2) + "\n"
    try:
        private_write(report_path, encoded)
    except OSError:
        report["status"] = "unavailable"
        report["reasonCode"] = "private-report-write-unavailable"
        code = 3
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
