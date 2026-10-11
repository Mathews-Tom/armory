from __future__ import annotations

from pathlib import Path

from render_video import find_rendered_file


def test_native_versioned_gif_is_located(tmp_path: Path) -> None:
    gif = tmp_path / "videos/scene/480p15/Scene_ManimCE_v0.19.2.gif"
    gif.parent.mkdir(parents=True)
    gif.write_bytes(b"current render")
    assert (
        find_rendered_file(
            tmp_path,
            "Scene",
            "480p15",
            "gif",
            source_stem="scene",
            manim_version="0.19.2",
        )
        == gif
    )


def test_output_from_another_quality_is_not_selected(tmp_path: Path) -> None:
    wrong_quality = tmp_path / "videos/scene/1080p60/Scene.mp4"
    wrong_quality.parent.mkdir(parents=True)
    wrong_quality.write_bytes(b"old high-quality render")
    assert (
        find_rendered_file(
            tmp_path,
            "Scene",
            "480p15",
            "mp4",
            source_stem="scene",
            manim_version="0.19.2",
        )
        is None
    )


def test_same_class_in_other_source_files_is_not_guessed(tmp_path: Path) -> None:
    for stem in ("other_a", "other_b"):
        video = tmp_path / f"videos/{stem}/480p15/Scene.mp4"
        video.parent.mkdir(parents=True)
        video.write_bytes(stem.encode())
    assert (
        find_rendered_file(
            tmp_path,
            "Scene",
            "480p15",
            "mp4",
            source_stem="scene",
            manim_version="0.19.2",
        )
        is None
    )


def test_legacy_plain_gif_cannot_replace_current_version_output(tmp_path: Path) -> None:
    stale = tmp_path / "videos/scene/480p15/Scene.gif"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"stale legacy output")
    assert (
        find_rendered_file(
            tmp_path,
            "Scene",
            "480p15",
            "gif",
            source_stem="scene",
            manim_version="0.19.2",
        )
        is None
    )
