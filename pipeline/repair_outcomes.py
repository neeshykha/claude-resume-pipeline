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

Canonical schema (14 columns as of 2026-08-21):
    applied_date,company,title,url,fit_score,jd_coverage_pct,stage,outcome,
    notes,source_channel,surfaced_date,unmet_hard_reqs,vendor_tool_named_in_jd,
    hard_req_cap_trigger

The last three were added 2026-08-01 after a conversion audit (see
SESSION_STATE 2026-08-01):

  surfaced_date            When the pipeline first surfaced the role. Exists
                           because `applied_date` was doing two jobs: on a
                           surfaced row it held the SURFACING date, and
                           mark_applied.py then OVERWROTE it with the
                           confirmation date on promotion, destroying the only
                           record of how long the role sat unsent. 66% of
                           dated surfaced rows are >14 days old and that decay
                           was invisible. Never overwritten once set.
  unmet_hard_reqs          Count of JD hard requirements that cannot be
                           honestly claimed. The intended replacement for
                           jd_coverage_pct as a readiness signal: coverage is
                           range-restricted by construction (85% of applied
                           rows sit at >=93%) because the tailoring loop
                           optimizes it to a target, so it cannot explain
                           outcome variation at any sample size. This one
                           varies, and it is what actually kills at screen.
  vendor_tool_named_in_jd  The incumbent AI/support tool the JD names, when it
                           names one (e.g. "Intercom/Fin", "Forethought AI").
                           Vanta rejected Aneesh at screen for lacking
                           Intercom/Fin despite 15/15 coverage. Recorded to
                           test whether vendor mismatch is a real pattern; at
                           n=2 it is a hypothesis, not a finding.

`hard_req_cap_trigger` was added 2026-08-21, from a finding by audit_scores.py.
The HARD-REQUIREMENT TIER CAP (daily_task_prompt.md Step 2c) demotes a role to
light tier when the JD states a years-minimum in a function Aneesh has zero
years in, or marks a requirement non-negotiable in its own words. `unmet_hard_reqs`
cannot express that: it counts EVERY disclosed gap, and most are soft ("no
fintech domain", "no Stripe billing experience"). So the audit could not tell a
correctly-capped row from a missed one and had to report all 10 as an unresolved
REVIEW queue rather than as findings. Vanta 2026-08-21 is the clean example --
2 unmet hard reqs AND full tailoring, entirely correct, because that JD states
no years minimum at all.

  hard_req_cap_trigger     Verbatim text of the requirement that fires the cap.
                           Three distinct states, deliberately -- `outcome=null`
                           already taught this tracker what happens when one
                           value means both "no" and "never recorded":
                             ""       not recorded (every row before 2026-08-21,
                                      and any run that skipped the check)
                             "none"   checked, nothing triggers the cap
                             <text>   the requirement, quoted from the JD, e.g.
                                      "5+ years in Data Governance or GTM Systems"
                           Empty is NOT "no cap". Backfilling the 219 pre-existing
                           rows would mean re-reading 219 JDs, so they stay empty
                           and audit_scores.py keeps falling back to reading the
                           notes for those.

`source_channel` records how the role reached Aneesh: "pipeline" (the daily
run surfaced it), "user_surfaced" (his own browsing, fed in by hand), "referral"
(an employee referral), or "linkedin" (a company that entered the watchlist via
the Step 1d-2 LinkedIn lead harvest). Added because the 2026-07-28 confirmation
backfill turned up a CodeRabbit application submitted through their Employee
Referral program, a channel the tracker had no way to represent and which
converts at a very different rate from cold ATS applications. The point of the
column is to make per-channel conversion comparable once enough outcomes land.

Recognized drifted shapes:

  O. LEGACY_V3: the 14-column schema in force 2026-08-21 to 2026-08-27
     -> widen with one empty trailing column (furthest_stage).

  N. LEGACY_V2: the 13-column schema in force 2026-08-01 to 2026-08-21
     -> widen with two empty trailing columns (hard_req_cap_trigger,
        furthest_stage).

  M. LEGACY_V1: the 10-column schema in force 2026-07-28 to 2026-08-01
     -> widen with three empty trailing columns. Told apart from the drifted
        10-column shapes below by column 9 holding a KNOWN_CHANNELS value
        rather than a file path, so this branch must be tested first.

  L. legacy 9-column canonical (pre-source_channel)
     -> append the default source_channel, then widen.

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
# Schema in force 2026-07-28 through 2026-08-01. Kept as a named constant
# because it is still a RECOGNIZED input shape, not just history: shape "M"
# below widens these rows, and the header check accepts a file still on it.
LEGACY_V1 = CORE + ["source_channel"]
# Schema in force 2026-08-01 through 2026-08-21. Also a recognized input shape:
# shape "N" widens these rows by one column.
LEGACY_V2 = LEGACY_V1 + ["surfaced_date", "unmet_hard_reqs",
                         "vendor_tool_named_in_jd"]
# Schema in force 2026-08-21 through 2026-08-27. Recognized input shape:
# shape "O" widens these rows by one column.
LEGACY_V3 = LEGACY_V2 + ["hard_req_cap_trigger"]
# Added 2026-08-27. `outcome` is a single TERMINAL-state column, so a role that
# reached an interview and was then rejected ends up reading `rejected` and the
# interview is erased. That made interview rate uncomputable from the schema:
# an audit that day found SIX interview-stage events of which only two showed in
# `outcome`, the other four surviving as free text in `notes`. This column
# records the furthest point a role ever reached and is never overwritten
# downward. Vocabulary in FURTHEST_STAGES below.
CANONICAL = LEGACY_V3 + ["furthest_stage"]
DEFAULT_CHANNEL = "pipeline"

# Ordered weakest to strongest. `furthest_stage` only ever moves right.
# EMPTY IS NOT "no interview" -- it means NOT RECORDED, and it is the correct
# value for the ~230 rows that predate this column. Same three-state rule as
# hard_req_cap_trigger: do not backfill by assumption, because "nobody checked"
# and "checked, never interviewed" are different facts and conflating them is
# exactly what made `outcome` useless here.
FURTHEST_STAGES = ["", "applied", "assessment", "interview", "onsite", "offer"]


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


def pad(row):
    """Widen a repaired row to full CANONICAL width with empty strings.

    Every classify() branch returns through here, so adding a column to
    CANONICAL never again requires touching the individual shape handlers.
    """
    return row + [""] * (len(CANONICAL) - len(row))


def classify(row):
    """Return (shape, repaired_row) or (None, None) if unrecognized.

    Repaired rows always come back at full CANONICAL width. A drifted
    10-column row and a LEGACY_V1 10-column row are told apart by column 9:
    in V1 it holds a channel from KNOWN_CHANNELS, whereas in the legacy
    'trailing PDF path' shape it holds a file path. That test is why the
    V1 branch must run BEFORE the 10-column shape handlers below.
    """
    # C is tested FIRST among the 10-column shapes. Its column 9 is often
    # empty, and "" is a member of KNOWN_CHANNELS, so the V1 branch below
    # would otherwise claim a shifted row and pad it instead of un-shifting
    # it. Guarded to width 10 so it can never touch a real 13-column row.
    if (len(row) == 10 and not row[0].strip() and not row[1].strip()
            and row[2].strip()):
        return "C", pad(row[1:] + [DEFAULT_CHANNEL])

    if len(row) == len(CANONICAL) and row[9].strip() in KNOWN_CHANNELS:
        return "ok", row
    if len(row) == len(LEGACY_V3) and row[9].strip() in KNOWN_CHANNELS:
        return "O", pad(row)
    if len(row) == len(LEGACY_V2) and row[9].strip() in KNOWN_CHANNELS:
        return "N", pad(row)
    if len(row) == len(LEGACY_V1) and row[9].strip() in KNOWN_CHANNELS:
        return "M", pad(row)
    if len(row) == len(CORE):
        return "L", pad(row + [DEFAULT_CHANNEL])
    if len(row) != 10:
        return None, None

    # A: url in its canonical position, trailing extra field
    if is_url(row[3]):
        repaired = row[:9]
        repaired[8] = merge_notes(repaired[8], row[9])
        return "A", pad(repaired + [DEFAULT_CHANNEL])

    # B: score where the url belongs, url shifted one right
    if is_num(row[3]) and is_url(row[4]):
        return "B", pad([
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
        ])
    return None, None


def main():
    apply = "--apply" in sys.argv
    with open(OUTCOMES, newline="", encoding="utf-8") as f:
        raw = list(csv.reader(f))
    header, rows = raw[0], raw[1:]
    if header not in (CANONICAL, LEGACY_V3, LEGACY_V2, LEGACY_V1, CORE):
        print(f"header is not a recognized schema: {header}", file=sys.stderr)
        return 2

    out = []
    counts = {"ok": 0, "A": 0, "B": 0, "C": 0, "L": 0, "M": 0, "N": 0, "O": 0}
    unknown = []
    for i, row in enumerate(rows, start=2):
        shape, repaired = classify(row)
        if shape is None:
            unknown.append((i, len(row), row[:4]))
            out.append(row)
            continue
        counts[shape] += 1
        out.append(repaired)

    total_fixed = (counts["A"] + counts["B"] + counts["C"] + counts["L"]
                   + counts["M"] + counts["N"] + counts["O"])
    print(f"rows: {len(rows)} | already canonical: {counts['ok']}")
    print(f"repairable: {total_fixed} "
          f"(A trailing-pdf: {counts['A']}, B transposed: {counts['B']}, "
          f"C shifted: {counts['C']}, L legacy-9col: {counts['L']}, "
          f"M widen-v1: {counts['M']}, N widen-v2: {counts['N']}, "
          f"O widen-v3: {counts['O']})")
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
