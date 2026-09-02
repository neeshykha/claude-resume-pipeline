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
import datetime
import glob
import os
import re
import sys

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


def check(path):
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

    status = "FAIL" if problems else "ok  "
    print(f"[{status}] {name}")
    print(f"         contractions={len(contractions)} expanded={len(expanded)} "
          f"em-dashes={dashes} sentences={len(lengths)} in-band={band_pct:.0f}%")
    for p in problems:
        print(f"         - {p}")
    return not problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--today", action="store_true",
                    help="check every *_cover.md modified today")
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
    results = [check(p) for p in paths]
    ok = all(results)
    print()
    print("all clean" if ok else
          "FIX THE FAILURES ABOVE, then re-render the PDF and the _ATS variant.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
