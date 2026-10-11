# Text Animation

Utility patterns for animating text: replacement, progressive reveal, callouts, and emphasis. Use these within any scene to make text feel purposeful rather than static.

## Animated text replacement

Smoothly replace one piece of text with another in-place. Use for showing state changes, refining a label, or correcting a hypothesis.

```python
from manim import *

class TextReplacementExample(Scene):
    def construct(self):
        old_text = Text("Before", font_size=48)
        self.play(Write(old_text))
        self.wait(0.5)

        new_text = Text("After", font_size=48, color=GREEN)
        new_text.move_to(old_text)  # same position
        self.play(ReplacementTransform(old_text, new_text))
        self.wait(1)
```

## Progressive reveal with bullet points

Reveal one bullet point at a time. Use for structured lists, step-by-step explanations, or feature breakdowns.

```python
from manim import *

class ProgressiveRevealExample(Scene):
    def construct(self):
        points = VGroup(*[
            Text(f"• {t}", font_size=28)
            for t in [
                "First: define the problem",
                "Second: gather data",
                "Third: train the model",
                "Fourth: evaluate results",
            ]
        ]).arrange(DOWN, aligned_edge=LEFT, buff=0.35)
        points.move_to(ORIGIN)

        for point in points:
            self.play(FadeIn(point, shift=RIGHT * 0.3), run_time=0.5)
            self.wait(0.6)

        self.wait(1)
```

## Callout / annotation

Draw attention to a specific element with a label and connecting line.

```python
from manim import *

class CalloutExample(Scene):
    def construct(self):
        box = Rectangle(width=3, height=1.5, color=BLUE, fill_opacity=0.2)
        box_label = Text("System", font_size=28, color=BLUE).move_to(box)
        self.play(FadeIn(VGroup(box, box_label)))
        self.wait(0.5)

        # Callout annotation
        callout_text = Text("bottleneck here", font_size=22, color=RED)
        callout_text.next_to(box, RIGHT, buff=1.5)
        callout_line = Arrow(callout_text.get_left(), box.get_right(), buff=0.1,
                             color=RED, stroke_width=2)
        self.play(GrowArrow(callout_line), FadeIn(callout_text))
        self.wait(1)
```

## Emphasis techniques

```python
# Flash and scale
self.play(Indicate(element, color=YELLOW, scale_factor=1.2))

# Box highlight
box = SurroundingRectangle(element, color=RED, buff=0.15)
self.play(Create(box))

# Wiggle (use for errors or warnings)
self.play(Wiggle(element, scale_value=1.15, rotation_angle=0.05 * TAU))
```

## Tips

- `ReplacementTransform` removes the old object and creates the new one — no manual `FadeOut` needed
- `FadeIn(point, shift=RIGHT * 0.3)` is more dynamic than plain `FadeIn` for list reveals
- Keep callout text short (3-5 words); longer annotations belong in a text section, not a callout
- Use `Indicate` sparingly — overuse reduces its impact; reserve for the single most important element per scene
