# Verification and the render record

## Commands

Every command has `--help`. `PROJECT` is a directory containing `index.html`.

| Command | Network | Purpose |
|---|---|---|
| `bootstrap PROJECT (--browser-path P \| --download-browser)` | Yes (install, optional browser download) | Install the pinned package with the lockfile's package manager and write the environment lock |
| `doctor PROJECT [--json]` | No | Re-verify node, FFmpeg, ffprobe, the installed package version and the browser version against the lock |
| `init TEMPLATE DEST` | No | Copy a bundled template into an empty directory |
| `fonts add PROJECT …` | No | Provision a user-supplied font and its licence |
| `audit PROJECT [--require-provenance] [--deny-warnings] [--json]` | No | Asset, font, timing and provenance audit |
| `plan PROJECT [--fps N]` | No | Frame-aligned sample times |
| `run lint\|check\|snapshot\|render PROJECT [--fps N]` | No network required by the bundled templates; arbitrary project code is not isolated | Audit-gated pinned invocation, bound to source, verified toolchain, config and effective FPS |
| `deliver PROJECT --out DIR [--fps N]` | No | Verify matching reports and artifacts, then assemble a standalone source bundle |

Exit status is 0 on success and 1 on failures or findings.

## Bootstrap and the environment lock

Bootstrap installs the exact package from `config.toml` into the project (`npm install --save-exact`, `pnpm add --save-exact`, `yarn add --exact` or `bun add --exact`, chosen from the lockfile; npm for a fresh project; conflicting lockfiles are an error). It does not install Node, FFmpeg or Chrome, and it never renders.

The browser is chosen explicitly. `--browser-path` pins an existing executable. `--download-browser` runs the pinned CLI's `browser ensure`, then `browser path`. *source* Those commands resolve through the CLI's own search order and may download; whichever executable results is pinned by its path. The lock records the browser's real `--version` output, not a doctor cache entry.

`.html-video/environment.json` records tool paths and exact version strings. Every `run` re-reads it, re-executes each `--version`, compares, and aborts on any difference. Commands run `node <project>/node_modules/hyperframes/bin/hyperframes.mjs …` directly, with:

| Variable | Value |
|---|---|
| `HYPERFRAMES_NO_TELEMETRY`, `HYPERFRAMES_NO_UPDATE_CHECK` | `1` |
| `HYPERFRAMES_BROWSER_PATH`, `PRODUCER_HEADLESS_SHELL_PATH` | the pinned browser *(source: the CLI checks these before any cache or download)* |
| `HYPERFRAMES_FFMPEG_PATH`, `HYPERFRAMES_FFPROBE_PATH` | the recorded binaries |
| `GEMINI_API_KEY` | removed *(source: `snapshot` runs a hosted vision model by default when it is set)* |

## What each step runs

| Step | Fixed arguments |
|---|---|
| lint | `lint --json .` |
| check | `check --json --no-browser-gpu --at <plan times> --timeout <ms> .` (`--strict` on request) |
| snapshot | `snapshot --at <up to 12 plan times> --no-end --describe false --no-browser-gpu -o .html-video/snapshots .` |
| render | `render --strict --no-best-effort --no-browser-gpu --workers 1 --fps N -o <mp4> .` |

Each step invalidates its previous report before preparing the environment or invoking a tool. It audits the project before and after execution; source mutation fails the step. `.html-video/reports/<step>.json` binds the source closure, effective FPS, relevant config and verified environment, including the CLI entry-file digest and actual tool paths/versions. These fields identify the checked context, not every transitive dependency or machine setting. Use one FPS for lint, check, snapshot, render and delivery; an override is not inferred from an old report.

## Coverage policy for check

`check` fails the step unless the JSON report shows all of: `ok` true, `browserSkipped` false, the requested times in `layout.samples`, `motion.enabled` true with `motion.samples` above 0 for an animated composition, `contrast.checked` above 0 when text exists, and `_meta.version` equal to the pin. No visible text is reported as "contrast not proven", never as a pass. Warnings are listed, not hidden.

Coverage applies only to requested samples, deterministically capped at the configured maximum (80 by default). Larger compositions can omit clip boundaries; passing the sampled checks is not exhaustive timeline coverage.

Passing is necessary, not sufficient. Open every `contact-sheet*.jpg` page and the individual frames, compare against intent, and record awkward crops, wrong emphasis or mistimed clips. Hyperframes paginates contact sheets for larger sample sets; all pages are hashed, checked for additions/deletions, and delivered. Known unmapped-font or Google Fonts compiler logs fail the run.

## Render verification

After rendering, ffprobe must report the declared width and height, the requested frame rate (to 0.01), a duration within 1.5 frames of the declared one and a frame count within one of `duration x fps`. Render destinations must be MP4 files and cannot collide with audited inputs. Resolved destinations inside the project must be under `renders/`; the default render directory cannot escape through a symlink. Explicit external MP4 destinations are allowed. Only an accepted output target is deleted before rendering so a failure cannot leave a stale file.

## Reproducibility record

`deliver` writes `RENDER.json` with the verified pinned spec and toolchain context, config, effective FPS, step arguments and sampling times, output digest/size, ffprobe result, warnings, source closure, and digests for every delivered file. It copies the actual bound reports into `reports/` and records their provenance; it does not relabel old results with a new configured version. Report timestamps are informational, not authority.

Rendering is seek-driven from the source, so the same source in the same environment is expected to look the same, but **no byte-identity claim is made**. Browser, encoder, operating system and font files all affect pixels and bytes. Re-render in a matching environment and compare frames, not hashes.

## Delivery gate

`deliver` refuses audit errors, missing/failed reports, source/config/toolchain/FPS mismatches, altered or missing videos/frames/contact-sheet pages, and non-empty output directories. It re-hashes copied evidence and re-audits `source/` with provenance required; failed bundles are removed. The bundle contains editable source and reachable assets, user-declared licences, project dependency manifests, MP4, snapshots, contact-sheet pages, reports and `RENDER.json`. This verifies structural and artifact consistency, not semantic intent or complete visual correctness.
