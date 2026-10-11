"""
Side-by-Side Comparison Template — parametric A vs B visualization.

Customize LEFT_SIDE, RIGHT_SIDE, and their items. Works for any two-option comparison.
Run with: manim -ql comparison_template.py ComparisonScene

Config:
    TITLE           — main title at top
    LEFT_LABEL      — label for left panel
    LEFT_COLOR      — accent color for left panel
    LEFT_ITEMS      — list of feature strings for left side (1-6)
    RIGHT_LABEL     — label for right panel
    RIGHT_COLOR     — accent color for right panel
    RIGHT_ITEMS     — list of feature strings for right side (1-6)
    FINAL_HOLD      — seconds to hold the last frame (0.5-30)

Every animation pins its run_time, so total duration is deterministic:
    6.5 + FINAL_HOLD  seconds
"""

from manim import *

# ── Config ─────────────────────────────────────────────────────────────────
TITLE = "Monolith vs Microservices"

LEFT_LABEL = "Monolith"
LEFT_COLOR = BLUE
LEFT_ITEMS = [
    "Single deployable unit",
    "Shared memory/state",
    "Simple local dev",
    "Harder to scale",
    "Single point of failure",
]

RIGHT_LABEL = "Microservices"
RIGHT_COLOR = GREEN
RIGHT_ITEMS = [
    "Independent deployments",
    "Isolated state per service",
    "Complex local dev",
    "Scale services independently",
    "Isolated failure domains",
]

FINAL_HOLD = 2.0
# ───────────────────────────────────────────────────────────────────────────

PANEL_X = 3.2  # horizontal distance from center for each panel
PANEL_Y = -0.3  # vertical center for content


class ComparisonScene(Scene):
    def construct(self) -> None:
        # Title
        title = Text(TITLE, font_size=44, weight=BOLD)
        if title.width > 12:
            title.scale_to_fit_width(12)
        self.play(Write(title), run_time=1)
        self.wait(0.5)
        self.play(title.animate.to_edge(UP), run_time=1)

        # Divider
        divider = Line(UP * 2.8, DOWN * 3.2, color=GREY, stroke_width=1)
        self.play(Create(divider), run_time=1)

        # Panel labels
        left_title = Text(LEFT_LABEL, font_size=34, color=LEFT_COLOR, weight=BOLD)
        if left_title.width > 5.2:
            left_title.scale_to_fit_width(5.2)
        left_title.move_to(LEFT * PANEL_X + UP * 2.2)

        right_title = Text(RIGHT_LABEL, font_size=34, color=RIGHT_COLOR, weight=BOLD)
        if right_title.width > 5.2:
            right_title.scale_to_fit_width(5.2)
        right_title.move_to(RIGHT * PANEL_X + UP * 2.2)

        self.play(Write(left_title), Write(right_title), run_time=1)

        # Left items
        left_group = VGroup(
            *[Text(f"• {item}", font_size=20, color=LEFT_COLOR) for item in LEFT_ITEMS]
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.35)
        if left_group.width > 5.6:
            left_group.scale_to_fit_width(5.6)
        left_group.move_to(LEFT * PANEL_X + DOWN * 0.3)

        # Right items (rendered as separate boxes to convey independence)
        right_group = VGroup()
        for item in RIGHT_ITEMS:
            label = Text(item, font_size=18, color=RIGHT_COLOR)
            if label.width > 2.6:
                label.scale_to_fit_width(2.6)
            right_group.add(
                VGroup(
                    RoundedRectangle(
                        width=2.8,
                        height=0.55,
                        corner_radius=0.08,
                        color=RIGHT_COLOR,
                        fill_opacity=0.1,
                    ),
                    label,
                )
            )
        right_group.arrange(DOWN, buff=0.18)
        right_group.move_to(RIGHT * PANEL_X + DOWN * 0.3)

        # Animate both sides
        self.play(
            LaggedStart(
                *[FadeIn(item, shift=LEFT * 0.2) for item in left_group], lag_ratio=0.15
            ),
            LaggedStart(
                *[FadeIn(item, scale=0.85) for item in right_group], lag_ratio=0.15
            ),
            run_time=2,
        )

        self.wait(FINAL_HOLD)
