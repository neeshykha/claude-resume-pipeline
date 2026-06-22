"""
pipeline/cleanup.py — Prune stale pipeline data after each daily run.

Rules:
  seen_jobs.json  — remove entries where applied=false AND last_seen_date >= 14 days ago.
                    Never touch applied=true entries (permanent application record).
  jobs_*.json     — delete daily snapshot files older than 14 days.
  run_*.json      — delete daily run log files older than 14 days.

Run with: .venv/bin/python pipeline/cleanup.py [--dry-run]
"""

import json
import sys
import os
from datetime import date, timedelta
from pathlib import Path

JOBS_DIR = Path("pipeline/jobs")
SEEN_JOBS = JOBS_DIR / "seen_jobs.json"
CUTOFF = date.today() - timedelta(days=14)
DRY_RUN = "--dry-run" in sys.argv


def main():
    pruned_jobs = prune_seen_jobs()
    pruned_files = prune_daily_files()

    print(f"cleanup.py complete (dry_run={DRY_RUN})")
    print(f"  seen_jobs.json: removed {pruned_jobs} stale unapplied entries")
    print(f"  daily files:    deleted {pruned_files} files older than {CUTOFF}")


def prune_seen_jobs():
    with open(SEEN_JOBS) as f:
        data = json.load(f)

    jobs = data["jobs"]
    before = len(jobs)
    kept = {}
    removed = []

    for key, entry in jobs.items():
        # Never prune applied entries — they're a permanent application record
        if entry.get("applied") is True:
            kept[key] = entry
            continue

        last_seen = entry.get("last_seen_date") or entry.get("first_seen_date", "")
        try:
            last_seen_date = date.fromisoformat(last_seen)
        except ValueError:
            kept[key] = entry
            continue

        if last_seen_date < CUTOFF:
            removed.append(f"    - {key} (last_seen={last_seen})")
        else:
            kept[key] = entry

    if removed:
        print(f"\n  Pruning {len(removed)} stale unapplied entries:")
        for r in removed:
            print(r)

    if not DRY_RUN and removed:
        data["jobs"] = kept
        with open(SEEN_JOBS, "w") as f:
            json.dump(data, f, indent=2)

    return len(removed)


def prune_daily_files():
    patterns = ["jobs_*.json", "run_*.json"]
    deleted = 0

    for pattern in patterns:
        for path in sorted(JOBS_DIR.glob(pattern)):
            # Extract date from filename: jobs_2026-06-01.json → 2026-06-01
            stem = path.stem  # e.g. "jobs_2026-06-01" or "run_2026-06-01"
            parts = stem.split("_", 1)
            if len(parts) < 2:
                continue
            date_str = parts[1][:10]  # take first 10 chars (YYYY-MM-DD)
            try:
                file_date = date.fromisoformat(date_str)
            except ValueError:
                continue

            if file_date < CUTOFF:
                print(f"    Deleting {path.name} (date={file_date})")
                if not DRY_RUN:
                    path.unlink()
                deleted += 1

    return deleted


if __name__ == "__main__":
    main()
