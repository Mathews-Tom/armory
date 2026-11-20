---
name: keenable
description: 'Keyless web search and page fetch via Keenable when no vendor key is required. Returns title, URL and snippet for current information. Triggers on: "search the web", "look up online", "find recent information", "web search", "fetch this page". NOT a replacement for the Tavily skill; use that when a Tavily key is already configured.'
metadata:
  version: 1.0.0
  category: research
  tags: [web-search, research, real-time, keyless]
  difficulty: beginner
---

# Keenable Search

Web search and page fetch over the Keenable index. Works without an API key on
the public endpoints; set `KEENABLE_API_KEY` for higher limits.

This is an opt-in skill. It does not replace Tavily or `web-fetch`.

## When to Use Keenable vs Other Tools

| Situation                           | Tool            | Reason                                              |
| ----------------------------------- | --------------- | --------------------------------------------------- |
| Need current information, no API key | `search.mjs`   | Public search endpoint, no vendor signup            |
| Have a specific URL, need page text | `fetch.mjs`     | Public fetch returns clean markdown                 |
| Already using Tavily with a key     | `tavily` skill  | Keep using Tavily when that key is already set      |
| Need a static resource already known | direct fetch   | Skip a search if no live lookup is needed           |

## Scripts

Both scripts exist at `scripts/`. No key is required. `KEENABLE_API_KEY` is optional.

- `scripts/search.mjs` — query-based web search
- `scripts/fetch.mjs` — fetch a URL as clean markdown

## Search

```bash
node {baseDir}/scripts/search.mjs "query"
node {baseDir}/scripts/search.mjs "query" -n 10
node {baseDir}/scripts/search.mjs "query" --days 7
```

### Search Options

| Option       | Default | Description                                              |
| ------------ | ------- | -------------------------------------------------------- |
| `-n <count>` | 5       | Number of results to return (max: 50).                   |
| `--days <n>` | —       | Limit results to pages published in the last n days.     |

## Fetch Content from URL

```bash
node {baseDir}/scripts/fetch.mjs "https://example.com/article"
```

Use when you already have a URL and need the page content as markdown.

## Output Format

Search prints a markdown source list (title, URL, snippet). Fetch prints the
page title, source URL, and markdown body.

## Error Handling

| Error                    | Cause                         | Resolution                                                                 |
| ------------------------ | ----------------------------- | -------------------------------------------------------------------------- |
| `401 Unauthorized`       | Invalid API key               | Check `KEENABLE_API_KEY`; keyless calls should not send a key              |
| `429 Too Many Requests`  | Rate limit hit                | Wait and retry; public limits are documented at https://docs.keenable.ai/rate-limits |
| Empty sources list       | No matches found              | Broaden or rephrase the query                                              |
| Fetch returns no content | Page could not be extracted   | Try a different URL                                                        |

## Limitations

- **Rate limits**: The public endpoint is rate-limited per IP (see the docs above). A key raises the cap.
- **Result quality**: Verify critical claims from primary sources.
- This skill is optional. It does not change Armory's default research tools.
