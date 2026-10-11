# Changelog — Remotion Video

## 1.2.1

- Rename the optional Manim video consumer to `animate` (2.0.0) in the math-animation boundary and routing evaluation. Explicit React/Remotion requests still stay here, including React math.

## 1.2.0

- Add a routing boundary: explicit Hyperframes or plain HTML/CSS-authored video requests belong to `html-video`; Remotion remains the choice for explicit React or Remotion requests, including HTML content embedded inside a React composition.
- Update the skill description and cross-reference so explicit engines outrank content preferences, including React math animations. A missing Node.js prerequisite never authorizes an implicit engine switch.
- Add routing evaluation cases for both directions.
