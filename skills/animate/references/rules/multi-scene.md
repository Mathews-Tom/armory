# Multi-Scene Composition

Split a long animation into multiple Manim Scene classes, render them separately, and concatenate with ffmpeg. Use when a concept has distinct chapters that benefit from separate rendering and iteration.

## When to use

- Video is longer than ~90 seconds (single scene becomes hard to debug)
- User wants to iterate on one section without re-rendering others
- Concept has 3+ distinct chapters with different visual styles

## Structure: multiple Scene classes in one file

```python
from manim import *

class IntroScene(Scene):
    def construct(self):
        title = Text("Binary Search", font_size=56, weight=BOLD)
        subtitle = Text("Efficient lookup in O(log n)", font_size=30, color=GREY)
        subtitle.next_to(title, DOWN)
        self.play(Write(title))
        self.play(FadeIn(subtitle))
        self.wait(2)


class AlgorithmScene(Scene):
    def construct(self):
        # ... main algorithm animation ...
        pass


class SummaryScene(Scene):
    def construct(self):
        points = VGroup(*[
            Text(f"• {t}", font_size=28)
            for t in [
                "Requires sorted array",
                "O(log n) time complexity",
                "O(1) space complexity",
            ]
        ]).arrange(DOWN, aligned_edge=LEFT, buff=0.4)
        points.move_to(ORIGIN)
        for point in points:
            self.play(FadeIn(point, shift=RIGHT * 0.3), run_time=0.5)
            self.wait(0.5)
        self.wait(2)
```

## Rendering each scene

```bash
# Render each scene class separately with the provisioned animate environment
"$ANIMATE_ENV/bin/python" "$SKILL_DIR/scripts/render_video.py" scene.py IntroScene --quality low --format mp4
"$ANIMATE_ENV/bin/python" "$SKILL_DIR/scripts/render_video.py" scene.py AlgorithmScene --quality low --format mp4
"$ANIMATE_ENV/bin/python" "$SKILL_DIR/scripts/render_video.py" scene.py SummaryScene --quality low --format mp4
```

## Concatenating with ffmpeg

After rendering all scenes at final quality, join them:

```bash
# Create a file list for ffmpeg concat
cat > concat_list.txt << 'EOF'
file 'IntroScene.mp4'
file 'AlgorithmScene.mp4'
file 'SummaryScene.mp4'
EOF

# Concatenate (no re-encoding if all videos have same codec/resolution)
ffmpeg -f concat -safe 0 -i concat_list.txt -c copy final_video.mp4
```

If videos have different resolutions or codecs, re-encode:

```bash
ffmpeg -f concat -safe 0 -i concat_list.txt \
    -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2" \
    -c:v libx264 -c:a aac \
    final_video.mp4
```

## Transition between scenes

To add a 1-second fade transition between scenes:

```bash
ffmpeg -i scene1.mp4 -i scene2.mp4 \
    -filter_complex \
    "[0:v]fade=t=out:st=SCENE1_END-1:d=1[v0]; \
     [1:v]fade=t=in:st=0:d=1[v1]; \
     [v0][v1]concat=n=2:v=1:a=0[v]" \
    -map "[v]" output.mp4
```

Replace `SCENE1_END` with the duration of scene1 in seconds.

## When not to use multi-scene

- Single concepts that animate in under 90 seconds — keep as one Scene
- When transition animations need to share objects across sections — objects can't persist across Scene classes
- When render time is not a bottleneck — splitting adds file management overhead
