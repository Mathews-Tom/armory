"""Contract tests for declared model-fit targets and dry-run manifests."""

from __future__ import annotations

from pathlib import Path

import pytest

import scripts.model_fit as model_fit
from scripts.install import PackageInfo
from scripts.package_types import TYPES


def _config_text(
    required_telemetry: str = "[model, usage.input_tokens, usage.output_tokens]",
) -> str:
    return f"""\
schema_version: 1
raw_receipt_retention: derived-only
targets:
  - id: claude-code-opus-xhigh
    client: claude-code
    model: opus
    expected_model_prefix: claude-opus-
    effort: xhigh
    profiles: [core, full]
    tool_surface: []
    required_telemetry: {required_telemetry}
"""


def _write_config(tmp_path: Path, text: str | None = None) -> Path:
    path = tmp_path / "model_fit.yaml"
    path.write_text(text or _config_text(), encoding="utf-8")
    return path


def test_loads_declared_target(tmp_path: Path) -> None:
    config = model_fit.load_model_fit_config(_write_config(tmp_path))

    assert config.schema_version == 1
    assert config.raw_receipt_retention == "derived-only"
    assert config.targets[0].model == "opus"
    assert config.targets[0].expected_model_prefix == "claude-opus-"
    assert config.targets[0].profiles == ("core", "full")


def test_incomplete_target_names_missing_field(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = _write_config(
        tmp_path, _config_text().replace("    model: opus\n", "")
    )

    result = model_fit.main(
        [
            "--config",
            str(config_path),
            "--target",
            "claude-code-opus-xhigh",
            "--dry-run",
        ]
    )

    assert result == 2
    assert "targets[0].model must be a non-empty string" in capsys.readouterr().err


def test_rejects_undeclared_telemetry(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, _config_text("[model, estimated_tokens]"))

    with pytest.raises(model_fit.ModelFitConfigError, match="estimated_tokens"):
        model_fit.load_model_fit_config(config_path)


def test_rejects_target_without_required_model_telemetry(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, _config_text("[usage.input_tokens]"))

    with pytest.raises(model_fit.ModelFitConfigError, match="must include 'model'"):
        model_fit.load_model_fit_config(config_path)


def test_rejects_undeclared_target(tmp_path: Path) -> None:
    config = model_fit.load_model_fit_config(_write_config(tmp_path))

    with pytest.raises(model_fit.ModelFitConfigError, match="undeclared target"):
        model_fit.select_target(config, "not-declared")


def test_profile_manifest_rejects_missing_definition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = PackageInfo(
        name="present",
        version="1.0.0",
        description="",
        source_path=tmp_path,
        pkg_type=TYPES["skill"],
    )
    monkeypatch.setattr(
        model_fit,
        "load_profiles",
        lambda: {
            "core": {"packages": {"skills": ["present", "missing"]}},
        },
    )
    monkeypatch.setattr(model_fit, "discover_packages", lambda: [package])

    with pytest.raises(model_fit.ModelFitConfigError, match="skill/missing"):
        model_fit.resolve_profile_manifest("core")


def test_dry_run_keeps_discovery_separate_from_loaded_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = model_fit.load_model_fit_config(_write_config(tmp_path))
    target = config.targets[0]
    monkeypatch.setattr(
        model_fit,
        "resolve_profile_manifest",
        lambda profile: model_fit.ProfileManifest(profile=profile, packages=()),
    )
    monkeypatch.setattr(
        model_fit, "probe_client_version", lambda: "2.1.241 (Claude Code)"
    )

    result = model_fit.dry_run(target, ("core",))

    assert result["schema_version"] == model_fit.SCHEMA_VERSION
    assert result["model_request_made"] is False
    assert result["package_content_observation"] == "not-loaded"
    assert result["client_version"] == "2.1.241 (Claude Code)"
    assert result["profile_manifests"] == [{"profile": "core", "packages": []}]


def test_dry_run_rejects_profile_outside_target(tmp_path: Path) -> None:
    config = model_fit.load_model_fit_config(_write_config(tmp_path))

    with pytest.raises(model_fit.ModelFitConfigError, match="does not declare profile"):
        model_fit.dry_run(config.targets[0], ("developer",))
