# Changelog — Web Fetch

## 1.4.0

- Make `browser-json` the default capture backend in `reddit_thread.py` (`--backend browser-json`, with `--backend dom` retained as fallback): navigates directly to Reddit's `.json` thread listing in the authorized browser session without SPA DOM rendering or scrolling, preserves `[deleted]`/`[removed]` parent markers so child replies stay linked, and follows same-post `more` continuations.
- Add single-tab multi-URL batch capture (`reddit_thread.py URL1 URL2 ... --output DIR`) that reuses one tab across all posts, writes per-post subdirectories plus `batch.json`, and fails fast automatically on environment-level Reddit blocks.
- Document an isolated persistent `--profile` session as the primary setup so tabs stay out of the user's daily Chrome window.

## 1.3.0

- Classify Reddit access/verification gates (`network_security`, `human_verification`, `rate_limit`, `login_required`, `private_or_banned`) separately from unavailable/not-found posts (`not_found`), preserving `block_reason`, `visited_pages`, and a safely quoted `gate_detail` excerpt in `thread.json` and `thread.md`.
- Support `REDDIT_BROWSER_SESSION` as a fallback for `--session` (preserving tab-only cleanup for borrowed sessions) and surface upfront guidance when standalone headless Chrome hits a Reddit gate.
- Update `SKILL.md`, `references/reddit.md`, and evals with upfront browser-session selection guidance, concrete `agent-browser` setup examples (`--auto-connect`, `--cdp 9222`, `--headed`), batch fail-fast rules on environment-level blocks, and accurate Python 3.11+ runtime requirements.

## 1.2.0

- Add a Reddit-only deterministic helper using the existing `agent-browser` CLI, with no Reddit API credentials or new Python dependencies. Capture post text and comment/reply records, expand supported controls and same-post continuations, and save JSON plus a readable hierarchical Markdown view.
- Preserve stable comment IDs and parents, deduplicate repeated records, retain captured post text across sparse snapshots, recover newly revealed bodies with their expansion state, and merge observed comment counts independently so missing-data reports stay accurate. Report caps, stalled expansion, access gates, and browser failures without claiming API-level completeness.
- Route Reddit post/thread requests through the helper while retaining the existing curl/WebFetch workflow for ordinary URLs. Add access-policy guidance, untrusted-content rules, and regression/evaluation cases.
