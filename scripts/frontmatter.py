#!/usr/bin/env python3
"""Shared frontmatter parsing utilities for armory package definitions."""
from __future__ import annotations

import re
from typing import Any

import yaml


class FrontmatterError(ValueError):
    """A package definition contains invalid frontmatter."""


def parse_frontmatter(content: str) -> dict[str, Any]:
    """Parse YAML frontmatter from a package definition file.

    Raises ValueError when frontmatter is absent, is not valid YAML, or is not a mapping.
    """
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        raise FrontmatterError("No valid YAML frontmatter found")
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise FrontmatterError(f"Invalid YAML frontmatter: {exc}") from exc
    if not isinstance(data, dict):
        raise FrontmatterError(f"Frontmatter must be a YAML mapping, got {type(data).__name__}")
    return data


def extract_version(meta: dict[str, Any]) -> str:
    """Extract version from metadata.version (preferred) or top-level version (legacy)."""
    metadata = meta.get("metadata")
    if isinstance(metadata, dict) and metadata.get("version"):
        return str(metadata["version"])
    return str(meta.get("version", ""))


def extract_body(content: str) -> str:
    """Extract body content after frontmatter closing '---'."""
    match = re.match(r"^---\s*\n.*?\n---\s*\n(.*)$", content, re.DOTALL)
    return match.group(1) if match else content


def validate_version(version: str) -> bool:
    """Validate semver format: X.Y.Z (digits only, no pre-release tags)."""
    return re.fullmatch(r"\d+\.\d+\.\d+", version) is not None
