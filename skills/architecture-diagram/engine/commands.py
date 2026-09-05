#!/usr/bin/env python3
"""Architecture-diagram validation, delivery, and comparison CLI."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from . import fetch_icons
from .compare import compare_specs
from .diagnostics import (
    QUALITY_PROFILES,
    QUALITY_STANDARD,
    SEVERITY_ERROR,
    Diagnostic,
)
from .geometry_checks import edge_label_box
from .icons import (
    BundledGenericIconLookup,
    CacheIconLookup,
    CompositeIconLookup,
    IconLookup,
)
from .layout import box_evidence
from .model import Spec
from .pipeline import RenderResult, render
from .spec import SpecError, load_spec
from .receipts import comparison_receipt, receipt as build_receipt


EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2


def _layout_report(spec: Spec, result: RenderResult) -> dict[str, object]:
    """Expose the exact boxes and waypoints used by SVG emission."""
    return {
        "nodes": [
            {"id": node.id, "box": box_evidence(result.node_boxes[node.id])}
            for node in spec.nodes
        ],
        "zones": [
            {
                "id": zone.id,
                "label": zone.label,
                "parent": zone.parent,
                "members": [node.id for node in spec.nodes if node.zone == zone.id],
                "box": box_evidence(result.zone_boxes[zone.id]),
            }
            for zone in spec.zones
        ],
        "edges": [
            {
                "from": routed.edge.src,
                "to": routed.edge.dst,
                "label": routed.edge.label,
                "type": routed.edge.type,
                "points": [{"x": x, "y": y} for x, y in routed.points],
                "label_position": {
                    "x": routed.label_pos[0],
                    "y": routed.label_pos[1],
                },
            }
            for routed in result.routed_edges
        ],
        "labels": [
            {
                "edge": {"from": routed.edge.src, "to": routed.edge.dst},
                "text": routed.edge.label,
                "box": box_evidence(edge_label_box(routed)),
            }
            for routed in result.routed_edges
            if routed.edge.label
        ],
    }


def _report(
    receipt: dict[str, object], as_json: bool, diagnostics: list[Diagnostic]
) -> None:
    """Under --json, stdout carries the receipt and nothing else."""
    if as_json:
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return
    output = receipt["output"]
    assert isinstance(output, dict)
    if output["written"]:
        artifact = receipt["artifact"]
        assert isinstance(artifact, dict)
        print(f"wrote {output['path']} ({artifact['bytes']} bytes)")
    for d in diagnostics:
        print(f"{d.severity}: [{d.code}] {d.message}", file=sys.stderr)
        for fix in d.supported_fixes:
            print(f"  fix: {fix}", file=sys.stderr)


def _input_failure(
    command: str, spec_path: Path, output: Path | None, quality: str, exc: Exception
) -> tuple[int, dict[str, object], list[Diagnostic]]:
    diagnostic = Diagnostic(
        code="usage/spec-unreadable",
        severity=SEVERITY_ERROR,
        message=f"cannot read spec {str(spec_path)!r}: {exc}",
        subject={"path": str(spec_path)},
        supported_fixes=("pass the path to an existing UTF-8 YAML spec",),
    )
    return (
        EXIT_USAGE,
        build_receipt(
            command,
            spec_path,
            None,
            None,
            [diagnostic],
            quality,
            output=output,
            delivery_stage="input",
        ),
        [diagnostic],
    )


def _read_spec(
    command: str, spec_path: Path, output: Path | None, quality: str
) -> tuple[bytes, str] | tuple[int, dict[str, object], list[Diagnostic]]:
    try:
        source = spec_path.read_bytes()
        return source, source.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return _input_failure(command, spec_path, output, quality, exc)


def _read_comparison_spec(
    side: str, path: Path
) -> tuple[bytes | None, Spec | None, Diagnostic | None]:
    try:
        source = path.read_bytes()
        text = source.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return (
            None,
            None,
            Diagnostic(
                code=f"compare/{side}-unreadable",
                severity=SEVERITY_ERROR,
                message=f"cannot read {side} specification {str(path)!r}: {exc}",
                subject={"path": str(path)},
                supported_fixes=("pass an existing UTF-8 YAML specification",),
            ),
        )
    try:
        return source, load_spec(text), None
    except SpecError as exc:
        return source, None, exc.diagnostic


def _compare(
    base_path: Path, head_path: Path
) -> tuple[int, dict[str, object], list[Diagnostic]]:
    base_bytes, base_spec, base_error = _read_comparison_spec("base", base_path)
    head_bytes, head_spec, head_error = _read_comparison_spec("head", head_path)
    diagnostics = [error for error in (base_error, head_error) if error is not None]
    if diagnostics:
        return (
            EXIT_FAILURE,
            comparison_receipt(
                base_path, base_bytes, head_path, head_bytes, diagnostics
            ),
            diagnostics,
        )

    assert base_spec is not None
    assert head_spec is not None
    try:
        comparison = compare_specs(base_spec, head_spec)
    except SpecError as exc:
        diagnostics = [exc.diagnostic]
        return (
            EXIT_FAILURE,
            comparison_receipt(
                base_path, base_bytes, head_path, head_bytes, diagnostics
            ),
            diagnostics,
        )
    return (
        EXIT_OK,
        comparison_receipt(
            base_path, base_bytes, head_path, head_bytes, [], comparison
        ),
        [],
    )


def _icon_lookup(cache_dir: Path | None, sha: str | None) -> IconLookup:
    selected_cache_dir = cache_dir or fetch_icons.default_cache_dir()
    selected_sha = sha or fetch_icons.DRAWIO_SHA
    return CompositeIconLookup(
        [
            CacheIconLookup(cache_dir=selected_cache_dir, sha=selected_sha),
            BundledGenericIconLookup(),
        ]
    )


def _render_candidate(
    spec_text: str, lookup: IconLookup, quality: str
) -> tuple[Spec | None, RenderResult | None, bytes | None, list[Diagnostic]]:
    try:
        spec = load_spec(spec_text)
    except SpecError as exc:
        return None, None, None, [exc.diagnostic]
    result = render(spec, lookup, quality=quality)
    return spec, result, result.svg.encode("utf-8"), result.diagnostics


def _validate(
    spec_path: Path,
    cache_dir: Path | None,
    sha: str | None,
    quality: str,
    layout_json: bool,
) -> tuple[int, dict[str, object], list[Diagnostic]]:
    loaded = _read_spec("validate", spec_path, None, quality)
    if len(loaded) == 3:
        return loaded
    spec_bytes, spec_text = loaded
    spec, result, artifact_bytes, diagnostics = _render_candidate(
        spec_text, _icon_lookup(cache_dir, sha), quality
    )
    if artifact_bytes is not None:
        with tempfile.TemporaryDirectory(
            prefix=".architecture-diagram-validate-"
        ) as path:
            candidate = Path(path) / "candidate.svg"
            candidate.write_bytes(artifact_bytes)
            artifact_bytes = candidate.read_bytes()
    receipt = build_receipt(
        "validate",
        spec_path,
        spec_bytes,
        artifact_bytes,
        diagnostics,
        quality,
        delivery_stage="check" if result is not None and not result.ok else None,
        profile_active=spec is not None and spec.profile is not None,
    )
    if layout_json and spec is not None and result is not None:
        receipt["layout"] = _layout_report(spec, result)
    return (EXIT_OK if receipt["ok"] else EXIT_FAILURE), receipt, diagnostics


def _delivery_failure(
    spec_path: Path,
    spec_bytes: bytes | None,
    artifact_bytes: bytes | None,
    output: Path,
    quality: str,
    stage: str,
    exc: Exception,
) -> tuple[int, dict[str, object], list[Diagnostic]]:
    diagnostic = Diagnostic(
        code=f"delivery/{stage}-failed",
        severity=SEVERITY_ERROR,
        message=f"delivery {stage} failed: {exc}",
        subject={"output": str(output)},
        supported_fixes=(
            "correct the output path or filesystem permissions and rerun delivery",
        ),
    )
    return (
        EXIT_FAILURE,
        build_receipt(
            "deliver",
            spec_path,
            spec_bytes,
            artifact_bytes,
            [diagnostic],
            quality,
            output=output,
            delivery_stage=stage,
        ),
        [diagnostic],
    )


def _deliver(
    spec_path: Path,
    output: Path,
    cache_dir: Path | None,
    sha: str | None,
    quality: str,
) -> tuple[int, dict[str, object], list[Diagnostic]]:
    loaded = _read_spec("deliver", spec_path, output, quality)
    if len(loaded) == 3:
        return loaded
    spec_bytes, spec_text = loaded
    output_parent = output.parent
    try:
        if not output_parent.is_dir():
            raise OSError(f"output directory does not exist: {output_parent}")
        with tempfile.TemporaryDirectory(
            prefix=".architecture-diagram-delivery-", dir=output_parent
        ) as stage_name:
            stage_dir = Path(stage_name)
            if os.stat(stage_dir).st_dev != os.stat(output_parent).st_dev:
                raise OSError("staging directory is not on the output filesystem")
            (stage_dir / "specification.yaml").write_bytes(spec_bytes)
            spec, result, artifact_bytes, diagnostics = _render_candidate(
                spec_text, _icon_lookup(cache_dir, sha), quality
            )
            if artifact_bytes is None:
                receipt = build_receipt(
                    "deliver",
                    spec_path,
                    spec_bytes,
                    None,
                    diagnostics,
                    quality,
                    output=output,
                    delivery_stage="render",
                    profile_active=spec is not None and spec.profile is not None,
                )
                return EXIT_FAILURE, receipt, diagnostics
            candidate = stage_dir / "candidate.svg"
            candidate.write_bytes(artifact_bytes)
            if os.stat(candidate).st_dev != os.stat(output_parent).st_dev:
                raise OSError("candidate artifact is not on the output filesystem")
            if result is None or not result.ok:
                receipt = build_receipt(
                    "deliver",
                    spec_path,
                    spec_bytes,
                    artifact_bytes,
                    diagnostics,
                    quality,
                    output=output,
                    delivery_stage="check",
                    profile_active=spec is not None and spec.profile is not None,
                )
                return EXIT_FAILURE, receipt, diagnostics
            receipt = build_receipt(
                "deliver",
                spec_path,
                spec_bytes,
                artifact_bytes,
                diagnostics,
                quality,
                output=output,
                written=True,
                delivery_stage="commit",
                profile_active=spec is not None and spec.profile is not None,
            )
            try:
                (stage_dir / "receipt.json").write_text(
                    json.dumps(receipt, indent=2, sort_keys=True)
                )
            except OSError as exc:
                return _delivery_failure(
                    spec_path,
                    spec_bytes,
                    artifact_bytes,
                    output,
                    quality,
                    "receipt",
                    exc,
                )
            try:
                os.replace(candidate, output)
            except OSError as exc:
                return _delivery_failure(
                    spec_path,
                    spec_bytes,
                    artifact_bytes,
                    output,
                    quality,
                    "commit",
                    exc,
                )
            return EXIT_OK, receipt, diagnostics
    except OSError as exc:
        return _delivery_failure(
            spec_path, spec_bytes, None, output, quality, "prepare", exc
        )


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("spec", type=Path, help="path to a UTF-8 YAML spec")
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--sha", default=None)
    parser.add_argument(
        "--quality",
        choices=QUALITY_PROFILES,
        default=QUALITY_STANDARD,
        help="showcase raises composition findings from warnings to errors",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="print the machine-readable receipt to stdout and nothing else",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate_parser = commands.add_parser(
        "validate", help="render and validate without writing an output artifact"
    )
    _add_common_arguments(validate_parser)
    validate_parser.add_argument(
        "--layout-json",
        action="store_true",
        help="print the exact emitted layout geometry without writing an SVG",
    )
    deliver_parser = commands.add_parser(
        "deliver", help="validate, stage, and atomically commit an SVG artifact"
    )
    _add_common_arguments(deliver_parser)
    deliver_parser.add_argument(
        "-o", "--output", type=Path, required=True, help="target SVG path"
    )
    compare_parser = commands.add_parser(
        "compare", help="compare two authored specifications into a JSON receipt"
    )
    compare_parser.add_argument("base", type=Path, help="baseline UTF-8 YAML spec")
    compare_parser.add_argument("head", type=Path, help="changed UTF-8 YAML spec")

    args = parser.parse_args(argv)

    if args.command == "compare":
        code, receipt, diagnostics = _compare(args.base, args.head)
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return code
    if args.command == "validate":
        code, receipt, diagnostics = _validate(
            args.spec, args.cache_dir, args.sha, args.quality, args.layout_json
        )
    else:
        code, receipt, diagnostics = _deliver(
            args.spec, args.output, args.cache_dir, args.sha, args.quality
        )
    _report(receipt, args.as_json or getattr(args, "layout_json", False), diagnostics)
    return code


if __name__ == "__main__":
    sys.exit(main())
