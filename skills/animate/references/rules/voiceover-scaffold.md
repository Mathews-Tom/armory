# Voiceover Scaffold

Generate a timing script from a Manim scene's structure. Use this to write narration that syncs with animation beats before recording or passing to TTS.

## When to use

- User wants to add narration to an animation
- User asks "write a script for this video"
- User wants to hand off to a TTS service (ElevenLabs, OpenAI TTS, macOS `say`)

## Deriving a timing script from scene structure

Each animation beat in `construct()` maps to a narration window. Extract timing from `run_time` and `self.wait()` calls.

Example scene analysis:

```python
# Scene beat breakdown → narration timing
self.play(Write(title))               # t=0–1s    → "Today we explore binary search."
self.wait(0.5)                        # t=1–1.5s  → [pause]
self.play(title.animate.to_edge(UP))  # t=1.5–2s  → [pause, title moves]
self.play(FadeIn(cells))              # t=2–2.5s  → "Here is our sorted array of ten values."
self.play(Write(target_text))         # t=2.5–3s  → "We're looking for the value 23."
# ... search loop, ~3s per iteration  → "The algorithm checks the middle element..."
self.wait(2)                          # end        → "Binary search finds the answer in O(log n) steps."
```

## Voiceover script template

Use this structure when writing narration:

```text
[0:00] <Opening — state the concept>
[0:05] <Context — why this matters>
[0:15] <Step 1 — narrate first animation beat>
[0:25] <Step 2 — narrate second animation beat>
...
[N:XX] <Summary — restate key takeaway>
```

## Scripting best practices

- One sentence per animation beat — viewers can't read and listen simultaneously
- Write for spoken delivery, not prose — short sentences, no jargon
- Leave 0.5s silence buffer after each self.wait() — don't narrate during pauses
- Avoid "as you can see" — the animation shows it; the narration adds context
- Total narration should be 10–15% shorter than the video duration — speaking takes space

## TTS handoff

Once the script is written, hand off to TTS:

```bash
# macOS built-in (fast, no API key)
say -v Samantha -r 175 -o voiceover.aiff "Your script here"
ffmpeg -i voiceover.aiff voiceover.mp3

# OpenAI TTS (higher quality)
# Use the openai Python SDK or REST API with model="tts-1-hd", voice="onyx"

# ElevenLabs (most natural)
# Use the elevenlabs Python SDK with chosen voice ID
```

After generating the audio file, sync it with the video using `scripts/add_audio.py`:

```bash
python3 scripts/add_audio.py scene_output.mp4 voiceover.mp3 \
    --output final_narrated.mp4 \
    --trim-to-video
```

## Timing adjustment workflow

If voiceover timing is off after first pass:

1. Identify which beat is out of sync by noting the timestamp
2. Adjust `run_time` or `self.wait()` in the scene to match the spoken word
3. Re-render at low quality, re-check sync
4. Once satisfied, do full render + audio overlay
