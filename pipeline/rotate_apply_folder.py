#!/usr/bin/env python3
"""Rotate the apply-now folder: keep only what Aneesh still has to send.

Usage:
    .venv/bin/python pipeline/rotate_apply_folder.py            # report only
    .venv/bin/python pipeline/rotate_apply_folder.py --apply    # actually move

WHY THIS EXISTS
---------------
`tailored/` holds 1,516 files (588 JSON, 487 PDF, 440 Markdown) as of 2026-08-28.
Opening an ATS upload dialog into it means picking a PDF out of a thousand-plus
files where `Aneesh_Khan_Outreach_PrincipalTAM.md` sorts directly next to the
`.pdf` of the same name. That is not a rare slip, it is a coin flip made several
times a week. `tailored/apply_now/` holds ONLY the PDFs of roles still waiting to
be sent, so the dialog opens on a short list of unambiguous files.

WHAT DECIDES EVICTION
---------------------
Two triggers, in this order:

1. STATE. The role's `outcomes.csv` row has left `surfaced` (applied, rejected,
   closed, expired). Step 0.5 already derives this from Gmail confirmations, so
   this is the real "he is done with it" signal rather than a guess.

2. AGE. The role was tailored more than APPLY_WINDOW_DAYS ago and is still
   sitting at `surfaced`.

Trigger 2 exists because trigger 1 alone does not converge. The post-epoch send
rate is 38% (34 of 89 surfaced rows), so roughly six in ten roles never leave
`surfaced` on their own. At a 45-day window that settles at ~134 PDFs, which
recreates the problem this folder exists to solve. At 7 days it settles around
25-34, which is one screen.

7 days rather than 14 because the costs are lopsided: eviction MOVES a file back
to `tailored/`, it never deletes, so a too-short window costs one extra
navigation on a rare occasion while a too-long window costs the entire point of
the folder.

DELIBERATELY NOT DONE: no longer window for high-scoring roles. A 116 ignored for
a week is something Aneesh should be TOLD about, not a file to keep around
longer. Hence `report_lines()` naming high scorers loudly; the digest carries
that line (daily_task_prompt.md Step 5).

Nothing is ever deleted, and an unmatched PDF is always KEPT and reported rather
than evicted on a guess.
"""
import argparse
import csv
import datetime
import os
import shutil
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(SCRIPT_DIR)
TAILORED = os.path.join(REPO, "tailored")
APPLY_DIR = os.path.join(TAILORED, "apply_now")
OUTCOMES = os.path.join(SCRIPT_DIR, "outcomes.csv")

APPLY_WINDOW_DAYS = 7
HIGH_SCORE = 100          # evictions at or above this are called out by name


def load_rows():
    if not os.path.exists(OUTCOMES):
        return []
    with open(OUTCOMES, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def resume_basename(pdf_name):
    """Map any PDF back to the resume filename its outcomes.csv row records.

    Cover letters are the reason this is not just the filename. Step 6 notes
    record the pair as "tailored/Aneesh_Khan_X.pdf + _cover.pdf" -- the cover is
    a shorthand suffix, not a full path -- so matching a cover PDF by its own
    basename finds nothing. Strip the suffix and match the resume instead.
    """
    stem = pdf_name[:-4] if pdf_name.lower().endswith(".pdf") else pdf_name
    if stem.endswith("_cover"):
        stem = stem[: -len("_cover")]
    return stem + ".pdf"


def find_row(rows, pdf_name):
    key = resume_basename(pdf_name)
    for r in rows:
        if key in (r.get("notes") or ""):
            return r
    return None


def parse_date(s):
    try:
        return datetime.date.fromisoformat((s or "").strip())
    except Exception:
        return None


def decide(row, pdf_path, today):
    """Return (evict: bool, reason: str)."""
    if row is None:
        return False, "no outcomes.csv row matched; keeping (never evict on a guess)"

    stage = (row.get("stage") or "").strip().lower()
    if stage and stage != "surfaced":
        return True, f"stage={stage}"

    surfaced = parse_date(row.get("surfaced_date")) or parse_date(row.get("applied_date"))
    if surfaced is None:
        # No usable date on the row: fall back to when the PDF was written.
        try:
            mtime = datetime.date.fromtimestamp(os.path.getmtime(pdf_path))
        except OSError:
            return False, "no date on row and file mtime unreadable; keeping"
        surfaced = mtime
        basis = "file mtime"
    else:
        basis = "surfaced_date"

    age = (today - surfaced).days
    if age > APPLY_WINDOW_DAYS:
        return True, f"still surfaced after {age}d (>{APPLY_WINDOW_DAYS}d, by {basis})"
    return False, f"surfaced {age}d ago"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="actually move files; default is a report")
    ap.add_argument("--window", type=int, default=APPLY_WINDOW_DAYS,
                    help=f"days before an unsent role is evicted (default {APPLY_WINDOW_DAYS})")
    args = ap.parse_args()

    globals()["APPLY_WINDOW_DAYS"] = args.window

    os.makedirs(APPLY_DIR, exist_ok=True)
    today = datetime.date.today()
    rows = load_rows()

    pdfs = sorted(f for f in os.listdir(APPLY_DIR) if f.lower().endswith(".pdf"))
    if not pdfs:
        print(f"apply_now/ is empty (window {APPLY_WINDOW_DAYS}d)")
        return 0

    evict, keep = [], []
    for name in pdfs:
        path = os.path.join(APPLY_DIR, name)
        row = find_row(rows, name)
        should, why = decide(row, path, today)
        (evict if should else keep).append((name, row, why))

    print(f"apply_now/: {len(pdfs)} PDFs | keeping {len(keep)}, evicting {len(evict)} "
          f"(window {APPLY_WINDOW_DAYS}d)")

    if keep:
        print("\n  KEEP")
        for name, row, why in keep:
            co = (row or {}).get("company", "?")
            print(f"    {name:58} {co[:18]:18} {why}")

    if evict:
        print("\n  EVICT -> tailored/")
        for name, row, why in evict:
            co = (row or {}).get("company", "?")
            print(f"    {name:58} {co[:18]:18} {why}")

    # The digest line. Unsent evictions are the ones worth reporting; a role
    # leaving because it was actually applied to is housekeeping.
    unsent = [(n, r, w) for n, r, w in evict if "still surfaced" in w]
    if unsent:
        roles = {}
        for name, row, _ in unsent:
            key = resume_basename(name)
            if key not in roles:
                roles[key] = row
        print("\n  DIGEST LINE:")
        loud = []
        for row in roles.values():
            if not row:
                continue
            try:
                if int(row.get("fit_score") or 0) >= HIGH_SCORE:
                    loud.append(f"{row.get('company')} {row.get('title')} "
                                f"({row.get('fit_score')})")
            except ValueError:
                pass
        msg = (f"    Evicted {len(roles)} role(s) from apply_now/ tailored "
               f">{APPLY_WINDOW_DAYS}d ago and never sent.")
        if loud:
            msg += " Scored >=%d: %s." % (HIGH_SCORE, "; ".join(loud))
        print(msg)

    if not args.apply:
        print("\nreport only; re-run with --apply to move")
        return 0

    moved = 0
    for name, _, _ in evict:
        src, dst = os.path.join(APPLY_DIR, name), os.path.join(TAILORED, name)
        if os.path.exists(dst):
            os.remove(src)          # already archived; drop the duplicate
        else:
            shutil.move(src, dst)
        moved += 1
    print(f"\nmoved {moved} PDF(s) back to tailored/ (nothing deleted)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
