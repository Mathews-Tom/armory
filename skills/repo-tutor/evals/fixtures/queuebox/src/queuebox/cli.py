from __future__ import annotations

import argparse

from queuebox.service import submit_job


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["submit"])
    parser.add_argument("title")
    args = parser.parse_args()
    job_id = submit_job(args.title)
    print(f"queued: {job_id}")
