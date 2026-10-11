"""Static extraction from HTML, CSS and script text using only the stdlib.

This is deliberately a reference extractor, not a browser: it finds the
references a renderer will resolve statically. It does not implement the CSS
cascade and it does not execute JavaScript. Where static syntax cannot be
interpreted conservatively (dynamic ``font-family``, unresolved animation
counts, import maps with bad addresses, over-nested ``srcdoc``) it reports an
explicit problem instead of guessing. Script-computed URLs are invisible to
it and are reported as limitations by the caller.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import cast

# --------------------------------------------------------------------------
# Data shapes
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Ref:
    """One reference.

    ``kind`` records the loading context so the audit can follow a file the way
    the browser would, regardless of its extension: ``script`` and ``module``
    are executed code, ``style`` is a stylesheet, ``composition`` is a mounted
    HTML composition, ``document`` is a nested browsing context, ``font`` is an
    ``@font-face`` source or font preload and ``bare`` is a bare module
    specifier that only an import map can resolve.
    """

    url: str
    line: int
    source: str
    kind: str = ""


@dataclass(frozen=True)
class Element:
    tag: str
    attrs: dict[str, str]
    line: int


@dataclass(frozen=True)
class CssText:
    """A stretch of CSS (a style element, a style attribute, or a file)."""

    line: int
    text: str


@dataclass(frozen=True)
class ScriptText:
    line: int
    text: str


@dataclass(frozen=True)
class Unsupported:
    """Static syntax the extractor refuses to interpret; always an error."""

    code: str
    line: int
    message: str


@dataclass
class HtmlScan:
    elements: list[Element] = field(default_factory=lambda: list[Element]())
    refs: list[Ref] = field(default_factory=lambda: list[Ref]())
    css: list[CssText] = field(default_factory=lambda: list[CssText]())
    scripts: list[ScriptText] = field(default_factory=lambda: list[ScriptText]())
    handlers: list[ScriptText] = field(default_factory=lambda: list[ScriptText]())
    fragment_refs: list[Ref] = field(default_factory=lambda: list[Ref]())
    nested: list[HtmlScan] = field(default_factory=lambda: list[HtmlScan]())
    unsupported: list[Unsupported] = field(default_factory=lambda: list[Unsupported]())
    import_map: list[tuple[str, str, int]] = field(
        default_factory=lambda: list[tuple[str, str, int]]()
    )
    has_visible_text: bool = False
    viewport: str | None = None

    @property
    def ids(self) -> set[str]:
        return {el.attrs["id"] for el in self.elements if el.attrs.get("id")}

    def walk(self) -> Iterator[HtmlScan]:
        """This document and every ``srcdoc`` document inside it, recursively."""
        yield self
        for inner in self.nested:
            yield from inner.walk()

    def all_css(self) -> list[CssText]:
        return [block for part in self.walk() for block in part.css]


# --------------------------------------------------------------------------
# srcset and CSS reference extraction
# --------------------------------------------------------------------------


def parse_srcset(value: str) -> list[str]:
    """Candidate URLs of an ``srcset``/``imagesrcset`` value, descriptors dropped."""
    urls: list[str] = []
    i, n = 0, len(value)
    while i < n:
        while i < n and (value[i].isspace() or value[i] == ","):
            i += 1
        if i >= n:
            break
        j = i
        while j < n and not value[j].isspace():
            j += 1
        url = value[i:j]
        i = j
        if url.endswith(","):
            stripped = url.rstrip(",")
            if stripped:
                urls.append(stripped)
            continue
        urls.append(url)
        depth = 0
        while i < n:
            char = value[i]
            i += 1
            if char == "(":
                depth += 1
            elif char == ")":
                depth = max(0, depth - 1)
            elif char == "," and depth == 0:
                break
    return urls


_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def strip_css_comments(text: str) -> str:
    """Remove comments while preserving line numbers."""
    return _COMMENT.sub(lambda m: re.sub(r"[^\n]", " ", m.group()), text)


_CSS_ESCAPE = re.compile(
    r"\\(?:([0-9a-fA-F]{1,6})(?:\r\n|[ \t\r\n\f])?|([^\n\r\f0-9a-fA-F]))"
)


def decode_css_escapes(text: str) -> str:
    """Decode CSS escapes that spell identifier characters (``\\75 rl(`` is ``url(``).

    Escapes that would produce structural characters (quotes, parentheses,
    braces, semicolons, slashes, backslash, whitespace) are left in place so
    they cannot change how the surrounding rule is split; a URL that still
    contains a backslash is rejected as an invalid path by the audit.
    """

    def keep(char: str) -> bool:
        return char.isalnum() or char in "_-" or ord(char) > 127

    def replace(match: re.Match[str]) -> str:
        if match.group(1) is not None:
            point = int(match.group(1), 16)
            char = (
                "\ufffd"
                if point == 0 or point > 0x10FFFF or 0xD800 <= point <= 0xDFFF
                else chr(point)
            )
        else:
            char = match.group(2)
        return char if keep(char) else match.group(0)

    return _CSS_ESCAPE.sub(replace, text)


def prepare_css(text: str) -> str:
    """Comments removed and identifier escapes decoded; the form every CSS scan reads."""
    return decode_css_escapes(strip_css_comments(text))


_FACE = re.compile(r"@font-face\s*\{([^}]*)\}", re.I)
_NAMESPACE = re.compile(r"@namespace\b[^;{}]*;", re.I)
_CSS_TOKEN = re.compile(
    r"""
    @import\s+(?:url\(\s*(?P<iu>"[^"]*"|'[^']*'|[^)\s]*)\s*\)|(?P<is>"[^"]*"|'[^']*'))
    |(?P<fn>(?<![\w-])(?:-webkit-)?image-set\()
    |(?<![\w-])url\(\s*(?P<u>"[^"]*"|'[^']*'|[^)]*?)\s*\)
    """,
    re.X | re.I,
)
_QUOTED = re.compile(r""""([^"]*)"|'([^']*)'""")
_URL_FN = re.compile(r"url\([^)]*\)", re.I)


def _blank(match: re.Match[str]) -> str:
    return re.sub(r"[^\n]", " ", match.group())


def _unquote(token: str) -> str:
    token = token.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        return token[1:-1]
    return token


def _closing_paren(text: str, start: int) -> int:
    depth, quote = 1, ""
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
    return len(text)


def scan_css_refs(text: str, base_line: int = 1) -> list[Ref]:
    """``url()``, ``@import`` and ``image-set()`` string references in CSS.

    Escapes in identifiers are decoded first, ``@namespace`` URIs are not
    fetches and are skipped, and a ``url()`` inside ``@font-face`` is tagged
    ``font`` so licence binding follows the source context, not the extension.
    """
    clean = _NAMESPACE.sub(_blank, prepare_css(text))
    face_spans = [(m.start(), m.end()) for m in _FACE.finditer(clean)]
    refs: list[Ref] = []
    for match in _CSS_TOKEN.finditer(clean):
        line = base_line + clean.count("\n", 0, match.start())
        if match.group("fn"):
            end = _closing_paren(clean, match.end())
            body = _URL_FN.sub("", clean[match.end() : end])
            for quoted in _QUOTED.finditer(body):
                refs.append(
                    Ref(
                        quoted.group(1) or quoted.group(2) or "",
                        line,
                        "css image-set()",
                    )
                )
            continue
        imported = (
            match.group("iu") if match.group("iu") is not None else match.group("is")
        )
        if imported is not None:
            refs.append(Ref(_unquote(imported), line, "css @import", "style"))
            continue
        in_face = any(start <= match.start() < stop for start, stop in face_spans)
        refs.append(
            Ref(
                _unquote(match.group("u")),
                line,
                "css url()",
                "font" if in_face else "",
            )
        )
    return refs


# --------------------------------------------------------------------------
# JavaScript module references
# --------------------------------------------------------------------------

JS_TYPES = frozenset(
    {
        "", "module", "text/javascript", "application/javascript",
        "application/ecmascript", "application/x-ecmascript",
        "application/x-javascript", "text/ecmascript", "text/jscript",
        "text/livescript", "text/x-ecmascript", "text/x-javascript",
        "text/javascript1.0", "text/javascript1.1", "text/javascript1.2",
        "text/javascript1.3", "text/javascript1.4", "text/javascript1.5",
    }
)  # fmt: skip


def strip_js_comments(text: str) -> str:
    """Blank ``//`` and ``/* */`` comments outside strings, keeping line numbers.

    Regular-expression literals are not recognised; a literal that contains an
    unbalanced quote can desynchronise the string state. That only affects
    which static imports are seen, never what is accepted as safe.
    """
    out: list[str] = []
    i, n, quote = 0, len(text), ""
    while i < n:
        char = text[i]
        if quote:
            out.append(char)
            if char == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if char == quote or (char == "\n" and quote != "`"):
                quote = ""
            i += 1
        elif char in "\"'`":
            quote = char
            out.append(char)
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            end = n if end < 0 else end
            out.append(" " * (end - i))
            i = end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            out.append(re.sub(r"[^\n]", " ", text[i:end]))
            i = end
        else:
            out.append(char)
            i += 1
    return "".join(out)


_IMPORT_FROM = re.compile(
    r"""(?<![\w$.])import\s*
    (?:(?:[\w$]+|\*\s*as\s+[\w$]+|\{[^}]*\})(?:\s*,\s*(?:\*\s*as\s+[\w$]+|\{[^}]*\}))?\s*from\s*)?
    (?P<q>['"])(?P<s>[^'"\n]+)(?P=q)""",
    re.X,
)
_EXPORT_FROM = re.compile(
    r"""(?<![\w$.])export\s*(?:\*(?:\s*as\s+[\w$]+)?|\{[^}]*\})\s*from\s*
    (?P<q>['"])(?P<s>[^'"\n]+)(?P=q)""",
    re.X,
)
_DYNAMIC_IMPORT = re.compile(
    r"""(?<![\w$.])import\s*\(\s*(?P<q>['"])(?P<s>[^'"\n]+)(?P=q)\s*[,)]"""
)
_META_URL = re.compile(
    r"""new\s+URL\s*\(\s*(?P<q>['"])(?P<s>[^'"\n]+)(?P=q)\s*,\s*import\.meta\.url\b"""
)
_SCHEME_START = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def scan_js_refs(text: str, base_line: int = 1) -> list[Ref]:
    """Static module graph edges: ``import``/``export … from``, ``import("lit")``.

    ``new URL("./x", import.meta.url)`` is reported as a plain asset reference.
    A specifier that is neither path-like nor an absolute URL is ``bare``: only
    an import map can resolve it, so the audit resolves it against the maps.
    Computed specifiers cannot be seen here; the script hazard scan warns on
    them.
    """
    clean = strip_js_comments(text)
    refs: list[Ref] = []
    for pattern, source in (
        (_IMPORT_FROM, "js import"),
        (_EXPORT_FROM, "js export-from"),
        (_DYNAMIC_IMPORT, "js import()"),
    ):
        for match in pattern.finditer(clean):
            spec = match.group("s")
            line = base_line + clean.count("\n", 0, match.start())
            path_like = spec.startswith(("./", "../", "/")) or _SCHEME_START.match(spec)
            refs.append(Ref(spec, line, source, "module" if path_like else "bare"))
    for match in _META_URL.finditer(clean):
        line = base_line + clean.count("\n", 0, match.start())
        refs.append(Ref(match.group("s"), line, "js new URL()"))
    return refs


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

_PAINT_ATTRS = (
    "fill",
    "stroke",
    "filter",
    "mask",
    "clip-path",
    "marker-start",
    "marker-mid",
    "marker-end",
)
_NO_REF_HREF_TAGS = {"a", "area"}
_JS_URL_ATTRS = ("href", "src", "action", "formaction", "data", "xlink:href")
_MAX_SRCDOC_DEPTH = 3
_CDATA = re.compile(r"<!\[CDATA\[|\]\]>")
_PI_HREF = re.compile(r"""href\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.I)


def _link_kind(attrs: dict[str, str]) -> str:
    rel = set(attrs.get("rel", "").lower().split())
    if "stylesheet" in rel:
        return "style"
    if "modulepreload" in rel:
        return "script"
    if "preload" in rel:
        return {"script": "script", "style": "style", "font": "font"}.get(
            attrs.get("as", "").strip().lower(), ""
        )
    return ""


class _Scanner(HTMLParser):
    def __init__(self, depth: int, line_offset: int) -> None:
        super().__init__(convert_charrefs=True)
        self.scan = HtmlScan()
        self._depth = depth
        self._offset = line_offset
        self._raw: tuple[str, dict[str, str], int, list[str]] | None = None
        self._head_depth = 0

    def _line(self) -> int:
        return self.getpos()[0] + self._offset

    def _add_refs(self, tag: str, attrs: dict[str, str], line: int) -> None:
        rel = set(attrs.get("rel", "").lower().split())
        skip_link = tag == "link" and (
            "canonical" in rel or ("alternate" in rel and "stylesheet" not in rel)
        )
        js_script = (
            tag == "script" and attrs.get("type", "").strip().lower() in JS_TYPES
        )
        for name in ("src", "poster", "background", "xlink:href"):
            if name in attrs:
                kind = ""
                if name == "src" and js_script:
                    kind = "script"
                elif name == "src" and tag in ("iframe", "frame", "embed"):
                    kind = "document"
                elif name == "xlink:href" and tag == "script":
                    kind = "script"
                self._add_ref(tag, name, attrs[name], line, kind)
        for name in ("data-composition-src", "data-composition-file"):
            if name in attrs:
                self._add_ref(tag, name, attrs[name], line, "composition")
        if "href" in attrs and tag not in _NO_REF_HREF_TAGS and not skip_link:
            kind = _link_kind(attrs) if tag == "link" else ""
            if tag == "script":
                kind = "script"
            self._add_ref(tag, "href", attrs["href"], line, kind)
        if tag == "object" and "data" in attrs:
            self._add_ref(tag, "data", attrs["data"], line, "document")
        for name in ("srcset", "imagesrcset"):
            if name in attrs:
                for url in parse_srcset(attrs[name]):
                    self.scan.refs.append(Ref(url, line, f"{tag}[{name}]"))
        if "srcdoc" in attrs:
            self._add_srcdoc(attrs["srcdoc"], line)

    def _add_ref(
        self, tag: str, name: str, value: str, line: int, kind: str = ""
    ) -> None:
        ref = Ref(value, line, f"{tag}[{name}]", kind)
        if (
            value.strip().startswith("#")
            and name in ("href", "xlink:href")
            and tag != "link"
        ):
            self.scan.fragment_refs.append(ref)
        else:
            self.scan.refs.append(ref)

    def _add_srcdoc(self, text: str, line: int) -> None:
        if self._depth >= _MAX_SRCDOC_DEPTH:
            self.scan.unsupported.append(
                Unsupported(
                    "srcdoc_too_deep",
                    line,
                    f"iframe srcdoc is nested more than {_MAX_SRCDOC_DEPTH} levels deep; "
                    "the static audit does not follow it. Move the document to a local file",
                )
            )
            return
        inner = scan_html(text, _depth=self._depth + 1, _line_offset=line - 1)
        self.scan.nested.append(inner)
        if any(part.has_visible_text for part in inner.walk()):
            self.scan.has_visible_text = True

    def _add_script_attrs(self, attrs: dict[str, str], line: int) -> None:
        for name, value in attrs.items():
            if name.startswith("on") and len(name) > 2 and value.strip():
                self.scan.handlers.append(ScriptText(line, value))
            elif name in _JS_URL_ATTRS:
                squeezed = re.sub(r"[\t\r\n]", "", value).lstrip()
                if squeezed.lower().startswith("javascript:"):
                    self.scan.handlers.append(ScriptText(line, squeezed[11:]))

    def handle_pi(self, data: str) -> None:
        if data.lower().startswith("xml-stylesheet"):
            match = _PI_HREF.search(data)
            if match:
                value = match.group(1) if match.group(1) is not None else match.group(2)
                self.scan.refs.append(
                    Ref(value, self._line(), "xml-stylesheet", "style")
                )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        line = self._line()
        self.scan.elements.append(Element(tag, values, line))
        if tag == "head":
            self._head_depth += 1
        if tag == "meta" and values.get("name", "").lower() == "viewport":
            self.scan.viewport = values.get("content", "")
        self._add_refs(tag, values, line)
        self._add_script_attrs(values, line)
        if "style" in values:
            self.scan.css.append(CssText(line, values["style"]))
        for name in _PAINT_ATTRS:
            if name in values and "url(" in values[name].lower():
                self.scan.css.append(CssText(line, f"{name}:{values[name]};"))
        if "font-family" in values:
            self.scan.css.append(CssText(line, f"font-family:{values['font-family']};"))
        if tag == "font" and "face" in values:
            self.scan.css.append(CssText(line, f"font-family:{values['face']};"))
        if tag in ("script", "style"):
            self._raw = (tag, values, line, [])

    def handle_endtag(self, tag: str) -> None:
        if tag == "head" and self._head_depth:
            self._head_depth -= 1
        raw = self._raw
        if raw is None or raw[0] != tag:
            return
        self._raw = None
        _, values, line, chunks = raw
        text = _CDATA.sub("", "".join(chunks))
        if tag == "style":
            self.scan.css.append(CssText(line, text))
            return
        if "src" in values:
            return
        kind = values.get("type", "").strip().lower()
        if kind in JS_TYPES:
            self.scan.scripts.append(ScriptText(line, text))
        elif kind == "importmap":
            self._import_map(text, line)
        elif kind == "speculationrules":
            self._speculation_rules(text, line)

    def _json(
        self, text: str, line: int, code: str, what: str
    ) -> dict[str, object] | None:
        try:
            data: object = json.loads(text)
        except ValueError as error:
            self.scan.unsupported.append(
                Unsupported(code, line, f"{what} is not valid JSON ({error})")
            )
            return None
        if not isinstance(data, dict):
            self.scan.unsupported.append(
                Unsupported(code, line, f"{what} must be a JSON object")
            )
            return None
        return cast("dict[str, object]", data)

    def _import_map(self, text: str, line: int) -> None:
        data = self._json(text, line, "importmap_invalid", "import map")
        if data is None:
            return
        sections: list[object] = [data.get("imports")]
        scopes = data.get("scopes")
        if isinstance(scopes, dict):
            sections.extend(cast("dict[str, object]", scopes).values())
        for section in sections:
            if not isinstance(section, dict):
                continue
            for key, address in cast("dict[str, object]", section).items():
                if not isinstance(address, str):
                    continue
                if not (
                    address.startswith(("/", "./", "../"))
                    or _SCHEME_START.match(address)
                ):
                    self.scan.unsupported.append(
                        Unsupported(
                            "importmap_address_invalid",
                            line,
                            f"import map address {address!r} for {key!r} must start with ./, ../, / or be an absolute URL",
                        )
                    )
                    continue
                self.scan.import_map.append((key, address, line))
                # A trailing-slash key maps a directory prefix, not one file; its
                # local target is resolved per importing specifier by the audit.
                if not (key.endswith("/") and address.startswith(("./", "../"))):
                    self.scan.refs.append(Ref(address, line, "importmap", "module"))

    def _speculation_rules(self, text: str, line: int) -> None:
        data = self._json(text, line, "speculationrules_invalid", "speculation rules")
        if data is None:
            return
        for rules in data.values():
            if not isinstance(rules, list):
                continue
            for rule in cast("list[object]", rules):
                if not isinstance(rule, dict):
                    continue
                fields = cast("dict[str, object]", rule)
                urls = fields.get("urls")
                if isinstance(urls, list):
                    for url in cast("list[object]", urls):
                        if isinstance(url, str):
                            self.scan.refs.append(
                                Ref(url, line, "speculationrules", "document")
                            )
                if "where" in fields or fields.get("source") == "document":
                    self.scan.unsupported.append(
                        Unsupported(
                            "speculationrules_document_rules",
                            line,
                            "document speculation rules match page links the static audit cannot enumerate; list explicit local urls or remove the rules",
                        )
                    )

    def handle_data(self, data: str) -> None:
        if self._raw is not None:
            self._raw[3].append(data)
        elif not self._head_depth and data.strip():
            self.scan.has_visible_text = True


def scan_html(text: str, _depth: int = 0, _line_offset: int = 0) -> HtmlScan:
    parser = _Scanner(_depth, _line_offset)
    parser.feed(text)
    parser.close()
    scan = parser.scan
    for css in list(scan.css):
        scan.refs.extend(scan_css_refs(css.text, css.line))
    for script in [*scan.scripts, *scan.handlers]:
        scan.refs.extend(scan_js_refs(script.text, script.line))
    return scan


# --------------------------------------------------------------------------
# Fonts
# --------------------------------------------------------------------------

GENERIC_FAMILIES = frozenset(
    {
        "serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-serif",
        "ui-sans-serif", "ui-monospace", "ui-rounded", "emoji", "math", "fangsong",
        "inherit", "initial", "unset", "revert", "revert-layer",
    }
)  # fmt: skip
SYSTEM_FONT_KEYWORDS = frozenset(
    {"caption", "icon", "menu", "message-box", "small-caption", "status-bar"}
)
_GLOBAL_KEYWORDS = frozenset({"inherit", "initial", "unset", "revert", "revert-layer"})

_FAMILY_DECL = re.compile(r"(?<![\w-])font-family\s*:\s*([^;}]+)", re.I)
_SHORTHAND_DECL = re.compile(r"(?<![\w-])font\s*:\s*([^;}]+)", re.I)
_CUSTOM_PROP = re.compile(r"(--[\w-]+)\s*:\s*([^;}]+)")
_FACE_SRC = re.compile(r"(?<![\w-])src\s*:\s*([^;}]+)", re.I)
_VAR_START = re.compile(r"(?<![\w-])var\(", re.I)
_LENGTH = re.compile(
    r"^(?:[+-]?(?:\d*\.\d+|\d+)(?:e[+-]?\d+)?(?:px|pt|em|rem|%|vw|vh|vmin|vmax|vi|vb"
    r"|ch|ex|cm|mm|in|pc|q|cqw|cqh|svh|lvh|dvh|svw|lvw|dvw|lh|rlh|cap|ic)|0)$",
    re.I,
)
_SIZE_KEYWORDS = frozenset(
    {"xx-small", "x-small", "small", "medium", "large", "x-large", "xx-large",
     "xxx-large", "smaller", "larger"}
)  # fmt: skip
_MATH = re.compile(r"^(?:calc|clamp|min|max|var|env|attr)\(", re.I)
_IMPORTANT = re.compile(r"!\s*important", re.I)


def normalize_family(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().strip("\"'").strip()).lower()


def split_families(value: str) -> list[str]:
    """Split a ``font-family`` list on top-level commas and strip quotes."""
    value = _IMPORTANT.sub("", value)
    items: list[str] = []
    buf: list[str] = []
    quote, depth = "", 0
    for char in value:
        if quote:
            buf.append(char)
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
            buf.append(char)
        elif char == "(":
            depth += 1
            buf.append(char)
        elif char == ")":
            depth = max(0, depth - 1)
            buf.append(char)
        elif char == "," and depth == 0:
            items.append("".join(buf))
            buf = []
        else:
            buf.append(char)
    items.append("".join(buf))
    return [item.strip().strip("\"'").strip() for item in items if item.strip()]


def _top_tokens(value: str) -> list[tuple[str, int, int]]:
    """Whitespace-separated tokens outside quotes and parentheses, with offsets."""
    tokens: list[tuple[str, int, int]] = []
    i, n = 0, len(value)
    while i < n:
        while i < n and value[i].isspace():
            i += 1
        if i >= n:
            break
        start, depth, quote = i, 0, ""
        while i < n:
            char = value[i]
            if quote:
                if char == "\\":
                    i += 2
                    continue
                if char == quote:
                    quote = ""
            elif char in "\"'":
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth = max(0, depth - 1)
            elif char.isspace() and depth == 0:
                break
            i += 1
        tokens.append((value[start:i], start, min(i, n)))
    return tokens


def _split_top(value: str, separator: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    quote, depth = "", 0
    for char in value:
        if quote:
            buf.append(char)
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
            buf.append(char)
        elif char == "(":
            depth += 1
            buf.append(char)
        elif char == ")":
            depth = max(0, depth - 1)
            buf.append(char)
        elif char == separator and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(char)
    parts.append("".join(buf))
    return parts


@dataclass(frozen=True)
class FontUse:
    family: str
    line: int


@dataclass(frozen=True)
class FontProblem:
    """A font declaration the audit cannot interpret.

    ``font_dynamic``: ``var()`` that does not resolve to exactly one value.
    ``font_shorthand_unsupported``: a ``font`` shorthand with no readable family.
    ``font_system_keyword``: ``font: caption`` and the other OS font keywords.
    """

    code: str
    line: int
    detail: str


@dataclass
class FontScan:
    declared: dict[str, int] = field(default_factory=lambda: dict[str, int]())
    uses: list[FontUse] = field(default_factory=lambda: list[FontUse]())
    faces_without_url: list[FontUse] = field(default_factory=lambda: list[FontUse]())
    local_sources: list[FontUse] = field(default_factory=lambda: list[FontUse]())
    problems: list[FontProblem] = field(default_factory=lambda: list[FontProblem]())


def collect_custom_props(blocks: list[CssText]) -> dict[str, list[str]]:
    """Every distinct definition of every custom property, across all blocks.

    Scope is deliberately ignored; a property with more than one definition is
    treated as ambiguous by :func:`expand_vars` instead of being flattened.
    """
    custom: dict[str, list[str]] = {}
    for block in blocks:
        for prop in _CUSTOM_PROP.finditer(prepare_css(block.text)):
            value = _IMPORTANT.sub("", prop.group(2)).strip()
            definitions = custom.setdefault(prop.group(1), [])
            if value not in definitions:
                definitions.append(value)
    return custom


def expand_vars(
    value: str, custom: dict[str, list[str]], depth: int = 0
) -> list[str] | None:
    """Substitute ``var()`` with its single definition and its fallback.

    Returns every concrete value the declaration can take, or ``None`` when a
    property has several definitions, none and no fallback, or recursion does
    not end: the value is then dynamic and must not be trusted.
    """
    match = _VAR_START.search(value)
    if match is None:
        return [value]
    if depth >= 5:
        return None
    end = _closing_paren(value, match.end())
    if end >= len(value):
        return None
    inner = value[match.end() : end]
    name, comma, fallback = inner.partition(",")
    definitions = custom.get(name.strip(), [])
    if len(definitions) > 1:
        return None
    candidates = list(definitions)
    if comma:
        candidates.append(fallback.strip())
    if not candidates:
        return None
    expanded: list[str] = []
    for candidate in candidates:
        inner_values = expand_vars(
            value[: match.start()] + candidate + value[end + 1 :], custom, depth + 1
        )
        if inner_values is None:
            return None
        expanded.extend(inner_values)
    return expanded


def _size_base(token: str) -> str:
    depth = 0
    for index, char in enumerate(token):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "/" and depth == 0:
            return token[:index]
    return token


def _is_size(token: str, allow_keyword: bool) -> bool:
    if token.startswith("/"):
        return False
    base = _size_base(token)
    return bool(
        _LENGTH.match(base)
        or _MATH.match(base)
        or (allow_keyword and base.lower() in _SIZE_KEYWORDS)
    )


def _shorthand_family(value: str) -> tuple[str | None, str, str]:
    """Family list of a ``font`` shorthand: (family text, problem code, detail)."""
    text = _IMPORTANT.sub("", value).strip()
    lowered = text.lower()
    if lowered in _GLOBAL_KEYWORDS:
        return None, "", ""
    if lowered in SYSTEM_FONT_KEYWORDS:
        return None, "font_system_keyword", text
    tokens = _top_tokens(text)
    first = next(
        (i for i, (tok, _, _) in enumerate(tokens) if _is_size(tok, True)), None
    )
    if first is None:
        return None, "font_shorthand_unsupported", text
    last = first
    while last + 1 < len(tokens) and _is_size(tokens[last + 1][0], False):
        last += 1
    nxt = last + 1
    if tokens[last][0].endswith("/"):
        nxt += 1
    elif nxt < len(tokens) and tokens[nxt][0].startswith("/"):
        nxt += 2 if tokens[nxt][0] == "/" else 1
    if nxt < len(tokens):
        return text[tokens[nxt][1] :], "", ""
    if last > first:  # the final size-like token was really the family
        return tokens[last][0], "", ""
    return (
        None,
        "font_dynamic" if "var(" in text.lower() else "font_shorthand_unsupported",
        text,
    )


def scan_fonts(
    blocks: list[CssText], custom: dict[str, list[str]] | None = None
) -> FontScan:
    """Scan CSS blocks; pass ``custom`` to resolve ``var()`` across files."""
    result = FontScan()
    custom = custom if custom is not None else collect_custom_props(blocks)
    for block in blocks:
        text = prepare_css(block.text)
        line = block.line
        for face in _FACE.finditer(text):
            _scan_face(result, face.group(1), line + text.count("\n", 0, face.start()))
        outside = _FACE.sub(_blank, text)
        for match in _FAMILY_DECL.finditer(outside):
            _collect(
                result,
                match.group(1),
                line + outside.count("\n", 0, match.start()),
                custom,
            )
        for match in _SHORTHAND_DECL.finditer(outside):
            at = line + outside.count("\n", 0, match.start())
            family, code, detail = _shorthand_family(match.group(1))
            if code:
                result.problems.append(FontProblem(code, at, detail[:80]))
            elif family is not None:
                _collect(result, family, at, custom)
    return result


def _scan_face(result: FontScan, body: str, line: int) -> None:
    family = _FAMILY_DECL.search(body)
    names = split_families(family.group(1)) if family else []
    name = names[0] if names else "(unnamed)"
    if names:
        result.declared.setdefault(normalize_family(name), line)
    sources = [m.group(1) for m in _FACE_SRC.finditer(body)]
    has_url = any(re.search(r"(?<![\w-])url\(", s, re.I) for s in sources)
    has_local = any(re.search(r"(?<![\w-])local\(", s, re.I) for s in sources)
    if not has_url:
        result.faces_without_url.append(FontUse(name, line))
    elif has_local:
        result.local_sources.append(FontUse(name, line))


def _collect(
    result: FontScan, value: str, line: int, custom: dict[str, list[str]]
) -> None:
    if re.search(r"\bvar\s*\(", value, re.I):
        result.problems.append(FontProblem("font_dynamic", line, value.strip()[:80]))
        return
    expanded = expand_vars(value, custom)
    if expanded is None:
        result.problems.append(FontProblem("font_dynamic", line, value.strip()[:80]))
        return
    for item in expanded:
        for family in split_families(item):
            if normalize_family(family) not in GENERIC_FAMILIES:
                result.uses.append(FontUse(family, line))


# --------------------------------------------------------------------------
# Motion-related CSS and script hazards
# --------------------------------------------------------------------------

_ANIMATION_DECL = re.compile(
    r"(?<![\w-])(?:-webkit-)?(animation(?:-name|-iteration-count)?)\s*:\s*([^;}]+)",
    re.I,
)
_TRANSITION = re.compile(
    r"(?<![\w-])(?:-webkit-)?transition(?:-duration)?\s*:\s*([^;}]+)", re.I
)
_KEYFRAMES = re.compile(r"@(?:-webkit-)?keyframes\b", re.I)
_ITERATION_NUMBER = re.compile(r"^(?:\d*\.\d+|\d+)(?:e[+-]?\d+)?$", re.I)
_UNRESOLVED_KEYWORDS = frozenset({"inherit", "unset", "revert", "revert-layer"})


@dataclass
class MotionScan:
    animated: bool = False
    infinite: list[int] = field(default_factory=lambda: list[int]())
    unresolved: list[tuple[int, str]] = field(
        default_factory=lambda: list[tuple[int, str]]()
    )
    transitions: list[int] = field(default_factory=lambda: list[int]())


def _animation_value(
    prop: str, value: str, props: dict[str, list[str]]
) -> tuple[bool, bool, str]:
    """(is animated, is infinite, unresolved detail) for one animation declaration."""
    text = _IMPORTANT.sub("", value).strip()
    expanded = expand_vars(text, props)
    if expanded is None:
        return False, False, f"{text[:60]!r} uses var() that has no single value"
    animated = infinite = False
    unresolved = ""
    for item in expanded:
        for part in _split_top(item, ","):
            low = part.strip().lower()
            if low in ("", "none"):
                continue
            animated = True
            if prop == "animation-name":
                continue
            if prop == "animation-iteration-count":
                if low == "infinite":
                    infinite = True
                elif not (_ITERATION_NUMBER.match(low) or low == "initial"):
                    unresolved = unresolved or f"iteration count {part.strip()[:40]!r}"
                continue
            for token, _, _ in _top_tokens(part):
                lowered = token.lower()
                if lowered == "infinite":
                    infinite = True
                elif _MATH.match(lowered) or lowered in _UNRESOLVED_KEYWORDS:
                    unresolved = (
                        unresolved or f"{token[:40]!r} in an animation shorthand"
                    )
    return animated, infinite, unresolved


def scan_css_motion(blocks: list[CssText]) -> MotionScan:
    """Animation facts over every block together.

    Keyframes and the declarations that use them routinely live in different
    blocks (a stylesheet and a style attribute), so ``animated`` is decided
    across all of them. ``-webkit-`` prefixed declarations count. An iteration
    count that is ``infinite`` or cannot be resolved to a number is reported.
    """
    result = MotionScan()
    props = collect_custom_props(blocks)
    keyframes = animation_declared = False
    for block in blocks:
        text = prepare_css(block.text)
        keyframes = keyframes or bool(_KEYFRAMES.search(text))
        for match in _ANIMATION_DECL.finditer(text):
            line = block.line + text.count("\n", 0, match.start())
            animated, infinite, unresolved = _animation_value(
                match.group(1).lower(), match.group(2), props
            )
            animation_declared = animation_declared or animated
            if infinite:
                result.infinite.append(line)
            if unresolved:
                result.unresolved.append((line, unresolved))
        for match in _TRANSITION.finditer(text):
            if match.group(1).strip().lower() not in ("none", "0", "0s", "0ms"):
                result.transitions.append(
                    block.line + text.count("\n", 0, match.start())
                )
    result.animated = keyframes and animation_declared
    return result


_NONDETERMINISTIC = re.compile(
    r"\b(?:requestAnimationFrame|requestIdleCallback|setTimeout|setInterval|Date\.now"
    r"|performance\.now|Math\.random|crypto\.getRandomValues|crypto\.randomUUID)\b"
    r"|\bnew\s+Date\s*\(\s*\)|(?<![\w$.])Date\s*\(\s*\)"
)
_PAGE_CLOCK_ANIMATION = re.compile(
    r"\.animate\s*\(|\bnew\s+(?:Animation|KeyframeEffect)\b|\bdocument\.timeline\b"
)
_NETWORK_API = re.compile(
    r"\b(fetch\s*\(|XMLHttpRequest|WebSocket|WebTransport|EventSource|sendBeacon|importScripts"
    r"|new\s+(?:Shared)?Worker\b|serviceWorker\b|import\s*\()"
)
_REMOTE_LITERAL = re.compile(
    r"""(?:https?|wss?|ftp)://(?!www\.w3\.org/)"""
    r"""(?:localhost\b|\d{1,3}(?:\.\d{1,3}){3}\b|[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})"""
    r"""(?::\d+)?[^\s"'`)]*"""
    r"""|(?<=["'`])//[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?:[/:][^\s"'`)]*)?"""
)


@dataclass(frozen=True)
class ScriptHazard:
    code: str
    line: int
    snippet: str


def scan_script(text: str, base_line: int = 1) -> list[ScriptHazard]:
    hazards: list[ScriptHazard] = []
    patterns = (
        ("nondeterministic_api", _NONDETERMINISTIC),
        ("page_clock_animation", _PAGE_CLOCK_ANIMATION),
        ("dynamic_network_api", _NETWORK_API),
        ("remote_url_literal", _REMOTE_LITERAL),
    )
    for code, pattern in patterns:
        for match in pattern.finditer(text):
            line = base_line + text.count("\n", 0, match.start())
            hazards.append(ScriptHazard(code, line, match.group(0)[:80]))
    return hazards


def registers_timeline(scripts: list[ScriptText]) -> bool:
    return any("__timelines" in script.text for script in scripts)
