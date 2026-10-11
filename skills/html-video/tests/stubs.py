"""A local fake toolchain so the real step runner and delivery gate run end to end.

The stubs stand in for the pinned Hyperframes CLI, Node, FFmpeg/ffprobe and the
browser. They are real executables that ``verify_environment``, ``run_*`` and
``deliver`` invoke exactly as they would the genuine tools; no network is used.
Behaviour is steered per test through a JSON control file.
"""

from __future__ import annotations

import json
import platform
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from helpers import template_project, write
from hv_audit import audit_project
from hv_config import Config
from hv_run import StepOutcome, run_check, run_lint, run_render, run_snapshot

NODE_VERSION = "v22.1.0"
FFMPEG_VERSION = "ffmpeg version stub-1"
FFPROBE_VERSION = "ffprobe version stub-1"
BROWSER_VERSION = "StubChrome 1.0"
CLI_REL = "node_modules/hyperframes/bin/hyperframes.mjs"

STUB_CLI = """\
import json
import os
import sys
from pathlib import Path

control_path = Path(os.environ["HV_STUB_CONTROL"])
ctl = json.loads(control_path.read_text()) if control_path.is_file() else {}
args = sys.argv[1:]
command = args[0]


def opt(name):
    return args[args.index(name) + 1]


mutate = ctl.get("mutate_source")
if mutate and command in mutate["during"]:
    with open(mutate["path"], "a", encoding="utf-8") as handle:
        handle.write(mutate["text"])
if command in ctl.get("fail", []):
    print("stub failure", file=sys.stderr)
    sys.exit(3)
version = ctl["version"]
if command == "lint":
    print(json.dumps({"errorCount": 0, "warningCount": 0, "_meta": {"version": version}}))
elif command == "check":
    times = [float(t) for t in opt("--at").split(",")]
    section = {"errorCount": 0, "warningCount": 0}
    print(json.dumps({
        "ok": True,
        "browserSkipped": False,
        "lint": dict(section),
        "runtime": dict(section),
        "layout": {**section, "samples": times},
        "motion": {**section, "enabled": True, "samples": 61},
        "contrast": {**section, "enabled": True, "checked": 6, "passed": 6},
        "_meta": {"version": version},
    }))
elif command == "snapshot":
    out = Path(opt("-o"))
    for index, _ in enumerate(opt("--at").split(",")):
        (out / f"frame-{index:02d}.png").write_bytes(b"png" + str(index).encode())
    (out / "contact-sheet-1.jpg").write_bytes(b"jpg1")
    (out / "contact-sheet-2.jpg").write_bytes(b"jpg2")
elif command == "render":
    if ctl.get("font_warning"):
        print("[WARN] [Compiler] No deterministic font mapping for: HV Text", file=sys.stderr)
    if ctl.get("benign_warning"):
        print("[WARN] [Compiler] timeline has no explicit end; using data-duration", file=sys.stderr)
    Path(opt("-o")).write_bytes(b"stub video fps=" + opt("--fps").encode() + ctl.get("video_tag", "").encode())
else:
    print("unknown stub command " + command, file=sys.stderr)
    sys.exit(2)
"""


def _executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


@dataclass
class Rig:
    """A template project wired to the stub toolchain."""

    project: Path
    scratch: Path
    cfg: Config

    @property
    def control_path(self) -> Path:
        return self.scratch / "control.json"

    def control(self, **values: object) -> None:
        """Replace the stub behaviour; the pinned version is always supplied."""
        document = {"version": self.cfg.version, **values}
        self.control_path.write_text(json.dumps(document), encoding="utf-8")

    def set_probe(self, fps: int) -> None:
        """What ffprobe reports for the rendered MP4, consistent with the composition."""
        comp = audit_project(self.project).composition
        assert comp is not None
        duration = f"{comp.duration:f}"
        document = {
            "streams": [
                {
                    "codec_name": "h264",
                    "width": comp.width,
                    "height": comp.height,
                    "r_frame_rate": f"{fps}/1",
                    "nb_frames": str(round(comp.duration * fps)),
                    "duration": duration,
                }
            ],
            "format": {"duration": duration},
        }
        (self.scratch / "probe.json").write_text(json.dumps(document), encoding="utf-8")

    def write_browser(self, version: str) -> None:
        _executable(self.scratch / "bin" / "chrome", f'#!/bin/sh\necho "{version}"\n')

    def write_lock(self, browser_version: str = BROWSER_VERSION) -> None:
        """Record the toolchain as `bootstrap` would, matching what the stubs print."""
        bin_dir = self.scratch / "bin"
        document = {
            "schema": 1,
            "recorded_at": "2000-01-01T00:00:00+00:00",
            "platform": f"{platform.system().lower()}-{platform.machine().lower()}",
            "hyperframes": {
                "package": self.cfg.package,
                "version": self.cfg.version,
                "cli": CLI_REL,
                "package_manager": "npm",
            },
            "node": {"path": str(bin_dir / "node"), "version": NODE_VERSION},
            "ffmpeg": {"path": str(bin_dir / "ffmpeg"), "version": FFMPEG_VERSION},
            "ffprobe": {"path": str(bin_dir / "ffprobe"), "version": FFPROBE_VERSION},
            "browser": {
                "path": str(bin_dir / "chrome"),
                "version": browser_version,
                "source": "user-path",
            },
        }
        write(self.project, ".html-video/environment.json", json.dumps(document))

    def rebootstrap_browser(self, version: str) -> None:
        """A different browser, re-verified and re-recorded like `bootstrap --browser-path`."""
        self.write_browser(version)
        self.write_lock(version)

    def replace_cli(self, text: str) -> None:
        """Swap the installed CLI file without touching the recorded lock."""
        (self.project / CLI_REL).write_text(text, encoding="utf-8")

    def run_all(self, fps: int | None = None) -> dict[str, StepOutcome]:
        if fps is not None:
            self.set_probe(fps)
        outcomes = {
            "lint": run_lint(self.project, self.cfg, fps),
            "check": run_check(self.project, self.cfg, fps),
            "snapshot": run_snapshot(self.project, self.cfg, fps),
            "render": run_render(self.project, self.cfg, fps),
        }
        for step, outcome in outcomes.items():
            assert outcome.ok, (step, outcome.findings)
        return outcomes


def make_rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cfg: Config) -> Rig:
    """A font-provisioned template project, stub tools and a matching environment lock."""
    project = template_project(tmp_path, "title-sequence")
    scratch = tmp_path / "scratch"
    bin_dir = scratch / "bin"
    _executable(
        bin_dir / "node",
        f'#!/bin/sh\nif [ "$1" = "--version" ]; then echo {NODE_VERSION}; exit 0; fi\n'
        f'exec "{sys.executable}" "$@"\n',
    )
    _executable(bin_dir / "ffmpeg", f'#!/bin/sh\necho "{FFMPEG_VERSION}"\n')
    _executable(
        bin_dir / "ffprobe",
        f'#!/bin/sh\nif [ "$1" = "-version" ]; then echo "{FFPROBE_VERSION}"; exit 0; fi\n'
        f'cat "{scratch / "probe.json"}"\n',
    )
    write(
        project,
        f"node_modules/{cfg.package}/package.json",
        json.dumps(
            {"name": cfg.package, "version": cfg.version, "bin": "bin/hyperframes.mjs"}
        ),
    )
    write(project, CLI_REL, STUB_CLI)
    rig = Rig(project, scratch, cfg)
    rig.write_browser(BROWSER_VERSION)
    rig.write_lock()
    rig.control()
    rig.set_probe(cfg.fps)
    monkeypatch.setenv("HV_STUB_CONTROL", str(rig.control_path))
    return rig
