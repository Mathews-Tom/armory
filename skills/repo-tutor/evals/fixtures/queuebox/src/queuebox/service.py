from __future__ import annotations

from queuebox.store import JsonJobStore
from queuebox.validators import validate_title


def submit_job(title: str) -> str:
    validate_title(title)
    return JsonJobStore().save({"title": title, "status": "queued"})
