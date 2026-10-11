# Pipeline / Data Flow

Animate sequential stages connected by arrows. Use for RAG pipelines, ETL processes, request flows, CI/CD stages, or any linear step-by-step process.

## When to use

- User says: "show how data flows through X", "animate my pipeline", "visualize the ETL process"
- Concept has discrete named stages with a clear left-to-right or top-to-bottom order
- Each stage transforms or passes something to the next

## Layout rules

- Arrange boxes horizontally with `arrange(RIGHT, buff=0.5)`
- Keep to 4-7 stages maximum; more than 7 becomes unreadable at standard resolution
- Color-code each stage with a distinct color (BLUE → TEAL → GREEN → YELLOW → RED progression works well)
- Animate stage-by-stage: FadeIn box, then GrowArrow to next
- Use `RoundedRectangle` for stages, `Arrow` for connectors

## Working example

```python
from manim import *

class PipelineScene(Scene):
    def construct(self):
        stages = ["Ingest", "Embed", "Index", "Retrieve", "Generate"]
        colors = [BLUE, TEAL, GREEN, YELLOW, RED]

        boxes = VGroup()
        for name, color in zip(stages, colors):
            box = VGroup(
                RoundedRectangle(corner_radius=0.2, width=2, height=1,
                                 color=color, fill_opacity=0.2),
                Text(name, font_size=28, color=color)
            )
            boxes.add(box)

        boxes.arrange(RIGHT, buff=0.5)
        boxes.move_to(ORIGIN)

        for i, box in enumerate(boxes):
            self.play(FadeIn(box, shift=UP * 0.3), run_time=0.5)
            if i < len(boxes) - 1:
                arrow = Arrow(
                    boxes[i].get_right(), boxes[i + 1].get_left(),
                    buff=0.1, color=WHITE, stroke_width=2
                )
                self.play(GrowArrow(arrow), run_time=0.3)

        self.wait(2)
```

## Variations

- **Vertical pipeline**: use `arrange(DOWN, buff=0.5)` and swap arrow directions
- **Branching flow**: position boxes manually with `.move_to()` and draw arrows explicitly
- **Data packet animation**: use `Dot` traveling along a `Line` path after all boxes are visible
- **Highlight active stage**: after pipeline is built, use `Indicate(boxes[i], color=YELLOW)` to replay flow
