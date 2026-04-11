---
name: notebooklm
description: 'Full NotebookLM API via notebooklm-py CLI: create notebooks, add sources, generate podcasts, videos, infographics, slides, quizzes, flashcards, mind maps. Triggers on: "notebooklm", "create a podcast", "audio overview", "generate flashcards", "generate infographic", "/notebooklm".'
metadata:
  version: 1.1.1
  category: research
  tags: [notebooklm, podcast, flashcards, source-analysis]
  difficulty: intermediate
---

# NotebookLM Automation

Complete programmatic access to Google NotebookLM — including capabilities not
exposed in the web UI. Create notebooks, add sources (URLs, YouTube, PDFs,
audio, video, images), chat with content, generate all artifact types, and
download results in multiple formats.

## Prerequisites

### Installation

```bash
uv tool install notebooklm-py
```

### Authentication (one-time)

```bash
notebooklm login          # Opens browser for Google OAuth
notebooklm list           # Verify authentication works
```

If commands fail with auth errors, re-run `notebooklm login`.

### Verify Setup

```bash
notebooklm --version
notebooklm status         # Shows "Authenticated as: email@..."
notebooklm list --json    # Should return valid JSON
```

### CI/CD and Parallel Agents

| Variable               | Purpose                                            |
| ---------------------- | -------------------------------------------------- |
| `NOTEBOOKLM_HOME`      | Custom config directory (default: `~/.notebooklm`) |
| `NOTEBOOKLM_AUTH_JSON` | Inline auth JSON — no file writes needed           |

**Parallel agents:** The CLI stores notebook context in `~/.notebooklm/context.json`. Multiple concurrent agents using `notebooklm use` overwrite each other's context. Use explicit `-n <notebook_id>` or `--notebook <notebook_id>` flags instead, or set unique `NOTEBOOKLM_HOME` per agent.

## Quick Reference

| Task                     | Command                                                        |
| ------------------------ | -------------------------------------------------------------- |
| Authenticate             | `notebooklm login`                                             |
| Diagnose auth            | `notebooklm auth check --test`                                 |
| List notebooks           | `notebooklm list`                                              |
| Create notebook          | `notebooklm create "Title"`                                    |
| Set context              | `notebooklm use <notebook_id>`                                 |
| Show context             | `notebooklm status`                                            |
| Add URL source           | `notebooklm source add "https://..."`                          |
| Add file                 | `notebooklm source add ./file.pdf`                             |
| Add YouTube              | `notebooklm source add "https://youtube.com/..."`              |
| List sources             | `notebooklm source list`                                       |
| Wait for source          | `notebooklm source wait <source_id>`                           |
| Web research (fast)      | `notebooklm source add-research "query"`                       |
| Web research (deep)      | `notebooklm source add-research "query" --mode deep --no-wait` |
| Check research status    | `notebooklm research status`                                   |
| Wait for research        | `notebooklm research wait --import-all`                        |
| Chat                     | `notebooklm ask "question"`                                    |
| Chat (new conversation)  | `notebooklm ask "question" --new`                              |
| Chat (specific sources)  | `notebooklm ask "question" -s src_id1 -s src_id2`              |
| Chat (with references)   | `notebooklm ask "question" --json`                             |
| Get source fulltext      | `notebooklm source fulltext <source_id>`                       |
| Get source guide         | `notebooklm source guide <source_id>`                          |
| Generate podcast         | `notebooklm generate audio "instructions"`                     |
| Generate video           | `notebooklm generate video "instructions"`                     |
| Generate quiz            | `notebooklm generate quiz`                                     |
| Generate infographic     | `notebooklm generate infographic`                              |
| Generate slide deck      | `notebooklm generate slide-deck`                               |
| Generate report          | `notebooklm generate report`                                   |
| Generate mind map        | `notebooklm generate mind-map`                                 |
| Generate data table      | `notebooklm generate data-table "description"`                 |
| Generate flashcards      | `notebooklm generate flashcards`                               |
| Check artifact status    | `notebooklm artifact list`                                     |
| Wait for completion      | `notebooklm artifact wait <artifact_id>`                       |
| Download audio           | `notebooklm download audio ./output.mp3`                       |
| Download video           | `notebooklm download video ./output.mp4`                       |
| Download report          | `notebooklm download report ./report.md`                       |
| Download mind map        | `notebooklm download mind-map ./map.json`                      |
| Download data table      | `notebooklm download data-table ./data.csv`                    |
| Download quiz            | `notebooklm download quiz quiz.json`                           |
| Download quiz (markdown) | `notebooklm download quiz --format markdown quiz.md`           |
| Download flashcards      | `notebooklm download flashcards cards.json`                    |
| Download infographic     | `notebooklm download infographic ./infographic.png`            |
| Download slide deck      | `notebooklm download slide-deck ./slides.pdf`                  |
| List languages           | `notebooklm language list`                                     |
| Set language             | `notebooklm language set zh_Hans`                              |

**Partial IDs:** Use the first 6+ characters of UUIDs. Must be a unique prefix. Prefer full UUIDs in automation.

## Autonomy Rules

**Run without confirmation:**

- `status`, `auth check`, `list`, `source list`, `artifact list`, `language list/get/set`
- `use <id>`, `create`, `ask "..."`, `source add`
- `source wait`, `artifact wait`, `research wait/status` (in subagent context)

**Confirm before running:**

- `delete` — destructive
- `generate *` — long-running, may fail due to rate limits
- `download *` — writes to filesystem
- `artifact wait`, `source wait`, `research wait` — long-running (in main conversation)

## Generation Types

All generate commands support:

- `-s, --source` to use specific source(s) instead of all
- `--language` to override output language
- `--json` for machine-readable output (returns `task_id` and `status`)
- `--retry N` for automatic retry with exponential backoff

| Type        | Command                | Key Options                                                                                                                         | Download Format |
| ----------- | ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | --------------- |
| Podcast     | `generate audio`       | `--format [deep-dive\|brief\|critique\|debate]`, `--length [short\|default\|long]`                                                  | .mp3            |
| Video       | `generate video`       | `--format [explainer\|brief]`, `--style [auto\|classic\|whiteboard\|kawaii\|anime\|watercolor\|retro-print\|heritage\|paper-craft]` | .mp4            |
| Slide Deck  | `generate slide-deck`  | `--format [detailed\|presenter]`, `--length [default\|short]`                                                                       | .pdf            |
| Infographic | `generate infographic` | `--orientation [landscape\|portrait\|square]`, `--detail [concise\|standard\|detailed]`                                             | .png            |
| Report      | `generate report`      | `--format [briefing-doc\|study-guide\|blog-post\|custom]`                                                                           | .md             |
| Mind Map    | `generate mind-map`    | _(sync, instant)_                                                                                                                   | .json           |
| Data Table  | `generate data-table`  | description required                                                                                                                | .csv            |
| Quiz        | `generate quiz`        | `--difficulty [easy\|medium\|hard]`, `--quantity [fewer\|standard\|more]`                                                           | .json/.md/.html |
| Flashcards  | `generate flashcards`  | `--difficulty [easy\|medium\|hard]`, `--quantity [fewer\|standard\|more]`                                                           | .json/.md/.html |

## Features Beyond the Web UI

| Feature               | Command                       | Description                                     |
| --------------------- | ----------------------------- | ----------------------------------------------- |
| Batch downloads       | `download <type> --all`       | Download all artifacts of a type at once        |
| Quiz/Flashcard export | `download quiz --format json` | Export as JSON, Markdown, or HTML               |
| Mind map extraction   | `download mind-map`           | Hierarchical JSON for visualization tools       |
| Data table export     | `download data-table`         | Structured tables as CSV                        |
| Source fulltext       | `source fulltext <id>`        | Retrieve the indexed text content of any source |
| Programmatic sharing  | `share` commands              | Manage sharing permissions without the UI       |

## JSON Output Formats

Use `--json` for machine-readable output:

**Create notebook:**

```json
{ "id": "abc123de-...", "title": "Research" }
```

**Add source:**

```json
{ "source_id": "def456...", "title": "Example", "status": "processing" }
```

**Generate artifact:**

```json
{ "task_id": "xyz789...", "status": "pending" }
```

**Chat with references:**

```json
{
  "answer": "X is... [1] [2]",
  "conversation_id": "...",
  "references": [
    {
      "source_id": "abc123...",
      "citation_number": 1,
      "cited_text": "Relevant passage..."
    }
  ]
}
```

**Source list:**

```json
{
  "sources": [
    { "id": "...", "title": "...", "status": "ready|processing|error" }
  ]
}
```

**Artifact list:**

```json
{
  "artifacts": [
    {
      "id": "...",
      "title": "...",
      "type": "Audio Overview",
      "status": "in_progress|pending|completed|unknown"
    }
  ]
}
```

## Common Workflows

### Research to Podcast

1. `notebooklm create "Research: [topic]" --json` — capture notebook ID
2. `notebooklm source add "https://..." --json` for each source — capture source IDs
3. `notebooklm source list --json` — wait until all status=ready
4. `notebooklm generate audio "Focus on [angle]" --json` — capture artifact ID
5. `notebooklm artifact wait <artifact_id>` — blocks until complete
6. `notebooklm download audio ./podcast.mp3`

### Document Analysis

1. `notebooklm create "Analysis: [project]"`
2. `notebooklm source add ./doc.pdf`
3. `notebooklm ask "Summarize the key points"`
4. Continue chatting as needed

### Bulk Import

1. `notebooklm create "Collection: [name]"`
2. Add sources (max 50 per notebook):
   ```bash
   notebooklm source add "https://url1.com" --json
   notebooklm source add "https://url2.com" --json
   notebooklm source add ./local-file.pdf --json
   ```
3. `notebooklm source list --json` to verify

**Supported source types:** PDFs, YouTube URLs, web URLs, Google Docs, text files, Markdown, Word docs, audio files, video files, images.

### Deep Web Research

1. `notebooklm create "Research: [topic]"`
2. Start deep research: `notebooklm source add-research "topic" --mode deep --no-wait`
3. Wait: `notebooklm research wait --import-all --timeout 300`
4. Sources auto-imported when research completes

**Modes:** `--mode fast` (5-10 sources, seconds) vs `--mode deep` (20+ sources, 2-5 min).
**Search from:** `--from web` (default) or `--from drive` (Google Drive).

### Subagent Pattern for Long Operations

For non-blocking generation, spawn a background agent:

1. Run `notebooklm generate audio "..." --json` — parse `artifact_id`
2. Spawn a Task agent to wait and download:
   ```
   Wait for artifact {artifact_id} in notebook {notebook_id} to complete.
   Use: notebooklm artifact wait {artifact_id} -n {notebook_id} --timeout 600
   Then: notebooklm download audio ./podcast.mp3 -a {artifact_id} -n {notebook_id}
   ```
3. Main conversation continues while agent waits

## Processing Times

| Operation          | Typical Time   | Suggested Timeout |
| ------------------ | -------------- | ----------------- |
| Source processing  | 30s - 10 min   | 600s              |
| Research (fast)    | 30s - 2 min    | 180s              |
| Research (deep)    | 15 - 30+ min   | 1800s             |
| Mind map           | instant (sync) | n/a               |
| Notes              | instant        | n/a               |
| Quiz, flashcards   | 5 - 15 min     | 900s              |
| Report, data table | 5 - 15 min     | 900s              |
| Audio generation   | 10 - 20 min    | 1200s             |
| Video generation   | 15 - 45 min    | 2700s             |

## Error Handling

| Error                        | Cause                 | Action                                                |
| ---------------------------- | --------------------- | ----------------------------------------------------- |
| Auth/cookie error            | Session expired       | `notebooklm auth check` then `notebooklm login`       |
| "No notebook context"        | Context not set       | Use `-n <id>` flag or `notebooklm use <id>`           |
| "No result found for RPC ID" | Rate limiting         | Wait 5-10 min, retry                                  |
| `GENERATION_FAILED`          | Google rate limit     | Wait and retry later                                  |
| Download fails               | Generation incomplete | Check `artifact list` for status                      |
| Invalid notebook/source ID   | Wrong ID              | Run `notebooklm list` to verify                       |
| RPC protocol error           | Google changed APIs   | May need CLI update (`uv tool upgrade notebooklm-py`) |

**Exit codes:** 0 = success, 1 = error, 2 = timeout (wait commands only).

**Reliable operations:** Notebooks, sources, chat, mind map, report, data table.
**May hit rate limits:** Audio, video, quiz, flashcards, infographic, slide deck.

## Language Configuration

Language is a **global** setting affecting all notebooks.

```bash
notebooklm language list              # 80+ supported languages
notebooklm language get               # Current setting
notebooklm language set ja            # Set globally
notebooklm generate audio --language ja  # Override per command
```

Common codes: `en`, `zh_Hans`, `zh_Hant`, `ja`, `ko`, `es`, `fr`, `de`, `pt_BR`.

## Limitations

- **Unofficial API**: Uses browser automation via `notebooklm-py`. May break if Google changes NotebookLM internals. Not affiliated with Google.
- **50 sources per notebook**: Hard limit from NotebookLM.
- **Rate limiting**: Generation endpoints are rate-limited by Google. No workaround beyond waiting.
- **Auth expiry**: Google OAuth sessions expire. Re-run `notebooklm login` when auth fails.
- **No streaming**: Chat responses are returned in full, not streamed.
- **Single-agent context**: `notebooklm use` writes to a shared file. Use `-n` flags for parallel workflows.
