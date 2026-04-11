---
name: to-markdown
description: 'Convert any file or URL to clean Markdown: PDF, DOCX, XLSX, PPTX, HTML, images (OCR), audio, CSV, YouTube. Optimised for LLM pipelines. Triggers on: "convert to markdown", "extract text from PDF", "parse this document", "ingest for RAG".'
metadata:
  version: 1.0.1
  category: visualization
  tags: [conversion, markdown, document-ingestion, pdf]
  difficulty: beginner
---

# To Markdown

Convert any file or URL to clean Markdown using [MarkItDown](https://github.com/microsoft/markitdown) as the conversion engine, with a lightweight fetch layer for URLs.

## Reference Files

| File                    | Purpose                                                 |
| ----------------------- | ------------------------------------------------------- |
| `references/formats.md` | Per-format handling notes, internal engines, known gaps |
| `references/fetch.md`   | URL fetch layer: trafilatura + Playwright strategies    |
| `references/install.md` | Dependency install guide for all variants               |

## Decision Tree

Determine the input type before touching any tool:

```text
Input type?
  Local file path        -> markitdown directly
  URL
    YouTube URL          -> markitdown directly (transcript extraction built-in)
    Static page          -> trafilatura fetch -> markitdown on HTML result
    JS-rendered / auth   -> Playwright fetch -> markitdown on result
  Pasted HTML string     -> markitdown directly on string
```

Do not use `web_fetch` or `WebFetch` for URLs — route through the fetch layer described in `references/fetch.md` to preserve the conversion pipeline.

## Core Conversion Workflow

### Step 1: Ensure dependencies

```bash
uv pip show markitdown || uv pip install 'markitdown[all]' trafilatura
```

See `references/install.md` for selective installs and full dependency table.

### Step 2: Convert

```python
from markitdown import MarkItDown

md = MarkItDown(enable_plugins=False)
result = md.convert("path/to/file.pdf")
print(result.text_content)
```

### Step 3: Workflow

1. Detect input type (file path, URL, raw HTML).
2. If URL, run fetch layer first (see `references/fetch.md`).
3. Run markitdown conversion on the local file or fetched content.
4. Post-process if needed (strip boilerplate, trim to main content).
5. Write output or return inline per output conventions below.

## Output Conventions

| Context                      | Output behaviour                                        |
| ---------------------------- | ------------------------------------------------------- |
| Single file, user wants file | Write `<input_stem>.md` to same directory               |
| Single file, inline request  | Return Markdown in conversation                         |
| Batch (multiple files)       | Write each to `<stem>.md`, summarise what was produced  |
| URL                          | Write `<slug>.md` to current directory or return inline |
| Piped into another workflow  | Return `result.text_content` string only                |

Default: "convert this file" -> write a file. "Read this" or "what does this say" -> return inline.

### Output Example

**Source** (two-column PDF with a table):

```text
Annual Report 2024                    Financial Highlights
Revenue grew 12% year-over-year...    | Metric   | 2023  | 2024  |
                                      | Revenue  | $4.2B | $4.7B |
                                      | EBITDA   | $1.1B | $1.3B |
```

**Converted Markdown**:

```markdown
# Annual Report 2024

Revenue grew 12% year-over-year...

## Financial Highlights

| Metric  | 2023  | 2024  |
| ------- | ----- | ----- |
| Revenue | $4.2B | $4.7B |
| EBITDA  | $1.1B | $1.3B |
```

Multi-column layouts merge into linear flow. Tables are preserved as Markdown tables. Headings are inferred from font size/weight.

## LLM Image Description (opt-in)

Markitdown supports an `llm_client` for image description in PPTX and image files. **Never enable by default** — it incurs cost, latency, and unexpected API calls. Prompt the user first: "This file contains images. Do you want me to use Claude to describe them? This will make additional API calls."

```python
import anthropic
from markitdown import MarkItDown

client = anthropic.Anthropic()
md = MarkItDown(llm_client=client, llm_model="claude-sonnet-4-20250514")
result = md.convert("presentation.pptx")
```

## Error Handling

| Severity     | Condition                                     | Action                                                           |
| ------------ | --------------------------------------------- | ---------------------------------------------------------------- |
| **Terminal** | Unsupported format (no converter exists)      | Report to user immediately; do not retry                         |
| **Terminal** | Password-protected Office file                | Report to user; no programmatic workaround                       |
| **Terminal** | File not found / path invalid                 | Report exact path; ask user to verify                            |
| **Recover**  | Empty output from PDF                         | Likely scanned — escalate to OCR path in `references/formats.md` |
| **Recover**  | Missing optional dependency (e.g. playwright) | Install the dependency, then retry the conversion                |
| **Recover**  | URL fetch returns paywall page                | Report fetch limitation; do not retry or attempt bypass          |
| **Recover**  | trafilatura returns empty                     | Escalate to Playwright fetch strategy per `references/fetch.md`  |

```python
result = md.convert(path)
if not result.text_content.strip():
    raise ValueError(f"No text extracted from {path}. See references/formats.md for OCR options.")
```

Never silently return empty Markdown. Surface the failure with the severity and a pointer to the relevant reference file.

## Known Gaps and Escalation

- **HTML fidelity**: markitdown uses `html2text` internally — complex layouts lose structure. For high-fidelity HTML conversion where DOM structure matters, suggest Turndown via Node subprocess.
- **Hard paywalls**: The fetch layer returns the regwall page, not the content. This is a fetch limitation, not a conversion problem.
- **Scanned PDFs** (image-only, no text layer): markitdown returns near-empty output. Escalate to OCR workflow (Azure Document Intelligence or Tesseract). See `references/formats.md`.
- **Protected Office files**: Password-protected DOCX/XLSX will fail. Inform the user.

## Calibration Rules

1. Converted output must contain at least 10 words per page of source document. Below this threshold, treat as empty extraction and escalate per the error handling table.
2. Tables in the source must appear as Markdown tables in the output — if a table is present in the original but missing in the conversion, flag it to the user.
3. Heading hierarchy from the source document must be preserved (H1 > H2 > H3). Flat output with no headings from a structured document indicates a conversion quality issue.
4. For URL conversions, output must not contain navigation elements, cookie banners, or footer boilerplate. If present, re-run through trafilatura with `include_tables=True` to strip boilerplate.
5. Multi-sheet XLSX must produce one clearly labeled section per sheet. Missing sheets indicate a partial conversion — report which sheets were extracted.

## Limitations

- No paywall bypass. Document it, don't attempt it.
- No Turndown integration built-in. Different runtime (Node.js).
- No scheduled/batch crawling. One conversion per invocation.
- No output format other than Markdown.
- Auto-generated YouTube captions may contain errors for technical terms.
- Scanned PDFs require external OCR — markitdown alone returns empty output.
