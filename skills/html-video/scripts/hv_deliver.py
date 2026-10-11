"""Deliverability gate and bundle assembly.

A delivery is complete only when the editable source, every referenced asset,
the provenance and licence records, passing reports for the current source, and
an MP4 matching the render record all exist. Each report must also describe the
toolchain, config and fps that are in effect now: the environment is re-verified
here and compared with what every step recorded, and every report-bound artifact
(snapshots, contact sheet, MP4) is re-hashed. The bundle is re-audited after
copying, so a missing file cannot hide behind the original project directory.
Timestamps are informational and never decide correctness.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from hv_audit import AuditResult, Finding, audit_project, sha256_file
from hv_config import Config
from hv_env import verify_environment
from hv_run import (
    SNAPSHOT_DIR,
    StepContext,
    StepError,
    read_report,
    report_path,
    step_context,
    validate_fps,
)

REQUIRED_STEPS = ("lint", "check", "snapshot", "render")
RESERVED_NAMES = ("source", "snapshots", "reports", "RENDER.json")
PROJECT_MANIFESTS = (
    "package.json", "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb",
)  # fmt: skip
REPRODUCIBILITY_NOTE = (
    "Rendering is seek-driven from the source, but this record makes no byte-identity claim. "
    "Output depends on the recorded Hyperframes, browser, FFmpeg and operating system versions and on the font files."
)


@dataclass
class Delivery:
    ok: bool
    findings: list[Finding] = field(default_factory=lambda: list[Finding]())
    out: Path | None = None
    files: int = 0


def _fail(findings: list[Finding], code: str, message: str) -> None:
    findings.append(Finding(code, "error", message))


def _dict(value: object) -> dict[str, object]:
    return {str(k): v for k, v in value.items()} if isinstance(value, dict) else {}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]


def _detail(report: dict[str, object]) -> dict[str, object]:
    return _dict(report.get("detail"))


def _diff(recorded: object, current: object, path: str = "") -> list[str]:
    """Human-readable leaf differences between a recorded and the current context."""
    if isinstance(current, dict) and isinstance(recorded, dict):
        old, new = _dict(recorded), _dict(current)
        out: list[str] = []
        for key in sorted(set(old) | set(new)):
            out.extend(
                _diff(old.get(key), new.get(key), f"{path}.{key}" if path else key)
            )
        return out
    if recorded == current and type(recorded) is type(current):
        return []
    return [f"{path or 'value'}: recorded {recorded!r}, now {current!r}"]


def _same_fps(value: object, fps: int) -> bool:
    return type(value) is int and value == fps


def _context_findings(
    step: str, report: dict[str, object], context: StepContext
) -> list[Finding]:
    findings: list[Finding] = []
    rerun = f"re-run `run {step}`"
    if not _same_fps(report.get("fps"), context.fps) or not _same_fps(
        _detail(report).get("fps"), context.fps
    ):
        _fail(
            findings,
            "report_fps_mismatch",
            f"the {step} report used fps {report.get('fps')!r}, delivery requires {context.fps}; {rerun} (or deliver with the same --fps)",
        )
    for key, code, current in (
        ("environment", "report_environment_mismatch", context.environment),
        ("config", "report_config_mismatch", context.config),
    ):
        differences = _diff(report.get(key), current)
        if differences:
            _fail(
                findings,
                code,
                f"the {step} report {key} differs from the verified current {key} ({'; '.join(differences[:6])}); {rerun}",
            )
    return findings


def check_reports(
    project: Path, audit: AuditResult, context: StepContext | None
) -> tuple[dict[str, dict[str, object]], list[Finding]]:
    """Every required report must exist, have passed, and describe the current source,
    toolchain, config and fps.

    ``context`` is the freshly verified current context. It is None only when that
    verification failed, in which case the caller already holds a blocking finding.
    """
    findings: list[Finding] = []
    reports: dict[str, dict[str, object]] = {}
    closure = audit.closure_sha256()
    for step in REQUIRED_STEPS:
        report = read_report(project, step)
        if report is None:
            _fail(
                findings,
                "report_missing",
                f"no {step} report; run `html_video.py run {step}`",
            )
        elif report.get("step") != step:
            _fail(
                findings,
                "report_invalid",
                f"the {step} report records step {report.get('step')!r}; re-run `run {step}`",
            )
        elif report.get("closure_sha256") != closure:
            _fail(
                findings,
                "report_stale",
                f"the {step} report was recorded for different source; re-run `run {step}`",
            )
        elif report.get("ok") is not True:
            _fail(
                findings,
                "report_failed",
                f"the {step} report did not pass; fix and re-run `run {step}`",
            )
        elif context is not None and (
            mismatches := _context_findings(step, report, context)
        ):
            findings.extend(mismatches)
        else:
            reports[step] = report
    return reports, findings


def _current_context(
    project: Path, cfg: Config, fps: int | None, findings: list[Finding]
) -> StepContext | None:
    """Verify the environment now and describe it; blocking problems go to findings."""
    try:
        effective = validate_fps(cfg.fps if fps is None else fps)
    except StepError as exc:
        _fail(findings, "fps_invalid", str(exc))
        return None
    env, problems = verify_environment(project, cfg)
    for problem in problems:
        _fail(findings, "environment_invalid", problem)
    if env is None or problems:
        return None
    try:
        return step_context(project, cfg, env, effective)
    except StepError as exc:
        _fail(findings, "environment_invalid", str(exc))
        return None


def _verified_video(report: dict[str, object], findings: list[Finding]) -> Path | None:
    detail = _detail(report)
    raw = detail.get("output")
    video = Path(raw) if isinstance(raw, str) else None
    if video is None or not video.is_absolute() or not video.is_file():
        _fail(
            findings,
            "video_missing",
            "the rendered MP4 recorded by the render report no longer exists",
        )
        return None
    if video.name in RESERVED_NAMES:
        _fail(
            findings,
            "video_name_reserved",
            f"the MP4 is named {video.name}, which the bundle layout reserves",
        )
        return None
    digest, size = detail.get("sha256"), detail.get("bytes")
    if (
        not isinstance(digest, str)
        or sha256_file(video) != digest
        or video.stat().st_size != size
    ):
        _fail(
            findings,
            "video_changed",
            "the MP4 differs from the one recorded by the render report; re-render",
        )
        return None
    return video


def _verified_snapshots(
    project: Path, report: dict[str, object], findings: list[Finding]
) -> tuple[dict[str, str], dict[str, str]]:
    """Re-hash every recorded frame and every page of the contact sheets."""
    detail = _detail(report)
    frames = _dict(detail.get("frames"))
    times = detail.get("times")
    verified: dict[str, str] = {}
    if not frames or not isinstance(times, list) or len(times) != len(frames):
        _fail(
            findings,
            "snapshot_incomplete",
            "the snapshot report does not record one frame per sampled time; re-run `run snapshot`",
        )
        return verified, {}
    for rel, digest in sorted(frames.items()):
        recorded = Path(rel)
        path = project / rel
        if (
            recorded.parent.as_posix() != SNAPSHOT_DIR
            or not recorded.name.startswith("frame-")
            or recorded.suffix != ".png"
            or not isinstance(digest, str)
            or not path.is_file()
            or sha256_file(path) != digest
        ):
            _fail(
                findings,
                "snapshot_changed",
                f"snapshot {rel} is missing or changed; re-run `run snapshot`",
            )
        else:
            verified[rel] = digest
    on_disk = {
        p.relative_to(project).as_posix()
        for p in (project / SNAPSHOT_DIR).glob("frame-*.png")
    }
    if on_disk != set(frames):
        _fail(
            findings,
            "snapshot_changed",
            "the snapshot directory holds different frames than the snapshot report; re-run `run snapshot`",
        )
    sheets = _dict(detail.get("contact_sheets"))
    verified_sheets: dict[str, str] = {}
    if not sheets:
        _fail(
            findings,
            "snapshot_incomplete",
            "the snapshot report has no contact sheets; re-run `run snapshot`",
        )
    for rel, digest in sorted(sheets.items()):
        recorded = Path(rel)
        path = project / rel
        if (
            recorded.parent.as_posix() != SNAPSHOT_DIR
            or not recorded.name.startswith("contact-sheet")
            or recorded.suffix != ".jpg"
            or not isinstance(digest, str)
            or not path.is_file()
            or not path.resolve().is_relative_to(project.resolve())
            or sha256_file(path) != digest
        ):
            _fail(
                findings,
                "snapshot_changed",
                f"contact sheet {rel} is missing or changed",
            )
        else:
            verified_sheets[rel] = digest
    on_disk_sheets = {
        path.relative_to(project).as_posix()
        for path in (project / SNAPSHOT_DIR).glob("contact-sheet*.jpg")
    }
    if on_disk_sheets != set(sheets):
        _fail(
            findings,
            "snapshot_changed",
            "the contact-sheet pages differ from the snapshot report; re-run `run snapshot`",
        )
    return verified, verified_sheets


def _copy_checked(
    src: Path,
    dst: Path,
    expected: str,
    findings: list[Finding],
    copied: dict[str, str],
    key: str,
) -> None:
    """Copy and require the copy to carry the digest that was verified or recorded."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    digest = sha256_file(dst)
    if digest != expected:
        _fail(
            findings,
            "changed_during_delivery",
            f"{key} changed while it was being copied; nothing was delivered",
        )
    copied[key] = digest


def _spec(context: StepContext) -> str:
    hyperframes = _dict(context.environment.get("hyperframes"))
    return f"{hyperframes.get('package')}@{hyperframes.get('version')}"


def deliver(project: Path, out: Path, cfg: Config, fps: int | None = None) -> Delivery:
    """Assemble the bundle. ``fps`` is the fps every report must have used (config default)."""
    project = project.resolve()
    audit = audit_project(project, require_provenance=True)
    findings = [f for f in audit.findings if f.severity == "error"]
    context = _current_context(project, cfg, fps, findings)
    reports, report_findings = check_reports(project, audit, context)
    findings.extend(report_findings)

    video: Path | None = None
    snapshots: dict[str, str] = {}
    contact_sheets: dict[str, str] = {}
    if "render" in reports:
        video = _verified_video(reports["render"], findings)
    if "snapshot" in reports:
        snapshots, contact_sheets = _verified_snapshots(
            project, reports["snapshot"], findings
        )
    if findings or video is None or context is None:
        return Delivery(False, findings)

    if out.exists() and any(out.iterdir()):
        _fail(
            findings,
            "output_not_empty",
            f"{out} exists and is not empty; choose a new directory",
        )
        return Delivery(False, findings)
    source = out / "source"
    source.mkdir(parents=True, exist_ok=True)
    copied: dict[str, str] = {}
    for rel, asset in sorted(audit.files.items()):
        _copy_checked(
            project / asset.real,
            source / rel,
            asset.sha256,
            findings,
            copied,
            f"source/{rel}",
        )
    for name in PROJECT_MANIFESTS:
        if (project / name).is_file():
            shutil.copyfile(project / name, source / name)
            copied[f"source/{name}"] = sha256_file(source / name)
    render_detail = _detail(reports["render"])
    _copy_checked(
        video,
        out / video.name,
        str(render_detail.get("sha256")),
        findings,
        copied,
        video.name,
    )
    for rel, digest in snapshots.items():
        name = Path(rel).name
        _copy_checked(
            project / rel,
            out / "snapshots" / name,
            digest,
            findings,
            copied,
            f"snapshots/{name}",
        )
    for rel, digest in contact_sheets.items():
        name = Path(rel).name
        _copy_checked(
            project / rel,
            out / "snapshots" / name,
            digest,
            findings,
            copied,
            f"snapshots/{name}",
        )
    provenance: dict[str, object] = {}
    for step, report in reports.items():
        source_report = report_path(project, step)
        recorded = sha256_file(source_report)
        _copy_checked(
            source_report,
            out / "reports" / source_report.name,
            recorded,
            findings,
            copied,
            f"reports/{source_report.name}",
        )
        provenance[step] = {
            "sha256": recorded,
            "ok": report.get("ok"),
            "fps": report.get("fps"),
            "closure_sha256": report.get("closure_sha256"),
            "recorded_at": report.get("recorded_at"),
        }

    again = audit_project(source, require_provenance=True)
    for finding in again.findings:
        if finding.severity == "error":
            _fail(
                findings,
                "bundle_not_standalone",
                f"delivered source fails its own audit: {finding.message}",
            )
    if findings:
        for child in out.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        return Delivery(False, findings)

    check_detail = _detail(reports["check"])
    snapshot_detail = _detail(reports["snapshot"])
    record = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "hyperframes": _spec(context),
        "fps": context.fps,
        "environment": context.environment,
        "config": context.config,
        "video": video.name,
        "closure_sha256": audit.closure_sha256(),
        "reports": provenance,
        "lint": {"argv": _detail(reports["lint"]).get("argv")},
        "check": {
            k: check_detail.get(k) for k in ("argv", "requested_times", "strict")
        },
        "snapshot": {k: snapshot_detail.get(k) for k in ("argv", "times")},
        "render": {
            k: render_detail.get(k)
            for k in ("argv", "fps", "sha256", "bytes", "probe", "composition")
        },
        "warnings": [f.as_dict() for f in audit.findings if f.severity == "warning"],
        "files": dict(sorted(copied.items())),
        "reproducibility": REPRODUCIBILITY_NOTE,
    }
    (out / "RENDER.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    return Delivery(True, [], out, len(copied) + 1)
