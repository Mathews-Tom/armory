# Fonts, assets and provenance

## Why fonts are provisioned explicitly

The Hyperframes compiler resolves named families before the browser loads linked stylesheets. A face declared only in `assets/fonts.css` therefore does not protect the compile path: the real CLI attempted `fonts.googleapis.com/css2` while rendering that arrangement. Provisioning now emits the same local font faces **inline in `index.html`**, where the compiler can see them, and keeps the linked CSS for editable asset provenance. The instrumented lint/check/snapshot/render workflow then completed without a recorded external Node fetch. This is evidence for the tested template and toolchain, not a sandbox guarantee for arbitrary JavaScript.

The package ships **no font**. A font is a user decision with its own licence.

## Provisioning

```bash
python3 "$SKILL_DIR/scripts/html_video.py" fonts add PROJECT \
  --font-file ./Brand-Regular.woff2 --family "Brand Sans" \
  --license-id OFL-1.1 --license-file ./OFL.txt \
  --source "https://example.org/where-you-got-it"
```

- Accepts woff2, woff, ttf and otf, detected by magic bytes. Collections (.ttc) are refused.
- `--license-id` is an SPDX id or a `LicenseRef-…` token; `--license-file` is the licence text that came with the font. Both are required, and the tool records them without judging them. Redistribution rights remain the user's responsibility.
- The font is copied to `assets/fonts/`, the licence to `assets/fonts/licenses/`, and a declaration is added to `PROVENANCE.json`. Both `assets/fonts.css` and the managed `html-video-fonts` style in `index.html` are regenerated. Do not hand-edit either generated block. Saved metadata and every destination path are validated before mutation; traversal and external symlink targets are refused.
- Templates use the alias family `HV Text`. Provide regular and bold files with `--weight 400` and `--weight 700`, or one variable font with `--weight "100 900"`. One file cannot back two separate faces.
- Swap a face with `--replace`; the previous file is removed when nothing else uses it.

If the user cannot supply a font, the only reproducible alternative is vector text: draw labels as SVG paths you outline yourself. That removes text from contrast checking and from selection, so state the trade-off. Do not rely on a system font.

## Provenance file

`PROVENANCE.json` holds `{"version": 1, "assets": [...]}`. Each entry needs `path`, `source` and `license` (non-empty strings); `license_file` and `sha256` are optional but validated when present; font entries also carry a `font` object written by `fonts add`.

```json
{ "path": "assets/logo.png", "source": "original", "license": "user-owned", "sha256": "…" }
```

Declarations are the user's statements. With `--require-provenance` (and always in `deliver`), every referenced file other than HTML and CSS must have one, and fonts must record a licence file.

## What the audit proves

| Code | Meaning |
|---|---|
| `remote_resource` | `http:`, `https:`, `ftp:`, `ws:` or protocol-relative URL in a render-critical position |
| `absolute_path`, `invalid_path`, `unsupported_scheme` | `file:`, `/root` or drive paths, backslashes, `javascript:` and similar |
| `path_escape`, `symlink_escape` | Lexically or through a symlink outside the project; internal symlinks are allowed |
| `missing_asset`, `case_mismatch`, `not_a_file` | The file is absent, differs in letter case (breaks on case-sensitive systems), or is a directory |
| `reference_cycle` | CSS `@import` or composition mounts that loop back |
| `invalid_data_uri`, `fragment_missing` | Malformed `data:` payload, or `#id` with no matching element |
| `font_not_declared`, `font_face_not_inline`, `font_face_no_url`, `font_face_local_source` | A named family lacks compiler-visible inline local faces, or a source can select a machine-dependent `local()` font |
| `font_dynamic`, `font_system_keyword`, `font_shorthand_unsupported` | Font-family scope or operating-system selection cannot be proven; use a literal provisioned family |
| `provenance_*`, `font_license_missing` | Missing, malformed or mismatched declarations |

References resolve from their containing file. CSS identifiers with escapes are decoded before extraction; namespace identifiers are not fetches. Fragment-only references and non-executable image data URIs need no file lookup. Embedded executable documents and data-URI fonts are refused. `<a href>` is not a resource load; script handlers are still inspected for hazards. Font licence requirements follow `@font-face` and font-preload context even when the file extension is unconventional.

## What the audit does not prove

The audit follows supported local SVG/XHTML resources and static module imports, and checks nested `srcdoc` up to a bounded depth. It is not a full CSS cascade resolver or JavaScript parser: computed URLs, script-set fonts, canvas text and runtime loading can escape extraction. Recognisable hazards are warnings, and a zero-warning scan does not prove their absence. Import-map scopes are over-approximated rather than resolved per importing document. Font-family custom properties are rejected instead of guessed from global definitions. For a hard offline guarantee, enforce network isolation outside this tool; review and correct all remaining warnings before rendering.
