#!/usr/bin/env python3
"""Run layout and finishing gate for a launch video rendered by html-video.

    launch_video.py start [--parent DIR]
    launch_video.py finish RUN_DIR --poster-at SECONDS [--min-seconds S] [--max-seconds S]

`start` creates the run directory. `finish` reads the html-video delivery in
RUN_DIR/delivery, verifies it, writes the poster and bakes it as frame 0, checks
that the share copy credits every attribution-licensed asset, and records the
result in LAUNCH.json. Outputs are staged and only moved into RUN_DIR when
every check passes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from fractions import Fraction
from html.parser import HTMLParser
from pathlib import Path

RUN_DIR_NAME = "launch-output"
DELIVERY_DIR = "delivery"
SHARE_COPY = "share-copy.txt"
OUTPUT_VIDEO = "launch.mp4"
POSTER = "poster.jpg"
CREDITS = "CREDITS.txt"
RECORD = "LAUNCH.json"
DEFAULT_MIN_SECONDS = 15.0
DEFAULT_MAX_SECONDS = 25.0
# Frame 0 must match the poster at least this closely after re-encoding.
POSTER_MIN_PSNR_DB = 30.0
_PSNR_AVERAGE = re.compile(r"PSNR .*average:(inf|[0-9.]+)")


class FinishError(Exception):
    """A finishing check failed; ``code`` is stable for callers."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Probe:
    width: int
    height: int
    frame_rate: str
    video_frames: int
    audio_streams: int
    duration_s: float

    @property
    def fps(self) -> Fraction:
        return Fraction(self.frame_rate)


@dataclass(frozen=True)
class Asset:
    path: str
    source: str
    license: str

    @property
    def needs_credit(self) -> bool:
        """Creative Commons BY-family licences require attribution."""
        return self.license.upper().startswith("CC-BY-")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tool(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise FinishError("tool_missing", f"{name} is not on PATH; install FFmpeg")
    return found


def _run(argv: list[str], code: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()
        raise FinishError(code, detail[-1] if detail else f"{argv[0]} failed")
    return result


def probe(video: Path) -> Probe:
    result = _run(
        [
            _tool("ffprobe"),
            "-v",
            "error",
            "-count_packets",
            "-show_entries",
            (
                "stream=codec_type,width,height,r_frame_rate,nb_read_packets"
                ":format=duration"
            ),
            "-of",
            "json",
            str(video),
        ],
        "probe_failed",
    )
    document = json.loads(result.stdout)
    streams = document.get("streams", [])
    videos = [s for s in streams if s.get("codec_type") == "video"]
    if len(videos) != 1:
        raise FinishError(
            "probe_failed",
            f"{video.name}: expected one video stream, found {len(videos)}",
        )
    stream = videos[0]
    try:
        return Probe(
            width=int(stream["width"]),
            height=int(stream["height"]),
            frame_rate=str(stream["r_frame_rate"]),
            video_frames=int(stream["nb_read_packets"]),
            audio_streams=sum(1 for s in streams if s.get("codec_type") == "audio"),
            duration_s=float(document["format"]["duration"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise FinishError(
            "probe_failed", f"{video.name}: incomplete probe ({exc})"
        ) from exc


class _AudioTags(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "audio":
            self.count += 1


def composition_audio_clips(source: Path) -> int:
    """Count `<audio>` clips across every HTML file of the delivered source."""
    total = 0
    for page in sorted(source.rglob("*.html")):
        parser = _AudioTags()
        parser.feed(page.read_text(encoding="utf-8"))
        total += parser.count
    return total


def read_assets(source: Path) -> list[Asset]:
    path = source / "PROVENANCE.json"
    if not path.is_file():
        raise FinishError("provenance_invalid", f"{path} is missing")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        return [
            Asset(
                path=str(a["path"]), source=str(a["source"]), license=str(a["license"])
            )
            for a in document["assets"]
        ]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise FinishError("provenance_invalid", f"{path}: {exc}") from exc


def _normalise(text: str) -> str:
    return " ".join(text.replace("-", " ").lower().split())


def missing_credits(share_copy: str, assets: list[Asset]) -> list[Asset]:
    """Return attribution-licensed assets the share copy does not credit.

    A credit names the asset's recorded source verbatim and its licence id,
    written either as the SPDX id (``CC-BY-4.0``) or spaced (``CC BY 4.0``).
    """
    text = _normalise(share_copy)
    return [
        asset
        for asset in assets
        if asset.needs_credit
        and (asset.source not in share_copy or _normalise(asset.license) not in text)
    ]


def credits_text(assets: list[Asset]) -> str:
    lines = ["# Assets in this launch video, as declared in PROVENANCE.json", ""]
    for asset in sorted(assets, key=lambda a: a.path):
        marker = " [credit required]" if asset.needs_credit else ""
        lines.append(f"{asset.path} | {asset.license} | {asset.source}{marker}")
    return "\n".join(lines) + "\n"


def poster_psnr(video: Path, poster: Path) -> float:
    """PSNR in dB between frame 0 of ``video`` and ``poster``; inf when identical."""
    result = _run(
        [
            _tool("ffmpeg"),
            "-v",
            "info",
            "-nostats",
            "-i",
            str(video),
            "-i",
            str(poster),
            "-lavfi",
            (
                "[0:v]trim=end_frame=1,setpts=PTS-STARTPTS,format=yuv420p[a];"
                "[1:v]format=yuv420p[b];[a][b]psnr"
            ),
            "-f",
            "null",
            "-",
        ],
        "poster_not_baked",
    )
    match = _PSNR_AVERAGE.search(result.stderr)
    if match is None:
        raise FinishError("poster_not_baked", "ffmpeg reported no PSNR for frame 0")
    return float(match.group(1))


@dataclass(frozen=True)
class Finished:
    outputs: dict[str, str]
    poster_psnr_db: float


def _load_delivery(run_dir: Path) -> tuple[Path, Path, str]:
    delivery = run_dir / DELIVERY_DIR
    record_path = delivery / "RENDER.json"
    if not record_path.is_file():
        raise FinishError(
            "render_record_missing",
            f"{record_path} is missing; run html-video deliver with --out {delivery}",
        )
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
        name = str(record["video"])
        expected = str(record["files"][name])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise FinishError("render_record_invalid", f"{record_path}: {exc}") from exc
    video = delivery / name
    if not video.is_file():
        raise FinishError("video_missing", f"{video} is missing")
    if sha256_file(video) != expected:
        raise FinishError(
            "video_digest_mismatch",
            f"{video.name} differs from RENDER.json; re-deliver",
        )
    return delivery, video, sha256_file(record_path)


def finish(
    run_dir: Path,
    poster_at: float,
    min_seconds: float = DEFAULT_MIN_SECONDS,
    max_seconds: float = DEFAULT_MAX_SECONDS,
) -> Finished:
    run_dir = run_dir.resolve()
    delivery, video, record_sha = _load_delivery(run_dir)
    source = delivery / "source"
    share_path = run_dir / SHARE_COPY
    if not share_path.is_file() or not share_path.read_text(encoding="utf-8").strip():
        raise FinishError("share_copy_missing", f"write {share_path} before finishing")
    share_copy = share_path.read_text(encoding="utf-8")

    before = probe(video)
    if not min_seconds <= before.duration_s <= max_seconds:
        raise FinishError(
            "duration_out_of_range",
            f"video is {before.duration_s:.2f}s; expected {min_seconds:g}-{max_seconds:g}s",
        )
    clips = composition_audio_clips(source)
    if clips and before.audio_streams == 0:
        raise FinishError(
            "audio_missing",
            f"composition has {clips} <audio> clip(s) but the MP4 is silent",
        )
    frame = 1 / before.fps
    if not 0 <= poster_at <= before.duration_s - float(frame):
        raise FinishError(
            "poster_out_of_range",
            f"--poster-at {poster_at} is outside 0-{before.duration_s - float(frame):.3f}s",
        )
    assets = read_assets(source)
    uncredited = missing_credits(share_copy, assets)
    if uncredited:
        names = ", ".join(f"{a.path} ({a.license}, {a.source})" for a in uncredited)
        raise FinishError(
            "credit_missing", f"{SHARE_COPY} must credit source and licence of: {names}"
        )

    ffmpeg = _tool("ffmpeg")
    with tempfile.TemporaryDirectory(prefix=".launch-staging-", dir=run_dir) as tmp:
        staging = Path(tmp)
        poster = staging / POSTER
        _run(
            [ffmpeg, "-v", "error", "-y", "-ss", f"{poster_at}", "-i", str(video)]
            + ["-frames:v", "1", "-q:v", "2", str(poster)],
            "poster_failed",
        )
        baked = staging / OUTPUT_VIDEO
        _run(
            [ffmpeg, "-v", "error", "-y", "-i", str(video), "-i", str(poster)]
            + ["-filter_complex", "[0:v][1:v]overlay=0:0:enable='eq(n,0)'[v]"]
            + ["-map", "[v]", "-map", "0:a?", "-fps_mode", "passthrough"]
            + [
                "-c:v",
                "libx264",
                "-crf",
                "18",
                "-preset",
                "slow",
                "-pix_fmt",
                "yuv420p",
            ]
            + ["-c:a", "copy", "-movflags", "+faststart", str(baked)],
            "bake_failed",
        )
        after = probe(baked)
        drift = abs(after.duration_s - before.duration_s)
        if (
            (after.width, after.height, after.frame_rate, after.video_frames)
            != (before.width, before.height, before.frame_rate, before.video_frames)
            or after.audio_streams != before.audio_streams
            or drift > float(frame)
        ):
            raise FinishError(
                "bake_mismatch",
                f"baked video differs from the render: {after} vs {before}",
            )
        psnr = poster_psnr(baked, poster)
        if psnr < POSTER_MIN_PSNR_DB:
            raise FinishError(
                "poster_not_baked", f"frame 0 matches the poster at only {psnr:.1f} dB"
            )
        (staging / CREDITS).write_text(credits_text(assets), encoding="utf-8")
        outputs = {
            name: sha256_file(staging / name)
            for name in (OUTPUT_VIDEO, POSTER, CREDITS)
        }
        outputs[SHARE_COPY] = sha256_file(share_path)
        record: dict[str, object] = {
            "version": 1,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "delivery": {
                "render_json_sha256": record_sha,
                "video": video.name,
                "video_sha256": sha256_file(video),
            },
            "poster_at": poster_at,
            "poster_psnr_db": psnr,
            "duration_range_s": [min_seconds, max_seconds],
            "probe": asdict(after),
            "credits_required": [asdict(a) for a in assets if a.needs_credit],
            "outputs": outputs,
        }
        (staging / RECORD).write_text(
            json.dumps(record, indent=2) + "\n", encoding="utf-8"
        )
        for name in (OUTPUT_VIDEO, POSTER, CREDITS, RECORD):
            (staging / name).replace(run_dir / name)
    return Finished(outputs=outputs, poster_psnr_db=psnr)


def start(parent: Path, now: datetime | None = None) -> Path:
    """Create the run directory; never reuse an existing one."""
    target = parent / RUN_DIR_NAME
    if target.exists():
        stamp = (now or datetime.now()).strftime("%Y-%m-%d-%H%M%S")
        target = parent / f"{RUN_DIR_NAME}-{stamp}"
    target.mkdir(parents=True, exist_ok=False)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="launch_video.py", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    start_cmd = commands.add_parser("start", help="create the run directory")
    start_cmd.add_argument("--parent", type=Path, default=Path.cwd())
    finish_cmd = commands.add_parser(
        "finish", help="poster, frame-0 bake, credits, record"
    )
    finish_cmd.add_argument("run_dir", type=Path)
    finish_cmd.add_argument("--poster-at", type=float, required=True)
    finish_cmd.add_argument("--min-seconds", type=float, default=DEFAULT_MIN_SECONDS)
    finish_cmd.add_argument("--max-seconds", type=float, default=DEFAULT_MAX_SECONDS)
    args = parser.parse_args(argv)

    if args.command == "start":
        try:
            print(start(args.parent))
        except FileExistsError as exc:
            print(f"ERROR   run_dir_exists: {exc}", file=sys.stderr)
            return 1
        return 0
    try:
        result = finish(
            args.run_dir, args.poster_at, args.min_seconds, args.max_seconds
        )
    except FinishError as exc:
        print(f"ERROR   {exc.code}: {exc}", file=sys.stderr)
        return 1
    for name, digest in sorted(result.outputs.items()):
        print(f"{name}  {digest}")
    print(f"poster frame 0 PSNR {result.poster_psnr_db:.1f} dB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
