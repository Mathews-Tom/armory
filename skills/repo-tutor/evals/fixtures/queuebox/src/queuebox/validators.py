from __future__ import annotations


def validate_title(title: str) -> None:
    if not title.strip():
        raise ValueError("job title must not be empty")
