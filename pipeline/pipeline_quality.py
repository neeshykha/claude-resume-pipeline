#!/usr/bin/env python3
"""Is the pipeline getting better? A read-only report over outcomes.csv.

Usage:
    .venv/bin/python pipeline/pipeline_quality.py [--since YYYY-MM-DD]

Built 2026-09-30 from Aneesh's question of how to judge the pipeline when the
strategy is to aim high. Interview rate alone can't answer it: a low rate can
mean bad picks or ambitious ones. So this splits the question in three:

  1. Are the picks the ones he'd choose?    send rate + his_verdict skip reasons
  2. Are the materials good enough to send?  sent_as_is vs sent_edited
  3. Is aiming high getting traction?        advance rate split by stretch level

plus a monthly trend of what gets tailored (score, pay, reach share), so "aim
high" can be checked as a behavior rather than taken as a label.

Only rows with surfaced_date on or after the 2026-07-28 outcome-data epoch are
counted (CLAUDE.md: older applied rows are self-reported and unfalsifiable).
Samples are small; every rate prints its n. Writes nothing.
"""
import argparse
import csv
import os
import re
import statistics
from collections import Counter, defaultdict

from mark_verdict import VERDICT_SINCE

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTCOMES = os.path.join(SCRIPT_DIR, "outcomes.csv")
EPOCH = "2026-07-28"

# stage values that mean the application went out
SENT_STAGES = {"applied", "assessment", "interview", "onsite", "offer", "rejected", "closed"}
ADVANCED = {"assessment", "interview", "onsite", "offer"}
PAY_RE = re.compile(r"\$(\d{2,3})(?:,\d{3}|K)\s*[-–]\s*\$?(\d{2,3})(?:,\d{3}|K)", re.I)


def stretch(r):
    """fit / reach / unrecorded, from the two readiness columns.

    reach = the hard-requirement cap fired, or 2+ unmet hard requirements.
    unrecorded = both columns blank (rows before 2026-08-21 mostly).
    """
    u = (r.get("unmet_hard_reqs") or "").strip()
    cap = (r.get("hard_req_cap_trigger") or "").strip()
    if not u and not cap:
        return "unrecorded"
    if cap not in ("", "none") or (u.isdigit() and int(u) >= 2):
        return "reach"
    return "fit"


def is_sent(r):
    return r["stage"].strip() in SENT_STAGES or (r.get("his_verdict") or "").startswith("sent")


def advanced(r):
    return (r.get("furthest_stage") or "").strip() in ADVANCED or r["outcome"].strip() in ADVANCED


def pay_mid(notes):
    m = PAY_RE.search(notes or "")
    if not m:
        return None
    return (int(m.group(1)) + int(m.group(2))) / 2


def pct(a, b):
    return f"{a}/{b} ({100 * a / b:.0f}%)" if b else f"{a}/0"


def load(path, since):
    with open(path, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if (r.get("surfaced_date") or "") >= since]


def report(rows):
    lines = []
    out = lines.append
    sent = [r for r in rows if is_sent(r)]
    open_ = [r for r in rows if r["stage"].strip() == "surfaced"]
    expired = [r for r in rows if r["stage"].strip() == "expired"]
    out(f"Tailored: {len(rows)} | sent: {pct(len(sent), len(rows))} | still open: {len(open_)} | expired unsent: {len(expired)}")

    out(f"\n1-2. His verdicts (the judgment signal; rows surfaced {VERDICT_SINCE} onward)")
    asked = [r for r in rows if (r.get("surfaced_date") or "") >= VERDICT_SINCE]
    v = Counter((r.get("his_verdict") or "").strip() or "(not recorded)" for r in asked)
    recorded = sum(n for k, n in v.items() if k != "(not recorded)")
    for k, n in sorted(v.items(), key=lambda kv: -kv[1]):
        out(f"  {k:<16} {n}")
    skips = {k: n for k, n in v.items() if k.startswith("skip_")}
    sends = {k: n for k, n in v.items() if k.startswith("sent_")}
    if recorded:
        if skips:
            out(f"  skip_fit share of skips:       {pct(skips.get('skip_fit', 0), sum(skips.values()))}  (high = scoring problem)")
            out(f"  skip_materials share of skips: {pct(skips.get('skip_materials', 0), sum(skips.values()))}  (high = tailoring problem)")
        if sends:
            out(f"  sent without edits:            {pct(sends.get('sent_as_is', 0), sum(sends.values()))}")
    else:
        out("  none recorded yet: set them with mark_verdict.py (--todo lists what's missing)")

    out("\n3. Traction by stretch level (sent roles only)")
    for b in ("fit", "reach", "unrecorded"):
        grp = [r for r in sent if stretch(r) == b]
        adv = [r for r in grp if advanced(r)]
        out(f"  {b:<11} advanced {pct(len(adv), len(grp))}")
    out("  reach = hard-req cap fired or 2+ unmet hard reqs. Zero reach advances over ~40 sends")
    out("  means the ceiling is too high or the materials can't carry a reach; verdicts say which.")

    out("\nAim-high trend (what gets tailored, by month surfaced)")
    out("  month    n  sent  med_score  score>=110  med_pay_mid  reach_share")
    by_m = defaultdict(list)
    for r in rows:
        by_m[r["surfaced_date"][:7]].append(r)
    for m in sorted(by_m):
        g = by_m[m]
        scores = [int(r["fit_score"]) for r in g if r["fit_score"].strip().isdigit()]
        pays = [p for p in (pay_mid(r["notes"]) for r in g) if p]
        known = [r for r in g if stretch(r) != "unrecorded"]
        out(f"  {m}  {len(g):>3}  {sum(is_sent(r) for r in g):>4}  "
            f"{(statistics.median(scores) if scores else 0):>9.0f}  "
            f"{sum(s >= 110 for s in scores):>10}  "
            f"{('$%.0fK' % statistics.median(pays)) if pays else '   n/a':>11}  "
            f"{(pct(sum(stretch(r) == 'reach' for r in known), len(known)) if known else 'n/a'):>11}")
    out("  pay is parsed from notes where a range was recorded; months with few rows are noise.")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=EPOCH)
    a = ap.parse_args()
    if a.since < EPOCH:
        print(f"note: rows before {EPOCH} are self-reported; including them anyway because --since asked\n")
    print(report(load(OUTCOMES, a.since)))


if __name__ == "__main__":
    main()
