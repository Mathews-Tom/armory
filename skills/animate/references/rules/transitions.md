# Scene Transitions

Utility patterns for moving between sections within a single Scene. Use these to avoid jarring cuts and create visual continuity between distinct animation segments.

## Fade transition (clear and restart)

The simplest transition: fade everything out, pause briefly, start fresh.

```python
from manim import *

class FadeTransitionExample(Scene):
    def construct(self):
        # Section 1
        section1 = Text("Part One", font_size=48)
        self.play(Write(section1))
        self.wait(1)

        # Fade everything out
        self.play(*[FadeOut(mob) for mob in self.mobjects])
        self.wait(0.3)

        # Section 2
        section2 = Text("Part Two", font_size=48, color=BLUE)
        self.play(Write(section2))
        self.wait(1)
```

## Wipe transition (slide content off screen)

Slides current content left while new content slides in from right. Creates a sense of forward progress.

```python
from manim import *

class WipeTransitionExample(Scene):
    def construct(self):
        # Section 1
        old_content = VGroup(
            Text("Section 1", font_size=48),
            Text("Some explanation here", font_size=28, color=GREY),
        ).arrange(DOWN)
        self.play(FadeIn(old_content))
        self.wait(1)

        # Slide old content left (off screen)
        self.play(old_content.animate.shift(LEFT * 15), run_time=0.8)
        self.remove(*old_content)

        # New content arrives from right
        new_content = VGroup(
            Text("Section 2", font_size=48, color=GREEN),
            Text("Next idea here", font_size=28, color=GREY),
        ).arrange(DOWN).shift(RIGHT * 15)
        self.add(new_content)
        self.play(new_content.animate.shift(LEFT * 15), run_time=0.8)
        self.wait(1)
```

## When to use each

| Transition    | Use when                                          |
| ------------- | ------------------------------------------------- |
| Fade          | Unrelated sections; clear conceptual break        |
| Wipe          | Sequential sections; showing progression/timeline |
| No transition | Continuous animation; same objects transform      |

## Tips

- Use `self.play(*[FadeOut(mob) for mob in self.mobjects])` to fade everything without tracking individual objects
- After a wipe, always `self.remove(*old_content)` to prevent invisible objects from accumulating
- Keep transition duration ≤ 1s; transitions should not compete with content for attention
- Add `self.wait(0.3)` after a fade-out before starting new content — gives the viewer a visual breath
