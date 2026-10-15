"""Native installed-file views on fictional homes; never runtime-enabled claims."""

from __future__ import annotations

import json
from pathlib import Path

import inventory_catalog
import pytest
from inventory_catalog import BLOCKING_COVERAGE, load_inventory

KEY = b"fictional-native-catalog-key-000000"


def skill(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "SKILL.md"
    target.write_text(
        f"---\nname: {name}\ndescription: Fictional native fixture.\n---\n\n# Scope\n"
    )
    return target


def json_file(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def claude_registry(home: Path, install: Path, *, version: int = 2) -> Path:
    target = home / ".claude/plugins/installed_plugins.json"
    json_file(
        target,
        {
            "version": version,
            "plugins": {
                "fictional-addon@fictional-market": [
                    {"scope": "user", "installPath": str(install)}
                ]
            },
        },
    )
    return target


def blocking(coverage: dict[str, int]) -> set[str]:
    return {code for code in BLOCKING_COVERAGE if coverage.get(code, 0)}


def test_claude_custom_directories_supplement_default_and_keep_namespaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    personal = skill(tmp_path / ".claude/skills/personal", "fictional-personal")
    install = tmp_path / "installed-addon"
    conventional = skill(install / "skills/conventional", "fictional-conventional")
    nested = skill(install / "extra/group/nested", "fictional-nested")
    direct = skill(install / "single", "fictional-single")
    json_file(
        install / ".claude-plugin/plugin.json",
        {
            "name": "fictional-addon",
            "skills": ["./extra", "./single"],
        },
    )
    claude_registry(tmp_path, install)

    inventory = load_inventory("claude", key=KEY)
    assert {entry.name for entry in inventory.entries} == {
        "fictional-personal",
        "fictional-addon:fictional-conventional",
        "fictional-addon:fictional-nested",
        "fictional-addon:fictional-single",
    }
    assert inventory.resolve_direct(str(personal)) == "fictional-personal"
    assert (
        inventory.resolve_direct(str(conventional))
        == "fictional-addon:fictional-conventional"
    )
    assert inventory.resolve_direct(str(nested)) == "fictional-addon:fictional-nested"
    assert inventory.resolve_direct(str(direct)) == "fictional-addon:fictional-single"
    assert {entry.ownership for entry in inventory.entries if ":" in entry.name} == {
        "protected"
    }
    assert not blocking(inventory.coverage)


def test_claude_manifest_absence_uses_only_known_conventional_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    install = tmp_path / "installed-addon"
    skill(install / "skills/known", "fictional-known")
    skill(install / "not-declared/hidden", "fictional-not-declared")
    claude_registry(tmp_path, install)
    inventory = load_inventory("claude", key=KEY)
    assert [entry.name for entry in inventory.entries] == [
        "fictional-addon:fictional-known"
    ]
    assert not blocking(inventory.coverage)


@pytest.mark.parametrize("version", [1, 3])
def test_unknown_claude_registry_version_does_not_claim_plugin_absence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: int,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    skill(tmp_path / ".claude/skills/personal", "fictional-personal")
    install = tmp_path / "installed-addon"
    skill(install / "skills/known", "fictional-known")
    claude_registry(tmp_path, install, version=version)
    inventory = load_inventory("claude", key=KEY)
    assert [entry.name for entry in inventory.entries] == ["fictional-personal"]
    assert blocking(inventory.coverage) == {"plugin_registry_unsupported_version"}


def test_declared_missing_resource_and_registry_drift_are_not_silent_zeros(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    install = tmp_path / "installed-addon"
    skill(install / "skills/known", "fictional-known")
    manifest = install / ".claude-plugin/plugin.json"
    json_file(manifest, {"name": "fictional-addon"})
    claude_registry(tmp_path, install)
    initial = load_inventory("claude", key=KEY)
    json_file(manifest, {"name": "fictional-addon", "skills": ["./missing"]})
    changed = load_inventory("claude", key=KEY)
    assert [entry.name for entry in changed.entries] == [
        "fictional-addon:fictional-known"
    ]
    assert "skill_root_unusable" in blocking(changed.coverage)
    assert changed.integrity != initial.integrity


def test_plugin_inner_alias_cannot_read_outside_declared_install_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    install = tmp_path / "installed-addon"
    install.mkdir()
    outside = tmp_path / "not-approved"
    skill(outside / "secret", "fictional-forbidden")
    (install / "escape").symlink_to(outside, target_is_directory=True)
    json_file(
        install / ".claude-plugin/plugin.json",
        {"name": "fictional-addon", "skills": "./escape"},
    )
    claude_registry(tmp_path, install)
    real_open = inventory_catalog.open_regular

    def guarded(path: Path | str) -> tuple[int, object]:
        assert not Path(path).is_relative_to(outside)
        return real_open(path)

    monkeypatch.setattr(inventory_catalog, "open_regular", guarded)
    inventory = load_inventory("claude", key=KEY)
    assert inventory.entries == []
    assert "alias_escape" in blocking(inventory.coverage)


def test_codex_system_shared_and_cached_versions_are_protected_not_enabled_views(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    skill(tmp_path / ".codex/skills/.system/creator", "fictional-creator")
    skill(tmp_path / ".agents/skills/shared", "fictional-shared")
    plugin = tmp_path / ".codex/plugins/cache/fictional-market/addon"
    json_file(
        plugin / ".codex-remote-plugin-install.json",
        {
            "schema_version": 1,
            "remote_plugin_id": "fictional-remote-id",
        },
    )
    for version in ("1.0.0", "2.0.0"):
        install = plugin / version
        skill(install / "single", "fictional-cached")
        skill(install / "skills/unlisted", "fictional-unlisted")
        json_file(
            install / ".codex-plugin/plugin.json",
            {"name": "fictional-addon", "skills": "./single"},
        )
    staged = tmp_path / ".codex/plugins/.remote-plugin-install-staging/fictional-stage"
    skill(staged / "skills/staged", "fictional-staged")
    json_file(
        staged / ".codex-plugin/plugin.json",
        {"name": "fictional-stage", "skills": "./skills"},
    )

    inventory = load_inventory("codex", key=KEY)
    assert sorted(entry.name for entry in inventory.entries) == [
        "fictional-addon:fictional-cached",
        "fictional-addon:fictional-cached",
        "fictional-creator",
        "fictional-shared",
    ]
    assert {entry.ownership for entry in inventory.entries} == {"protected"}
    assert inventory.coverage["duplicate_name"] == 1
    assert inventory.coverage["codex_cache_is_not_active_plugin_selection"] == 1
    assert not blocking(inventory.coverage)


def test_unknown_remote_install_schema_refuses_the_plugin_view(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    skill(tmp_path / ".codex/skills/personal", "fictional-personal")
    plugin = tmp_path / ".codex/plugins/cache/fictional-market/addon"
    install = plugin / "1.0.0"
    skill(install / "skills/known", "fictional-known")
    json_file(
        install / ".codex-plugin/plugin.json",
        {"name": "fictional-addon", "skills": "./skills"},
    )
    json_file(
        plugin / ".codex-remote-plugin-install.json",
        {
            "schema_version": 2,
            "remote_plugin_id": "fictional-remote-id",
        },
    )
    inventory = load_inventory("codex", key=KEY)
    assert [entry.name for entry in inventory.entries] == ["fictional-personal"]
    assert blocking(inventory.coverage) == {"plugin_install_unsupported_version"}


@pytest.mark.parametrize("resources", [{}, {"skills": []}])
def test_codex_default_skill_directory_is_optional_and_plugin_qualified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resources: dict[str, object]
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    skill(tmp_path / ".codex/skills/personal", "fictional-shared-name")
    cache = tmp_path / ".codex/plugins/cache/fictional-market"
    install = cache / "addon/1.0.0"
    skill(install / "skills/nested", "fictional-shared-name")
    json_file(
        install / ".codex-plugin/plugin.json",
        {"name": "fictional-addon", **resources},
    )
    json_file(
        cache / "no-skills/1.0.0/.codex-plugin/plugin.json",
        {"name": "fictional-no-skills", **resources},
    )
    inventory = load_inventory("codex", key=KEY)
    assert sorted(entry.name for entry in inventory.entries) == [
        "fictional-addon:fictional-shared-name",
        "fictional-shared-name",
    ]
    assert inventory.coverage["duplicate_name"] == 0
    assert inventory.coverage["plugins_without_skill_directory"] == 1
    assert not blocking(inventory.coverage)


@pytest.mark.parametrize("declared", ["", ".", "./", "skills"])
def test_invalid_codex_resource_cannot_widen_the_plugin_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, declared: str
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    install = tmp_path / ".codex/plugins/cache/fictional-market/addon/1.0.0"
    skill(install / "unlisted", "fictional-unlisted")
    skill(install / "skills/contained", "fictional-contained")
    json_file(
        install / ".codex-plugin/plugin.json",
        {"name": "fictional-addon", "skills": declared},
    )
    inventory = load_inventory("codex", key=KEY)
    assert inventory.entries == []
    assert "plugin_manifest_invalid" in blocking(inventory.coverage)
