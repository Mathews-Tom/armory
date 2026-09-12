# Historical Patterns — Retired From Detection

Patterns that earlier versions of this skill flagged as current AI tells, since retired or demoted by the source ([Wikipedia:Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing), revision of 2026-09-11). They may still indicate *older* AI text; they are unreliable for current model output and common in ordinary human writing.

Rules for this file:

- **Never flag a historical pattern as primary evidence.** At most, mention it as corroboration when several current patterns are already present in the same passage.
- **Never "fix" a deliberate human use** of these constructions.
- When a rewrite touches one anyway (because the sentence is being rewritten for a current pattern), that is fine — just do not report it as a detected AI tell.

---

## False Ranges

**Was:** "From X to Y" constructions where X and Y sit on no meaningful scale ("from the Big Bang to the cosmic web", "whether you're a beginner or a seasoned expert").

**Status:** Removed from the source entirely — reclassified as an ordinary human rhetorical habit, not an AI signature. The *sales-brochure* variant ("whether you're just starting out or a seasoned pro") is still worth editing, but as promotional language, not as a range construction.

## Elegant Variation (Synonym Cycling)

**Was:** Cycling through synonyms to avoid repeating a word ("the protagonist... the main character... the central figure... the hero").

**Status:** Moved to the source's historical indicators. It was an artifact of repetition penalties in older models; current models do not reliably show it, and human writers have done it since long before LLMs (it has its own non-AI style essay on Wikipedia). The related *editing* advice still stands on its own merits: do not vary domain-specific terms ("API" stays "API"), and reduce repetition by restructuring, not by synonym substitution.

## Didactic Disclaimers

**Was:** Boilerplate cautions appended to content ("It's important to consult a professional before...", "Remember, everyone's situation is different.").

**Status:** Listed by the source as characteristic of 2022-2024 chat models and no longer typical. Genuine legal/safety notices are content, not tells — keep them.

## Transition-Word Frequency as a Primary Signal

**Was:** Counting formal connectives ("However", "Furthermore", "Additionally") against a per-1,000-words threshold.

**Status:** The source explicitly lists transition words in isolation as an *ineffective* indicator — conventional in essayistic and academic prose. Only the specific vocabulary-list words remain signals, and only in clusters. Never report a transition count as a finding.

## Statistical "Humanization" Targets

**Was:** Numeric targets for sentence-length variance, type-token ratio, clause density, and similar detector-facing metrics, applied during rewriting.

**Status:** Removed from this skill. The targets were uncited, and engineering text toward detector metrics is a different task from editing — one this skill deliberately does not perform. Sentence-length variety survives as ordinary style advice in `transformation-rules.md`, grounded in readability rather than in detector evasion.
