# Changelog — Route

## 1.1.0

- Add routing for videos authored as HTML and CSS and rendered with Hyperframes to `html-video`.
- Clarify engine-specific precedence for video creation: explicit Hyperframes selects `html-video`, explicit Manim selects `concept-to-video`, explicit React or Remotion selects `remotion-video`.
- Distinguish video creation from existing-video analysis (`watch`) and from ordinary web pages with no video output.
- Add routing evaluation cases for the new route and its boundaries.
