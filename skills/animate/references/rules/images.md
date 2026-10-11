# Image Embedding

Embed external images (logos, screenshots, diagrams) into Manim scenes using `ImageMobject`. Use when the concept requires a real asset rather than a constructed primitive.

## When to use

- User says: "use our company logo", "include a screenshot of the UI", "show this diagram"
- The image conveys information that Manim primitives cannot replicate efficiently
- Branding or real-world context is needed alongside the animation

## Basic image embedding

```python
from manim import *

class ImageEmbedScene(Scene):
    def construct(self):
        # Load image — path relative to where you run manim from
        logo = ImageMobject("assets/logo.png")

        # Scale: default is image's pixel dimensions in Manim units
        logo.scale(0.5)                    # 50% of original size
        logo.move_to(ORIGIN)

        self.play(FadeIn(logo))
        self.wait(1)

        # Move to corner after intro
        self.play(logo.animate.to_corner(UL, buff=0.3).scale(0.5))
        self.wait(2)
```

## Scaling strategies

```python
# Scale to specific width (preserves aspect ratio)
logo.width = 3.0

# Scale to specific height
logo.height = 2.0

# Scale relative to another object
logo.match_width(reference_box)
logo.match_height(reference_box)

# Scale by factor
logo.scale(0.4)
```

## Common positioning patterns

```python
# Logo watermark in corner
logo.to_corner(UL, buff=0.3)
logo.width = 1.5

# Screenshot filling a panel
screenshot.move_to(RIGHT * 3.5)
screenshot.height = 5.0

# Image with caption below
image = ImageMobject("diagram.png").scale(0.6)
caption = Text("Figure: System overview", font_size=20, color=GREY)
caption.next_to(image, DOWN, buff=0.2)
group = VGroup(image, caption).move_to(ORIGIN)
```

## Screenshot pattern (annotated)

Show a screenshot then add callout arrows pointing to specific regions:

```python
from manim import *

class AnnotatedScreenshot(Scene):
    def construct(self):
        screenshot = ImageMobject("assets/ui_screenshot.png")
        screenshot.height = 5.0
        screenshot.move_to(ORIGIN)

        self.play(FadeIn(screenshot))
        self.wait(0.5)

        # Callout to a region
        callout = Text("Login button", font_size=24, color=YELLOW)
        callout.move_to(RIGHT * 5 + UP * 1)
        # Arrow pointing to bottom-right of screenshot (adjust coords to match your image)
        arrow = Arrow(callout.get_left(), screenshot.get_right() + DOWN * 1.5,
                      buff=0.1, color=YELLOW, stroke_width=2)
        self.play(GrowArrow(arrow), FadeIn(callout))
        self.wait(2)
```

## Notes

- Supported formats: PNG, JPG, GIF (first frame only), SVG (via `SVGMobject` instead)
- Image path is relative to the working directory when you run `manim`, not the script location
- Keep images ≤ 2048×2048px for fast rendering; larger images slow down frame generation
- For SVG logos, use `SVGMobject("logo.svg")` — it supports color manipulation and animation
