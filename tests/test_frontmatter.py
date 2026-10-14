"""Tests for frontmatter parsing utilities."""
from __future__ import annotations

import pytest
import yaml

from scripts.frontmatter import (
    extract_body,
    extract_version,
    parse_frontmatter,
    validate_version,
)


class TestParseFrontmatter:
    """Tests for parse_frontmatter."""

    def test_valid_frontmatter(self) -> None:
        content = "---\nname: test-skill\ndescription: A test\n---\nBody here.\n"
        result = parse_frontmatter(content)
        assert result["name"] == "test-skill"
        assert result["description"] == "A test"

    def test_no_frontmatter_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_frontmatter("Just plain text, no frontmatter.")

    def test_incomplete_frontmatter_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_frontmatter("---\nname: broken\nno closing delimiter")

    def test_multiline_frontmatter(self) -> None:
        content = "---\nname: multi\ndescription: |\n  Line one.\n  Line two.\ntags:\n  - a\n  - b\n---\nBody.\n"
        result = parse_frontmatter(content)
        assert result["name"] == "multi"
        assert "Line one." in result["description"]
        assert result["tags"] == ["a", "b"]

    def test_frontmatter_with_nested_metadata(self) -> None:
        content = "---\nname: nested\nmetadata:\n  version: 1.2.3\n  author: test\n---\nBody.\n"
        result = parse_frontmatter(content)
        assert result["metadata"]["version"] == "1.2.3"
        assert result["metadata"]["author"] == "test"

    @pytest.mark.parametrize(
        "content",
        [
            "---\n\n---\nBody.\n",
            "---\n- a\n- b\n---\nBody.\n",
            "---\njust a scalar\n---\nBody.\n",
            "---\n42\n---\nBody.\n",
        ],
        ids=["null", "list", "string", "int"],
    )
    def test_non_mapping_frontmatter_raises(self, content: str) -> None:
        with pytest.raises(ValueError):
            parse_frontmatter(content)

    def test_malformed_yaml_raises_value_error_with_cause(self) -> None:
        content = "---\nname: [unclosed\n---\nBody.\n"
        with pytest.raises(ValueError) as excinfo:
            parse_frontmatter(content)
        assert isinstance(excinfo.value.__cause__, yaml.YAMLError)

    def test_flow_mapping_frontmatter_accepted(self) -> None:
        assert parse_frontmatter("---\n{}\n---\nBody.\n") == {}


class TestExtractVersion:
    """Tests for extract_version."""

    def test_metadata_version_preferred(self) -> None:
        meta = {"version": "0.1.0", "metadata": {"version": "2.0.0"}}
        assert extract_version(meta) == "2.0.0"

    def test_top_level_version_fallback(self) -> None:
        meta = {"version": "1.0.0"}
        assert extract_version(meta) == "1.0.0"

    def test_empty_version_returns_empty(self) -> None:
        meta = {}
        assert extract_version(meta) == ""

    def test_metadata_without_version_falls_back(self) -> None:
        meta = {"metadata": {"author": "test"}, "version": "3.0.0"}
        assert extract_version(meta) == "3.0.0"

    def test_metadata_not_dict_falls_back(self) -> None:
        meta = {"metadata": "not-a-dict", "version": "4.0.0"}
        assert extract_version(meta) == "4.0.0"

    def test_numeric_version_converted_to_str(self) -> None:
        meta = {"version": 1}
        assert extract_version(meta) == "1"


class TestExtractBody:
    """Tests for extract_body."""

    def test_body_after_frontmatter(self) -> None:
        content = "---\nname: test\n---\nThe body content.\n"
        assert extract_body(content) == "The body content.\n"

    def test_no_frontmatter_returns_content(self) -> None:
        content = "Just plain text."
        assert extract_body(content) == "Just plain text."

    def test_multiline_body(self) -> None:
        content = "---\nname: x\n---\nLine 1.\nLine 2.\nLine 3.\n"
        body = extract_body(content)
        assert "Line 1." in body
        assert "Line 3." in body

    def test_empty_body(self) -> None:
        content = "---\nname: empty\n---\n"
        assert extract_body(content) == ""


class TestValidateVersion:
    """Tests for validate_version."""

    def test_valid_zero_version(self) -> None:
        assert validate_version("0.0.0") is True

    def test_valid_standard_version(self) -> None:
        assert validate_version("1.2.3") is True

    def test_valid_large_numbers(self) -> None:
        assert validate_version("10.200.3000") is True

    def test_invalid_two_parts(self) -> None:
        assert validate_version("1.0") is False

    def test_invalid_v_prefix(self) -> None:
        assert validate_version("v1.0.0") is False

    def test_invalid_prerelease(self) -> None:
        assert validate_version("1.0.0-beta") is False

    def test_invalid_empty(self) -> None:
        assert validate_version("") is False

    def test_invalid_text(self) -> None:
        assert validate_version("latest") is False

    @pytest.mark.parametrize("version", ["1.2.3\n", "1.2.3\r\n", "\n1.2.3", " 1.2.3"])
    def test_invalid_whitespace_variants(self, version: str) -> None:
        assert validate_version(version) is False
