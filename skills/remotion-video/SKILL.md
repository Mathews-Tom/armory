---
name: remotion-video
description: 'Create motion graphics and videos using Remotion (React) with audio sync, web fonts, and TailwindCSS. Triggers on: "create a Remotion video", "React video", "motion graphics", "branded video", "product demo video", "video with voiceover". NOT for math animations, use concept-to-video.'
metadata:
  version: 1.1.1
  category: business
  tags: [video, react, remotion, motion-graphics]
  difficulty: advanced
---

# Remotion Video

Creates production-grade videos using Remotion — a React framework where video is code.
Every frame is a React component. Animations use spring physics and frame-based interpolation.

## Reference Files

| File                                    | Purpose                                                          |
| --------------------------------------- | ---------------------------------------------------------------- |
| `references/rules/fundamentals.md`      | useCurrentFrame, useVideoConfig, interpolate, spring, core hooks |
| `references/rules/animations.md`        | Easing, spring config, interpolateColors, timing patterns        |
| `references/rules/compositions.md`      | Composition, registerRoot, Folder, calculateMetadata             |
| `references/rules/media.md`             | Img, Video, OffthreadVideo, Audio, staticFile, async loading     |
| `references/rules/text-and-fonts.md`    | Google Fonts, local fonts, text measurement, typography          |
| `references/rules/tailwind.md`          | TailwindCSS integration, utility-first styling in Remotion       |
| `references/rules/audio.md`             | Audio component, volume curves, trimming, frame-synced audio     |
| `references/rules/subtitles.md`         | Caption system, SRT/VTT parsing, word-level timing               |
| `references/rules/three-d.md`           | @remotion/three, ThreeCanvas, React Three Fiber integration      |
| `references/rules/charts.md`            | Bar, pie, line chart animation patterns                          |
| `references/rules/rendering.md`         | CLI render, renderMedia API, quality presets                     |
| `references/rules/data-driven.md`       | Dataset rendering, batch generation, parametric compositions     |
| `references/templates/explainer.tsx`    | Parametric tech explainer template                               |
| `references/templates/product-demo.tsx` | Product showcase template                                        |
| `references/templates/data-viz.tsx`     | Animated chart composition template                              |
| `scripts/scaffold_project.sh`           | Bootstrap a new Remotion project with TailwindCSS                |
| `scripts/render.sh`                     | Render wrapper with quality presets and format options           |

## Why Remotion

Remotion treats video as a React application. Each frame is a pure function of time — given frame N and total frames F, your component renders deterministically. This means:

- **Component composition**: Nest scenes, reuse components, apply CSS.
- **Spring physics**: `spring()` gives natural motion without hand-tweaking cubic beziers.
- **Asset pipeline**: Import images, audio, video — the same way you import in React.
- **Iterative workflow**: Edit code → hot-reload preview → render final. The `.tsx` file IS the editable intermediate.
- **Data-driven at scale**: Render thousands of personalized videos by passing different props to the same composition.

## Workflow

```text
Scaffold → Compose → Preview → Iterate → Render
```

1. **Scaffold** the project (once per video project)
2. **Interpret** the user's concept — choose the right template and rule files
3. **Compose** React components for each scene
4. **Preview** in Remotion Studio (`npm run dev`)
5. **Iterate** based on user feedback
6. **Render** final video via `scripts/render.sh`

## Step 0: Ensure Dependencies

Node.js 18+ is required. Check before scaffolding:

```bash
node --version   # Must be >= 18.0.0
npm --version
```

If Node.js is not available, inform the user — Remotion cannot run without it.

## Step 1: Scaffold the Project

Run `scripts/scaffold_project.sh` to create a new Remotion project. The script is idempotent — it detects an existing project and skips re-initialization.

```bash
bash scripts/scaffold_project.sh my-video-project
cd my-video-project
npm run dev   # Opens Remotion Studio at localhost:3000
```

## Step 2: Interpret the Concept

Determine the best approach. Read the relevant rule file for detailed patterns.

| Content type                        | Rule file               | Template         |
| ----------------------------------- | ----------------------- | ---------------- |
| Explainer / educational             | fundamentals.md         | explainer.tsx    |
| Product demo / marketing            | animations.md           | product-demo.tsx |
| Data visualization / animated chart | charts.md               | data-viz.tsx     |
| Video with voiceover / narration    | audio.md + subtitles.md | explainer.tsx    |
| Social media clip (short, looping)  | animations.md           | product-demo.tsx |
| 3D scene / abstract motion graphics | three-d.md              | (custom)         |
| Personalized / batch generation     | data-driven.md          | any              |
| Video with embedded media           | media.md                | any              |

## Step 3: Compose the Components

Core rules for writing Remotion components:

- **One composition per video**: `registerRoot` points to one root composition.
- **Sequences for timing**: Use `<Sequence from={30} durationInFrames={60}>` to place scenes at specific frames.
- **AbsoluteFill for layering**: Use `<AbsoluteFill>` as the base for any full-screen element.
- **Frame-based math only**: Derive all animation state from `useCurrentFrame()`. Never use `Date.now()` or `setTimeout`.
- **Spring over easing**: Prefer `spring({ frame, fps })` for natural motion.
- **Props for everything variable**: Hardcoded values → props. This enables data-driven rendering.

### Component structure pattern

```tsx
import {
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
  AbsoluteFill,
  Sequence,
} from "remotion";

type MySceneProps = {
  title: string;
  accentColor: string;
};

export const MyScene: React.FC<MySceneProps> = ({ title, accentColor }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const opacity = interpolate(frame, [0, 30], [0, 1], {
    extrapolateRight: "clamp",
  });
  const scale = spring({ frame, fps, config: { damping: 12, stiffness: 100 } });

  return (
    <AbsoluteFill style={{ backgroundColor: "#0a0a0a" }}>
      <div
        style={{ opacity, transform: `scale(${scale})`, color: accentColor }}
      >
        {title}
      </div>
    </AbsoluteFill>
  );
};
```

## Step 4: Preview

Remotion Studio provides hot-reload preview. Start it with:

```bash
npm run dev
```

Studio opens at `http://localhost:3000`. The timeline scrubber lets you inspect any frame.

Use `<Still>` component for frame-accurate screenshots during iteration.

## Step 5: Iterate

| Request                | Action                                                            |
| ---------------------- | ----------------------------------------------------------------- |
| "Slower/faster"        | Adjust `durationInFrames` on `<Sequence>` or change FPS           |
| "Different color"      | Update props passed to composition                                |
| "Add a section"        | Add new `<Sequence>` block with incremented `from` offset         |
| "Change font"          | Load via `@remotion/google-fonts`, apply as CSS `fontFamily`      |
| "Add background music" | Add `<Audio src={staticFile('audio.mp3')} />` to root composition |
| "Make it loop"         | Set `durationInFrames` and design matching first/last frame state |
| "Add captions"         | See subtitles.md for SRT parsing and word-level timing            |

## Step 6: Render

Use `scripts/render.sh` to render the final video:

```bash
bash scripts/render.sh --composition MyComposition --quality final --format mp4
```

### Quality presets

| Preset    | Resolution | FPS | Use case              |
| --------- | ---------- | --- | --------------------- |
| `preview` | 480p       | 15  | Fast layout check     |
| `draft`   | 720p       | 30  | Client draft review   |
| `final`   | 1080p      | 30  | Standard delivery     |
| `4k`      | 2160p      | 60  | Presentation / cinema |

### Format options

| Format | Use case                         |
| ------ | -------------------------------- |
| `mp4`  | Standard delivery (H.264)        |
| `webm` | Web-optimized                    |
| `gif`  | Embeddable in docs, social media |

## Error Handling

| Error                           | Cause                                   | Resolution                                                                     |
| ------------------------------- | --------------------------------------- | ------------------------------------------------------------------------------ |
| `node: command not found`       | Node.js not installed                   | Install Node.js 18+ from nodejs.org                                            |
| `Cannot find module 'remotion'` | Dependencies not installed              | Run `npm install` in the project directory                                     |
| `Composition not found`         | Wrong composition ID                    | Check `registerRoot` and `<Composition id=` match                              |
| `delayRender timed out`         | Async asset load > 30s                  | Increase timeout via `delayRender('reason', { timeoutInMilliseconds: 60000 })` |
| `OffthreadVideo failed`         | Video codec not supported               | Convert to H.264 MP4 with ffmpeg first                                         |
| `ENOMEM` during render          | Out of memory on large compositions     | Reduce `--concurrency` flag, or lower resolution                               |
| `Port 3000 already in use`      | Another dev server running              | Kill existing process or set `--port 3001`                                     |
| Spring animation goes past 1.0  | Missing `{ extrapolateRight: 'clamp' }` | Add extrapolation clamp to `interpolate` calls                                 |
| Fonts not loading in render     | Font not loaded before render starts    | Use `@remotion/google-fonts` or `delayRender` for font face load               |

## Limitations

- **Node.js required** — Remotion is a Node.js framework. Cannot run in Python-only or headless container environments.
- **Chromium dependency** — Remotion renders via Chromium. The `npx remotion render` command downloads it automatically, but it requires ~300MB disk space.
- **No server-side Lambda in v1** — Cloud rendering via `@remotion/lambda` is deferred to a future skill version. Local rendering only.
- **Large renders are slow** — A 60-second 1080p video at 30fps = 1800 frames rendered through Chromium. Plan for 10-30 minutes on a typical laptop.
- **GIF size** — GIFs at full resolution are large. Limit to 480p and <10 seconds for embeddable GIFs.
- **Audio in preview** — Remotion Studio supports audio playback in preview. Rendered audio requires ffmpeg.

## Design Principles

- **Frame-based thinking**: Every visual state is a function of the current frame number. No timers, no intervals.
- **Composition-first**: Split video into logical `<Sequence>` blocks. Each scene is its own component.
- **Spring over easing**: `spring()` gives physically accurate motion. Only use `interpolate` with easing when spring doesn't fit.
- **Props for content**: Never hardcode strings, colors, or data inside components. Pass via props to enable reuse.
- **Type everything**: All composition props have TypeScript types enforced via `z.infer<typeof schema>` (Zod) or explicit interfaces.

## Cross-Reference

For **mathematical animations**, **algorithm visualizations**, or when **Node.js is unavailable**, use `concept-to-video` (Manim/Python) instead. Manim runs in any Python environment and excels at geometric proofs, equation animations, and LaTeX rendering.
