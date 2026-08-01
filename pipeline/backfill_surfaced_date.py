#!/usr/bin/env python3
"""One-time backfill of outcomes.csv's `surfaced_date` column.

Usage:
    .venv/bin/python pipeline/backfill_surfaced_date.py            # dry run
    .venv/bin/python pipeline/backfill_surfaced_date.py --apply    # writes

Added 2026-08-01 alongside the column itself. `surfaced_date` records when the
pipeline first saw a role. It exists because `applied_date` was doing two
different jobs depending on stage -- on a surfaced row it held the SURFACING
date, and mark_applied.py then overwrote it with the confirmation date on
promotion, destroying the only record of how long a role sat unsent.

Three sources, in descending order of trust:

  1. seen_jobs.json `first_seen_date`, matched by normalized URL. The poller
     has written this since the tracker began, so it is authoritative and
     survives promotion.
  2. seen_jobs.json `first_seen_date`, matched by company+title slug. Catches
     rows whose URL changed (reposts under a new req ID).
  3. The row's own `applied_date`, but ONLY for rows still at stage=surfaced,
     where that column provably still holds the surfacing date because
     mark_applied.py never touched it.

Rows matching none of the three are left blank rather than guessed: an applied
row with no seen_jobs entry has genuinely lost its surfacing date, and a wrong
date here would corrupt the aging report that age_report.py builds on it.

Idempotent: a row that already has a surfaced_date is never rewritten.
"""
import csv
import json
import os
import re
import shutil
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTCOMES = os.path.join(SCRIPT_DIR, "outcomes.csv")
SEEN_JOBS = os.path.join(SCRIPT_DIR, "jobs", "seen_jobs.json")


def slugify(text):
    """Mirror of poll_ats.slugify -- kept local so this script has no import
    dependency on the 74k-line poller just to read a date."""
    text = (text or "").lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def norm_url(u):
    return (u or "").strip().rstrip("/").lower()


def main():
    apply = "--apply" in sys.argv

    with open(SEEN_JOBS, encoding="utf-8") as f:
        jobs = json.load(f).get("jobs", {})

    by_url, by_title = {}, {}
    for key, j in jobs.items():
        first = (j.get("first_seen_date") or "").strip()
        if not first:
            continue
        u = norm_url(j.get("url"))
        if u:
            by_url.setdefault(u, first)
        # key is "<ats_slug>::<title_slug>"; the ats slug is not always the
        # company name, so index on the title half plus the company field.
        tslug = key.split("::", 1)[-1]
        by_title.setdefault((slugify(j.get("company")), tslug), first)

    with open(OUTCOMES, newline="", encoding="utf-8") as f:
        raw = list(csv.reader(f))
    header, rows = raw[0], raw[1:]
    try:
        ci = {n: header.index(n) for n in
              ("applied_date", "company", "title", "url", "stage",
               "surfaced_date")}
    except ValueError:
        print("outcomes.csv is not on the current schema; run "
              "repair_outcomes.py --apply first", file=sys.stderr)
        return 2

    stats = {"url": 0, "title": 0, "applied_date": 0, "already": 0, "blank": 0}
    unresolved = []

    for r in rows:
        if len(r) != len(header):
            continue
        if r[ci["surfaced_date"]].strip():
            stats["already"] += 1
            continue

        got = by_url.get(norm_url(r[ci["url"]]))
        src = "url"
        if not got:
            got = by_title.get((slugify(r[ci["company"]]),
                                slugify(r[ci["title"]])))
            src = "title"
        if not got and r[ci["stage"]].strip() == "surfaced":
            got = r[ci["applied_date"]].strip()
            src = "applied_date"

        if got:
            r[ci["surfaced_date"]] = got
            stats[src] += 1
        else:
            stats["blank"] += 1
            unresolved.append((r[ci["company"]], r[ci["title"]][:40],
                               r[ci["stage"]] or "(blank)"))

    total = sum(stats[k] for k in ("url", "title", "applied_date"))
    print(f"rows: {len(rows)}")
    print(f"  filled from seen_jobs URL match:      {stats['url']}")
    print(f"  filled from seen_jobs title match:    {stats['title']}")
    print(f"  filled from own applied_date:         {stats['applied_date']}")
    print(f"  already had a surfaced_date:          {stats['already']}")
    print(f"  left blank (unrecoverable):           {stats['blank']}")
    print(f"  TOTAL newly filled:                   {total}")

    if unresolved:
        print("\nunresolved (left blank on purpose, never guessed):")
        for co, ti, st in unresolved:
            print(f"  {st:<10} {co[:22]:<23} {ti}")

    if not apply:
        print("\ndry run; re-run with --apply to write")
        return 0
    if not total:
        print("nothing to backfill")
        return 0

    shutil.copy2(OUTCOMES, OUTCOMES + ".presurfaced.bak")
    tmp = OUTCOMES + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    os.replace(tmp, OUTCOMES)
    print(f"\nwrote {total} surfaced_date values; "
          f"backup at outcomes.csv.presurfaced.bak")
    return 0


if __name__ == "__main__":
    sys.exit(main())
