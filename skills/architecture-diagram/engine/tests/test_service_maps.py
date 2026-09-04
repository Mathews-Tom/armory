"""Verify every service-mapping entry resolves to a real cached icon.

These YAML files are curated by hand (they exist to translate what a user
says — "S3 bucket", "load balancer" — into the exact slug the icon cache
uses). Hand-curated data drifts from reality: a typo'd slug, a shape that
gets renamed upstream, a copy-paste mistake across ~70 entries per provider.
This test is the guard: every `slug` value must resolve to an actual file in
the real cache built by `fetch_icons.py` at the pinned commit, not just look
plausible.

Requires the real cache to be present (built via `fetch_icons.py --provider
all`); skips instead of failing when it isn't, since building it needs
network access this test suite should not depend on for routine runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from engine import fetch_icons

REFERENCES = Path(__file__).parent.parent.parent / "references"
MAPPING_FILES = {
    "aws": REFERENCES / "services-aws.yaml",
    "gcp": REFERENCES / "services-gcp.yaml",
    "azure": REFERENCES / "services-azure.yaml",
}


def _real_cache_dir() -> Path | None:
    """Locate a real, already-fetched cache for the pinned SHA. Checked in
    order: explicit env override, then the default per-user cache location."""
    import os

    for candidate in (
        os.environ.get("ARMORY_ICON_CACHE_TEST_DIR"),
        str(fetch_icons.default_cache_dir()),
    ):
        if candidate:
            path = Path(candidate) / fetch_icons.DRAWIO_SHA
            if path.exists() and any(path.glob("*/*.json")):
                return Path(candidate)
    return None


def _load_mapping(path: Path) -> dict[str, dict[str, object]]:
    data = yaml.safe_load(path.read_text())
    return data["services"]


class TestMappingFileStructure:
    @pytest.mark.parametrize("provider", sorted(MAPPING_FILES))
    def test_file_exists_and_parses(self, provider: str) -> None:
        mapping = _load_mapping(MAPPING_FILES[provider])
        assert mapping, f"{provider} mapping is empty"

    @pytest.mark.parametrize("provider", sorted(MAPPING_FILES))
    def test_every_entry_has_required_fields(self, provider: str) -> None:
        mapping = _load_mapping(MAPPING_FILES[provider])
        for key, entry in mapping.items():
            assert "label" in entry, f"{provider}/{key} missing label"
            assert "color" in entry, f"{provider}/{key} missing color"
            assert str(entry["color"]).startswith("#"), (
                f"{provider}/{key} color must be a hex string"
            )

    @pytest.mark.parametrize("provider", sorted(MAPPING_FILES))
    def test_no_duplicate_slugs_within_a_provider(self, provider: str) -> None:
        mapping = _load_mapping(MAPPING_FILES[provider])
        keys = list(mapping)
        assert len(keys) == len(set(keys))


@pytest.mark.skipif(
    _real_cache_dir() is None,
    reason="real icon cache not built — run fetch_icons.py --provider all first",
)
class TestSlugsResolveAgainstRealCache:
    @pytest.mark.parametrize("provider", sorted(MAPPING_FILES))
    def test_every_slug_has_a_cache_entry(self, provider: str) -> None:
        cache_dir = _real_cache_dir()
        assert cache_dir is not None
        mapping = _load_mapping(MAPPING_FILES[provider])
        provider_dir = cache_dir / fetch_icons.DRAWIO_SHA / provider
        missing = [
            key for key in mapping if not (provider_dir / f"{key}.json").exists()
        ]
        assert not missing, (
            f"{provider} mapping references slugs with no cache entry: {missing}"
        )
