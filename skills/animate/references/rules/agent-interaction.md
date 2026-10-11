# Agent / Multi-System Interaction

Animate message passing between named entities arranged spatially. Use for multi-agent systems, distributed systems, pub/sub architectures, request/response flows, or any system where components communicate.

## When to use

- User says: "show how agents communicate", "animate the request flow", "visualize pub/sub", "show this multi-agent system"
- Concept has distinct named components that send messages to each other
- The communication pattern (who talks to whom, in what order) is the primary insight

## Layout rules

- Position entities as labeled circles using `Circle` + `Text` in `VGroup`
- Place entities at meaningful positions: Orchestrator at center top, workers around it
- Use 4 entities max in a standard layout; more than 5 gets crowded
- Animate messages as `Arrow` + `Text` that appear and then `FadeOut`
- `Indicate` the destination entity after each message arrives
- Keep arrows directional (src → dst); don't reuse persistent arrow objects

## Working example

```python
from manim import *

class AgentInteractionScene(Scene):
    def construct(self):
        positions = {
            "Orchestrator": UP * 2,
            "Planner": LEFT * 4,
            "Executor": RIGHT * 4,
            "Memory": DOWN * 2,
        }
        colors = {
            "Orchestrator": BLUE,
            "Planner": GREEN,
            "Executor": ORANGE,
            "Memory": PURPLE,
        }

        agents = {}
        for name, pos in positions.items():
            circle = Circle(radius=0.6, color=colors[name], fill_opacity=0.2)
            label = Text(name, font_size=20, color=colors[name])
            label.next_to(circle, DOWN, buff=0.15)
            agent = VGroup(circle, label).move_to(pos)
            agents[name] = agent

        self.play(LaggedStart(*[FadeIn(a, scale=0.5) for a in agents.values()], lag_ratio=0.2))
        self.wait(0.5)

        messages = [
            ("Orchestrator", "Planner", "Plan task", YELLOW),
            ("Planner", "Orchestrator", "Steps ready", GREEN),
            ("Orchestrator", "Executor", "Execute step 1", YELLOW),
            ("Executor", "Memory", "Store result", ORANGE),
            ("Executor", "Orchestrator", "Step complete", GREEN),
        ]

        for src, dst, msg_text, color in messages:
            src_pos = agents[src][0].get_center()
            dst_pos = agents[dst][0].get_center()

            arrow = Arrow(src_pos, dst_pos, buff=0.7, color=color, stroke_width=2)
            msg = Text(msg_text, font_size=16, color=color)
            msg.next_to(arrow, UP if src_pos[1] >= dst_pos[1] else DOWN, buff=0.1)

            self.play(GrowArrow(arrow), FadeIn(msg), run_time=0.6)
            self.play(Indicate(agents[dst][0], color=color), run_time=0.3)
            self.play(FadeOut(arrow), FadeOut(msg), run_time=0.3)

        self.wait(2)
```

## Variations

- **Persistent connections**: draw static `Line` edges between all agents first, then animate `Dot` traveling along them
- **Broadcast**: use `LaggedStart` to send arrows from one node to multiple simultaneously
- **State changes**: change circle fill color when an agent enters a new state (idle → working → done)
- **Timeline replay**: after showing all messages, add a numbered sequence list on the side
- **Error path**: use RED arrow for a failed message, shake the destination with `Wiggle`
