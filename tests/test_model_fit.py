"""Contract tests for declared model-fit targets and dry-run manifests."""

from __future__ import annotations

import json
import subprocess
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


def _stream_output(
    *,
    model: str = "claude-opus-4-7-20250219",
    output_tokens: int | None = 4,
) -> str:
    usage: dict[str, int] = {"input_tokens": 11}
    if output_tokens is not None:
        usage["output_tokens"] = output_tokens
    return "\n".join(
        (
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "model": model,
                        "content": "sensitive assistant text",
                    },
                }
            ),
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "stop_reason": "end_turn",
                    "usage": usage,
                }
            ),
        )
    )


class _FakeProcess:
    def __init__(
        self,
        *,
        stdout: str,
        returncode: int = 0,
        timeout_once: bool = False,
    ) -> None:
        self.pid = 123
        self.returncode = returncode
        self._stdout = stdout
        self._timeout_once = timeout_once

    def communicate(self, timeout: int | None = None) -> tuple[str, str]:
        if timeout is not None and self._timeout_once:
            self._timeout_once = False
            raise subprocess.TimeoutExpired(["claude"], timeout)
        return self._stdout, ""


def test_probe_command_isolated_and_toolless(tmp_path: Path) -> None:
    target = model_fit.load_model_fit_config(_write_config(tmp_path)).targets[0]

    command = model_fit._probe_command(target)

    assert command == [
        "claude",
        "-p",
        "Reply with exactly READY.",
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        "opus",
        "--effort",
        "xhigh",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--tools",
        "",
    ]


def test_capture_maps_client_fields_without_retaining_raw_text(tmp_path: Path) -> None:
    target = model_fit.load_model_fit_config(_write_config(tmp_path)).targets[0]
    observed, terminal_metadata = model_fit._capture_from_events(
        model_fit._parse_stream_events(_stream_output()),
        target,
    )

    assert observed == {
        "model": "claude-opus-4-7-20250219",
        "usage": {"input_tokens": 11, "output_tokens": 4},
    }
    assert terminal_metadata == {"subtype": "success", "stop_reason": "end_turn"}
    assert "sensitive assistant text" not in json.dumps(observed | terminal_metadata)


def test_capture_rejects_missing_required_telemetry(tmp_path: Path) -> None:
    target = model_fit.load_model_fit_config(_write_config(tmp_path)).targets[0]

    with pytest.raises(
        model_fit.ModelFitCaptureError,
        match=r"usage\.output_tokens",
    ):
        model_fit._capture_from_events(
            model_fit._parse_stream_events(_stream_output(output_tokens=None)),
            target,
        )


def test_live_probe_writes_derived_receipt_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = model_fit.load_model_fit_config(_write_config(tmp_path)).targets[0]
    monkeypatch.setattr(
        model_fit,
        "resolve_profile_manifest",
        lambda profile: model_fit.ProfileManifest(profile=profile, packages=()),
    )
    monkeypatch.setattr(
        model_fit, "probe_client_version", lambda: "2.1.241 (Claude Code)"
    )
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    process = _FakeProcess(stdout=_stream_output())

    def fake_popen(*args: object, **kwargs: object) -> _FakeProcess:
        calls.append((args, kwargs))
        return process

    monkeypatch.setattr(model_fit.subprocess, "Popen", fake_popen)

    receipt = model_fit.live_probe(target, ("core",), timeout_seconds=10)
    output_path = tmp_path / "receipt.json"
    model_fit.write_receipt(output_path, receipt)

    persisted = output_path.read_text(encoding="utf-8")
    assert receipt["schema_version"] == model_fit.SCHEMA_VERSION
    assert receipt["mode"] == "live"
    assert receipt["model_request_made"] is True
    assert receipt["raw_receipt_retention"] == "derived-only"
    assert receipt["package_content_observation"] == "not-observed"
    assert receipt["tool_surface"] == {"declared": [], "observed": "not-disclosed"}
    assert calls[0][1]["start_new_session"] is True
    assert "sensitive assistant text" not in persisted


def test_live_mode_requires_output_path(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="2"):
        model_fit.main(
            [
                "--config",
                str(_write_config(tmp_path)),
                "--target",
                "claude-code-opus-xhigh",
                "--live",
            ]
        )


def test_capture_rejects_model_outside_declared_prefix(tmp_path: Path) -> None:
    target = model_fit.load_model_fit_config(_write_config(tmp_path)).targets[0]

    with pytest.raises(
        model_fit.ModelFitCaptureError, match="does not match expected prefix"
    ):
        model_fit._capture_from_events(
            model_fit._parse_stream_events(
                _stream_output(model="claude-sonnet-4-7-20250219"),
            ),
            target,
        )


def test_stream_parser_skips_blank_lines(tmp_path: Path) -> None:
    target = model_fit.load_model_fit_config(_write_config(tmp_path)).targets[0]

    events = model_fit._parse_stream_events(f"\n{_stream_output()}\n\n")
    observed, _metadata = model_fit._capture_from_events(events, target)

    assert observed["model"] == "claude-opus-4-7-20250219"


@pytest.mark.parametrize(
    ("stream", "message"),
    [
        ("", "client emitted no stream-json events"),
        ("not json", "malformed stream-json"),
        ('{"type":"assistant","message":[]}', "malformed client disclosure"),
        (
            chr(10).join(
                (
                    '{"type":"assistant","message":{"model":"claude-opus-4-7-20250219"}}',
                    '{"type":"result","is_error":false,"usage":{}}',
                    '{"type":"result","is_error":false,"usage":{}}',
                )
            ),
            "expected exactly one terminal result event",
        ),
    ],
)
def test_capture_rejects_malformed_client_disclosures(
    tmp_path: Path,
    stream: str,
    message: str,
) -> None:
    target = model_fit.load_model_fit_config(_write_config(tmp_path)).targets[0]

    with pytest.raises(model_fit.ModelFitCaptureError, match=message):
        events = model_fit._parse_stream_events(stream)
        model_fit._capture_from_events(events, target)


def test_capture_rejects_error_terminal(tmp_path: Path) -> None:
    target = model_fit.load_model_fit_config(_write_config(tmp_path)).targets[0]
    stream = chr(10).join(
        (
            '{"type":"assistant","message":{"model":"claude-opus-4-7-20250219"}}',
            '{"type":"result","is_error":true,"usage":{"input_tokens":1,"output_tokens":1}}',
        )
    )

    with pytest.raises(model_fit.ModelFitCaptureError, match="is_error: false"):
        model_fit._capture_from_events(model_fit._parse_stream_events(stream), target)


def test_live_probe_rejects_nonzero_client_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = model_fit.load_model_fit_config(_write_config(tmp_path)).targets[0]
    monkeypatch.setattr(
        model_fit,
        "resolve_profile_manifest",
        lambda profile: model_fit.ProfileManifest(profile=profile, packages=()),
    )
    monkeypatch.setattr(
        model_fit, "probe_client_version", lambda: "2.1.241 (Claude Code)"
    )
    monkeypatch.setattr(
        model_fit.subprocess,
        "Popen",
        lambda *args, **kwargs: _FakeProcess(stdout="", returncode=1),
    )

    with pytest.raises(model_fit.ModelFitCaptureError, match="status 1"):
        model_fit.live_probe(target, ("core",), timeout_seconds=10)


def test_live_probe_kills_process_group_on_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = model_fit.load_model_fit_config(_write_config(tmp_path)).targets[0]
    monkeypatch.setattr(
        model_fit,
        "resolve_profile_manifest",
        lambda profile: model_fit.ProfileManifest(profile=profile, packages=()),
    )
    monkeypatch.setattr(
        model_fit, "probe_client_version", lambda: "2.1.241 (Claude Code)"
    )
    monkeypatch.setattr(
        model_fit.subprocess,
        "Popen",
        lambda *args, **kwargs: _FakeProcess(stdout="", timeout_once=True),
    )
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(
        model_fit.os,
        "killpg",
        lambda pid, sig: killed.append((pid, sig)),
    )

    with pytest.raises(model_fit.ModelFitCaptureError, match="timed out after 10"):
        model_fit.live_probe(target, ("core",), timeout_seconds=10)

    assert killed == [(123, model_fit.signal.SIGKILL)]


def test_live_probe_rejects_nonpositive_timeout(tmp_path: Path) -> None:
    target = model_fit.load_model_fit_config(_write_config(tmp_path)).targets[0]

    with pytest.raises(model_fit.ModelFitConfigError, match="greater than zero"):
        model_fit.live_probe(target, ("core",), timeout_seconds=0)


def test_main_deduplicates_selected_profiles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = _write_config(tmp_path)
    monkeypatch.setattr(
        model_fit,
        "resolve_profile_manifest",
        lambda profile: model_fit.ProfileManifest(profile=profile, packages=()),
    )
    monkeypatch.setattr(
        model_fit, "probe_client_version", lambda: "2.1.241 (Claude Code)"
    )

    result = model_fit.main(
        [
            "--config",
            str(config_path),
            "--target",
            "claude-code-opus-xhigh",
            "--profile",
            "full",
            "--profile",
            "core",
            "--profile",
            "full",
            "--dry-run",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert [manifest["profile"] for manifest in payload["profile_manifests"]] == [
        "full",
        "core",
    ]
