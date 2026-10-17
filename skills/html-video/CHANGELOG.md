# Changelog — HTML Video

## 1.0.1

- Route launch videos planned from the current project to `launch-video`, which renders through this package.
- Document that `fonts add --family` is only the provenance name and that a second font family needs its own `--alias`; without it the file silently becomes another face of `HV Text`.

## 1.0.0

- Add the package: author HTML/CSS videos and render them with a pinned, project-local Hyperframes CLI.
- Ship four original templates: title sequence, side-by-side comparison, diagram explainer and captioned sequence. Motion is finite CSS keyframes on HTML elements, seeked by the runtime's CSS adapter; no GSAP, CDN script or bundled font.
- Separate explicit `bootstrap` provisioning from local authoring and static audit. Pin the package manager, browser executable and actual environment versions; never use `npx` at render time. Arbitrary project JavaScript is not network-isolated.
- Add an offline audit for remote resources (including legacy HTML background attributes), path and symlink escapes, missing files, case mismatches, reference cycles, undeclared fonts, composition timing and user-declared provenance. Document that it is a static audit and not a script sandbox.
- Add user-selected font provisioning with mandatory licence metadata, validated project-contained mutation paths, linked CSS and compiler-visible inline font faces. Reject system-dependent `local()` sources and dynamic font-family scope instead of guessing.
- Bind lint, check, snapshot and render reports to source, verified toolchain, config and effective FPS; invalidate prior proof before reruns. Verify and deliver every snapshot and paginated contact sheet with the video, source and report provenance.
- Reject render destinations that collide with source, use a non-MP4 extension, name a directory, or escape the default render directory through a symlink; preserve input files before any render mutation.
- Add evaluation cases and deterministic tests for the audit, font, environment, coverage and delivery boundaries.
