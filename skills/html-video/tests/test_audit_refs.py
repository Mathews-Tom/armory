"""Reference resolution at the project boundary: what may and may not be loaded."""

from __future__ import annotations

import base64
import html
import os
from pathlib import Path

import pytest

from helpers import audit, codes, page, project, write
from hv_audit import AuditResult
from hv_scan import parse_srcset, scan_css_refs


def _count(result: AuditResult, code: str) -> int:
    return codes(result).count(code)


def test_remote_render_critical_resources_are_errors_in_every_position(
    tmp_path: Path,
) -> None:
    html = page(
        '<img src="http://example.com/a.png"><video src="https://example.com/v.mp4" poster="//example.com/p.png"></video>',
        head=(
            '<script src="https://cdn.example.com/x.js"></script>'
            '<link rel="stylesheet" href="//cdn.example.com/x.css">'
            "<style>@import url(https://fonts.example.com/f.css); .a{background:url('https://x.example/b.png')}</style>"
        ),
    )
    result = audit(project(tmp_path / "p", html))
    assert not result.ok
    assert _count(result, "remote_resource") == 7


@pytest.mark.parametrize(
    "markup",
    [
        '<body background="https://example.invalid/body.png">',
        '<table background="https://example.invalid/table.png"></table>',
        '<table><tr><td background="https://example.invalid/cell.png">Cell</td></tr></table>',
    ],
)
def test_legacy_background_resources_follow_remote_policy(
    tmp_path: Path, markup: str
) -> None:
    result = audit(project(tmp_path / "p", page(markup)))
    assert _count(result, "remote_resource") == 1


def test_non_http_schemes_and_absolute_paths_are_rejected(tmp_path: Path) -> None:
    html = page(
        '<img src="file:///etc/passwd"><img src="/abs/a.png"><img src="javascript:alert(1)"><img src="C:\\x.png"><img src="a\\b.png">'
    )
    result = audit(project(tmp_path / "p", html))
    assert sorted(set(codes(result, "error"))) == [
        "absolute_path",
        "invalid_path",
        "unsupported_scheme",
    ]


def test_path_escape_is_rejected_even_when_the_target_exists_and_even_percent_encoded(
    tmp_path: Path,
) -> None:
    write(tmp_path, "outside.png", b"x")
    html = page(
        '<img src="../outside.png"><img src="sub/../../outside.png"><img src="%2e%2e/outside.png">'
    )
    result = audit(project(tmp_path / "p", html, {"sub/keep.txt": "k"}))
    assert _count(result, "path_escape") == 3
    assert "outside.png" not in result.assets


def test_symlink_escaping_the_project_is_rejected_but_internal_alias_is_allowed(
    tmp_path: Path,
) -> None:
    write(tmp_path, "secret.png", b"secret")
    root = project(
        tmp_path / "p",
        page('<img src="out.png"><img src="real.png"><img src="alias.png">'),
        {"real.png": b"real"},
    )
    try:
        os.symlink(tmp_path / "secret.png", root / "out.png")
        os.symlink(root / "real.png", root / "alias.png")
    except OSError:
        pytest.skip("symlinks unavailable")
    result = audit(root)
    assert _count(result, "symlink_escape") == 1
    assert "alias.png" in result.assets and "real.png" in result.assets
    assert _count(result, "duplicate_asset_alias") == 1  # one real file under two paths


def test_missing_directory_and_case_mismatched_references(tmp_path: Path) -> None:
    root = project(
        tmp_path / "p",
        page('<img src="gone.png"><img src="logo.png"><img src="dir">'),
        {"Logo.PNG": b"x", "dir/x": "x"},
    )
    result = audit(root)
    assert _count(result, "missing_asset") == 1
    assert _count(result, "case_mismatch") == 1
    assert _count(result, "not_a_file") == 1


def test_css_references_resolve_against_the_stylesheet_not_the_page(
    tmp_path: Path,
) -> None:
    root = project(
        tmp_path / "p",
        page(head='<link rel="stylesheet" href="css/site.css">'),
        {
            "css/site.css": ".a{background:url(img/bg.png)} .b{background:url('../shared/x.png')}",
            "css/img/bg.png": b"1",
            "shared/x.png": b"2",
        },
    )
    result = audit(root)
    assert result.ok, result.findings
    assert {"css/img/bg.png", "shared/x.png"} <= set(result.assets)
    # The same URL written in the page would point elsewhere and must fail.
    broken = project(
        tmp_path / "q",
        page(head="<style>.a{background:url(img/bg.png)}</style>"),
        {"css/img/bg.png": b"1"},
    )
    assert _count(audit(broken), "missing_asset") == 1


def test_css_import_cycle_is_reported_once_but_shared_imports_are_not_cycles(
    tmp_path: Path,
) -> None:
    cyclic = project(
        tmp_path / "c",
        page(head='<link rel="stylesheet" href="a.css">'),
        {"a.css": '@import "b.css";', "b.css": '@import url("a.css");'},
    )
    assert _count(audit(cyclic), "reference_cycle") == 1
    diamond = project(
        tmp_path / "d",
        page(
            head='<link rel="stylesheet" href="a.css"><link rel="stylesheet" href="b.css">'
        ),
        {
            "a.css": '@import "shared.css";',
            "b.css": '@import "shared.css";',
            "shared.css": ".x{}",
        },
    )
    result = audit(diamond)
    assert "reference_cycle" not in codes(result)
    assert {"a.css", "b.css", "shared.css"} <= set(result.assets)


def test_html_self_mount_is_a_cycle(tmp_path: Path) -> None:
    root = project(
        tmp_path / "p", page('<div data-composition-src="index.html"></div>')
    )
    assert _count(audit(root), "reference_cycle") == 1


def test_srcset_poster_source_and_audio_references_are_all_checked(
    tmp_path: Path,
) -> None:
    body = (
        '<img src="a.png" srcset="b.png 1x, c.png 2x">'
        '<video src="v.mp4" poster="p.png"><source src="v.webm"><track src="t.vtt"></video>'
        '<audio src="s.mp3"></audio><picture><source srcset="d.png 480w, e.png 800w"></picture>'
    )
    present = {
        "a.png": b"1",
        "b.png": b"2",
        "v.mp4": b"3",
        "p.png": b"4",
        "s.mp3": b"5",
        "d.png": b"6",
    }
    result = audit(project(tmp_path / "p", page(body), present))
    missing = {
        f.message.split("'")[1] for f in result.findings if f.code == "missing_asset"
    }
    assert missing == {"c.png", "v.webm", "t.vtt", "e.png"}
    assert set(present) <= set(result.assets)


def test_data_uris_are_ignored_only_when_well_formed(tmp_path: Path) -> None:
    good = base64.b64encode(b"hello").decode()
    body = f'<img src="data:image/png;base64,{good}"><img src="data:text/plain,hi"><img src="data:image/png;base64,@@@@">'
    result = audit(project(tmp_path / "p", page(body)))
    assert codes(result, "error") == ["invalid_data_uri"]


def test_fragments_must_target_an_existing_id(tmp_path: Path) -> None:
    body = (
        '<svg><defs><linearGradient id="g"></linearGradient><symbol id="s"></symbol></defs>'
        '<use href="#s"></use><use href="#nope"></use><rect fill="url(#g)"></rect><rect fill="url(#zzz)"></rect></svg>'
    )
    result = audit(project(tmp_path / "p", page(body)))
    assert _count(result, "fragment_missing") == 2


def test_dynamic_network_use_is_a_warning_not_a_proof_of_absence(
    tmp_path: Path,
) -> None:
    script = (
        "<script>fetch('https://api.example.com/data'); const u = base + '/x'; fetch(u);"
        " new XMLHttpRequest(); import('./m.js'); const t = Date.now();</script>"
    )
    result = audit(project(tmp_path / "p", page(script), {"m.js": "export {}"}))
    assert result.ok  # static audit cannot fail what it cannot see
    assert {"dynamic_network_api", "remote_url_literal", "nondeterministic_api"} <= set(
        codes(result, "warning")
    )
    # An SVG namespace literal is not a remote fetch.
    namespaced = audit(
        project(
            tmp_path / "q",
            page(
                "<script>el.setAttribute('xmlns','http://www.w3.org/2000/svg')</script>"
            ),
        )
    )
    assert "remote_url_literal" not in codes(namespaced)


def test_local_script_files_are_scanned_and_empty_references_warn(
    tmp_path: Path,
) -> None:
    root = project(
        tmp_path / "p",
        page('<img src="">', head='<script src="app.js"></script>'),
        {"app.js": "setInterval(tick, 10)"},
    )
    result = audit(root)
    assert "nondeterministic_api" in codes(result, "warning")
    assert "empty_reference" in codes(result, "warning")


def test_identical_content_in_distinct_files_is_noted_and_different_content_is_not(
    tmp_path: Path,
) -> None:
    same = project(
        tmp_path / "s",
        page('<img src="a.png"><img src="b.png">'),
        {"a.png": b"same", "b.png": b"same"},
    )
    assert _count(audit(same), "duplicate_content") == 1
    diff = project(
        tmp_path / "d",
        page('<img src="a.png"><img src="b.png">'),
        {"a.png": b"one", "b.png": b"two"},
    )
    assert "duplicate_content" not in codes(audit(diff))


def test_one_file_under_several_spellings_is_one_asset(tmp_path: Path) -> None:
    root = project(
        tmp_path / "p",
        page('<img src="a.png"><img src="./a.png"><img src="sub/../a.png?v=2#x">'),
        {"a.png": b"1", "sub/k": "k"},
    )
    result = audit(root)
    assert [p for p in result.assets if p.endswith(".png")] == ["a.png"]


def test_srcset_and_image_set_parsers_handle_descriptors_and_commas() -> None:
    assert parse_srcset("a.png 1x, b.png 2x") == ["a.png", "b.png"]
    assert parse_srcset("a.png, b.png") == ["a.png", "b.png"]
    assert parse_srcset("a.png,b.png") == [
        "a.png,b.png"
    ]  # a comma inside a URL token is part of the URL
    assert parse_srcset("w.png 100w , x.png 200w") == ["w.png", "x.png"]
    refs = scan_css_refs(
        "a{background:image-set('lo.png' 1x, \"hi.png\" 2x)} /* url(commented.png) */ b{background:url( x.png )}"
    )
    assert [r.url for r in refs] == ["lo.png", "hi.png", "x.png"]


# -- documents and scripts the browser loads but the old audit never read ----------


def test_iframe_srcdoc_is_audited_as_the_document_it_is(tmp_path: Path) -> None:
    inner = html.escape(
        '<img src="https://evil.example.com/a.png"><img src="gone.png">'
        "<style>.a{background:url(https://evil.example.com/b.png)}</style>",
        quote=True,
    )
    result = audit(
        project(tmp_path / "p", page(f'<iframe id="f" srcdoc="{inner}"></iframe>'))
    )
    assert not result.ok
    assert _count(result, "remote_resource") == 2
    assert _count(result, "missing_asset") == 1  # resolved like the parent page


def test_srcdoc_nested_too_deeply_to_audit_is_rejected_not_waved_through(
    tmp_path: Path,
) -> None:
    doc = '<img src="https://evil.example.com/deep.png">'
    for _ in range(5):
        doc = f'<iframe srcdoc="{html.escape(doc, quote=True)}"></iframe>'
    result = audit(project(tmp_path / "p", page(doc)))
    assert "srcdoc_too_deep" in codes(result, "error")


def test_import_map_addresses_are_references_and_bare_specifiers_need_a_map(
    tmp_path: Path,
) -> None:
    importmap = (
        '<script type="importmap">{"imports":{"g":"https://cdn.example.com/g.js",'
        '"h":"./h.js","lib/":"./vendor/lib/"}}</script>'
    )
    body = '<script type="module">import h from "h"; import a from "lib/a.js"; import z from "zzz";</script>'
    files: dict[str, str | bytes] = {
        "h.js": "export default 1",
        "vendor/lib/a.js": "export default 2",
    }
    result = audit(project(tmp_path / "p", page(body, head=importmap), files))
    assert _count(result, "remote_resource") == 1
    assert _count(result, "unresolved_module_specifier") == 1
    assert {"h.js", "vendor/lib/a.js"} <= set(result.assets)
    broken = audit(
        project(
            tmp_path / "q", page(body, head=importmap), {"h.js": "export default 1"}
        )
    )
    assert _count(broken, "missing_asset") == 1  # lib/a.js through the prefix map


def test_invalid_import_map_and_speculation_rules_fail_loudly(tmp_path: Path) -> None:
    cases = {
        "badjson": ('<script type="importmap">{oops</script>', "importmap_invalid"),
        "badaddress": (
            '<script type="importmap">{"imports":{"x":"x.js"}}</script>',
            "importmap_address_invalid",
        ),
        "docrules": (
            '<script type="speculationrules">{"prefetch":[{"where":{"href_matches":"/*"}}]}</script>',
            "speculationrules_document_rules",
        ),
    }
    for name, (head, expected) in cases.items():
        result = audit(project(tmp_path / name, page(head=head)))
        assert expected in codes(result, "error"), (name, codes(result))
    remote = audit(
        project(
            tmp_path / "remote",
            page(
                head='<script type="speculationrules">{"prerender":[{"urls":["https://evil.example.com/n.html"]}]}</script>'
            ),
        )
    )
    assert _count(remote, "remote_resource") == 1


@pytest.mark.parametrize(
    "attribute",
    [
        "onclick=\"fetch('https://e.example.com/x')\"",
        "onload=\"new Worker('w.js')\"",
    ],
)
def test_inline_event_handlers_are_scanned_for_script_hazards(
    tmp_path: Path, attribute: str
) -> None:
    result = audit(project(tmp_path / "p", page(root_attrs=attribute)))
    assert "dynamic_network_api" in codes(result, "warning")
    link = audit(
        project(
            tmp_path / "q",
            page('<span id="a"><a href="javascript:setInterval(tick,5)">x</a></span>'),
        )
    )
    assert "nondeterministic_api" in codes(link, "warning")


def test_every_script_mime_the_browser_executes_is_scanned(tmp_path: Path) -> None:
    for index, mime in enumerate(
        ["application/ecmascript", "text/jscript", "application/x-javascript", ""]
    ):
        body = f'<script type="{mime}">setInterval(tick, 10)</script>'
        result = audit(project(tmp_path / str(index), page(body)))
        assert "nondeterministic_api" in codes(result, "warning"), mime


@pytest.mark.parametrize(
    ("snippet", "code"),
    [
        ("const t = new Date().getTime();", "nondeterministic_api"),
        ("const s = Date();", "nondeterministic_api"),
        ("crypto.getRandomValues(buffer);", "nondeterministic_api"),
        ("const id = crypto.randomUUID();", "nondeterministic_api"),
        (
            "el.animate([{opacity: 0}, {opacity: 1}], {duration: 1000});",
            "page_clock_animation",
        ),
        ("new SharedWorker('w.js');", "dynamic_network_api"),
        ("img.src = 'http://127.0.0.1:8000/a.png';", "remote_url_literal"),
        ("img.src = 'http://localhost:3000/a.png';", "remote_url_literal"),
        ("const u = '//cdn.example.com/x.js';", "remote_url_literal"),
    ],
)
def test_script_hazard_forms_that_leak_the_seek_clock_or_the_network_warn(
    tmp_path: Path, snippet: str, code: str
) -> None:
    result = audit(project(tmp_path / "p", page(f"<script>{snippet}</script>")))
    assert result.ok
    assert code in codes(result, "warning")


def test_deterministic_script_forms_do_not_warn(tmp_path: Path) -> None:
    body = "<script>const d = new Date(2020, 1, 1); const n = 'http://www.w3.org/2000/svg';</script>"
    assert codes(audit(project(tmp_path / "p", page(body))), "warning") == []


def test_escaped_css_url_and_import_tokens_are_decoded_and_namespace_is_not_a_fetch(
    tmp_path: Path,
) -> None:
    style = (
        "<style>.a{background:\\75 rl(https://evil.example.com/a.png)}"
        ' @\\69mport "https://evil.example.com/b.css";</style>'
    )
    result = audit(project(tmp_path / "p", page(head=style)))
    assert _count(result, "remote_resource") == 2
    namespace = (
        "<style>@namespace svg url(http://www.w3.org/2000/svg); .a{color:red}</style>"
    )
    assert audit(project(tmp_path / "q", page(head=namespace))).ok
    unrepresentable = "<style>.a{background:url(a\\2e png)}</style>"
    rejected = audit(project(tmp_path / "r", page(head=unrepresentable)))
    assert "invalid_path" in codes(rejected, "error")


def test_local_svg_documents_are_followed_for_their_own_references(
    tmp_path: Path,
) -> None:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
        '<style><![CDATA[@import url("extra.css");]]></style>'
        '<image href="pic.png"/><image href="https://evil.example.com/i.png"/>'
        '<use xlink:href="#nope"/></svg>'
    )
    files: dict[str, str | bytes] = {
        "art.svg": svg,
        "pic.png": b"1",
        "extra.css": ".x{}",
    }
    result = audit(
        project(tmp_path / "p", page('<object data="art.svg"></object>'), files)
    )
    assert _count(result, "remote_resource") == 1
    assert _count(result, "fragment_missing") == 1
    assert {"art.svg", "pic.png", "extra.css"} <= set(result.assets)
    assert (
        audit(project(tmp_path / "z", page('<img src="a.svgz">'), {"a.svgz": b"x"}))
        .errors[0]
        .code
        == "unscannable_document"
    )


def test_static_javascript_imports_are_followed_whatever_the_file_extension(
    tmp_path: Path,
) -> None:
    files: dict[str, str | bytes] = {
        "app.txt": 'import "./dep.js"; import "./gone.js";',
        "dep.js": 'import x from "https://cdn.example.com/x.js"; const u = new URL("./img.png", import.meta.url);',
        "img.png": b"1",
    }
    result = audit(
        project(tmp_path / "p", page(head='<script src="app.txt"></script>'), files)
    )
    assert _count(result, "remote_resource") == 1
    assert _count(result, "missing_asset") == 1
    assert {"app.txt", "dep.js", "img.png"} <= set(result.assets)
    commented: dict[str, str | bytes] = {
        "app.js": '// import "./nope.js"\n/* import "./nope2.js" */ import "./ok.js";',
        "ok.js": "",
    }
    assert audit(
        project(tmp_path / "q", page(head='<script src="app.js"></script>'), commented)
    ).ok


def test_data_uri_documents_scripts_and_stylesheets_cannot_be_audited(
    tmp_path: Path,
) -> None:
    body = (
        '<iframe src="data:text/html,<img src=https://evil.example.com/a.png>"></iframe>'
        '<script src="data:text/javascript,fetch(1)"></script>'
    )
    style = '<style>@import url("data:text/css,.a{}");</style>'
    result = audit(project(tmp_path / "p", page(body, head=style)))
    assert _count(result, "opaque_data_document") == 3
    good = base64.b64encode(b"x").decode()
    image = audit(
        project(tmp_path / "q", page(f'<img src="data:image/png;base64,{good}">'))
    )
    assert image.ok
