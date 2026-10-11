# Changelog — Humanize

## 2.1.0

- Add `scripts/lint_prose.py`: a deterministic prose scanner with stable rule IDs (`HUM001`-`HUM011`), exact offsets, line/column and evidence, `--lines` changed-line focus with paragraph context, an explicit `fix` command that deletes only selected chat artifacts into a new file, and `patterns` to print selected sections of the pattern reference instead of loading it whole.
- Add `scripts/check_preservation.py`: compares source and draft protected blocks in order (removal, addition, change, reorder), protected inline spans and prose literals as multisets (citations, technical identifiers, numbers with sign, currency, unit and qualifier), and explicit `--literal` names or terms. Prose order stays free; a pass is structural, not semantic.
- Add `scripts/prose_markup.py`, the shared parser: fenced, indented and HTML code, inline code (including multi-line spans), YAML/TOML frontmatter, tables, block quotes, quoted snippets, link targets and bare URLs with balanced parentheses, exact CRLF handling.
- Compare protected text verbatim, including code line endings; keep embedded code protected even when quote or table edits are explicitly allowed. Share chat-artifact recognition between scanning and preservation checks, without interpreting real URL contents as artifact residue.
- Rework the four-phase workflow: deterministic scan before judgment, lazy guidance and profile loading, a bounded rewrite of flagged paragraphs only, and the preservation checker before the final file is written. Add a mechanical-cleanup mode that runs no rewrite.
- Resolve the file-mode contradiction between "URLs untouched" and tracking cleanup: URLs, query strings and tracking parameters stay exact by default; removal is a separate explicit step on unsigned URLs, and signed links never change.
- Add regression tests for protected mixed Markdown, CRLF, quoted evidence, duplicate numbers and citations, unit and qualifier changes, identifier drift, safe fix selection, and invalid ranges; add evals for the new behavior.
- Keep the 29-pattern reference taxonomy, the sample-overrides-pattern rule, the no-invention rule, and every existing scope mode unchanged.
- Add package-local `PROVENANCE.md`.

## 2.0.0

- Existing pattern-taxonomy release; see git history for earlier changes.
