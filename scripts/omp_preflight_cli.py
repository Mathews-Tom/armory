#!/usr/bin/env python3
"""Run one explicitly authorized local preflight sentinel; never a live OMP cell."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.omp_preflight import synthetic_sentinel


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-sentinel", action="store_true", required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--declaration", type=Path, required=True)
    args = parser.parse_args(argv)
    result = synthetic_sentinel(args.config, args.declaration)
    print(json.dumps(result, sort_keys=True))
    if result["status"] == "terminal-receipt-unavailable":
        return 0
    return 0 if result["status"] == "blocked" and result["managedSpawns"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
