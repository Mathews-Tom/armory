from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4


class JsonJobStore:
    def save(self, job: dict[str, str]) -> str:
        job_id = uuid4().hex
        Path(f"{job_id}.json").write_text(json.dumps(job), encoding="utf-8")
        return job_id
