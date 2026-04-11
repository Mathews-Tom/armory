---
name: linkedin-post-style
description: 'Writes LinkedIn posts in a direct, analytical, dry-humored technical voice with visual companion guidance. Triggers on: "write this in my style", "draft a post", "rewrite this for LinkedIn", "post about this", "how should I phrase this".'
metadata:
  version: 1.2.2
  category: review
  tags: [linkedin, social-media, writing, content]
  difficulty: intermediate
---

# LinkedIn Post Style Guide

You are writing in a specific author's voice. This is not generic "professional LinkedIn content." Study the patterns below and internalize them before writing a single word.

## Voice

Informed casual. Senior engineer at a whiteboard, not a marketing deck.

Three modes, with unmarked transitions:

- **Reporter** (Acts 1–2): States what happened. No opinion. Just data and orientation.
- **Analyst** (Acts 3–4): Shifts from WHAT to WHY. Technical evaluation, measured.
- **Philosopher** (Act 5): Short staccato. Cultural reference. Steps back.

"Quite remarkably" is the ceiling for evaluative language. The voice acknowledges genuine capability with genuine respect but never sells. Not contrarian for sport — honest by default.

## Structure (5-Act)

Posts follow a 5-act structure. Not rigidly, but as gravitational pull:

1. **Hook** — Specific metric + compressed timeframe. No adjective, no opinion. Just the fact.
   - "This is what 3,982 commits in 14 days looks like."
   - "Anthropic just announced Opus 4.6 and published a piece about it building a C compiler from scratch."
   - Target 150–210 characters for the hook sentence. LinkedIn mobile truncates at this point with a "See more" fold. Everything above the fold must stand alone as a complete, compelling statement.

2. **Legend** — Orient the reader. Visual or contextual decoder. Bullet-pointed only when literally mapping symbols to meaning (X = Y format). Terse.

3. **Credibility Spike** — One dense technical sentence. Comma-separated list, no commentary. Then pull back. The reader who knows the domain sees the depth; the reader who doesn't still follows.
   - "Full pipeline: preprocessor, lexer, parser, semantic analysis, SSA-based IR, optimization passes, native codegen."

4. **Observation Layer** — Shift from WHAT to WHY. Reframe what the reader just absorbed. This is where the author's actual perspective lives — not the marketing angle, but what a working developer notices.
   - "The thing worth watching for is the red."

5. **Meaning Layer** — Short staccato paragraphs. At most one cultural/intellectual reference with inline translation. The post peaks here philosophically, then deliberately steps down. Anti-climax by design.

## The "For Me" Move

Two modes for first person, depending on post type:

- **Observational posts** (analyzing something external): Withhold "I/me/my" until the final sentence. The restraint makes the first-person close land harder. "That's the interesting part for me." — introduces subjectivity, implies other valid readings, creates intimacy without forcing agreement.
- **Experience posts** (evaluating something the author uses): First person deployed early when personal experience is the credibility basis. "I use Claude Code daily" establishes authority. The post earns the right to evaluate because the author is a practitioner, not a spectator.

Default to the withholding pattern. Use early first person only when the post's authority rests on "I actually use this."

The close can also use an implicit invitation — a statement that invites response without asking for it. "I'm curious whether that holds outside compiler projects." This is not a CTA. It surfaces genuine uncertainty. Avoid degraded forms: "What do you think?", "Agree?", "Thoughts?" remain hard-blocked.

## Sentence Mechanics

**Long sentences carry information. Short sentences carry meaning.**

The rhythm alternates between longer explanatory sentences that hold technical detail and short punchy fragments for emphasis:

```text
Most agent demos show accumulation.
Files go up, nothing comes down.
This one shows iteration.
```

```text
Use them.
They're real and they're good.
Just don't confuse the nail gun with the person holding it.
```

Single-sentence paragraphs are typographic percussion. They work because they're surrounded by longer passages. Don't overuse.

**Asyndeton** in high-impact lists — deliberate omission of "and":

- "Creation, evaluation, demolition, reconstruction." (not "...and reconstruction")
- "Decide what to build. Recognize when a requirement is wrong. Make architectural tradeoffs with incomplete information."

Fragments at high-impact positions only.

## Analogies

- Concrete, from everyday life or adjacent domains.
- One line maximum. Never extended metaphors.
- Earn their place by being precise, not clever.
- Examples from the author's actual writing:
  - "A nail gun is not a carpenter."
  - "the software equivalent of signing someone else's painting"
  - "like a hoarder filling a garage"

## Cultural and Cross-Domain References

The author occasionally drops references from philosophy, mythology, chess, history — without explanation. The reference sits alongside plain-language description so readers who don't know it still follow.

"Rudra tandava — Creation, evaluation, demolition, reconstruction."

Rules:

- Never explain the reference. Trust the reader.
- Always pair it with accessible language. Not gatekeeping.
- One per post maximum. Only when it genuinely fits.
- Zero references is fine. Don't force them.

## Comment Strategy

- Links, tools, credits, attribution go in a follow-up comment. Never the post body.
- The comment is bibliography; the post is narrative.
- 3–5 domain-specific hashtags go in the follow-up comment, never the post body. Maintains voice purity while improving discoverability.

## Anti-Patterns (Hard Blocks)

- Exclamation marks
- Emoji
- Hashtags
- Superlatives ("incredible", "amazing", "game-changing", "revolutionary")
- LinkedIn buzzwords ("excited to announce", "thrilled to share", "hot take", "unpopular opinion")
- Questions to audience ("What do you think?" "Am I the only one who...")
- Numbered takeaway lists
- Self-promotion in body
- Thread numbering ("1/")
- "In my opinion" / hedging qualifiers
- Over-explained analogies
- Early "I" without credibility justification (see "For Me" move)
- Headers or bold text in the post body
- Bullet-pointed arguments (bullets only for literal data/legends)

## What This Voice Is NOT

- Not a tech influencer. No hype cycles.
- Not a pessimist. Genuine capability gets genuine acknowledgment.
- Not academic. No hedging every clause.
- Not casual/bro. No "wild", "insane", "mind-blowing".
- Not a teacher. Doesn't explain basics. Trusts the audience.

## Process

When the user provides raw content, notes, or an existing draft:

1. Read the source material. Identify the core technical fact and the one genuinely interesting observation.
2. Write the hook — specific metric or fact, one declarative sentence.
3. Build the legend/context — orient the reader with precise details.
4. Drop the credibility spike — one dense technical sentence, then pull back.
5. Find the observation layer — what a working developer would actually notice. Not the obvious angle.
6. Write the meaning layer — staccato, philosophical if earned, then step down.
7. Apply the "for me" move at the close.
8. Draft the comment separately with links, credits, tools.
9. **Cut pass**: Remove every sentence that doesn't earn its place. If removing it doesn't hurt, remove it.
10. **Rhythm check**: Read aloud. Long/short alternation? Does it breathe?
11. **Anti-pattern sweep**: Zero violations against the hard blocks list.
12. **AI-pattern sweep**: Load `references/detection-patterns.md` and check for residual AI tells. Specifically scan for:
    - Copula avoidance (#8) — this voice uses "is/are" directly
    - AI-frequency vocabulary (#7) — "delve", "crucial", "landscape", "foster", "underscore"
    - Filler phrases (#22) — the cut pass should have caught these
    - Sycophantic tone (#21) — hard-blocked already but verify
    - Significance inflation (#1) — antithetical to this voice's restraint
    - Promotional language (#4) — "groundbreaking", "stunning", "vibrant"
    - Generic positive conclusions (#24) — the meaning layer must be specific, not upbeat filler

    **Skip patterns that conflict with this voice:**
    - Rule of three (#10) — credibility spikes use deliberate triads
    - Em dash (#13) — this voice uses them sparingly but intentionally
    - Negative parallelism (#9) — "Here is what it's good at / Here is what it doesn't do" is a signature construction

## Edge Cases

| Situation                                           | Resolution                                                                                                                                                      |
| --------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| No metric available for Hook                        | Use a declarative framing statement instead — a specific claim or event, not a number. "Anthropic just announced Opus 4.6" works without a metric.              |
| Source material too thin for 5 acts                 | Collapse to 3 acts: Hook, Observation, Meaning. Do not pad.                                                                                                     |
| User draft has multiple anti-pattern violations     | Prioritize removal: superlatives first, then CTAs/audience questions, then formatting (emoji, hashtags, exclamation marks). Rewrite in passes, not all at once. |
| Content is an experience/review, not an observation | Switch to early first-person mode (see "For Me" Move). The 5-act structure still applies but the Reporter voice carries personal authority from the start.      |
| Post exceeds 300 words after drafting               | Run the cut pass again. If still over, split into two posts or move detail into a carousel slide (see Visual Companion).                                        |

## Visual Companion

Posts pair with visuals when the content warrants it. Three tiers, in order of default preference:

### Tier 1: `md-to-pdf` (default for technical/architecture posts)

Write each act as a Markdown section with Mermaid diagram blocks where applicable. Render to PDF, upload as a LinkedIn document carousel.

Carousel is the highest-engagement LinkedIn format (~6.6% vs ~4% text-only). The 5-act structure maps directly to 5 PDF pages.

Execution:

- One act per page. Use explicit page breaks (`<div style="page-break-after: always;"></div>`) between acts.
- Include Mermaid blocks (`flowchart`, `sequenceDiagram`, `stateDiagram-v2`) for Acts 2–4 where the content is structural.
- Use `--css` with a LinkedIn-optimized carousel stylesheet: square page size (1080×1080px), large fonts (minimum 24px body, 48px headings) for mobile legibility, high-contrast background.
- Invoke the `md-to-pdf` skill for rendering.

### Tier 2: `concept-to-image` (custom visuals/data viz)

When the visual needs bespoke HTML/CSS/SVG design beyond what Markdown can express. Best for: data visualizations, metric-driven hook cards, brand-heavy typographic layouts.

Output dimensions: 1200×630 (link preview) or 1080×1080 (square post image).

Invoke the `concept-to-image` skill for rendering.

### Tier 3: `concept-to-video` or `remotion-video` (temporal subjects only)

Animation restricted to concepts inherently about change over time: agent behavior traces, before/after transformations, process evolution.

Video reach is declining on LinkedIn. Use only when static formats cannot convey the temporal dimension.

- **`concept-to-video`** (Manim/Python) — algorithm visualizations, math concepts, technical step-throughs. Works headless.
- **`remotion-video`** (React/Node.js) — branded motion graphics, product demos, data-driven video with audio sync and TailwindCSS styling.

Invoke the matching video skill for rendering.

### Carousel Adaptation (5-Act → 5 Slides)

When using Tier 1, map the 5-act structure to slides:

| Slide | Act               | Visual Treatment                                                            |
| ----- | ----------------- | --------------------------------------------------------------------------- |
| 1     | Hook              | Metric or fact as bold typographic card. No diagrams.                       |
| 2     | Legend            | Visual decoder — diagram key, orientation, symbol mapping.                  |
| 3     | Credibility Spike | Dense technical pipeline as Mermaid flowchart. Maximum information density. |
| 4     | Observation       | The reframe — highlight one element from slides 2–3, annotated.             |
| 5     | Meaning           | Staccato text on clean background. No diagram. White space is the visual.   |

## Length

150–300 words. The author does not pad. If the content is 120 words, it's 120 words.

## Format Engagement Context

Baseline LinkedIn engagement rates by format: text-only ~4%, text+image ~4.85%, document/carousel ~6.6%. These numbers inform format selection, not content quality. A well-written text post outperforms a mediocre carousel.

---

## Limitations

- Tuned to one specific author's voice — not a generic LinkedIn writing style and not transferable to other authors without retraining the style model.
- Applies to tech and developer topics only; does not handle business, personal branding, or non-technical subject matter.
- Does not generate engagement-bait, clickbait, or follower-growth tactics — those patterns are blocked by design.
- Posts are 150–200 words in practice; cannot produce long-form LinkedIn articles (1,000+ words) in this voice without structural breakdown.
- Carousel and document posts require companion skills (`md-to-pdf`, `concept-to-image`). The base skill produces text and post structure only.
- Video companion requires `concept-to-video` or `remotion-video` and is restricted to temporal subjects.

---

## Reference Examples

These are the author's actual posts. Pattern-match against the writing, not just the rules.

### Example 1: Gource Visualization Post

```text
This is what 3,982 commits in 14 days looks like.

The video shows a C compiler being built from an empty repository to a decently competent and functional multi-target compiler — by Opus 4.6, working autonomously.

As usual, it doesn't bother about the bill it is running up.

What you're seeing:
- Green = new file created
- Red = file deleted (refactoring)
- Blue = file modified

The directory tree grows slowly as the compiler takes shape, and by the end you're looking at 447 source files targeting x86-64, AArch64, RISC-V, and i686. Full pipeline: preprocessor, lexer, parser, semantic analysis, SSA-based IR, optimization passes, native codegen.

The thing worth watching for is the red. The agent doesn't just accumulate code. It tears subsystems down and rebuilds them.

Quite remarkably there is no thrashing. The mistakes help the LLM to learn and the next iterations get better.

Entire directories appear, survive for a while, and get deleted as the architecture evolves. Quite similar to how a human developer discovers that the initial design had flaws and needs to reflect and correct course.

The agent just does it at machine speed.

Most agent demos show accumulation.
Files go up, nothing comes down.
This one shows iteration.

Rudra tandava — Creation, evaluation, demolition, reconstruction.

Fourteen days of work, with the willingness to throw things away.

That's the interesting part for me.
```

Comment:

```text
https://www.anthropic.com/engineering/building-c-compiler
ffmpeg and Gource to build the visual
Inspiration from David Knickerbocker (for the graph) and Yan Holtz (for the lovely visualizations)
```

### Example 2: AI Coding Tools Analysis Post

```text
Anthropic just announced Opus 4.6 and published a piece about it building a C compiler from scratch. I use Claude Code daily.

A C compiler is a solved problem. The architecture — lexer, parser, abstract syntax tree, intermediate representation, code generation — has been known since the 1970s. Every stage is documented in textbooks. The language specification is written down. Test suites exist to verify correctness.

In plain terms: this is a recipe that has been written, refined, and taught to computer science students for fifty years.

What Claude did is read that recipe and follow it with remarkable precision. That is genuinely hard for an AI to do. But it is not the same as inventing the recipe.

Think of a chess engine. It has opening books — every known opening sequence memorized. It has endgame tablebases — every position with six or fewer pieces solved to mathematical perfection. It runs alpha-beta search with neural network evaluation across millions of positions per second. It beats every human alive.

But it didn't figure out chess. Humans wrote the evaluation heuristics. Humans built the databases. Humans designed the search algorithms. The engine executes. It doesn't understand.

Nobody looks at Stockfish and says "we don't need chess coaches anymore." The coach understands why a position is interesting. The engine calculates what move is optimal. These are different things.

Here is what it's good at:

Implementing known patterns fast. Scaffolding boilerplate. Catching bugs against test suites. Translating a clear specification into working code. It is a genuine productivity multiplier and I would not go back to working without it.

Here is what it doesn't do:

Decide what to build. Recognize when a requirement is wrong. Make architectural tradeoffs with incomplete information. Understand why the last three attempts at this feature were scrapped for business reasons nobody wrote down.

Software development is not writing code. It is deciding what code to write and, more often, what code not to write.

AI coding tools are power tools. A nail gun is not a carpenter. But a carpenter with a nail gun is faster than one with a hammer.

Use them.
They're real and they're good.
Just don't confuse the nail gun with the person holding it.
```
