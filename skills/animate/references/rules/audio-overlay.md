# Audio Overlay

Add background music, voiceover, or sound effects to a rendered Manim video using ffmpeg. Manim itself renders silent MP4s — audio is applied as a post-processing step.

## When to use

- User wants background music on the final video
- User has a recorded voiceover to sync with the animation
- User wants to combine multiple audio tracks (music + narration)

## Basic overlay

The simplest case: add a single audio file to a video.

```bash
python3 scripts/add_audio.py scene_output.mp4 music.mp3 --output final.mp4
```

## Background music with volume ducking

Lower the music volume so it doesn't overpower narration.

```bash
python3 scripts/add_audio.py scene_output.mp4 background.mp3 \
    --output final.mp4 \
    --volume 0.25 \
    --fade-in 2 \
    --fade-out 3 \
    --trim-to-video
```

## Voiceover alignment

Voiceover must be pre-recorded and trimmed to match the animation timing before overlay.

```bash
# Trim voiceover to exactly match video length, then overlay
python3 scripts/add_audio.py scene_output.mp4 voiceover.mp3 \
    --output final_with_voice.mp4 \
    --trim-to-video
```

## Two-track mixing (music + voiceover)

Mix narration and music using raw ffmpeg when both tracks are needed:

```bash
ffmpeg -i video.mp4 -i voiceover.mp3 -i music.mp3 \
    -filter_complex \
    "[1:a]volume=1.0[voice]; [2:a]volume=0.2[music]; [voice][music]amix=inputs=2:duration=first[aout]" \
    -map 0:v -map "[aout]" \
    -c:v copy -c:a aac \
    -shortest final.mp4
```

## ffmpeg command patterns reference

| Operation              | ffmpeg filter                          |
| ---------------------- | -------------------------------------- | ----- |
| Volume control         | `volume=0.3`                           |
| Fade in (2s)           | `afade=t=in:st=0:d=2`                  |
| Fade out (3s from end) | `afade=t=out:st=END-3:d=3`             |
| Trim to N seconds      | `atrim=0:N`                            |
| Mix two audio streams  | `[a1][a2]amix=inputs=2:duration=first` |
| Delay audio by 2s      | `adelay=2000                           | 2000` |

## Prerequisites

- ffmpeg and ffprobe must already be installed (macOS: `brew install ffmpeg`; Debian/Ubuntu: `sudo apt-get install ffmpeg`); ask the user before installing system packages
- Verify: `ffmpeg -version`
- `scripts/add_audio.py` wraps ffmpeg with a simpler CLI interface for common use cases
- Use raw ffmpeg for multi-track mixing or advanced filter graphs

## Audio format notes

- Input: any format ffmpeg supports (MP3, WAV, AAC, OGG, FLAC)
- Output audio is encoded as AAC in the output MP4
- For GIF output, audio is not supported — GIFs are always silent
