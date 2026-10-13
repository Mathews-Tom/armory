#!/usr/bin/env python3
"""One-time script to backfill tags, category, and difficulty into package metadata."""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

from scripts.package_types import REPO_ROOT, TYPES


# ---------------------------------------------------------------------------
# Category assignment rules
# ---------------------------------------------------------------------------

CATEGORY_PATTERNS: list[tuple[list[str], str]] = [
    (["review", "audit", "quality", "lint"], "review"),
    (["security", "secret", "vulnerability", "sentinel"], "security"),
    (["research", "literature", "paper", "academic", "critique"], "research"),
    (["competitive", "market", "feasibility", "idea", "validator"], "business"),
    (
        [
            "image", "video", "diagram", "presentation", "visual",
            "html-presentation", "static-web", "remotion",
        ],
        "visualization",
    ),
    (["humanize", "linkedin", "changelog", "content", "writing"], "content"),
    (["sql", "migration", "benchmark", "database"], "data"),
    (["ship", "release", "deploy", "adr", "api-docs", "engineering-retro"], "operations"),
    (
        [
            "debug", "test", "tdd", "gpu", "regex", "filesystem", "github",
            "agent-builder", "mcp", "prompt",
        ],
        "development",
    ),
]

TYPE_DEFAULT_CATEGORY: dict[str, str] = {
    "hook": "operations",
    "rule": "operations",
    "command": "development",
    "utility": "development",
    "preset": "operations",
}

VALID_CATEGORIES = {
    "development", "review", "security", "research", "content",
    "business", "visualization", "operations", "data",
}


def classify_category(name: str, description: str, pkg_type: str) -> str:
    """Determine category from package name and description."""
    haystack = f"{name} {description}".lower()
    for keywords, category in CATEGORY_PATTERNS:
        for kw in keywords:
            if kw in haystack:
                return category
    return TYPE_DEFAULT_CATEGORY.get(pkg_type, "development")


# ---------------------------------------------------------------------------
# Tag generation
# ---------------------------------------------------------------------------

TAG_RULES: dict[str, list[str]] = {
    # Skills
    "pr-review": ["code-review", "pull-request", "quality", "diff-analysis"],
    "code-refiner": ["refactoring", "code-quality", "simplification", "readability"],
    "pre-landing-review": ["pre-merge", "safety-gate", "code-review", "checklist"],
    "architecture-reviewer": ["architecture", "scalability", "enterprise", "security-audit"],
    "architecture-diagram": ["architecture", "diagram", "visualization", "svg"],
    "debug-investigator": ["debugging", "root-cause", "hypothesis", "bisect"],
    "test-harness": ["testing", "pytest", "test-generation", "python"],
    "sql-optimizer": ["sql", "performance", "database", "optimization"],
    "benchmark-runner": ["benchmarking", "performance", "comparison", "metrics"],
    "dependency-audit": ["dependencies", "vulnerabilities", "licenses", "supply-chain"],
    "migration-risk-analyzer": ["database", "migration", "ddl", "rollback"],
    "ship-workflow": ["release", "ci-cd", "pull-request", "changelog"],
    "changelog-composer": ["changelog", "release-notes", "git-history", "versioning"],
    "engineering-retro": ["retrospective", "velocity", "git-analysis", "sprint"],
    "adr-writer": ["architecture", "decision-record", "documentation", "adr"],
    "api-docs-generator": ["api", "documentation", "openapi", "fastapi"],
    "estimate-calibrator": ["estimation", "pert", "confidence-interval", "planning"],
    "task-decomposer": ["task-breakdown", "dependencies", "planning", "phased"],
    "plan-review": ["plan-audit", "scope", "risk-assessment", "assumptions"],
    "competitive-analyzer": ["competitive-analysis", "market", "porters-five-forces", "positioning"],
    "market-analyzer": ["market-sizing", "tam-sam-som", "trends", "industry"],
    "feasibility-assessor": ["feasibility", "unit-economics", "viability", "business-case"],
    "idea-validator": ["idea-validation", "lean-canvas", "jtbd", "swot"],
    "literature-review": ["academic", "literature", "synthesis", "citations"],
    "research-critique": ["research", "methodology", "claims-evidence", "peer-review"],
    "manuscript-review": ["manuscript", "pre-publication", "citation-hygiene", "submission"],
    "manuscript-provenance": ["provenance", "reproducibility", "computational", "verification"],
    "concept-to-image": ["image-generation", "html-to-png", "svg", "visual-design"],
    "animate": ["video", "manim", "animation", "explainer"],
    "remotion-video": ["video", "react", "remotion", "motion-graphics"],
    "html-presentation": ["slides", "presentation", "reveal-js", "html"],
    "static-web-artifacts-builder": ["html", "interactive", "dashboard", "svg"],
    "humanize": ["writing", "ai-detection", "natural-language", "rewriting"],
    "linkedin-post-style": ["linkedin", "social-media", "writing", "content"],
    "to-markdown": ["conversion", "markdown", "document-ingestion", "pdf"],
    "md-to-pdf": ["pdf", "markdown", "mermaid", "latex"],
    "gpu-optimizer": ["gpu", "cuda", "vram", "pytorch"],
    "filesystem": ["files", "directories", "search", "navigation"],
    "github": ["github", "cli", "issues", "pull-requests"],
    "agent-builder": ["agent-sdk", "headless", "automation", "mcp"],
    "mcp-to-skill": ["mcp", "skill-conversion", "context-optimization", "token-reduction"],
    "prompt-lab": ["prompt-engineering", "evaluation", "few-shot", "chain-of-thought"],
    "rag-auditor": ["rag", "retrieval", "hallucination", "grounding"],
    "repo-sentinel": ["security", "public-repo", "secret-scanning", "audit"],
    "qa-systematic": ["qa", "testing", "browser", "regression"],
    "tavily": ["web-search", "research", "real-time", "ai-optimized"],
    "web-fetch": ["http", "curl", "api", "web-content"],
    "lightpanda-browser": ["browser", "headless", "scraping", "lightweight"],
    "immune": ["memory", "error-detection", "antibodies", "adaptive"],
    "notebooklm": ["notebooklm", "podcast", "flashcards", "source-analysis"],
    "skill-library": ["armory", "catalog", "install", "package-management"],
    "package-evaluator": ["quality", "audit", "scoring", "frontmatter"],
    # Agents
    "code-reviewer": ["code-review", "quality", "severity-ranking", "sonnet"],
    "codebase-auditor": ["audit", "codebase", "quality", "sonnet"],
    "content-strategist": ["content", "strategy", "planning", "sonnet"],
    "full-stack-builder": ["full-stack", "implementation", "development", "opus"],
    "idea-scout": ["ideas", "research", "validation", "opus"],
    "media-producer": ["media", "production", "content", "sonnet"],
    "project-architect": ["architecture", "design", "planning", "opus"],
    "project-planner": ["planning", "decomposition", "estimation", "sonnet"],
    "proposal-writer": ["proposals", "writing", "business", "opus"],
    "release-captain": ["release", "deployment", "ci-cd", "sonnet"],
    "research-analyst": ["research", "analysis", "synthesis", "opus"],
    "secret-scanner": ["secrets", "scanning", "security", "haiku"],
    "security-reviewer": ["security", "review", "vulnerabilities", "sonnet"],
    "team-lead": ["orchestration", "delegation", "multi-agent", "opus"],
    "test-engineer": ["testing", "test-generation", "coverage", "haiku"],
    # Hooks
    "cost-tracker": ["cost", "tokens", "usage", "logging"],
    "git-protection": ["git", "branch-protection", "safety", "hooks"],
    "pre-edit-backup": ["backup", "files", "safety", "pre-edit"],
    # Rules
    "commit-standards": ["commits", "conventional", "git", "branch-naming"],
    "security-standards": ["security", "secrets", "input-validation", "authentication"],
    "test-standards": ["testing", "coverage", "pytest", "ci"],
    # Commands
    "refactor": ["refactoring", "code-quality", "simplification"],
    "security-scan": ["security", "scanning", "vulnerabilities", "audit"],
    "tdd": ["tdd", "testing", "red-green-refactor", "test-first"],
    # Utilities
    "arxiv-search": ["arxiv", "academic", "papers", "search"],
    "dependency-tree": ["dependencies", "tree", "analysis", "packages"],
    "test-coverage-report": ["coverage", "testing", "reports", "metrics"],
    # Presets
    "ai-builder": ["ai", "agent", "development", "toolkit"],
    "biz-validation": ["business", "validation", "market", "feasibility"],
    "content-ops": ["content", "writing", "publishing", "workflow"],
    "core": ["essential", "baseline", "review", "git"],
    "eng-ops": ["engineering", "operations", "ci-cd", "release"],
    "media-craft": ["media", "video", "visualization", "design"],
    "python-strict": ["python", "typing", "testing", "strict"],
    "research": ["research", "academic", "literature", "analysis"],
    "sec-strict": ["security", "scanning", "secrets", "strict"],
}


def generate_tags(name: str, pkg_type: str, meta: dict[str, Any]) -> list[str]:
    """Generate 3-6 tags for a package."""
    if name in TAG_RULES:
        return TAG_RULES[name]

    # Fallback: extract from name and description
    tags: list[str] = []

    # Add name parts as tags
    parts = name.split("-")
    for part in parts:
        if len(part) > 2:
            tags.append(part)

    # Add type-derived tag
    type_tags = {
        "skill": "skill",
        "agent": "agent",
        "hook": "hook",
        "rule": "rule",
        "command": "command",
        "utility": "utility",
        "preset": "preset",
    }
    if pkg_type in type_tags:
        tags.append(type_tags[pkg_type])

    # For agents, add model tag
    if pkg_type == "agent":
        model = meta.get("model", "")
        if model:
            tags.append(str(model))

    # Deduplicate and limit
    seen: set[str] = set()
    unique: list[str] = []
    for t in tags:
        t_lower = t.lower()
        if t_lower not in seen:
            seen.add(t_lower)
            unique.append(t_lower)
    return unique[:6]


# ---------------------------------------------------------------------------
# Difficulty assignment
# ---------------------------------------------------------------------------

BEGINNER_PACKAGES = {
    "filesystem", "web-fetch", "to-markdown",
    "tavily", "lightpanda-browser", "youtube-search", "arxiv-search",
    "commit-standards", "test-standards", "security-standards",
    "cost-tracker", "git-protection", "pre-edit-backup",
}

ADVANCED_PACKAGES = {
    "architecture-reviewer", "manuscript-review", "manuscript-provenance",
    "rag-auditor", "gpu-optimizer", "migration-risk-analyzer", "repo-sentinel",
    "competitive-analyzer", "idea-validator", "feasibility-assessor",
    "qa-systematic", "remotion-video", "animate",
    "project-architect", "team-lead", "security-reviewer", "research-analyst",
}


def classify_difficulty(name: str) -> str:
    """Assign difficulty level."""
    if name in BEGINNER_PACKAGES:
        return "beginner"
    if name in ADVANCED_PACKAGES:
        return "advanced"
    return "intermediate"


# ---------------------------------------------------------------------------
# File rewriting
# ---------------------------------------------------------------------------

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def rewrite_file(path: Path, pkg_type: str) -> dict[str, Any] | None:
    """Add tags/category/difficulty to a package definition file. Returns added fields or None."""
    content = path.read_text(encoding="utf-8")

    fm_match = FRONTMATTER_RE.match(content)
    if not fm_match:
        print(f"  SKIP {path.relative_to(REPO_ROOT)} — no frontmatter", file=sys.stderr)
        return None

    fm_raw = fm_match.group(1)
    body = content[fm_match.end():]

    data: dict[str, Any] = yaml.safe_load(fm_raw) or {}

    name = data.get("name", path.parent.name)
    description = data.get("description", "")

    # Ensure metadata dict exists
    if "metadata" not in data or not isinstance(data.get("metadata"), dict):
        data["metadata"] = {}

    meta = data["metadata"]
    added: dict[str, Any] = {}

    # Category
    if "category" not in meta:
        cat = classify_category(name, description, pkg_type)
        meta["category"] = cat
        added["category"] = cat

    # Tags
    if "tags" not in meta:
        tags = generate_tags(name, pkg_type, data)
        meta["tags"] = tags
        added["tags"] = tags

    # Difficulty
    if "difficulty" not in meta:
        diff = classify_difficulty(name)
        meta["difficulty"] = diff
        added["difficulty"] = diff

    if not added:
        return None

    # Reconstruct YAML frontmatter
    new_fm = yaml.dump(data, default_flow_style=None, sort_keys=False, allow_unicode=True)
    # Remove trailing newline from yaml.dump before closing ---
    new_fm = new_fm.rstrip("\n")

    new_content = f"---\n{new_fm}\n---\n{body}"
    path.write_text(new_content, encoding="utf-8")
    return added


def main() -> None:
    updated = 0

    for pkg_type_key, pkg_type in TYPES.items():
        repo_dir = pkg_type.repo_dir
        if not repo_dir.exists():
            continue

        for pkg_dir in sorted(repo_dir.iterdir()):
            if not pkg_dir.is_dir():
                continue
            if pkg_dir.name.startswith(".") or pkg_dir.name.startswith("_"):
                continue
            if pkg_dir.name == "evals":
                continue

            def_file = pkg_dir / pkg_type.definition_file
            if not def_file.exists():
                continue

            result = rewrite_file(def_file, pkg_type_key)
            if result is None:
                continue

            updated += 1
            rel = def_file.parent.relative_to(REPO_ROOT)
            parts: list[str] = []
            if "category" in result:
                parts.append(f"category: {result['category']}")
            if "tags" in result:
                parts.append(f"tags: {result['tags']}")
            if "difficulty" in result:
                parts.append(f"difficulty: {result['difficulty']}")
            print(f"Updated {rel} — {', '.join(parts)}")

    print(f"\nUpdated {updated} packages")


if __name__ == "__main__":
    main()
