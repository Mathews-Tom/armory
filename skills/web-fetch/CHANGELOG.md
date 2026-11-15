# Changelog — Web Fetch

## 1.2.0

- Add a Reddit-only deterministic helper using the existing `agent-browser` CLI, with no Reddit API credentials or new Python dependencies. Capture post text and comment/reply records, expand supported controls and same-post continuations, and save JSON plus a readable hierarchical Markdown view.
- Preserve stable comment IDs and parents, deduplicate repeated records, retain captured post text across sparse snapshots, recover newly revealed bodies with their expansion state, and merge observed comment counts independently so missing-data reports stay accurate. Report caps, stalled expansion, access gates, and browser failures without claiming API-level completeness.
- Route Reddit post/thread requests through the helper while retaining the existing curl/WebFetch workflow for ordinary URLs. Add access-policy guidance, untrusted-content rules, and regression/evaluation cases.
