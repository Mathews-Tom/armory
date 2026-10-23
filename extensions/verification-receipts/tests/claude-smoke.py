#!/usr/bin/env python3
"""Manual real-TTY Claude qualification, never an authenticated CI prerequisite.

Supply ARMORY_CLAUDE_NATIVE_CWD and ARMORY_CLAUDE_NATIVE_SETTINGS after reviewing
that context's optional writers, plugins, hooks and MCP inventory. The settings
are additive: HOME, authentication and user/managed enforcement stay intact.
No trust/login prompt is answered. Only discovered native commands are entered.
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
import shutil
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import termios
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from types import FrameType
from typing import Any

import pyte

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.build_extensions import (
    CONTENT_MANIFEST,
    BuildError,
    ToolUnavailableError,
    build_feature,
    check_artifact_imports,
    load_metadata,
    verify_artifact_dir,
)

_spec = importlib.util.spec_from_file_location(
    "_armory_receipts_omp_smoke", Path(__file__).with_name("omp-smoke.py")
)
assert _spec is not None and _spec.loader is not None
_shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_shared)
Failure = _shared.Failure
Unavailable = _shared.Unavailable
require = _shared.require
private_write = _shared.private_write

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
STEP = 45
LIMIT = 420
MAX_CAPTURE = 8 * 1024 * 1024
ANSI = re.compile(r"\x1b(?:\][^\x07]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~]|[@-_])")
COMMANDS = {
    "armory-verify": "Run one explicitly configured local verification gate",
    "armory-evidence": "Read persisted verification evidence",
}
type JsonObject = dict[str, Any]


def compact(raw: bytes) -> str:
    # The native renderer inserts wrapping/indentation into fixed ASCII receipt
    # metadata. These projections contain no whitespace-bearing string fields.
    return re.sub(r"\s+", "", ANSI.sub("", raw.decode("utf-8", "replace")))


def projections(raw: bytes) -> list[JsonObject]:
    text = compact(raw)
    result = []
    for match in re.finditer(r'\{"receipts":', text):
        try:
            value, _ = json.JSONDecoder().raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("receipts"), list):
            result.append(value)
    return result


def native_replies(raw: bytes) -> list[bytes]:
    text = compact(raw)
    replies = []
    for match in re.finditer(r"verification-receipts:(\{)", text):
        try:
            _, end = json.JSONDecoder().raw_decode(text[match.start(1) :])
        except json.JSONDecodeError:
            continue
        replies.append(text[match.start(1) : match.start(1) + end].encode())
    return replies


class NativeTTY:
    def __init__(self, argv: list[str], cwd: Path, env: dict[str, str]) -> None:
        self.argv, self.cwd, self.env = argv, cwd, env
        self.master = -1
        self.process: subprocess.Popen[bytes] | None = None
        self.raw = bytearray()
        self.ready = False
        self.interaction_required = False
        self.screen = pyte.HistoryScreen(240, 60, history=5000)
        self.terminal = pyte.Stream(self.screen)
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")

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

    def read(self, predicate: Callable[[bytes], bool], start: int = 0) -> bytes:
        deadline = time.monotonic() + STEP
        while time.monotonic() < deadline:
            value = self.rendered()
            plain = ANSI.sub("", value.decode("utf-8", "replace")).lower()
            if any(
                marker in plain
                for marker in (
                    "do you trust the files",
                    "trust this folder",
                    "please log in",
                    "select login method",
                    "sign in to continue",
                    "permission required",
                )
            ):
                self.interaction_required = True
                raise Unavailable("native-trust-login-or-policy-interaction-required")
            if len(self.raw) > MAX_CAPTURE:
                raise Failure("native-terminal-capture-limit")
            if len(self.raw) > start and predicate(value):
                return value
            if self.process is None or self.process.poll() is not None:
                raise Unavailable("native-process-exited-before-response")
            if select.select(
                [self.master], [], [], min(0.2, deadline - time.monotonic())
            )[0]:
                try:
                    chunk = os.read(self.master, 65536)
                except OSError as error:
                    raise Unavailable("native-terminal-disconnected") from error
                if not chunk:
                    raise Unavailable("native-terminal-disconnected")
                self.receive(chunk)
        raise Unavailable("native-command-response-deadline")

    def drain(self) -> None:
        while select.select([self.master], [], [], 0.15)[0]:
            try:
                chunk = os.read(self.master, 65536)
            except OSError:
                return
            if not chunk:
                return
            self.receive(chunk)

    def start(self) -> None:
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 60, 240, 0, 0))

        def controlling_terminal() -> None:
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

        try:
            self.process = subprocess.Popen(
                self.argv,
                cwd=self.cwd,
                env=self.env,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                # This finite driver is single-threaded; a controlling TTY is
                # required to preserve the real interactive trust boundary.
                preexec_fn=controlling_terminal,  # noqa: PLW1509
            )
        finally:
            os.close(slave)
        self.read(lambda raw: "❯" in raw.decode("utf-8", "replace"))
        for command, description in COMMANDS.items():
            self.drain()
            mark = len(self.raw)
            os.write(self.master, ("/" + command).encode())

            def discovered(raw: bytes, label: str = description) -> bool:
                return compact(label.encode()) in compact(raw)

            self.read(discovered, mark)
            # Never submit a command unless the actual native completion menu
            # identified it. Ctrl-U only clears our unsubmitted typeahead.
            os.write(self.master, b"\x15")
        self.drain()
        self.ready = True

    def command(self, text: str, predicate: Callable[[bytes], bool]) -> bytes:
        require(
            text.split(" ", 1)[0] in ("/armory-verify", "/armory-evidence"),
            "non-native-command-refused",
        )
        self.drain()
        mark = len(self.raw)
        os.write(self.master, text.encode())
        self.read(lambda raw: compact(text.encode()) in compact(raw), mark)
        self.drain()
        mark = len(self.raw)
        observed = native_replies(self.rendered())
        previous = observed[-1] if observed else None
        os.write(self.master, b"\r")

        def completed(rendered: bytes) -> bool:
            replies = native_replies(rendered)
            return bool(replies) and replies[-1] != previous and predicate(replies[-1])

        rendered = self.read(completed, mark)
        return native_replies(rendered)[-1]

    def evidence(
        self, expected: Callable[[list[JsonObject]], bool], mode: str = ""
    ) -> list[JsonObject]:
        def matches(raw: bytes) -> bool:
            return any(expected(value["receipts"]) for value in projections(raw))

        raw = self.command("/armory-evidence" + (" " + mode if mode else ""), matches)
        values: list[list[JsonObject]] = [
            value["receipts"]
            for value in projections(raw)
            if expected(value["receipts"])
        ]
        return values[-1]

    def stop(self) -> None:
        if self.process is None:
            return
        try:
            if (
                self.ready
                and not self.interaction_required
                and self.process.poll() is None
            ):
                self.drain()
                mark = len(self.raw)
                os.write(self.master, b"/exit\r")
                self.read(lambda raw: "claude--resume" in compact(raw), mark)
        finally:
            # The installed host can retain its input loop after /exit renders
            # resume metadata. Closing our own controlling terminal reaps it.
            if self.master != -1:
                os.close(self.master)
                self.master = -1
            try:
                self.process.wait(timeout=STEP)
            except subprocess.TimeoutExpired as error:
                raise Failure("native-shutdown-not-proven") from error
        require(
            not self.ready or self.interaction_required or self.process.returncode == 0,
            "native-shutdown-nonzero",
        )
        require(
            not _shared.group_exists(self.process.pid), "native-process-group-survived"
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
    # This is not an automatic policy inventory. The caller must review optional
    # writers before selecting this additive profile. Refuse explicit overrides
    # of enforcement/authentication/configuration-source boundaries nonetheless.
    allowed = {
        "autoMemoryEnabled",
        "autoDreamEnabled",
        "idleCompaction",
        "promptSuggestionEnabled",
        "enabledPlugins",
        "deniedMcpServers",
        "statusLine",
        "env",
    }
    if not isinstance(value, dict) or set(value) - allowed:
        raise Unavailable("native-profile-must-not-override-enforcement")
    environment = value.get("env", {})
    if not isinstance(environment, dict) or any(
        name
        in {
            "HOME",
            "CLAUDE_CONFIG_DIR",
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_AUTH_TOKEN",
            "ANTHROPIC_BASE_URL",
        }
        or "PERMISSION" in name
        or "BYPASS" in name
        for name in environment
    ):
        raise Unavailable("native-profile-must-preserve-authentication-and-enforcement")
    return cwd, settings


def execute(args: argparse.Namespace, report: JsonObject, root: Path) -> None:
    if sys.version_info < (3, 12) or os.name != "posix":
        raise Unavailable("python312-posix-required")
    cwd, settings = context(args)
    claude, bun, git = (shutil.which(name) for name in ("claude", "bun", "git"))
    if claude is None or bun is None or git is None:
        raise Unavailable("installed-claude-bun-git-required")
    version = (
        _shared.finite([claude, "--version"], root, "native-version-unavailable")
        .decode()
        .strip()
        .split()[0]
    )
    report["version"] = version
    if version != "2.1.309":
        raise Unavailable("installed-version-needs-native-interface-review")
    feature = Path(args.feature_dir).resolve(strict=True)
    metadata = load_metadata(feature)
    artifact = (
        Path(args.artifact).resolve(strict=True)
        if args.artifact
        else build_feature(feature, root / "build")["claude"]
    )
    manifest = verify_artifact_dir(artifact)
    require(
        metadata.name == "verification-receipts"
        and metadata.host_entries.get("claude") == "claude-code/register.ts"
        and manifest.get("feature") == metadata.name
        and manifest.get("host") == "claude"
        and manifest.get("version") == metadata.version
        and manifest.get("runtime") == metadata.runtime
        and manifest.get("entrypoints")
        == {
            "hooks": "hooks/hooks.json",
            "module": "hooks/register.ts",
            "plugin_manifest": ".claude-plugin/plugin.json",
        },
        "native-artifact-identity-mismatch",
    )
    files = {
        record["path"]: (artifact / record["path"]).read_bytes()
        for record in manifest["files"]
    }
    check_artifact_imports(files, "claude")
    runtime = root / "native-artifact"
    shutil.copytree(artifact, runtime)
    verify_artifact_dir(runtime)
    report["artifactManifestSha256"] = hashlib.sha256(
        (artifact / CONTENT_MANIFEST).read_bytes()
    ).hexdigest()
    report["settingsSha256"] = hashlib.sha256(settings.read_bytes()).hexdigest()
    report["context"] = (
        "explicit reviewed additive settings; normal HOME/authentication/settings sources retained"
    )
    report["developmentLoaderUsesDisposableCopy"] = True
    repo, data = root / "repository", root / "data"
    repo.mkdir(mode=0o700)
    data.mkdir(mode=0o700)
    _shared.finite(
        [git, "init", "--quiet", str(repo)], root, "synthetic-git-init-blocked"
    )
    private_write(repo / "input.txt", "original covered input\n")
    private_write(repo / "unrelated.txt", "unrelated input\n")
    (repo / "covered").mkdir(mode=0o700)
    private_write(repo / "covered" / "baseline.txt", "directory baseline\n")
    private_write(repo / "gate.py", _shared.GATE)
    token, secret = uuid.uuid4().hex, "SYNTHETIC_PRIVATE_OUTPUT_" + uuid.uuid4().hex
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
                str(root / "ready.sock"),
                token,
                secret,
                str(root / (name + ".pid.json")),
            ],
            "cwd": ".",
            "timeoutMs": 45000,
            "maxOutputBytes": 4096,
            "requiresCompleteOutput": True,
            "scope": {
                "paths": ["input.txt", "covered"],
                "configPaths": ["gate.py"],
                "environmentNames": [],
                "datasetIdentity": None,
            },
        }
    config = {"schemaVersion": 1, "configId": "native-claude-smoke", "gates": gates}
    private_write(repo / "receipts.json", json.dumps(config))
    _shared.finite(
        [git, "-C", str(repo), "add", "."], root, "synthetic-git-add-blocked"
    )
    _shared.finite(
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
        "synthetic-git-commit-blocked",
    )
    env = {
        **os.environ,
        "ARMORY_RECEIPTS_REPO": str(repo),
        "ARMORY_RECEIPTS_CONFIG": "receipts.json",
        "ARMORY_RECEIPTS_DATA_ROOT": str(data),
        "ARMORY_RECEIPTS_ACCOUNT": "synthetic-native-smoke",
        "ARMORY_RECEIPTS_WORK_CONTEXT": "synthetic-native-smoke",
    }
    argv = [claude, "--settings", str(settings), "--plugin-dir", str(runtime)]
    hosts: list[NativeTTY] = []
    barriers = []
    known: dict[str, JsonObject] = {}

    def host() -> NativeTTY:
        value = NativeTTY(argv, cwd, env)
        hosts.append(value)
        value.start()
        return value

    def run(native: NativeTTY, name: str, status: str) -> JsonObject:
        native.command(
            "/armory-verify " + name, lambda raw: '{"state":"running"}' in compact(raw)
        )
        values = native.evidence(lambda rows: len(rows) == len(known) + 1, "wait")
        added = [row for row in values if row["executionId"] not in known]
        require(
            len(added) == 1 and added[0]["status"] == status,
            "native-execution-result-mismatch",
        )
        known[added[0]["executionId"]] = added[0]
        return added[0]

    def passed(name: str) -> None:
        report["scenarios"][SCENARIOS.index(name)]["status"] = "passed"

    try:
        native = host()
        require(
            native.evidence(lambda rows: rows == []) == [],
            "native-initial-evidence-not-empty",
        )
        success = run(native, "success", "passed")
        require(
            success["proof"] and success["applicability"] == "current",
            "native-success-not-current",
        )
        passed("success")
        failed = run(native, "failure", "failed")
        require(
            not failed["proof"] and failed["applicability"] == "current",
            "native-failure-not-exact",
        )
        passed("failure")
        baseline = known.copy()
        native.stop()
        native = host()
        reopened = native.evidence(lambda rows: len(rows) == len(known))
        require(
            {row["executionId"]: row for row in reopened} == baseline,
            "fresh-native-session-reopen-mismatch",
        )
        passed("reopen")
        native.stop()
        (repo / "unrelated.txt").write_text("unrelated edit\n")
        native = host()
        unrelated = native.evidence(lambda rows: len(rows) == len(known))
        require(
            {row["executionId"]: row for row in unrelated} == baseline,
            "unrelated-edit-invalidated-receipt",
        )
        # Restore each covered change before the next case. This proves both
        # additions/deletions and configuration edits against the same success.
        mutations = [
            (repo / "input.txt", b"covered edit\n"),
            (repo / "covered" / "new-untracked.txt", b"new covered file\n"),
            (repo / "covered" / "baseline.txt", None),
            (
                repo / "gate.py",
                (repo / "gate.py").read_bytes() + b"\n# config mutation\n",
            ),
        ]
        for path, changed in mutations:
            native.stop()
            original = path.read_bytes() if path.exists() else None
            if changed is None:
                path.unlink()
            else:
                path.write_bytes(changed)
            native = host()
            rows = native.evidence(
                lambda rows: (
                    len(rows) == len(known)
                    and all(
                        row["applicability"] == "stale" and not row["proof"]
                        for row in rows
                    )
                )
            )
            require(
                {row["executionId"] for row in rows} == set(known),
                "covered-mutation-lost-evidence",
            )
            native.stop()
            if original is None:
                path.unlink()
            else:
                path.write_bytes(original)
        passed("freshness")
        native = host()
        barrier = _shared.Barrier(root, token)
        barriers.append(barrier)
        native.command(
            "/armory-verify changed-during-run",
            lambda raw: '{"state":"running"}' in compact(raw),
        )
        ready = barrier.ready({"changed-during-run"})
        (repo / "input.txt").write_text("mutation after actual gate readiness\n")
        ready["changed-during-run"][1].sendall(b"continue\n")
        rows = native.evidence(lambda rows: len(rows) == len(known) + 1, "wait")
        added = [row for row in rows if row["executionId"] not in known]
        require(
            len(added) == 1
            and added[0]["status"] == "passed"
            and added[0]["applicability"] == "unknown"
            and not added[0]["proof"],
            "changed-during-run-not-unknown",
        )
        known[added[0]["executionId"]] = added[0]
        barrier.close()
        passed("changed-during-run")
        barrier = _shared.Barrier(root, token)
        barriers.append(barrier)
        native.command(
            "/armory-verify cancellation",
            lambda raw: '{"state":"running"}' in compact(raw),
        )
        ready = barrier.ready({"cancellation", "descendant"})
        root_pid = ready["cancellation"][0]["pid"]
        require(
            ready["cancellation"][0]["pgid"] == root_pid
            and ready["descendant"][0]["pgid"] == root_pid,
            "gate-descendant-not-owned-group",
        )
        rows = native.evidence(
            lambda rows: (
                len(rows) == len(known) + 1
                and any(row["status"] == "cancelled" for row in rows)
            ),
            "cancel",
        )
        added = [row for row in rows if row["executionId"] not in known]
        require(
            len(added) == 1
            and added[0]["status"] == "cancelled"
            and not added[0]["proof"],
            "native-cancelled-receipt-missing",
        )
        known[added[0]["executionId"]] = added[0]
        for value, channel in ready.values():
            require(channel.recv(1) == b"", "cancelled-gate-channel-still-open")
            try:
                os.kill(value["pid"], 0)
            except ProcessLookupError:
                pass
            else:
                raise Failure("cancelled-root-or-descendant-survived")
        require(not _shared.group_exists(root_pid), "cancelled-gate-group-survived")
        barrier.close()
        final = rows
        native.stop()
        native = host()
        require(
            native.evidence(lambda rows: len(rows) == len(known)) == final,
            "cancelled-receipt-reopen-mismatch",
        )
        passed("cancellation")
        retained = []
        for path in data.rglob("receipts/*.json"):
            receipt = json.loads(path.read_text())
            identity = receipt["plan"]["executionId"]
            row = _shared.receipt_for(final, identity)
            require(
                receipt["plan"]["context"]["host"] == "claude"
                and receipt["result"]["descendantsStopped"] is True,
                "private-receipt-native-cleanup-mismatch",
            )
            output = path.parent.parent / "runs" / identity / "artifacts/output.bin"
            content = output.read_bytes()
            require(
                secret.encode() in content
                and hashlib.sha256(content).hexdigest() == row["output"]["sha256"],
                "private-output-capture-mismatch",
            )
            require(
                stat.S_IMODE(path.stat().st_mode) == 0o600
                and stat.S_IMODE(output.stat().st_mode) == 0o600,
                "private-receipt-mode-mismatch",
            )
            retained.append({"receipt": receipt, "outputHex": content.hex()})
        require(len(retained) == 4, "private-receipt-cardinality")
        require(
            all(secret.encode() not in item.raw for item in hosts),
            "private-output-rendered",
        )
        passed("private-output")
        passed("native-text")
        private_write(
            Path(args.report).with_suffix(".private.json"),
            json.dumps(
                {
                    "receipts": retained,
                    "terminalHex": [bytes(item.raw).hex() for item in hosts],
                }
            ),
        )
    finally:
        cleanup_proven = True
        for native in reversed(hosts):
            try:
                native.stop()
            except (Failure, Unavailable, OSError):
                cleanup_proven = False
        capture = Path(args.report).with_suffix(".private.json")
        if not capture.exists():
            private_write(
                capture,
                json.dumps({"terminalHex": [bytes(item.raw).hex() for item in hosts]}),
            )
        for barrier in barriers:
            for pid in barrier.pids.values():
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    pass
                else:
                    cleanup_proven = False
            barrier.close()
        report["_cleanupProven"] = cleanup_proven
        if not cleanup_proven:
            raise Failure("native-or-gate-cleanup-not-proven")


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
    if (
        not Path(args.feature_dir).is_absolute()
        or not report_path.is_absolute()
        or (args.artifact and not Path(args.artifact).is_absolute())
    ):
        parser.error("feature/artifact/report paths must be absolute")
    if (
        not report_path.parent.is_dir()
        or report_path.exists()
        or report_path.with_suffix(".private.json").exists()
        or stat.S_IMODE(report_path.parent.stat().st_mode) & 0o077
    ):
        parser.error("report parent must be private; report/capture must not exist")
    os.umask(0o077)
    root = Path(tempfile.mkdtemp(prefix="armory-vr-claude-", dir="/tmp")).resolve()
    report: JsonObject = {
        "schemaVersion": 1,
        "host": "claude",
        "mode": "interactive",
        "version": None,
        "status": "unavailable",
        "scenarios": [{"name": name, "status": "not-run"} for name in SCENARIOS],
        "usageInterpretation": "Only native commands submitted; not a model/network-call meter.",
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
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        report["reasonCode"] = "native-prerequisite-or-protocol-unavailable"
    finally:
        signal.alarm(0)
        for kind, handler in old.items():
            signal.signal(kind, handler)
        if report.pop("_cleanupProven", True):
            shutil.rmtree(root)
        else:
            report["ownedScratchRetainedForUnprovenCleanup"] = True
    private_write(report_path, json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
