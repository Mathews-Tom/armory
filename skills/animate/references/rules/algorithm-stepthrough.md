# Algorithm Step-Through

Animate stateful algorithms where you show each step, highlight the current position, and reveal the outcome. Use for sorting, binary search, graph traversal, dynamic programming, or any algorithm that transforms data across discrete steps.

## When to use

- User says: "show how quicksort works", "animate binary search", "visualize BFS"
- The algorithm operates on a visible data structure (array, graph, tree)
- The key insight is watching the state change step by step

## Layout rules

- Represent arrays as `VGroup` of `Square` + `Text` cells arranged with `arrange(RIGHT, buff=0)`
- Use `SurroundingRectangle` for range highlights (current search window, subarray, etc.)
- Use `Arrow` pointing down from above for index pointers (lo, mid, hi)
- Color feedback: GREEN = found/correct, RED = pointer/current, BLUE = search range, GREY = eliminated
- Animate each step: show pointers → wait → react → clean up pointers → next step

## Working example

```python
from manim import *

class AlgorithmScene(Scene):
    def construct(self):
        title = Text("Binary Search", font_size=48, weight=BOLD)
        self.play(Write(title))
        self.wait(0.5)
        self.play(title.animate.to_edge(UP))

        values = [2, 5, 8, 12, 16, 23, 38, 56, 72, 91]
        cells = VGroup()
        for v in values:
            cell = VGroup(
                Square(side_length=0.8, color=WHITE, stroke_width=1),
                Text(str(v), font_size=24)
            )
            cells.add(cell)

        cells.arrange(RIGHT, buff=0)
        cells.move_to(ORIGIN)
        self.play(FadeIn(cells))

        target_text = Text("Target: 23", font_size=32, color=YELLOW)
        target_text.next_to(cells, DOWN, buff=1)
        self.play(Write(target_text))

        lo, hi = 0, len(values) - 1
        target = 23

        while lo <= hi:
            mid = (lo + hi) // 2
            highlight = SurroundingRectangle(
                VGroup(*cells[lo:hi + 1]),
                color=BLUE, buff=0.05
            )
            pointer = Arrow(
                cells[mid].get_top() + UP * 0.5,
                cells[mid].get_top(),
                buff=0.05, color=RED
            )
            mid_label = Text("mid", font_size=20, color=RED)
            mid_label.next_to(pointer, UP, buff=0.1)

            self.play(Create(highlight), GrowArrow(pointer), Write(mid_label), run_time=0.6)
            self.wait(0.5)

            if values[mid] == target:
                cells[mid][0].set_fill(GREEN, opacity=0.5)
                self.play(Indicate(cells[mid], color=GREEN, scale_factor=1.3))
                found = Text("Found!", font_size=40, color=GREEN)
                found.next_to(target_text, DOWN)
                self.play(Write(found))
                break
            elif values[mid] < target:
                lo = mid + 1
            else:
                hi = mid - 1

            self.play(FadeOut(highlight), FadeOut(pointer), FadeOut(mid_label), run_time=0.3)

        self.wait(2)
```

## Variations

- **Sorting**: swap cell positions using `.animate.move_to()` and simultaneously recolor to show comparisons
- **Graph traversal**: use `Circle` nodes with `Line` edges; color nodes as they're visited
- **Tree algorithms**: use `VGroup` positioned manually in tree shape; highlight edges as you traverse
- **Show comparisons counter**: add a `ValueTracker` and `always_redraw` label for comparison count
