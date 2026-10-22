"""Isolated native-build containment, ownership and multi-host rollback cases."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import build_extensions as builder
from scripts.package_types import TYPES

FIXTURE = TYPES["extension"].repo_dir / "_fixtures" / "fixture-wordcount"
NAME = FIXTURE.name


@pytest.fixture
def feature(tmp_path: Path) -> Path:
    destination = tmp_path / "sources" / NAME
    shutil.copytree(FIXTURE, destination)
    return destination


def _tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize(
    ("parameter", "body", "permission"),
    [
        pytest.param("api", 'await api.fs.read("file");', "fs.read", id="renamed-api"),
        pytest.param(
            "api",
            'const root = api; await root.fs.list(".");',
            "fs.read",
            id="root-alias",
        ),
        pytest.param(
            "api",
            'const fs = api.fs; await fs.exists("file");',
            "fs.read",
            id="namespace-alias",
        ),
        pytest.param(
            "api",
            'const run = api.process.run; await run("tool");',
            "process.spawn",
            id="method-alias",
        ),
        pytest.param(
            "api",
            'const { fs } = api; await fs.stat("file");',
            "fs.read",
            id="root-destructure",
        ),
        pytest.param(
            "api",
            'const { read: load } = api.fs; await load("file");',
            "fs.read",
            id="method-destructure",
        ),
        pytest.param(
            "api",
            'const { process: { spawn: launch } } = api; await launch("tool");',
            "process.spawn",
            id="nested-destructure",
        ),
        pytest.param(
            "{ http: { fetch: request } }",
            'await request("https://example.invalid");',
            "network",
            id="parameter-destructure",
        ),
        pytest.param(
            "api",
            'await api?.fs?.ancestors?.("file");',
            "fs.read",
            id="optional-static-read",
        ),
        pytest.param(
            "api",
            'await api.fs?.write?.("file", "value");',
            "fs.write",
            id="optional-static-write",
        ),
        pytest.param(
            "api",
            'await api.http.fetch("https://example.invalid");',
            "network",
            id="renamed-network",
        ),
        pytest.param(
            "$", 'await $.process.run("tool");', "process.spawn", id="literal-control"
        ),
    ],
)
def test_claude_bound_effects_require_and_accept_declared_permissions(
    parameter: str, body: str, permission: str, feature: Path, tmp_path: Path
) -> None:
    source = (
        "export function register(onHook) {\n"
        f'  onHook("session.start", async ({parameter}, event, next) => {{\n'
        f"    {body}\n"
        "    return next(event);\n"
        "  });\n"
        "}\n"
    )
    (feature / "claude-code/register.ts").write_text(source)
    output = tmp_path / "output"
    with pytest.raises(builder.BuildError, match=rf"does not declare '{permission}'"):
        builder.build_feature(feature, output)
    assert not (output / "extensions" / NAME / "claude").exists()
    assert not (output / "extensions" / NAME / "omp").exists()

    metadata = feature / "EXTENSION.md"
    metadata.write_text(
        metadata.read_text().replace("permissions: []", f"permissions: [{permission}]")
    )
    artifacts = builder.build_feature(feature, output)
    manifest = builder.verify_artifact_dir(artifacts["claude"])
    assert manifest["permissions"] == [permission]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            'const note = "$.process.run() $.fs.write() $.http.fetch()"; // $.fs.read()\nvoid note;',
            id="inert-text",
        ),
        pytest.param(
            "const other = { process: { run() { return 7; } } }; other.process.run();",
            id="unrelated-object",
        ),
        pytest.param(
            "{ const api = { fs: { read() { return 7; } } }; api.fs.read(); }",
            id="shadowed-root",
        ),
        pytest.param(
            "function local($) { $.process.run(); } local({ process: { run() { return 7; } } });",
            id="shadowed-dollar-parameter",
        ),
        pytest.param(
            "const fs = api.fs; { const fs = { write() { return 7; } }; fs.write(); }",
            id="shadowed-namespace",
        ),
        pytest.param(
            "function identity() { return arguments[0]; } identity(7);",
            id="nested-own-arguments",
        ),
        pytest.param(
            "function identity() { const read = () => arguments[0]; return read(); } identity(7);",
            id="nested-arrow-own-arguments",
        ),
    ],
)
def test_claude_non_effects_build_without_permissions(
    body: str, feature: Path, tmp_path: Path
) -> None:
    source = (
        "export function register(on) {\n"
        f'  on("session.start", async (api, event, next) => {{ {body}\n'
        "    return next(event);\n"
        "  });\n"
        "}\n"
    )
    (feature / "claude-code/register.ts").write_text(source)
    artifacts = builder.build_feature(feature, tmp_path / "output")
    manifest = builder.verify_artifact_dir(artifacts["claude"])
    assert manifest["permissions"] == []


@pytest.mark.parametrize(
    ("preamble", "body"),
    [
        pytest.param("", 'await api["process"].run("tool");', id="computed-namespace"),
        pytest.param("", 'await api.process["run"]("tool");', id="computed-method"),
        pytest.param(
            "", 'const key = "fs"; await api[key].read("file");', id="dynamic-namespace"
        ),
        pytest.param(
            "function consume(value) { return value; }\n",
            "consume(api);",
            id="local-api-transfer",
        ),
        pytest.param(
            'import { countWords } from "../core/index.ts";\n',
            "countWords(api);",
            id="pure-import-api-transfer",
        ),
        pytest.param(
            "function consume(value) { return value; }\n",
            "consume(api.fs);",
            id="namespace-transfer",
        ),
        pytest.param(
            "function consume(value) { return value; }\n",
            "consume(api.process.run);",
            id="method-transfer",
        ),
        pytest.param("", "return api;", id="returned-api"),
        pytest.param("", "const holder = { api }; void holder;", id="stored-api"),
        pytest.param(
            "",
            "let alias; alias = api; await alias.process.run('tool');",
            id="dynamic-alias-transfer",
        ),
        pytest.param(
            "",
            "const read = () => arguments[0]; read();",
            id="arrow-inherited-injected-arguments",
        ),
    ],
)
def test_claude_unresolved_api_access_is_rejected_even_with_all_permissions(
    preamble: str, body: str, feature: Path, tmp_path: Path
) -> None:
    (feature / "claude-code/register.ts").write_text(
        preamble
        + "export function register(on) {\n"
        + f'  on("session.start", async (api) => {{ {body} }});\n'
        + "}\n"
    )
    metadata = feature / "EXTENSION.md"
    metadata.write_text(
        metadata.read_text().replace(
            "permissions: []",
            "permissions: [fs.read, fs.write, process.spawn, network]",
        )
    )
    output = tmp_path / "output"
    with pytest.raises(builder.BuildError, match="claude artifact"):
        builder.build_feature(feature, output)
    assert not (output / "extensions" / NAME / "claude").exists()
    assert not (output / "extensions" / NAME / "omp").exists()


@pytest.mark.parametrize("transitive", [False, True])
def test_outside_json_never_enters_helper_bundle(
    transitive: bool, feature: Path, tmp_path: Path
) -> None:
    outside = feature.parent / "outside-secret.json"
    sentinel = b'{"synthetic":"OUTSIDE_PRIVATE_BYTES_73219"}\n'
    outside.write_bytes(sentinel)
    leaf = "helpers/bridge.ts" if transitive else "helpers/wordcount.ts"
    if transitive:
        (feature / "helpers/wordcount.ts").write_text('import "./bridge.ts";\n')
    (feature / leaf).write_text(
        'import value from "../../outside-secret.json"; console.log(value);\n'
    )
    output = tmp_path / "output"
    with pytest.raises(builder.BuildError, match="outside-secret.json"):
        builder.build_feature(feature, output)
    assert not output.exists()
    assert outside.read_bytes() == sentinel


@pytest.mark.parametrize(
    "case",
    [
        "escape",
        "leaf-link",
        "parent-link",
        "fifo",
        "data",
        "secret",
        "tests",
        "adapter",
    ],
)
def test_transitive_helper_inputs_are_contained_before_bundling(
    case: str, feature: Path, tmp_path: Path
) -> None:
    helper = feature / "helpers/wordcount.ts"
    helper.write_text('import { value } from "./bridge.ts"; console.log(value);\n')
    outside = tmp_path / "outside"
    outside.mkdir()
    foreign = outside / "value.ts"
    foreign.write_text('export const value = "OUTSIDE_GRAPH_SENTINEL";\n')
    bridge = feature / "helpers/bridge.ts"
    if case == "escape":
        specifier = "../../../outside/value.ts"
    elif case == "leaf-link":
        (feature / "helpers/value.ts").symlink_to(foreign)
        specifier = "./value.ts"
    elif case == "parent-link":
        (feature / "helpers/linked").symlink_to(outside, target_is_directory=True)
        specifier = "./linked/value.ts"
    elif case == "fifo":
        os.mkfifo(feature / "helpers/value.ts")
        specifier = "./value.ts"
    elif case == "data":
        (feature / "helpers/events.jsonl").write_text('{"synthetic":true}\n')
        specifier = "./events.jsonl"
    elif case == "secret":
        (feature / "helpers/.env.fixture").write_text("SYNTHETIC_ONLY=value\n")
        specifier = "./.env.fixture"
    elif case == "tests":
        (feature / "helpers/fixtures").mkdir()
        (feature / "helpers/fixtures/value.ts").write_text("export const value = 1;\n")
        specifier = "./fixtures/value.ts"
    else:
        (feature / "omp/value.ts").write_text("export const value = 1;\n")
        specifier = "../omp/value.ts"
    bridge.write_text(f'export {{ value }} from "{specifier}";\n')
    output = tmp_path / "output"
    with pytest.raises(builder.BuildError):
        builder.build_feature(feature, output)
    assert not output.exists()
    assert foreign.read_text() == 'export const value = "OUTSIDE_GRAPH_SENTINEL";\n'


@pytest.mark.parametrize(
    "source",
    [
        'import{x}from"../../outside.ts";export{x};',
        'const x=1;import { y } from "../../outside.ts";export {y};',
        'import\n{ x }\nfrom\n"../../outside.ts";export{x};',
        'export*from"../../outside.ts";',
        'export*as value from"../../outside.ts";',
        'import type{X}from"../../outside.ts";export type{X};',
        'import{type X}from"../../outside.ts";export type{X};',
        'export type{X}from"../../outside.ts";',
        'import"../../outside.ts";',
        'type X=import("../../outside.ts").X;export type{X};',
    ],
)
def test_static_module_syntax_cannot_hide_escaping_imports(source: str) -> None:
    with pytest.raises(builder.BuildError, match="outside.ts"):
        builder.check_artifact_imports({"omp/entry.ts": source.encode()}, "omp")


@pytest.mark.parametrize(
    "source",
    [
        'const path="./outside.ts";export const value=import(path);',
        'export const value=require("./outside.ts");',
        'const load=require;export const value=load("./outside.ts");',
        'import value=require("./outside.ts");export{value};',
        'export const value=globalThis["require"]("./outside.ts");',
        'export const value=globalThis["requ"+"ire"]("./outside.ts");',
        'export const value=import.meta["requ"+"ire"]("./outside.ts");',
        'import{value}from"./outside.ts"with{type:"macro"};export{value};',
    ],
)
def test_dynamic_or_macro_loads_are_refused(source: str) -> None:
    with pytest.raises(builder.BuildError, match="unsupported module load"):
        builder.check_artifact_imports({"omp/entry.ts": source.encode()}, "omp")


def test_parser_preserves_valid_compact_modules_and_ignores_comment_text(
    feature: Path, tmp_path: Path
) -> None:
    source = (
        b'const text="require( and import( are documentation";\n'
        b'// import{x}from"../../outside.ts";\n'
        b'import{countWords}from"../core/index.ts";'
        b'export{countWords}from"../core/index.ts";'
        b"export const value=countWords(text);\n"
    )
    (feature / "omp/compact.ts").write_bytes(source)
    artifacts = builder.build_feature(feature, tmp_path / "output")
    assert (artifacts["omp"] / "omp/compact.ts").read_bytes() == source
    manifest = builder.verify_artifact_dir(artifacts["omp"])
    assert "omp/compact.ts" in {entry["path"] for entry in manifest["files"]}


def test_runner_entry_and_transitive_helper_graph_are_detached_and_reproducible(
    feature: Path, tmp_path: Path
) -> None:
    (feature / "runner").mkdir()
    (feature / "runner/wordcount.ts").write_text(
        'import { count } from "../helpers/bridge.ts";\n'
        'import { basename } from "node:path";\n'
        'console.log(JSON.stringify({words:count(process.argv.slice(2).join(" ")),name:basename("/synthetic/input")}));\n'
    )
    (feature / "helpers/bridge.ts").write_text(
        'export { count } from "../runner/count.ts";\n'
    )
    (feature / "runner/count.ts").write_text(
        'import { countWords } from "../core/index.ts";\n'
        'import config from "./defaults.json" with {type:"json"};\n'
        "export const count = (text: string) => countWords(text) + config.offset;\n"
    )
    (feature / "runner/defaults.json").write_text('{"offset":1}\n')
    definition = feature / "EXTENSION.md"
    definition.write_text(
        definition.read_text().replace(
            "- helpers/wordcount.ts", "- runner/wordcount.ts"
        )
    )
    first = builder.build_feature(feature, tmp_path / "first")
    other_source = tmp_path / "elsewhere" / NAME
    shutil.copytree(feature, other_source)
    second = builder.build_feature(other_source, tmp_path / "second")
    for host in first:
        assert _tree(first[host]) == _tree(second[host])
        assert not (first[host] / "runner").exists()
        assert (first[host] / "helpers/wordcount.js").is_file()
    detached = tmp_path / "detached"
    shutil.copytree(first["claude"], detached)
    shutil.rmtree(feature)
    shutil.rmtree(other_source)
    result = subprocess.run(
        [builder.require_bun(), "helpers/wordcount.js", "one", "two"],
        cwd=detached,
        env={"PATH": os.environ["PATH"], "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"words": 3, "name": "input"}


@pytest.mark.parametrize("component", ["output", "extensions", "feature", "host"])
def test_every_generated_output_ancestor_refuses_links(
    component: str, feature: Path, tmp_path: Path
) -> None:
    output = tmp_path / "output"
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "KEEP").write_bytes(b"FOREIGN_OUTPUT_SENTINEL\n")
    if component == "output":
        link = output
    elif component == "extensions":
        output.mkdir()
        link = output / "extensions"
    elif component == "feature":
        (output / "extensions").mkdir(parents=True)
        link = output / "extensions" / NAME
    else:
        (output / "extensions" / NAME).mkdir(parents=True)
        link = output / "extensions" / NAME / "omp"
    link.symlink_to(foreign, target_is_directory=True)
    before = _tree(foreign)
    with pytest.raises(builder.BuildError, match="symbolic link"):
        builder.build_feature(feature, output)
    assert _tree(foreign) == before
    assert link.is_symlink()


def test_output_parent_link_cannot_reach_canonical_source(
    feature: Path, tmp_path: Path
) -> None:
    output = tmp_path / "output"
    output.mkdir()
    (output / "extensions").symlink_to(feature, target_is_directory=True)
    before = _tree(feature)
    with pytest.raises(builder.BuildError, match="symbolic link"):
        builder.build_feature(feature, output)
    assert _tree(feature) == before


@pytest.mark.parametrize("host", ["omp", "claude"])
@pytest.mark.parametrize(
    "mutation",
    ["modified", "modified-mode", "foreign-file", "foreign-directory", "manifest-link"],
)
def test_rebuild_preserves_all_modified_or_foreign_output(
    host: str, mutation: str, feature: Path, tmp_path: Path
) -> None:
    output = tmp_path / "output"
    artifacts = builder.build_feature(feature, output)
    selected = artifacts[host]
    if mutation == "modified":
        (selected / "core/index.ts").write_bytes(b"LOCAL_EDIT_MUST_SURVIVE\n")
    elif mutation == "modified-mode":
        (selected / "core/index.ts").chmod(0o600)
    elif mutation == "foreign-file":
        (selected / "foreign-note.md").write_bytes(b"FOREIGN_NOTE_MUST_SURVIVE\n")
    elif mutation == "foreign-directory":
        (selected / "foreign-empty-directory").mkdir()
    else:
        manifest = selected / builder.CONTENT_MANIFEST
        foreign = tmp_path / "foreign-manifest.json"
        foreign.write_bytes(manifest.read_bytes())
        manifest.unlink()
        manifest.symlink_to(foreign)
    before = {name: _tree(path) for name, path in artifacts.items()}
    with pytest.raises(builder.BuildError):
        builder.build_feature(feature, output)
    assert {name: _tree(path) for name, path in artifacts.items()} == before
    if mutation == "modified-mode":
        assert (selected / "core/index.ts").stat().st_mode & 0o777 == 0o600
    if mutation == "foreign-directory":
        assert (selected / "foreign-empty-directory").is_dir()
    if mutation == "manifest-link":
        assert (selected / builder.CONTENT_MANIFEST).is_symlink()


@pytest.mark.parametrize("failed_host", ["omp", "claude"])
@pytest.mark.parametrize("existing", [True, False])
def test_host_swap_failure_restores_every_previous_artifact(
    failed_host: str,
    existing: bool,
    feature: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "output"
    if existing:
        artifacts = builder.build_feature(feature, output)
        before = {host: _tree(path) for host, path in artifacts.items()}
    else:
        artifacts = {
            host: output / "extensions" / NAME / host for host in ("omp", "claude")
        }
        before = {}
    (feature / "core/index.ts").write_text(
        "export const countWords = (text: string): number => text.trim() ? 99 : 0;\n"
    )
    rename = os.rename
    injected = False

    def fail_activation(
        source: Any, destination: Any, *args: Any, **kwargs: Any
    ) -> None:
        nonlocal injected
        source_path, destination_path = Path(source), Path(destination)
        if (
            not injected
            and destination_path == artifacts[failed_host]
            and source_path.name == failed_host
        ):
            injected = True
            raise OSError("synthetic activation failure")
        rename(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "rename", fail_activation)
    with pytest.raises(OSError, match="synthetic activation failure"):
        builder.build_feature(feature, output)
    assert injected
    if existing:
        assert {host: _tree(path) for host, path in artifacts.items()} == before
        for path in artifacts.values():
            assert builder.verify_artifact_dir(path)["version"] == "1.0.0"
    else:
        assert all(not path.exists() for path in artifacts.values())
    assert not list((output / "extensions" / NAME).glob(".staging-*"))


def test_helper_macros_are_refused_before_they_can_execute(
    feature: Path, tmp_path: Path
) -> None:
    marker = tmp_path / "macro-must-not-execute"
    (feature / "helpers/wordcount.ts").write_text(
        'import { value } from "./macro.ts" with {type:"macro"};\n'
        "console.log(value());\n"
    )
    (feature / "helpers/macro.ts").write_text(
        'import { writeFileSync } from "node:fs";\n'
        f'export function value() {{ writeFileSync({json.dumps(str(marker))}, "BAD"); return 1; }}\n'
    )
    with pytest.raises(builder.BuildError, match="macros"):
        builder.build_feature(feature, tmp_path / "output")
    assert not marker.exists()
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize(
    "corruption", ["traversal", "duplicate", "bad-size", "missing-files"]
)
def test_malformed_owned_manifests_are_refused_without_output_loss(
    corruption: str, feature: Path, tmp_path: Path
) -> None:
    output = tmp_path / "output"
    artifacts = builder.build_feature(feature, output)
    path = artifacts["claude"] / builder.CONTENT_MANIFEST
    manifest = json.loads(path.read_text())
    if corruption == "traversal":
        manifest["files"][0]["path"] = "../../../FOREIGN"
    elif corruption == "duplicate":
        manifest["files"].append(dict(manifest["files"][0]))
    elif corruption == "bad-size":
        manifest["files"][0]["size"] = True
    else:
        del manifest["files"]
    path.write_text(json.dumps(manifest))
    before = {host: _tree(root) for host, root in artifacts.items()}
    with pytest.raises(builder.BuildError, match="invalid content manifest"):
        builder.build_feature(feature, output)
    assert {host: _tree(root) for host, root in artifacts.items()} == before


def test_rollback_retains_old_tree_and_concurrent_foreign_addition(
    feature: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "output"
    artifacts = builder.build_feature(feature, output)
    original = {host: _tree(root) for host, root in artifacts.items()}
    rename = os.rename
    injected = False

    def fail_after_foreign_write(
        source: Any, destination: Any, *args: Any, **kwargs: Any
    ) -> None:
        nonlocal injected
        if (
            not injected
            and Path(source).name == "claude"
            and Path(destination) == artifacts["claude"]
        ):
            injected = True
            (artifacts["omp"] / "foreign-note.md").write_bytes(
                b"CONCURRENT_FOREIGN_NOTE\n"
            )
            raise OSError("synthetic second-host failure")
        rename(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "rename", fail_after_foreign_write)
    with pytest.raises(builder.BuildError, match="rollback needs recovery"):
        builder.build_feature(feature, output)
    assert injected
    assert (
        artifacts["omp"] / "foreign-note.md"
    ).read_bytes() == b"CONCURRENT_FOREIGN_NOTE\n"
    assert _tree(artifacts["claude"]) == original["claude"]
    transactions = list((output / "extensions" / NAME).glob(".staging-build-*"))
    assert len(transactions) == 1
    assert _tree(transactions[0] / "retired-omp") == original["omp"]


@pytest.mark.parametrize("transitive", [False, True])
@pytest.mark.parametrize(
    "reference",
    [
        'import "../helpers/wordcount.js";\n',
        'export * from "../helpers/wordcount.js";\n',
    ],
)
def test_claude_modules_cannot_import_executable_helpers(
    transitive: bool, reference: str, feature: Path, tmp_path: Path
) -> None:
    entry = feature / "claude-code/register.ts"
    if transitive:
        (entry.parent / "bridge.ts").write_text(reference)
        reference = 'import "./bridge.ts";\n'
    with entry.open("a") as handle:
        handle.write("\n" + reference)

    output = tmp_path / "output"
    with pytest.raises(builder.BuildError):
        builder.build_feature(feature, output)
    assert not output.exists()


@pytest.mark.parametrize("failed_host", ["omp", "claude"])
def test_rollback_preserves_concurrent_empty_destination_and_retired_artifacts(
    failed_host: str,
    feature: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "output"
    artifacts = builder.build_feature(feature, output)
    original = {host: _tree(path) for host, path in artifacts.items()}
    (feature / "core/index.ts").write_text(
        "export const countWords = (text: string): number => text.trim() ? 99 : 0;\n"
    )
    rename = os.rename
    foreign_inode: int | None = None

    def fail_with_foreign_destination(
        source: Any, destination: Any, *args: Any, **kwargs: Any
    ) -> None:
        nonlocal foreign_inode
        if (
            foreign_inode is None
            and Path(source).name == failed_host
            and Path(destination) == artifacts[failed_host]
        ):
            foreign = artifacts[failed_host]
            foreign.mkdir(mode=0o711)
            foreign.chmod(0o711)
            foreign_inode = foreign.stat().st_ino
            raise OSError("synthetic activation failure with foreign destination")
        rename(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "rename", fail_with_foreign_destination)
    with pytest.raises(builder.BuildError, match="rollback needs recovery"):
        builder.build_feature(feature, output)

    foreign = artifacts[failed_host]
    assert foreign_inode is not None
    assert foreign.stat().st_ino == foreign_inode
    assert stat.S_IMODE(foreign.stat().st_mode) == 0o711
    assert list(foreign.iterdir()) == []
    transactions = list((output / "extensions" / NAME).glob(".staging-build-*"))
    assert len(transactions) == 1
    for host, destination in artifacts.items():
        retired = transactions[0] / f"retired-{host}"
        assert _tree(retired if retired.exists() else destination) == original[host]
