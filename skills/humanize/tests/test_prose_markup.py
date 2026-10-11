"""Boundary tests for the shared Markdown region parser."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from prose_markup import InputError, parse, read_source  # noqa: E402


def regions(text: str) -> list[tuple[str, str]]:
    return [(r.kind, text[r.start : r.end]) for r in parse(text).regions]


def test_indented_list_continuation_is_prose_but_top_level_indent_is_code() -> None:
    assert regions("- item\n\n    continued prose\n") == []
    assert regions("Para.\n\n    code line\n") == [("indented_code", "    code line")]


def test_fence_nested_in_a_list_is_protected() -> None:
    text = "1. Step\n\n    ```sh\n    run --x\n    ```\n\nAfter.\n"
    assert regions(text) == [("fenced_code", "    ```sh\n    run --x\n    ```")]


def test_unclosed_fence_protects_to_the_end() -> None:
    text = "Intro.\n\n```py\nx = 1\nstill code\n"
    assert regions(text) == [("fenced_code", "```py\nx = 1\nstill code")]


def test_frontmatter_requires_an_opening_first_line_and_key_like_content() -> None:
    assert regions("Intro\n---\nkey: v\n---\n") == []
    assert regions("---\n\nText\n\n---\n") == []
    assert regions("\ufeff---\nkey: v\n---\nBody\n")[0][0] == "frontmatter"


def test_urls_keep_balanced_parentheses_and_drop_sentence_punctuation() -> None:
    text = "See https://en.wikipedia.org/wiki/Foo_(bar). Then (https://x.org/a) done.\n"
    assert regions(text) == [
        ("bare_url", "https://en.wikipedia.org/wiki/Foo_(bar)"),
        ("bare_url", "https://x.org/a"),
    ]
    link = 'A [b](https://example.com/a_(b)?x=1 "title") c\n'
    assert [
        (kind, value) for kind, value in regions(link) if kind == "link_target"
    ] == [("link_target", "https://example.com/a_(b)?x=1")]


def test_inline_code_may_span_lines_but_not_paragraphs() -> None:
    assert regions("Use `git\ncommit` now.\n") == [("inline_code", "`git\ncommit`")]
    assert regions("Stray ` tick\n\nand another ` tick\n") == []


def test_positions_are_code_point_based_with_crlf() -> None:
    doc = parse("a\u00e9\r\nsecond line\r\n")
    offset = doc.text.index("second")
    assert doc.position(offset) == (2, 1)
    assert doc.position(1) == (1, 2)


def test_masking_preserves_offsets_and_line_breaks() -> None:
    text = "Run `x` now.\r\n\r\n```\r\ncode\r\n```\r\n"
    masked = parse(text).masked()
    assert len(masked) == len(text)
    assert masked.count("\r\n") == text.count("\r\n")
    assert "code" not in masked and "Run" in masked


def test_read_source_rejects_invalid_bytes(tmp_path: Path) -> None:
    bad = tmp_path / "bad.txt"
    bad.write_bytes(b"ok \xff")
    with pytest.raises(InputError):
        read_source(str(bad))
    nul = tmp_path / "nul.txt"
    nul.write_bytes(b"a\x00b")
    with pytest.raises(InputError):
        read_source(str(nul))
