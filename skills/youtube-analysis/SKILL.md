---
name: youtube-analysis
description: 'Extract YouTube transcripts and produce structured concept analysis with multi-level summaries, key concepts, takeaways. Uses youtube-transcript-api with yt-dlp fallback. Triggers on: "analyze youtube video", "youtube transcript", "summarize this video", "extract concepts from video", "video key points", or any youtube.com/youtu.be URL.'
metadata:
  version: 1.1.1
  category: visualization
  tags: [youtube, analysis, skill]
  difficulty: intermediate
---

# YouTube Analysis

Extract transcripts from YouTube videos and produce structured concept analysis — key ideas, arguments, technical terms, takeaways, and multi-level summaries — all without API keys or MCP servers.

## Reference Files

| File                              | Purpose                                                |
| --------------------------------- | ------------------------------------------------------ |
| `scripts/fetch_transcript.py`     | Core transcript + metadata fetcher (CLI + importable)  |
| `scripts/analyze_video.py`        | Orchestrator: fetch → structure → export scaffold      |
| `scripts/utils.py`                | URL parsing, timestamp formatting, transcript chunking |
| `references/analysis-patterns.md` | Prompt patterns for each video type                    |
| `assets/output-template.md`       | Markdown template for final output                     |

## Workflow

```text
User provides YouTube URL
        │
        ▼
┌─────────────────────┐
│  Step 0: Deps check │
└────────┬────────────┘
         ▼
┌─────────────────────┐
│  Step 1: Parse URL  │
└────────┬────────────┘
         ▼
┌─────────────────────┐     ┌──────────────┐
│  Step 2: Transcript │────▶│  yt-dlp      │
│  (youtube-t-api)    │fail │  (fallback)  │
└────────┬────────────┘     └──────┬───────┘
         │◀───────────────-────────┘
         ▼
┌─────────────────────┐
│  Step 3: Metadata   │
│  (yt-dlp --dump-json│
└────────┬────────────┘
         ▼
┌─────────────────────┐
│  Step 4: Claude     │
│  analyzes transcript│
└────────┬────────────┘
         ▼
┌─────────────────────┐
│  Step 5: Export MD  │
└─────────────────────┘
```

## Step 0: Ensure Dependencies

Before running any script, verify dependencies are installed:

```bash
uv pip install youtube-transcript-api yt-dlp -q
```

Or run scripts directly with `uv run`:

```bash
uv run --with youtube-transcript-api --no-project python scripts/fetch_transcript.py "URL"
```

Verify:

```bash
python -c "from youtube_transcript_api import YouTubeTranscriptApi; print('OK')"
yt-dlp --version
```

## Step 1: URL Parsing and Validation

Use `scripts/utils.py:parse_youtube_url()` to extract the video ID. Supported formats:

| Format         | Example                                            |
| -------------- | -------------------------------------------------- |
| Standard watch | `youtube.com/watch?v=dQw4w9WgXcQ`                  |
| Short URL      | `youtu.be/dQw4w9WgXcQ`                             |
| Shorts         | `youtube.com/shorts/dQw4w9WgXcQ`                   |
| Embed          | `youtube.com/embed/dQw4w9WgXcQ`                    |
| Live           | `youtube.com/live/dQw4w9WgXcQ`                     |
| With params    | `youtube.com/watch?v=dQw4w9WgXcQ&t=120&list=PLxxx` |
| Bare ID        | `dQw4w9WgXcQ`                                      |
| Mobile         | `m.youtube.com/watch?v=dQw4w9WgXcQ`                |
| Music          | `music.youtube.com/watch?v=dQw4w9WgXcQ`            |

If parsing fails, ask the user to provide the URL in a standard format.

## Step 2: Transcript Extraction

Run `fetch_transcript.py` to get the transcript:

```bash
cd <skill_dir>/scripts
python fetch_transcript.py "YOUTUBE_URL" --lang en
```

This outputs JSON to stdout. The script:

1. **Primary path**: Uses `youtube-transcript-api` to scrape captions directly (no API key)
2. **Fallback path**: If primary fails, uses `yt-dlp --write-sub --write-auto-sub` to extract subtitle files
3. **Language handling**: Tries requested language first, falls back to any available transcript

The returned JSON contains both individual timestamped segments and a joined `transcript_text` field.

**Or import as a module** (used by `analyze_video.py`):

```python
from fetch_transcript import fetch_video
data = fetch_video("https://youtube.com/watch?v=VIDEO_ID", lang="en")
```

## Step 3: Metadata Extraction

Metadata is fetched automatically by `fetch_transcript.py` via `yt-dlp --dump-json`:

- Title, channel name
- Duration (seconds)
- Upload date (YYYY-MM-DD)
- Description (first 500 chars in scaffold)
- View count
- Tags

No separate step needed — `fetch_video()` returns everything.

## Step 4: Concept Analysis

**This is where you (Claude) do the work.** The scripts provide raw data; you perform the analysis.

### Analysis Depth

Choose based on user request or video duration:

| Depth      | When to Use                                      | Sections to Fill                              |
| ---------- | ------------------------------------------------ | --------------------------------------------- |
| `quick`    | User wants fast overview, or video < 10 min      | TL;DR, Key Concepts, Takeaways                |
| `standard` | Default for most videos                          | All template sections                         |
| `deep`     | User wants thorough breakdown, or video > 30 min | All sections + timestamped section-by-section |

### Analysis Process

1. **Read the full transcript** from the JSON output
2. **Identify the video type** (or use user-provided hint). See `references/analysis-patterns.md` for type-specific guidance
3. **Extract key concepts**: Main ideas, arguments, claims — each as a bullet with brief explanation
4. **Identify technical terms**: Definitions as presented in the video
5. **Pull notable statements**: Paraphrase key quotes with approximate timestamps
6. **Synthesize takeaways**: Actionable items the viewer should consider
7. **Write the TL;DR**: One to three sentences capturing the core message
8. **Suggest related topics**: Based on concepts mentioned, what should the viewer explore next

### For Deep Analysis

Use `utils.chunk_transcript()` to break the transcript into 5-minute segments, then analyze each chunk with timestamps:

```python
from utils import chunk_transcript
chunks = chunk_transcript(data["transcript"], chunk_minutes=5)
for chunk in chunks:
    print(f"[{chunk['start_formatted']} - {chunk['end_formatted']}]")
    print(chunk["text"])
```

Or run the orchestrator with `--depth deep`:

```bash
python analyze_video.py "YOUTUBE_URL" --depth deep
```

### Video Type Patterns

| Type      | Key Extraction Focus                              | See                               |
| --------- | ------------------------------------------------- | --------------------------------- |
| Lecture   | Thesis, arguments, citations, definitions         | `references/analysis-patterns.md` |
| Tutorial  | Steps, tools, prerequisites, gotchas              | `references/analysis-patterns.md` |
| Interview | Perspectives, disagreements, attributed positions | `references/analysis-patterns.md` |
| Podcast   | Topic threads, opinions, recommendations          | `references/analysis-patterns.md` |
| Tech Talk | Architecture, trade-offs, benchmarks, lessons     | `references/analysis-patterns.md` |
| Panel     | Consensus vs. disagreement, per-speaker views     | `references/analysis-patterns.md` |

Read `references/analysis-patterns.md` for detailed extraction guidance per type.

## Step 5: Export to Markdown

The orchestrator generates a scaffold:

```bash
cd <skill_dir>/scripts
python analyze_video.py "YOUTUBE_URL" --output ./analysis.md --depth standard --type auto
```

Flags:

- `--output PATH`: Where to write (default: `./{sanitized_title}.md`)
- `--depth quick|standard|deep`: Analysis depth
- `--type auto|lecture|tutorial|interview|podcast|tech-talk|panel`: Video type hint
- `--lang CODE`: Transcript language (default: `en`)
- `--json`: Output raw JSON instead of Markdown scaffold

The scaffold contains populated metadata and `[TO BE ANALYZED]` placeholders. Claude replaces these with actual analysis.

**Preferred workflow**: Run `fetch_transcript.py` to get JSON, analyze in context, then produce the final Markdown directly using `assets/output-template.md` as the structure guide. The orchestrator is useful for batch processing or when the user wants a file written.

## Error Handling

| Error                | Exit Code | Cause                                  | Resolution                                       |
| -------------------- | --------- | -------------------------------------- | ------------------------------------------------ |
| URL parse failure    | 1         | Invalid or unsupported URL format      | Ask user for standard YouTube URL                |
| No transcript        | 2         | Video has no captions (manual or auto) | Inform user; suggest a different video           |
| Video unavailable    | 1         | Private, deleted, or geo-blocked       | Inform user of the restriction                   |
| Age-restricted       | 1         | Requires authentication                | Inform user; yt-dlp may work with cookies        |
| Metadata fetch fail  | 0         | yt-dlp network issue                   | Transcript still works; metadata shows "Unknown" |
| Language unavailable | 0         | Requested lang not available           | Auto-falls back to available language            |
| yt-dlp not installed | 1         | Missing dependency                     | Run Step 0 dependency installation               |

## Limitations

- **No visual analysis**: Transcript-only; slides, diagrams, code on screen, and demos are not captured. Note this in output when relevant.
- **Auto-caption quality**: Auto-generated captions may contain errors, especially for technical terms, proper nouns, and non-English accents.
- **Music videos**: Lyrics may not be available as captions. Music-only content produces poor results.
- **Live streams**: Ongoing live streams may have incomplete or unavailable transcripts.
- **Rate limiting**: Excessive requests to YouTube may trigger temporary blocks. Space requests if processing multiple videos.
- **Language coverage**: Best results for English. Other languages depend on caption availability and quality.
- **Speaker attribution**: Transcripts rarely identify individual speakers. Claude infers from context where possible.
