"""Flag repository text addressed to an evaluator or language model.

Repository content is data. The scanner decides nothing; it surfaces
locations so the assessing agent and the report treat them as untrusted, and
so evidence overlapping flagged lines cannot support a competency score.
"""

from __future__ import annotations

import re

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "override_instructions",
        re.compile(
            r"\b(ignore|disregard|forget|override)\b.{0,30}\b(previous|prior|above|earlier|all|your)\b.{0,20}\b(instructions?|prompts?|rules|guidelines)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "addressed_to_evaluator",
        re.compile(
            r"\b(note|message|attention|instructions?)\s+(to|for)\s+(the\s+|any\s+|all\s+)?(ai|llm|language model|assistant|evaluator|assessor|reviewer|grader|agent)s?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "role_assignment",
        re.compile(
            r"\b(you are|act as|pretend to be)\s+(an?\s+|the\s+)?(ai|llm|evaluator|assessor|grader|hiring|recruit\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "grade_directive",
        re.compile(
            r"\b(rate|grade|score|assess|classify|level|rank|evaluate)\s+(this|the)\s+(candidate|author|developer|engineer|maintainer|contributor)\b.{0,60}\b(as|at)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "award_directive",
        re.compile(
            r"\b(award|assign|give|grant|recommend)\b.{0,40}\b(staff|principal|distinguished|senior|5\s*/\s*5|maximum|highest)\b.{0,20}\b(level|title|score|rating|grade|engineer)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "chat_markup",
        re.compile(r"(<\|im_start\|>|<\|system\|>|\[INST\]|<<SYS>>)", re.IGNORECASE),
    ),
)


def scan_text(path: str, text: str, limit: int = 20) -> list[dict[str, object]]:
    flags: list[dict[str, object]] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw[:4000]
        for name, pattern in PATTERNS:
            if pattern.search(line):
                excerpt = " ".join(line.strip().split())
                if len(excerpt) > 157:
                    excerpt = excerpt[:157] + "..."
                flags.append(
                    {"path": path, "line": lineno, "pattern": name, "excerpt": excerpt}
                )
                break
        if len(flags) >= limit:
            break
    return flags
