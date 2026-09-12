# Domain Style Profiles

Voice calibration rules per writing domain. Apply the matching profile during Phase 2 (draft the rewrite). Target tells are referenced by pattern name — see `detection-patterns.md`.

---

## Academic

**Register:** Formal, measured, evidence-based.
**Audience:** Researchers, reviewers, graduate students.

Rules:

- Maintain hedging where epistemically appropriate ("suggests" vs. "proves") — but remove _excessive_ hedging (stacked qualifiers)
- Preserve citation structure and in-text references exactly
- Passive voice is acceptable where convention demands it (methods sections)
- Do not inject personality or first-person unless the original uses it
- Avoid contractions
- Replace AI-inflated significance claims with measured statements: "This study examines..." not "This groundbreaking study delves into..."
- Technical jargon is expected — do not simplify domain-specific terms
- Sentence length: longer is acceptable, but vary within paragraphs

**Preserve:** Citation formats, section headings (Introduction/Methods/Results/Discussion), figure/table references, statistical notation.

**Target tells to fix:** significance inflation, AI-frequency vocabulary, formulaic challenges/future-outlook sections, vague attributions.

---

## Technical

**Register:** Precise, direct, information-dense.
**Audience:** Engineers, developers, technical practitioners.

Rules:

- Clarity over style — if a sentence is clear but boring, leave it
- Code blocks, terminal output, config snippets pass through unchanged
- Numbered steps and bullet lists are natural in technical writing — do not convert all lists to prose
- Contractions are fine
- First person ("I configured...", "we deployed...") is natural in technical blogs and docs
- Replace promotional language with specifics: "blazing fast" -> "handles 10K requests/second"
- Remove all chatbot wrappers aggressively

**Preserve:** Code blocks, command-line examples, version numbers, API endpoints, configuration values, error messages.

**Target tells to fix:** promotional language, copula avoidance, AI-frequency vocabulary, boldface and inline-header lists.

---

## Blog

**Register:** Conversational, opinionated, personal.
**Audience:** General readers, tech-curious non-specialists.

Rules:

- First person is expected and natural
- Contractions, fragments, rhetorical questions all allowed
- Opinions and reactions are good — "I genuinely don't know how to feel about this"
- Humor and asides are human signals — preserve or introduce where natural
- Vary rhythm aggressively: short punchy sentences mixed with longer explanatory ones
- Analogies should be concrete and from everyday life
- Remove ALL promotional language — blog readers detect it instantly
- Remove significance inflation — readers came for the author's perspective, not Wikipedia-style importance claims

**Preserve:** Personal anecdotes, named sources, specific experiences, the author's apparent opinions.

**Target tells to fix:** all Class A staging patterns and Class B inflation patterns, plus forced triads.

---

## Social

**Register:** Casual, compressed, direct.
**Audience:** Reddit, Twitter/X, forum users.

Rules:

- Extremely short paragraphs (1-3 sentences)
- Fragments and incomplete sentences are natural
- Slang and informal language acceptable
- No hedging — social media writing is assertive
- No significance inflation — users will mock it
- Remove ALL chatbot artifacts — these are the most obvious tell on social platforms
- Contractions mandatory — "do not" reads as AI on Reddit
- Lowercase acceptable for casual tone
- Swearing is fine if the original contains it

**Preserve:** Links, usernames/handles, quoted text, platform-specific formatting.

**Target tells to fix:** chatbot wrappers, knowledge-cutoff disclaimers, excessive hedging, filler phrases, promotional language.

---

## Professional

**Register:** Clear, neutral, competent. Business correspondence tone.
**Audience:** Colleagues, clients, stakeholders.

Rules:

- Polite but not sycophantic — remove "I hope this finds you well" only if it reads as filler
- Contractions acceptable in internal communication, avoid in external/formal
- No promotional language unless the context is genuinely marketing
- Action items and next steps should be clear and direct
- Remove AI vocabulary but preserve business terminology where standard
- Moderate formality — neither stiff nor casual
- First person is natural ("I'll follow up on...", "We reviewed...")

**Preserve:** Names, dates, action items, deadlines, project references, organizational terminology.

**Target tells to fix:** chatbot wrappers and sycophancy, filler phrases, AI-frequency vocabulary, formulaic upbeat conclusions.

---

## Marketing

**Register:** Persuasive but authentic. Benefits-focused.
**Audience:** Potential customers, users, decision-makers.

Rules:

- Some promotional language is expected — but it must be specific, not generic
- "Blazing fast" is AI slop; "loads in 0.3 seconds" is marketing with substance
- Remove vague superlatives, keep specific claims
- Social proof should cite real numbers or real customers, not "industry experts agree"
- CTA (call to action) is expected — do not remove it, but make it specific
- Bullet lists and feature comparisons are natural format for marketing
- Remove AI tells that undermine trust: chatbot artifacts, hedging, generic conclusions

**Preserve:** Product names, feature lists, pricing, CTAs, testimonials (if sourced), comparison data.

**Target tells to fix:** vague attributions, formulaic upbeat conclusions, AI-frequency vocabulary, significance inflation.

---

## Engineering

**Register:** Terse, factual, artifact-shaped. PR descriptions, commit messages, changelogs, code review replies, ADRs, issue comments.
**Audience:** Maintainers, reviewers, future readers of `git log`.

Rules:

- Lead with what changed and why; observable behavior over intent narration
- Commit subjects stay imperative; bodies explain what/why, never "this commit was created to..."
- Describe the code as it is now — edit history belongs to version control, not the text (writing-about-the-previous-version pattern)
- Review replies answer first and add only what is new to the reviewer (re-explaining-shared-context pattern)
- Concrete numbers over adjectives: "removes ~4% idle CPU", not "significantly improves performance"
- Issue/PR references, SHAs, version numbers, and error messages pass through exactly
- Lists are natural for changelogs and parallel changes — do not force prose
- No emoji in headings, no bold-label bullets that restate their label

**Preserve:** Issue references, commit SHAs, semver strings, file paths, flag names, benchmark numbers, reviewer names.

**Target tells to fix:** staged run-up, negative parallelism, boldface and inline-header lists, chatbot wrappers and sycophancy, writing about the previous version, re-explaining shared context, mechanical chat residue.
