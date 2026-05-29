"""Tests for scripts/generate_adapters.py."""

from __future__ import annotations

from pathlib import Path

from scripts.generate_adapters import CodexAdapter, load_packages, truncate_description


class TestCodexAdapter:
    def test_generated_root_stays_within_size_budget(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "adapters" / "codex"
        adapter = CodexAdapter(output_dir)

        adapter.generate(load_packages())

        root = output_dir / "AGENTS.md"
        assert root.exists()
        assert len(root.read_bytes()) <= adapter.SIZE_BUDGET_BYTES
        assert adapter.validate() == []

    def test_root_description_limit_matches_shared_truncation_default(self) -> None:
        assert CodexAdapter.ROOT_DESCRIPTION_MAX_CHARS == 200
        truncated = truncate_description(
            "word " * 80, CodexAdapter.ROOT_DESCRIPTION_MAX_CHARS
        )

        assert len(truncated) <= CodexAdapter.ROOT_DESCRIPTION_MAX_CHARS
