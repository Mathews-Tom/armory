"""Tests for fetch_assets.py — Phase 4 asset resolution."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Make the scripts directory importable
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from fetch_assets import (  # noqa: E402
    AssetResolutionError,
    IconFinderAdapter,
    LocalAssetAdapter,
    NoneAdapter,
    _normalise_query,
    _validate_storyboard,
    main,
    resolve_storyboard,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def asset_dir(tmp_path: Path) -> Path:
    """Fixture directory with three SVG files."""
    (tmp_path / "database.svg").write_text("<svg/>")
    (tmp_path / "network-arrow.svg").write_text("<svg/>")
    (tmp_path / "Computer_Server.svg").write_text("<svg/>")
    return tmp_path


@pytest.fixture()
def simple_storyboard() -> dict[str, Any]:
    return {
        "concept": "TCP/IP",
        "duration_estimate_seconds": 60,
        "scenes": [
            {
                "index": 0,
                "title": "Intro",
                "duration_seconds": 15,
                "beats": ["show computers"],
                "assets": [
                    {"kind": "icon", "query": "database", "required": True},
                    {"kind": "text", "query": "TCP/IP", "required": True},
                ],
            },
            {
                "index": 1,
                "title": "SYN",
                "duration_seconds": 20,
                "beats": ["animate arrow"],
                "assets": [
                    {"kind": "icon", "query": "network arrow", "required": False},
                ],
            },
        ],
    }


@pytest.fixture()
def storyboard_file(tmp_path: Path, simple_storyboard: dict[str, Any]) -> Path:
    p = tmp_path / "storyboard.json"
    p.write_text(json.dumps(simple_storyboard))
    return p


# ---------------------------------------------------------------------------
# _normalise_query
# ---------------------------------------------------------------------------


def test_normalise_query_lowercases_and_hyphenates() -> None:
    # Arrange
    query = "Computer Server"
    # Act
    result = _normalise_query(query)
    # Assert
    assert result == "computer-server"


def test_normalise_query_collapses_underscores() -> None:
    assert _normalise_query("network_arrow") == "network-arrow"


def test_normalise_query_strips_whitespace() -> None:
    assert _normalise_query("  database  ") == "database"


# ---------------------------------------------------------------------------
# LocalAssetAdapter
# ---------------------------------------------------------------------------


def test_localassetadapter_exact_match_returns_path(asset_dir: Path) -> None:
    # Arrange
    adapter = LocalAssetAdapter(asset_dir)
    # Act
    result = adapter.resolve("database", "icon")
    # Assert
    assert result is not None
    assert result.name == "database.svg"


def test_localassetadapter_case_insensitive_match_returns_path(
    asset_dir: Path,
) -> None:
    # Arrange
    adapter = LocalAssetAdapter(asset_dir)
    # Act — file is "Computer_Server.svg"; stem normalises to "computer-server"
    result = adapter.resolve("Computer Server", "icon")
    # Assert
    assert result is not None
    assert result.name == "Computer_Server.svg"


def test_localassetadapter_hyphen_normalised_match_returns_path(
    asset_dir: Path,
) -> None:
    # Arrange
    adapter = LocalAssetAdapter(asset_dir)
    # Act — "network arrow" → "network-arrow" matches "network-arrow.svg"
    result = adapter.resolve("network arrow", "icon")
    # Assert
    assert result is not None
    assert result.name == "network-arrow.svg"


def test_localassetadapter_no_match_returns_none(asset_dir: Path) -> None:
    # Arrange
    adapter = LocalAssetAdapter(asset_dir)
    # Act
    result = adapter.resolve("missing-icon", "icon")
    # Assert
    assert result is None


def test_localassetadapter_invalid_directory_raises_valueerror(
    tmp_path: Path,
) -> None:
    # Arrange
    missing = tmp_path / "no_such_dir"
    # Act / Assert
    with pytest.raises(ValueError, match="asset-dir does not exist"):
        LocalAssetAdapter(missing)


# ---------------------------------------------------------------------------
# NoneAdapter
# ---------------------------------------------------------------------------


def test_noneadapter_always_returns_none() -> None:
    # Arrange
    adapter = NoneAdapter()
    # Act / Assert
    assert adapter.resolve("anything", "icon") is None
    assert adapter.resolve("", "text") is None


def test_noneadapter_name_is_none() -> None:
    assert NoneAdapter().name == "none"


# ---------------------------------------------------------------------------
# IconFinderAdapter
# ---------------------------------------------------------------------------


def test_iconfinderadapter_missing_api_key_raises_valueerror_at_construction() -> None:
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="ICONFINDER_API_KEY is not set"):
        IconFinderAdapter("")


def test_iconfinderadapter_from_env_missing_key_raises_valueerror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.delenv("ICONFINDER_API_KEY", raising=False)
    # Act / Assert
    with pytest.raises(ValueError, match="ICONFINDER_API_KEY is not set"):
        IconFinderAdapter.from_env()


def _make_urlopen_mock(
    search_payload: dict[str, Any],
    download_bytes: bytes = b"<svg/>",
) -> Any:
    """Return a patch target that returns search then download responses."""
    call_count = 0

    def fake_urlopen(req: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            resp = MagicMock()
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            resp.read.return_value = json.dumps(search_payload).encode()
            return resp
        else:
            resp = MagicMock()
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            resp.read.return_value = download_bytes
            return resp

    return fake_urlopen


def test_iconfinderadapter_resolve_successful_fetch_returns_path(
    tmp_path: Path,
) -> None:
    # Arrange
    payload = {
        "icons": [
            {
                "vector_sizes": [
                    {
                        "formats": [
                            {
                                "download_url": "https://cdn.iconfinder.com/data/icons/db.svg"
                            }
                        ]
                    }
                ],
                "raster_sizes": [],
            }
        ]
    }
    adapter = IconFinderAdapter("test-key")
    fake_open = _make_urlopen_mock(payload)

    with patch("urllib.request.urlopen", side_effect=fake_open):
        with patch.dict("os.environ", {"TMPDIR": str(tmp_path)}):
            # Act
            result = adapter.resolve("database", "icon")

    # Assert
    assert result is not None
    assert result.suffix == ".svg"
    assert result.parent == tmp_path


def test_iconfinderadapter_resolve_http_404_raises_runtimeerror() -> None:
    # Arrange
    import urllib.error

    adapter = IconFinderAdapter("test-key")

    def fake_urlopen(req: Any) -> Any:
        raise urllib.error.HTTPError(
            url="https://api.iconfinder.com/v4/icons/search",
            code=404,
            msg="Not Found",
            hdrs=MagicMock(),
            fp=None,
        )

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        # Act / Assert
        with pytest.raises(RuntimeError, match="HTTP 404"):
            adapter.resolve("missing", "icon")


def test_iconfinderadapter_resolve_http_500_raises_runtimeerror() -> None:
    # Arrange
    import urllib.error

    adapter = IconFinderAdapter("test-key")

    def fake_urlopen(req: Any) -> Any:
        raise urllib.error.HTTPError(
            url="https://api.iconfinder.com/v4/icons/search",
            code=500,
            msg="Server Error",
            hdrs=MagicMock(),
            fp=None,
        )

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        with pytest.raises(RuntimeError, match="HTTP 500"):
            adapter.resolve("database", "icon")


def test_iconfinderadapter_resolve_url_contains_encoded_query(
    tmp_path: Path,
) -> None:
    """urlencode must come from urllib.parse — this test catches the wrong-module bug."""
    # Arrange
    captured_urls: list[str] = []
    payload = {
        "icons": [
            {
                "vector_sizes": [
                    {
                        "formats": [
                            {
                                "download_url": "https://cdn.iconfinder.com/data/icons/db.svg"
                            }
                        ]
                    }
                ],
                "raster_sizes": [],
            }
        ]
    }
    adapter = IconFinderAdapter("test-key")
    fake_open = _make_urlopen_mock(payload)

    original_side_effect = fake_open

    def capturing_urlopen(req: Any) -> Any:
        if hasattr(req, "full_url"):
            captured_urls.append(req.full_url)
        return original_side_effect(req)

    with patch("urllib.request.urlopen", side_effect=capturing_urlopen):
        with patch.dict("os.environ", {"TMPDIR": str(tmp_path)}):
            # Act
            adapter.resolve("my query", "icon")

    # Assert — the search URL must contain the percent-encoded query param
    assert captured_urls, "urlopen was never called"
    search_url = captured_urls[0]
    assert "query=my+query" in search_url or "query=my%20query" in search_url


def test_iconfinderadapter_resolve_no_results_returns_none() -> None:
    # Arrange
    adapter = IconFinderAdapter("test-key")
    payload: dict[str, Any] = {"icons": []}

    def fake_urlopen(req: Any) -> Any:
        resp = MagicMock()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        resp.read.return_value = json.dumps(payload).encode()
        return resp

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        # Act
        result = adapter.resolve("obscure-query", "icon")

    # Assert
    assert result is None


# ---------------------------------------------------------------------------
# _validate_storyboard
# ---------------------------------------------------------------------------


def test_validate_storyboard_missing_scenes_raises_valueerror() -> None:
    with pytest.raises(ValueError, match="scenes"):
        _validate_storyboard({"concept": "x"})


def test_validate_storyboard_empty_scenes_raises_valueerror() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        _validate_storyboard({"scenes": []})


def test_validate_storyboard_invalid_kind_raises_valueerror() -> None:
    bad: dict[str, Any] = {
        "scenes": [
            {
                "index": 0,
                "assets": [{"kind": "video", "query": "x", "required": True}],
            }
        ]
    }
    with pytest.raises(ValueError, match="kind"):
        _validate_storyboard(bad)


def test_validate_storyboard_required_not_bool_raises_valueerror() -> None:
    bad: dict[str, Any] = {
        "scenes": [
            {
                "index": 0,
                "assets": [{"kind": "icon", "query": "x", "required": "true"}],
            }
        ]
    }
    with pytest.raises(ValueError, match="required.*boolean"):
        _validate_storyboard(bad)


# ---------------------------------------------------------------------------
# resolve_storyboard — integration
# ---------------------------------------------------------------------------


def test_resolve_storyboard_with_none_adapter_returns_null_mapping(
    simple_storyboard: dict[str, Any],
) -> None:
    # Arrange — mark all assets optional so NoneAdapter doesn't raise
    for scene in simple_storyboard["scenes"]:
        for asset in scene["assets"]:
            asset["required"] = False
    adapter = NoneAdapter()
    # Act
    result = resolve_storyboard(simple_storyboard, adapter)
    # Assert
    assert set(result.keys()) == {0, 1}
    assert result[0]["database"] is None
    assert result[0]["TCP/IP"] is None
    assert result[1]["network arrow"] is None


def test_resolve_storyboard_with_local_adapter_resolves_database(
    simple_storyboard: dict[str, Any],
    asset_dir: Path,
) -> None:
    # Arrange
    adapter = LocalAssetAdapter(asset_dir)
    # "TCP/IP" asset is required but won't resolve — patch it to optional
    simple_storyboard["scenes"][0]["assets"][1]["required"] = False
    # Act
    result = resolve_storyboard(simple_storyboard, adapter)
    # Assert
    assert result[0]["database"] is not None
    assert result[0]["database"].endswith("database.svg")
    assert result[1]["network arrow"] is not None


def test_resolve_storyboard_required_missing_raises_assetresolutionerror(
    simple_storyboard: dict[str, Any],
) -> None:
    # Arrange
    adapter = NoneAdapter()
    # Both assets in scene 0 are required=True, NoneAdapter returns None
    # Act / Assert
    with pytest.raises(AssetResolutionError) as exc_info:
        resolve_storyboard(simple_storyboard, adapter)
    err = exc_info.value
    assert isinstance(err.missing, list)
    assert "database" in err.missing
    assert "TCP/IP" in err.missing


def test_resolve_storyboard_optional_missing_does_not_raise(
    simple_storyboard: dict[str, Any],
    asset_dir: Path,
) -> None:
    # Arrange — mark all assets optional
    for scene in simple_storyboard["scenes"]:
        for asset in scene["assets"]:
            asset["required"] = False
    adapter = NoneAdapter()
    # Act — should not raise
    result = resolve_storyboard(simple_storyboard, adapter)
    # Assert
    assert result[0]["database"] is None


def test_assetresolutionerror_has_missing_attribute() -> None:
    # Arrange / Act
    err = AssetResolutionError(["icon-a", "icon-b"])
    # Assert
    assert err.missing == ["icon-a", "icon-b"]
    assert "icon-a" in str(err)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_main_cli_happy_path_local_adapter_prints_json(
    storyboard_file: Path,
    asset_dir: Path,
    simple_storyboard: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange — make all required assets optional so NoneAdapter won't raise
    # Rewrite storyboard with all optional
    for scene in simple_storyboard["scenes"]:
        for asset in scene["assets"]:
            asset["required"] = False
    storyboard_file.write_text(json.dumps(simple_storyboard))

    # Act
    main(
        [
            str(storyboard_file),
            "--adapter",
            "local",
            "--asset-dir",
            str(asset_dir),
        ]
    )

    # Assert
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert "0" in output
    assert "database" in output["0"]


def test_main_cli_output_file_written(
    storyboard_file: Path,
    tmp_path: Path,
    simple_storyboard: dict[str, Any],
) -> None:
    # Arrange — all optional to avoid resolution error
    for scene in simple_storyboard["scenes"]:
        for asset in scene["assets"]:
            asset["required"] = False
    storyboard_file.write_text(json.dumps(simple_storyboard))
    out_file = tmp_path / "resolved.json"

    # Act
    main(["--adapter", "none", "--output", str(out_file), str(storyboard_file)])

    # Assert
    assert out_file.exists()
    data = json.loads(out_file.read_text())
    assert "0" in data


def test_main_cli_malformed_storyboard_raises_valueerror(
    tmp_path: Path,
) -> None:
    # Arrange
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{not valid json")
    # Act / Assert
    with pytest.raises(ValueError, match="malformed storyboard JSON"):
        main(["--adapter", "none", str(bad_file)])


def test_main_cli_missing_asset_dir_raises_valueerror(
    storyboard_file: Path,
) -> None:
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="--asset-dir is required"):
        main(["--adapter", "local", str(storyboard_file)])
