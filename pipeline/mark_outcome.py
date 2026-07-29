#!/usr/bin/env python3
"""Records real application OUTCOMES into outcomes.csv.

Usage:
    .venv/bin/python pipeline/mark_outcome.py <outcomes.json>

Companion to mark_applied.py. That script answers "did he apply?"; this one
answers "what happened?" -- rejection, interview, offer. Until 2026-07-28 the
pipeline had no way to record the latter at all, so `outcome` was empty on
every row and the company-cap logic had to fall back on an age-out heuristic
to guess whether a silent application was dead.

Input schema:

{
  "outcomes": [
    {
      "company": "Harvey",
      "title": "User Operations Manager",     # optional substring match
      "url": "https://...",                   # optional, matched first
      "stage": "rejected",                    # optional, defaults per outcome
      "outcome": "rejected",
      "outcome_date": "2026-07-15",           # optional
      "notes": "role filled",                 # optional, appended to notes
      "source_channel": "pipeline",           # optional, only used on append
      "title_exact": false,                   # optional; require an exact
                                              # title match instead of a
                                              # substring, for when one req's
                                              # title is a prefix of another's
      "append_if_missing": true               # optional, default false
    }
  ]
}

Matching: URL first (exact, normalized), then company + optional title
substring, across ALL rows regardless of stage -- an outcome can land on a row
that was never promoted to applied. A company/title pair matching more than one
row is SKIPPED and reported, never guessed.

`append_if_missing` exists for applications the tracker never saw: roles applied
to before the pipeline covered them, or found through channels it cannot poll.
Appended rows carry stage/outcome from the input and a note recording that they
came from a confirmation backfill rather than a pipeline run.
"""
import csv
import json
import os
import shutil
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTCOMES = os.path.join(SCRIPT_DIR, "outcomes.csv")

# Terminal outcomes imply the application is closed; interview implies it is
# still live. Used only to default `stage` when the caller omits it.
STAGE_DEFAULTS = {
    "rejected": "rejected",
    "closed": "closed",
    "offer": "offer",
    "interview": "interview",
    "pending": "applied",
}


def norm_url(u):
    return (u or "").rstrip("/").lower()


def merge_notes(existing, addition):
    existing, addition = (existing or "").strip(), (addition or "").strip()
    if not addition:
        return existing
    if not existing:
        return addition
    if addition in existing:
        return existing
    return f"{existing}; {addition}"


def main():
    if len(sys.argv) != 2:
        print("usage: mark_outcome.py <outcomes.json>", file=sys.stderr)
        return 2
    with open(sys.argv[1], encoding="utf-8") as f:
        entries = json.load(f).get("outcomes", [])
    if not entries:
        print("no outcomes in input file")
        return 0

    with open(OUTCOMES, newline="", encoding="utf-8") as f:
        raw = list(csv.reader(f))
    header, rows = raw[0], raw[1:]
    try:
        ci = {n: header.index(n) for n in
              ("applied_date", "company", "title", "url", "stage", "outcome",
               "notes", "source_channel")}
    except ValueError:
        print("outcomes.csv is not on the current schema; run "
              "repair_outcomes.py --apply first", file=sys.stderr)
        return 2

    def well_formed(r):
        return len(r) == len(header)

    updated, appended, ambiguous, missing = [], [], [], []

    for e in entries:
        company = (e.get("company") or "").strip()
        title = (e.get("title") or "").strip()
        url = norm_url(e.get("url"))
        outcome = (e.get("outcome") or "").strip()
        stage = (e.get("stage") or STAGE_DEFAULTS.get(outcome, "")).strip()

        candidates = [r for r in rows if well_formed(r)]
        matches = []
        if url:
            matches = [r for r in candidates if norm_url(r[ci["url"]]) == url]
        if not matches and company:
            matches = [r for r in candidates
                       if r[ci["company"]].strip().lower() == company.lower()]
            # A supplied title is a REQUIREMENT, not a tie-breaker. Filtering
            # only when several rows matched would let a company with exactly
            # one row absorb an outcome meant for a different req there --
            # which is how an Arize "AI Product Manager" rejection landed on
            # their "AI Solutions Manager, SMB" row on the first backfill run.
            if title:
                if e.get("title_exact"):
                    matches = [r for r in matches
                               if r[ci["title"]].strip().lower() == title.lower()]
                else:
                    matches = [r for r in matches
                               if title.lower() in r[ci["title"]].lower()]

        if len(matches) == 1:
            r = matches[0]
            r[ci["outcome"]] = outcome
            if stage:
                r[ci["stage"]] = stage
            if e.get("outcome_date"):
                r[ci["notes"]] = merge_notes(
                    r[ci["notes"]], f"outcome {e['outcome_date']}")
            r[ci["notes"]] = merge_notes(r[ci["notes"]], e.get("notes"))
            if e.get("source_channel"):
                r[ci["source_channel"]] = e["source_channel"]
            updated.append((r[ci["company"]], r[ci["title"]], outcome))
        elif len(matches) > 1:
            ambiguous.append((company, title, len(matches)))
        elif e.get("append_if_missing"):
            new = [""] * len(header)
            new[ci["applied_date"]] = e.get("applied_date", "")
            new[ci["company"]] = company
            new[ci["title"]] = title
            new[ci["url"]] = e.get("url", "")
            new[ci["stage"]] = stage or "applied"
            new[ci["outcome"]] = outcome
            new[ci["notes"]] = merge_notes(
                e.get("notes"), "added by confirmation backfill")
            new[ci["source_channel"]] = e.get("source_channel", "pipeline")
            rows.append(new)
            appended.append((company, title, outcome))
        else:
            missing.append((company, title))

    if updated or appended:
        shutil.copy2(OUTCOMES, OUTCOMES + ".bak")
        tmp = OUTCOMES + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)
        os.replace(tmp, OUTCOMES)

    print(f"updated {len(updated)} existing rows")
    for c, t, o in updated:
        print(f"  {c} / {t} -> {o}")
    print(f"appended {len(appended)} new rows")
    for c, t, o in appended:
        print(f"  {c} / {t} -> {o}")
    if ambiguous:
        print(f"AMBIGUOUS, skipped ({len(ambiguous)}):")
        for c, t, n in ambiguous:
            print(f"  {c} / {t or '(no title given)'} matched {n} rows")
    if missing:
        print(f"NO MATCH and append_if_missing not set ({len(missing)}):")
        for c, t in missing:
            print(f"  {c} / {t}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
