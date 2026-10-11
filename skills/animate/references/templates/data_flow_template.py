"""
Data Flow Animation Template — parametric pipeline/ETL/RAG visualization.

Customize STAGES to match your pipeline. Each stage has a name and color.
Run with: manim -ql data_flow_template.py DataFlowScene

Config:
    STAGES      — list of (name, color) tuples for each pipeline stage (2-5)
    TITLE       — title shown at the top
    ARROW_COLOR — color for connecting arrows
    FINAL_HOLD  — seconds to hold the last frame (0.5-30)

Every animation pins its run_time, so total duration is deterministic:
    3.2 + 1.3 * len(STAGES) + FINAL_HOLD  seconds
"""

from manim import *

# ── Config ─────────────────────────────────────────────────────────────────
TITLE = "RAG Pipeline"

STAGES: list[tuple[str, ManimColor]] = [
    ("Ingest", BLUE),
    ("Embed", TEAL),
    ("Index", GREEN),
    ("Retrieve", YELLOW),
    ("Generate", RED),
]

ARROW_COLOR = WHITE
FINAL_HOLD = 2.0
# ───────────────────────────────────────────────────────────────────────────

BOX_WIDTH = 1.9
BOX_HEIGHT = 1.0


class DataFlowScene(Scene):
    def construct(self) -> None:
        # Title
        title = Text(TITLE, font_size=52, weight=BOLD)
        if title.width > 12:
            title.scale_to_fit_width(12)
        self.play(Write(title), run_time=1)
        self.wait(0.5)
        self.play(title.animate.to_edge(UP), run_time=1)

        # Build stage boxes
        boxes = VGroup()
        for name, color in STAGES:
            label = Text(name, font_size=26, color=color)
            if label.width > BOX_WIDTH - 0.2:
                label.scale_to_fit_width(BOX_WIDTH - 0.2)
            box = VGroup(
                RoundedRectangle(
                    corner_radius=0.2,
                    width=BOX_WIDTH,
                    height=BOX_HEIGHT,
                    color=color,
                    fill_opacity=0.2,
                ),
                label,
            )
            boxes.add(box)

        boxes.arrange(RIGHT, buff=0.55)
        boxes.move_to(ORIGIN)

        # Animate stages + arrows sequentially
        arrows: list[Arrow] = []
        for i, box in enumerate(boxes):
            self.play(FadeIn(box, shift=UP * 0.3), run_time=0.45)
            if i < len(boxes) - 1:
                arrow = Arrow(
                    boxes[i].get_right(),
                    boxes[i + 1].get_left(),
                    buff=0.08,
                    color=ARROW_COLOR,
                    stroke_width=2,
                )
                arrows.append(arrow)
                self.play(GrowArrow(arrow), run_time=0.3)

        self.wait(1)

        # Replay: highlight each stage in sequence
        for i, box in enumerate(boxes):
            color = STAGES[i][1]
            self.play(
                box[0].animate.set_fill(color, opacity=0.55),
                run_time=0.35,
            )
            self.play(
                box[0].animate.set_fill(color, opacity=0.2),
                run_time=0.2,
            )

        self.wait(FINAL_HOLD)
