# Engineering Prose — Before/After Examples

Engineering artifacts — PR descriptions, commit messages, changelogs, review replies — are the highest-volume AI-drafted prose in most repositories. The register is technical: neutral, specific, no personality required. The tells cluster differently here than in blogs — staging, bold-label lists, and draft residue dominate.

## Example 1: Pull Request Description

**Before (AI-generated):**
> ## 🚀 Overview
>
> This PR doesn't just fix the race condition — it fundamentally rethinks how the worker pool manages its lifecycle. Let's dive into the key changes:
>
> - **Robustness:** Enhanced the shutdown sequence to ensure graceful termination.
> - **Performance:** Optimized the polling loop, showcasing significant improvements.
> - **Maintainability:** Refactored the codebase to foster better separation of concerns.
>
> These changes represent a pivotal step forward in the reliability of our infrastructure. Comprehensive tests have been added to ensure correctness.

**After (humanized):**
> Fixes the shutdown race in the worker pool: workers now drain their queue before the pool closes the results channel, so in-flight jobs are no longer dropped (#412).
>
> Also replaces the 100ms polling loop with a condition variable, which removes ~4% idle CPU on quiet workers.
>
> Tests cover the drain path and a shutdown-under-load case that reproduced the original panic.

**Patterns removed:** negative parallelism ("doesn't just fix — it fundamentally rethinks"), staged run-up ("Let's dive into"), inline bold-header list with restated labels, decorative heading emoji, significance inflation ("pivotal step forward"), AI vocabulary ("robust", "enhanced", "showcasing", "foster"), promotional vagueness replaced with the measurable claims underneath.

## Example 2: Commit Message Body

**Before (AI-generated):**
> This commit was created to update the retry logic. The previous implementation has been refactored to improve reliability. The new approach now leverages exponential backoff, ensuring robust handling of transient failures and enhancing the overall resilience of the system.

**After (humanized):**
> Retry transient upstream failures with exponential backoff (200ms base, 3 attempts, full jitter). Fixed-interval retries were synchronizing across replicas and amplifying outages into thundering herds.

**Patterns removed:** writing about the previous version ("This commit was created to...", "has been refactored"), passive voice with missing subjects, AI vocabulary ("leverages", "ensuring robust", "enhancing"), superficial -ing riders replaced by the actual reason for the change.

## Example 3: Changelog Entry

**Before (AI-generated):**
> ### ✨ What's New
>
> We're thrilled to announce a comprehensive update to the export module! This release marks a significant milestone in our journey toward seamless data interoperability. Users can now enjoy enhanced CSV handling, ensuring smoother workflows than ever before.

**After (humanized):**
> ### Added
>
> - CSV export now streams rows instead of buffering the full file; exports over 1M rows no longer hit the 2GB memory limit.
> - Delimiter and quoting are configurable per export (`delimiter`, `quote_style`).

**Patterns removed:** chatbot wrapper enthusiasm ("We're thrilled to announce"), significance inflation ("significant milestone in our journey"), promotional language ("seamless", "smoother than ever"), heading emoji, vague benefit claims replaced with the concrete behavior change.

## Example 4: Review Reply

**Before (AI-generated):**
> Thank you for this insightful feedback! You raise an excellent point about the potential null dereference. As you correctly noted, when the payload is empty, the parser returns None, and the subsequent access on line 87 would fail. This is indeed a critical issue that could impact production stability. To address this concern, I have added a guard clause that validates the payload before parsing. I hope this resolves your concern — please don't hesitate to reach out with any further questions!

**After (humanized):**
> Fixed in 3f2a9c1 — added a guard before the parse, empty payloads now return 400. Good catch.

**Patterns removed:** sycophantic wrapper ("Thank you for this insightful feedback!", "excellent point"), re-explaining shared context (restating the reviewer's own diagnosis back to them), significance inflation ("critical issue that could impact production stability"), chatbot closer ("please don't hesitate to reach out"). The reply answers first and adds only what is new: the fix, its location, the observable behavior.
