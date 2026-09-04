"""Tests for fetch_icons.py — cache building from a fake Source (no network)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import fetch_icons
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@dataclass
class FakeSource:
    """Deterministic Source backed by committed fixtures — real converted
    content, zero network calls."""

    stencil_text: dict[str, str] = field(default_factory=dict)
    tree: dict[str, list[str]] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def fetch_text(self, path: str) -> str:
        self.calls.append(path)
        if path in self.stencil_text:
            return self.stencil_text[path]
        if path in self.files:
            return self.files[path]
        raise FileNotFoundError(path)

    def list_tree(self, prefix: str, suffix: str) -> list[str]:
        return list(self.tree.get(prefix, []))


def _real_aws_gcp_source() -> FakeSource:
    return FakeSource(
        stencil_text={
            fetch_icons.STENCIL_PATHS["aws"]: (
                FIXTURES / "real_shapes.xml"
            ).read_text(),
            fetch_icons.STENCIL_PATHS["gcp"]: (
                FIXTURES / "real_shapes.xml"
            ).read_text(),
        }
    )


def _azure_source(count: int = 2) -> FakeSource:
    azure_svg = (FIXTURES / "azure_virtual_machine.svg").read_text()
    paths = [
        f"{fetch_icons.AZURE_TREE_PREFIX}/compute/Icon-{i}.svg" for i in range(count)
    ]
    return FakeSource(
        tree={fetch_icons.AZURE_TREE_PREFIX: paths},
        files={p: azure_svg for p in paths},
    )


class TestConvertStencilProvider:
    def test_converts_every_shape_in_the_fixture(self) -> None:
        entries = fetch_icons.convert_stencil_provider(_real_aws_gcp_source(), "aws")
        names = {e.name for e in entries}
        assert names == {"lambda", "BigQuery"}

    def test_entries_carry_source_path(self) -> None:
        entries = fetch_icons.convert_stencil_provider(_real_aws_gcp_source(), "aws")
        assert all(e.source == fetch_icons.STENCIL_PATHS["aws"] for e in entries)

    def test_lambda_has_no_warnings(self) -> None:
        entries = fetch_icons.convert_stencil_provider(_real_aws_gcp_source(), "aws")
        lam = next(e for e in entries if e.name == "lambda")
        assert lam.warnings == []
        assert lam.slug == "lambda"


class TestConvertAzure:
    def test_fetches_every_listed_file_concurrently(self) -> None:
        source = _azure_source(count=5)
        entries = fetch_icons.convert_azure(source, max_workers=4)
        assert len(entries) == 5
        assert all(e.warnings == [] for e in entries)
        assert all(e.body for e in entries)

    def test_each_icon_independently_namespaced(self) -> None:
        """Two Azure entries converted in the same run must not share ids —
        this is convert_azure calling inline_svg with a distinct slug per
        file, verified end to end rather than just at the svg_inline unit."""
        entries = fetch_icons.convert_azure(_azure_source(count=2), max_workers=2)
        all_ids = []
        for e in entries:
            all_ids.extend(re.findall(r'id="([^"]+)"', e.body))
        assert len(all_ids) == len(set(all_ids))


class TestCacheWriting:
    def test_writes_one_json_file_per_icon(self, tmp_path: Path) -> None:
        entries = fetch_icons.convert_stencil_provider(_real_aws_gcp_source(), "aws")
        stats = fetch_icons.write_cache(tmp_path, "deadbeef", "aws", entries)
        provider_dir = tmp_path / "deadbeef" / "aws"
        written = sorted(p.name for p in provider_dir.glob("*.json"))
        assert written == ["bigquery.json", "lambda.json"]
        assert stats["count"] == 2
        icon_records = stats["icons"]
        assert isinstance(icon_records, dict)
        assert icon_records["lambda.json"]["sha256"] == fetch_icons._sha256(
            (provider_dir / "lambda.json").read_bytes()
        )

    def test_cache_entry_is_directly_usable_by_a_renderer(self, tmp_path: Path) -> None:
        entries = fetch_icons.convert_stencil_provider(_real_aws_gcp_source(), "aws")
        fetch_icons.write_cache(tmp_path, "deadbeef", "aws", entries)
        payload = json.loads(
            (tmp_path / "deadbeef" / "aws" / "lambda.json").read_text()
        )
        assert payload["viewBox"] == "0 0 54.05 56"
        assert "<path" in payload["body"]
        assert payload["warnings"] == []

    def test_slug_collision_gets_a_numeric_suffix_not_overwritten(
        self, tmp_path: Path
    ) -> None:
        a = fetch_icons.IconEntry(
            slug="dup", name="Dup A", view_box="0 0 1 1", body="<path/>a", source="x"
        )
        b = fetch_icons.IconEntry(
            slug="dup", name="Dup B", view_box="0 0 1 1", body="<path/>b", source="x"
        )
        fetch_icons.write_cache(tmp_path, "sha", "aws", [a, b])
        names = sorted(p.name for p in (tmp_path / "sha" / "aws").glob("*.json"))
        assert names == ["dup-1.json", "dup.json"]

    def test_warned_count_reflects_conversion_warnings(self, tmp_path: Path) -> None:
        ok = fetch_icons.IconEntry(
            slug="ok", name="OK", view_box="0 0 1 1", body="<path/>", source="x"
        )
        bad = fetch_icons.IconEntry(
            slug="bad",
            name="Bad",
            view_box="0 0 1 1",
            body="",
            source="x",
            warnings=["oops"],
        )
        stats = fetch_icons.write_cache(tmp_path, "sha", "aws", [ok, bad])
        assert stats["warned"] == 1
        assert stats["count"] == 2


class TestManifest:
    def test_creates_manifest_with_per_icon_digests_and_terms(
        self, tmp_path: Path
    ) -> None:
        entry = fetch_icons.IconEntry(
            slug="lambda",
            name="lambda",
            view_box="0 0 1 1",
            body="<path/>",
            source="fixture",
        )
        stats = fetch_icons.write_cache(tmp_path, "sha1", "aws", [entry])
        fetch_icons.update_manifest(tmp_path, "sha1", "aws", stats)
        manifest = json.loads((tmp_path / "sha1" / "manifest.json").read_text())

        assert manifest["format_version"] == fetch_icons.CACHE_MANIFEST_VERSION
        assert manifest["sha"] == "sha1"
        assert manifest["license_note"]["aws"] == fetch_icons.LICENSE_NOTE["aws"]
        record = manifest["providers"]["aws"]["icons"]["lambda.json"]
        assert record["sha256"] == fetch_icons._sha256(
            (tmp_path / "sha1" / "aws" / "lambda.json").read_bytes()
        )
        assert record["source"] == "fixture"
        assert record["terms"] == fetch_icons.LICENSE_NOTE["aws"]["terms"]

    def test_merges_across_multiple_providers(self, tmp_path: Path) -> None:
        aws = fetch_icons.write_cache(
            tmp_path,
            "sha1",
            "aws",
            [
                fetch_icons.IconEntry(
                    slug="lambda",
                    name="lambda",
                    view_box="0 0 1 1",
                    body="<path/>",
                    source="fixture",
                )
            ],
        )
        gcp = fetch_icons.write_cache(
            tmp_path,
            "sha1",
            "gcp",
            [
                fetch_icons.IconEntry(
                    slug="bigquery",
                    name="bigquery",
                    view_box="0 0 1 1",
                    body="<path/>",
                    source="fixture",
                )
            ],
        )
        fetch_icons.update_manifest(tmp_path, "sha1", "aws", aws)
        fetch_icons.update_manifest(tmp_path, "sha1", "gcp", gcp)
        manifest = json.loads((tmp_path / "sha1" / "manifest.json").read_text())
        assert set(manifest["providers"]) == {"aws", "gcp"}
        assert manifest["providers"]["aws"]["count"] == 1
        assert manifest["providers"]["gcp"]["count"] == 1


class TestFetchProviderCaching:
    def test_skips_refetch_when_already_cached(self, tmp_path: Path) -> None:
        source = _real_aws_gcp_source()
        fetch_icons.fetch_provider(source, tmp_path, "sha1", "aws", force=False)
        assert len(source.calls) == 1
        fetch_icons.fetch_provider(source, tmp_path, "sha1", "aws", force=False)
        assert len(source.calls) == 1, (
            "second call should have hit the cache, not the source"
        )

    def test_force_refetches_even_when_cached(self, tmp_path: Path) -> None:
        source = _real_aws_gcp_source()
        fetch_icons.fetch_provider(source, tmp_path, "sha1", "aws", force=False)
        fetch_icons.fetch_provider(source, tmp_path, "sha1", "aws", force=True)
        assert len(source.calls) == 2

    def test_rebuilds_a_legacy_manifest_with_per_icon_digests(
        self, tmp_path: Path
    ) -> None:
        source = _real_aws_gcp_source()
        fetch_icons.fetch_provider(source, tmp_path, "sha1", "aws", force=False)
        (tmp_path / "sha1" / "manifest.json").write_text(
            json.dumps({"sha": "sha1", "providers": {"aws": {"count": 2}}})
        )

        stats = fetch_icons.fetch_provider(source, tmp_path, "sha1", "aws", force=False)
        manifest = json.loads((tmp_path / "sha1" / "manifest.json").read_text())

        assert len(source.calls) == 2
        assert stats["count"] == 2
        assert manifest["format_version"] == fetch_icons.CACHE_MANIFEST_VERSION
        assert manifest["providers"]["aws"]["icons"]["lambda.json"]["sha256"] == (
            fetch_icons._sha256(
                (tmp_path / "sha1" / "aws" / "lambda.json").read_bytes()
            )
        )

    def test_unknown_provider_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="unknown provider"):
            fetch_icons.fetch_provider(
                _real_aws_gcp_source(), tmp_path, "sha1", "bogus", force=False
            )


class TestDefaultCacheDir:
    def test_respects_xdg_cache_home(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XDG_CACHE_HOME", "/tmp/xdg-test")
        assert fetch_icons.default_cache_dir() == Path(
            "/tmp/xdg-test/armory/cloud-icons"
        )

    def test_falls_back_to_home_cache(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
        assert (
            fetch_icons.default_cache_dir()
            == Path.home() / ".cache" / "armory" / "cloud-icons"
        )
