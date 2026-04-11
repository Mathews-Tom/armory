---
name: youtube-search
description: 'Search YouTube by keyword and return structured video metadata (title, URL, channel, views, duration, date) via yt-dlp. No API keys. Triggers on: "search youtube", "find youtube videos", "top youtube videos on", "trending videos on", "youtube results for", "yt search", "/yt-search".'
metadata:
  version: 1.1.1
  category: research
  tags: [youtube, search, skill]
  difficulty: beginner
---

# YouTube Search

Search YouTube by keyword and return structured video metadata — title, URL,
channel, views, duration, upload date. Uses `yt-dlp` for scraping with no API
keys or OAuth required.

## Prerequisites

```bash
uv tool install yt-dlp
```

Verify:

```bash
yt-dlp --version
```

## Usage

### Basic Search

```bash
yt-dlp "ytsearch10:claude code skills" --dump-json --flat-playlist --no-warnings 2>/dev/null \
  | jq -r '[.title, .url, .channel, .view_count, .duration_string, .upload_date] | @tsv'
```

- `ytsearch10:` — search YouTube, return 10 results (adjust number as needed)
- `--dump-json` — output metadata as JSON
- `--flat-playlist` — don't download, just list
- `--no-warnings` — suppress non-error output

### Structured JSON Output

```bash
yt-dlp "ytsearch5:claude code mcp servers" \
  --dump-json --flat-playlist --no-warnings 2>/dev/null \
  | jq '{
    title: .title,
    url: .url,
    channel: .channel,
    views: .view_count,
    duration: .duration_string,
    upload_date: .upload_date,
    description: (.description // "" | .[0:200])
  }'
```

### Search with Sorting

yt-dlp does not support server-side sort. To sort by views or date, capture all
results and sort client-side:

```bash
# Sort by view count (descending)
yt-dlp "ytsearch20:AI agents 2026" \
  --dump-json --flat-playlist --no-warnings 2>/dev/null \
  | jq -s 'sort_by(-.view_count) | .[:10][] | {title, url, channel, views: .view_count}'
```

```bash
# Sort by upload date (newest first)
yt-dlp "ytsearch20:claude code tutorial" \
  --dump-json --flat-playlist --no-warnings 2>/dev/null \
  | jq -s 'sort_by(-.upload_date) | .[:10][] | {title, url, channel, upload_date}'
```

### Search Result Count

The number after `ytsearch` controls how many results to fetch:

| Pattern            | Results                                |
| ------------------ | -------------------------------------- |
| `ytsearch5:query`  | 5 results                              |
| `ytsearch10:query` | 10 results (default recommendation)    |
| `ytsearch20:query` | 20 results                             |
| `ytsearch50:query` | 50 results (slow, may hit rate limits) |

**Recommendation:** Fetch 15-20 results, then filter/sort client-side to the top N the user wants. This provides enough data for meaningful sorting without being excessive.

## Workflow

```text
User provides search query
        |
        v
+---------------------+
|  Step 0: Deps check |
+----------+----------+
           v
+---------------------+
|  Step 1: Search     |
|  (yt-dlp ytsearch)  |
+----------+----------+
           v
+---------------------+
|  Step 2: Parse JSON |
|  (jq formatting)    |
+----------+----------+
           v
+---------------------+
|  Step 3: Present    |
|  results to user    |
+---------------------+
```

### Step 1: Execute Search

```bash
yt-dlp "ytsearch${COUNT}:${QUERY}" \
  --dump-json --flat-playlist --no-warnings 2>/dev/null
```

### Step 2: Parse and Format

Extract relevant fields with `jq`. The full metadata object from yt-dlp contains
many fields; the useful subset for search results:

| Field              | Description                                |
| ------------------ | ------------------------------------------ |
| `.title`           | Video title                                |
| `.url`             | Full YouTube URL                           |
| `.channel`         | Channel name                               |
| `.view_count`      | Total views (integer)                      |
| `.duration_string` | Duration as `H:MM:SS` or `MM:SS`           |
| `.upload_date`     | Upload date as `YYYYMMDD`                  |
| `.description`     | Video description (can be long — truncate) |
| `.like_count`      | Likes (may be null)                        |
| `.comment_count`   | Comments (may be null)                     |

### Step 3: Present Results

Format as a markdown table for the user:

```bash
yt-dlp "ytsearch10:${QUERY}" \
  --dump-json --flat-playlist --no-warnings 2>/dev/null \
  | jq -s 'sort_by(-.view_count) | .[] | "| \(.title[:60]) | \(.channel) | \(.view_count) | \(.duration_string) | \(.upload_date) |"' -r
```

Prefix with a header row:

```text
| Title | Channel | Views | Duration | Date |
|-------|---------|-------|----------|------|
```

## Advanced Patterns

### Filter by Duration

```bash
# Only videos longer than 10 minutes (600 seconds)
yt-dlp "ytsearch20:deep dive AI agents" \
  --dump-json --flat-playlist --no-warnings 2>/dev/null \
  | jq -s '[.[] | select(.duration >= 600)] | sort_by(-.view_count) | .[:10][]'
```

### Filter by Recency

```bash
# Only videos from the last 30 days
CUTOFF=$(date -v-30d +%Y%m%d 2>/dev/null || date -d "30 days ago" +%Y%m%d)
yt-dlp "ytsearch20:claude code" \
  --dump-json --flat-playlist --no-warnings 2>/dev/null \
  | jq -s --arg cutoff "$CUTOFF" '[.[] | select(.upload_date >= $cutoff)] | sort_by(-.view_count) | .[]'
```

### Channel-Specific Search

```bash
# Search within a specific channel
yt-dlp "ytsearch10:skills site:youtube.com/c/ChannelName" \
  --dump-json --flat-playlist --no-warnings 2>/dev/null
```

Or use the channel URL directly:

```bash
yt-dlp "https://www.youtube.com/@ChannelName/search?query=skills" \
  --dump-json --flat-playlist --no-warnings 2>/dev/null
```

### Extract URLs Only (for Piping)

```bash
# Get just URLs for feeding into other tools (youtube-analysis, notebooklm)
yt-dlp "ytsearch10:claude code MCP" \
  --dump-json --flat-playlist --no-warnings 2>/dev/null \
  | jq -r '.url'
```

## Composability

This skill produces URLs and metadata that feed into other skills:

- **youtube-analysis**: Pass URLs to extract transcripts and perform concept analysis
- **notebooklm**: Pass URLs as sources via `notebooklm source add "URL"`

Example pipeline (manual steps, not automated):

1. `/yt-search` — discover 10 relevant videos
2. User reviews and selects videos
3. Feed selected URLs into `notebooklm source add` or `youtube-analysis`

## Error Handling

| Error                       | Cause                              | Resolution                               |
| --------------------------- | ---------------------------------- | ---------------------------------------- |
| No results                  | Query too specific or misspelled   | Broaden the search terms                 |
| Empty JSON                  | yt-dlp rate limited by YouTube     | Wait a few minutes, retry                |
| `yt-dlp: command not found` | Not installed                      | `uv tool install yt-dlp`                 |
| Partial results             | Some videos geo-blocked or private | Normal behavior; results are best-effort |
| Timeout                     | Network or YouTube slowness        | Reduce result count or retry             |

## Limitations

- **No server-side sorting**: YouTube search results come in relevance order. Sorting by views or date requires fetching extra results and sorting client-side.
- **Rate limiting**: Aggressive scraping (50+ results, rapid repeated searches) may trigger YouTube rate limits. Space requests apart.
- **Metadata completeness**: Some fields (`.like_count`, `.comment_count`) may be null for certain videos. Always handle nulls in jq filters.
- **No authentication**: Uses public YouTube data only. Age-restricted or private videos are excluded from results.
- **Search relevance**: YouTube's search algorithm determines initial ordering. Results may not match exact expectations.
