"""
Timeline Animation Template — parametric chronological event visualization.

Customize EVENTS with (year/label, description, color) tuples.
Run with: manim -ql timeline_template.py TimelineScene

Config:
    TITLE      — title shown at top
    EVENTS     — list of (label, description, color) tuples in chronological order (2-8)
    FINAL_HOLD — seconds to hold the last frame (0.5-30)

Every animation pins its run_time, so total duration is deterministic:
    3.3 + len(EVENTS) + FINAL_HOLD  seconds
"""

from manim import *

# ── Config ─────────────────────────────────────────────────────────────────
TITLE = "Evolution of Language Models"

EVENTS: list[tuple[str, str, ManimColor]] = [
    ("2017", "Transformer architecture introduced", BLUE),
    ("2018", "BERT: bidirectional pretraining", TEAL),
    ("2019", "GPT-2: 1.5B parameter language model", GREEN),
    ("2020", "GPT-3: few-shot learning at scale", YELLOW),
    ("2022", "InstructGPT & ChatGPT launch", ORANGE),
    ("2023", "GPT-4 & multimodal models", RED),
]

FINAL_HOLD = 2.0
# ───────────────────────────────────────────────────────────────────────────

LINE_Y = 0.0  # vertical position of the timeline axis
DOT_RADIUS = 0.12
LABEL_BUFF = 0.35  # space between dot and year label


class TimelineScene(Scene):
    def construct(self) -> None:
        # Title
        title = Text(TITLE, font_size=46, weight=BOLD)
        if title.width > 12:
            title.scale_to_fit_width(12)
        self.play(Write(title), run_time=1)
        self.wait(0.5)
        self.play(title.animate.to_edge(UP), run_time=1)

        n = len(EVENTS)
        x_start = -5.5
        x_end = 5.5
        xs = [x_start + i * (x_end - x_start) / (n - 1) for i in range(n)]
        label_width = min(2.2, (x_end - x_start) / (n - 1) - 0.25)

        # Draw the main timeline axis
        axis = Line(
            LEFT * 6 + UP * LINE_Y,
            RIGHT * 6 + UP * LINE_Y,
            color=GREY,
            stroke_width=2,
        )
        self.play(Create(axis), run_time=0.8)

        # Animate each event
        for i, ((label, description, color), x) in enumerate(zip(EVENTS, xs)):
            pos = np.array([x, LINE_Y, 0])

            # Dot on timeline
            dot = Dot(pos, radius=DOT_RADIUS, color=color)

            # Year label (alternates above/below to avoid overlap)
            above = i % 2 == 0
            year_text = Text(label, font_size=22, color=color, weight=BOLD)
            if year_text.width > label_width:
                year_text.scale_to_fit_width(label_width)
            year_text.next_to(dot, UP * (1 if above else -1), buff=LABEL_BUFF)

            # Description (opposite side from year)
            desc_text = Text(description, font_size=17, color=WHITE)
            if desc_text.width > label_width:
                desc_text.scale_to_fit_width(label_width)
            desc_text.next_to(dot, DOWN * (1 if above else -1), buff=LABEL_BUFF)

            # Connector line from dot to description
            connector_end = desc_text.get_top() if above else desc_text.get_bottom()
            connector = Line(
                dot.get_bottom() if above else dot.get_top(),
                connector_end,
                color=color,
                stroke_width=1.5,
            )

            self.play(
                FadeIn(dot, scale=0.5),
                Write(year_text),
                run_time=0.5,
            )
            self.play(
                Create(connector),
                FadeIn(desc_text, shift=DOWN * 0.2 if above else UP * 0.2),
                run_time=0.5,
            )

        self.wait(FINAL_HOLD)
