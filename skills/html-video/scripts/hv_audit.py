"""Offline asset and composition-contract audit for a Hyperframes project.

The audit walks every static reference reachable from the entry document and
rejects anything a renderer could not reproduce from the project directory:
remote resources, path or symlink escapes, missing files, case mismatches and
reference cycles. It also validates the explicit composition contract (frame
size, duration, clip timing), the font policy and user-declared provenance.

This is a static reference audit, not a sandbox. Script-computed URLs and
network calls cannot be proven absent; they are reported as warnings and the
render must run with network isolation enforced outside this tool.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import math
import os
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import unquote

from hv_provenance import FONT_EXTENSIONS, PROVENANCE_FILE, Entry, read_provenance
from hv_scan import (
    CssText,
    HtmlScan,
    Ref,
    collect_custom_props,
    normalize_family,
    registers_timeline,
    scan_css_motion,
    scan_css_refs,
    scan_fonts,
    scan_html,
    scan_js_refs,
    scan_script,
)

Severity = Literal["error", "warning", "info"]

HTML_EXTENSIONS = (".html", ".htm")
CSS_EXTENSIONS = (".css",)
SCRIPT_EXTENSIONS = (".js", ".mjs")
_HTML_LIKE_EXTENSIONS = (*HTML_EXTENSIONS, ".xhtml", ".svg")
MEDIA_TAGS = frozenset({"video", "audio", "img"})
_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
_RELATIVE_START = re.compile(
    r"^([A-Za-z_][\w-]*)\s*(?:([+-])\s*((?:\d+(?:\.\d*)?|\.\d+)))?$"
)
_DIMENSION = re.compile(r"^[1-9]\d{0,4}$")
_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*):")
_REMOTE_SCHEMES = frozenset({"http", "https", "ftp", "ws", "wss"})
TIMING_EPSILON = 0.01


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Severity
    message: str
    file: str = ""
    line: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "file": self.file,
            "line": self.line,
        }


@dataclass(frozen=True)
class Asset:
    path: str
    kind: Literal["document", "stylesheet", "script", "asset"]
    real: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Clip:
    id: str
    start: float
    end: float | None


@dataclass(frozen=True)
class Composition:
    width: int
    height: int
    duration: float
    clips: tuple[Clip, ...]
    has_text: bool
    animated: bool


@dataclass
class AuditResult:
    entry: str
    findings: list[Finding] = field(default_factory=lambda: list[Finding]())
    assets: dict[str, Asset] = field(default_factory=lambda: dict[str, Asset]())
    extra_files: dict[str, Asset] = field(default_factory=lambda: dict[str, Asset]())
    composition: Composition | None = None
    has_motion_sidecar: bool = False

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def files(self) -> dict[str, Asset]:
        """Every file that belongs to the deliverable source, keyed by project path."""
        return {**self.assets, **self.extra_files}

    def closure_sha256(self) -> str:
        digest = hashlib.sha256()
        for path, asset in sorted(self.files.items()):
            digest.update(f"{path}\0{asset.sha256}\n".encode())
        return digest.hexdigest()


# --------------------------------------------------------------------------
# Reference classification and resolution
# --------------------------------------------------------------------------

Classification = Literal[
    "empty", "fragment", "data", "remote", "file_url", "unsupported_scheme",
    "absolute", "invalid_path", "relative",
]  # fmt: skip


def classify_ref(url: str) -> Classification:
    value = url.strip()
    if not value:
        return "empty"
    if value.startswith("#"):
        return "fragment"
    if value.startswith("//"):
        return "remote"
    scheme = _SCHEME.match(value)
    if scheme:
        name = scheme.group(1).lower()
        if len(name) == 1:
            return "absolute"  # Windows drive letter
        if name == "data":
            return "data"
        if name in _REMOTE_SCHEMES:
            return "remote"
        if name == "file":
            return "file_url"
        return "unsupported_scheme"
    if value.startswith("/"):
        return "absolute"
    if "\\" in value:
        return "invalid_path"
    return "relative"


def data_uri_valid(url: str) -> bool:
    match = re.match(r"^data:([^,]*),(.*)$", url.strip(), re.S | re.I)
    if match is None:
        return False
    if match.group(1).lower().endswith(";base64"):
        payload = re.sub(r"\s+", "", unquote(match.group(2)))
        try:
            base64.b64decode(payload.encode("ascii"), validate=True)
        except (binascii.Error, UnicodeEncodeError):
            return False
    return True


ResolveCode = Literal[
    "ok", "self", "path_escape", "missing_asset", "case_mismatch",
    "symlink_escape", "not_a_file", "invalid_path",
]  # fmt: skip


def resolve_local(root: Path, from_rel: str, url: str) -> tuple[ResolveCode, str]:
    """Resolve a relative reference against the referencing file inside ``root``.

    Returns a result code and the lexical project-relative POSIX path.
    """
    path_part = re.split(r"[?#]", url.strip(), maxsplit=1)[0]
    if not path_part:
        return "self", from_rel
    decoded = unquote(path_part)
    if "\x00" in decoded or "\\" in decoded:
        return "invalid_path", decoded
    rel = posixpath.normpath(posixpath.join(posixpath.dirname(from_rel), decoded))
    if rel == ".." or rel.startswith("../") or rel.startswith("/"):
        return "path_escape", rel
    if rel == ".":
        return "not_a_file", rel
    current = root
    for part in rel.split("/"):
        try:
            names = os.listdir(current)
        except OSError:
            return "missing_asset", rel
        if part not in names:
            folded = part.casefold()
            return (
                "case_mismatch"
                if any(n.casefold() == folded for n in names)
                else "missing_asset"
            ), rel
        current = current / part
    real = current.resolve()
    if not real.is_relative_to(root.resolve()):
        return "symlink_escape", rel
    if not real.exists():
        return "missing_asset", rel
    if not real.is_file():
        return "not_a_file", rel
    return "ok", rel


def _kind(rel: str) -> Literal["document", "stylesheet", "script", "asset"]:
    lowered = rel.lower()
    if lowered.endswith(HTML_EXTENSIONS):
        return "document"
    if lowered.endswith(CSS_EXTENSIONS):
        return "stylesheet"
    if lowered.endswith(SCRIPT_EXTENSIONS):
        return "script"
    return "asset"


_HINT_KINDS: dict[str, Literal["document", "stylesheet", "script", "asset"]] = {
    "script": "script",
    "module": "script",
    "style": "stylesheet",
    "composition": "document",
}


def _route(rel: str, hint: str) -> Literal["html", "css", "js"] | None:
    """How a followed file is scanned: by its loading context, then by extension."""
    if hint == "composition":
        return "html"
    if hint in ("script", "module"):
        return "js"
    if hint == "style":
        return "css"
    lowered = rel.lower()
    if lowered.endswith(_HTML_LIKE_EXTENSIONS):
        return "html"
    if lowered.endswith(CSS_EXTENSIONS):
        return "css"
    if lowered.endswith(SCRIPT_EXTENSIONS):
        return "js"
    return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------
# Audit
# --------------------------------------------------------------------------

_REF_MESSAGES: dict[str, str] = {
    "remote": "remote resource {url!r}: render-critical resources must be local files",
    "file_url": "file: URL {url!r} escapes the project; use a project-relative path",
    "unsupported_scheme": "unsupported scheme in {url!r}",
    "absolute": "absolute path {url!r}; use a project-relative path",
    "invalid_path": "invalid path {url!r} (backslash or NUL)",
}
_RESOLVE_MESSAGES: dict[str, str] = {
    "path_escape": "reference {url!r} escapes the project directory",
    "missing_asset": "referenced file {url!r} does not exist",
    "case_mismatch": "reference {url!r} differs in letter case from the file on disk (breaks on case-sensitive systems)",
    "symlink_escape": "reference {url!r} resolves through a symlink to outside the project",
    "not_a_file": "reference {url!r} is not a regular file",
    "invalid_path": "invalid path {url!r}",
}
_REF_CODES: dict[str, str] = {
    "remote": "remote_resource",
    "file_url": "absolute_path",
    "unsupported_scheme": "unsupported_scheme",
    "absolute": "absolute_path",
    "invalid_path": "invalid_path",
}


_OPAQUE_DATA_KINDS = frozenset({"script", "module", "style", "composition", "document"})
_FONT_PROBLEMS: dict[str, str] = {
    "font_dynamic": "font-family {detail!r} depends on var(). Write a provisioned family literally; static extraction cannot prove CSS scope or inheritance",
    "font_shorthand_unsupported": "font shorthand {detail!r} has no family list the audit can read; declare font-family separately with a provisioned family",
    "font_system_keyword": "font: {detail} selects an operating-system font that differs per machine; name a provisioned family instead",
}
_HAZARD_MESSAGES: dict[str, str] = {
    "nondeterministic_api": "{snippet} reads the wall clock, timers or unseeded randomness; frames must depend only on the seek time",
    "page_clock_animation": "{snippet}: Web Animations run on the page clock and are not seeked; use CSS keyframe animations or a registered timeline",
    "dynamic_network_api": "{snippet}: runtime network, worker or dynamic loading cannot be proven absent by static audit; enforce network isolation at render time",
    "remote_url_literal": "remote URL literal {snippet!r} in script; if it is fetched at runtime the render is not offline",
}


class _Audit:
    def __init__(self, root: Path, entry: str) -> None:
        self.root = root
        self.result = AuditResult(entry=entry)
        self.stack: list[str] = []
        self.done: set[str] = set()
        self.scans: dict[str, HtmlScan] = {}
        self.css_by_file: dict[str, list[CssText]] = {}
        self.script_findings_seen: set[tuple[str, str, int]] = set()
        self.font_assets: dict[str, tuple[str, int]] = {}
        self.import_map: list[tuple[str, str, str, int]] = []
        self.bare: list[tuple[str, Ref]] = []
        self.bare_done = 0

    def add(
        self, code: str, severity: Severity, message: str, file: str = "", line: int = 0
    ) -> None:
        self.result.findings.append(Finding(code, severity, message, file, line))

    # -- registration -----------------------------------------------------

    def register(self, rel: str, hint: str = "") -> Asset:
        existing = self.result.assets.get(rel)
        if existing is not None:
            return existing
        path = self.root / rel
        real = path.resolve()
        kind = _HINT_KINDS.get(hint) or _kind(rel)
        asset = Asset(
            path=rel,
            kind=kind,
            real=real.relative_to(self.root.resolve()).as_posix(),
            size=real.stat().st_size,
            sha256=sha256_file(real),
        )
        self.result.assets[rel] = asset
        return asset

    # -- reference handling ----------------------------------------------

    def handle_refs(
        self, file: str, refs: list[Ref], html_ids: set[str] | None
    ) -> None:
        for ref in refs:
            if ref.kind == "bare":
                self.bare.append((file, ref))
                continue
            kind = classify_ref(ref.url)
            if kind == "empty":
                self.add(
                    "empty_reference",
                    "warning",
                    f"empty reference in {ref.source}",
                    file,
                    ref.line,
                )
            elif kind == "fragment":
                if html_ids is not None and ref.url.strip()[1:] not in html_ids:
                    self.add(
                        "fragment_missing",
                        "error",
                        f"{ref.url!r} has no matching id in {file}",
                        file,
                        ref.line,
                    )
            elif kind == "data":
                if not data_uri_valid(ref.url):
                    self.add(
                        "invalid_data_uri",
                        "error",
                        f"malformed data: URI in {ref.source}",
                        file,
                        ref.line,
                    )
                elif ref.kind == "font":
                    self.add(
                        "font_data_uri",
                        "error",
                        "a data: URI font has no file to carry a licence or provenance declaration; use a local font file added with `fonts add`",
                        file,
                        ref.line,
                    )
                elif ref.kind in _OPAQUE_DATA_KINDS:
                    self.add(
                        "opaque_data_document",
                        "error",
                        f"data: URI in {ref.source} carries a document, script or stylesheet the static audit cannot follow; use a local file",
                        file,
                        ref.line,
                    )
            elif kind != "relative":
                self.add(
                    _REF_CODES[kind],
                    "error",
                    _REF_MESSAGES[kind].format(url=ref.url[:120]),
                    file,
                    ref.line,
                )
            else:
                self.follow(file, ref)

    def follow(self, file: str, ref: Ref) -> None:
        code, rel = resolve_local(self.root, file, ref.url)
        if code == "self":
            return
        if code != "ok":
            self.add(
                code,
                "error",
                _RESOLVE_MESSAGES[code].format(url=ref.url[:120]),
                file,
                ref.line,
            )
            return
        if rel.lower().endswith(".svgz"):
            self.add(
                "unscannable_document",
                "error",
                f"{rel} is compressed SVG; the static audit cannot read its references. Decompress it to .svg",
                file,
                ref.line,
            )
        asset = self.register(rel, ref.kind)
        if ref.kind == "font":
            self.font_assets.setdefault(rel, (file, ref.line))
        route = _route(asset.path, ref.kind)
        if route is not None:
            self.visit(rel, route)

    # -- bare module specifiers --------------------------------------------

    def resolve_bare_specifiers(self) -> None:
        """Resolve bare ``import "x"`` specifiers through the project's import maps.

        Runs after traversal because the import map may live in a different
        document than the module that uses it. Following a mapped file can
        reveal more bare specifiers, so the list is drained until it stops
        growing. Every scope's mappings are accepted for every importer, a
        deliberate over-approximation of scope matching.
        """
        while self.bare_done < len(self.bare):
            file, ref = self.bare[self.bare_done]
            self.bare_done += 1
            target = self._mapped(ref.url)
            if target is None:
                self.add(
                    "unresolved_module_specifier",
                    "error",
                    f"bare module specifier {ref.url!r} cannot be resolved offline; map it to a local file in an import map or use a relative path",
                    file,
                    ref.line,
                )
            elif target[2]:  # prefix mapping: the exact address was already followed
                self.handle_refs(
                    target[0],
                    [Ref(target[1] + target[2], target[3], "importmap", "module")],
                    None,
                )

    def _mapped(self, spec: str) -> tuple[str, str, str, int] | None:
        best: tuple[str, str, str, int] | None = None
        best_len = -1
        for key, address, file, line in self.import_map:
            if key == spec:
                return (file, address, "", line)
            if key.endswith("/") and spec.startswith(key) and len(key) > best_len:
                best, best_len = (file, address, spec[len(key) :], line), len(key)
        return best

    # -- traversal --------------------------------------------------------

    def visit(self, rel: str, kind: Literal["html", "css", "js"]) -> None:
        if rel in self.stack:
            chain = " -> ".join([*self.stack[self.stack.index(rel) :], rel])
            self.add("reference_cycle", "error", f"reference cycle: {chain}", rel)
            return
        if rel in self.done:
            return
        self.stack.append(rel)
        try:
            text = (self.root / rel).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            self.add("not_utf8", "error", f"{rel} is not valid UTF-8 text", rel)
        else:
            if kind == "html":
                self._visit_document(rel, text)
            elif kind == "css":
                self.css_by_file[rel] = [CssText(1, text)]
                self.handle_refs(rel, scan_css_refs(text), None)
            else:
                self.handle_refs(rel, scan_js_refs(text), None)
                self.script_hazards(rel, text, 1)
        finally:
            self.stack.pop()
            self.done.add(rel)

    def _visit_document(self, rel: str, text: str) -> None:
        scan = scan_html(text)
        self.scans[rel] = scan
        self.css_by_file[rel] = scan.all_css()
        # ``srcdoc`` documents resolve relative references against the parent
        # document, so every nested part is audited as if it were part of ``rel``.
        for part in scan.walk():
            self.handle_refs(rel, part.refs, None)
            self.handle_refs(rel, part.fragment_refs, part.ids)
            for css in part.css:
                self.handle_refs(
                    rel,
                    [
                        r
                        for r in scan_css_refs(css.text, css.line)
                        if r.url.startswith("#")
                    ],
                    part.ids,
                )
            for script in [*part.scripts, *part.handlers]:
                self.script_hazards(rel, script.text, script.line)
            for key, address, line in part.import_map:
                self.import_map.append((key, address, rel, line))
            for item in part.unsupported:
                self.add(item.code, "error", item.message, rel, item.line)

    def script_hazards(self, file: str, text: str, base_line: int) -> None:
        for hazard in scan_script(text, base_line):
            key = (file, hazard.code, hazard.line)
            if key in self.script_findings_seen:
                continue
            self.script_findings_seen.add(key)
            self.add(
                hazard.code,
                "warning",
                _HAZARD_MESSAGES[hazard.code].format(snippet=hazard.snippet),
                file,
                hazard.line,
            )


def _number(value: str | None) -> float | None:
    if value is None or not _NUMBER.fullmatch(value.strip()):
        return None
    number = float(value.strip())
    return number if math.isfinite(number) else None


def audit_project(
    root: Path, entry: str = "index.html", require_provenance: bool = False
) -> AuditResult:
    root = root.resolve()
    audit = _Audit(root, entry)
    result = audit.result
    code, rel = resolve_local(root, "", entry)
    if code != "ok":
        audit.add(
            "missing_entry",
            "error",
            f"entry document {entry!r} is not usable ({code})",
            entry,
        )
        return result
    audit.register(rel)
    audit.visit(rel, "html")
    audit.resolve_bare_specifiers()
    entry_scan = audit.scans.get(rel)
    if entry_scan is not None:
        _check_base(audit, rel, entry_scan)
    _check_css(audit, rel)
    if entry_scan is not None:
        _check_composition(audit, rel, entry_scan)
    _check_duplicates(audit)
    _check_provenance(audit, rel, require_provenance)
    return result


def _check_base(audit: _Audit, rel: str, scan: HtmlScan) -> None:
    for element in scan.elements:
        if element.tag == "base" and "href" in element.attrs:
            audit.add(
                "base_href",
                "error",
                "<base href> changes reference resolution and is not supported",
                rel,
                element.line,
            )


def _check_css(audit: _Audit, entry_rel: str) -> None:
    all_blocks = [block for blocks in audit.css_by_file.values() for block in blocks]
    custom = collect_custom_props(all_blocks)
    scans = {
        file: scan_fonts(blocks, custom) for file, blocks in audit.css_by_file.items()
    }
    declared = {name for scan in scans.values() for name in scan.declared}
    # Hyperframes compileForRender reads @font-face only from the rendered
    # HTML's own <style> elements; a linked or imported stylesheet is invisible
    # to it, so a family the page uses must be declared inline in the entry.
    entry_scan = audit.scans.get(entry_rel)
    inline_declared = (
        set(scan_fonts(entry_scan.css, custom).declared) if entry_scan else set[str]()
    )
    reported: set[str] = set()
    reported_inline: set[str] = set()
    for file, scan in scans.items():
        for use in scan.uses:
            name = normalize_family(use.family)
            if name not in declared:
                if name not in reported:
                    reported.add(name)
                    audit.add(
                        "font_not_declared", "error",
                        f"font family {use.family!r} has no local @font-face. The Hyperframes compiler would fetch it from "
                        "Google Fonts or substitute a system font; add the font with `fonts add` or declare @font-face with a local file",
                        file, use.line,
                    )  # fmt: skip
            elif name not in inline_declared and name not in reported_inline:
                reported_inline.add(name)
                audit.add(
                    "font_face_not_inline", "error",
                    f"font family {use.family!r} is declared only in linked or imported CSS, which Hyperframes compileForRender does not read; "
                    f"declare its @font-face inside a <style> element of {entry_rel} (`fonts add` writes the managed <style id=\"html-video-fonts\"> block)",
                    file, use.line,
                )  # fmt: skip
        for face in scan.faces_without_url:
            audit.add(
                "font_face_no_url",
                "error",
                f"@font-face {face.family!r} has no url() source (local() is not reproducible)",
                file,
                face.line,
            )
        for face in scan.local_sources:
            audit.add(
                "font_face_local_source",
                "error",
                f"@font-face {face.family!r} lists local() before or after its url(); a machine that has that font renders it instead of the audited, licensed file. Remove every local() source",
                file,
                face.line,
            )
        for problem in scan.problems:
            audit.add(
                problem.code,
                "error",
                _FONT_PROBLEMS[problem.code].format(detail=problem.detail),
                file,
                problem.line,
            )
    motion = scan_css_motion(all_blocks)
    for line in motion.infinite:
        audit.add(
            "infinite_animation",
            "error",
            "infinite CSS animation has no finite end the renderer can seek; give a finite iteration count",
            line=line,
        )
    for line, detail in motion.unresolved:
        audit.add(
            "animation_unresolved",
            "error",
            f"animation iteration count cannot be resolved ({detail}); use finite literal numbers so the renderer can seek to the end",
            line=line,
        )
    for line in motion.transitions:
        audit.add(
            "css_transition",
            "warning",
            "CSS transitions run on the page clock and are not seeked; use keyframe animations",
            line=line,
        )


def _check_composition(audit: _Audit, rel: str, scan: HtmlScan) -> None:
    root_el = next((e for e in scan.elements if "data-composition-id" in e.attrs), None)
    if root_el is None:
        audit.add(
            "no_composition_root", "error", "no element with data-composition-id", rel
        )
        return
    attrs = root_el.attrs
    problems = False
    if _number(attrs.get("data-start")) != 0:
        audit.add(
            "root_start", "error", 'root data-start must be "0"', rel, root_el.line
        )
        problems = True
    dims: list[int] = []
    for name in ("data-width", "data-height"):
        value = attrs.get(name, "").strip()
        if not _DIMENSION.fullmatch(value):
            audit.add(
                "bad_dimension",
                "error",
                f"root {name} must be a positive integer pixel count, got {value!r}",
                rel,
                root_el.line,
            )
            problems = True
        else:
            dims.append(int(value))
            if int(value) % 2:
                audit.add(
                    "odd_dimension",
                    "warning",
                    f"{name}={value} is odd; yuv420p H.264 encoders expect even dimensions",
                    rel,
                    root_el.line,
                )
    duration = _number(attrs.get("data-duration"))
    if duration is None or duration <= 0:
        audit.add(
            "bad_duration",
            "error",
            "root data-duration must be a finite positive number of seconds",
            rel,
            root_el.line,
        )
        problems = True
    if "data-no-timeline" not in attrs and not registers_timeline(scan.scripts):
        audit.add(
            "missing_no_timeline", "error",
            "root has no window.__timelines registration and no data-no-timeline; the renderer would wait out its readiness timeout",
            rel, root_el.line,
        )  # fmt: skip
    if scan.viewport is not None and len(dims) == 2:
        match = re.search(r"width\s*=\s*(\d+).*height\s*=\s*(\d+)", scan.viewport, re.S)
        if match and (int(match.group(1)), int(match.group(2))) != (dims[0], dims[1]):
            audit.add(
                "viewport_mismatch",
                "warning",
                "viewport meta disagrees with data-width/data-height",
                rel,
            )
    clips = _check_clips(audit, rel, scan, root_el.line, duration)
    if problems or duration is None or len(dims) != 2:
        return
    motion = scan_css_motion(
        [b for blocks in audit.css_by_file.values() for b in blocks]
    )
    has_text = any(s.has_visible_text for s in audit.scans.values())
    audit.result.composition = Composition(
        width=dims[0], height=dims[1], duration=duration, clips=tuple(clips),
        has_text=has_text, animated=motion.animated or registers_timeline(scan.scripts),
    )  # fmt: skip


def _check_clips(
    audit: _Audit, rel: str, scan: HtmlScan, root_line: int, duration: float | None
) -> list[Clip]:
    seen: dict[str, int] = {}
    for element in scan.elements:
        ident = element.attrs.get("id")
        if ident:
            if ident in seen:
                audit.add(
                    "duplicate_id",
                    "error",
                    f"duplicate id {ident!r} (first on line {seen[ident]})",
                    rel,
                    element.line,
                )
            else:
                seen[ident] = element.line
    timed = [
        e
        for e in scan.elements
        if "data-start" in e.attrs and "data-composition-id" not in e.attrs
    ]
    by_id = {e.attrs["id"]: e for e in timed if e.attrs.get("id")}
    resolved: dict[str, tuple[float, float | None] | None] = {}

    def length(element_attrs: dict[str, str], tag: str, line: int) -> float | None:
        raw = element_attrs.get("data-duration")
        if raw is None:
            if tag not in MEDIA_TAGS:
                audit.add(
                    "clip_missing_duration",
                    "error",
                    "timed clip needs data-duration",
                    rel,
                    line,
                )
            return None
        value = _number(raw)
        if value is None or value <= 0:
            audit.add(
                "bad_duration",
                "error",
                f"data-duration must be a finite positive number, got {raw!r}",
                rel,
                line,
            )
            return None
        return value

    def resolve(
        ident: str, visiting: tuple[str, ...]
    ) -> tuple[float, float | None] | None:
        if ident in resolved:
            return resolved[ident]
        element = by_id[ident]
        raw = element.attrs["data-start"].strip()
        start: float | None
        number = _number(raw)
        if number is not None:
            start = number
            if number < 0:
                audit.add(
                    "bad_start",
                    "error",
                    f"data-start must be >= 0, got {raw!r}",
                    rel,
                    element.line,
                )
                start = None
        else:
            match = _RELATIVE_START.fullmatch(raw)
            if match is None or re.fullmatch(r"(?i)nan|inf(?:inity)?", match.group(1)):
                audit.add(
                    "bad_start",
                    "error",
                    f"data-start {raw!r} is neither a finite number nor 'id [+/- seconds]'",
                    rel,
                    element.line,
                )
                start = None
            elif match.group(1) in visiting or match.group(1) == ident:
                audit.add(
                    "start_cycle",
                    "error",
                    f"data-start reference cycle through {match.group(1)!r}",
                    rel,
                    element.line,
                )
                start = None
            elif match.group(1) not in by_id:
                audit.add(
                    "unknown_start_reference",
                    "error",
                    f"data-start refers to unknown clip {match.group(1)!r}",
                    rel,
                    element.line,
                )
                start = None
            else:
                base = resolve(match.group(1), (*visiting, ident))
                if base is None or base[1] is None:
                    if base is not None:
                        audit.add(
                            "reference_unknown_duration",
                            "error",
                            f"{match.group(1)!r} has no known duration to start after",
                            rel,
                            element.line,
                        )
                    start = None
                else:
                    offset = float(match.group(3)) if match.group(3) else 0.0
                    start = base[1] + (-offset if match.group(2) == "-" else offset)
                    if start < 0:
                        audit.add(
                            "bad_start",
                            "error",
                            f"data-start {raw!r} resolves before 0",
                            rel,
                            element.line,
                        )
                        start = None
        span = length(element.attrs, element.tag, element.line)
        resolved[ident] = (
            None if start is None else (start, None if span is None else start + span)
        )
        return resolved[ident]

    clips: list[Clip] = []
    for element in timed:
        ident = element.attrs.get("id")
        if not ident:
            audit.add(
                "clip_missing_id",
                "error",
                "timed clip needs a stable id",
                rel,
                element.line,
            )
            continue
        if by_id[ident] is not element:
            continue
        timing = resolve(ident, ())
        if timing is None:
            continue
        start, end = timing
        clips.append(Clip(ident, start, end))
        if duration is not None:
            if start >= duration - TIMING_EPSILON:
                audit.add(
                    "clip_after_end",
                    "warning",
                    f"clip {ident!r} starts at {start:g}s, at or after the composition end",
                    rel,
                    element.line,
                )
            elif end is not None and end > duration + TIMING_EPSILON:
                audit.add(
                    "clip_past_root",
                    "warning",
                    f"clip {ident!r} ends at {end:g}s, past the {duration:g}s composition",
                    rel,
                    element.line,
                )
    return clips


def _check_duplicates(audit: _Audit) -> None:
    by_real: dict[str, list[str]] = {}
    for asset in audit.result.assets.values():
        by_real.setdefault(asset.real, []).append(asset.path)
    for paths in by_real.values():
        if len(paths) > 1:
            audit.add(
                "duplicate_asset_alias",
                "info",
                f"one file is referenced under several paths: {', '.join(sorted(paths))}",
            )
    by_hash: dict[str, set[str]] = {}
    for asset in audit.result.assets.values():
        if asset.kind == "asset":
            by_hash.setdefault(asset.sha256, set()).add(asset.real)
    for reals in by_hash.values():
        if len(reals) > 1:
            audit.add(
                "duplicate_content",
                "info",
                f"distinct files have identical content: {', '.join(sorted(reals))}",
            )


def _check_provenance(audit: _Audit, entry_rel: str, required: bool) -> None:
    root = audit.root
    # Resolve both side files before reading them: a symlink to outside the
    # project must be reported, never read or registered.
    provenance_code, _ = resolve_local(root, "", PROVENANCE_FILE)
    entries: list[Entry] = []
    if provenance_code == "ok":
        entries, problems = read_provenance(root)
        for problem in problems:
            audit.add("provenance_invalid", "error", problem, PROVENANCE_FILE)
    elif provenance_code != "missing_asset":
        audit.add(
            provenance_code,
            "error",
            _RESOLVE_MESSAGES[provenance_code].format(url=PROVENANCE_FILE),
            PROVENANCE_FILE,
        )
    declared: dict[str, Entry] = {}
    for item in entries:
        code, rel = resolve_local(root, "", item.path)
        if code != "ok":
            audit.add(
                "provenance_missing_file",
                "error",
                f"declared asset {item.path!r} is not usable ({code})",
                PROVENANCE_FILE,
            )
            continue
        declared[rel] = item
        asset = _extra(audit, rel)
        if item.sha256 is not None and item.sha256 != asset.sha256:
            audit.add(
                "provenance_hash_mismatch",
                "error",
                f"{rel} no longer matches its declared sha256",
                PROVENANCE_FILE,
            )
        if item.license_file is not None:
            lcode, lrel = resolve_local(root, "", item.license_file)
            if lcode != "ok":
                audit.add(
                    "provenance_license_missing",
                    "error",
                    f"licence file {item.license_file!r} for {rel} is not usable ({lcode})",
                    PROVENANCE_FILE,
                )
            else:
                _extra(audit, lrel)
    if provenance_code == "ok":
        _extra(audit, PROVENANCE_FILE)
    sidecar = posixpath.splitext(entry_rel)[0] + ".motion.json"
    sidecar_code, _ = resolve_local(root, "", sidecar)
    if sidecar_code == "ok":
        _extra(audit, sidecar)
        audit.result.has_motion_sidecar = True
    elif sidecar_code != "missing_asset":
        audit.add(
            sidecar_code,
            "error",
            _RESOLVE_MESSAGES[sidecar_code].format(url=sidecar),
            sidecar,
        )
    if not required:
        return
    for rel, asset in audit.result.assets.items():
        is_font = rel in audit.font_assets or rel.lower().endswith(FONT_EXTENSIONS)
        if asset.kind in ("document", "stylesheet") and rel not in audit.font_assets:
            continue
        declaration = declared.get(rel)
        if declaration is None:
            audit.add(
                "provenance_undeclared",
                "error",
                f"{rel} has no provenance declaration (source and license) in {PROVENANCE_FILE}",
                rel,
            )
        elif is_font and declaration.license_file is None:
            audit.add(
                "font_license_missing",
                "error",
                f"font {rel} has no licence file recorded",
                PROVENANCE_FILE,
            )


def _extra(audit: _Audit, rel: str) -> Asset:
    existing = audit.result.assets.get(rel) or audit.result.extra_files.get(rel)
    if existing is not None:
        return existing
    real = (audit.root / rel).resolve()
    asset = Asset(
        rel,
        _kind(rel),
        real.relative_to(audit.root).as_posix(),
        real.stat().st_size,
        sha256_file(real),
    )
    audit.result.extra_files[rel] = asset
    return asset
