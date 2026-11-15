# Changelog — Web Fetch

## 1.2.0

- Add a Reddit-only deterministic helper using the existing `agent-browser` CLI, with no Reddit API credentials or new Python dependencies. Capture post text and comment/reply records, expand supported controls and same-post continuations, and save JSON plus a readable hierarchical Markdown view.
- Preserve stable comment IDs and parents, deduplicate repeated records, retain captured post text when continuation pages omit their body, and report caps, stalled expansion, missing data, access gates, and browser failures without claiming API-level completeness.
- Route Reddit post/thread requests through the helper while retaining the existing curl/WebFetch workflow for ordinary URLs. Add access-policy guidance, untrusted-content rules, and regression/evaluation cases.
