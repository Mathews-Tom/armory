"""Composition contract, font policy, motion hazards and provenance declarations."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest

from helpers import audit, codes, page, project, template_project, write
from hv_audit import AuditResult
from hv_config import TEMPLATES_DIR
from hv_provenance import PROVENANCE_FILE


def _has(result: AuditResult, code: str, severity: str = "error") -> bool:
    return code in codes(result, severity)


# -- explicit frame size, duration and timing --------------------------------


def test_valid_composition_exposes_resolved_timing(tmp_path: Path) -> None:
    body = '<p id="a" data-start="0" data-duration="2">A</p><p id="b" data-start="a + 0.5" data-duration="1">B</p>'
    result = audit(project(tmp_path / "p", page(body)))
    assert result.ok, result.findings
    comp = result.composition
    assert comp is not None
    assert (comp.width, comp.height, comp.duration) == (1920, 1080, 4.0)
    assert [(c.id, c.start, c.end) for c in comp.clips] == [
        ("a", 0.0, 2.0),
        ("b", 2.5, 3.5),
    ]
    assert comp.has_text and not comp.animated


@pytest.mark.parametrize("duration", ["NaN", "Infinity", "1e999", "-1", "0", "abc", ""])
def test_root_duration_must_be_a_finite_positive_plain_number(
    tmp_path: Path, duration: str
) -> None:
    result = audit(project(tmp_path / "p", page(duration=duration)))
    assert _has(result, "bad_duration")
    assert result.composition is None


@pytest.mark.parametrize("width", ["0", "19.5", "1920px", "-4", "", "123456"])
def test_frame_dimensions_must_be_positive_integers(tmp_path: Path, width: str) -> None:
    html = page().replace('data-width="1920"', f'data-width="{width}"')
    assert _has(audit(project(tmp_path / "p", html)), "bad_dimension")


def test_odd_dimensions_warn(tmp_path: Path) -> None:
    html = page().replace('data-width="1920"', 'data-width="1919"')
    assert _has(audit(project(tmp_path / "p", html)), "odd_dimension", "warning")


def test_clip_start_expressions_resolve_or_fail_precisely(tmp_path: Path) -> None:
    cases = {
        "unknown": (
            '<p id="a" data-start="ghost" data-duration="1">A</p>',
            "unknown_start_reference",
        ),
        "cycle": (
            '<p id="a" data-start="b" data-duration="1">A</p><p id="b" data-start="a" data-duration="1">B</p>',
            "start_cycle",
        ),
        "negative": (
            '<p id="a" data-start="0" data-duration="1">A</p><p id="b" data-start="a - 5" data-duration="1">B</p>',
            "bad_start",
        ),
        "nonfinite": (
            '<p id="a" data-start="NaN" data-duration="1">A</p>',
            "bad_start",
        ),
        "no_duration_ref": (
            '<img id="m" data-start="0"><p id="b" data-start="m" data-duration="1">B</p>',
            "reference_unknown_duration",
        ),
        "no_duration": ('<p id="a" data-start="0">A</p>', "clip_missing_duration"),
        "no_id": ('<p data-start="0" data-duration="1">A</p>', "clip_missing_id"),
        "dup": (
            '<p id="a" data-start="0" data-duration="1">A</p><p id="a" data-start="1" data-duration="1">B</p>',
            "duplicate_id",
        ),
    }
    for name, (body, expected) in cases.items():
        result = audit(project(tmp_path / name, page(body)))
        assert _has(result, expected), (name, codes(result))


def test_clips_outside_the_composition_warn(tmp_path: Path) -> None:
    body = '<p id="a" data-start="3" data-duration="5">A</p><p id="b" data-start="9" data-duration="1">B</p>'
    result = audit(project(tmp_path / "p", page(body)))
    assert _has(result, "clip_past_root", "warning") and _has(
        result, "clip_after_end", "warning"
    )


def test_timeline_free_root_requires_data_no_timeline_unless_a_timeline_is_registered(
    tmp_path: Path,
) -> None:
    bare = page().replace(" data-no-timeline", "")
    assert _has(audit(project(tmp_path / "a", bare)), "missing_no_timeline")
    registered = page("<script>window.__timelines = {main: tl};</script>").replace(
        " data-no-timeline", ""
    )
    assert not _has(audit(project(tmp_path / "b", registered)), "missing_no_timeline")


def test_infinite_animation_is_an_error_and_transitions_warn(tmp_path: Path) -> None:
    head = "<style>@keyframes k{to{opacity:0}} .a{animation:k 1s infinite} .b{animation-iteration-count:infinite} .c{transition:opacity .3s} .d{transition:none}</style>"
    result = audit(project(tmp_path / "p", page(head=head)))
    assert codes(result, "error").count("infinite_animation") == 2
    assert codes(result, "warning").count("css_transition") == 1
    assert result.composition is not None and result.composition.animated


def test_animation_is_detected_across_css_blocks_and_style_attributes(
    tmp_path: Path,
) -> None:
    body = '<p id="a" data-start="0" data-duration="1" style="animation: spin 1s both">A</p>'
    root = project(
        tmp_path / "p",
        page(body, head='<link rel="stylesheet" href="m.css">'),
        {"m.css": "@keyframes spin{to{opacity:0}}"},
    )
    result = audit(root)
    assert result.ok, result.findings
    assert result.composition is not None and result.composition.animated


@pytest.mark.parametrize(
    "declaration",
    [
        "-webkit-animation: s 1s infinite",
        "-webkit-animation-iteration-count: infinite",
        "animation: s 1s var(--n)",
        "animation: s 1s infinite, t 2s 3",
    ],
)
def test_infinite_iteration_counts_are_rejected_in_every_spelling(
    tmp_path: Path, declaration: str
) -> None:
    head = (
        "<style>@keyframes s{to{opacity:0}} @keyframes t{to{opacity:0}} :root{--n:infinite}"
        f" .a{{{declaration}}}</style>"
    )
    result = audit(project(tmp_path / "p", page(head=head)))
    assert "infinite_animation" in codes(result, "error")
    assert result.composition is not None and result.composition.animated


@pytest.mark.parametrize(
    "declaration",
    [
        ":root{--n:2} .b{--n:3} .a{animation: s 1s var(--n)}",
        ".a{animation: s 1s var(--undefined)}",
        ".a{animation: s 1s calc(1 + 1)}",
        ".a{animation-iteration-count: calc(2 * 3)}",
    ],
)
def test_unresolvable_iteration_counts_are_rejected(
    tmp_path: Path, declaration: str
) -> None:
    head = f"<style>@keyframes s{{to{{opacity:0}}}} {declaration}</style>"
    result = audit(project(tmp_path / "p", page(head=head)))
    assert "animation_unresolved" in codes(result, "error")


def test_a_keyframe_named_infinite_scroll_is_not_an_infinite_animation(
    tmp_path: Path,
) -> None:
    head = "<style>@keyframes infinite-scroll{to{opacity:0}} .a{animation: infinite-scroll 2s both}</style>"
    result = audit(project(tmp_path / "p", page(head=head)))
    assert result.ok, result.findings
    assert result.composition is not None and result.composition.animated


# -- fonts ---------------------------------------------------------------------


def test_named_family_without_local_font_face_fails_loudly(tmp_path: Path) -> None:
    result = audit(
        project(
            tmp_path / "p",
            page(head="<style>p{font-family:'Inter', sans-serif}</style>"),
        )
    )
    finding = next(f for f in result.findings if f.code == "font_not_declared")
    assert "Google Fonts" in finding.message


def test_generic_only_stacks_and_inline_declared_families_pass(tmp_path: Path) -> None:
    assert audit(
        project(tmp_path / "g", page(head="<style>p{font-family:serif}</style>"))
    ).ok
    css = '@font-face{font-family:"HV  Text";src:url("f.woff2") format("woff2")}'
    root = project(
        tmp_path / "d",
        page(head=f'<style>{css} p{{font-family:"hv text", sans-serif}}</style>'),
        {"f.woff2": b"wOF2"},
    )
    assert audit(root).ok


def test_font_face_must_have_a_local_url_source(tmp_path: Path) -> None:
    local_only = page(
        head='<style>@font-face{font-family:"X";src:local("Arial")} p{font-family:X}</style>'
    )
    assert _has(audit(project(tmp_path / "l", local_only)), "font_face_no_url")
    remote = page(
        head='<style>@font-face{font-family:"X";src:url(https://f.example/x.woff2)} p{font-family:X}</style>'
    )
    assert _has(audit(project(tmp_path / "r", remote)), "remote_resource")


@pytest.mark.parametrize(
    ("css", "code"),
    [
        ('h1{font: var(--size)/1.1 "Inter"}', "font_not_declared"),
        ("h2{font: calc(2rem + 4px) Roboto}", "font_not_declared"),
        ('p{font:italic 700 20px/1.2 "Nope", serif}', "font_not_declared"),
        (":root{--fam:Zed} h1{font:20px var(--fam)}", "font_dynamic"),
        (':root{--f:"Zed", serif} p{font-family:var(--f)}', "font_dynamic"),
        ("h1{font-family:var(--missing, Inter)}", "font_dynamic"),
        ("h3{font: caption}", "font_system_keyword"),
        ("h3{font: status-bar}", "font_system_keyword"),
        ("h3{font: 20px}", "font_shorthand_unsupported"),
        ("h1{font-family:var(--missing)}", "font_dynamic"),
        (
            '.t{--f:"Comic Neue"} :root{--f:"HV Text"} h1{font-family:var(--f)}',
            "font_dynamic",
        ),
    ],
)
def test_unreadable_or_unsupported_font_declarations_fail_instead_of_passing(
    tmp_path: Path, css: str, code: str
) -> None:
    result = audit(project(tmp_path / "p", page(head=f"<style>{css}</style>")))
    assert _has(result, code), (css, codes(result))


def test_font_family_variable_defined_in_another_scope_is_not_proven(
    tmp_path: Path,
) -> None:
    face = '@font-face{font-family:"X";src:url("x.woff2") format("woff2")}'
    css = f'{face} .hidden{{--f:"X", serif}} p{{font-family:var(--f)}}'
    root = project(
        tmp_path / "p",
        page("<p>Visible text</p>", head=f"<style>{css}</style>"),
        {"x.woff2": b"wOF2"},
    )
    assert _has(audit(root), "font_dynamic")


def test_font_face_may_not_use_local_sources_even_with_a_url_fallback(
    tmp_path: Path,
) -> None:
    css = '<style>@font-face{font-family:"X";src:local("Arial"), url(x.woff2)} p{font-family:X}</style>'
    result = audit(project(tmp_path / "p", page(head=css), {"x.woff2": b"wOF2"}))
    assert _has(result, "font_face_local_source")


def test_data_uri_fonts_are_rejected_because_nothing_can_carry_their_licence(
    tmp_path: Path,
) -> None:
    payload = base64.b64encode(b"wOF2").decode()
    css = f'@font-face{{font-family:"X";src:url(data:font/woff2;base64,{payload}) format("woff2")}} p{{font-family:X}}'
    result = audit(project(tmp_path / "p", page(head=f"<style>{css}</style>")))
    assert _has(result, "font_data_uri")


def test_a_font_declared_only_in_linked_or_imported_css_is_invisible_to_the_compiler(
    tmp_path: Path,
) -> None:
    face = '@font-face{font-family:"X";src:url("x.woff2") format("woff2")}'
    files: dict[str, str | bytes] = {"f.css": face, "x.woff2": b"wOF2"}
    linked = project(
        tmp_path / "linked",
        page(
            head='<link rel="stylesheet" href="f.css"><style>p{font-family:X}</style>'
        ),
        files,
    )
    result = audit(linked)
    finding = next(f for f in result.findings if f.code == "font_face_not_inline")
    assert "index.html" in finding.message
    assert "font_not_declared" not in codes(result)
    imported = project(
        tmp_path / "imported",
        page(head='<style>@import "f.css"; p{font-family:X}</style>'),
        files,
    )
    assert _has(audit(imported), "font_face_not_inline")
    inline = project(
        tmp_path / "inline",
        page(head=f"<style>{face} p{{font-family:X}}</style>"),
        files,
    )
    assert audit(inline).ok


# -- provenance ----------------------------------------------------------------


def _provenance(root: Path, *entries: dict[str, object]) -> None:
    write(root, PROVENANCE_FILE, json.dumps({"version": 1, "assets": list(entries)}))


def test_every_non_document_asset_needs_a_declaration_when_required(
    tmp_path: Path,
) -> None:
    root = project(tmp_path / "p", page('<img src="a.png">'), {"a.png": b"1"})
    assert audit(root).ok  # authoring does not demand it
    assert _has(audit(root, require_provenance=True), "provenance_undeclared")
    _provenance(root, {"path": "a.png", "source": "original", "license": "CC0-1.0"})
    assert audit(root, require_provenance=True).ok


def test_provenance_declarations_are_validated_against_the_files(
    tmp_path: Path,
) -> None:
    root = project(tmp_path / "p", page('<img src="a.png">'), {"a.png": b"1"})
    _provenance(
        root,
        {
            "path": "a.png",
            "source": "s",
            "license": "MIT",
            "sha256": "0" * 64,
            "license_file": "LICENSE.txt",
        },
    )
    result = audit(root, require_provenance=True)
    assert {"provenance_hash_mismatch", "provenance_license_missing"} <= set(
        codes(result, "error")
    )
    _provenance(root, {"path": "gone.png", "source": "s", "license": "MIT"})
    assert _has(audit(root), "provenance_missing_file")
    write(root, PROVENANCE_FILE, "{not json")
    assert _has(audit(root), "provenance_invalid")
    _provenance(root, {"path": "a.png", "source": "", "license": "MIT"})
    assert _has(audit(root), "provenance_invalid")


def test_a_font_needs_its_licence_file_recorded_for_delivery(tmp_path: Path) -> None:
    css = '<style>@font-face{font-family:"X";src:url("x.woff2") format("woff2")} p{font-family:X}</style>'
    root = project(tmp_path / "p", page(head=css), {"x.woff2": b"wOF2"})
    _provenance(root, {"path": "x.woff2", "source": "s", "license": "OFL-1.1"})
    assert _has(audit(root, require_provenance=True), "font_license_missing")


def test_font_licence_is_bound_to_the_font_face_source_not_the_extension(
    tmp_path: Path,
) -> None:
    css = '<style>@font-face{font-family:"X";src:url("f/b2.bin") format("woff2")} p{font-family:X}</style>'
    root = project(tmp_path / "p", page(head=css), {"f/b2.bin": b"wOF2"})
    _provenance(root, {"path": "f/b2.bin", "source": "s", "license": "OFL-1.1"})
    assert _has(audit(root, require_provenance=True), "font_license_missing")
    write(root, "f/OFL.txt", "licence text")
    _provenance(
        root,
        {
            "path": "f/b2.bin",
            "source": "s",
            "license": "OFL-1.1",
            "license_file": "f/OFL.txt",
        },
    )
    assert audit(root, require_provenance=True).ok


def test_provenance_and_sidecar_symlinks_leaving_the_project_are_findings_not_crashes(
    tmp_path: Path,
) -> None:
    write(tmp_path, "outside.json", json.dumps({"version": 1, "assets": []}))
    root = project(tmp_path / "p", page())
    try:
        os.symlink(tmp_path / "outside.json", root / PROVENANCE_FILE)
        os.symlink(tmp_path / "outside.json", root / "index.motion.json")
    except OSError:
        pytest.skip("symlinks unavailable")
    result = audit(root)
    escapes = sorted(f.file for f in result.findings if f.code == "symlink_escape")
    assert escapes == [PROVENANCE_FILE, "index.motion.json"]
    assert not result.has_motion_sidecar
    assert not {PROVENANCE_FILE, "index.motion.json"} & set(result.files)


# -- shipped templates ------------------------------------------------------------


@pytest.mark.parametrize(
    "name", sorted(p.name for p in TEMPLATES_DIR.iterdir() if p.is_dir())
)
def test_templates_fail_without_a_font_and_pass_with_one(
    tmp_path: Path, name: str
) -> None:
    bare = audit(template_project(tmp_path / "bare", name, with_font=False))
    assert codes(bare, "error") == ["font_not_declared"]
    root = template_project(tmp_path / "ready", name)
    result = audit(root, require_provenance=True)
    assert result.ok, result.findings
    assert not result.warnings, result.warnings
    comp = result.composition
    assert comp is not None
    assert (comp.width, comp.height) == (1920, 1080) and comp.animated and comp.has_text
    assert result.has_motion_sidecar
    assert len(comp.clips) >= 5
