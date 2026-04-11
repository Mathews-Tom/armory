---
name: tavily
description: 'AI-optimized web search via Tavily API when no URL is provided. Returns clean AI-ready snippets for current info and news. Triggers on: "search the web", "look up online", "find recent information", "web search". NOT for known URLs, use web-fetch.'
metadata:
  version: 1.1.1
  category: research
  tags: [web-search, research, real-time, ai-optimized]
  difficulty: beginner
---

# Tavily Search

Web search and URL content extraction powered by Tavily API. Returns clean, structured results
optimized for AI consumption — no HTML noise, no cookie banners, no pagination.

## When to Use Tavily vs Other Tools

| Situation                            | Tool                               | Reason                                   |
| ------------------------------------ | ---------------------------------- | ---------------------------------------- |
| Need current information on a topic  | `search.mjs`                       | Tavily aggregates and ranks live results |
| Need news from the last N days       | `search.mjs --topic news --days N` | News mode filters recency                |
| Have a specific URL, need full text  | `extract.mjs`                      | Extracts clean article content from URL  |
| Need documentation for a library     | `search.mjs --deep`                | Deep mode covers docs sites thoroughly   |
| Need a static resource already known | direct fetch or read               | Skip Tavily if no live lookup needed     |
| Need multiple competing perspectives | `search.mjs -n 10`                 | Increase result count for breadth        |

## Scripts

Both scripts exist at `scripts/` and require `TAVILY_API_KEY` in the environment.

- `scripts/search.mjs` — query-based web search
- `scripts/extract.mjs` — full content extraction from a URL

## Search

```bash
node {baseDir}/scripts/search.mjs "query"
node {baseDir}/scripts/search.mjs "query" -n 10
node {baseDir}/scripts/search.mjs "query" --deep
node {baseDir}/scripts/search.mjs "query" --topic news
node {baseDir}/scripts/search.mjs "query" --topic news --days 3
```

### Search Options

| Option            | Default   | Description                                                                                                                                                |
| ----------------- | --------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `-n <count>`      | 5         | Number of results to return (max: 20). Increase for broader coverage.                                                                                      |
| `--deep`          | off       | Advanced search mode — slower but more comprehensive. Use for complex research questions, technical deep-dives, or when standard results are insufficient. |
| `--topic <topic>` | `general` | `general` for standard search; `news` for current events filtered by recency.                                                                              |
| `--days <n>`      | —         | Only valid with `--topic news`. Limits results to articles published in the last n days.                                                                   |

## Extract Content from URL

```bash
node {baseDir}/scripts/extract.mjs "https://example.com/article"
```

Use when you already have a URL and need the full page content — Tavily strips navigation,
ads, and boilerplate, returning structured article text.

## Output Format

Search results return a JSON array. Each result contains:

```json
[
  {
    "title": "Article or page title",
    "url": "https://source.com/path",
    "content": "Clean text snippet (AI-optimized excerpt)",
    "score": 0.92
  }
]
```

`score` is Tavily's relevance ranking (0–1). Higher is more relevant. When parsing results,
use `content` for summarization and `url` for attribution. Do not treat `content` as the full
article — use `extract.mjs` on the URL if complete text is needed.

Extract output returns a single object:

```json
{
  "url": "https://source.com/path",
  "raw_content": "Full extracted page text..."
}
```

## Error Handling

| Error                         | Cause                        | Resolution                                                           |
| ----------------------------- | ---------------------------- | -------------------------------------------------------------------- |
| `TAVILY_API_KEY not set`      | Environment variable missing | Set `TAVILY_API_KEY` before running. Get a key at https://tavily.com |
| `401 Unauthorized`            | Invalid API key              | Verify the key value; regenerate at Tavily dashboard if needed       |
| `429 Too Many Requests`       | Rate limit hit               | Reduce request frequency; free tier allows 1000 API credits/month    |
| Empty results array `[]`      | No matches found             | Broaden or rephrase the query; try `--deep` for niche topics         |
| `ETIMEDOUT` / timeout         | Network or API latency       | Retry once; `--deep` searches take longer (up to 30s)                |
| Extract returns empty content | Page blocks scrapers         | Use a different source or fall back to a manual fetch approach       |

## Limitations

- **Rate limits**: Free tier is 1000 API credits/month. Each search costs 1 credit; `--deep` costs more.
- **Content freshness**: Results reflect Tavily's index; very recent content (last few hours) may not appear in `general` mode. Use `--topic news` for recency-sensitive queries.
- **Result quality**: Tavily optimizes for AI-readable content but cannot guarantee factual accuracy. Verify critical claims from primary sources.
- **Paywalled content**: Articles behind paywalls return only the publicly accessible excerpt.
- **Non-text content**: PDFs, images, and media pages extract poorly or not at all.
- **Language**: Best results for English queries. Other languages are supported but result quality varies.
