# AI Writing Detection Patterns

Source: [Wikipedia:Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing), maintained by WikiProject AI Cleanup (CC BY-SA 4.0). Last synced: revision of 2026-09-11. All examples below are original to this repository.

29 patterns in five classes, ordered by strength. Class A patterns justify an edit on a single sighting. Patterns marked **weak alone** are habits careful writers also have — act on them only when several tells share the same passage. Cross-reference patterns by **name**; numbers are for compact reporting and may change between versions.

Why these patterns exist: a language model writes whatever is most likely to come next, so by default it makes the choice that fits the widest range of readers and subjects. A person chooses for one reader and one subject. Word habits churn with every model release; the structural habits persist. That is why structure leads this list and vocabulary sits in the middle.

---

## Class A — Staging instead of stating

The strongest and most frequent tells in current model prose. One sighting justifies an edit.

### Pattern 1: Negative Parallelism (Not X but Y)

**Watch for:** "not just X, it's Y", "not only... but also...", "it's not X — it's Y", "X rather than Y", the contrast split across sentences ("This doesn't mean X. It means Y."), and the clipped negative tail ("..., no guesswork").

**Problem:** The negative half denies something nobody claimed, so the positive half sounds bigger. Weight is added without a claim. Keep a contrast only when the negative half corrects a belief the reader actually holds, or when both halves carry information.

Before:
> The migration isn't just a version bump — it's a fundamental rethinking of how the service handles state.

After:
> The migration moves session state out of the service and into Redis.

### Pattern 2: One-Line Closers and Dramatic Fragments

**Watch for:** a one-sentence paragraph that restates the paragraph above it; "That's the real win."; "Read that again."; "Let that sink in."; the same closer after several sections; rows of fragments ("No config. No setup. No surprises."); word-by-word emphasis ("every. single. request.").

**Problem:** The line asks the reader to pause on a claim instead of adding one. A short sentence earns its place when it carries a new fact. Cut closers that repeat; merge fragment rows into a sentence with a specific claim.

Before:
> The cache cut median latency from 80ms to 12ms.
>
> That's the real win.

After:
> The cache cut median latency from 80ms to 12ms.

### Pattern 3: Deep-Sounding Sayings

**Watch for:** "the real question is", "at its core", "what really matters", "the heart of the matter", "X is the language/currency/architecture of Y", "X becomes a trap", "X isn't a tool, it's a mindset".

**Problem:** An ordinary point is dressed as a hidden truth or aphorism, and the dressing adds no detail. Replace the saying with the specific claim it gestures at.

Before:
> At its core, observability is the language of trust between a team and its systems.

After:
> Traces let the on-call engineer see which downstream call failed without guessing.

### Pattern 4: Staged Run-Up

**Watch for:** "Let's dive in", "let's explore", "here's what you need to know", "without further ado", "Here's the thing:", "Honestly?", "Let's be honest", standalone "Look," before a routine claim.

**Problem:** The writer announces the point or stages a moment of candor instead of making the point. Delete the run-up and state the point. "Honestly" inside a casual sentence is ordinary; the tell is the standalone opener.

Before:
> Here's the thing: connection pooling matters more than most teams realize. Let's break down why.

After:
> Each new database connection costs a TLS handshake and an auth round trip, so a pool of warm connections saves 40-80ms per request.

### Pattern 5: Arguing With No One

**Watch for:** "This isn't mainly about...", "I'm not saying...", "To be clear,", "Don't get me wrong,", "Some might argue... but", "A tempting approach would be...", "One might be tempted to...", "You might think... but".

**Problem:** The text rebuts an objection or rejects an option that appears nowhere else — usually residue from an earlier draft. Delete the phantom debate; if it hides a real claim, state the claim. Keep an objection the text attributes to a real source and answers in full, and keep an alternative a reader would genuinely weigh. Several unrelated rejections in a row are a stronger sign than one.

Before:
> A tempting approach would be to retry the whole batch, but that would double-process successful rows. Instead, the worker retries only failed rows.

After:
> The worker retries only failed rows, so successful rows are never double-processed.

---

## Class B — Inflation and Borrowed Authority

The fact underneath is usually sound. Keep the fact, cut the dressing. Act on one sighting.

### Pattern 6: Significance and Legacy Inflation

**Watch for:** "stands as a testament", "marks a pivotal moment", "plays a key/vital/crucial role", "underscores the importance", "reflects a broader trend", "setting the stage for", "evolving landscape", "indelible mark", "deeply rooted", "represents a shift".

**Problem:** An ordinary detail is claimed to mark a change, prove a legacy, or embody a trend. Keep the fact, drop the significance claim.

Before:
> The 2019 rewrite marked a pivotal moment in the platform's evolution, setting the stage for the microservices architecture that followed.

After:
> The 2019 rewrite split the monolith's billing and auth modules into separate services.

### Pattern 7: Promotional Language

**Watch for:** "boasts", "vibrant", "rich" (figurative), "nestled", "breathtaking", "stunning", "renowned", "groundbreaking" (figurative), "must-visit", "state-of-the-art", "seamless", "cutting-edge", "world-class", sales-brochure ranges like "whether you're a beginner or a seasoned expert".

**Problem:** Neutral description slides into advertisement. State what the thing is and what it measurably does.

Before:
> The library boasts a seamless, cutting-edge API that empowers developers of all skill levels.

After:
> The library exposes four functions and needs no configuration for the default case.

### Pattern 8: Superficial -ing Analyses

**Watch for:** trailing participle phrases: "..., highlighting...", "..., underscoring...", "..., reflecting...", "..., showcasing...", "..., ensuring...", "..., fostering...", "..., contributing to...".

**Problem:** A clause of fake analysis rides on the end of a factual sentence, asserting meaning the source never gave. Keep only riders the source supports; otherwise end the sentence at the fact.

Before:
> The team adopted trunk-based development, reflecting its deep commitment to engineering excellence and fostering a culture of continuous delivery.

After:
> The team adopted trunk-based development. Merge conflicts dropped by half in the first quarter.

### Pattern 9: Notability and Borrowed Authority

**Watch for:** "cited in NYT, BBC, and Forbes", "written by a leading expert", "recognized globally", "an active social media presence", lists of outlets or awards without any specific claim.

**Problem:** The text asserts that a subject matters by stacking media mentions or credentials instead of saying anything. Name one real source and what it actually said, or cut the list.

Before:
> Her work has been featured in TechCrunch, Wired, and The Verge, and she is widely recognized as a thought leader in distributed systems.

After:
> In a 2025 Wired interview she argued that consensus protocols are over-deployed for workloads that tolerate stale reads.

### Pattern 10: Vague Attributions

**Watch for:** "Experts believe", "Industry reports suggest", "Observers have noted", "Some critics argue", "Studies have shown" with no study named.

**Problem:** Opinions attributed to authorities that are never identified. Name the source and what it said, or remove the claim.

Before:
> Experts agree that monorepos improve developer productivity in most organizations.

After:
> Google's 2016 paper on its monorepo reports simplified dependency management across 25,000 engineers; it does not measure productivity directly.

### Pattern 11: Vague Connection or Association

**Watch for:** "associated with", "in association with", "connected to", "in connection with", "linked to", "tied to".

**Problem:** Two things are declared connected without saying how. "She was associated with the project's leadership" hides whether she led it, advised it, or attended one meeting. State the relationship the source gives; if the source doesn't say, keep the vague wording rather than inventing a role.

Before:
> He was associated with the development of the payments platform.

After:
> He was the tech lead for the payments platform from 2021 to 2023.

### Pattern 12: Formulaic Challenges and Upbeat Conclusions

**Watch for:** "Despite these challenges... continues to thrive", stock "Challenges and Future Outlook" sections, "The future looks bright", "exciting times ahead", "a step in the right direction", any final paragraph that only cheers.

**Problem:** Problems are raised and dismissed in one rhetorical move, or the piece ends on generic optimism instead of information. State the problems plainly. End on the last concrete fact; if the source states real plans, use those.

Before:
> Despite scaling challenges, the platform continues to thrive. The future looks bright as the team pushes toward excellence.

After:
> The job queue saturates above 10K events/sec. The team's Q3 plan is to shard it by tenant.

---

## Class C — Language Habits

Vocabulary and grammar tells. The word list churns with each model generation — treat it as the weakest signal class and re-sync from the source periodically.

### Pattern 13: AI-Frequency Vocabulary

**Overused words:** additionally, align with, bolstered, crucial, deep dive, delve, emphasizing, enduring, enhance, fostering, garner, highlight (verb), interplay, intricate/intricacies, key (adjective), landscape (abstract), leverage (verb), meticulous(ly), pivotal, robust (figurative), showcase, tapestry (abstract), testament, underscore (verb), valuable, vibrant.

**Problem:** These words appear at anomalous frequency in model output, especially in clusters. A single formal word is not a tell; a sentence carrying three of them is. Keep genuine technical uses ("robust statistics", "feature gating"). This is the only vocabulary list — a word being overused does not make its synonyms suspect.

Before:
> Additionally, the intricate interplay between caching layers underscores the pivotal importance of a robust invalidation strategy.

After:
> The two caching layers can serve stale data unless invalidation is coordinated between them.

### Pattern 14: Copula Avoidance

**Watch for:** "serves as", "stands as", "functions as", "acts as", "represents", "boasts", "features", "offers" — where "is", "are", or "has" would do.

**Problem:** Simple copulas are systematically replaced with elaborate substitutes.

Before:
> The gateway serves as the single entry point and features built-in rate limiting.

After:
> The gateway is the single entry point and has built-in rate limiting.

### Pattern 15: Filler Phrases

Common substitutions:

- "In order to" → "To"
- "Due to the fact that" → "Because"
- "At this point in time" → "Now"
- "In the event that" → "If"
- "has the ability to" → "can"
- "It is important to note that" → delete, state the fact
- "It is worth noting that" → delete
- "a wide range of" → name the range or delete
- "in terms of" → delete or restructure
- "plays a role in" → name the action

### Pattern 16: Excessive Hedging

**Watch for:** stacked qualifiers — "could potentially possibly", "might arguably", "it may perhaps be the case that". **Weak alone.**

**Problem:** Qualifiers pile up until every claim sounds uncertain, usually to soften an earlier overstatement rather than to report real doubt. Keep one qualifier the evidence supports. Ordinary hedges ("perhaps", "tends to") are human habits, not tells; keep scope statements, legal notices, and genuine epistemic caution.

Before:
> It could potentially be argued that the index might possibly improve query performance in some cases.

After:
> The index should speed up lookups by customer ID; range scans are unaffected.

### Pattern 17: Rule of Three

**Watch for:** triads everywhere — "fast, reliable, and scalable"; three parallel examples; three short facts and a lesson. **Weak alone** — writers use deliberate triads for rhythm.

**Problem:** Ideas are forced into threes to sound complete whether or not the meaning has three parts. Check that each item adds a distinct idea; merge or cut the ones that don't. Keep a triad when the content genuinely has three parts.

Before:
> The new pipeline is faster, more reliable, and easier to maintain, delivering speed, stability, and simplicity.

After:
> The new pipeline runs in 4 minutes instead of 11, and its failures now surface in one log stream.

### Pattern 18: Repeated Sentence Openings

**Watch for:** several consecutive sentences opening with the same subject or word. **Weak alone** — writers repeat openings deliberately for rhythm ("She came. She saw. She conquered.").

**Problem:** Repetition is handled by rule instead of by ear. Merge sentences, change the subject, or lead with the action. Do not ban the repeated word; one remaining sentence may still start with it.

Before:
> The service reads the queue. The service batches the events. The service writes them to the warehouse.

After:
> The service reads the queue, batches the events, and writes them to the warehouse.

### Pattern 19: Passive Voice and Missing Subjects

**Watch for:** "No configuration needed.", "Results are preserved automatically.", "Mistakes were made." **Weak alone** — passive is standard in some registers (methods sections, incident reports).

**Problem:** The actor disappears. Name the actor when that adds clarity.

Before:
> The flag is read at startup and settings are applied automatically.

After:
> The daemon reads the flag at startup and applies the settings.

---

## Class D — Formatting by Rule

Individually weak; strong in clusters. A document showing three of these at once is likely generated.

### Pattern 20: Em Dash Overuse

**Watch for:** dashes as the universal connector — multiple per paragraph, spaced hyphens (` -- `) used as dashes. **Weak alone** — many strong writers use dashes deliberately.

**Problem:** A dash lets the writer skip deciding how two clauses relate. Replace with a period, comma, colon, or parentheses, or rewrite the sentence. If the writer's own sample uses dashes, match the sample's rate. Leave dashes inside code, commands, paths, and URLs alone.

Before:
> The deploy failed — the config was stale — and the rollback — which nobody had tested — failed too.

After:
> The deploy failed because the config was stale. The rollback failed too; nobody had tested it.

### Pattern 21: Boldface and Inline-Header Lists

**Watch for:** bold as decoration ("**OKRs**, **KPIs**"); bullet lists where every item is a **Bold Label:** followed by a sentence; the label restated in the sentence ("**Performance:** Performance improved").

**Problem:** Emphasis and structure applied mechanically. Remove decorative bold. Turn a labeled list into prose when the items are sentences in disguise; keep a list when items are genuinely parallel data.

Before:
> - **Speed:** Speed has been significantly improved.
> - **Security:** Security has been strengthened with encryption at rest.

After:
> This release cuts cold-start time to 300ms and adds encryption at rest.

### Pattern 22: Decorative Headings

**Watch for:** Title Case In Every Heading, emoji or arrows decorating headings and bullets ("🚀 Launch Phase:", "→ Key Insight:"), headings that only contain other headings.

**Problem:** Formatting as ornament. Use sentence case; delete emoji and arrows unless the venue's own style uses them.

Before:
> ## 🚀 Strategic Roadmap And Vision

After:
> ## Roadmap

### Pattern 23: Curly Quotation Marks

**Watch for:** curly quotes (“...”) and curly apostrophes (’) in plain-text or code-adjacent contexts, or mixed curly and straight in the same document. **Weak alone** — word processors and typographic pipelines insert them; published prose legitimately uses them; some models never emit them.

**Problem:** In Markdown, source code, and technical docs, straight quotes are the convention. Normalize to straight quotes there; leave typographically curly documents alone.

---

## Class E — Leftovers From the Chat and the Draft

Text that was written for the chat session or an earlier draft, not for the reader. Act on one sighting.

### Pattern 24: Chatbot Wrappers and Sycophancy

**Watch for:** "Great question!", "Certainly!", "I'd be happy to help", "Welcome to this guide", "I hope this helps!", "Feel free to reach out", "Let me know if you'd like...".

**Problem:** Conversation residue wrapping the actual content. Delete the wrapper, keep the content.

Before:
> Great question! Here's a comprehensive overview of the retry logic. I hope this helps!

After:
> The client retries failed requests three times with exponential backoff starting at 200ms.

### Pattern 25: Knowledge-Cutoff Disclaimers and Unsupported Guesses

**Watch for:** "While details are limited in available sources, it appears...", "As of my last update...", "it is likely that...", "presumably" bridging a gap in sources.

**Problem:** The model narrates its own uncertainty and then guesses. State what the source shows, or remove the sentence. Do not replace a disclaimer with an invented fact.

Before:
> While specific details about the migration are limited, it likely involved significant refactoring of the core modules.

After:
> The changelog for v4.0 lists the migration but gives no detail on scope.

### Pattern 26: Heading Echoed in the First Sentence

**Watch for:** a section whose first sentence restates its heading ("## Performance" followed by "Performance is a critical aspect of the system.").

**Problem:** The heading already did that work. Start the section with a fact.

Before:
> ## Error handling
> Error handling is an important part of any robust application.

After:
> ## Error handling
> All handlers return typed errors; the middleware maps them to HTTP status codes.

### Pattern 27: Writing About the Previous Version

**Watch for:** prose describing the edit instead of the subject: "This function was added to replace...", "This section has been updated to...", "The revised approach now...", "(previously X)" clutter.

**Problem:** Draft archaeology shipped to the reader. Describe what the thing is and does now. Edit history belongs in version control, not in the text.

Before:
> This module was refactored to improve clarity and now handles validation, which was previously done in the controller.

After:
> This module validates request payloads before they reach the controller.

### Pattern 28: Re-Explaining Shared Context

**Watch for:** a reply that opens by restating the question or the situation both parties already know; a review response that re-derives the whole diagnosis before answering; background paragraphs addressed to someone who wrote the background.

**Problem:** Every sentence-level tell can be clean and the text still reads as a generated memo, because it explains things the reader already has. In replies, comments, and follow-ups: answer first, add only what is new, and cut any restatement of shared context.

Before:
> Thanks for raising this. As you pointed out, the null check on line 42 can be bypassed when the payload is empty, which would cause the handler to dereference a missing field. To address this concern, I've added a guard clause.

After:
> Fixed — added a guard clause above line 42. Empty payloads now return 400.

### Pattern 29: Mechanical Chat Residue

**Watch for:** citation artifacts leaked from chat interfaces — `:contentReference[oaicite:0]{index=0}`, `turn0search0`, `[cite: 3]`, `[span_1](start_span)`; tracking parameters like `utm_source=chatgpt.com` in URLs; placeholder text ("[Insert name here]", "TODO: add example" in shipped prose); Markdown headings that skip levels; Markdown syntax in venues that don't render it.

**Problem:** These are mechanical fingerprints, not style. In file mode, strip citation artifacts and tracking parameters, fill or flag placeholders (never invent content for them), and fix heading levels. Highest-confidence signals in this document — but always verify a URL still works after removing parameters.

---

## False-Positive Guards

Do not flag these — the source lists them as ineffective or misleading indicators:

- **Perfect grammar.** Many people write cleanly.
- **Formal, academic, or "fancy" prose.** Only the specific words in the vocabulary list are elevated in model output; formality itself is not a tell.
- **Transition words in isolation.** "However" and "Furthermore" are conventional in essayistic and academic writing.
- **Mixed casual and formal registers.** Common in technical writers, multilingual writers, and multi-author documents.
- **"Bland" or "robotic" feel without a named pattern.** A vibe is not evidence; name the pattern or leave the text alone.
- **A single dash, triad, hedge, or curly quote.** Weak-alone patterns need company.
- **Deliberate repetition and rhetorical fragments in an author's own voice sample.** The sample wins.
- **Unsourced content.** Predates LLMs as a phenomenon; modern chatbots often do include citations.

One further guard: absence of every pattern above does not prove a human wrote the text, and their presence does not prove a machine did. These patterns justify editing prose on its own merits — they are not an authorship test.

## Retired Patterns

Two patterns from earlier versions of this file were removed when the source reclassified them. **False ranges** ("from the Big Bang to dark matter") no longer appears in the source at all. **Elegant variation / synonym cycling** was moved to the source's historical indicators — it was a repetition-penalty artifact of older models. Do not flag either as a primary signal; see `historical-patterns.md` in the humanize skill for details.
