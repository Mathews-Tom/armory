from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine import commands
from engine.compare import compare_specs
from engine.receipts import COMPARISON_LIMITATIONS
from engine.spec import load_spec


_FIXTURES = Path(__file__).parent / "fixtures"


def _statuses(
    receipt: dict[str, list[dict[str, object]]], entity: str
) -> dict[str, list[str]]:
    statuses: dict[str, list[str]] = {}
    for change in receipt[entity]:
        status = change["status"]
        assert isinstance(status, list)
        assert all(isinstance(item, str) for item in status)
        statuses[str(change["id"])] = status
    return statuses


def test_compare_specs_classifies_disjoint_change_groups() -> None:
    receipt = compare_specs(
        load_spec((_FIXTURES / "spec-compare-base.yaml").read_text()),
        load_spec((_FIXTURES / "spec-compare-head.yaml").read_text()),
    )

    assert _statuses(receipt, "nodes") == {
        "added": ["added"],
        "changed": ["changed"],
        "moved": ["moved"],
        "removed": ["removed"],
        "unchanged": ["unchanged"],
    }
    assert _statuses(receipt, "edges") == {
        "added-edge": ["added"],
        "changed-edge": ["changed"],
        "removed-edge": ["removed"],
        "rerouted-edge": ["rerouted"],
    }
    changed_node = next(
        change for change in receipt["nodes"] if change["id"] == "changed"
    )
    moved_node = next(change for change in receipt["nodes"] if change["id"] == "moved")
    rerouted_edge = next(
        change for change in receipt["edges"] if change["id"] == "rerouted-edge"
    )
    assert changed_node["changed_fields"] == [
        {"path": "/label", "base": "Before", "head": "After"}
    ]
    assert moved_node["changed_fields"] == [
        {"path": "/zone", "base": "left", "head": "right"}
    ]
    assert rerouted_edge["changed_fields"] == [
        {"path": "/from", "base": "changed", "head": "moved"}
    ]


def test_compare_specs_canonicalizes_entity_order() -> None:
    receipt = compare_specs(
        load_spec((_FIXTURES / "spec-compare-base.yaml").read_text()),
        load_spec((_FIXTURES / "spec-compare-reordered.yaml").read_text()),
    )

    assert all(
        status == ["unchanged"] for status in _statuses(receipt, "nodes").values()
    )
    assert all(
        status == ["unchanged"] for status in _statuses(receipt, "edges").values()
    )


def test_compare_cli_always_includes_the_limitations_text(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = commands.main(
        [
            "compare",
            str(_FIXTURES / "spec-compare-base.yaml"),
            str(_FIXTURES / "spec-compare-head.yaml"),
        ]
    )
    captured = capsys.readouterr()

    assert code == commands.EXIT_OK
    assert captured.err == ""
    assert json.loads(captured.out)["limitations"] == COMPARISON_LIMITATIONS


def test_compare_cli_rejects_an_edge_without_an_authored_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = tmp_path / "missing-id.yaml"
    spec.write_text("nodes:\n  - id: a\n  - id: b\nedges:\n  - from: a\n    to: b\n")

    code = commands.main(["compare", str(spec), str(spec)])
    payload = json.loads(capsys.readouterr().out)

    assert code == commands.EXIT_FAILURE
    assert [finding["code"] for finding in payload["diagnostics"]] == [
        "compare/missing-edge-id"
    ]
    assert payload["limitations"] == COMPARISON_LIMITATIONS
