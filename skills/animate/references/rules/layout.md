# Layout & Positioning

Utility patterns for arranging objects spatially. Use these to place elements correctly on the Manim canvas without overlap or edge clipping.

## Canvas coordinate system

Manim's default canvas is 14.2 × 8 units (16:9 aspect ratio). The origin `ORIGIN` is the center.

```text
                    UP (0, 3.5, 0)
                         |
(-7, 0, 0) LEFT -------- + -------- RIGHT (7, 0, 0)
                         |
                   DOWN (0, -3.5, 0)
```

Safe content zone: x ∈ [-6, 6], y ∈ [-3, 3]. Keep objects within these bounds.

## Core positioning methods

```python
# Absolute placement
obj.move_to(ORIGIN)           # center
obj.move_to(UP * 2 + LEFT * 3)  # specific coordinate

# Relative to another object
label.next_to(box, DOWN, buff=0.3)   # below box with 0.3 gap
label.next_to(box, RIGHT, buff=0.5)  # right of box

# Edge anchoring
title.to_edge(UP, buff=0.3)    # near top edge
footer.to_edge(DOWN, buff=0.3) # near bottom edge
obj.to_edge(LEFT, buff=0.5)    # near left edge

# Alignment
obj.align_to(reference, LEFT)  # align left edges
obj.align_to(reference, UP)    # align top edges
```

## VGroup arrangement

```python
from manim import *

class LayoutExample(Scene):
    def construct(self):
        # Horizontal row
        items = VGroup(*[
            RoundedRectangle(width=1.5, height=1, corner_radius=0.1, color=BLUE)
            for _ in range(4)
        ])
        items.arrange(RIGHT, buff=0.4)
        items.move_to(ORIGIN)
        self.play(LaggedStart(*[FadeIn(item) for item in items], lag_ratio=0.15))

        # Vertical column aligned left
        labels = VGroup(*[
            Text(f"Item {i+1}", font_size=24) for i in range(4)
        ])
        labels.arrange(DOWN, aligned_edge=LEFT, buff=0.3)
        labels.next_to(items, DOWN, buff=0.5)
        self.play(LaggedStart(*[FadeIn(l) for l in labels], lag_ratio=0.1))

        # Grid layout
        grid = VGroup(*[
            Square(side_length=0.8, color=GREEN) for _ in range(6)
        ])
        grid.arrange_in_grid(rows=2, cols=3, buff=0.3)
        grid.move_to(ORIGIN)
        self.wait(1)
```

## Common layout patterns

| Layout         | Method                                              | Use for                  |
| -------------- | --------------------------------------------------- | ------------------------ |
| Horizontal row | `arrange(RIGHT, buff=0.5)`                          | Pipeline stages, options |
| Vertical stack | `arrange(DOWN, buff=0.3)`                           | Lists, layers, timeline  |
| Grid           | `arrange_in_grid(rows=R, cols=C, buff=0.3)`         | Microservices, matrix    |
| Radial         | Manual trig: `radius * [cos(angle), sin(angle), 0]` | Cycles, star topology    |
| Tree           | Manual `.move_to()` per node                        | Hierarchies, ASTs        |

## Spacing guidelines

- Between labels and their parent objects: `buff=0.2`
- Between sibling boxes in a row: `buff=0.4–0.6`
- Between sections vertically: `buff=0.8–1.2`
- Between title and content: `buff=0.5`
- Canvas padding from edges: at least `0.5` units

## Debugging layout

If objects overlap or fall off screen, add this to check positions:

```python
# Print center of each object during development
for mob in self.mobjects:
    print(mob.get_center())
```
