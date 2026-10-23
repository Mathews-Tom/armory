#!/usr/bin/env python3
"""Manual real-TTY Claude Code qualification of Resume Brief, never a CI prerequisite.

Supply ARMORY_CLAUDE_NATIVE_CWD and ARMORY_CLAUDE_NATIVE_SETTINGS after reviewing
that context's optional writers, plugins, hooks and MCP inventory. The settings
are additive: HOME, authentication and user/managed enforcement stay intact.
No trust/login prompt is answered. Only the discovered `/armory-brief` command
is entered; no model prompt is submitted. Assertions are shared with
tests/omp-smoke.py so both hosts are judged identically.
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
    "_armory_brief_omp_smoke", Path(__file__).with_name("omp-smoke.py")
)
assert _spec is not None and _spec.loader is not None
shared = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = shared
_spec.loader.exec_module(shared)
Failure = shared.Failure
Unavailable = shared.Unavailable
require = shared.require
private_write = shared.private_write
compact: Callable[[str], str] = shared.compact

type JsonObject = dict[str, Any]

SCENARIOS = shared.SCENARIOS
STEP = 45
LIMIT = 480
MAX_CAPTURE = 8 * 1024 * 1024
ANSI = re.compile(r"\x1b(?:\][^\x07]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~]|[@-_])")
COMMANDS = {
    "armory-brief": "Record, reopen, show or list freshness-checked project briefs (read-only)",
}
ACCOUNT = "synthetic-native-smoke"
# Starts of literal /armory-brief answers, as rendered with whitespace removed.
ANSWER = re.compile(
    r"(?:Recordedsnapshot|Reopenedsnapshot|Nosnapshotsrecorded\.|"
    r"ResumeBrief(?:invalid-arguments|invalid-configuration|rejected|operation-failed|context-changed|session-unavailable)|"
    + shared.SNAPSHOT_ID
    + r"recorded=)"
)


def screen_text(raw: bytes) -> str:
    return compact(ANSI.sub("", raw.decode("utf-8", "replace")))


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
                if self.process is not None:
                    before = len(self.raw)
                    self.drain()
                    if len(self.raw) > before:
                        # Recheck trust and capture limits before accepting output.
                        continue
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
                # PTYs can split one repaint across reads; an old input prompt
                # below a partial card is not evidence that the answer ended.
                self.drain()
        raise Unavailable("native-command-response-deadline")

    def drain(self) -> None:
        deadline = time.monotonic() + STEP
        while select.select([self.master], [], [], 0.15)[0]:
            if time.monotonic() >= deadline:
                raise Unavailable("native-terminal-drain-deadline")
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
                return screen_text(label.encode()) in screen_text(raw)

            self.read(discovered, mark)
            # Never submit a command unless the actual native completion menu
            # identified it. Ctrl-U only clears our unsubmitted typeahead.
            os.write(self.master, b"\x15")
        self.drain()
        self.ready = True

    def command(self, text: str, predicate: Callable[[str], bool]) -> str:
        """Submit one literal discovered command; return its rendered answer text."""
        require(
            shared.LITERAL.fullmatch(text) is not None, "non-native-command-refused"
        )
        self.drain()
        mark = len(self.raw)
        os.write(self.master, text.encode())
        self.read(lambda raw: compact(text) in screen_text(raw), mark)
        self.drain()
        mark = len(self.raw)
        os.write(self.master, b"\r")

        def answer_text(rendered: bytes) -> str | None:
            flat = screen_text(rendered)
            echo = f"❯{compact(text)}"
            position = flat.rfind(echo)
            if position < 0:
                return None
            # Claude can redraw away earlier answers: their total count is not
            # monotonic. Anchor this answer to its latest echoed command.
            tail = flat[position + len(echo) :]
            match = ANSWER.search(tail)
            if match is None:
                return None
            segment = tail[match.start() :]
            if "❯" not in segment:
                return None
            return segment.split("❯", 1)[0]

        def answered(rendered: bytes) -> bool:
            segment = answer_text(rendered)
            if segment is None:
                return False
            if segment.startswith(
                (
                    "ResumeBriefoperation-failed",
                    "ResumeBriefcontext-changed",
                    "ResumeBriefsession-unavailable",
                )
            ):
                raise Failure("native-command-runtime-failed")
            return predicate(segment)

        segment = answer_text(self.read(answered, mark))
        require(segment is not None, "native-answer-framing-lost")
        assert segment is not None
        self.answers.append({"command": text, "text": segment})
        return segment

    def stop(self) -> None:
        if self.closed:
            return
        if self.process is None:
            if self.master != -1:
                os.close(self.master)
                self.master = -1
            self.closed = True
            return
        try:
            if (
                self.ready
                and not self.interaction_required
                and self.process.poll() is None
                and self.master != -1
            ):
                self.drain()
                mark = len(self.raw)
                os.write(self.master, b"/exit\r")
                self.read(lambda raw: "claude--resume" in screen_text(raw), mark)
        finally:
            # The installed host can retain its input loop after /exit renders
            # resume metadata. Closing our own controlling terminal reaps it.
            if self.master != -1:
                os.close(self.master)
                self.master = -1
            shared.stop_process(
                self.process, graceful=self.ready and not self.interaction_required
            )
            self.closed = True
        require(
            not self.ready or self.interaction_required or self.process.returncode == 0,
            "native-shutdown-nonzero",
        )
        require(
            not shared.group_exists(self.process.pid), "native-process-group-survived"
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
    # Exact reviewed production controls, not a general settings or env overlay.
    # User/managed hooks and all enforcement/authentication settings are inherited.
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
        r"armory-native-[a-zA-Z0-9_-]{1,96}",
        environment["CHROME_DEVTOOLS_AXI_SESSION"],
    ):
        raise Unavailable("native-browser-session-label-must-be-synthetic")
    return cwd, settings


def passed(report: JsonObject, name: str) -> None:
    report["scenarios"][SCENARIOS.index(name)]["status"] = "passed"


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
        metadata.name == shared.FEATURE
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
    require(
        manifest.get("extension_schema_version") == metadata.schema_version,
        "native-artifact-schema-mismatch",
    )
    files = {
        record["path"]: (artifact / record["path"]).read_bytes()
        for record in manifest["files"]
    }
    check_artifact_imports(files, "claude")
    # Claude's development loader writes generated SDK files into its plugin dir.
    runtime = root / "native-artifact"
    shutil.copytree(artifact, runtime)
    verify_artifact_dir(runtime)
    report["artifact"] = {
        "mode": "supplied-production" if args.artifact else "built-production",
        "feature": metadata.name,
        "host": "claude",
        "sourceDefinitionSha256": hashlib.sha256(
            (feature / "EXTENSION.md").read_bytes()
        ).hexdigest(),
        "contentManifestSha256": hashlib.sha256(
            (artifact / CONTENT_MANIFEST).read_bytes()
        ).hexdigest(),
    }
    report["artifactManifestSha256"] = hashlib.sha256(
        (artifact / CONTENT_MANIFEST).read_bytes()
    ).hexdigest()
    report["developmentLoaderUsesDisposableCopy"] = True
    return runtime


def helpers_running(runtime: Path) -> bool:
    listing = shared.finite(
        ["ps", "-axo", "command="], runtime, "process-listing-unavailable"
    ).decode("utf-8", "replace")
    return str(runtime / "helpers" / "claude-cli.js") in listing


def execute(args: argparse.Namespace, report: JsonObject, root: Path) -> None:
    if sys.version_info < (3, 12) or os.name != "posix":
        raise Unavailable("python312-posix-required")
    cwd, settings = context(args)
    claude, bun, git = (shutil.which(name) for name in ("claude", "bun", "git"))
    if claude is None or bun is None or git is None:
        raise Unavailable("installed-claude-bun-git-required")
    words = (
        shared.finite([claude, "--version"], root, "native-version-unavailable")
        .decode()
        .split()
    )
    if not words:
        raise Unavailable("native-version-unavailable")
    version = words[0]
    report["version"] = version
    if version != "2.1.309":
        raise Unavailable("installed-version-needs-native-interface-review")
    runtime = prepare_artifact(args, report, root)
    report["settingsSha256"] = hashlib.sha256(settings.read_bytes()).hexdigest()
    report["context"] = (
        "explicit reviewed additive settings; normal HOME/authentication/settings sources retained"
    )
    project = shared.synthetic_project(root, git)
    selected = {
        "ARMORY_BRIEF_REPO": str(project.repo),
        "ARMORY_BRIEF_CONTEXT": "brief.json",
        "ARMORY_BRIEF_DATA_ROOT": str(project.data),
        "ARMORY_BRIEF_ACCOUNT": ACCOUNT,
        "ARMORY_BRIEF_OMP_SESSION": str(project.session),
        "ARMORY_BRIEF_OMP_HANDOFF": str(project.handoff),
    }
    inherited = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("ARMORY_BRIEF_")
    }
    full = {**inherited, **selected, "ARMORY_BRIEF_RECEIPT": str(project.receipt)}
    narrow = {**inherited, **selected}
    argv = [claude, "--settings", str(settings), "--plugin-dir", str(runtime)]
    hosts: list[NativeTTY] = []

    def host(env: dict[str, str]) -> NativeTTY:
        value = NativeTTY(argv, cwd, env)
        hosts.append(value)
        value.start()
        return value

    def card_complete(segment: str) -> bool:
        return (
            "Currentcard:" in segment
            and "Authority:none." in segment.split("Currentcard:", 1)[1]
        )

    plan = project.repo / "docs" / "PLAN.md"
    blockers_path = project.repo / "docs" / "blockers.json"
    objective = compact(shared.inert(project.objective))
    try:
        native = host(full)
        recorded = native.command(
            "/armory-brief record", lambda segment: objective in segment
        )
        shared.common_text(project, recorded)
        first = shared.snapshot_id(recorded)
        snapshots = shared.private_snapshots(project)
        require(
            len(snapshots) == 1 and snapshots[0]["snapshotId"] == first,
            "native-record-not-durable",
        )
        shared.recorded_card(project, recorded, snapshots[0])
        recorded_by = snapshots[0]["recordedBy"]
        observed = snapshots[0]["observations"]["claudeSession"]
        require(
            recorded_by["host"] == "claude"
            and recorded_by["accountId"] == ACCOUNT
            and isinstance(observed, dict)
            and observed["sessionId"] == recorded_by["sessionId"]
            and shared.evaluated_session(recorded) == recorded_by["sessionId"],
            "native-record-not-bound-to-host-session",
        )
        require(
            set(observed)
            == {
                "sessionId",
                "cwd",
                "root",
                "startedAtMs",
                "turns",
                "observedMessages",
                "messagesComplete",
                "lastRole",
                "toolUses",
                "cwdResolved",
                "rootResolved",
            },
            "native-host-session-projection-not-allowlisted",
        )
        statuses = {
            source["role"]: source["status"]
            for source in snapshots[0]["observations"]["sources"]
        }
        require(
            statuses
            == {
                "context": "ok",
                "plan": "ok",
                "blockers": "ok",
                "receipt": "ok",
                "omp-session": "ok",
                "omp-handoff": "ok",
                "claude-session": "ok",
            },
            "native-record-source-status-mismatch",
        )
        recorded_plan = next(
            source["sha256"]
            for source in snapshots[0]["observations"]["sources"]
            if source["role"] == "plan"
        )
        require(
            recorded_plan == shared.plan_sha(project),
            "native-record-plan-hash-mismatch",
        )
        passed(report, "success")

        moved = project.external / "blockers.moved"
        blockers_path.rename(moved)
        missing = native.command(
            "/armory-brief record", lambda segment: "Blockers:unknown" in segment
        )
        moved.rename(blockers_path)
        require("Blockers:unknown" in missing, "missing-source-not-unknown")
        statuses = {
            source["role"]: source["status"]
            for source in shared.private_snapshots(project)[-1]["observations"][
                "sources"
            ]
        }
        require(
            statuses.get("blockers") == "missing", "missing-source-not-recorded-unknown"
        )
        refused = native.command(
            "/armory-brief record extra",
            lambda segment: segment.startswith("ResumeBriefinvalid-arguments"),
        )
        require(
            refused.startswith("ResumeBriefinvalid-arguments"),
            "invalid-arguments-not-refused",
        )
        require(
            len(shared.private_snapshots(project)) == 2, "refused-command-changed-state"
        )
        passed(report, "failure")

        native.stop()
        native = host(full)
        reopened = native.command(f"/armory-brief reopen {first}", card_complete)
        found = shared.discrepancies(reopened)
        require(
            bool(found)
            and all(item["role"] == "claude-session" for item in found)
            and shared.field(found, "claudeSession.id")["kind"] == "changed",
            "fresh-native-session-reopen-mismatch",
        )
        fresh_session = shared.evaluated_session(reopened)
        require(
            fresh_session != recorded_by["sessionId"],
            "reopen-not-bound-to-fresh-session",
        )
        passed(report, "reopen")

        shared.finite(
            [git, "-C", str(project.repo), "checkout", "--quiet", "-b", "feature/next"],
            root,
            "synthetic-git-branch-blocked",
        )
        plan.write_text(plan.read_text() + "2. Emit\n")
        blockers_path.write_text(json.dumps(shared.blockers("resolved")))
        context_path = project.repo / "brief.json"
        original_context_hash = hashlib.sha256(context_path.read_bytes()).hexdigest()
        context_path.write_bytes(context_path.read_bytes() + b"\n")
        fresh = native.command(f"/armory-brief reopen {first}", card_complete)
        found = shared.discrepancies(fresh)
        shared.changed_values(found, project)
        require(
            shared.field(found, "repository.branch")["role"] == "git",
            "branch-discrepancy-source-mismatch",
        )
        changed = shared.field(found, "sources.plan")
        require(
            changed["role"] == "plan"
            and changed["recorded"] == recorded_plan
            and changed["current"] == shared.plan_sha(project),
            "plan-discrepancy-hash-mismatch",
        )
        require(
            shared.field(found, "blockers[flaky-ci]")["role"] == "blockers",
            "blocker-discrepancy-source-mismatch",
        )
        context_change = shared.field(found, "sources.context")
        require(
            context_change["recorded"] == original_context_hash
            and context_change["current"]
            == hashlib.sha256(context_path.read_bytes()).hexdigest(),
            "refreshed-approval-source-hash-mismatch",
        )
        shared.approval_text(fresh)
        require(
            "nothingwasresumedorexecuted" in fresh,
            "native-text-resume-disclaimer-missing",
        )
        passed(report, "freshness")

        edited = plan.read_bytes()
        plan.unlink()
        plan.symlink_to(project.outside)
        linked = native.command(f"/armory-brief reopen {first}", card_complete)
        plan.unlink()
        private_write(plan, edited)
        item = shared.field(shared.discrepancies(linked), "sources.plan")
        require(
            item["kind"] == "became-unknown" and item["current"] is None,
            # Source identities, not the link target, are the native evidence.
            "linked-source-not-refused",
        )
        require(
            'Unknownsources.plan:"rejected:' in linked
            and project.markers["outside"] not in linked,
            "linked-source-not-refused-or-followed",
        )
        native.stop()
        native = host(narrow)
        widened = native.command(
            f"/armory-brief reopen {first}",
            lambda segment: segment.startswith("ResumeBriefrejected"),
        )
        require(
            "differsfromtheconfiguredselection" in widened,
            "changed-selection-not-refused",
        )
        passed(report, "changed-during-run")

        shown = native.command(
            f"/armory-brief show {first}", lambda segment: "Authority:none." in segment
        )
        require(
            shared.evaluated_session(shown)
            not in {recorded_by["sessionId"], fresh_session},
            "transition-not-rebound",
        )
        require(not helpers_running(runtime), "owned-helper-outlived-command")
        native.stop()
        require(not helpers_running(runtime), "owned-helper-outlived-host")
        passed(report, "cancellation")

        require(
            len(shared.private_snapshots(project)) == 2, "reopen-or-show-wrote-state"
        )
        raw = b"".join(bytes(item.raw) for item in hosts)
        require(
            not any(marker.encode() in raw for marker in project.markers.values()),
            "source-body-rendered",
        )
        passed(report, "private-output")

        require(
            b"\x1b]0;SYNTHETIC-TITLE" not in raw and b"SYNTHETIC-TITLE\x07" not in raw,
            "native-text-raw-hostile",
        )
        answers = [answer for item in hosts for answer in item.answers]
        require(len(answers) == 8, "native-text-capture-cardinality")
        shared.common_text(project, fresh.split("Currentcard:", 1)[1])
        passed(report, "native-text")
        report["nativeTextCommands"] = [
            answer["command"].split(" ", 2)[:2] for answer in answers
        ]
        private_write(
            Path(args.report).with_suffix(".private.json"),
            json.dumps(
                {
                    "syntheticOnly": True,
                    "answers": answers,
                    "snapshots": shared.private_snapshots(project),
                    "terminalHex": [bytes(item.raw).hex() for item in hosts],
                }
            ),
        )
    finally:
        cleanup_proven = True
        report["_cleanupProven"] = False
        for native in reversed(hosts):
            try:
                native.stop()
            except (Failure, Unavailable, OSError):
                cleanup_proven = False
        try:
            if helpers_running(runtime):
                cleanup_proven = False
        except (Failure, Unavailable, OSError):
            cleanup_proven = False
        report["_cleanupProven"] = cleanup_proven
        capture = Path(args.report).with_suffix(".private.json")
        if not capture.exists():
            private_write(
                capture,
                json.dumps({"terminalHex": [bytes(item.raw).hex() for item in hosts]}),
            )
        if not cleanup_proven:
            raise Failure("native-cleanup-not-proven")


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
    root = Path(tempfile.mkdtemp(prefix="armory-rb-claude-", dir="/tmp")).resolve()
    report: JsonObject = {
        "schemaVersion": 1,
        "host": "claude",
        "mode": "interactive",
        "version": None,
        "status": "unavailable",
        "scenarios": [
            {"name": name, "status": "not-run", "assertion": shared.ASSERTIONS[name]}
            for name in SCENARIOS
        ],
        "usageInterpretation": "Only native commands submitted; not a model/network-call meter.",
        "notExercised": [
            "in-flight cancellation inside a live host (covered by deterministic adapter tests only)",
            "headless -p and SDK surfaces",
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
                report["status"] = "failed"
                report["reasonCode"] = "owned-scratch-cleanup-failed"
                code = 1
        else:
            report["ownedScratchRetainedForUnprovenCleanup"] = True
            report["status"] = "failed"
            report["reasonCode"] = "native-cleanup-not-proven"
            code = 1
    try:
        private_write(report_path, json.dumps(report, sort_keys=True, indent=2) + "\n")
    except OSError:
        report["status"] = "unavailable"
        report["reasonCode"] = "private-report-write-unavailable"
        code = 3
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
