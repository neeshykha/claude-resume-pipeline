#!/usr/bin/env python3
"""Promotes outcomes.csv / seen_jobs.json rows from stage=surfaced to
stage=applied based on matched Gmail application-confirmation emails.

Usage:
    .venv/bin/python pipeline/mark_applied.py <confirmations.json>

<confirmations.json> is a small file Claude writes after searching Gmail for
`to:aneeshk10+jobs@gmail.com` confirmations and matching each one against
outcomes.csv rows that are still stage=surfaced. Schema:

{
  "confirmations": [
    {"url": "https://...", "company": "...", "applied_date": "2026-07-24"}
  ]
}

Matching is by URL first (exact, normalized: trailing slash + case stripped),
falling back to company name (case-insensitive) only among rows still
stage=surfaced. If a company name matches more than one surfaced row and no
URL was given to disambiguate, the row is SKIPPED and reported as ambiguous
-- never guessed. Always include the URL from the confirmation email body
when you can find it; only fall back to company-name-only matching when the
email genuinely doesn't state which requisition it's confirming.

Behavior:
- Rewrites outcomes.csv atomically (tmp + rename, keeps a .bak).
- For each matched row: overwrites applied_date with the confirmation's real
  date (the existing value in that column for stage=surfaced rows is when it
  was TAILORED, not applied -- a known schema wart; this call is what makes
  the column mean what it says again) and sets stage to "applied".
- Mirrors the same promotion into seen_jobs.json (applied=true, applied_date
  set) for any dedup_key whose URL matches, keeping both files consistent.
- Prints a summary: promoted / ambiguous (skipped) / not-found. Never
  silently guesses on an ambiguous match.
"""
import csv
import json
import os
import shutil
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTCOMES = os.path.join(SCRIPT_DIR, "outcomes.csv")
SEEN_JOBS = os.path.join(SCRIPT_DIR, "jobs", "seen_jobs.json")


def norm_url(u):
    return (u or "").rstrip("/").lower()


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: mark_applied.py <confirmations.json>", file=sys.stderr)
        return 2
    with open(sys.argv[1], encoding="utf-8") as f:
        data = json.load(f)
    confirmations = data.get("confirmations", [])
    if not confirmations:
        print("no confirmations in input file")
        return 0

    if not os.path.exists(OUTCOMES):
        print("outcomes.csv not found", file=sys.stderr)
        return 2
    # Read as raw rows (not DictReader) and match by column index. Some
    # historical rows in outcomes.csv have shifted/extra columns (documented
    # corruption, see SESSION_STATE 2026-07-20) that make DictReader choke on
    # write-back. Reading/writing by index lets malformed rows pass through
    # completely untouched instead of crashing or getting further mangled.
    with open(OUTCOMES, newline="", encoding="utf-8") as f:
        raw_rows = list(csv.reader(f))
    if not raw_rows:
        print("outcomes.csv is empty", file=sys.stderr)
        return 2
    header = raw_rows[0]
    try:
        col = {name: header.index(name) for name in
               ("applied_date", "company", "title", "url", "stage")}
    except ValueError:
        print("outcomes.csv header missing an expected column", file=sys.stderr)
        return 2
    data_rows = raw_rows[1:]

    def well_formed(row):
        return len(row) == len(header)

    promoted, ambiguous, not_found = [], [], []
    promoted_urls = []

    for c in confirmations:
        target_url = norm_url(c.get("url"))
        company = (c.get("company") or "").strip().lower()
        applied_date = c.get("applied_date", "")

        candidates = [r for r in data_rows if well_formed(r) and r[col["stage"]] == "surfaced"]
        matches = []
        if target_url:
            matches = [r for r in candidates if norm_url(r[col["url"]]) == target_url]
        if not matches and company:
            matches = [r for r in candidates if r[col["company"]].strip().lower() == company]

        if len(matches) == 1:
            row = matches[0]
            row[col["applied_date"]] = applied_date
            row[col["stage"]] = "applied"
            promoted.append((row[col["company"]], row[col["title"]]))
            promoted_urls.append(norm_url(row[col["url"]]))
        elif len(matches) > 1:
            ambiguous.append(c)
        else:
            not_found.append(c)

    if promoted:
        shutil.copy2(OUTCOMES, OUTCOMES + ".bak")
        tmp = OUTCOMES + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(data_rows)
        os.replace(tmp, OUTCOMES)

    # Mirror into seen_jobs.json by URL
    seen_touched = 0
    if promoted_urls and os.path.exists(SEEN_JOBS):
        with open(SEEN_JOBS, encoding="utf-8") as f:
            seen = json.load(f)
        jobs = seen.get("jobs", {})
        confirmed_by_url = {norm_url(c.get("url")): c.get("applied_date", "")
                             for c in confirmations if c.get("url")}
        for key, entry in jobs.items():
            u = norm_url(entry.get("url"))
            if u in promoted_urls and u in confirmed_by_url:
                entry["applied"] = True
                entry["applied_date"] = confirmed_by_url[u]
                seen_touched += 1
        if seen_touched:
            shutil.copy2(SEEN_JOBS, SEEN_JOBS + ".bak")
            tmp2 = SEEN_JOBS + ".tmp"
            with open(tmp2, "w", encoding="utf-8") as f:
                json.dump(seen, f, indent=2)
            os.replace(tmp2, SEEN_JOBS)

    print(f"outcomes.csv: {len(promoted)} promoted to stage=applied")
    for company, title in promoted:
        print(f"  {company} — {title}")
    print(f"seen_jobs.json: {seen_touched} entries flipped to applied=true")
    if ambiguous:
        print(f"AMBIGUOUS (skipped, multiple surfaced rows, no URL to disambiguate): {len(ambiguous)}")
        for c in ambiguous:
            print(f"  {c.get('company')}")
    if not_found:
        print(f"NOT FOUND (no matching surfaced row): {len(not_found)}")
        for c in not_found:
            print(f"  {c.get('company')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
