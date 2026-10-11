# Equation / Mathematical Concept

Animate formulas, equations, and mathematical ideas. Use for loss functions, attention mechanisms, probability distributions, geometric proofs, or any "explain the math behind X" request.

## When to use

- User says: "explain the math of X", "show the formula for", "visualize how softmax works", "animate gradient descent equation"
- The concept has a formula that needs unpacking into components
- Geometric intuition can supplement the symbolic representation

## LaTeX decision

Prefer `Text` with Unicode over `MathTex` to avoid LaTeX dependency issues:

```python
# Preferred (no LaTeX needed):
Text("Attention(Q,K,V) = softmax(QKᵀ / √dₖ) · V", font_size=30)

# Use MathTex only when formula rendering quality is critical:
MathTex(r"\text{Loss} = -\sum_i y_i \log(\hat{y}_i)")
```

## Layout rules

- Show formula first, centered at `UP * 1`, then break it into labeled components below
- Component breakdown: symbol + arrow + description in a `VGroup().arrange(RIGHT, buff=0.5)`
- Use `LaggedStart` to reveal components sequentially
- Color each variable consistently across formula and breakdown
- Keep formula text ≤ 50 characters per line; split long formulas across two `Text` objects

## Working example

```python
from manim import *

class MathConceptScene(Scene):
    def construct(self):
        title = Text("Attention Mechanism", font_size=48, weight=BOLD)
        self.play(Write(title))
        self.wait(0.5)
        self.play(title.animate.to_edge(UP))

        formula = Text("Attention(Q, K, V) = softmax(QKᵀ / √dₖ) · V", font_size=30)
        formula.move_to(UP * 1)
        self.play(Write(formula), run_time=1.5)
        self.wait(1)

        components = [
            ("Q = Query", "What am I looking for?", BLUE),
            ("K = Key",   "What do I contain?",     GREEN),
            ("V = Value", "What do I provide?",     ORANGE),
        ]

        comp_group = VGroup()
        for symbol, desc, color in components:
            row = VGroup(
                Text(symbol, font_size=28, color=color),
                Text(f"→ {desc}", font_size=22, color=GREY),
            ).arrange(RIGHT, buff=0.5)
            comp_group.add(row)

        comp_group.arrange(DOWN, buff=0.4, aligned_edge=LEFT)
        comp_group.move_to(DOWN * 1.2)

        self.play(LaggedStart(*[FadeIn(c, shift=RIGHT * 0.3) for c in comp_group], lag_ratio=0.3))
        self.wait(2)
```

## Variations

- **Geometric proof**: draw shapes (circles, triangles) alongside the formula and annotate with `Text` labels
- **Step-by-step derivation**: start with the full formula, then `Transform` intermediate versions of it
- **Value substitution**: show concrete numbers flowing into the formula using `ReplacementTransform`
- **Graph + equation**: plot the function on `Axes` to the right while showing the formula on the left
- **Highlight term**: use `SurroundingRectangle` to box specific terms as you explain each one
