#!/usr/bin/env python3
"""Pick the oldest rate-limited harvest rejections for a targeted re-probe.

Usage:
    .venv/bin/python pipeline/throttle_recheck_pick.py            # 10 names
    .venv/bin/python pipeline/throttle_recheck_pick.py -n 5

Writes pipeline/jobs/throttle_recheck_<date>.json (a JSON list of names) and
prints the path plus a one-line backlog summary. The run then feeds that file to
harvest_ats.py --names-file ... --apply. Read-only against
enrollment_candidates.json; harvest_ats.py's supersede logic replaces each old
record with whatever the re-probe finds (enrolled, a real rejection, or a fresh
throttled record dated today, which sends it to the back of this queue).

Why this exists (added 2026-09-24). harvest_ats.py writes a company whose
probes were refused with HTTP 429 as a rejection carrying throttled=true and
recheck_if_resurfaced=true. Nothing re-checked those unless the company turned
up again in a LinkedIn alert, so they accumulated: 94 parked in the four runs
from 2026-09-18 to 2026-09-24, every one of them a Workable refusal. They are
companies the discovery layer already paid to find. Oldest-first rotation plus
the re-probe rewriting rejected_date means every parked name comes round again
without any attempt counter.
"""
import argparse
import json
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
QUEUE = os.path.join(HERE, "enrollment_candidates.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=10)
    args = ap.parse_args()

    with open(QUEUE, encoding="utf-8") as f:
        q = json.load(f)
    parked = [r for r in q.get("rejected", [])
              if r.get("throttled") and not r.get("superseded_by_enrollment")
              and r.get("name")]
    parked.sort(key=lambda r: (r.get("rejected_date") or "", r["name"].lower()))
    names = [r["name"] for r in parked[:args.n]]

    today = date.today().isoformat()
    out = os.path.join(HERE, "jobs", f"throttle_recheck_{today}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(names, f, indent=1)
        f.write("\n")
    oldest = parked[0].get("rejected_date") if parked else "none"
    print(f"throttle backlog {len(parked)} (oldest {oldest}); picked {len(names)}")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
