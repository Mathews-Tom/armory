# Subtitles

Generate SRT subtitle files from scene timing and overlay them on exported video. Use when the user wants captions, accessibility text, or on-screen narration cues synchronized to the animation.

## When to use

- User says: "add subtitles", "include captions", "make it accessible"
- Video will be shared without audio (subtitles carry the message)
- Voiceover was generated and needs accompanying text

## SRT format

SRT is the standard subtitle format. Each entry has: sequence number, timecode, text.

```text
1
00:00:00,000 --> 00:00:03,500
Today we explore binary search.

2
00:00:04,000 --> 00:00:07,000
Here is our sorted array of ten values.

3
00:00:07,500 --> 00:00:11,000
We are looking for the value 23.
```

## Deriving SRT from scene timing

Track cumulative time through the scene by summing `run_time` and `self.wait()` values:

```python
# Timing log (compute while writing the scene):
# 0.0s  → Write(title)              run_time=1.0   ends at 1.0s
# 1.0s  → wait(0.5)                                ends at 1.5s
# 1.5s  → title.animate.to_edge()   run_time=0.5   ends at 2.0s
# 2.0s  → FadeIn(cells)             run_time=0.6   ends at 2.6s
# 2.6s  → Write(target_text)        run_time=0.6   ends at 3.2s
```

## SRT generation helper

Write the SRT file directly from a timing list:

```python
def write_srt(entries: list[tuple[float, float, str]], output_path: str) -> None:
    """Write subtitle entries to an SRT file.

    Args:
        entries: List of (start_seconds, end_seconds, text) tuples
        output_path: Path to write the .srt file
    """
    def fmt(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    with open(output_path, "w") as f:
        for i, (start, end, text) in enumerate(entries, 1):
            f.write(f"{i}\n{fmt(start)} --> {fmt(end)}\n{text}\n\n")


# Example usage
write_srt([
    (0.0,  3.5,  "Today we explore binary search."),
    (4.0,  7.0,  "Here is our sorted array of ten values."),
    (7.5,  11.0, "We are looking for the value 23."),
], "subtitles.srt")
```

## Burning subtitles into video with ffmpeg

Hard-coded subtitles (permanently embedded in video, no separate file needed):

```bash
ffmpeg -i final.mp4 \
    -vf "subtitles=subtitles.srt:force_style='FontSize=22,PrimaryColour=&Hffffff,OutlineColour=&H000000,Outline=2'" \
    -c:a copy \
    final_subtitled.mp4
```

Soft subtitles (separate track, user can toggle — works in VLC/YouTube):

```bash
ffmpeg -i final.mp4 -i subtitles.srt \
    -c:v copy -c:a copy -c:s mov_text \
    -map 0 -map 1 \
    final_with_subs.mp4
```

## Tips

- Leave 300ms gap between subtitle entries (end of one, start of next)
- Max 42 characters per line; split long lines
- If using voiceover, align subtitle text exactly to spoken words — not animation beats
- For YouTube upload, just provide the `.srt` file alongside the video; YouTube accepts it separately
