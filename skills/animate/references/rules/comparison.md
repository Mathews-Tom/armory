# Side-by-Side Comparison

Animate two approaches, options, or states simultaneously on a split screen. Use for before/after, trade-off analysis, two competing architectures, or any "A vs B" concept.

## When to use

- User says: "compare X and Y", "show the difference between", "before and after", "pros and cons"
- The comparison benefits from visual parallelism — viewer sees both sides at once
- Contrast is the primary insight (not a sequence of steps)

## Layout rules

- Split canvas at center with a vertical `Line` divider
- Left panel: x ∈ [-7, -0.2], Right panel: x ∈ [0.2, 7]
- Use `LEFT * 3.5` and `RIGHT * 3.5` as panel centers
- Titles go at top of each panel (`UP * 2` from center)
- Animate both sides simultaneously with `self.play(A, B)` to reinforce parallelism
- Use distinct but harmonious colors per side (BLUE vs GREEN is canonical)

## Working example

```python
from manim import *

class ComparisonScene(Scene):
    def construct(self):
        title = Text("Monolith vs Microservices", font_size=44, weight=BOLD)
        self.play(Write(title))
        self.wait(0.5)
        self.play(title.animate.to_edge(UP))

        divider = Line(UP * 2.5, DOWN * 2.5, color=GREY, stroke_width=1)
        self.play(Create(divider))

        # Left: Monolith
        left_title = Text("Monolith", font_size=32, color=BLUE)
        left_title.move_to(LEFT * 3.5 + UP * 2)
        mono_box = Rectangle(width=3, height=4, color=BLUE, fill_opacity=0.1)
        mono_box.move_to(LEFT * 3.5 + DOWN * 0.5)
        mono_labels = VGroup(*[
            Text(s, font_size=18) for s in ["Auth", "API", "DB", "UI", "Logic"]
        ]).arrange(DOWN, buff=0.3).move_to(mono_box)

        # Right: Microservices
        right_title = Text("Microservices", font_size=32, color=GREEN)
        right_title.move_to(RIGHT * 3.5 + UP * 2)
        micro_boxes = VGroup()
        for name in ["Auth", "API", "DB", "UI", "Logic"]:
            box = VGroup(
                RoundedRectangle(width=1.2, height=0.8, corner_radius=0.1,
                                 color=GREEN, fill_opacity=0.1),
                Text(name, font_size=16, color=GREEN)
            )
            micro_boxes.add(box)
        micro_boxes.arrange_in_grid(rows=2, cols=3, buff=0.3)
        micro_boxes.move_to(RIGHT * 3.5 + DOWN * 0.5)

        self.play(Write(left_title), Write(right_title))
        self.play(FadeIn(mono_box), FadeIn(mono_labels))
        self.play(LaggedStart(*[FadeIn(b, scale=0.8) for b in micro_boxes], lag_ratio=0.15))

        self.wait(2)
```

## Variations

- **Morphing comparison**: start with one state, then `Transform` it into the other
- **Metric bars**: add `Rectangle` bars of different heights under each side to show performance differences
- **Pros/cons list**: use bullet points with GREEN checkmarks and RED crosses using Unicode (✓, ✗)
- **Three-way comparison**: use three panels at `LEFT * 4.5`, `ORIGIN`, `RIGHT * 4.5` with two dividers
- **Animated highlight winner**: at the end, fade one side to 20% opacity and brighten the other
