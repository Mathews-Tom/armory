"""Native extension packaging: metadata, reproducible builds, host lifecycle and gates.

Every case uses the fictional ``fixture-wordcount`` package under
``extensions/_fixtures/``, which sits outside registered feature discovery.
Passing these tests is infrastructure evidence only, not compatibility of any
real feature with a real host session.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from scripts import check_extensions
from scripts.build_extensions import (
    CONTENT_MANIFEST,
    BuildError,
    build_feature,
    read_content_manifest,
    registered_features,
    verify_artifact_dir,
)
from scripts.build_extensions import main as build_main
from scripts.extension_lifecycle import (
    HostLayout,
    LifecycleError,
    payload_problems,
    run_action,
)
from scripts.extension_metadata import ExtensionMetadataError, parse_extension_metadata
from scripts.frontmatter import extract_body, parse_frontmatter
from scripts.package import package, package_native
from scripts.package_types import TYPES

EXTENSION = TYPES["extension"]
FIXTURE = EXTENSION.repo_dir / "_fixtures" / "fixture-wordcount"
NAME = FIXTURE.name
COMMAND = "armory-fixture-wordcount"


def _tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _fixture_meta() -> dict[str, Any]:
    return parse_frontmatter((FIXTURE / "EXTENSION.md").read_text(encoding="utf-8"))


def _rewrite_definition(
    feature: Path, mutate: Callable[[dict[str, Any]], None]
) -> None:
    definition = feature / "EXTENSION.md"
    text = definition.read_text(encoding="utf-8")
    meta = parse_frontmatter(text)
    mutate(meta)
    definition.write_text(
        f"---\n{yaml.safe_dump(meta, sort_keys=False)}---\n{extract_body(text)}",
        encoding="utf-8",
    )


@pytest.fixture
def source_root(tmp_path: Path) -> Path:
    """A detached copy of the fixture source, safe to mutate."""
    root = tmp_path / "sources"
    shutil.copytree(FIXTURE, root / NAME)
    return root


@pytest.fixture
def host_root(tmp_path: Path) -> Path:
    root = tmp_path / "host-root"
    root.mkdir()
    return root


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_fixture_metadata_declares_both_native_hosts() -> None:
    metadata = parse_extension_metadata(_fixture_meta())
    assert metadata.hosts == ("omp", "claude")
    assert metadata.host_entries == {
        "omp": "omp/index.ts",
        "claude": "claude-code/register.ts",
    }
    assert metadata.commands == (COMMAND,)
    assert metadata.exercised == {}


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda block: block["hosts"].update(cursor={"entry": "omp/index.ts"}),
            "unsupported host 'cursor'",
        ),
        (
            lambda block: block["hosts"]["omp"].update(entry="core/index.ts"),
            "must be a .ts or .js file under omp/",
        ),
        (
            lambda block: block["hosts"]["claude"].update(
                entry="claude-code/../core/index.ts"
            ),
            "without '.' or '..'",
        ),
        (
            lambda block: block.update(helpers=["../helpers/escape.ts"]),
            "without '.' or '..'",
        ),
        (
            lambda block: block.update(commands=["wordcount"]),
            "must be 'armory-' followed by kebab-case",
        ),
        (lambda block: block.update(commands=[]), "at least one literal command"),
        (
            lambda block: block.update(storage="user-private"),
            "user-private storage requires 'fs.write'",
        ),
        (lambda block: block.update(permissions=["shell"]), "unknown ['shell']"),
        (lambda block: block.update(schema_version=True), "expected 1"),
        (lambda block: block.update(runtime="node"), "unsupported runtime 'node'"),
        (
            lambda block: block.update(
                tested={"cursor": [{"version": "1", "surfaces": ["x"]}]}
            ),
            "not a declared host",
        ),
        (
            lambda block: block.update(minimum_host_version="2.1.0"),
            "unknown keys ['minimum_host_version']",
        ),
    ],
)
def test_metadata_rejects_invalid_declarations(
    mutate: Callable[[dict[str, Any]], None], message: str
) -> None:
    meta = _fixture_meta()
    mutate(meta["extension"])
    with pytest.raises(ExtensionMetadataError) as excinfo:
        parse_extension_metadata(meta)
    assert message in str(excinfo.value)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def test_build_is_byte_identical_across_output_and_source_roots(
    source_root: Path, tmp_path: Path
) -> None:
    from_repo = build_feature(FIXTURE, tmp_path / "out-a")
    from_copy = build_feature(source_root / NAME, tmp_path / "elsewhere" / "out-b")

    assert sorted(from_repo) == ["claude", "omp"]
    for host in ("omp", "claude"):
        assert (
            from_repo[host]
            == (tmp_path / "out-a" / "extensions" / NAME / host).resolve()
        )
        assert _tree(from_repo[host]) == _tree(from_copy[host])


def test_build_produces_host_native_self_contained_artifacts(tmp_path: Path) -> None:
    built = build_feature(FIXTURE, tmp_path / "dist")
    omp, claude = _tree(built["omp"]), _tree(built["claude"])
    core_source = (FIXTURE / "core" / "index.ts").read_bytes()

    assert json.loads(omp["package.json"])["omp"] == {"extensions": ["./index.ts"]}
    assert omp["index.ts"] == b'export { default } from "./omp/index.ts";\n'
    assert omp["omp/index.ts"] == (FIXTURE / "omp" / "index.ts").read_bytes()
    plugin = json.loads(claude[".claude-plugin/plugin.json"])
    assert (plugin["name"], plugin["version"]) == (NAME, "1.0.0")
    assert json.loads(claude["hooks/hooks.json"])["modules"] == ["./register.ts"]
    assert (
        claude["hooks/register.ts"]
        == (FIXTURE / "claude-code" / "register.ts").read_bytes()
    )

    for host, files in (("omp", omp), ("claude", claude)):
        assert files["core/index.ts"] == core_source
        assert b"countWords" in files["helpers/wordcount.js"]
        assert "LICENSE" in files
        assert not [
            path
            for path in files
            if "tests/" in path or "mod-checks" in path or path.endswith(".test.ts")
        ]
        assert not [
            path
            for path in files
            if path in ("EXTENSION.md", "CHANGELOG.md") or path.startswith("evals/")
        ]
        manifest = verify_artifact_dir(built[host])
        assert (manifest["feature"], manifest["host"], manifest["version"]) == (
            NAME,
            host,
            "1.0.0",
        )
        assert manifest["commands"] == [COMMAND]
        assert manifest["exercised_compatibility"] == []
        assert {entry["path"] for entry in manifest["files"]} == set(files) - {
            CONTENT_MANIFEST
        }
    assert (
        read_content_manifest(built["omp"])["core"]
        == read_content_manifest(built["claude"])["core"]
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.mark.parametrize(
    "corrupt",
    [
        pytest.param(
            lambda f: (f / "core" / "leak.ts").symlink_to("/etc/hosts"),
            id="core-file-link",
        ),
        pytest.param(
            lambda f: (f / "core" / "shared").symlink_to(f.parent),
            id="core-directory-link",
        ),
        pytest.param(lambda f: os.mkfifo(f / "core" / "pipe.ts"), id="special-file"),
        pytest.param(
            lambda f: _write(f / "omp" / ".env.local", "TOKEN=x\n"),
            id="secret-env",
        ),
        pytest.param(
            lambda f: _write(f / "core" / "cache.sqlite", ""), id="persistent-data"
        ),
        pytest.param(
            lambda f: _write(f / "core" / "notes.txt", "x\n"),
            id="unsupported-source-type",
        ),
        pytest.param(
            lambda f: _write(f / "core" / "pad.ts", 'import pad from "left-pad";\n'),
            id="bare-core-import",
        ),
        pytest.param(
            lambda f: _write(
                f / "claude-code" / "fs.ts", 'import { readFileSync } from "node:fs";\n'
            ),
            id="node-import-in-claude",
        ),
        pytest.param(
            lambda f: _write(
                f / "omp" / "escape.ts", 'import { x } from "../../outside.ts";\n'
            ),
            id="escaping-import",
        ),
        pytest.param(
            lambda f: _write(
                f / "claude-code" / "lazy.ts",
                'export const load = () => import("./register.ts");\n',
            ),
            id="dynamic-import",
        ),
        pytest.param(
            lambda f: _write(f / "claude-code" / "hooks.json", "{}\n"),
            id="generated-file-collision",
        ),
        pytest.param(
            lambda f: (f / "omp" / "index.ts").unlink(), id="missing-omp-entry"
        ),
        pytest.param(lambda f: (f / "EXTENSION.md").unlink(), id="missing-definition"),
    ],
)
def test_build_refuses_unsafe_or_incomplete_sources(
    corrupt: Callable[[Path], object], source_root: Path, tmp_path: Path
) -> None:
    feature = source_root / NAME
    corrupt(feature)
    out = tmp_path / "out"
    with pytest.raises(BuildError):
        build_feature(feature, out)
    assert not (out / "extensions" / NAME / "omp").exists()
    assert not (out / "extensions" / NAME / "claude").exists()


def test_build_refuses_output_inside_canonical_source() -> None:
    with pytest.raises(BuildError, match="inside canonical extension source"):
        build_feature(FIXTURE, FIXTURE / "dist")
    assert not (FIXTURE / "dist").exists()


def test_built_helper_runs_offline_from_a_detached_copy(tmp_path: Path) -> None:
    built = build_feature(FIXTURE, tmp_path / "dist")
    detached = tmp_path / "detached" / NAME
    shutil.copytree(built["omp"], detached)
    bun = shutil.which("bun")
    assert bun is not None, "bun is required for native extension tests"

    result = subprocess.run(
        [bun, "helpers/wordcount.js", "one", "two"],
        cwd=detached,
        env={"PATH": os.environ["PATH"], "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"words": 2}


def test_artifact_verification_detects_tampering_and_foreign_files(
    tmp_path: Path,
) -> None:
    built = build_feature(FIXTURE, tmp_path / "dist")
    (built["omp"] / "core" / "index.ts").write_text(
        "export const tampered = true;\n", encoding="utf-8"
    )
    with pytest.raises(BuildError, match="does not match its recorded digest"):
        verify_artifact_dir(built["omp"])
    (built["claude"] / "hooks" / "extra.ts").write_text(
        "export {};\n", encoding="utf-8"
    )
    with pytest.raises(BuildError, match="is not listed"):
        verify_artifact_dir(built["claude"])


def test_build_cli_requires_explicit_feature_and_output(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as missing_output:
        build_main(["--feature", NAME])
    assert missing_output.value.code == 2
    with pytest.raises(SystemExit) as both:
        build_main(["--feature", NAME, "--all", "--output-dir", str(tmp_path)])
    assert both.value.code == 2
    assert build_main(["--feature", NAME, "--output-dir", str(tmp_path)]) == 1
    assert not (tmp_path / "extensions").exists()


def test_fixture_is_outside_registered_discovery() -> None:
    assert NAME not in registered_features(EXTENSION.repo_dir)
    assert "_fixtures" not in registered_features(EXTENSION.repo_dir)


def test_native_package_archives_are_reproducible(tmp_path: Path) -> None:
    first = package_native(FIXTURE, tmp_path / "a", EXTENSION)
    second = package_native(FIXTURE, tmp_path / "b", EXTENSION)

    assert [path.name for path in first] == [
        f"{NAME}-1.0.0-omp.extension",
        f"{NAME}-1.0.0-claude.extension",
    ]
    for left, right in zip(first, second, strict=True):
        assert left.read_bytes() == right.read_bytes()
    with zipfile.ZipFile(first[0]) as archive:
        assert f"{NAME}/package.json" in archive.namelist()
        assert all(name.startswith(f"{NAME}/") for name in archive.namelist())
    with pytest.raises(ValueError, match="per-host native archives"):
        package(FIXTURE, tmp_path / "c", EXTENSION)


# ---------------------------------------------------------------------------
# Host lifecycle
# ---------------------------------------------------------------------------


def _act(action: str, host: str, root: Path, sources: Path) -> str:
    return run_action(action, host, NAME, root, sources)


def test_omp_lifecycle_preserves_foreign_state(
    host_root: Path, source_root: Path
) -> None:
    config = host_root / "config.yml"
    config.write_text(
        "theme: dark\nextensions:\n- ./local/ext-pack\n", encoding="utf-8"
    )
    foreign = host_root / "extensions" / "other" / "index.ts"
    _write(foreign, "export default function () {}\n")
    originals = {config: config.read_bytes(), foreign: foreign.read_bytes()}
    layout = HostLayout(root=host_root.resolve(), host="omp", feature=NAME)

    assert "installed" in _act("install", "omp", host_root, source_root)
    assert json.loads((layout.payload / "package.json").read_text())["omp"][
        "extensions"
    ] == ["./index.ts"]
    record = json.loads(layout.ownership.read_text())
    assert (record["version"], record["target_root"], record["state"]) == (
        "1.0.0",
        str(host_root.resolve()),
        "enabled",
    )
    assert set(record["files"]) == set(_tree(layout.payload))
    assert stat.S_IMODE(layout.ownership.stat().st_mode) == 0o600
    assert config.read_bytes() == originals[config]

    _act("disable", "omp", host_root, source_root)
    disabled = yaml.safe_load(config.read_text())
    assert disabled["disabledExtensions"] == [f"extension-module:{NAME}"]
    assert disabled["theme"] == "dark"
    assert (layout.payload / "index.ts").is_file()

    assert "re-enabled" in _act("install", "omp", host_root, source_root)
    assert config.read_bytes() == originals[config]

    _act("remove", "omp", host_root, source_root)
    assert not layout.payload.exists()
    assert not layout.ownership.exists()
    assert {path: path.read_bytes() for path in originals} == originals


def test_claude_lifecycle_registers_exactly_one_plugin_dir_entry(
    host_root: Path, source_root: Path
) -> None:
    settings = host_root / "settings.json"
    original = (
        json.dumps(
            {
                "model": "x",
                "env": {"CLAUDE_CODE_PLUGIN_DIRS": "/opt/other", "KEEP": "1"},
            },
            indent=2,
        )
        + "\n"
    )
    settings.write_text(original, encoding="utf-8")
    layout = HostLayout(root=host_root.resolve(), host="claude", feature=NAME)

    def plugin_dirs() -> str:
        return str(json.loads(settings.read_text())["env"]["CLAUDE_CODE_PLUGIN_DIRS"])

    _act("install", "claude", host_root, source_root)
    assert plugin_dirs() == f"/opt/other{os.pathsep}{layout.payload}"
    assert (layout.payload / ".claude-plugin" / "plugin.json").is_file()
    assert not (host_root / "extensions").exists()

    _act("disable", "claude", host_root, source_root)
    assert plugin_dirs() == "/opt/other"
    assert (layout.payload / "hooks" / "register.ts").is_file()

    _act("install", "claude", host_root, source_root)
    _act("remove", "claude", host_root, source_root)
    assert settings.read_text(encoding="utf-8") == original
    assert not layout.payload.exists()


def test_claude_settings_created_by_install_are_removed_with_it(
    host_root: Path, source_root: Path
) -> None:
    _act("install", "claude", host_root, source_root)
    assert json.loads((host_root / "settings.json").read_text())["env"][
        "CLAUDE_CODE_PLUGIN_DIRS"
    ]
    _act("remove", "claude", host_root, source_root)
    assert not (host_root / "settings.json").exists()


@pytest.mark.parametrize("host", ["omp", "claude"])
@pytest.mark.parametrize(
    ("damage", "problem"),
    [
        (
            lambda payload: (payload / "core" / "index.ts").write_text("// edited\n"),
            "core/index.ts: locally modified",
        ),
        (
            lambda payload: (payload / "notes.md").write_text("mine\n"),
            "notes.md: foreign file",
        ),
    ],
)
def test_remove_and_update_refuse_changed_payloads(
    host: str,
    damage: Callable[[Path], object],
    problem: str,
    host_root: Path,
    source_root: Path,
) -> None:
    _act("install", host, host_root, source_root)
    layout = HostLayout(root=host_root.resolve(), host=host, feature=NAME)
    damage(layout.payload)
    snapshot = _tree(host_root)

    for action in ("remove", "update"):
        with pytest.raises(LifecycleError) as excinfo:
            _act(action, host, host_root, source_root)
        assert problem in str(excinfo.value)
        assert _tree(host_root) == snapshot


@pytest.mark.parametrize("host", ["omp", "claude"])
def test_install_refuses_foreign_payload_directory(
    host: str, host_root: Path, source_root: Path
) -> None:
    layout = HostLayout(root=host_root.resolve(), host=host, feature=NAME)
    _write(layout.payload / "index.ts", "// someone else's\n")
    with pytest.raises(LifecycleError, match="not owned by Armory"):
        _act("install", host, host_root, source_root)
    assert _tree(layout.payload) == {"index.ts": b"// someone else's\n"}


def test_install_refuses_symlinked_payload_parent(
    host_root: Path, source_root: Path, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (host_root / "extensions").symlink_to(elsewhere)
    with pytest.raises(LifecycleError, match="symbolic link"):
        _act("install", "omp", host_root, source_root)
    assert list(elsewhere.iterdir()) == []


def test_omp_install_refuses_name_collisions_and_foreign_disables(
    host_root: Path, source_root: Path
) -> None:
    _write(host_root / "extensions" / f"{NAME}.ts", "export default function () {}\n")
    with pytest.raises(LifecycleError, match="would share the OMP extension name"):
        _act("install", "omp", host_root, source_root)
    (host_root / "extensions" / f"{NAME}.ts").unlink()
    (host_root / "config.yml").write_text(
        f"disabledExtensions:\n- extension-module:{NAME}\n", encoding="utf-8"
    )
    with pytest.raises(LifecycleError, match="Armory does not own"):
        _act("install", "omp", host_root, source_root)
    assert not (host_root / "extensions" / NAME).exists()


def _bump(feature: Path, version: str) -> None:
    _rewrite_definition(feature, lambda meta: meta["metadata"].update(version=version))
    with (feature / "core" / "index.ts").open("a", encoding="utf-8") as handle:
        handle.write(f"// release {version}\n")


def test_update_replaces_payload_and_rolls_back_a_failed_swap(
    host_root: Path, source_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feature = source_root / NAME
    layout = HostLayout(root=host_root.resolve(), host="omp", feature=NAME)
    _act("install", "omp", host_root, source_root)
    _bump(feature, "1.0.1")
    _act("update", "omp", host_root, source_root)
    assert (
        (layout.payload / "core" / "index.ts")
        .read_text()
        .endswith("// release 1.0.1\n")
    )
    installed = json.loads(layout.ownership.read_text())
    assert installed["version"] == "1.0.1"

    _bump(feature, "1.0.2")
    real_rename = os.rename
    failed_swap = False

    def failing_swap(source: Path, destination: Path) -> None:
        nonlocal failed_swap
        if (
            not failed_swap
            and Path(source).is_relative_to(layout.staging)
            and Path(destination) == layout.payload
        ):
            failed_swap = True
            raise RuntimeError("simulated failure while swapping the update")
        real_rename(source, destination)

    monkeypatch.setattr(os, "rename", failing_swap)
    with pytest.raises(RuntimeError, match="simulated failure"):
        _act("update", "omp", host_root, source_root)

    assert payload_problems(layout.payload, installed["files"]) == []
    restored = json.loads(layout.ownership.read_text())
    assert (restored["version"], restored["pending"]) == ("1.0.1", None)
    assert list(layout.staging.iterdir()) == []


def test_interrupted_install_is_rolled_back_before_the_next_action(
    host_root: Path, source_root: Path
) -> None:
    layout = HostLayout(root=host_root.resolve(), host="omp", feature=NAME)
    program = """
import os
import sys
from pathlib import Path
import scripts.extension_lifecycle as lifecycle

root, sources, name = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
layout = lifecycle.HostLayout(root=root.resolve(), host="omp", feature=name)
real_rename = os.rename

def crash_after_payload_rename(source, destination):
    real_rename(source, destination)
    if Path(destination) == layout.payload:
        os._exit(86)

os.rename = crash_after_payload_rename
lifecycle.run_action("install", "omp", name, root, sources)
"""
    interrupted = subprocess.run(
        [sys.executable, "-c", program, str(host_root), str(source_root), NAME],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert interrupted.returncode == 86, interrupted.stderr
    assert layout.payload.is_dir()
    assert json.loads(layout.ownership.read_text())["pending"]["action"] == "install"

    _act("install", "omp", host_root, source_root)
    record = json.loads(layout.ownership.read_text())
    assert record["pending"] is None
    assert payload_problems(layout.payload, record["files"]) == []
    assert list(layout.staging.iterdir()) == []


def test_update_refuses_downgrade_and_reports_current(
    host_root: Path, source_root: Path
) -> None:
    feature = source_root / NAME
    _bump(feature, "2.0.0")
    _act("install", "claude", host_root, source_root)
    assert "already current" in _act("update", "claude", host_root, source_root)
    _bump(feature, "1.5.0")
    with pytest.raises(LifecycleError, match="refusing to downgrade"):
        _act("update", "claude", host_root, source_root)


def test_unsupported_host_and_invalid_transitions_fail_explicitly(
    host_root: Path, source_root: Path
) -> None:
    feature = source_root / NAME
    _rewrite_definition(feature, lambda meta: meta["extension"]["hosts"].pop("claude"))
    with pytest.raises(LifecycleError, match="does not support host 'claude'"):
        _act("install", "claude", host_root, source_root)
    with pytest.raises(LifecycleError, match="unsupported platform 'cursor'"):
        _act("install", "cursor", host_root, source_root)
    with pytest.raises(LifecycleError, match="unsupported action 'enable'"):
        _act("enable", "omp", host_root, source_root)
    with pytest.raises(LifecycleError, match="is not installed for omp"):
        _act("remove", "omp", host_root, source_root)
    _act("install", "omp", host_root, source_root)
    with pytest.raises(LifecycleError, match="already installed"):
        _act("install", "omp", host_root, source_root)
    _act("disable", "omp", host_root, source_root)
    with pytest.raises(LifecycleError, match="already disabled"):
        _act("disable", "omp", host_root, source_root)
    with pytest.raises(LifecycleError, match="does not exist"):
        run_action("install", "omp", NAME, host_root / "missing", source_root)
    assert not (host_root / ".armory-native" / "claude-plugins").exists()


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--all"],
        ["--catalog"],
        ["--ci", "--catalog"],
        ["--all", "--catalog", "--feature", NAME],
        ["--stage", "core"],
        ["--native-smoke"],
        ["--all", "--catalog", "--native-smoke"],
        ["--feature", "Bad_Name"],
        ["--feature", "no-such-feature"],
        ["--feature", "no-such-feature", "--stage", "full"],
    ],
)
def test_check_cli_rejects_invalid_arguments(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        check_extensions.main(argv)
    assert excinfo.value.code == 2


def test_implemented_stage_follows_committed_files(tmp_path: Path) -> None:
    feature = tmp_path / "demo"
    (feature / "core").mkdir(parents=True)
    assert check_extensions.implemented_stage(feature) == "core"
    (feature / "omp").mkdir()
    assert check_extensions.implemented_stage(feature) == "omp"
    (feature / "claude-code").mkdir()
    with pytest.raises(check_extensions.GateFailure, match="introduced atomically"):
        check_extensions.implemented_stage(feature)
    (feature / "EXTENSION.md").write_text("---\nname: demo\n---\n", encoding="utf-8")
    assert check_extensions.implemented_stage(feature) == "full"
    with pytest.raises(check_extensions.GateFailure, match="no implemented component"):
        check_extensions.implemented_stage(tmp_path / "empty")


def test_full_gate_of_an_unregistered_prefix_is_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("scripts.package_types.REPO_ROOT", tmp_path)
    (tmp_path / "extensions" / "demo" / "core").mkdir(parents=True)

    assert (
        check_extensions.main(["--feature", "demo"]) == check_extensions.EXIT_INCOMPLETE
    )
    report = json.loads(capsys.readouterr().out)
    assert (report["stage"], report["feature_complete"]) == ("full", False)
    assert report["surfaces"] == [
        {
            "name": "registration",
            "status": "incomplete",
            "detail": report["surfaces"][0]["detail"],
        }
    ]
    assert "implemented stage is 'core'" in report["surfaces"][0]["detail"]


def _statuses(report: check_extensions.Report) -> dict[str, str]:
    return {surface.name: surface.status for surface in report.surfaces}


def test_registered_fixture_passes_every_static_gate_but_native_smoke_stays_incomplete() -> (
    None
):
    report = check_extensions.check_registered(FIXTURE, native_smoke=True)
    statuses = _statuses(report)
    evidence = json.dumps(report.as_dict(), indent=2)

    expected_passed = {
        "definition",
        "toolchain",
        "core-sources",
        "typecheck",
        "lint",
        "unit-tests",
        "reproducible-build",
        "omp-artifact",
        "claude-static-validation",
        "claude-native-tests",
        "omp-lifecycle",
        "claude-lifecycle",
    }
    assert {
        name for name, status in statuses.items() if status == "passed"
    } == expected_passed, evidence
    assert (
        statuses["omp-native-smoke"] == statuses["claude-native-smoke"] == "unavailable"
    ), evidence
    assert report.exit_code == check_extensions.EXIT_INCOMPLETE
    assert report.feature_complete is False


def test_omp_stage_gate_certifies_only_its_stage() -> None:
    report = check_extensions.check_stage(FIXTURE, "omp")
    statuses = _statuses(report)
    evidence = json.dumps(report.as_dict(), indent=2)

    assert report.stage == "omp"
    assert statuses["omp-prefix-build"] == "passed", evidence
    assert statuses["unit-tests"] == "passed", evidence
    assert statuses["omp-native-smoke"] == "unavailable"
    assert report.exit_code == check_extensions.EXIT_INCOMPLETE
    assert report.feature_complete is False


def test_catalog_gate_verifies_explicit_install_consumers() -> None:
    report = check_extensions.check_catalog()
    statuses = _statuses(report)
    assert report.exit_code == check_extensions.EXIT_OK, json.dumps(
        report.as_dict(), indent=2
    )
    assert {"catalog-manifest", "catalog-evaluator", "catalog-explicit-install"} <= set(
        statuses
    )


# ---------------------------------------------------------------------------
# Catalog consumers
# ---------------------------------------------------------------------------


def test_catalog_readers_map_sections_through_the_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import search

    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "packages": {
                    "utilities": [
                        {"name": "tool", "description": "", "path": "utilities/tool"}
                    ],
                    "extensions": [
                        {"name": NAME, "description": "", "path": f"extensions/{NAME}"}
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(search, "MANIFEST_PATH", manifest)
    assert {entry["name"]: entry["type"] for entry in search.load_packages()} == {
        "tool": "utility",
        NAME: "extension",
    }

    spec = importlib.util.spec_from_file_location(
        "site_generate", TYPES["skill"].repo_dir.parent / "site" / "generate.py"
    )
    assert spec is not None and spec.loader is not None
    site_generate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(site_generate)
    monkeypatch.setattr(site_generate, "_REPO_ROOT", tmp_path)
    assert {
        entry["name"]: entry["type"] for entry in site_generate.load_manifest()
    } == {
        "tool": "utility",
        NAME: "extension",
    }


def test_eval_discovery_ignores_workspace_and_unregistered_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import run_evals, validate_evals

    monkeypatch.setattr("scripts.package_types.REPO_ROOT", tmp_path)
    monkeypatch.setattr(run_evals, "_REPO_ROOT", tmp_path)
    for workspace_dir in (
        "node_modules/typescript",
        "_fixtures/demo/evals",
        "_tooling",
        "in-progress/core",
    ):
        (tmp_path / "extensions" / workspace_dir).mkdir(parents=True)
    (
        tmp_path / "extensions" / "_fixtures" / "demo" / "evals" / "cases.yaml"
    ).write_text("cases: []\n")
    skill = tmp_path / "skills" / "demo-skill"
    (skill / "evals").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Demo.\n---\n", encoding="utf-8"
    )
    (skill / "evals" / "cases.yaml").write_text(
        (FIXTURE / "evals" / "cases.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )

    assert validate_evals.main() == 0
    assert run_evals.collect_all_packages() == ["skills/demo-skill"]


def test_manifest_and_evaluator_report_registered_extensions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.evaluate_package import evaluate_package
    from scripts.generate_manifest import collect_packages

    monkeypatch.setattr("scripts.package_types.REPO_ROOT", tmp_path)
    monkeypatch.setattr("scripts.generate_manifest.REPO_ROOT", tmp_path)
    registered = tmp_path / "extensions" / NAME
    shutil.copytree(FIXTURE, registered)

    [entry] = collect_packages(EXTENSION, "owner/repo")
    assert (entry["name"], entry["version"], entry["path"]) == (
        NAME,
        "1.0.0",
        f"extensions/{NAME}",
    )
    assert (entry["hosts"], entry["runtime"], entry["commands"]) == (
        ["claude", "omp"],
        "bun",
        [COMMAND],
    )

    report = evaluate_package(registered, EXTENSION)
    assert cast(dict[str, object], report["static_conformance"])["status"] == "PASS"
    effectiveness = cast(dict[str, object], report["live_effectiveness"])
    assert effectiveness["status"] == "NOT_MEASURED"

    _rewrite_definition(
        registered,
        lambda meta: meta["extension"]["hosts"].update(cursor={"entry": "x.ts"}),
    )
    failing = evaluate_package(registered, EXTENSION)
    assert failing["status"] == "FAIL"
    assert "unsupported host 'cursor'" in json.dumps(failing["findings"])
