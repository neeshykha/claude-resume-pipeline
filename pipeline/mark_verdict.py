#!/usr/bin/env python3
"""Records Aneesh's own verdict on a tailored role in outcomes.csv -> his_verdict.

Usage:
    .venv/bin/python pipeline/mark_verdict.py "<company>" <verdict> [--title "<fragment>"] [--note "<text>"]
    .venv/bin/python pipeline/mark_verdict.py --todo      # post-epoch rows with no verdict yet

Verdicts (repair_outcomes.HIS_VERDICTS):
    sent_as_is      sent the materials without changes
    sent_edited     sent, but had to fix the resume or letter first
    skip_fit        passed: the role itself was wrong (scoring problem)
    skip_materials  passed: the role was fine, the materials weren't (tailoring problem)
    skip_time       passed: no time, nothing wrong with either
    skip_other      passed for another reason; say which with --note

Why this exists (2026-09-30): the pipeline aims high on purpose, so interview
rate alone can't say whether it's working, and ~58% of tailored roles were going
unsent with nothing recording why. This column is the only place the pipeline
hears his judgment of a pick. pipeline_quality.py reads it.

Matching follows mark_outcome.py: company is matched case-insensitively; when
more than one row matches, --title (substring) must narrow it to exactly one, or
nothing is written and the candidates are printed. It never guesses. The file is
copied to outcomes.csv.bak before every write.
"""
import argparse
import csv
import os
import shutil
import sys

from repair_outcomes import HIS_VERDICTS

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTCOMES = os.path.join(SCRIPT_DIR, "outcomes.csv")
EPOCH = "2026-07-28"


def load(path):
    with open(path, newline="", encoding="utf-8") as f:
        raw = list(csv.reader(f))
    header = raw[0]
    if "his_verdict" not in header:
        sys.exit("outcomes.csv has no his_verdict column; run repair_outcomes.py --apply first")
    return header, raw[1:]


def find(header, rows, company, title):
    ci = {n: header.index(n) for n in ("company", "title")}
    wf = [r for r in rows if len(r) == len(header)]
    m = [r for r in wf if r[ci["company"]].strip().lower() == company.strip().lower()]
    if not m:
        m = [r for r in wf if company.strip().lower() in r[ci["company"]].lower()]
    if title:
        m = [r for r in m if title.lower() in r[ci["title"]].lower()]
    return m


def todo(header, rows):
    ci = {n: header.index(n) for n in ("surfaced_date", "company", "title", "stage", "fit_score", "his_verdict")}
    out = [r for r in rows if len(r) == len(header)
           and (r[ci["surfaced_date"]] or "") >= EPOCH and not r[ci["his_verdict"]].strip()]
    out.sort(key=lambda r: r[ci["surfaced_date"]])
    for r in out:
        print(f"{r[ci['surfaced_date']]}  {r[ci['stage']]:<10} {r[ci['fit_score']]:>4}  "
              f"{r[ci['company']]}: {r[ci['title']]}")
    print(f"\n{len(out)} post-epoch rows without a verdict")


def main(argv=None, path=OUTCOMES):
    ap = argparse.ArgumentParser()
    ap.add_argument("company", nargs="?")
    ap.add_argument("verdict", nargs="?")
    ap.add_argument("--title", default="")
    ap.add_argument("--note", default="")
    ap.add_argument("--todo", action="store_true")
    a = ap.parse_args(argv)

    header, rows = load(path)
    if a.todo:
        todo(header, rows)
        return 0
    if not a.company or not a.verdict:
        ap.error("company and verdict are required (or use --todo)")
    if a.verdict not in HIS_VERDICTS or not a.verdict:
        ap.error(f"verdict must be one of: {', '.join(v for v in HIS_VERDICTS if v)}")

    matches = find(header, rows, a.company, a.title)
    ci = {n: header.index(n) for n in ("company", "title", "stage", "notes", "his_verdict")}
    if len(matches) != 1:
        print(f"{len(matches)} rows match; nothing written.", file=sys.stderr)
        for r in matches:
            print(f"  {r[ci['company']]}: {r[ci['title']]} [{r[ci['stage']]}]", file=sys.stderr)
        if matches:
            print("Narrow it with --title \"<fragment>\".", file=sys.stderr)
        return 1

    r = matches[0]
    old = r[ci["his_verdict"]]
    r[ci["his_verdict"]] = a.verdict
    if a.note:
        note = f"verdict: {a.note}"
        r[ci["notes"]] = f"{r[ci['notes']]}; {note}" if r[ci["notes"]].strip() else note

    shutil.copy2(path, path + ".bak")
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    os.replace(tmp, path)
    was = f" (was {old})" if old else ""
    print(f"{r[ci['company']]}: {r[ci['title']]} -> {a.verdict}{was}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
