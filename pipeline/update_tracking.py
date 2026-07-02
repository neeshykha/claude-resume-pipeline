#!/usr/bin/env python3
"""Deterministic tracking-file updater for the daily pipeline (Step 6).

Replaces hand-editing of seen_jobs.json / seen_urls.json / outcomes.csv with
Read+Write tools, which (a) burns tokens re-writing a 140KB+ JSON file and
(b) caused the 2026-06-30 corruption where entries were written outside the
top-level "jobs" object and broke poll_ats.py dedup.

Usage:
    .venv/bin/python pipeline/update_tracking.py <track_file.json> [--touch-reseen <ats_hits.json>]

<track_file.json> is a small per-run file Claude writes with this schema:
{
  "run_date": "2026-07-01",
  "jobs": [
    {
      "dedup_key": "cresta::ai-deployment-manager",
      "company": "Cresta",
      "title": "AI Deployment Manager",
      "url": "https://...",
      "score": 103,
      "jd_coverage_pct": 100,        // optional
      "notes": ""                     // optional
    }
  ]
}

Behavior:
- seen_jobs.json: adds new entries under the top-level "jobs" object
  (applied=false, outcome=null). For existing dedup_keys, updates
  last_seen_date ONLY — never clobbers first_seen_date/applied/outcome/notes.
- seen_urls.json: appends new URLs, dedupes, keeps last 500.
- outcomes.csv: appends one row per NEW job using the canonical header
  (applied_date,company,title,url,fit_score,jd_coverage_pct,stage,outcome,notes)
  with stage=surfaced and empty outcome. Skips rows whose URL already exists.
- --touch-reseen: reads the ats_hits file's reseen_keys array and bumps
  last_seen_date on those seen_jobs entries.
- Writes seen_jobs.json atomically (tmp file + rename) and keeps a .bak of
  the previous version.
"""
import argparse
import csv
import json
import os
import shutil
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SEEN_JOBS = os.path.join(SCRIPT_DIR, "jobs", "seen_jobs.json")
SEEN_URLS = os.path.join(SCRIPT_DIR, "jobs", "seen_urls.json")
OUTCOMES = os.path.join(SCRIPT_DIR, "outcomes.csv")
OUTCOMES_HEADER = ["applied_date", "company", "title", "url", "fit_score",
                   "jd_coverage_pct", "stage", "outcome", "notes"]


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def atomic_write_json(path, data):
    if os.path.exists(path):
        shutil.copy2(path, path + ".bak")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("track_file")
    ap.add_argument("--touch-reseen", metavar="ATS_HITS_JSON", default=None)
    args = ap.parse_args()

    track = load_json(args.track_file, None)
    if not track or "jobs" not in track or "run_date" not in track:
        print("track file must contain run_date and jobs[]", file=sys.stderr)
        return 2
    run_date = track["run_date"]

    seen = load_json(SEEN_JOBS, {"jobs": {}})
    if "jobs" not in seen or not isinstance(seen["jobs"], dict):
        print("seen_jobs.json malformed: missing top-level 'jobs' object", file=sys.stderr)
        return 2
    jobs = seen["jobs"]
    # Sanity: warn about any stray top-level keys (the 2026-06-30 bug class)
    strays = [k for k in seen if k not in ("jobs", "schema_version", "description")]
    if strays:
        print(f"WARNING: stray top-level keys in seen_jobs.json: {strays}", file=sys.stderr)

    added, touched = [], []
    for j in track["jobs"]:
        key = j["dedup_key"]
        if key in jobs:
            jobs[key]["last_seen_date"] = run_date
            touched.append(key)
        else:
            jobs[key] = {
                "company": j["company"],
                "title": j["title"],
                "url": j.get("url", ""),
                "first_seen_date": run_date,
                "last_seen_date": run_date,
                "score": j.get("score"),
                "applied": False,
                "outcome": None,
            }
            if j.get("notes"):
                jobs[key]["notes"] = j["notes"]
            added.append(key)

    reseen_touched = 0
    if args.touch_reseen:
        hits = load_json(args.touch_reseen, {})
        for key in hits.get("reseen_keys", []):
            if key in jobs:
                jobs[key]["last_seen_date"] = run_date
                reseen_touched += 1

    atomic_write_json(SEEN_JOBS, seen)

    # seen_urls.json
    urls = load_json(SEEN_URLS, [])
    known = {u.rstrip("/").lower() for u in urls}
    new_urls = 0
    for j in track["jobs"]:
        u = (j.get("url") or "").rstrip("/")
        if u and u.lower() not in known:
            urls.append(u)
            known.add(u.lower())
            new_urls += 1
    atomic_write_json(SEEN_URLS, urls[-500:])

    # outcomes.csv — append rows for NEW jobs only (skip URLs already present)
    existing_urls = set()
    file_exists = os.path.exists(OUTCOMES)
    if file_exists:
        with open(OUTCOMES, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing_urls.add((row.get("url") or "").rstrip("/").lower())
    appended = 0
    with open(OUTCOMES, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not file_exists:
            w.writerow(OUTCOMES_HEADER)
        added_set = set(added)
        for j in track["jobs"]:
            if j["dedup_key"] not in added_set:
                continue  # re-touched entry, already tracked in outcomes.csv
            u = (j.get("url") or "").rstrip("/").lower()
            if u and u in existing_urls:
                continue
            w.writerow([run_date, j["company"], j["title"], j.get("url", ""),
                        j.get("score", ""), j.get("jd_coverage_pct", ""),
                        "surfaced", "", j.get("notes", "")])
            appended += 1

    print(f"seen_jobs: +{len(added)} new, {len(touched)} re-touched, "
          f"{reseen_touched} reseen-touched (total {len(jobs)})")
    print(f"seen_urls: +{new_urls} new")
    print(f"outcomes.csv: +{appended} rows")
    for k in added:
        print(f"  added: {k}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
