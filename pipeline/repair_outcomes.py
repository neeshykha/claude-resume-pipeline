#!/usr/bin/env python3
"""Repairs outcomes.csv rows written under older, drifted column schemas.

Usage:
    .venv/bin/python pipeline/repair_outcomes.py            # dry run, reports only
    .venv/bin/python pipeline/repair_outcomes.py --apply    # rewrites the file

Why this exists: outcomes.csv accumulated three incompatible row shapes over
time. Malformed rows are not a cosmetic problem -- mark_applied.py skips any
row whose column count differs from the header (its `well_formed` guard), so
every drifted row is permanently invisible to the application-confirmation
promotion path. An audit on 2026-07-28 found 47 of 149 rows (32%) in this
state, which meant a third of the tracker could never be promoted no matter
how well the Gmail confirmation loop worked.

Canonical schema (10 columns as of 2026-07-28):
    applied_date,company,title,url,fit_score,jd_coverage_pct,stage,outcome,
    notes,source_channel

`source_channel` records how the role reached Aneesh: "pipeline" (the daily
run surfaced it), "user_surfaced" (his own browsing, fed in by hand), "referral"
(an employee referral), or "linkedin" (a company that entered the watchlist via
the Step 1d-2 LinkedIn lead harvest). Added because the 2026-07-28 confirmation
backfill turned up a CodeRabbit application submitted through their Employee
Referral program, a channel the tracker had no way to represent and which
converts at a very different rate from cold ATS applications. The point of the
column is to make per-channel conversion comparable once enough outcomes land.

Recognized drifted shapes:

  L. legacy 9-column canonical (pre-source_channel)
     -> append the default source_channel.

  A. canonical + trailing PDF path
     date, company, title, url, score, coverage, stage, outcome, notes, pdf
     -> fold column 9 into notes, drop it.

  B. score/url transposed, PDF path in position 5
     date, company, title, score, url, pdf, _, _, _, notes
     -> reorder to canonical; fold the PDF path into notes.

  C. right-shifted by one leading empty field
     "", "", company, title, url, score, coverage, stage, outcome
     -> drop one leading empty field.

Anything that matches none of these is left untouched and reported, so an
unrecognized shape can never be silently mangled further. Well-formed rows
pass through byte-identical, making the script safe to re-run.
"""
import csv
import os
import shutil
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTCOMES = os.path.join(SCRIPT_DIR, "outcomes.csv")

CORE = ["applied_date", "company", "title", "url", "fit_score",
        "jd_coverage_pct", "stage", "outcome", "notes"]
CANONICAL = CORE + ["source_channel"]
DEFAULT_CHANNEL = "pipeline"


def is_url(v):
    return v.strip().lower().startswith("http")


def is_num(v):
    return v.strip().isdigit()


def merge_notes(notes, pdf):
    notes, pdf = notes.strip(), pdf.strip()
    if not pdf:
        return notes
    if not notes:
        return pdf
    return f"{notes}; {pdf}"


KNOWN_CHANNELS = {"", "pipeline", "user_surfaced", "referral", "linkedin"}


def classify(row):
    """Return (shape, repaired_row) or (None, None) if unrecognized.

    Repaired rows always come back at full CANONICAL width. A drifted
    10-column row and a current 10-column row are told apart by column 9:
    in the current schema it holds a channel from KNOWN_CHANNELS, whereas in
    the legacy 'trailing PDF path' shape it holds a file path.
    """
    if len(row) == len(CANONICAL) and row[9].strip() in KNOWN_CHANNELS:
        return "ok", row
    if len(row) == len(CORE):
        return "L", row + [DEFAULT_CHANNEL]
    if len(row) != 10:
        return None, None

    # C: two leading empties with a real company in position 2
    if not row[0].strip() and not row[1].strip() and row[2].strip():
        return "C", row[1:] + [DEFAULT_CHANNEL]

    # A: url in its canonical position, trailing extra field
    if is_url(row[3]):
        repaired = row[:9]
        repaired[8] = merge_notes(repaired[8], row[9])
        return "A", repaired + [DEFAULT_CHANNEL]

    # B: score where the url belongs, url shifted one right
    if is_num(row[3]) and is_url(row[4]):
        return "B", [
            row[0],              # applied_date
            row[1],              # company
            row[2],              # title
            row[4],              # url
            row[3],              # fit_score
            row[6],              # jd_coverage_pct (usually empty in this shape)
            row[7],              # stage
            row[8],              # outcome
            merge_notes(row[9], row[5]),
            DEFAULT_CHANNEL,
        ]
    return None, None


def main():
    apply = "--apply" in sys.argv
    with open(OUTCOMES, newline="", encoding="utf-8") as f:
        raw = list(csv.reader(f))
    header, rows = raw[0], raw[1:]
    if header not in (CANONICAL, CORE):
        print(f"header is not a recognized schema: {header}", file=sys.stderr)
        return 2

    out, counts, unknown = [], {"ok": 0, "A": 0, "B": 0, "C": 0, "L": 0}, []
    for i, row in enumerate(rows, start=2):
        shape, repaired = classify(row)
        if shape is None:
            unknown.append((i, len(row), row[:4]))
            out.append(row)
            continue
        counts[shape] += 1
        out.append(repaired)

    total_fixed = counts["A"] + counts["B"] + counts["C"] + counts["L"]
    print(f"rows: {len(rows)} | already canonical: {counts['ok']}")
    print(f"repairable: {total_fixed} "
          f"(A trailing-pdf: {counts['A']}, B transposed: {counts['B']}, "
          f"C shifted: {counts['C']}, L legacy-9col: {counts['L']})")
    if unknown:
        print(f"UNRECOGNIZED, left untouched: {len(unknown)}")
        for ln, n, head in unknown:
            print(f"  line {ln}: {n} cols :: {head}")

    if not apply:
        print("\ndry run; re-run with --apply to write")
        return 0
    if not total_fixed:
        print("nothing to repair")
        return 0

    shutil.copy2(OUTCOMES, OUTCOMES + ".prerepair.bak")
    tmp = OUTCOMES + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CANONICAL)
        w.writerows(out)
    os.replace(tmp, OUTCOMES)
    print(f"\nrepaired {total_fixed} rows; backup at outcomes.csv.prerepair.bak")
    return 0


if __name__ == "__main__":
    sys.exit(main())
