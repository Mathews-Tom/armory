# Iterative Process / Training Loop

Animate cyclic processes where the same steps repeat with improving state. Use for gradient descent, reinforcement learning loops, feedback systems, RLHF pipelines, or any "iterate until convergence" concept.

## When to use

- User says: "show the training loop", "animate gradient descent", "visualize the RL cycle", "explain how backprop works"
- The process is cyclical: steps repeat in order and the system improves with each pass
- The key insight is the feedback mechanism and convergence over time

## Layout rules

- Arrange cycle nodes in a circle (not a line) to convey cyclicality
- Use trigonometric positioning: `radius * np.array([cos(angle), sin(angle), 0])`
- Start at top (angle = π/2) and go clockwise (subtract `TAU/n` per step)
- Draw arrows between adjacent nodes after all nodes appear
- Animate a "highlight pulse" traveling around the cycle to show one iteration
- Add epoch/iteration counter at bottom to convey time passing

## Working example

```python
from manim import *

class TrainingLoopScene(Scene):
    def construct(self):
        title = Text("Training Loop", font_size=48, weight=BOLD)
        self.play(Write(title))
        self.play(title.animate.to_edge(UP).scale(0.7))

        steps = ["Forward\nPass", "Compute\nLoss", "Backward\nPass", "Update\nWeights"]
        colors = [BLUE, RED, ORANGE, GREEN]
        radius = 2.2
        n = len(steps)

        nodes = VGroup()
        for i, (step, color) in enumerate(zip(steps, colors)):
            angle = PI / 2 - i * TAU / n
            pos = radius * np.array([np.cos(angle), np.sin(angle), 0])
            box = VGroup(
                RoundedRectangle(width=2, height=1, corner_radius=0.15,
                                 color=color, fill_opacity=0.15),
                Text(step, font_size=20, color=color)
            ).move_to(pos)
            nodes.add(box)

        self.play(LaggedStart(*[FadeIn(nd, scale=0.5) for nd in nodes], lag_ratio=0.2))

        for i in range(n):
            start = nodes[i].get_center()
            end = nodes[(i + 1) % n].get_center()
            arrow = Arrow(start, end, buff=0.85, color=GREY, stroke_width=2)
            self.play(GrowArrow(arrow), run_time=0.3)

        # Animate one cycle
        for i in range(n):
            self.play(nodes[i][0].animate.set_fill(colors[i], opacity=0.5), run_time=0.4)
            self.play(nodes[i][0].animate.set_fill(colors[i], opacity=0.15), run_time=0.2)

        epoch = Text("Epoch: 1 → 2 → 3 → ... → N", font_size=24, color=YELLOW)
        epoch.to_edge(DOWN)
        self.play(Write(epoch))
        self.wait(2)
```

## Variations

- **Loss curve**: add `Axes` in the corner with a `ParametricFunction` showing loss decreasing over epochs
- **Weight visualization**: show a grid of colored cells representing weight matrix, update colors each iteration
- **Convergence animation**: use `ValueTracker` for loss value; animate it decreasing with `always_redraw`
- **RL loop**: replace "Forward Pass" with "Observe State", "Compute Loss" with "Get Reward", etc.
- **Mini-batch highlight**: show a dataset VGroup and highlight a random subset each iteration
