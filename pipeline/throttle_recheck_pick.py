#!/usr/bin/env python3
"""Pick the next rate-limited harvest rejections for a targeted re-probe.

Usage:
    .venv/bin/python pipeline/throttle_recheck_pick.py            # 10 names
    .venv/bin/python pipeline/throttle_recheck_pick.py -n 5

Writes pipeline/jobs/throttle_recheck_<date>.json (a JSON list of names) and
prints the path plus a one-line backlog summary. The run then feeds that file to
harvest_ats.py --names-file ... as a DRY RUN (Step 6.7). Read-only against
enrollment_candidates.json.

Why this exists (added 2026-09-24). harvest_ats.py writes a company whose
probes were refused with HTTP 429 as a rejection carrying throttled=true and
recheck_if_resurfaced=true. Nothing re-checked those unless the company turned
up again in a LinkedIn alert, so they accumulated: 94 parked in the four runs
from 2026-09-18 to 2026-09-24, every one of them a Workable refusal. They are
companies the discovery layer already paid to find.

How the rotation works (changed 2026-11-12). The pick used to be the ten
oldest by rejected_date, and it relied on the re-probe rewriting that date to
send a checked name to the back. The re-probe became a dry run on 2026-10-12,
a dry run writes nothing, and the same ten names were picked on every run
after that. The earlier pick files are the state now: a name is ordered by the
last day it was picked (never picked comes first), then by rejected_date, then
by name. So every parked name gets its turn, and a name that has had one waits
until the rest have. Today's own file is ignored, so a second call on the same
day returns the same names. If the pick files are ever cleared, the rotation
starts over from the oldest rejection, which is harmless.
"""
import argparse
import glob
import json
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
QUEUE = os.path.join(HERE, "enrollment_candidates.json")
JOBS = os.path.join(HERE, "jobs")
PREFIX = "throttle_recheck_"


def parked_records(queue: dict) -> list:
    """Rate-limited rejections still waiting on a re-probe."""
    return [r for r in queue.get("rejected", [])
            if r.get("throttled") and not r.get("superseded_by_enrollment")
            and r.get("name")]


def last_picked(jobs_dir: str, today: str) -> dict:
    """Lowercased name -> the latest day before `today` it was picked."""
    last = {}
    for path in glob.glob(os.path.join(jobs_dir, f"{PREFIX}*.json")):
        day = os.path.basename(path)[len(PREFIX):-len(".json")]
        if day >= today:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                names = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(names, list):
            continue
        for name in names:
            key = str(name).lower()
            if day > last.get(key, ""):
                last[key] = day
    return last


def pick(parked: list, last: dict, n: int) -> list:
    """The n names whose turn it is: never picked first, then longest since a pick."""
    ordered = sorted(parked, key=lambda r: (last.get(r["name"].lower(), ""),
                                            r.get("rejected_date") or "",
                                            r["name"].lower()))
    return [r["name"] for r in ordered[:n]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=10)
    args = ap.parse_args()

    with open(QUEUE, encoding="utf-8") as f:
        q = json.load(f)
    parked = parked_records(q)
    today = date.today().isoformat()
    last = last_picked(JOBS, today)
    names = pick(parked, last, args.n)

    out = os.path.join(JOBS, f"{PREFIX}{today}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(names, f, indent=1)
        f.write("\n")
    oldest = min((r.get("rejected_date") or "" for r in parked), default="none")
    never = sum(1 for r in parked if r["name"].lower() not in last)
    print(f"throttle backlog {len(parked)} (oldest {oldest}); picked {len(names)}; "
          f"never picked {never}")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
