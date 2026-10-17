# Inspect the project

Read the project in the current directory to learn what the video is about. The best material is the product **in use**, not the product describing itself.

## What to read, in priority order

1. **The main page or entry view** (`index.html`, the root route, the app shell). Extract the page title, hero headline, tagline, section headings, calls to action, testimonial copy and navigation items. This is the project's own voice.
2. **Styles** (`styles.css`, theme files, Tailwind config, CSS custom properties under `:root`). Record the exact background, text and accent colours, any gradient, and the display and body font families. These become the video's visual identity.
3. **`README.md`**: project name, one-line description, listed features, and any "how it works" or "usage" section.
4. **Package metadata** (`package.json`, `pyproject.toml`, `Cargo.toml`): `name`, `description`, and the declared licence, which you need for asset provenance.
5. **Routes and key components** (`app/`, `pages/`, route files, the editor, the upload form, the result view, the dashboard, state machines or step components). Identify the 2–3 beats of using the product: **entry → key action → result**.
6. **Example or demo folders**: sample inputs and outputs the authors tested with.
7. **`public/` or `assets/`**: logos, icons and images you can copy into the composition.

A command-line tool or library has a visual surface when the project documents real terminal output: a transcript in the README, the docs or example folders. That output, its brand assets (logo, banner, palette) and its install command are the material; see "Terminal projects" in `compose.md`. Only when the project has neither documented output nor brand assets (a backend service, a library with no examples) say so and ask the user what the video should show before planning. Do not invent a UI or invent output.

## The nine-question rubric

Answer all nine in writing before planning.

1. **What is it?** One sentence: what it actually does, or claims to do.
2. **What is the funniest or most impressive claim?** The one line from the project that earns a reaction.
3. **What is the visual hook?** The strongest visual: a palette moment, a UI element, a diagram, a card.
4. **What real UI or copy should be shown?** The section or screen with the most video-worthy content.
5. **What is the shortest satisfying video?** Would 15 seconds land it, or does it need 20?
6. **What tone fits?** If the user named a preset, use it. If they gave freeform direction, keep it and map it to the nearest preset. Otherwise infer both a preset and a short custom direction (absurd product → `yc-parody`, "fake startup launch"; earnest product → `polished`, "quiet premium product film"). See `tones.md`.
7. **What should the audio feel like?** Only if the user supplies a track: warm bed, sparse accents, cinematic swell, or deliberate silence.
8. **What should the share caption say?** Draft one sentence.
9. **What user flow is worth showing?** The 2–3 beats a real user goes through. If the project is a landing page with no app, write "none — landing-page only" and rely on question 3.

## How viewers get it

A stranger must leave knowing how to get the project. Find its real destination: a public URL, an install command, a store listing, or the project's own call to action. If the project declares none, ask the user. If there is still none, record "no public destination" in the plan, end on the project's name and a line that matches its real availability (for example "Coming soon"), and tell the user the video is a preview, not a complete launch post. Do not show a call to action such as "Download free" that leads nowhere, and never invent a URL, even when a tone preset's example shows one.

## What to skip

Never read:

- Build output (`dist/`, `.next/`, `build/`), lock files, test files and `.git/`
- Environment and secret files (`.env`, `.env.*`)
- Key and credential material (`.pem`, `.key`, `id_rsa`, service-account JSON, anything under `secrets/` or `credentials/`)
- Local configuration that commonly holds tokens, and anything `.gitignore` excludes for those reasons

## Nothing private leaves this step

Everything you read can end up on screen in a video the user posts publicly. Never carry secrets, API keys, tokens, internal hostnames or URLs, real customer or user names, email addresses or other personal data into the plan, the composition, the rendered video or the share copy. When the real UI shows such data, substitute plausible fictional stand-ins and say so in the plan.

## Ground every claim

Use the project's own copy, numbers and claims. Small illustrative UI text is fine when showing the product in use (a filename, an "Exported" toast). Invented metrics, testimonials, customer logos or claims are not.
