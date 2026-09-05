from __future__ import annotations

import pytest

from engine.compare import compare_specs
from engine.spec import SpecError, load_spec

_VALID_SOURCE = "a" * 40


def _valid_spec(*, node_sources: str = "    sources: [src-api]\n") -> str:
    return f"""sources:
  - id: src-api
    revision: {_VALID_SOURCE}
    path: src/api.py
    lines: [1, 3]
nodes:
  - id: api
{node_sources}  - id: db
edges:
  - id: api-to-db
    from: api
    to: db
    sources: [src-api]
"""


def _code(text: str) -> str:
    with pytest.raises(SpecError) as raised:
        load_spec(text)
    return raised.value.diagnostic.code


def test_parses_source_declarations_and_entity_attachments() -> None:
    spec = load_spec(_valid_spec())

    assert [
        (source.id, source.revision, source.path, source.lines)
        for source in spec.sources
    ] == [("src-api", _VALID_SOURCE, "src/api.py", (1, 3))]
    assert spec.nodes[0].sources == ("src-api",)
    assert spec.edges[0].sources == ("src-api",)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            _valid_spec().replace(
                "    lines: [1, 3]\n",
                "    lines: [1, 3]\n  - id: src-api\n",
                1,
            ),
            "source/duplicate-id",
        ),
        (_valid_spec().replace(_VALID_SOURCE, "a" * 39), "source/invalid-revision"),
        (
            _valid_spec().replace("path: src/api.py", "path: ../api.py"),
            "source/invalid-path",
        ),
        (
            _valid_spec().replace("lines: [1, 3]", "lines: [0, 3]"),
            "source/invalid-line-range",
        ),
        (
            _valid_spec().replace("lines: [1, 3]", "lines: [3, 1]"),
            "source/invalid-line-range",
        ),
        (
            _valid_spec(node_sources="    sources: [src-api, src-api]\n"),
            "source/duplicate-attachment",
        ),
        (
            _valid_spec(node_sources="    sources: [missing]\n"),
            "source/unknown-attachment",
        ),
    ],
)
def test_rejects_invalid_source_evidence_schema(text: str, expected: str) -> None:
    assert _code(text) == expected


def test_specs_without_source_declarations_keep_empty_authored_evidence() -> None:
    spec = load_spec("nodes:\n  - id: api\n")

    assert spec.sources == []
    assert spec.nodes[0].sources == ()


def test_compare_ignores_source_only_authored_changes() -> None:
    base = load_spec(_valid_spec())
    head = load_spec(
        _valid_spec(node_sources="    sources: []\n").replace(
            "sources: [src-api]\n", "sources: []\n", 1
        )
    )

    comparison = compare_specs(base, head)

    assert all(change["status"] == ["unchanged"] for change in comparison["nodes"])
    assert all(change["status"] == ["unchanged"] for change in comparison["edges"])
