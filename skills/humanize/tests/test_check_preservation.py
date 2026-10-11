"""Behavioral tests for the humanize preservation checker."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

import check_preservation  # noqa: E402

SOURCE = (
    "---\ntitle: Report\n---\n\n"
    "# Report\n\n"
    "The cache cut median latency from 80 ms to 12 ms, per Smith et al. (2020) [1]. "
    "Call `get_user` first; at least 10 users saw 12 ms again [1].\n\n"
    "```python\ndef get_user():\n    return 5\n```\n\n"
    "| name | value |\n| - | - |\n| x | 1 |\n\n"
    "> The vendor wrote: do not retry. ever.\n\n"
    "See [docs](https://example.com/a_(b)?x=1) and https://example.com/z.\n"
)
DRAFT = (
    "---\ntitle: Report\n---\n\n"
    "# Report\n\n"
    "Median latency fell from 80 ms to 12 ms [1]. Call `get_user` first. "
    "Smith et al. (2020) saw the same, and at least 10 users saw 12 ms again [1].\n\n"
    "```python\ndef get_user():\n    return 5\n```\n\n"
    "| name | value |\n| - | - |\n| x | 1 |\n\n"
    "> The vendor wrote: do not retry. ever.\n\n"
    "Docs: https://example.com/z and [docs](https://example.com/a_(b)?x=1).\n"
)


def check(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    source: str,
    draft: str,
    *extra: str,
) -> tuple[int, dict[str, Any]]:
    src = tmp_path / "source.md"
    drf = tmp_path / "draft.md"
    src.write_bytes(source.encode("utf-8"))
    drf.write_bytes(draft.encode("utf-8"))
    code = check_preservation.main([str(src), str(drf), *extra])
    out = capsys.readouterr().out
    return code, (json.loads(out) if out else {})


def failures(report: dict[str, Any], category: str) -> list[dict[str, Any]]:
    return [f for f in report["failures"] if f["category"] == category]


def test_prose_restructuring_preserves_protected_blocks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, report = check(tmp_path, capsys, SOURCE, DRAFT)
    assert report["failures"] == []
    assert code == 0
    assert report["status"] == "pass"


def test_benign_rewrites_do_not_trip_literals(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = "Additionally the team handled 1,000 requests and 50 percent of users noticed.\n"
    draft = "Also the team handled 1000 requests and 50% of customers noticed.\n"
    code, report = check(tmp_path, capsys, source, draft)
    assert (code, report["failures"]) == (0, [])
    plain = check(
        tmp_path,
        capsys,
        "Additionally the team shipped quickly.\n",
        "Also the team shipped fast.\n",
    )
    assert plain[1]["checked"]["literals"] == {}


def test_duplicate_citation_loss_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, report = check(tmp_path, capsys, SOURCE, DRAFT.replace("again [1]", "again"))
    assert code == 1
    (failure,) = failures(report, "citation")
    assert failure["problem"] == "removed"
    assert (failure["source_count"], failure["draft_count"]) == (2, 1)


def test_duplicate_number_loss_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, report = check(
        tmp_path, capsys, SOURCE, DRAFT.replace("saw 12 ms again", "saw it again")
    )
    assert code == 1
    (failure,) = failures(report, "numeric")
    assert failure["problem"] == "removed"
    assert (failure["source_count"], failure["draft_count"]) == (2, 1)


def test_added_number_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, report = check(
        tmp_path,
        capsys,
        SOURCE,
        DRAFT.replace("Median latency", "Median latency (about $9)"),
    )
    assert code == 1
    assert [f["problem"] for f in failures(report, "numeric")] == ["added"]


@pytest.mark.parametrize(
    ("old", "new", "part"),
    [
        ("from 80 ms to", "from 80 s to", "unit"),
        ("at least 10 users", "10 users", "qualifier"),
        ("at least 10 users", "about 10 users", "qualifier"),
    ],
)
def test_unit_and_qualifier_changes_are_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], old: str, new: str, part: str
) -> None:
    code, report = check(tmp_path, capsys, SOURCE, DRAFT.replace(old, new))
    assert code == 1
    (failure,) = failures(report, "numeric")
    assert failure["problem"] == "changed"
    assert failure["changed_parts"] == [part]


def test_sign_and_currency_changes_are_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, report = check(
        tmp_path,
        capsys,
        "Revenue fell -5% and cost $5 more.\n",
        "Revenue fell 5% and cost 5 more.\n",
    )
    assert code == 1
    assert sorted(f["changed_parts"][0] for f in failures(report, "numeric")) == [
        "currency",
        "sign",
    ]


def test_code_identifier_drift_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, report = check(
        tmp_path, capsys, SOURCE, DRAFT.replace("`get_user` first", "`getUser` first")
    )
    assert code == 1
    (failure,) = failures(report, "inline_code")
    assert failure["problem"] == "changed"

    code, report = check(
        tmp_path,
        capsys,
        "The job calls fetch_user_data twice.\n",
        "The job calls fetchUserData twice.\n",
    )
    assert code == 1
    assert [f["problem"] for f in failures(report, "identifier")] == ["changed"]

    code, report = check(
        tmp_path, capsys, SOURCE, DRAFT.replace("    return 5", "    return 6")
    )
    assert code == 1
    assert [f["problem"] for f in failures(report, "fenced_code")] == ["changed"]


def test_protected_block_reorder_removal_and_addition(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code_block = "```python\ndef get_user():\n    return 5\n```\n\n"
    table = "| name | value |\n| - | - |\n| x | 1 |\n\n"
    code, report = check(
        tmp_path, capsys, SOURCE, DRAFT.replace(code_block + table, table + code_block)
    )
    assert code == 1
    assert [f["problem"] for f in report["failures"]] == ["reordered"]

    code, report = check(tmp_path, capsys, SOURCE, DRAFT.replace(code_block, ""))
    assert [(f["problem"], f["category"]) for f in report["failures"]] == [
        ("removed", "fenced_code")
    ]

    code, report = check(
        tmp_path, capsys, SOURCE, DRAFT + "\n```sh\nrm -rf build\n```\n"
    )
    assert [(f["problem"], f["category"]) for f in report["failures"]] == [
        ("added", "fenced_code")
    ]


def test_frontmatter_table_and_quote_edits_fail_unless_allowed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    edits = {
        "frontmatter": ("title: Report", "title: Reports"),
        "table": ("| x | 1 |", "| x | 2 |"),
        "quote": ("do not retry. ever.", "avoid retrying."),
    }
    for kind, (old, new) in edits.items():
        draft = DRAFT.replace(old, new)
        code, report = check(tmp_path, capsys, SOURCE, draft)
        assert code == 1, kind
        assert {f["category"] for f in report["failures"]} == {kind}
        code, report = check(tmp_path, capsys, SOURCE, draft, "--allow", kind)
        assert (code, report["failures"]) == (0, []), kind


def test_quoted_snippet_must_stay_exact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = 'He said "do not ever retry this request" twice.\n'
    code, report = check(
        tmp_path, capsys, source, 'He said "never retry this request" twice.\n'
    )
    assert code == 1
    assert {f["category"] for f in report["failures"]} == {"inline_quote"}


def test_urls_with_balanced_parentheses_stay_exact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, report = check(
        tmp_path, capsys, SOURCE, DRAFT.replace("a_(b)?x=1", "a_(b)?x=2")
    )
    assert code == 1
    assert [f["problem"] for f in failures(report, "url")] == ["changed"]

    code, report = check(
        tmp_path,
        capsys,
        SOURCE,
        DRAFT.replace("example.com/z and", "example.com/y and"),
    )
    assert code == 1
    assert [f["problem"] for f in failures(report, "url")] == ["changed"]

    renamed = DRAFT.replace("[docs]", "[the documentation]")
    assert check(tmp_path, capsys, SOURCE, renamed)[0] == 0
    code, report = check(
        tmp_path,
        capsys,
        SOURCE,
        DRAFT.replace("a_(b)?x=1", "a_(b)?x=2"),
        "--allow",
        "url",
    )
    assert code == 0


def test_explicit_literals_keep_their_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = "Acme signed with Globex. Globex then paid Acme.\n"
    assert (
        check(
            tmp_path,
            capsys,
            source,
            "Acme and Globex agreed; Globex paid.\n",
            "--literal",
            "Globex",
        )[0]
        == 0
    )
    code, report = check(
        tmp_path,
        capsys,
        source,
        "Acme signed a deal and was paid.\n",
        "--literal",
        "Globex",
    )
    assert code == 1
    (failure,) = failures(report, "extra")
    assert (failure["source_count"], failure["draft_count"]) == (2, 0)
    assert check(tmp_path, capsys, source, "Acme signed a deal.\n")[0] == 0


def test_invalid_inputs_exit_with_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = tmp_path / "good.md"
    good.write_text("Plain text.\n", encoding="utf-8")
    bad = tmp_path / "bad.md"
    bad.write_bytes(b"caf\xe9\n")
    assert check_preservation.main([str(good), str(tmp_path / "missing.md")]) == 2
    assert check_preservation.main([str(good), str(bad)]) == 2
    assert check_preservation.main(["-", "-"]) == 2
    assert check_preservation.main([str(good), str(good), "--literal", ""]) == 2
    assert check_preservation.main([str(good), str(good), "--literal", "Initech"]) == 2
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "artifact",
    [
        "[cite_start]",
        "turn0search0",
        ":contentReference[oaicite:0]{index=0}",
        "[cite: 3]",
        "[span_1](start_span)",
    ],
)
def test_removing_chat_artifacts_preserves_real_literals(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], artifact: str
) -> None:
    source = f"The cache takes 25 ms [1].{artifact}\n"
    code, report = check(tmp_path, capsys, source, "The cache takes 25 ms [1].\n")
    assert (code, report["failures"]) == (0, [])


@pytest.mark.parametrize(
    ("source", "draft"),
    [
        ("Requires v2.1.0.", "Requires v2.4.0."),
        ("Requires py3.12.", "Requires py3.13."),
        ("__90%__ uptime.", "__50%__ uptime."),
        ("Takes .5 ms.", "Takes .9 ms."),
        ("Not more than 5 retries.", "More than 5 retries."),
        ("5 ms or more.", "5 ms."),
        (
            "Revenue peaked in\n2023. Costs fell.",
            "Revenue peaked in\n2024. Costs fell.",
        ),
    ],
)
def test_rewriting_literal_boundaries_cannot_hide_changed_facts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], source: str, draft: str
) -> None:
    code, report = check(tmp_path, capsys, source, draft)
    assert code == 1
    assert report["failures"]


@pytest.mark.parametrize(
    ("source", "draft", "allowed"),
    [
        ("> ```sh\n> rm -rf build\n> ```\n", "> ```sh\n> rm -rf /\n> ```\n", "quote"),
        ("> ~~~sh\n> rm -rf build\n> ~~~\n", "> ~~~sh\n> rm -rf /\n> ~~~\n", "quote"),
        (
            "| Option |\n| --- |\n| `--safe` |\n",
            "| Option |\n| --- |\n| `--force` |\n",
            "table",
        ),
        ('"Run `--safe` now."', '"Run `--force` now."', "inline_quote"),
    ],
)
def test_allowing_container_edits_never_unlocks_nested_code(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    source: str,
    draft: str,
    allowed: str,
) -> None:
    code, report = check(tmp_path, capsys, source, draft, "--allow", allowed)
    assert code == 1
    assert any("code" in finding["category"] for finding in report["failures"])


def test_fenced_code_line_endings_are_preserved_verbatim(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = '```python\r\nvalue = """a\r\nb"""\r\n```\r\n'
    code, report = check(tmp_path, capsys, source, source.replace("\r\n", "\n"))
    assert code == 1
    assert failures(report, "fenced_code")
