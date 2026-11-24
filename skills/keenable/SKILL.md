---
name: keenable
description: 'Keyless web search and page fetch via Keenable when no vendor API key is available. Returns title, URL and snippet for current information. Triggers on: "search without an API key", "keyless web search", "keenable". NOT for generic "search the web" (use tavily when TAVILY_API_KEY is set); NOT for known local or private URLs (use web-fetch).'
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

## Package boundary

| Neighbour   | Keenable handles                                      | Neighbour handles                                      |
| ----------- | ----------------------------------------------------- | ------------------------------------------------------ |
| `tavily`    | Keyless or Keenable-keyed search when no Tavily key   | Generic web search when `TAVILY_API_KEY` is configured |
| `web-fetch` | Page text via Keenable after this skill is already active | Direct fetch of a known URL, localhost, intranet, signed URLs |

Keenable's description triggers only on explicit no-key or Keenable-named intent so it does not compete with `tavily` for the same phrases.

## When to Use Keenable vs Other Tools

| Situation                                    | Tool            | Reason                                              |
| -------------------------------------------- | --------------- | --------------------------------------------------- |
| Web search without any vendor API key        | `search.mjs`    | Public search endpoint, no Tavily or other signup   |
| User asks for Keenable or keyless web search | `search.mjs`    | Matches this skill's invocation contract            |
| Have a URL, skill already active             | `fetch.mjs`     | Public fetch returns clean markdown via Keenable    |
| `TAVILY_API_KEY` already set                 | `tavily` skill  | Tavily owns generic web-search routing              |
| Known URL, local or private host             | `web-fetch`     | Fetches without sending the URL to Keenable         |

## Data handling

- Search queries and URLs passed to `fetch.mjs` are sent to Keenable (`api.keenable.ai`); Keenable's servers retrieve page content.
- Do not pass intranet, `localhost`, or signed or credential-bearing URLs to `fetch.mjs`; use `web-fetch` for those.
- Both scripts send `X-Keenable-Title: armory` to identify the caller.

## Scripts

Both scripts exist at `scripts/`. No key is required. `KEENABLE_API_KEY` is optional.

- `scripts/search.mjs` — query-based web search
- `scripts/fetch.mjs` — fetch a URL as clean markdown

## Search

```bash
node {baseDir}/scripts/search.mjs "query"
node {baseDir}/scripts/search.mjs "query" -n 10
node {baseDir}/scripts/search.mjs "query" --days 7
node {baseDir}/scripts/search.mjs "query" --keyless
```

When the user explicitly asks for a keyless search (or a search without an API
key), pass `--keyless`. It always uses the public endpoint and does not send
`KEENABLE_API_KEY`, even if one is set. Without the flag, a configured key is used.

### Search Options

| Option       | Default | Description                                              |
| ------------ | ------- | -------------------------------------------------------- |
| `-n <count>` | 5       | Number of results to return (max: 50).                   |
| `--days <n>` | —       | Limit results to pages published in the last n days.     |
| `--keyless`  | off     | Use the public endpoint and ignore `KEENABLE_API_KEY`.   |

## Fetch Content from URL

```bash
node {baseDir}/scripts/fetch.mjs "https://example.com/article"
```

Use when this skill is already active, you have a public URL, and need the page
content as markdown. Do not use for triggers; direct URL requests route to
`web-fetch` instead.

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
