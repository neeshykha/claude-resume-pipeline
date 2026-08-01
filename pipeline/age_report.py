#!/usr/bin/env python3
"""Reports how long tailored-but-unsent roles have been sitting, and retires
the ones that are certainly dead.

Usage:
    .venv/bin/python pipeline/age_report.py                  # report only
    .venv/bin/python pipeline/age_report.py --apply          # retire stale rows
    .venv/bin/python pipeline/age_report.py --days 60        # custom threshold

Added 2026-08-01. The conversion audit found that `stage=surfaced` was
concealing a decay curve: 50 of the 76 dated surfaced rows were more than 14
days old, including 13 that scored >=100 (Google Product Support Manager at
121 and 31 days, Cresta AI Deployment Manager at 114 and 39 days, Observe.AI
Senior CSM at 111 and 94 days). SESSION_STATE's 2026-07-30 entry separately
documents three roles closing between poll time and JD-verification time the
same evening. Against that churn rate an old surfaced row is not a backlog
item, it is a dead posting, and counting it as pipeline output overstates what
the system is producing.

`--apply` sets stage=expired on surfaced rows older than the threshold.
Deliberately conservative:

  - Default threshold is 45 days, far past Step 0.5's 3-day confirmation
    window, so a row cannot be retired while its confirmation is still
    plausibly in flight.
  - Only stage=surfaced rows are ever touched. applied/rejected/closed and
    the blank-stage rows are left alone.
  - A row with no surfaced_date is never retired, because its age is unknown
    rather than large. Run backfill_surfaced_date.py first.
  - mark_outcome.py matches across ALL stages, so a late rejection still
    lands on a retired row correctly. Only mark_applied.py's promotion path
    (which looks at surfaced rows) stops considering it, which is the point.
"""
import csv
import os
import shutil
import sys
from collections import Counter
from datetime import date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTCOMES = os.path.join(SCRIPT_DIR, "outcomes.csv")
DEFAULT_DAYS = 45
BUCKETS = [(7, "0-7d"), (14, "8-14d"), (30, "15-30d"), (60, "31-60d")]


def parse_date(s):
    s = (s or "").strip()
    try:
        return date(*map(int, s.split("-")))
    except Exception:
        return None


def bucket_of(age):
    for limit, label in BUCKETS:
        if age <= limit:
            return label
    return "60d+"


def arg_days(argv):
    if "--days" in argv:
        try:
            return int(argv[argv.index("--days") + 1])
        except (IndexError, ValueError):
            print("--days needs an integer", file=sys.stderr)
            sys.exit(2)
    return DEFAULT_DAYS


def main():
    apply = "--apply" in sys.argv
    threshold = arg_days(sys.argv)
    today = date.today()

    with open(OUTCOMES, newline="", encoding="utf-8") as f:
        raw = list(csv.reader(f))
    header, rows = raw[0], raw[1:]
    try:
        ci = {n: header.index(n) for n in
              ("company", "title", "fit_score", "stage", "surfaced_date")}
    except ValueError:
        print("outcomes.csv is not on the current schema; run "
              "repair_outcomes.py --apply first", file=sys.stderr)
        return 2

    buckets, ages, stale, undated = Counter(), [], [], 0
    for r in rows:
        if len(r) != len(header) or r[ci["stage"]].strip() != "surfaced":
            continue
        d = parse_date(r[ci["surfaced_date"]])
        if not d:
            undated += 1
            continue
        age = (today - d).days
        ages.append(age)
        buckets[bucket_of(age)] += 1
        if age > threshold:
            stale.append((age, r))

    total = len(ages) + undated
    print(f"surfaced rows: {total}  (dated {len(ages)}, undated {undated})")
    if ages:
        ages.sort()
        print(f"median age: {ages[len(ages)//2]}d   oldest: {ages[-1]}d")
    print()
    for _, label in BUCKETS + [(None, "60d+")]:
        n = buckets[label]
        if n:
            print(f"  {label:<8} {n:>3}  {'#' * n}")
    if undated:
        print(f"  {'no date':<8} {undated:>3}  {'#' * undated}")

    def score(r):
        try:
            return float(r[ci["fit_score"]])
        except ValueError:
            return 0.0

    hi = sorted((x for x in stale if score(x[1]) >= 100),
                key=lambda x: -score(x[1]))
    if hi:
        print(f"\nscore >=100 and older than {threshold}d "
              f"({len(hi)} roles, near-certainly expired):")
        for age, r in hi[:15]:
            print(f"  {age:>4}d  {r[ci['fit_score']]:>4}  "
                  f"{r[ci['company']][:20]:<21} {r[ci['title']][:45]}")

    print(f"\nolder than {threshold}d and still stage=surfaced: {len(stale)}")

    if not apply:
        if stale:
            print("report only; re-run with --apply to set stage=expired")
        return 0
    if not stale:
        print("nothing to retire")
        return 0

    for _, r in stale:
        r[ci["stage"]] = "expired"

    shutil.copy2(OUTCOMES, OUTCOMES + ".preexpire.bak")
    tmp = OUTCOMES + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    os.replace(tmp, OUTCOMES)
    print(f"retired {len(stale)} rows to stage=expired; "
          f"backup at outcomes.csv.preexpire.bak")
    return 0


if __name__ == "__main__":
    sys.exit(main())
