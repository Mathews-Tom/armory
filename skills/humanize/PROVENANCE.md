# Provenance — Humanize

## Pattern taxonomy

`references/detection-patterns.md` derives from Wikipedia's [Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing), maintained by WikiProject AI Cleanup and licensed CC BY-SA 4.0. The reference records the source revision date it last synced against. Its examples are original to this repository. Retired patterns live in `references/historical-patterns.md` rather than being dropped silently.

## Scripts

`scripts/lint_prose.py`, `scripts/check_preservation.py`, and `scripts/prose_markup.py` are original implementations written for this package using only the Python standard library. They contain no source code, rule tables, pattern text, or prose copied from the Wikipedia page or from any third-party humanizer project. The scanner's rules are a small mechanical-residue and cue set, not a second copy of the pattern catalogue; guidance text is read from `references/detection-patterns.md` at run time by `lint_prose.py patterns`.

[blader/humanizer](https://github.com/blader/humanizer) v3.1.0, commit `225a6f39ac85f76ee48dbad772ea4abe4ed6c9d8`, was inspected during design. It is a prose guidance package with its own validator, not a linter for user text, so it supplied no implementation, and nothing from it is vendored here.

[petergyang/no-ai-slop](https://github.com/petergyang/no-ai-slop) (MIT), commit `000650b156983f5159695b441477f4e63b25dc85`, was inspected for 2.2.0. Its editing principles informed the voice-preservation workflow, the portability test, the Staged Reveal and Reader Steering patterns, and the extensions to Staged Run-Up, Deep-Sounding Sayings, and Formulaic Challenges and Upbeat Conclusions; none of these come from the Wikipedia source. Some quoted tell phrases in the Watch-for lists also appear among its examples, because they are common idioms ("What if I told you", "Plot twist:", "What nobody tells you", "What most people get wrong", "The part everyone misses", "As you can see", "In other words", "In conclusion"). Explanations, before/after examples, scanner cues and workflow wording are original to this repository; nothing from it is vendored here.

## Limits

Scanner findings are review candidates. They are not evidence of AI authorship and do not measure detector scores.

The Markdown parser is conservative, not a full CommonMark implementation. It protects the documented code, quote, table, frontmatter and URL forms, including short quotations, list-nested code, lazy quote continuations and BOM-prefixed first lines. Setext headings, math blocks and arbitrary raw HTML are not special regions; keep non-prose payloads in code fences and do not mechanically edit unsupported markup.

Protected text is compared verbatim, including line endings. Allowing edits to a quote or table does not allow changes to its embedded code. Citation and numeric extraction is heuristic: supported numeric qualifiers and units are compared, while names, domain-specific units and other meaning-bearing terms require explicit `--literal` entries and a semantic read. Removing recognized chat citation artifacts outside protected content is intentionally permitted.
