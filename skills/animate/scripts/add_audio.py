"""
add_audio.py — ffmpeg wrapper for audio overlay on rendered Manim videos.

Usage:
    python3 scripts/add_audio.py video.mp4 audio.mp3 --output final.mp4
    python3 scripts/add_audio.py video.mp4 audio.mp3 --output final.mp4 --volume 0.3
    python3 scripts/add_audio.py video.mp4 audio.mp3 --output final.mp4 --fade-in 2 --fade-out 3
    python3 scripts/add_audio.py video.mp4 audio.mp3 --output final.mp4 --trim-to-video
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from _deps import MissingDependencyError, require_binary


def build_ffmpeg_command(
    video: Path,
    audio: Path,
    output: Path,
    volume: float,
    fade_in: float,
    fade_out: float,
    trim_to_video: bool,
) -> list[str]:
    """Build the ffmpeg command for audio overlay."""
    # Build audio filter chain
    filters: list[str] = []

    if volume != 1.0:
        filters.append(f"volume={volume}")

    if trim_to_video:
        # Get video duration first
        duration = get_video_duration(video)
        filters.append(f"atrim=0:{duration}")

    if fade_in > 0:
        filters.append(f"afade=t=in:st=0:d={fade_in}")

    if fade_out > 0:
        if trim_to_video:
            duration = get_video_duration(video)
            fade_start = max(0.0, duration - fade_out)
            filters.append(f"afade=t=out:st={fade_start:.3f}:d={fade_out}")
        else:
            filters.append(f"afade=t=out:st=0:d={fade_out}")

    audio_filter = ",".join(filters) if filters else "anull"

    cmd = [
        "ffmpeg",
        "-y",  # overwrite output without asking
        "-i",
        str(video),  # input video
        "-i",
        str(audio),  # input audio
        "-filter_complex",
        f"[1:a]{audio_filter}[aout]",
        "-map",
        "0:v",  # video from first input
        "-map",
        "[aout]",  # filtered audio
        "-c:v",
        "copy",  # copy video stream (no re-encode)
        "-c:a",
        "aac",  # encode audio as AAC
        "-shortest",  # end at shortest stream
        str(output),
    ]

    return cmd


def get_video_duration(video: Path) -> float:
    """Return video duration in seconds using ffprobe."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Overlay audio onto a Manim-rendered video using ffmpeg."
    )
    parser.add_argument("video", type=Path, help="Input video file (MP4)")
    parser.add_argument(
        "audio", type=Path, help="Audio file to overlay (MP3, WAV, etc.)"
    )
    parser.add_argument(
        "--output", "-o", type=Path, required=True, help="Output video file"
    )
    parser.add_argument(
        "--volume",
        type=float,
        default=1.0,
        help="Audio volume multiplier (default: 1.0, use 0.3 for background music)",
    )
    parser.add_argument(
        "--fade-in",
        type=float,
        default=0.0,
        help="Fade-in duration in seconds (default: 0, no fade)",
    )
    parser.add_argument(
        "--fade-out",
        type=float,
        default=0.0,
        help="Fade-out duration in seconds (default: 0, no fade)",
    )
    parser.add_argument(
        "--trim-to-video",
        action="store_true",
        help="Trim audio to match video length (default: ffmpeg uses -shortest)",
    )

    args = parser.parse_args()

    # Validate inputs
    if not args.video.exists():
        print(f"Error: video file not found: {args.video}", file=sys.stderr)
        sys.exit(1)

    if not args.audio.exists():
        print(f"Error: audio file not found: {args.audio}", file=sys.stderr)
        sys.exit(1)

    if args.volume <= 0:
        print(f"Error: --volume must be > 0, got {args.volume}", file=sys.stderr)
        sys.exit(1)

    try:
        require_binary("ffmpeg")
        require_binary("ffprobe")
    except MissingDependencyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Ensure output directory exists
    args.output.parent.mkdir(parents=True, exist_ok=True)

    cmd = build_ffmpeg_command(
        video=args.video,
        audio=args.audio,
        output=args.output,
        volume=args.volume,
        fade_in=args.fade_in,
        fade_out=args.fade_out,
        trim_to_video=args.trim_to_video,
    )

    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=False)

    if result.returncode != 0:
        print(f"Error: ffmpeg exited with code {result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)

    print(f"Done: {args.output}")


if __name__ == "__main__":
    main()
