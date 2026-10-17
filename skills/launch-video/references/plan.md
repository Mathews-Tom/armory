# Write the launch plan

Write `RUN_DIR/launch-plan.md`. One focused page: the creative contract for the composition. It says what the video must communicate and which project material it uses. It does not prescribe markup or keyframes.

## Plan structure

```markdown
# Launch Plan: [Project Name]

## What is it?
[One sentence. What it does and what makes it funny or impressive.]

## The angle
[The creative premise: the joke, the hook, the claim. Why this video belongs to this project and no other.]

## Hook (first 2–3 seconds)
[The opening moment. What word, image or motion earns the next 20 seconds?]

## Key moments
[2–3 sharp highlights, specific: "the altitude meter counting up", not "feature callouts".]

## Outro / punchline
[How it lands. The final line and the beat before the name.]

## User flow worth showing
[entry → key action → result, from rubric question 9, or "none — landing-page only".]

## How to get it
[The real URL, install command or call to action, or "no public destination" (see inspect.md).]

## Tone
- Preset: [default / polished / yc-parody / chaotic / deadpan / cinematic / app-store]
- Creative direction: [freeform phrase, inferred or from the user]
- Interpretation: [one sentence on pacing, writing, visual energy and restraint]

## Format: [landscape 1920x1080 / vertical 1080x1920 / square 1080x1080]
## Duration: [target seconds]

## Visual identity (from the project)
- Background / text / accent: [exact values]
- Display font / body font: [names, and the font files the user will supply]
- Strongest visual element: [what from the project to recreate]

## Assets
| File | Origin | Licence |
|---|---|---|
| [logo.svg] | [project path or URL] | [SPDX id or user-owned] |

## Audio
- Track: [user-supplied file, its source and licence, or "none"]
- Role and volume posture: [bed / sparse / swell / silence]

## Fictional stand-ins
[Any real personal data replaced, or "none".]

## Share copy (draft)
[One sentence.]

## Storyboard

### Scene 1 — [name] — [start]–[end]s
On screen: [what appears, which real project material]
Text and hold: [each line a viewer must read, with its settled time]
Sequential / interaction: [what appears one by one, or what action is simulated; or none]
Transition: [type and length] → Scene 2
```

## Shape and scene counts

Default shape: **Hook (2–3s) → Reveal (2–4s) → 2–3 sharp highlights (5–12s) → Punchline/outro (2–4s)**. A starting shape, not a template.

| Tone | Scenes | Pacing |
|---|---|---|
| `default` | 4–5 | Comfortable; each moment breathes |
| `polished` | 3–4 | Fewer scenes, longer holds |
| `yc-parody` | 4–5 | Structured; one claim per scene |
| `chaotic` | 6–8 | Rapid; some scenes under 2s |
| `deadpan` | 3–4 | Long holds, big empty space |
| `cinematic` | 4–5 | Big type, dramatic reveals |
| `app-store` | 4–6 | Feature cards, clean reveals |

## Duration

Scene durations must sum to 15–25 seconds; 18–22 is the sweet spot. Count them. Under 15, add a scene or lengthen holds. Over 25, cut a scene. `finish` rejects a render outside this window unless the user asked for another length and you pass `--min-seconds` / `--max-seconds` to match.

## Reading time

Pace comes from fast motion and tight cuts, never from pulling text away before it can be read. Every line a viewer must read needs settled time (fully entered, not yet exiting):

- Short label or 1–3 words: about 0.8s.
- Headline or sentence: about 0.3s per word, at least 1.2s. The hook line gets the most.

Entrances and transitions stay snappy (0.3–0.6s). A line can slam in fast and then hold. Two failures to design out now:

- **Too much text for the scene.** A 4s scene carries 2–3 short reads, not 6. Cut copy or split the scene; never speed it up.
- **Sequential text on a fast rhythm.** Reveals 0.5s apart suit accents, not readable lines. Reveal quickly, then hold the full set on screen.

## Choosing what to show

Every video shows something real from the project. In order of preference:

1. **A working-app moment** recreated from the real routes and components: the upload screen, the result view, the dashboard with realistic content. The product doing its job beats the product describing itself.
2. **A real UI element** recreated in HTML and CSS: a hero card, a swipe card, a progress meter, a stat block.
3. **The core concept animated**, grounded in the idea ("taxis for taxis": one taxi inside another).
4. **Text-forward**, when the product is its copy: giant display type, minimal chrome.

Never fill scenes with abstract patterns, colour washes or generic motion that could belong to any video. When a user flow exists, the centrepiece scenes show that flow; a stat card or the landing-page hero may frame it at most once.

## Make it alive

Look for things that can appear one by one (cards, stats, list items, results) and actions that can be simulated (a cursor click, a swipe, text typed into a field). Commit to them in the storyboard: "three profile cards slide in one by one", "the hook line types out character by character". The plan is the contract; unplanned motion rarely appears.

## Transitions by tone

| Tone | Preferred transitions |
|---|---|
| `default` | Staggered crossfade, clean wipe |
| `polished` | Soft staggered crossfade (0.6–0.8s), slide |
| `yc-parody` | Hard cut, minimal fade (0.2s) |
| `chaotic` | Hard cut, flash, zoom |
| `deadpan` | Slow fade through the background, long hold |
| `cinematic` | Dramatic wipe, crossfade |
| `app-store` | Slide or wipe (0.35–0.45s) |

`compose.md` maps each transition onto CSS keyframes.
