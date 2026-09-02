#!/usr/bin/env python3
"""Mechanical voice checks for a cover letter, before it gets rendered.

Usage:
    .venv/bin/python pipeline/check_voice.py tailored/Aneesh_Khan_X_cover.md
    .venv/bin/python pipeline/check_voice.py --today        # every letter dated today

WHY THIS EXISTS
---------------
The avoid-ai-writing skill audits prose well, but it is a judgment pass that has
to be remembered. The three findings below are arithmetic, so they belong in a
script that fails loudly instead of a habit that decays.

Added 2026-09-01 after that skill audited the Brown & Brown letter and found a
drift that had gone unnoticed across a whole day of output:

  CONTRACTIONS. Aneesh's voice profile says "contractions by default", and his
  own historical letters back it: Vanta AI Optimization 14, Zocdoc 15,
  WitnessAI 13, Zendesk 11, each with ZERO expanded forms. Every letter written
  on 2026-08-28 inverted that. Brown & Brown was the extreme at 0 contractions
  against 13 expansions ("I have never", "I did not", "does not make me",
  "If I am reporting", "is not a logistics problem"). Nothing in any single
  sentence looks wrong, which is exactly why it survived six letters: the tell
  is the aggregate, and only counting finds it.

Not a style opinion. A letter that reads a register stiffer than the man who
signs it is a worse letter, and this is the cheapest possible way to catch it.
"""
import argparse
import csv
import datetime
import glob
import os
import re
import sys

OUTCOMES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outcomes.csv")

# Stages that mean the letter has already gone out. A letter in one of these is
# a RECORD of what was sent, not a draft.
SENT_STAGES = {"applied", "rejected", "closed", "expired", "interview",
               "assessment", "onsite", "offer"}


def stage_of(cover_path):
    """Return the outcomes.csv stage for a cover letter, or None if unmatched.

    Matches the same way rotate_apply_folder.py does: Step 6 notes record the
    pair as "tailored/X.pdf + _cover.pdf", so a cover is found by stripping
    _cover and looking for the resume filename.
    """
    stem = os.path.basename(cover_path)
    for suffix in ("_cover.md", "_cover_data.json", "_cover.pdf"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    key = stem + ".pdf"
    try:
        with open(OUTCOMES, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if key in (row.get("notes") or ""):
                    return (row.get("stage") or "").strip().lower()
    except OSError:
        return None
    return None

CONTRACTION = re.compile(
    r"\b\w+n't\b|\b(?:I'm|I've|I'd|I'll|it's|that's|you're|you've|you'd|"
    r"they're|we're|we've|there's|here's|what's|who's|let's|isn't)\b", re.I)

# Expanded forms with a natural contraction. "I have" is included only in its
# auxiliary sense; possessive-ish uses are rare enough in a cover letter that
# the false-positive cost is lower than missing the drift.
EXPANDED = re.compile(
    r"\b(?:do not|did not|does not|is not|was not|were not|are not|has not|"
    r"have not|had not|cannot|can not|will not|would not|should not|could not|"
    r"I am|I have|I would|I will|it is|that is|you are|they are|we are|"
    r"there is|here is|what is|let us)\b")

EM_DASH_MAX = 2          # CLAUDE.md hard cap per document
BAND_LO, BAND_HI = 15, 25   # the "robotic" sentence-length band


def sentences(text):
    body = re.sub(r"^\s*(?:[A-Z][a-z]+ \d{1,2}, \d{4}|Hiring Team|Best,|Warmly,|Aneesh Khan)\s*$",
                  "", text, flags=re.M)
    parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+", body) if s.strip()]
    return [p for p in parts if len(p.split()) > 2]


def check(path, drafted_now=False):
    text = open(path, encoding="utf-8").read()
    name = os.path.basename(path)
    contractions = CONTRACTION.findall(text)
    expanded = EXPANDED.findall(text)
    dashes = text.count("—")
    sents = sentences(text)
    lengths = [len(s.split()) for s in sents]
    in_band = sum(1 for n in lengths if BAND_LO <= n <= BAND_HI)
    band_pct = (100.0 * in_band / len(lengths)) if lengths else 0.0

    problems = []
    # The ratio, not the raw count, is the signal: a short letter legitimately
    # has few of either.
    if len(expanded) > len(contractions):
        problems.append(
            f"CONTRACTIONS: {len(contractions)} contracted vs {len(expanded)} expanded. "
            f"His profile says contractions by default and his own letters run 5-15 "
            f"with zero expansions. Expand only for deliberate emphasis. "
            f"Found: {sorted(set(expanded))[:6]}")
    if dashes > EM_DASH_MAX:
        problems.append(f"EM DASHES: {dashes} (cap is {EM_DASH_MAX})")
    if lengths and band_pct > 60:
        problems.append(
            f"RHYTHM: {band_pct:.0f}% of sentences are {BAND_LO}-{BAND_HI} words "
            f"({in_band}/{len(lengths)}). Over 60% reads metronomic; break it with a "
            f"short one.")

    # STAGE GATE. A letter whose role has left `surfaced` has already been sent,
    # and the file is the record of what was sent. Editing it makes the archive
    # disagree with what the employer read, which is the same class of mistake as
    # a tracker column that means two things: later, nobody can tell which
    # version went out. Added 2026-09-01 after the contraction fix was applied to
    # six letters, four of which had already been submitted (Outreach, Baseten,
    # and Seven AI applied; Paylocity already rejected). Report, never edit.
    stage = stage_of(path)
    sent = stage in SENT_STAGES

    # `surfaced` DOES NOT MEAN UNSENT. It means no confirmation has been matched,
    # and confirmations arrive only through the Gmail +jobs forwarding filter,
    # which has documented capture gaps (the 2026-08-27 Datadog invitation came
    # from a personal recruiter domain and missed all three filters) and a lag of
    # hours to days besides. Proven 2026-09-01: CodePath and Cursor both read
    # `surfaced` and Aneesh had already sent both.
    #
    # A file-mtime heuristic was tried first and is also wrong. Several runs
    # happen per day now, so "modified today" caught letters an earlier run wrote
    # and Aneesh sent hours later: Cursor was written 08:59 and sent before this
    # check existed. Only the caller knows which letters IT just authored, so
    # that assertion is passed in rather than guessed. Step 4.5 passes explicit
    # paths with --drafted-now; a bare --today run is a REPORT and greenlights
    # nothing.
    editable = drafted_now and not sent

    if sent:
        status = "sent"
    elif not editable:
        status = "ASK "
    elif problems:
        status = "FAIL"
    else:
        status = "ok  "
    # Note "no row" is the NORMAL state for a letter this run just wrote: Step
    # 4.5 runs before Step 6 writes tracking. It is only alarming on a letter the
    # run did not author, which is what the --drafted-now assertion separates.
    if sent:
        stage_note = f"  [stage={stage}]"
    elif editable:
        stage_note = f"  [drafted this run{', ' + stage if stage else ''}]"
    else:
        stage_note = (f"  [stage={stage or 'no row'} "
                      f"- SENT STATUS UNKNOWN, not written by this run]")
    print(f"[{status}] {name}{stage_note}")
    print(f"         contractions={len(contractions)} expanded={len(expanded)} "
          f"em-dashes={dashes} sentences={len(lengths)} in-band={band_pct:.0f}%")
    for p in problems:
        print(f"         - {p}")
    if sent and problems:
        print("         ^ ALREADY SENT. Do not edit: this file is the record of "
              "what the employer read. Carry the finding into the next letter instead.")
    elif not editable and problems:
        print("         ^ ASK ANEESH BEFORE EDITING. 'surfaced' only means no "
              "confirmation was matched, not that it went unsent.")
    # A sent letter never fails: nothing is actionable, the text already went out.
    # Everything else with a problem fails, INCLUDING an ASK row -- asking Aneesh
    # is itself the required action, and a silent pass would hide it.
    return sent or not problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--today", action="store_true",
                    help="REPORT on every *_cover.md modified today. Greenlights "
                         "nothing: use --drafted-now for letters this run wrote.")
    ap.add_argument("--drafted-now", action="store_true",
                    help="assert the listed files were authored by the current run, "
                         "so they cannot have been sent yet and are safe to edit")
    args = ap.parse_args()

    paths = list(args.files)
    if args.today:
        today = datetime.date.today()
        for f in sorted(glob.glob("tailored/*_cover.md")):
            if datetime.date.fromtimestamp(os.path.getmtime(f)) == today:
                paths.append(f)
    if not paths:
        print("no cover letters to check")
        return 0

    # Evaluate every file before reducing: all() over a generator short-circuits
    # on the first failure, which silently skips the rest of the batch.
    results = [check(p, drafted_now=args.drafted_now) for p in paths]
    ok = all(results)
    print()
    if ok:
        print("all clean")
    else:
        print("FIX THE FAILURES ABOVE, then re-render the PDF and the _ATS variant.")
        print("ASK rows are NOT yours to edit without checking with Aneesh first.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
