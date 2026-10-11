"""Pinned lint, check, snapshot and render steps with coverage and output policy.

Each step first invalidates its previous report, then re-verifies the recorded
toolchain and audits the project, then invokes the project-local Hyperframes CLI
with fixed flags. A step records a report bound to the sha256 closure of the
project source, the verified toolchain identity, the complete relevant config and
the effective fps, so ``deliver`` can prove that every report and the MP4
describe the source, tools and settings being delivered. A failed or aborted
rerun can never leave an earlier passing report behind.
"""

from __future__ import annotations

import json
import math
import platform
import re
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path

from hv_audit import (
    AuditResult,
    Composition,
    Finding,
    Severity,
    audit_project,
    sha256_file,
)
from hv_config import Config
from hv_env import (
    EnvError,
    Environment,
    hyperframes,
    installed_cli,
    load_environment,
    run,
)

REPORT_DIR = ".html-video/reports"
SNAPSHOT_DIR = ".html-video/snapshots"
ENTRY = "index.html"
SAMPLE_TOLERANCE = 1e-3
RENDER_TIMEOUT_S = 3600
STEP_TIMEOUT_S = 600

# Known compiler outputs that mean a font was not resolved from provisioned local
# files. Only these exact signals are failures; other log noise is not inspected.
FONT_UNMAPPED = re.compile(r"no deterministic font mapping", re.IGNORECASE)
FONT_HOST = re.compile(r"https?://fonts\.(?:googleapis|gstatic)\.com", re.IGNORECASE)


class StepError(RuntimeError):
    """A step could not run (as opposed to running and finding problems)."""


@dataclass
class StepOutcome:
    step: str
    ok: bool
    findings: list[Finding] = field(default_factory=lambda: list[Finding]())
    detail: dict[str, object] = field(default_factory=lambda: dict[str, object]())


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------


def validate_fps(fps: int) -> int:
    if isinstance(fps, bool) or not 1 <= fps <= 120:
        raise StepError(f"fps must be an integer from 1 to 120, got {fps!r}")
    return fps


def frame_times(comp: Composition, fps: int, max_samples: int) -> list[float]:
    """Frame-aligned sample times at clip boundaries (before, at, after), midpoints and the ends.

    ``check --at-transitions`` derives boundaries from GSAP timelines only, so a
    CSS-animated composition needs explicit times. The ends are always kept.
    """
    validate_fps(fps)
    frames = max(1, round(comp.duration * fps))
    last = frames - 1

    def snap(seconds: float) -> int:
        return min(last, max(0, round(seconds * fps)))

    priority: list[int] = [0, last]
    exact: list[int] = []
    mids: list[int] = []
    near: list[int] = []
    for clip in comp.clips:
        edges = [clip.start] + ([clip.end] if clip.end is not None else [])
        for edge in edges:
            exact.append(snap(edge))
            near.extend((snap(edge) - 1, snap(edge) + 1))
        if clip.end is not None:
            mids.append(snap((clip.start + clip.end) / 2))
    ordered: list[int] = []
    for index in [*priority, *exact, *mids, *near]:
        index = min(last, max(0, index))
        if index not in ordered:
            ordered.append(index)
    kept = sorted(ordered[:max_samples])
    return [round(index / fps, 4) for index in kept]


def select_evenly(times: list[float], count: int) -> list[float]:
    if len(times) <= count:
        return list(times)
    picks = (
        {round(i * (len(times) - 1) / (count - 1)) for i in range(count)}
        if count > 1
        else {0}
    )
    return [times[i] for i in sorted(picks)]


def format_times(times: list[float]) -> str:
    return ",".join(f"{t:g}" for t in times)


# --------------------------------------------------------------------------
# Report parsing and coverage policy
# --------------------------------------------------------------------------


def parse_json_output(stdout: str) -> dict[str, object]:
    decoder = json.JSONDecoder()
    candidates = [0, *(m.start() for m in re.finditer(r"^\{", stdout, re.M))]
    for start in candidates:
        try:
            value, _ = decoder.raw_decode(stdout[start:].lstrip())
        except ValueError:
            continue
        if isinstance(value, dict):
            return {str(k): v for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    raise StepError("command did not print a JSON object")


def _section(report: dict[str, object], key: str) -> dict[str, object]:
    value = report.get(key)
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    return {}


def _count(section: dict[str, object], key: str) -> float:
    value = section.get(key)
    return (
        float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else 0.0
    )


def _times(section: dict[str, object], key: str) -> list[float]:
    value = section.get(key)
    if not isinstance(value, list):
        return []
    return [
        float(v)
        for v in value
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    ]  # pyright: ignore[reportUnknownVariableType]


def evaluate_check_report(
    report: dict[str, object],
    *,
    requested: list[float],
    animated: bool,
    has_text: bool,
    expected_version: str,
) -> list[Finding]:
    """Turn a ``check --json`` report into findings that prove (or disprove) coverage."""
    findings: list[Finding] = []

    def add(code: str, severity: Severity, message: str) -> None:
        findings.append(Finding(code, severity, message))

    failure = report.get("error")
    if isinstance(failure, str):
        add("check_error", "error", f"check could not run: {failure}")
        return findings
    meta = _section(report, "_meta")
    if meta.get("version") != expected_version:
        add(
            "check_version_mismatch",
            "error",
            f"check ran version {meta.get('version')!r}, expected {expected_version}",
        )
    sections = {
        name: _section(report, name)
        for name in ("lint", "runtime", "layout", "motion", "contrast")
    }
    if report.get("ok") is not True:
        counts = ", ".join(
            f"{n}={int(_count(s, 'errorCount'))}" for n, s in sections.items()
        )
        add("check_failed", "error", f"check reported errors ({counts})")
    warnings = int(sum(_count(s, "warningCount") for s in sections.values()))
    if warnings:
        add(
            "check_warnings",
            "warning",
            f"check reported {warnings} warning(s); read them in the report",
        )
    if report.get("browserSkipped") is not False:
        add(
            "browser_skipped",
            "error",
            "browser-backed checks did not run (browserSkipped is not false); layout, motion and contrast are unproven",
        )
    layout_samples = _times(sections["layout"], "samples")
    if not layout_samples:
        add(
            "no_layout_samples", "error", "layout.samples is empty; nothing was sampled"
        )
    else:
        missing = [
            t
            for t in requested
            if not any(abs(t - got) <= SAMPLE_TOLERANCE for got in layout_samples)
        ]
        if missing:
            add(
                "samples_missing",
                "error",
                f"requested sample times were not checked: {format_times(missing)}",
            )
    motion = sections["motion"]
    if animated and not (
        motion.get("enabled") is True and _count(motion, "samples") > 0
    ):
        add(
            "motion_unproven",
            "error",
            "the composition animates but motion checks did not run; add a *.motion.json sidecar with assertions",
        )
    contrast = sections["contrast"]
    if has_text:
        if not (contrast.get("enabled") is True and _count(contrast, "checked") > 0):
            add(
                "contrast_unproven",
                "error",
                "the composition has text but no contrast pair was checked",
            )
    else:
        add(
            "contrast_not_applicable",
            "warning",
            "no visible text: contrast was not proven",
        )
    return findings


def probe_render(env: Environment, video: Path) -> dict[str, object]:
    proc = run(
        [
            env.ffprobe.path, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,width,height,r_frame_rate,nb_frames,duration:format=duration",
            "-of", "json", str(video),
        ],
        timeout=60,
    )  # fmt: skip
    if proc.returncode != 0:
        raise StepError(f"ffprobe could not read {video}: {proc.stderr.strip()[-300:]}")
    return parse_json_output(proc.stdout)


def evaluate_render_probe(
    probe: dict[str, object], comp: Composition, fps: int
) -> list[Finding]:
    streams = probe.get("streams")
    stream = (
        _section({"s": streams[0]}, "s")
        if isinstance(streams, list) and streams
        else {}
    )  # pyright: ignore[reportUnknownArgumentType]
    findings: list[Finding] = []
    if not stream:
        return [Finding("render_mismatch", "error", "output has no video stream")]
    size = (stream.get("width"), stream.get("height"))
    if size != (comp.width, comp.height):
        findings.append(
            Finding(
                "render_mismatch",
                "error",
                f"output is {size[0]}x{size[1]}, composition declares {comp.width}x{comp.height}",
            )
        )
    try:
        rate = Fraction(str(stream.get("r_frame_rate")))
    except (ValueError, ZeroDivisionError):
        rate = Fraction(0)
    if abs(float(rate) - fps) > 0.01:
        findings.append(
            Finding(
                "render_mismatch",
                "error",
                f"output frame rate is {float(rate):g}, requested {fps}",
            )
        )
    raw_duration = stream.get("duration") or _section(probe, "format").get("duration")
    try:
        duration = float(str(raw_duration))
    except ValueError:
        duration = math.nan
    if not math.isfinite(duration) or abs(duration - comp.duration) > 1.5 / fps:
        findings.append(
            Finding(
                "render_mismatch",
                "error",
                f"output duration {raw_duration!r}s differs from declared {comp.duration:g}s",
            )
        )
    expected = round(comp.duration * fps)
    nb_frames = stream.get("nb_frames")
    if (
        isinstance(nb_frames, str)
        and nb_frames.isdigit()
        and abs(int(nb_frames) - expected) > 1
    ):
        findings.append(
            Finding(
                "render_mismatch",
                "error",
                f"output has {nb_frames} frames, expected about {expected}",
            )
        )
    return findings


# --------------------------------------------------------------------------
# Font resolution failures
# --------------------------------------------------------------------------


def font_findings(*streams: str) -> list[Finding]:
    """Error findings for the compiler's known unresolved/fetched-font signals."""
    findings: list[Finding] = []
    for code, pattern, meaning in (
        (
            "font_unmapped",
            FONT_UNMAPPED,
            "Hyperframes found a font family with no deterministic mapping to a provisioned local @font-face; "
            "declare the family with an inline @font-face in index.html pointing at the provisioned font file",
        ),
        (
            "font_network_fetch",
            FONT_HOST,
            "Hyperframes output references a Google Fonts host, so a font may have been fetched instead of read from provisioned files",
        ),
    ):
        line = next(
            (
                text.strip()
                for stream in streams
                for text in stream.splitlines()
                if pattern.search(text)
            ),
            None,
        )
        if line is not None:
            findings.append(Finding(code, "error", f"{meaning}: {line[:240]}"))
    return findings


# --------------------------------------------------------------------------
# Reports bound to source closure, toolchain, config and fps
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class StepContext:
    """Everything besides the source that a step result depends on."""

    fps: int
    environment: dict[str, object]
    config: dict[str, object]


def _canonical(value: dict[str, object]) -> dict[str, object]:
    """JSON round trip so in-memory and stored contexts compare equal."""
    loaded: object = json.loads(json.dumps(value, sort_keys=True))
    return {str(k): v for k, v in loaded.items()} if isinstance(loaded, dict) else {}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]


def config_binding(cfg: Config) -> dict[str, object]:
    """Every config value that can change a step's result, except the default fps.

    fps is bound separately as the effective value, so changing the config default
    does not invalidate reports that were produced with an explicit fps.
    """
    return _canonical(
        {
            "package": cfg.package,
            "version": cfg.version,
            "node_min_major": cfg.node_min_major,
            "workers": cfg.workers,
            "check_timeout_ms": cfg.check_timeout_ms,
            "max_check_samples": cfg.max_check_samples,
            "snapshot_frames": cfg.snapshot_frames,
            "forced_env": dict(cfg.forced_env),
            "scrubbed_env": sorted(cfg.scrubbed_env),
        }
    )


def environment_binding(
    project: Path, cfg: Config, env: Environment
) -> dict[str, object]:
    """Identity of the toolchain a step ran with; ``env`` must already be verified."""
    current = f"{platform.system().lower()}-{platform.machine().lower()}"
    if env.platform and env.platform != current:
        raise StepError(
            f"environment was bootstrapped on {env.platform} but this is {current}; re-run bootstrap"
        )
    try:
        cli, _ = installed_cli(project, cfg)
        if (project / env.cli).resolve() != cli:
            raise StepError(
                f"environment records CLI {env.cli} but the installed {cfg.package} CLI is {cli}; re-run bootstrap"
            )
        cli_digest = sha256_file(cli)
    except (EnvError, OSError) as exc:
        raise StepError(str(exc)) from exc
    return _canonical(
        {
            "platform": current,
            "hyperframes": {
                "package": env.package,
                "version": env.hyperframes_version,
                "cli": env.cli,
                "cli_sha256": cli_digest,
                "package_manager": env.package_manager,
            },
            "node": {"path": env.node.path, "version": env.node.version},
            "ffmpeg": {"path": env.ffmpeg.path, "version": env.ffmpeg.version},
            "ffprobe": {"path": env.ffprobe.path, "version": env.ffprobe.version},
            "browser": {
                "path": env.browser.path,
                "version": env.browser.version,
                "source": env.browser.source,
            },
        }
    )


def step_context(
    project: Path, cfg: Config, env: Environment, fps: int | None = None
) -> StepContext:
    """Context for a verified environment; ``fps`` defaults to the config value."""
    effective = validate_fps(cfg.fps if fps is None else fps)
    return StepContext(
        effective, environment_binding(project, cfg, env), config_binding(cfg)
    )


def report_path(project: Path, step: str) -> Path:
    return project / REPORT_DIR / f"{step}.json"


def invalidate_report(project: Path, step: str) -> None:
    """Remove the previous report so a failed or aborted rerun cannot keep it valid."""
    report_path(project, step).unlink(missing_ok=True)


def write_report(
    project: Path, outcome: StepOutcome, audit: AuditResult, context: StepContext
) -> None:
    path = report_path(project, outcome.step)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "step": outcome.step,
        "ok": outcome.ok,
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "closure_sha256": audit.closure_sha256(),
        "fps": context.fps,
        "environment": context.environment,
        "config": context.config,
        "findings": [f.as_dict() for f in outcome.findings],
        "detail": outcome.detail,
    }
    pending = path.with_name(f"{path.name}.tmp")
    pending.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    pending.replace(path)


def read_report(project: Path, step: str) -> dict[str, object] | None:
    path = report_path(project, step)
    if not path.is_file():
        return None
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return {str(k): v for k, v in raw.items()} if isinstance(raw, dict) else None  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]


# --------------------------------------------------------------------------
# Steps
# --------------------------------------------------------------------------


def prepare(project: Path, cfg: Config) -> tuple[Environment, AuditResult]:
    try:
        env = load_environment(project, cfg)
    except EnvError as exc:
        raise StepError(str(exc)) from exc
    return env, audit_project(project, ENTRY)


def _begin(
    project: Path, cfg: Config, step: str, fps: int | None
) -> tuple[Environment, AuditResult, StepContext]:
    """Invalidate the old report first, then verify toolchain, fps and source."""
    invalidate_report(project, step)
    effective = validate_fps(cfg.fps if fps is None else fps)
    env, audit = prepare(project, cfg)
    return env, audit, step_context(project, cfg, env, effective)


def _finish(
    project: Path, outcome: StepOutcome, audit: AuditResult, context: StepContext
) -> StepOutcome:
    """Refuse a pass if the source moved while the step ran, then record the report."""
    if audit_project(project, ENTRY).closure_sha256() != audit.closure_sha256():
        outcome.findings.append(
            Finding(
                "source_changed",
                "error",
                f"the project source changed while {outcome.step} ran; re-run it",
            )
        )
        outcome.ok = False
    write_report(project, outcome, audit, context)
    return outcome


def _blocked(step: str, audit: AuditResult) -> StepOutcome:
    return StepOutcome(
        step,
        False,
        [f for f in audit.findings if f.severity == "error"],
        {"blocked_by": "audit"},
    )


def _composition(audit: AuditResult) -> Composition:
    if audit.composition is None:
        raise StepError(
            "composition contract is invalid; run `audit` and fix the errors"
        )
    return audit.composition


def _lint_json(
    project: Path, cfg: Config, env: Environment, argv: list[str]
) -> tuple[dict[str, object], int]:
    proc = hyperframes(project, cfg, env, argv, STEP_TIMEOUT_S)
    try:
        return parse_json_output(proc.stdout), proc.returncode
    except StepError as exc:
        raise StepError(
            f"lint produced no JSON: {(proc.stderr or proc.stdout).strip()[-400:]}"
        ) from exc


def run_lint(project: Path, cfg: Config, fps: int | None = None) -> StepOutcome:
    env, audit, context = _begin(project, cfg, "lint", fps)
    if not audit.ok:
        return _finish(project, _blocked("lint", audit), audit, context)
    argv = ["lint", "--json", "."]
    report, code = _lint_json(project, cfg, env, argv)
    findings: list[Finding] = []
    meta = _section(report, "_meta")
    if meta.get("version") != cfg.version:
        findings.append(
            Finding(
                "lint_version_mismatch",
                "error",
                f"lint ran version {meta.get('version')!r}, expected {cfg.version}",
            )
        )
    errors, warnings = (
        int(_count(report, "errorCount")),
        int(_count(report, "warningCount")),
    )
    if errors or code != 0:
        findings.append(
            Finding(
                "lint_failed",
                "error",
                f"lint reported {errors} error(s), exit code {code}",
            )
        )
    if warnings:
        findings.append(
            Finding("lint_warnings", "warning", f"lint reported {warnings} warning(s)")
        )
    outcome = StepOutcome(
        "lint",
        not any(f.severity == "error" for f in findings),
        findings,
        {"argv": argv, "fps": context.fps, "report": report},
    )
    return _finish(project, outcome, audit, context)


def run_check(
    project: Path, cfg: Config, fps: int | None = None, strict: bool = False
) -> StepOutcome:
    env, audit, context = _begin(project, cfg, "check", fps)
    if not audit.ok:
        return _finish(project, _blocked("check", audit), audit, context)
    comp = _composition(audit)
    if comp.animated and not audit.has_motion_sidecar:
        finding = Finding(
            "motion_spec_missing",
            "error",
            "animated composition needs index.motion.json so `check` can prove motion",
        )
        outcome = StepOutcome("check", False, [finding], {"blocked_by": "motion_spec"})
        return _finish(project, outcome, audit, context)
    times = frame_times(comp, context.fps, cfg.max_check_samples)
    argv = [
        "check",
        "--json",
        "--no-browser-gpu",
        "--at",
        format_times(times),
        "--timeout",
        str(cfg.check_timeout_ms),
    ]
    if strict:
        argv.append("--strict")
    argv.append(".")
    proc = hyperframes(project, cfg, env, argv, STEP_TIMEOUT_S)
    try:
        report = parse_json_output(proc.stdout)
    except StepError as exc:
        raise StepError(
            f"check produced no JSON: {(proc.stderr or proc.stdout).strip()[-400:]}"
        ) from exc
    findings = evaluate_check_report(
        report,
        requested=times,
        animated=comp.animated,
        has_text=comp.has_text,
        expected_version=cfg.version,
    )
    # stdout is the JSON report, which may legitimately quote lint messages.
    findings.extend(font_findings(proc.stderr))
    outcome = StepOutcome(
        "check",
        not any(f.severity == "error" for f in findings),
        findings,
        {
            "argv": argv,
            "fps": context.fps,
            "requested_times": times,
            "strict": strict,
            "report": report,
        },
    )
    return _finish(project, outcome, audit, context)


def run_snapshot(project: Path, cfg: Config, fps: int | None = None) -> StepOutcome:
    env, audit, context = _begin(project, cfg, "snapshot", fps)
    if not audit.ok:
        return _finish(project, _blocked("snapshot", audit), audit, context)
    comp = _composition(audit)
    times = select_evenly(
        frame_times(comp, context.fps, cfg.max_check_samples), cfg.snapshot_frames
    )
    out_dir = project / SNAPSHOT_DIR
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    argv = [
        "snapshot",
        "--at",
        format_times(times),
        "--no-end",
        "--describe",
        "false",
        "--no-browser-gpu",
        "-o",
        str(out_dir),
        ".",
    ]
    proc = hyperframes(project, cfg, env, argv, STEP_TIMEOUT_S)
    frames = sorted(out_dir.glob("frame-*.png"))
    findings: list[Finding] = []
    if proc.returncode != 0:
        findings.append(
            Finding(
                "snapshot_failed",
                "error",
                f"snapshot exited {proc.returncode}: {(proc.stderr or proc.stdout).strip()[-300:]}",
            )
        )
    elif len(frames) != len(times):
        findings.append(
            Finding(
                "snapshot_incomplete",
                "error",
                f"expected {len(times)} frames, found {len(frames)}",
            )
        )
    findings.extend(font_findings(proc.stdout, proc.stderr))
    sheets = sorted(out_dir.glob("contact-sheet*.jpg"))
    if not sheets:
        findings.append(
            Finding(
                "snapshot_incomplete",
                "error",
                "snapshot produced no contact-sheet pages",
            )
        )
    detail: dict[str, object] = {
        "argv": argv,
        "fps": context.fps,
        "times": times,
        "frames": {f.relative_to(project).as_posix(): sha256_file(f) for f in frames},
        "contact_sheets": {
            sheet.relative_to(project).as_posix(): sha256_file(sheet)
            for sheet in sheets
        },
    }
    outcome = StepOutcome(
        "snapshot", not any(f.severity == "error" for f in findings), findings, detail
    )
    return _finish(project, outcome, audit, context)


def run_render(
    project: Path, cfg: Config, fps: int | None = None, output: Path | None = None
) -> StepOutcome:
    env, audit, context = _begin(project, cfg, "render", fps)
    if not audit.ok:
        return _finish(project, _blocked("render", audit), audit, context)
    comp = _composition(audit)
    root = project.resolve()
    target = (
        output if output is not None else root / "renders" / f"{root.name}.mp4"
    ).resolve()
    if target.is_dir() or target.suffix.lower() != ".mp4":
        raise StepError("render destination must be an MP4 file, not a directory")
    target_relative = (
        target.relative_to(root).as_posix() if target.is_relative_to(root) else None
    )
    if target_relative is not None and any(
        asset.real == target_relative
        for assets in (audit.assets, audit.extra_files)
        for asset in assets.values()
    ):
        raise StepError("render destination collides with an audited input file")
    if (output is None or target.is_relative_to(root)) and not target.is_relative_to(
        root / "renders"
    ):
        raise StepError("project render destinations must stay inside renders/")
    findings: list[Finding] = []
    if abs(comp.duration * context.fps - round(comp.duration * context.fps)) > 1e-6:
        findings.append(
            Finding(
                "fractional_frames",
                "warning",
                f"{comp.duration:g}s at {context.fps} fps is not a whole number of frames",
            )
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    argv = [
        "render",
        "--strict",
        "--no-best-effort",
        "--no-browser-gpu",
        "--workers",
        str(cfg.workers),
        "--fps",
        str(context.fps),
        "-o",
        str(target),
        ".",
    ]
    proc = hyperframes(project, cfg, env, argv, RENDER_TIMEOUT_S)
    detail: dict[str, object] = {
        "argv": argv,
        "fps": context.fps,
        "output": str(target),
    }
    findings.extend(font_findings(proc.stdout, proc.stderr))
    if proc.returncode != 0 or not target.is_file():
        findings.append(
            Finding(
                "render_failed",
                "error",
                f"render exited {proc.returncode}: {(proc.stderr or proc.stdout).strip()[-400:]}",
            )
        )
        failed = StepOutcome("render", False, findings, detail)
        return _finish(project, failed, audit, context)
    probe = probe_render(env, target)
    findings.extend(evaluate_render_probe(probe, comp, context.fps))
    detail.update(
        {
            "sha256": sha256_file(target),
            "bytes": target.stat().st_size,
            "probe": probe,
            "composition": {
                "width": comp.width,
                "height": comp.height,
                "duration": comp.duration,
            },
        }
    )
    outcome = StepOutcome(
        "render", not any(f.severity == "error" for f in findings), findings, detail
    )
    return _finish(project, outcome, audit, context)
