#!/usr/bin/env python3
"""Offline-first HTML video authoring policy around a pinned Hyperframes CLI.

Provisioning (`bootstrap`) is separate from authoring and rendering. The bundled
templates render locally without network access; arbitrary project JavaScript
is not network-isolated.

    html_video.py init TEMPLATE DEST
    html_video.py bootstrap PROJECT (--browser-path PATH | --download-browser)
    html_video.py fonts add PROJECT --font-file F --family NAME --license-id ID --license-file L --source S
    html_video.py audit PROJECT [--require-provenance] [--deny-warnings] [--json]
    html_video.py plan PROJECT [--fps N] [--json]
    html_video.py run {lint,check,snapshot,render} PROJECT [--fps N]
    html_video.py deliver PROJECT --out DIR [--fps N]
    html_video.py doctor PROJECT [--json]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from hv_audit import AuditResult, Finding, audit_project
from hv_config import TEMPLATES_DIR, ConfigError, load_config
from hv_deliver import deliver
from hv_env import EnvError, bootstrap, verify_environment
from hv_fonts import DEFAULT_ALIAS, FontError, add_font
from hv_run import (
    ENTRY,
    StepError,
    StepOutcome,
    format_times,
    frame_times,
    run_check,
    run_lint,
    run_render,
    run_snapshot,
    validate_fps,
)


def _print_findings(findings: list[Finding]) -> None:
    for finding in findings:
        where = (
            f" ({finding.file}:{finding.line})"
            if finding.file and finding.line
            else f" ({finding.file})"
            if finding.file
            else ""
        )
        print(
            f"{finding.severity.upper():7} {finding.code}: {finding.message}{where}",
            file=sys.stderr,
        )


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2))


def _project(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_dir():
        raise SystemExit(f"error: project directory {path} does not exist")
    return path.resolve()


def _audit_payload(result: AuditResult) -> dict[str, object]:
    comp = result.composition
    return {
        "ok": result.ok,
        "findings": [f.as_dict() for f in result.findings],
        "files": {
            path: {"sha256": a.sha256, "bytes": a.size, "kind": a.kind}
            for path, a in sorted(result.files.items())
        },
        "closure_sha256": result.closure_sha256(),
        "composition": None
        if comp is None
        else {
            "width": comp.width,
            "height": comp.height,
            "duration": comp.duration,
            "clips": len(comp.clips),
            "animated": comp.animated,
            "has_text": comp.has_text,
        },
    }


# -- commands -------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    names = (
        sorted(p.name for p in TEMPLATES_DIR.iterdir() if p.is_dir())
        if TEMPLATES_DIR.is_dir()
        else []
    )
    if args.list:
        print("\n".join(names))
        return 0
    if args.template not in names:
        raise SystemExit(
            f"error: unknown template {args.template!r}; available: {', '.join(names)}"
        )
    if not args.dest:
        raise SystemExit("error: init needs a destination directory")
    dest = Path(args.dest).expanduser()
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise SystemExit(f"error: {dest} exists and is not an empty directory")
    shutil.copytree(TEMPLATES_DIR / args.template, dest, dirs_exist_ok=True)
    print(f"created {dest}")
    print(
        "next: fonts add (a font is required), bootstrap, audit, then run lint/check/snapshot/render"
    )
    return 0


def cmd_bootstrap(args: argparse.Namespace) -> int:
    cfg = load_config()
    env = bootstrap(
        _project(args.project),
        cfg,
        browser_path=Path(args.browser_path).expanduser()
        if args.browser_path
        else None,
        download_browser=args.download_browser,
    )
    _emit(env.as_dict())
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = load_config()
    env, problems = verify_environment(_project(args.project), cfg)
    if args.json:
        _emit(
            {
                "ok": not problems,
                "problems": problems,
                "environment": env.as_dict() if env else None,
            }
        )
    elif problems:
        for problem in problems:
            print(f"PROBLEM {problem}", file=sys.stderr)
    else:
        print(f"ok: {cfg.spec}, browser {env.browser.version if env else ''}")
    return 1 if problems else 0


def cmd_fonts_add(args: argparse.Namespace) -> int:
    record = add_font(
        _project(args.project),
        font_file=Path(args.font_file).expanduser(),
        family=args.family,
        license_id=args.license_id,
        license_file=Path(args.license_file).expanduser(),
        source=args.source,
        alias=args.alias,
        weight=args.weight,
        style=args.style,
        replace=args.replace,
    )
    print(
        f"provisioned {record.alias!r} {record.weight} {record.style}: {record.path} (sha256 {record.sha256[:12]}…)"
    )
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    result = audit_project(
        _project(args.project), ENTRY, require_provenance=args.require_provenance
    )
    failed = not result.ok or (args.deny_warnings and bool(result.warnings))
    if args.json:
        _emit(_audit_payload(result))
    else:
        _print_findings([f for f in result.findings if f.severity != "info"])
        print(
            f"{'FAIL' if failed else 'ok'}: {len(result.files)} files, {len(result.errors)} errors, {len(result.warnings)} warnings"
        )
    return 1 if failed else 0


def cmd_plan(args: argparse.Namespace) -> int:
    cfg = load_config()
    fps = validate_fps(args.fps if args.fps is not None else cfg.fps)
    result = audit_project(_project(args.project), ENTRY)
    if result.composition is None:
        _print_findings(result.errors)
        print("error: composition contract is invalid; no plan", file=sys.stderr)
        return 1
    times = frame_times(result.composition, fps, cfg.max_check_samples)
    if args.json:
        _emit({"fps": fps, "duration": result.composition.duration, "at": times})
    else:
        print(format_times(times))
    return 0


def _report(outcome: StepOutcome, as_json: bool) -> int:
    if as_json:
        _emit(
            {
                "step": outcome.step,
                "ok": outcome.ok,
                "findings": [f.as_dict() for f in outcome.findings],
                "detail": outcome.detail,
            }
        )
    else:
        _print_findings(outcome.findings)
        print(f"{'ok' if outcome.ok else 'FAIL'}: {outcome.step}")
        output = outcome.detail.get("output")
        if outcome.ok and isinstance(output, str):
            print(output)
    return 0 if outcome.ok else 1


def cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config()
    project = _project(args.project)
    fps = args.fps if args.fps is not None else cfg.fps
    if args.step == "lint":
        outcome = run_lint(project, cfg, fps)
    elif args.step == "check":
        outcome = run_check(project, cfg, fps, strict=args.strict)
    elif args.step == "snapshot":
        outcome = run_snapshot(project, cfg, fps)
    else:
        outcome = run_render(
            project, cfg, fps, Path(args.output).expanduser() if args.output else None
        )
    return _report(outcome, args.json)


def cmd_deliver(args: argparse.Namespace) -> int:
    result = deliver(
        _project(args.project), Path(args.out).expanduser(), load_config(), args.fps
    )
    _print_findings(result.findings)
    if result.ok:
        print(f"delivered {result.files} files to {result.out}")
    return 0 if result.ok else 1


# -- parser ---------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="html_video.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser(
        "init", help="copy a bundled template into a new project directory"
    )
    init.add_argument("template", nargs="?", default="")
    init.add_argument("dest", nargs="?", default="")
    init.add_argument("--list", action="store_true", help="list template names")
    init.set_defaults(handler=cmd_init)

    boot = sub.add_parser(
        "bootstrap",
        help="install the pinned CLI into the project and record the toolchain (the only network step)",
    )
    boot.add_argument("project")
    choice = boot.add_mutually_exclusive_group()
    choice.add_argument(
        "--browser-path",
        help="existing Chrome or chrome-headless-shell executable to pin",
    )
    choice.add_argument(
        "--download-browser",
        action="store_true",
        help="run the pinned CLI's `browser ensure` (downloads if needed)",
    )
    boot.set_defaults(handler=cmd_bootstrap)

    doctor = sub.add_parser("doctor", help="re-verify the recorded toolchain offline")
    doctor.add_argument("project")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(handler=cmd_doctor)

    fonts = sub.add_parser("fonts", help="font provisioning").add_subparsers(
        dest="fonts_command", required=True
    )
    add = fonts.add_parser(
        "add", help="copy a user-selected font and record its licence"
    )
    add.add_argument("project")
    add.add_argument(
        "--font-file",
        required=True,
        help="woff2, woff, ttf or otf file you are allowed to redistribute",
    )
    add.add_argument(
        "--family",
        required=True,
        help="the font's real family name, for the provenance record",
    )
    add.add_argument(
        "--license-id",
        required=True,
        help="SPDX id such as OFL-1.1, or LicenseRef-… for a custom licence",
    )
    add.add_argument(
        "--license-file", required=True, help="the licence text shipped with the font"
    )
    add.add_argument(
        "--source",
        required=True,
        help="where the font was obtained (URL or description)",
    )
    add.add_argument(
        "--alias",
        default=DEFAULT_ALIAS,
        help=f"CSS family the templates use (default {DEFAULT_ALIAS!r})",
    )
    add.add_argument(
        "--weight",
        default="400",
        help='CSS weight, or a range such as "100 900" for a variable font',
    )
    add.add_argument(
        "--style", default="normal", choices=("normal", "italic", "oblique")
    )
    add.add_argument(
        "--replace",
        action="store_true",
        help="replace an existing face with a different file",
    )
    add.set_defaults(handler=cmd_fonts_add)

    audit = sub.add_parser(
        "audit", help="offline asset, font, timing and provenance audit"
    )
    audit.add_argument("project")
    audit.add_argument(
        "--require-provenance",
        action="store_true",
        help="every non-document asset needs a provenance declaration",
    )
    audit.add_argument("--deny-warnings", action="store_true")
    audit.add_argument("--json", action="store_true")
    audit.set_defaults(handler=cmd_audit)

    plan = sub.add_parser(
        "plan", help="frame-aligned boundary sample times for check/snapshot"
    )
    plan.add_argument("project")
    plan.add_argument("--fps", type=int)
    plan.add_argument("--json", action="store_true")
    plan.set_defaults(handler=cmd_plan)

    step = sub.add_parser("run", help="audit-gated, pinned lint/check/snapshot/render")
    step.add_argument("step", choices=("lint", "check", "snapshot", "render"))
    step.add_argument("project")
    step.add_argument(
        "--fps", type=int, help="frames per second (default from config.toml)"
    )
    step.add_argument(
        "--strict", action="store_true", help="check only: fail on warnings too"
    )
    step.add_argument(
        "--output", help="render only: MP4 path (default renders/<project>.mp4)"
    )
    step.add_argument("--json", action="store_true")
    step.set_defaults(handler=cmd_run)

    out = sub.add_parser(
        "deliver", help="verify completeness and assemble the delivery bundle"
    )
    out.add_argument("project")
    out.add_argument(
        "--out", required=True, help="new or empty directory for the bundle"
    )
    out.add_argument(
        "--fps",
        type=int,
        help="effective FPS used for every run step (default from config.toml)",
    )
    out.set_defaults(handler=cmd_deliver)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (EnvError, StepError, FontError, ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
