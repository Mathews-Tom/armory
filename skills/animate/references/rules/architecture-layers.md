# Architecture Layers

Animate stacked horizontal layers representing abstraction levels. Use for system architecture, network stacks (OSI model), software layers, cloud infrastructure tiers, or any hierarchical decomposition.

## When to use

- User says: "show the architecture", "visualize the stack", "explain the layers"
- Concept has components that sit on top of each other with dependency direction
- The hierarchy matters as much as the individual components

## Layout rules

- Use `Rectangle(width=8, height=1.2)` for wide uniform layers
- Arrange with `arrange(DOWN, buff=0.15)` for tight stacking
- Animate bottom-up with `reversed(layer_group)` — lower layers appear first, then higher ones build on top
- Add thin arrows between adjacent layers after all layers are visible
- Optionally add sub-components inside each layer using nested `VGroup`

## Working example

```python
from manim import *

class ArchitectureScene(Scene):
    def construct(self):
        layers = [
            ("Application", BLUE),
            ("API Gateway", TEAL),
            ("Service Mesh", GREEN),
            ("Infrastructure", ORANGE),
        ]

        layer_group = VGroup()
        for name, color in layers:
            layer = VGroup(
                Rectangle(width=8, height=1.2, color=color, fill_opacity=0.15),
                Text(name, font_size=32, color=color)
            )
            layer_group.add(layer)

        layer_group.arrange(DOWN, buff=0.15)
        layer_group.move_to(ORIGIN)

        # Build from bottom up
        for layer in reversed(layer_group):
            self.play(FadeIn(layer, shift=UP * 0.5), run_time=0.6)

        # Add connecting arrows
        for i in range(len(layer_group) - 1):
            arrow = Arrow(
                layer_group[i].get_bottom(),
                layer_group[i + 1].get_top(),
                buff=0.05, color=GREY, stroke_width=2
            )
            self.play(GrowArrow(arrow), run_time=0.3)

        self.wait(2)
```

## Variations

- **Zoom into a layer**: after all layers appear, scale one layer up with `.animate.scale(1.3)` and show its internals
- **Highlight request path**: draw an `Arrow` traveling vertically through the layers with a `Dot` moving along it
- **Uneven layers**: skip `arrange()` and set `height` per layer based on relative complexity
- **Color gradient**: use a single hue across `[DARK_BLUE, BLUE, BLUE_B, BLUE_C]` to show decreasing abstraction
