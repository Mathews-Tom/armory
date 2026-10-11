"""Behavioral tests for the humanize prose scanner and explicit mechanical fixes."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

import lint_prose  # noqa: E402

MIXED = (
    "---\ntitle: Great question!\nsource: [cite: 9]\n---\n\n"
    "# Notes\n\n"
    "Run `foo :contentReference[oaicite:0]{index=0}` once.\n\n"
    "```text\nGreat question! [cite: 1]\nI hope this helps!\n```\n\n"
    "| a | b |\n| - | - |\n| Great question! | [cite: 2] |\n\n"
    "> Certainly! quoted [cite: 3]\n\n"
    "    indented [cite: 4]\n\n"
    "See [guide](https://example.com/a?utm_source=chatgpt.com&x=1) now.[cite: 5]\n"
)


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = lint_prose.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def scan(capsys: pytest.CaptureFixture[str], path: Path, *extra: str) -> dict[str, Any]:
    code, out, err = run(capsys, "scan", str(path), *extra)
    assert code == 0, err
    report: dict[str, Any] = json.loads(out)
    return report


def write(tmp_path: Path, text: str, name: str = "in.md") -> Path:
    path = tmp_path / name
    path.write_bytes(text.encode("utf-8"))
    return path


def test_protected_regions_are_never_scanned(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = scan(capsys, write(tmp_path, MIXED))
    by_rule = {f["rule"]: f for f in report["findings"]}
    assert set(by_rule) == {"HUM001", "HUM002"}
    assert [f["evidence"] for f in report["findings"] if f["rule"] == "HUM001"] == [
        "[cite: 5]"
    ]
    assert by_rule["HUM002"]["evidence"] == "utm_source=chatgpt.com"
    assert by_rule["HUM002"]["fixable"] is True
    assert by_rule["HUM002"]["fix_requires"] == ["--strip-tracking"]


def test_fix_touches_only_the_selected_artifact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = write(tmp_path, MIXED)
    out_path = tmp_path / "out.md"
    code, _, err = run(
        capsys, "fix", str(source), "--select", "HUM001", "--output", str(out_path)
    )
    assert code == 0, err
    assert out_path.read_text(encoding="utf-8") == MIXED.replace("[cite: 5]", "")
    assert source.read_text(encoding="utf-8") == MIXED


def test_crlf_offsets_and_fix_preserve_line_endings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = (
        "# Title\r\n\r\nGreat question! The cache cut latency.[cite: 1]\r\n\r\n"
        "Second para.\r\nI hope this helps!\r\n"
    )
    path = write(tmp_path, text)
    report = scan(capsys, path)
    assert report["line_endings"] == "crlf"
    assert {f["rule"] for f in report["findings"]} == {"HUM001", "HUM005"}
    for finding in report["findings"]:
        assert text[finding["start"] : finding["end"]] == finding["evidence"]
    opener = next(
        f for f in report["findings"] if f.get("details", {}).get("role") == "opener"
    )
    closer = next(
        f for f in report["findings"] if f.get("details", {}).get("role") == "closer"
    )
    assert (opener["line"], opener["column"]) == (3, 1)
    assert (closer["line"], closer["column"]) == (6, 1)

    out_path = tmp_path / "out.md"
    code, _, err = run(
        capsys, "fix", str(path), "--select", "HUM001,HUM005", "--output", str(out_path)
    )
    assert code == 0, err
    assert (
        out_path.read_bytes()
        == b"# Title\r\n\r\nThe cache cut latency.\r\n\r\nSecond para.\r\n"
    )


def test_wrapper_paragraph_removal_leaves_one_blank_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = "Intro sentence.\n\nCertainly!\n\nBody sentence.\n\nI hope this helps!\n"
    path = write(tmp_path, text)
    out_path = tmp_path / "out.md"
    code, _, err = run(
        capsys, "fix", str(path), "--select", "HUM005", "--output", str(out_path)
    )
    assert code == 0, err
    assert out_path.read_text(encoding="utf-8") == "Intro sentence.\n\nBody sentence.\n"


def test_citation_between_words_leaves_single_space(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(
        tmp_path,
        "Latency fell [cite: 1] after the change :contentReference[oaicite:2]{index=2}.\n",
    )
    out_path = tmp_path / "out.md"
    code, _, err = run(
        capsys, "fix", str(path), "--select", "HUM001", "--output", str(out_path)
    )
    assert code == 0, err
    assert out_path.read_text(encoding="utf-8") == "Latency fell after the change.\n"


def test_quoted_evidence_is_not_flagged_but_the_same_text_unquoted_is(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    quoted = (
        "The reviewer pasted this reply:\n\n"
        "> Great question! I hope this helps!\n\n"
        'The bot answered "Let me know if you have any other questions today" and stopped.\n'
    )
    assert scan(capsys, write(tmp_path, quoted))["findings"] == []
    bare = "Body sentence.\n\nLet me know if you have any other questions today.\n"
    findings = scan(capsys, write(tmp_path, bare, "bare.md"))["findings"]
    assert [f["rule"] for f in findings] == ["HUM005"]


def test_fix_refuses_review_only_rules_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "Without further ado, the schema changed.\n")
    out_path = tmp_path / "out.md"
    assert scan(capsys, path)["findings"][0]["rule"] == "HUM006"
    code, _, _ = run(
        capsys, "fix", str(path), "--select", "HUM006", "--output", str(out_path)
    )
    assert code == 2
    assert not out_path.exists()


def test_fix_never_writes_over_input_or_existing_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "Result stands.[cite: 1]\n")
    code, _, _ = run(
        capsys, "fix", str(path), "--select", "HUM001", "--output", str(path), "--force"
    )
    assert code == 2
    assert path.read_text(encoding="utf-8") == "Result stands.[cite: 1]\n"
    existing = write(tmp_path, "keep me\n", "existing.md")
    code, _, _ = run(
        capsys, "fix", str(path), "--select", "HUM001", "--output", str(existing)
    )
    assert code == 2
    assert existing.read_text(encoding="utf-8") == "keep me\n"
    code, _, err = run(
        capsys,
        "fix",
        str(path),
        "--select",
        "HUM001",
        "--output",
        str(existing),
        "--force",
    )
    assert code == 0, err
    assert existing.read_text(encoding="utf-8") == "Result stands.\n"


def test_fix_with_no_matching_findings_writes_no_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "Plain sentence.\n")
    out_path = tmp_path / "out.md"
    code, out, err = run(
        capsys, "fix", str(path), "--select", "HUM001", "--output", str(out_path)
    )
    assert code == 0, err
    assert json.loads(out)["status"] == "no_changes"
    assert not out_path.exists()


def test_tracking_removal_is_opt_in_and_signed_urls_stay_exact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = (
        "See [a](https://example.com/a?utm_source=chatgpt.com&x=1) and "
        "[b](https://cdn.example.com/f?sig=abc&utm_source=chatgpt.com).\n"
    )
    path = write(tmp_path, text)
    out_path = tmp_path / "out.md"
    code, _, _ = run(
        capsys, "fix", str(path), "--select", "HUM002", "--output", str(out_path)
    )
    assert code == 2
    assert not out_path.exists()

    code, out, err = run(
        capsys,
        "fix",
        str(path),
        "--select",
        "HUM002",
        "--strip-tracking",
        "--output",
        str(out_path),
    )
    assert code == 0, err
    assert out_path.read_text(encoding="utf-8") == (
        "See [a](https://example.com/a?x=1) and "
        "[b](https://cdn.example.com/f?sig=abc&utm_source=chatgpt.com).\n"
    )
    assert len(json.loads(out)["skipped"]) == 1

    signed = next(
        f
        for f in scan(capsys, path)["findings"]
        if f.get("details", {}).get("signed_url")
    )
    assert signed["fixable"] is False
    code, _, _ = run(
        capsys,
        "fix",
        str(path),
        "--select",
        signed["id"],
        "--strip-tracking",
        "--output",
        str(tmp_path / "x.md"),
    )
    assert code == 2


def test_unknown_selection_ids_fail_loudly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "Result stands.[cite: 1]\n")
    for selection in ("HUM999", "HUM001:5", "nonsense"):
        code, _, _ = run(
            capsys,
            "fix",
            str(path),
            "--select",
            selection,
            "--output",
            str(tmp_path / "o.md"),
        )
        assert code == 2, selection
    assert not (tmp_path / "o.md").exists()


@pytest.mark.parametrize("spec", ["0", "3-2", "x", "1-99", "", "1,,2", "-4"])
def test_invalid_line_ranges_are_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], spec: str
) -> None:
    path = write(tmp_path, "One.\n\nTwo.\n")
    code, out, _ = run(capsys, "scan", str(path), "--lines", spec)
    assert code == 2
    assert out == ""


def test_line_ranges_keep_paragraph_context(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = (
        "Great question! Intro.\n\n"
        "Middle paragraph.\nLet's dive in now.\n\n"
        "Closing paragraph.[cite: 1]\n"
    )
    path = write(tmp_path, text)
    whole = scan(capsys, path)
    assert {f["rule"] for f in whole["findings"]} == {"HUM001", "HUM005", "HUM006"}

    context = scan(capsys, path, "--lines", "3")
    assert [f["rule"] for f in context["findings"]] == ["HUM006"]
    assert context["findings"][0]["in_requested_lines"] is False
    assert context["selected_lines"]["with_paragraph_context"] == [[3, 4]]

    exact = scan(capsys, path, "--lines", "4")
    assert exact["findings"][0]["in_requested_lines"] is True

    out_path = tmp_path / "out.md"
    code, _, err = run(
        capsys,
        "fix",
        str(path),
        "--select",
        "HUM001",
        "--lines",
        "1-2",
        "--output",
        str(out_path),
    )
    assert code == 0, err
    assert not out_path.exists()


def test_candidates_are_flagged_only_in_prose(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = (
        "# Overview\n\n## Details\n\n#### Skipped\n\n"
        "The change isn't just a rename, it's a rewrite.\n\n"
        "```\nThe change isn't just a rename, it's a rewrite.\n```\n\n"
        "That's the real win.\n"
    )
    report = scan(capsys, write(tmp_path, text))
    found = sorted((f["rule"], f["line"]) for f in report["findings"])
    assert found == [("HUM004", 5), ("HUM007", 7), ("HUM008", 13)]
    assert all(
        f["confidence"] in ("mechanical", "candidate") for f in report["findings"]
    )
    assert report["notice"]


def test_unreadable_input_is_reported_not_scanned(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.md"
    bad.write_bytes(b"caf\xe9 [cite: 1]\n")
    assert run(capsys, "scan", str(bad))[0] == 2
    assert run(capsys, "scan", str(tmp_path / "missing.md"))[0] == 2
    assert run(capsys, "scan", str(tmp_path))[0] == 2


def test_pattern_selection_is_narrower_than_the_whole_reference(
    capsys: pytest.CaptureFixture[str],
) -> None:
    everything = json.loads(run(capsys, "patterns", "--list", "--format", "json")[1])[
        "sections"
    ]
    class_a = json.loads(
        run(capsys, "patterns", "--class", "A", "--format", "json")[1]
    )["sections"]
    assert class_a and len(class_a) < len(everything)
    assert {s["class"] for s in class_a} == {"A"}
    assert run(capsys, "patterns")[0] == 2
    assert run(capsys, "patterns", "--name", "no such pattern anywhere")[0] == 2


@pytest.mark.parametrize(
    "quoted",
    [
        '"[cite: 1]"',
        "“[cite: 1]”",
        '"`literal` [cite: 1]"',
        '"https://example.org/a [cite: 1]"',
    ],
)
def test_mechanical_fix_preserves_short_and_nested_quoted_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], quoted: str
) -> None:
    text = f"The response was {quoted}.\n\nBody.[cite: 2]\n"
    source = write(tmp_path, text)
    output = tmp_path / "cleaned.md"
    code, _, error = run(
        capsys, "fix", str(source), "--select", "HUM001", "--output", str(output)
    )
    assert code == 0, error
    assert output.read_text(encoding="utf-8") == text.replace("Body.[cite: 2]", "Body.")


@pytest.mark.parametrize(
    "protected",
    [
        "\ufeff> Thanks. Let me know if you need anything.\n> Evidence.\n",
        "\ufeff```text\n\nCertainly! [cite: 1]\n```\n",
        "- Example:\n\n      Great question! Our hours are 9-5.\n",
        "- item\n\n```sh\nmake\n```\n\n    Certainly! sample output\n",
        "> The support bot replied: Thanks for reaching out.\nI hope this helps!\n",
        "Done. Let me know if you want me to run `make deploy` against https://prod.example.com/x.\n",
        "See https://example.org/turn0search0 for evidence.\n",
        'Use a 2" pipe. The log said "index miss [cite: 3] for shard four".\n',
    ],
)
def test_cleanup_preserves_protected_evidence_at_markdown_boundaries(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], protected: str
) -> None:
    text = protected + "\nBody.[cite: 2]\n"
    source = write(tmp_path, text)
    output = tmp_path / "cleaned.md"
    code, _, error = run(
        capsys, "fix", str(source), "--select", "HUM001,HUM005", "--output", str(output)
    )
    assert code == 0, error
    assert output.read_text(encoding="utf-8") == text.replace("Body.[cite: 2]", "Body.")


def test_cr_only_cleanup_never_consumes_the_next_factual_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = "Intro done.\rLet me know if you have questions\rThe deploy runs at 5pm.\r"
    output = tmp_path / "cleaned.md"
    code, report, error = run(
        capsys,
        "fix",
        str(write(tmp_path, text)),
        "--select",
        "HUM001,HUM005",
        "--output",
        str(output),
    )
    assert code == 0, error
    assert json.loads(report)["status"] == "no_changes"
    assert not output.exists()
