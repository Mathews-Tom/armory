"""build_scene CLI: generation, loud failures, and (when Manim is installed) a real render."""

from __future__ import annotations

import ast
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from build_scene import main
from verify_video import probe_video

CONFIGS: dict[str, dict[str, object]] = {
    "data_flow": {
        "template": "data_flow",
        "title": 'Say "hi" it\'s 100%',
        "stages": [{"name": "Ingest"}, {"name": "Embed"}, {"name": "Serve"}],
        "final_hold_seconds": 1.0,
    },
    "comparison": {
        "template": "comparison",
        "title": "A vs B",
        "left": {"label": "A", "items": ["fast", "simple"]},
        "right": {"label": "B", "items": ["scalable", "flexible"]},
        "final_hold_seconds": 1.0,
    },
    "timeline": {
        "template": "timeline",
        "title": "History",
        "events": [
            {"label": "2017", "description": "Transformer"},
            {"label": "2018", "description": "BERT"},
            {"label": "2019", "description": "GPT-2"},
        ],
        "final_hold_seconds": 1.0,
    },
}


def _write_config(tmp_path: Path, name: str = "data_flow") -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(CONFIGS[name]), encoding="utf-8")
    return path


def test_generate_only_writes_a_parseable_scene_and_plan(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert (
        main([str(_write_config(tmp_path)), "--out-dir", str(out), "--generate-only"])
        == 0
    )
    ast.parse((out / "scene.py").read_text(encoding="utf-8"))
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    assert plan["scene_class"] == "DataFlowScene"
    assert plan["expected_duration_s"] == pytest.approx(3.2 + 1.3 * 3 + 1.0)
    assert not (out / "scene.mp4").exists()


def test_invalid_config_exits_2_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = dict(CONFIGS["data_flow"], stages=[{"name": "only one"}])
    config = tmp_path / "bad.json"
    config.write_text(json.dumps(bad), encoding="utf-8")
    out = tmp_path / "out"
    assert main([str(config), "--out-dir", str(out), "--generate-only"]) == 2
    assert "supports 2-5" in capsys.readouterr().err
    assert not out.exists()


def test_missing_dependencies_exit_3_but_keep_the_generated_scene(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PATH", "")
    out = tmp_path / "out"
    assert main([str(_write_config(tmp_path)), "--out-dir", str(out)]) == 3
    assert (out / "scene.py").is_file()
    assert "never install" in capsys.readouterr().err


def test_audio_is_refused_for_webm(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            str(_write_config(tmp_path)),
            "--out-dir",
            str(tmp_path / "out"),
            "--format",
            "webm",
            "--audio",
            str(tmp_path / "a.mp3"),
        ]
    )
    assert code == 2
    assert "mp4" in capsys.readouterr().err


@pytest.mark.skipif(
    importlib.util.find_spec("manim") is None or shutil.which("ffmpeg") is None,
    reason="manim and ffmpeg are required for a real render",
)
@pytest.mark.parametrize("template", sorted(CONFIGS))
def test_real_render_matches_the_planned_duration(
    tmp_path: Path, template: str
) -> None:
    out = tmp_path / "out"
    code = main(
        [
            str(_write_config(tmp_path, template)),
            "--out-dir",
            str(out),
            "--quality",
            "low",
        ]
    )
    report = json.loads((out / "verification.json").read_text(encoding="utf-8"))
    assert code == 0, report["failures"]
    assert report["ok"] is True
    receipt = json.loads(
        (out / "frames" / "review-receipt.json").read_text(encoding="utf-8")
    )
    assert receipt["review"]["status"] == "pending"
    assert len(receipt["samples"]) == 5


@pytest.mark.parametrize("value", ["-1", "31"])
def test_invalid_sample_count_fails_before_writing(tmp_path: Path, value: str) -> None:
    out = tmp_path / "out"
    assert (
        main(
            [
                str(_write_config(tmp_path)),
                "--out-dir",
                str(out),
                "--generate-only",
                f"--samples={value}",
            ]
        )
        == 2
    )
    assert not out.exists()


def test_regeneration_invalidates_previous_review(tmp_path: Path) -> None:
    out = tmp_path / "out"
    receipt = out / "frames" / "review-receipt.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text('{"review":{"status":"pass"}}', encoding="utf-8")
    assert (
        main(
            [
                str(_write_config(tmp_path)),
                "--out-dir",
                str(out),
                "--generate-only",
                "--samples",
                "0",
            ]
        )
        == 0
    )
    assert not receipt.exists()


@pytest.mark.skipif(
    importlib.util.find_spec("manim") is None or shutil.which("ffmpeg") is None,
    reason="manim and ffmpeg are required for a real render",
)
def test_short_audio_cannot_pass_as_an_untruncated_video(tmp_path: Path) -> None:
    out = tmp_path / "out"
    config = _write_config(tmp_path)
    arguments = [
        str(config),
        "--out-dir",
        str(out),
        "--quality",
        "low",
        "--samples",
        "0",
    ]
    assert main(arguments) == 0
    silent = probe_video(out / "scene.mp4")
    audio = tmp_path / "short.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={silent.container_duration_s - 0.3}",
            str(audio),
        ],
        check=True,
    )
    assert main([*arguments, "--audio", str(audio)]) == 1
    report = json.loads((out / "verification.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert any(
        "duration" in failure or "frames" in failure for failure in report["failures"]
    )
