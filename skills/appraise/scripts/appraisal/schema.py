"""Stdlib validator for the JSON Schema 2020-12 subset used by this package.

Supported keywords: type, enum, const, required, properties,
additionalProperties, items, minItems, maxItems, uniqueItems, minimum,
maximum, minLength, maxLength, pattern, $ref (local "#/$defs/..."), anyOf,
oneOf, allOf. Any other validation keyword raises, so bundled schemas cannot
silently depend on validation this module does not perform.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

SCHEMA_DIR = Path(__file__).resolve().parent.parent.parent / "schemas"
SCHEMA_NAMES = ("input", "forensics", "judgments", "evidence", "assessment", "rubric")

_ANNOTATIONS = frozenset(
    {
        "$schema",
        "$id",
        "title",
        "description",
        "$defs",
        "default",
        "examples",
        "$comment",
        "format",
    }
)
_SUPPORTED = frozenset(
    {
        "type",
        "enum",
        "const",
        "required",
        "properties",
        "additionalProperties",
        "items",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "pattern",
        "$ref",
        "anyOf",
        "oneOf",
        "allOf",
    }
)


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


_TYPE_CHECKS: dict[str, Any] = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": _is_number,
    "null": lambda v: v is None,
}


class SchemaError(ValueError):
    """A document does not satisfy its schema."""

    def __init__(self, schema_name: str, errors: list[str]) -> None:
        self.schema_name = schema_name
        self.errors = errors
        super().__init__(
            f"{schema_name}: {len(errors)} schema error(s): " + "; ".join(errors[:8])
        )


@cache
def load_schema(name: str) -> dict[str, Any]:
    if name not in SCHEMA_NAMES:
        raise ValueError(f"unknown schema {name!r}; expected one of {SCHEMA_NAMES}")
    data: dict[str, Any] = json.loads(
        (SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8")
    )
    return data


def errors_for(instance: Any, schema_name: str) -> list[str]:
    root = load_schema(schema_name)
    errors: list[str] = []
    _validate(instance, root, root, "$", errors)
    return errors


def validate(instance: Any, schema_name: str) -> None:
    errors = errors_for(instance, schema_name)
    if errors:
        raise SchemaError(schema_name, errors)


def _resolve(ref: str, root: dict[str, Any]) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise ValueError(f"only local $ref is supported: {ref}")
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part]
    if not isinstance(node, dict):
        raise TypeError(f"$ref does not resolve to a schema object: {ref}")
    return node


def _validate(
    value: Any,
    schema: dict[str, Any],
    root: dict[str, Any],
    path: str,
    errors: list[str],
) -> None:
    unknown = set(schema) - _SUPPORTED - _ANNOTATIONS
    if unknown:
        raise ValueError(f"unsupported schema keyword(s) at {path}: {sorted(unknown)}")
    if "$ref" in schema:
        _validate(value, _resolve(schema["$ref"], root), root, path, errors)
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_TYPE_CHECKS[t](value) for t in types):
            errors.append(
                f"{path}: expected {'|'.join(types)}, got {type(value).__name__}"
            )
            return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected constant {schema['const']!r}")
    if isinstance(value, dict):
        _validate_object(value, schema, root, path, errors)
    elif isinstance(value, list):
        _validate_array(value, schema, root, path, errors)
    elif isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']}")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            errors.append(f"{path}: {value!r} does not match {schema['pattern']}")
    elif _is_number(value):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: {value} < {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: {value} > {schema['maximum']}")
    for keyword in ("allOf", "anyOf", "oneOf"):
        if keyword in schema:
            _validate_combinator(keyword, value, schema[keyword], root, path, errors)


def _validate_combinator(
    keyword: str,
    value: Any,
    subs: list[dict[str, Any]],
    root: dict[str, Any],
    path: str,
    errors: list[str],
) -> None:
    outcomes: list[list[str]] = []
    for sub in subs:
        sub_errors: list[str] = []
        _validate(value, sub, root, path, sub_errors)
        outcomes.append(sub_errors)
    passed = sum(1 for o in outcomes if not o)
    if keyword == "allOf":
        for o in outcomes:
            errors.extend(o)
    elif keyword == "anyOf" and passed == 0:
        errors.append(
            f"{path}: matches none of anyOf ({'; '.join(o[0] for o in outcomes if o)})"
        )
    elif keyword == "oneOf" and passed != 1:
        detail = "; ".join(o[0] for o in outcomes if o) if passed == 0 else ""
        errors.append(
            f"{path}: matches {passed} of oneOf, expected exactly 1 {detail}".rstrip()
        )


def _validate_object(
    value: dict[str, Any],
    schema: dict[str, Any],
    root: dict[str, Any],
    path: str,
    errors: list[str],
) -> None:
    for key in schema.get("required", []):
        if key not in value:
            errors.append(f"{path}: missing required property {key!r}")
    props: dict[str, Any] = schema.get("properties", {})
    extra = schema.get("additionalProperties", True)
    for key, item in value.items():
        child = f"{path}.{key}"
        if key in props:
            _validate(item, props[key], root, child, errors)
        elif extra is False:
            errors.append(f"{path}: unexpected property {key!r}")
        elif isinstance(extra, dict):
            _validate(item, extra, root, child, errors)


def _validate_array(
    value: list[Any],
    schema: dict[str, Any],
    root: dict[str, Any],
    path: str,
    errors: list[str],
) -> None:
    if "minItems" in schema and len(value) < schema["minItems"]:
        errors.append(f"{path}: fewer than {schema['minItems']} items")
    if "maxItems" in schema and len(value) > schema["maxItems"]:
        errors.append(f"{path}: more than {schema['maxItems']} items")
    if schema.get("uniqueItems"):
        seen = [json.dumps(v, sort_keys=True) for v in value]
        if len(seen) != len(set(seen)):
            errors.append(f"{path}: items are not unique")
    if "items" in schema:
        for index, item in enumerate(value):
            _validate(item, schema["items"], root, f"{path}[{index}]", errors)
