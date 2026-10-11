"""Font provisioning: user-selected file, mandatory licence record, no silent fallback."""

from __future__ import annotations
import json

from pathlib import Path

import pytest

from helpers import FAKE_WOFF2, audit, write
from hv_fonts import FONTS_CSS, FontError, add_font, sniff_format
from hv_provenance import read_provenance
from hv_scan import normalize_family, scan_fonts, scan_html


def _add(project: Path, scratch: Path, **overrides: object) -> None:
    font = overrides.pop("font_file", None) or write(
        scratch, "f/Brand.woff2", FAKE_WOFF2
    )
    licence = write(scratch, "f/OFL.txt", "licence text")
    args: dict[str, object] = {
        "font_file": font,
        "family": "Brand",
        "license_id": "OFL-1.1",
        "license_file": licence,
        "source": "https://example.invalid/brand",
    }
    args.update(overrides)
    add_font(project, **args)  # type: ignore[arg-type]


@pytest.fixture
def blank(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    write(root, "assets/fonts.css", "")
    write(root, "index.html", "<!doctype html><html><head></head><body></body></html>")
    return root


@pytest.mark.parametrize(
    ("magic", "expected"),
    [
        (b"wOF2", "woff2"),
        (b"wOFF", "woff"),
        (b"OTTO", "otf"),
        (b"\x00\x01\x00\x00", "ttf"),
        (b"true", "ttf"),
    ],
)
def test_container_format_comes_from_magic_bytes_not_the_extension(
    magic: bytes, expected: str
) -> None:
    assert sniff_format(magic + b"\x00" * 8) == expected


def test_collections_and_non_fonts_are_rejected() -> None:
    with pytest.raises(FontError, match="collection"):
        sniff_format(b"ttcf\x00\x00\x00\x00")
    with pytest.raises(FontError, match="not a woff2"):
        sniff_format(b"<!doctype html>")


def test_add_font_records_provenance_licence_and_css(
    blank: Path, tmp_path: Path
) -> None:
    _add(blank, tmp_path)
    entries, problems = read_provenance(blank)
    assert problems == [] and len(entries) == 1
    entry = entries[0]
    assert (
        entry.license == "OFL-1.1"
        and entry.font is not None
        and entry.font.family == "Brand"
    )
    assert (
        entry.license_file is not None
        and (blank / entry.license_file).read_text() == "licence text"
    )
    assert (blank / entry.path).read_bytes() == FAKE_WOFF2
    css = (blank / FONTS_CSS).read_text()
    assert (
        'font-family: "HV Text"' in css
        and entry.path.removeprefix("assets/") in css
        and 'format("woff2")' in css
    )


def test_font_without_licence_declaration_is_refused(
    blank: Path, tmp_path: Path
) -> None:
    with pytest.raises(FontError, match="licence file"):
        _add(blank, tmp_path, license_file=tmp_path / "missing.txt")
    with pytest.raises(FontError, match="license-id"):
        _add(blank, tmp_path, license_id="not an id")
    with pytest.raises(FontError, match="--source"):
        _add(blank, tmp_path, source="  ")
    assert not (blank / "PROVENANCE.json").exists()


@pytest.mark.parametrize("weight", ["0", "450", "900 100", "bold", "100 200 300"])
def test_invalid_weights_are_refused(blank: Path, tmp_path: Path, weight: str) -> None:
    with pytest.raises(FontError, match="weight"):
        _add(blank, tmp_path, weight=weight)


def test_re_adding_the_same_file_is_idempotent_but_a_different_file_needs_replace(
    blank: Path, tmp_path: Path
) -> None:
    _add(blank, tmp_path)
    _add(blank, tmp_path)
    assert len(read_provenance(blank)[0]) == 1
    other = write(tmp_path, "f/Other.woff2", b"wOF2" + b"\x01" * 64)
    with pytest.raises(FontError, match="--replace"):
        _add(blank, tmp_path, font_file=other)
    old_path = read_provenance(blank)[0][0].path
    _add(blank, tmp_path, font_file=other, replace=True)
    entries = read_provenance(blank)[0]
    assert len(entries) == 1 and entries[0].path != old_path
    assert not (blank / old_path).exists()


def test_one_file_cannot_back_two_faces_but_a_range_covers_a_variable_font(
    blank: Path, tmp_path: Path
) -> None:
    _add(blank, tmp_path, weight="400")
    with pytest.raises(FontError, match="weight range"):
        _add(blank, tmp_path, weight="700")
    _add(blank, tmp_path, weight="400", replace=True)  # still one face


def test_regular_and_bold_faces_keep_distinct_font_data(
    blank: Path, tmp_path: Path
) -> None:
    bold = b"wOF2" + b"\x02" * 8
    _add(blank, tmp_path, weight="700", font_file=write(tmp_path, "f/Bold.woff2", bold))
    _add(blank, tmp_path, weight="400")
    by_weight = {
        entry.font.weight: entry for entry in read_provenance(blank)[0] if entry.font
    }
    assert set(by_weight) == {"400", "700"}
    assert (blank / by_weight["400"].path).read_bytes() == FAKE_WOFF2
    assert (blank / by_weight["700"].path).read_bytes() == bold


def test_provisioned_font_satisfies_the_audit_font_policy(
    blank: Path, tmp_path: Path
) -> None:
    html = (
        '<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="assets/fonts.css">'
        '<style>p{font-family:"HV Text",sans-serif}</style></head><body>'
        '<div id="r" data-composition-id="m" data-start="0" data-duration="2" data-width="640" data-height="360" data-no-timeline>'
        "<p>Hi</p></div></body></html>"
    )
    write(blank, "index.html", html)
    assert "font_not_declared" in [f.code for f in audit(blank).errors]
    _add(blank, tmp_path)
    assert audit(blank, require_provenance=True).ok


def test_added_font_is_visible_to_the_html_render_compiler(
    blank: Path, tmp_path: Path
) -> None:
    _add(blank, tmp_path)
    html = scan_html((blank / "index.html").read_text())
    assert normalize_family("HV Text") in scan_fonts(html.css).declared
    font_path = read_provenance(blank)[0][0].path
    assert font_path in {ref.url.removeprefix("./") for ref in html.refs}


def test_replace_rejects_parent_escape_without_deleting_the_external_file(
    blank: Path, tmp_path: Path
) -> None:
    _add(blank, tmp_path)
    victim = write(tmp_path, "victim.woff2", FAKE_WOFF2)
    document = json.loads((blank / "PROVENANCE.json").read_text())
    document["assets"][0]["path"] = "../victim.woff2"
    write(blank, "PROVENANCE.json", json.dumps(document))
    before = (blank / "PROVENANCE.json").read_bytes()
    replacement = write(tmp_path, "f/Replacement.woff2", b"wOF2" + b"\x03" * 64)
    with pytest.raises(FontError, match="path|escape|relative"):
        _add(blank, tmp_path, font_file=replacement, replace=True)
    assert victim.read_bytes() == FAKE_WOFF2
    assert (blank / "PROVENANCE.json").read_bytes() == before


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("alias", 'HV Text";src:url(https://example.invalid/font)/*'),
        ("weight", "400; font-display:swap"),
        ("style", "normal; src:local(Arial)"),
        ("format", "unsupported"),
    ],
)
def test_invalid_saved_font_metadata_is_rejected_before_mutation(
    blank: Path, tmp_path: Path, field: str, value: str
) -> None:
    _add(blank, tmp_path)
    document = json.loads((blank / "PROVENANCE.json").read_text())
    document["assets"][0]["font"][field] = value
    write(blank, "PROVENANCE.json", json.dumps(document))
    before = (blank / FONTS_CSS).read_bytes()
    with pytest.raises(FontError, match=field):
        _add(
            blank,
            tmp_path,
            font_file=write(tmp_path, "f/New.woff2", b"wOF2" + b"\x05" * 64),
            weight="700",
        )
    assert (blank / FONTS_CSS).read_bytes() == before


def test_font_destination_symlink_escape_is_rejected_before_copying(
    blank: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "external-fonts"
    outside.mkdir()
    (blank / "assets/fonts").symlink_to(outside, target_is_directory=True)
    with pytest.raises(FontError, match="escape|outside"):
        _add(blank, tmp_path)
    assert list(outside.iterdir()) == []
    assert not (blank / "PROVENANCE.json").exists()


@pytest.mark.parametrize(
    "sidecar", ["PROVENANCE.json", "assets/fonts.css", "index.html"]
)
def test_sidecar_symlink_escape_is_rejected_without_external_changes(
    blank: Path, tmp_path: Path, sidecar: str
) -> None:
    external = write(tmp_path, "external.txt", "external content")
    target = blank / sidecar
    target.unlink(missing_ok=True)
    target.symlink_to(external)
    with pytest.raises(FontError, match="escape|outside"):
        _add(blank, tmp_path)
    assert external.read_text() == "external content"
